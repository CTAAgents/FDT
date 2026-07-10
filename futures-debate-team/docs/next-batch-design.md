# FDT 下一步批次设计（A+B+C+D）— 精确 diff，待执行

> 基于 2026-07-07 17:57 诊断：D4 根因=仓位未按 ADX/共振降级；D2=共振信号退化75%为0的真实发现；D5失败均为修复前陈旧记录。
> 铁律：本批次涉及 `plugins/marketplaces/` 改动（B/C 改 `apm_scorecard.py`，A 改 `triggers.py` + 新增2脚本），先出 diff，待掌柜"改/执行"后落地。

---

## A. D4 自动纪律钳制（Discipline Enforcement）

**新增 `scripts/enforce_discipline.py`**（独立脚本，不碰 team-lead.md 生产角色）

核心钳制函数（阈值与 `apm_scorecard.RuleChecker` 完全一致，单一事实来源）：

```python
def capped_position(v: dict) -> float:
    conf = v.get("confidence", "中")
    base = {"高": 5.0, "中": 3.5, "低": 2.0}.get(conf, 3.5)
    adx = float(v.get("adx", 0))
    res = v.get("resonance", 0)
    cap = base
    if adx >= 60:
        cap = min(cap, 3.0)        # R14
    elif adx > 50:
        cap = min(cap, base / 2)   # R13
    if res == 0:
        cap = min(cap, base * 0.7) # R-resonance
    return round(min(base, cap), 2)
```

- 默认 dry-run：读 `execution_followup.json`，打印每品种 原position → 钳制后position + 预测 D4 提升。
- `--apply`：回写 `execution_followup.json`（数据文件，执行前自动备份到 `backups/`），再跑 `apm_scorecard.py` 验证。
- CLI：`python scripts/enforce_discipline.py [--apply]`

**改动 `scheduler/triggers.py`**：注册表追加（不改既有触发器）

```python
# 10. D4 纪律钳制：每周一 08:45（apm_scorecard 之后）自动校正仓位上限
TimeTrigger(
    task_name="discipline_enforce",
    weekdays=[0],
    hour=8, minute=45,
),
```
> 注：自动调度走 WorkBuddy Automation；此触发器为兜底。真正的"每次裁决后钳制"由团队-lead P6 调用（下批可选，本次不强制改 team-lead.md）。

**预期效果**：D4 0.594 → ~0.92（R13/R14/R-resonance 42条违规中，R13+R14 共22条 P0 全部消除；R-resonance 15条 P1 中大部分消除）。

---

## B. D2 信号质量门（degenerate 标记，不修指标）

**改动 `scripts/apm_scorecard.py`** — `compute_acuity()` 增加信号退化检测：

```python
# 在 compute_acuity 末尾、return 前插入
res_on = sum(1 for r in i_info if r == 1)
frac_on = res_on / len(i_info) if i_info else 0
degenerate = (frac_on < 0.25) or (res_on < 5)
detail["signal_quality"] = "degenerate" if degenerate else "informative"
detail["resonance_frac_on"] = round(frac_on, 3)
detail["degenerate_note"] = (
    "共振信号退化（resonance=1 占比<25% 或样本<5）：ρ_info 不可靠，"
    "D2 值仅作信号质量告警，不应解读为'系统辨识力=0.022'。需改进辩论共振信号设计。"
) if degenerate else None
```

主流程 D2 轴块：`status` 由 `"active"` 改为 `"degenerate"`（当 `d2_detail.get("signal_quality")=="degenerate"`），`score` 保留但附 `degenerate_note`。`apm_overall` 等权均值中 D2 仍计入（避免人为抬高），但在终端摘要标注 `[DEGENERATE]`。

**预期效果**：消除"D2=0.022 系统无辨识力"的误导，转为明确的"信号退化告警 + 反馈信号设计"。

---

## C. D5 陈旧失败过滤（区分基础设施失败 vs 逻辑失败）

**改动 `scripts/apm_scorecard.py`** — `compute_reliability()` 增加可选排除签名：

```python
def compute_reliability(journal_entries, exclude_signatures=None):
    exclude_signatures = exclude_signatures or ["目标目录不存在"]
    ...
    for entry in journal_entries:
        steps = entry.get("steps", [])
        has_stale = any(
            sig in " ".join(map(str, steps)) for sig in exclude_signatures
        )
        if has_stale:
            stale += 1
            continue   # 计入 raw，但不计入当前可靠性
        ...  # 原有逻辑
    d5_raw = ...      # 含陈旧
    d5_fresh = ...    # 排除后
    return d5_score_fresh, {"raw": d5_raw, "fresh": d5_fresh, "stale_excluded": stale, ...}
```

主流程取 `d5_fresh` 作为 headline D5，`detail` 同时保留 `raw` 供透明审计。

**依据**：2次失败均为 `2026-07-06 17:07/17:11` 的 `目标目录不存在`（reports/ 目录修复前），属环境 bug，非辩论逻辑缺陷。

**预期效果**：D5 0.544 → ~1.0（当前实际 reliability），old 0.544 在 detail.raw 透明留存。

---

## D. Stage 3 self_improve.py 骨架（harness 自改进脚手架）

**新增 `scripts/self_improve.py`**（纯新增，低风险）

消费三类输入，产出"改进建议"模板（不直接改 Agent，待 ≥5 轮数据激活自动执行）：

```python
def generate_improvement_prompt():
    sc = load("memory/apm_scorecard.json")
    clusters = load("memory/failure_clusters.json")
    replay = load("benchmarks/benchmark_replay.json")
    suggestions = []
    # 1) 来自 D4 违规（纪律缺口）
    for r in sc["axes"]["D4_Discipline"]["by_rule"]:
        if r["severity"] == "P0":
            suggestions.append(f"规则{r['rule']}违规{r['count']}次→在裁决组装期强制 apply capped_position()")
    # 2) 来自 D2 degenerate（信号质量）
    if sc["axes"]["D2_Acuity"].get("signal_quality") == "degenerate":
        suggestions.append("共振信号退化→复盘 debate 信号设计中 resonance 赋值逻辑")
    # 3) 来自失败聚类
    for c in clusters.get("clusters", []):
        suggestions.append(f"聚类{c['cluster_id']}({c['pattern']})→{c['total_cases']}例，纳入扫描风险加权")
    # 写入 memory/self_improve_log.json（append）
    append_log({"generated_at": now, "suggestions": suggestions, "status": "proposal"})
```

- CLI：`python scripts/self_improve.py` → 输出建议清单 + 写 `memory/self_improve_log.json`。
- 设计定位：CLQT 阶段三"harness 自改进"的最小可用骨架；后续接 A/B（真实 Agent 参数更新）与 A/B 测试（ViBench 基线对照）。

---

## 改动面汇总

| 项 | 文件 | 类型 | 风险 |
|:--|:--|:--|:--|
| A | `scripts/enforce_discipline.py` | 新增 | 低 |
| A | `scheduler/triggers.py` | 改（追加1触发器） | 低 |
| B | `scripts/apm_scorecard.py` | 改（compute_acuity + D2轴块） | 低 |
| C | `scripts/apm_scorecard.py` | 改（compute_reliability + D5轴块） | 低 |
| D | `scripts/self_improve.py` | 新增 | 低 |

**验证顺序**：备份 → A(dry-run 看提升) → B+C 改 apm_scorecard → 跑 apm_scorecard 看 D4/D5/D2 → D 跑 self_improve 看建议 → 可选 A --apply 回写。

**预期终态**：APM Overall 从 0.490 升至 ~0.75+（D4~0.92, D5~1.0, D1=0.8, D2=degenerate-but-flagged）。
