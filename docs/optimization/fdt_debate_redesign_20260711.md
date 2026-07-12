# FDT 辩论流水线重新设计 · Diff 对比报告

> 状态：✅ **已实施并验证通过**（2026-07-11 19:05，掌柜"改"授权）。6 项改造（B/D/E/G/C/F）全落地，并额外修复 2 个真实架构问题（config.settings 阈值位置漂移、phase3 KeyError:slice 真根因）。详见各 § 实施记录与 FDT `memory/changelog.md`。
> 生成：2026-07-11 18:52 · 基于本轮盘后自动化执行暴露的问题。

---

## 0. 本次会话前置已完成（非本次 redesign 范围）

| 项 | 改动 | 位置 |
|----|------|------|
| 周末门控迁移 | `rrule` → `FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=20;BYMINUTE=15`（仅工作日）。**坑**：调度器忽略 `WEEKLY;BYDAY`，`BYMINUTE=15` 被解析成 `:10`（5分钟偏移，已知残留） | 自动化 `automation-1783403060853` |
| 数据基准规则 | Prompt 删步骤0周末门控；新增「📊 数据基准规则」：手动/即时执行以扫描时刻最新行情为准，禁回溯上一收盘；报告须标数据基准时间戳 | 同上 automation prompt |

---

## 1. 现状核查（纠正本轮误判，均有代码证据）

| 项 | 本轮误判 | 真实现状（代码证据） |
|----|----------|--------------------------|
| **B 编排入口** | "debate_orchestrator.py 不存在" | **存在** `skills/futures-trading-analysis/scripts/debate_orchestrator.py`。是**被动**门禁/校验脚手架：`DebatePhaseGate`（阶段门禁）、`wait_and_check()`（轮询+校验+返回 RETRY 信号）、`degrade_judge()`（D06降级）。**不 spawn Agent**——spawn 是团队主管（WorkBuddy Agent）的固有职责，Python 脚本也 spawn 不了 WorkBuddy 子 Agent。 |
| **C 报告生成器** | "phase3 与子集辩论不兼容" | `phase3_generate_report.py` **已有 `--debate` 模式**：L33 `add_argument("--debate")`，L61 `DEBATE_PATH = args.debate or ... debate_results.json`，L1449 `build_debate_report()`，L1924 `html_debate = build_debate_report()`。本轮 `exit=1` 是**因未传 `--debate`**，脚本默认找全量 `intermediate_data.json` 才报错。脚本本身兼容子集。 |
| **G 数据基准** | "报告缺数据基准时间戳" | 模板**已有**该字段：L1669 `<span class="label">数据基准</span> {intermediate.get("data_benchmark","")}`；L1944 `data_benchmark: intermediate.get("data_benchmark","")`。子集 `--debate` 模式需确保 `debate_results.json` 自带 `data_benchmark` 且 `build_debate_report` 优先读它。 |
| **F 置信度** | "置信度数值化未端到端强制" | `validate_agent_output.py` **已接受 0-1 数值或受控标签(高/中/低) 并归一化**（`confidence_utils` 单一来源，L26-60 导入/兜底），任意裸字符串被拒（L164-185 `is_valid_confidence` 校验）。本轮我"归一化"属冗余。 |
| **D 知识萃取** | 正确 | `extract_knowledge.py` CLI 仅 `ingest` 逐品种 `--pro/--con/--judge/--plan`，**无 `--from debate_results.json` 批量模式**（L690-717）。 |
| **E 扫描噪声** | "扫描假突破率过高" | 部分属实。`channel_breakout_strategy.py` 已有量能评分（L407-427 独立 +/-10 调整），但**量能是独立加减分、非突破有效前置门**——低量突破仍授 `break_base_score`（L142-165）。62 品种中 51 个被 P0-4 重校验门降级为 NOISE，说明突破判定对量能不敏感。 |

---

## 2. 改造项清单（按真实范围）

### 2.1 [B] 新增主动驱动层 `scripts/run_debate.py`（中·主优化）

**现状**：编排器被动；每轮 Lead 手工 spawn 24 个 Agent + 手工 poll 文件就绪 + 手工 L1 校验 + 手工组装 `debate_results.json` + 手工逐品种 `extract_knowledge` + 手工（或误用手写）报告。易碎、且踩"零胶水代码"红线。

**设计**：新增 `FDT/scripts/run_debate.py`，入参 = 扫描 JSON + 触发品种列表，负责【非 spawn】全链路：
1. 识别触发品种（STRONG/WATCH，`|total| >= DEBATE_ENTRY_MIN_ABS`）
2. 产出**标准化 spawn 计划 JSON**（哪些 Agent、哪些 prompt 注入点、哪些文件路径、ADX 角色反转规则）——Lead 按此计划 spawn（spawn 仍是 Lead 固有职责，但计划标准化、不再 ad-hoc）
3. 收口：`poll_file_ready`（复用 `DebatePhaseGate.wait_and_check`）+ L1 校验
4. 组装 `debate_results.json`（含 `data_benchmark`）
5. `extract_knowledge ingst --from`（见 2.2 批量）
6. `phase3_generate_report.py --debate`（见 2.4/2.5）

**效果**：把"易碎手工多步"（poll/校验/组装/萃取/报告）收敛进一个脚本；spawn 是唯一保留的 Lead 手工步骤（架构不可回避）。

**Diff**：新增文件，不覆盖现有。`debate_orchestrator.py` 继续作为被动门禁被 `run_debate.py` 调用，**不动**。

---

### 2.2 [D] `extract_knowledge.py` 增 `--from` 批量模式（小·实代码）

**现状**：`ingest` 需逐品种 4 个文件路径参数。

**设计**：新增 `batch_from_debate_results(json_path)` + CLI `ingest --from debate_results.json`；内部读 `verdicts`，过滤 `conf >= MIN_CONFIDENCE(0.6)`，逐个调现有 `extract_from_debate`（复用其全部逻辑，**不重复**），不传 `--bypass`（质量门控天然生效）。

**Diff（CLI 段 ~L690 新增分支）**：
```python
    elif cmd == "ingest_from":
        import argparse, json
        ap = argparse.ArgumentParser()
        ap.add_argument("--from", required=True, help="debate_results.json 路径")
        ap.add_argument("--bypass", action="store_true")
        a = ap.parse_args(sys.argv[2:])
        dr = json.load(open(a.from, encoding="utf-8"))
        for sym, v in dr.get("verdicts", {}).items():
            rec = {
                "round_id": dr.get("round_id", ""),
                "symbol": sym,
                "pro_args": v.get("bull_args", []),
                "con_args": v.get("bear_args", []),
                "signal_type": v.get("signal_type", ""),
                "volatility": {
                    "adx": v.get("adx"), "atr": v.get("atr")
                },
            }
            r = extractor.extract_from_debate(
                variety=sym.lower(),
                debate_record=rec,
                verdict={
                    "direction": v.get("direction"),
                    "confidence": v.get("confidence"),
                    "winner": v.get("winner", ""),
                    "reasoning": v.get("reasoning", ""),
                },
                trading_plan=v.get("trading_plan"),
                bypass_quality_gate=a.bypass,
            )
            print(f"  {sym}: {json.dumps(r, ensure_ascii=False)}")
```

**验证**：用本轮 `2026-07-11/debate_results.json` 跑，预期 ZN/RM（conf 0.70/0.65）入库，J/JD（conf 0.52）因 <0.6 自动跳过。

---

### 2.3 [E] `channel_breakout_strategy.py` 增量能确认前置（小·实代码）

**现状**（L142-165 DC20 突破评分；L411-425 量能独立评分）：量能是独立 +/-10 调整，**非突破有效前置**；低量突破仍授 `break_base_score`，可直达 STRONG/WATCH 触发辩论。

**设计**：仅当 `vol_ratio >= normal_lower_ratio` 时才授予 DC20 突破 base 分；否则该突破降级（记 `near_breakout` 弱信号、不授 base 分），避免无量伪突破直达信号等级。

**Diff（插入 L142 `if dc20_break == "up":` 之后，量能块 L411 之前）**：
```python
            # ── A1 量能确认前置（E 修复：无量突破不得授 base 分）──
            _vol_ok = True
            if volume and df is not None and len(df) > _r("volume", "ma_period", sym, chain_name, period):
                avg_vol_20 = df["volume"].iloc[-_r("volume", "ma_period", sym, chain_name, period):].mean()
                vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 1.0
                _vol_ok = vol_ratio >= _r("volume", "normal_lower_ratio", sym, chain_name, period)
            if not _vol_ok:
                dc_detail["volume_confirm"] = "weak_no_base"
                dc20_score += _r("dc20", "break_weak_no_vol_score", sym, chain_name, period)  # 负数/近0
                dc_detail["dc20_break_strength"] = "weak_no_vol"
                # 跳过下方 break_strong/moderate_bonus 分支（不授 base 分）
            else:
                # ── 原有 break_base_score + distance/pos 加分逻辑（保持不动）──
                dc20_score += _r("dc20", "break_base_score", sym, chain_name, period)
                dc_detail["dc20_direction"] = "up"
                if dc20_upper and price:
                    distance_pct = (price / dc20_upper - 1) * 100
                    ...  # 原有 distance/pos 分支保持
```
（`dc20_break == "down"` 分支镜像处理）

**配套**：`config/settings.py` `CHANNEL_BREAKOUT_CONFIG.volume` 增 `normal_lower_ratio`（默认 0.8，量比 ≥0.8 才认突破有效）。

**预期**：低量伪突破不再直达 STRONG/WATCH，P0-4 重校验门压力下降（对比改造前 51/62≈82% 降级比例应降低）。

---

### 2.4 [G] 数据基准回填（极小·接线）

**现状**：模板读 `intermediate.get("data_benchmark","")`；子集 `--debate` 模式 `intermediate` 可能为空 → 字段空白。

**设计**：
(a) 组装 `debate_results.json` 时写入顶层 `data_benchmark`（由扫描 `_meta.klines_latest_date` + 采集时间构成，如 `"2026-07-10 15:00 收盘"`）；
(b) `build_debate_report()` 优先读 `debate_results.get("data_benchmark")`，缺则回退 `intermediate`。

**Diff（L1669 / L1944 附近读取逻辑）**：
```python
# build_debate_report() 内
data_benchmark = debate_results.get("data_benchmark") or intermediate.get("data_benchmark", "")
```
不入新文件，改两处读取逻辑。

---

### 2.5 [C] 修正调用方式 + SKILL/自动化指引（极小·文档）

**现状**：`skills/futures-trading-analysis/SKILL.md` Step 8 与自动化 Prompt 3.2 写"单品种辩论直接 Write 结构化 HTML"——与本轮回退手写一致，属错误指引。

**设计**：改为"统一调用 `phase3_generate_report.py --debate debate_results.json` 生成报告"。SKILL.md Step 8 + 自动化 3.2 同步。

**Diff（SKILL.md Step 8 文案）**：
```markdown
# 原
- 单品种辩论：直接Write结构化HTML报告（六模块）到 {YYYY-MM-DD}/Commodities/
# 改为
- 单/多品种辩论：统一调用 `python skills/futures-trading-analysis/scripts/phase3_generate_report.py --debate {YYYY-MM-DD}/debate_results.json --workspace {YYYY-MM-DD}` 生成报告（已支持子集，含数据基准字段）
```
自动化 Prompt 3.2 同步措辞。

---

### 2.6 [F] 置信度单一来源收口（极小·澄清，无代码改动）

**现状**：L1 已接受数值/受控标签并归一化，任意裸串被拒；但 spawn 模板仍重复注入"confidence 必须为 0-1 数值"，易让 Agent 误以为标签非法。

**设计**：spawn 提示改为"confidence 由 `confidence_utils` 归一化，你输出数值或 高/中/低 均可"——消除误导，标签非非法。仅提示措辞调整，无代码改动。

---

### 2.7 [H] 周末冗余日志（已随配置变更自动消失）

第0步周末门控已从 Prompt 移除（见 §0），"跳过→被 override"的成对冗余日志不再产生。**无需修**。

---

## 3. 改造后流水线（目标态）

```
扫描 → [run_debate.py]
         ├─ 识别触发品种（|total|≥阈值）
         ├─ 产出标准化 spawn 计划 JSON → Lead 按计划 spawn（唯一保留的手工步骤）
         ├─ 收口 poll（复用 DebatePhaseGate）+ L1 校验
         ├─ 组装 debate_results.json（含 data_benchmark）
         ├─ extract_knowledge ingst --from（批量，conf<0.6 自动跳过）
         └─ phase3 --debate 生成报告（含数据基准）
```

易碎手工步骤从 ~6 类（spawn/poll/校验/组装/萃取/报告）收敛为 **1 类**（仅 spawn，Lead 固有职责）。

---

## 4. 影响面 / 引用关系 / 版本

| 类型 | 文件 | 改动 |
|------|------|------|
| 新增 | `scripts/run_debate.py` | 主动驱动层（B） |
| 修改 | `scripts/extract_knowledge.py` | 增 `--from` 批量（D） |
| 修改 | `skills/quant-daily/scripts/strategies/channel_breakout_strategy.py` | 量能前置门（E） |
| 修改 | `config/settings.py` | 增 `volume.normal_lower_ratio`（E 配套） |
| 修改 | `skills/futures-trading-analysis/scripts/phase3_generate_report.py` | `data_benchmark` 读字段微调（G） |
| 修改 | `skills/futures-trading-analysis/SKILL.md` | C 调用指引 |
| 修改 | 自动化 `automation-1783403060853` prompt 3.2 | C/F 指引 |
| **不动** | `debate_orchestrator.py` | 被动门禁继续复用 |
| **不动** | `validate_agent_output.py` | F 已满足 |
| **不动** | `phase3` 主体 | 仅 G 读字段微调 |

**版本**：FDT `pyproject.toml` 版本号维持 `get_fdt_version()` 单一真相源，本 redesign 属流程优化、非协议变更，**不强制 bump**。

---

## 5. 验证计划（执行后）

1. **单元（D）**：`extract_knowledge.py ingst --from 2026-07-11/debate_results.json`，确认 ZN/RM 入库、J/JD 因 conf 0.52<0.6 跳过。
2. **策略（E）**：`channel_breakout_strategy` 对本轮 62 品种重算，统计 STRONG/WATCH 数 + P0-4 降级比例，对比改造前（期望降级比例下降）。
3. **报告（C/G）**：`phase3 --debate 2026-07-11/debate_results.json` 生成 HTML，核对「数据基准」非空且为 `2026-07-10 15:00 收盘`。
4. **编排（B）**：`run_debate.py --plan-only` 产出 spawn 计划 JSON，人工核对品种/文件/阶段与本轮回测一致。

---

## 6. 待掌柜确认（铁律第2步）

以上为 **Diff 对比报告（铁律第1步）**。涉及 `plugins/marketplaces` 现有文件修改（SKILL.md / config/settings.py / channel_breakout_strategy.py / extract_knowledge.py / phase3 读字段）+ 新增 `run_debate.py`。

**请掌柜明确说出"改"或"执行"后，我方按文件逐一对齐实施，每个文件改动后回读校验，并追加 `memory/changelog.md` 记录。**
