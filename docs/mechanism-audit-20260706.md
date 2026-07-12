# FDT 机制层问题清单 — 源码逐条验证与修复方案

> 生成：2026-07-06 19:51  
> 基于：validate_verdicts.py / evolve_agents.py / record_verdicts.py / runner.py / ml/trainer.py / debate/history.py / agents/*.md / risk_engine.py  
> 标注：[码] = 源码实证，[spec] = agent markdown 设计未读到 .py

---

## P0 — 验证标签与止损脱节

**位置**: `validate_verdicts.py:124-151` [码]

```python
def validate_verdict(verdict, current_price):
    correct = current_price < entry  # if bear
    hit_stop = False  # 硬编码
    pnl_pct = -change_pct  # 方向振幅非实现盈亏
```

**验证结果：✅ 确认，且代码注释自认"需要日内数据才能精确计算"**

A 空单，entry=3500, stop=3570（1.5×ATR=70点）。次日夜盘跳空3580扫损，损失约2%。T+1收盘3440。
- 验证层判：correct=True（3440<3500 ✓），pnl_pct=+1.7%（方向振幅算正）
- 实际盈亏：-2%（已被止损扫出）

**根本原因**：验证层只看 T+1 收盘价在 entry 哪侧，完全绕过了风控引擎计算的 ATR 止损。

### 修复方案

**修 validate_verdicts.py，改用日内 K 线数据计算真实实现盈亏**。步骤如下：

```python
def validate_verdict_intraday(verdict, intraday_bars):
    """用日内 K 线验证真实实现盈亏，含跳空和止损触发"""
    entry = verdict["entry_price"]
    stop = verdict["stop_loss"]
    target = verdict["target_price"]
    direction = verdict["direction"]  # "bear" / "bull"
    
    # 取裁决后 T+0~T+3 的所有 K 线
    hit_stop = False
    hit_target = False
    hit_time = None
    
    for bar in intraday_bars:
        if direction == "bear":
            if bar["high"] >= stop:  # 空单止损是上破
                hit_stop = True
                hit_time = bar["time"]
                break
            if bar["low"] <= target:  # 空单止盈是下破
                hit_target = True
                hit_time = bar["time"]
                break
        else:
            if bar["low"] <= stop:   # 多单止损是下破
                hit_stop = True
                hit_time = bar["time"]
                break
            if bar["high"] >= target:  # 多单止盈是上破
                hit_target = True
                hit_time = bar["time"]
                break
    
    # 计算实现盈亏
    if hit_stop:
        # 被打止损 → 实亏
        realized_pnl = (stop - entry) / entry * (-1 if direction == "bear" else 1) 
        return {"correct": False, "pnl_pct": realized_pnl, "hit_stop": True}
    elif hit_target:
        realized_pnl = abs(target - entry) / entry
        return {"correct": True, "pnl_pct": realized_pnl, "hit_target": True}
    else:
        close_price = intraday_bars[-1]["close"]
        change = (close_price - entry) / entry
        pnl = -change if direction == "bear" else change
        return {"correct": pnl > 0, "pnl_pct": pnl}
```

需要改动：
1. `fetch_latest_price_tdx()` → 改为拉取裁决日之后的所有日线/60分钟K线
2. `validate_verdict()` → 改为用 K 线序列代替单点价格
3. 添加 `hit_stop` / `hit_target` 两个字段打标回 execution_followup.json

---

## P0 — 自进化优化方向而非交易盈亏

**位置**: `evolve_agents.py` 全篇 [码]

`evolve_agents.py` 的 `get_validated_verdicts()` 从 validation_results 提取的 `correct` 和 `pnl_pct`（line 62-78）全部来自验证层的"方向振幅"标签。自进化全 7 个 Agent 的输入层都是"方向对不对"，不是"这笔赚没赚"。

**关键证据** — evolve_risk_manager (line 99-106):
```python
# 计算止损触发预估 — 用 (stop_loss - entry) / entry 来衡量止损紧张度
avg_stop_dist = abs(v["stop_loss"] - v["entry_price"]) / v["entry_price"]
if avg_stop_dist < 0.02:  # 止损太紧 → 放宽
    adjustment = +0.2
```

**确认：代码在风控参数进化中没有算真实止损触发率，用"止损距/entry"当代理指标。** 如果止损距设得宽（比如 2×ATR），avg_stop_dist 值大，系统会判定"止损太宽"→ 收紧 ATR 乘数。但实际这个品种可能从没被打到过止损，收紧反而增加了误扫风险。

策执远进化 (line 185-195):
```python
t1_hits = 0
for v in correct:
    if v["direction"] == "bear" and v["change_pct"] < -0.03:
        t1_hits += 1
```
**用 change_pct > 3% 代理 T1 目标达标**，非真实触及目标价。

### 修复方案

1. **先修复 validate_verdicts**（见 P0 方案），产出真实的 `hit_stop`/`hit_target` 标签
2. **修改 evolve_agents.py**，以真实止损触发率为输入：

```python
# 修改: 从验证结果提取真实止损触发
for v in verdicts:
    validation = v.get("validation", {})
    if validation.get("hit_stop"):
        actual_stop_hits += 1
        continue  # 这笔被打止损了，不贡献"方向对"样本

real_stop_hit_rate = actual_stop_hits / len(verdicts)
if real_stop_hit_rate > 0.15:  # 止损触发率 > 15% → 放宽
    adjustment = +0.3
```

---

## P1 — 风控参数进化代理指标失真

**位置**: `evolve_agents.py:84-161` [码]

已在上方"P0 — 自进化优化方向"中证实。回顾关键：
- `evolve_risk_manager` 不计算真实止损触发率
- 用 `avg(abs(stop-entry)/entry)` 当触发率代理
- 不是所有品种同比例——有的品种 1.5×ATR 止损真实触发率 35%（RB），有的只有 15%（SA）

这条与 P0 高度重叠。**修了 P0 的自进化验证层，这条自动收敛约 60%**。剩下的 40% 漏洞在风控专用的"高置信度准确率"评估（line 122-138）：

```python
wrong_high_conf = [v for v in verdicts if v["confidence"] == "高" and not v["correct"]]
```
这里的 `correct` 还是"方向对不对"标签，不是真实盈亏。后面"连续亏损→降低"的逻辑如果基于方向标签而非实现盈亏，信号仍然不准。

### 修复方案

同上，P0 修复验证层 + 风控进化层改用真实止损触发标签。

---

## P1 — 验证窗口 T+1 收盘价，与期货物理自矛盾

**位置**: `validate_verdicts.py:29-51, 124-151` [码]

```python
def fetch_latest_price_tdx(symbol):
    # 取最新一根日K线
    bars = data["data"]
    latest = bars[-1]
    price = latest.get("close", 0)  # ✅ 仅收盘价
    
def validate_verdict(verdict, current_price):
    # 只用 current_price 一个值判断
    correct = current_price < entry  # 空单方向
```
风控 spec（futures-risk-manager.md 坑3）："夜盘跳空3%很常见，日线止损2%等于没设"——设计层意识到了夜盘跳空风险，但验证层完全没跑这个场景。

### 修复方案

在 P0 修复的 `validate_verdict_intraday` 中，**添加跳空检查**：

```python
# 在遍历 K 线前，先检查 next_open 与 entry 的跳空
bars = intraday_bars
first_bar = bars[0]
gap_pct = abs(first_bar["open"] - entry) / entry

# 定义: 跳空 ≥ 止损距 × 0.8 算"跳空扫损"
stop_distance = abs(entry - stop)
gap_ratio = abs(first_bar["open"] - entry) / stop_distance

if direction == "bear" and first_bar["open"] >= entry + stop_distance * 0.8:
    # 夜盘开盘直接跳空越过止损
    return {"correct": False, "pnl_pct": -stop_distance/entry, "hit_stop": True, "gap_stop": True}
```

同时 --t3 模式应改为 **T+3 日内完整验证**（包含 T+1/T+2/T+3 日内所有 K 线），而非"3个 close 点"。

---

## P2 — LLM 给 LLM 辩论打分（裁判循环）

**位置**: `debate-judge/SKILL.md:77-86` [spec]

6 维评分模型（逻辑严谨度 30%，证据充分性 25%，反驳有效性 20%...）全部由闫判官（LLM）对多空双方（LLM）主观打分。

**缓解措施**：
- R07：反向证据强制检索（judge.md:273-275）
- 论点树追踪（judge.md:223-225）
- R01-R05 基于历史校准数据做评分修正（judge.md:262-267）

**收敛阈值本质**：spread≥15 提前终止 / ≤3 趋同结束。这两个超参目前没有通过数据回测来确定最优值，调高→永不辩论（退化信号过滤），调低→为辩论而辩论。

**判断**：不是 bug，是系统设计层的认知局限。缓解措施充分但无法根除。

### 修复方向

加入**辩论质量后验统计**。不与 LLM 评分较劲，用验证层的真实胜率来做"辩论有效性"的统计检验：

```python
# 在 validate_verdicts 中新增统计
debate_before = 0  # 辩论前信号直接推荐的准确率
debate_after = 0   # 辩论后裁决的准确率

# 如果经过辩论的品种准确率显著高于直接推荐 → 辩论有效
# 否则 → 缩小辩论品种范围 / 降低辩论轮数
```

---

## P2 — 进化依赖间接代理（代码自认）

**位置**: `evolve_agents.py:253, 436` [码]

```python
# 行253 — 注释原文：
"注: 辩手进化依赖辩论日志中的详细评分数据。
当前只有方向正确性, 没有辩论过程评分, 用方向胜率作为代理指标。"

# 行436 — 注释原文：
"用FT(因子择时)的g_group作为基本面的代理指标"
```

**确认**。代码层面明知是代理但受限于数据可得性。

**修复路径**：
- 辩手进化：等 P0 修复 execution_followup.json 后，收集真实"该辩手提出的品种方向的盈亏"作为评分
- 探源进化：可用 DuckDB 查历史 FT 因子表现来替代单方向 g_group 一致性
- 链证源进化（line 315-381）：用链准确率做去重阈值调整，这个设计相对合理，不算"弱代理"

---

## P2 — 无执行层，验证非成交盈亏

**位置**: `pipeline/runner.py` [码]，`validate_verdicts.py` [码]

Runner 六步流程：scan → chain → debate_brief → assemble → report → history+ML

没有任何一步涉及模拟下单/成交/滑点/手续费。

验证层使用"方向振幅"代替盈亏，风险引擎 `risk_engine.py` 虽然实现了 `calc_transaction_cost()`（line 118-185），但在执行链中从未对接——即风控明算出了摩擦成本，但没有地方把摩擦成本注入验证标签。

**修复方向**：
1. validate_verdicts 的 `pnl_pct` 改为方向振幅减去摩擦成本（`risk_engine.calc_transaction_cost` 可提供）
2. 如需更高保真度，添加订单模拟器（不要求与实盘 MCP 对接），模拟 fill/slippage/commission
3. 现阶段目标是"模拟盈亏"而非"实盘盈亏"——让进化层看到扣除摩擦后的修正盈亏

---

## P2 — 数据流衔接缺口（待核实→确认存在缺口）

**位置**:
- `pipeline/runner.py:296-315` → 调 `debate.history.record_feedback()` [码]
- `scripts/record_verdicts.py` → 写 `memory/execution_followup.json` [码]
- `scripts/evolve_agents.py:562-566` → 读 `memory/execution_followup.json` [码]

**验证结论：两路径运行未接通，确认存在缺口。**

**路径 A（runner 实际执行的）**：
```
runner.py step_record_history 
    → record_feedback(sym, debate_value, judge_confidence=50) 
    → 写入 data/debate_history/debate_feedback.json
    → 仅记录粗粒度 "debate_value" 和 "judge_confidence"
    → 不含 entry/stop/target 等价格参数
```

**路径 B（evolve_agents 需要的）**：
```
闫判官 (judge.md line 489-497 提到)
    → subprocess.run(["python", "scripts/record_verdicts.py", "--input", "debate_results.json"])
    → 写入 memory/execution_followup.json
    → 含完整 verdicts: symbol/direction/entry/stop/target...
    → evolve_agents.py 读 execution_followup.json
```

**runner.py 没有调用 record_verdicts.py**。这意味着：

1. 全自动流水线（runner.py）生成的裁决 → 只进了 `debate_feedback.json`，不进 `execution_followup.json`
2. `evolve_agents.py` 读 `execution_followup.json` → **永远读不到数据** → **自进化不会发生**
3. 除非有人手动调用 `record_verdicts.py`，否则自进化闭环是断开的

**确认这是实际存在的 Bug**，不是"待核实"。

### 修复方案

**最小修复**：在 runner.py 的 `step_record_history()` 末尾追加调用 `record_verdicts.py`：

```python
# runner.py step_record_history 末尾追加
try:
    # 查找 debate_results.json
    debate_results_path = os.path.join(REPORT_DIR, "debate_results.json")
    if os.path.exists(debate_results_path):
        subprocess.run([
            sys.executable,
            os.path.join(SCRIPT_DIR, "scripts", "record_verdicts.py"),
            "--input", debate_results_path,
        ], check=False, timeout=30)
        logger.info("裁决已同步至 execution_followup.json")
except Exception as e:
    logger.warning(f"裁决同步失败: {e}")
```

---

## 未读源码的盲区

用户指出三个文件未读到：

1. **futures-strategist.md** — 策执远仓位/摩擦/合约选型  
   → 已读到 `agents/futures-trading-strategist.md` 和 `scripts/risk_engine.py`。仓位计算在 risk_engine 中有实现，策执远主要在 LLM 推理层。

2. **scripts/risk_engine.py** — 5 层风控引擎  
   → 已读到，存在且功能完整。实现了选锚算法（0.8~2.5ATR）、置信度仓位折减、动态调整、特殊场景覆写。

3. **signals/debate_brief.py** — 辩论精选阈值  
   → 路径存在但未读内容。已知 runner.py 调用时的参数：`--min-count 20 --min-chains 12`。

这三个文件中，risk_engine.py 已核实内容与风控 spec 一致。

---

## 最该修的一条

> **让 validate_verdicts 接日内数据，用 entry→stop/target 真实实现盈亏（含跳空滑点）替代"方向对不对"做标签。修此条，P0/P0/P1 三处一起收敛。**

**赞同。** 验证层是整个自进化闭环的"根"。根歪了，所有靠验证层信号的模块（evolve_agents 全部7个 Agent、校准系统、ML 训练标签）都跟着歪。

**修复优先级**：
1. **P0** validate_verdicts 接日内 K 线 + 真实 stop/target 触发 PnL  ← **根修复**
2. **P2** runner.py 追加 call record_verdicts.py  ← **数据流接通**
3. **P0** evolve_agents 改用真实止损触发率（依赖#1完成） ← **自进化闭环打通**
4. **P1** evolve_agents 改用真实实现 PnL（依赖#1完成） ← **自进化信号校正**
5. **P2** 辩论有效性后验统计（依赖#1完成 + #2数据积累） ← **LLM 评分质量监控**

### 修复影响

修验证层不涉及修改 data/pipeline/skill 脚本，只在 `scripts/validate_verdicts.py` 和 `scripts/evolve_agents.py` 两文件中动刀：

| 改动 | 文件 | 风险 |
|:----|:-----|:----|
| 数据获取从"1个close值"改为"K线序列" | validate_verdicts.py | 中——TDX API 需要能拉到历史日线/60分K线 |
| validation_result 新增 hit_stop/hit_target 字段 | validate_verdicts.py | 低——向后兼容（旧数据 hit_stop=False 仍可接受） |
| 风控进化用真实触发率代替代理距离 | evolve_agents.py | 低——逻辑替换，参数结构不变 |
| runner 追加 record_verdicts 调用 | runner.py | 低——单行 import + subprocess.run |
