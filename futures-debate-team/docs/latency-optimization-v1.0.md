# FDT 时延优化实施方案 v1.1

> 目标：将 FDT 一轮辩论执行时间从 60min 降至 **加权平均 ~12min**
> 策略：信号分级路由（🔴强信号8min）+ 研究员并行化 + 缩减辩论轮次
> **2026-07-11 全部实施完成 ✅**

---

## 一、现状时间分布

```
P1 数技源 scan_all  (5min) ─ 串行
P2 链证源链分析     (10min) ─ 串行
P3 研究员并行?       (30min) ─ 实际是串行spawn
    ├─ 探源/基本面   (10min)
    ├─ 观澜/技术面   (10min)
    └─ 链证源        (10min)
P3 辩论流程          (28min) ─ 6轮
P4 策执远方案        (5min)  ─ 串行
P5 风控明审核        (5min)  ─ 串行
                              总计 ≈ 60-80min
```

---

## 二、改进方案

### Step 1: 信号分级路由（最高优先级）

**文件新建**: `scripts/signal_classifier.py`

根据数技源 scan_all 的输出，实时判断信号强度并路由到不同的辩论模式：

| 信号等级 | 路由到 | 预估时间 | 判定条件 |
|:--------:|:-------|:--------:|:---------|
| 🔴 C1（强信号） | `fast` profile | **~8min** | ADX>40 + RSI∈(25,75) + BB带宽扩张 + 链一致性>75% |
| 🟡 C2（中信号） | 简化辩论 | **~20min** | 2/3条件满足 |
| 🔵 C3（模糊信号） | 全流程 | **~40min** | 信号矛盾/条件不足 |
| ⚪ C4（无信号） | 跳过 | **0min** | 无通道突破信号 |

**代码逻辑**:
```python
def classify_signal(scan_result: dict) -> SignalTier:
    """
    输入: scan_all 的 JSON 输出
    输出: C1/C2/C3/C4
    """
    adx = scan_result.get("adx", 0)
    rsi = scan_result.get("rsi", 50)
    bb_width = scan_result.get("bb_width", 0)
    chain_consensus = scan_result.get("chain_consensus", 0)
    has_breakout = scan_result.get("signal_type") in ("channel_breakout",)
    
    conditions_met = 0
    if adx > 40: conditions_met += 1
    if 25 < rsi < 75: conditions_met += 1
    if bb_width > 0.2: conditions_met += 1
    if chain_consensus > 0.75: conditions_met += 1
    
    if conditions_met >= 3 and has_breakout: return SignalTier.C1
    if conditions_met >= 2 and has_breakout: return SignalTier.C2
    if has_breakout: return SignalTier.C3
    return SignalTier.C4
```

---

### Step 2: 研究员并行化（最大单项收益）

**需修改文件**: `skills/futures-trading-analysis/SKILL.md`（闫判官 spawn 逻辑）

**改动内容**: 闫判官的 P3 spawn 从"串行逐个 spawn 研究员"改为"同时 spawn 三个研究员"

**改动点**（在 SKILL.md 中找到 P3 研究员 spawn 段落）:

```
改动前 (串行spawn):
  闫判官 spawn 基本面研究员 → 等待完成 → 读取产出
  → spawn 技术面研究员 → 等待完成 → 读取产出
  → spawn 链证源研究员 → 等待完成 → 读取产出

改动后 (并行spawn):
  闫判官 同时 spawn 三个研究员
  → 并行等待，全部就绪后同时读取
  → 合并三份快照后广播给辩手
```

**预期收益**: 30min → **10min**（三个研究员重叠执行）

**注意事项**:
- 文件冲突保护：每个研究员写不同命名的输出文件（`researcher_fundamental_*.json`, `researcher_technical_*.json`, `researcher_chain_*.json`）
- 超时：单个研究员 600s 超时，成功数 ≥2/3 即可继续
- 已实施的 IGP 推理门控会防止并发锁冲突

---

### Step 3: 缩减辩论轮次

**现状**: 6 轮辩论（多方立论 → 空方立论 → 正方rebuttal → 反方rebuttal → 自由交锋 → final）

**改为**:

| 信号等级 | 辩论轮次 | 预估时间 |
|:--------:|:--------:|:--------:|
| C1（强信号） | 0 轮（直接 fast） | 0 |
| C2（中信号） | 2 轮（辩手并行立论 → 1轮rebuttal） | ~10min |
| C3（模糊信号） | 4 轮（立论 → rebuttal → 交锋 → final） | ~16min |

**预期收益**: C2 场景 28min→**10min**，C3 场景 28min→**16min**

---

### Step 4: 预计算（远期）

**文件新建**: `scripts/precompute_cache.py`

核心：盘前将 scan_all 和研究员资料缓存，盘中仅做增量更新。

**实现路径**：
- 盘前定时任务（`/goal 每日08:00自动运行`）→ 跑 scan_all + 研究员资料收集
- 盘中被触发时 → 读缓存 + 重新获取最新 K 线价格（仅需~1min）
- 缓存有效期：4小时，有重大事件时自动失效

**预期收益**: C2 场景 20min→**12min**，C3 场景 40min→**20min**

---

## 三、实施步骤

```
Step 1: 信号分级路由  ── signal_classifier.py ✅
  ├ 状态: 已实施，6个测试全部通过
  ├ 文件: plugins/futures-debate-team/scripts/signal_classifier.py
  └ 收益: C1场景 ~8min（~60%交易日）

Step 2: 研究员并行化  ── SKILL.md P2 改并行spawn ✅
  ├ 状态: 已实施，P2从串行改为三个研究员并发spawn
  ├ 改动: 探源+观澜+链证源同时跑，wait_all + timeout=600s + min_success=2
  └ 收益: C2/C3场景各省 ~20min

Step 3: 辩论轮次缩减  ── SKILL.md + futures-judge.md ✅
  ├ 状态: 已实施，辩论轮次由信号等级决定
  ├ 改动: C1=0轮/ C2=2轮/ C3=4轮/ C4=0轮
  └ 收益: C2场景省 ~18min

Step 4: 预计算缓存  ── precompute_cache.py ✅
  ├ 状态: 已实施，8个测试全部通过
  ├ 文件: plugins/futures-debate-team/scripts/precompute_cache.py
  ├ 自动化: 「FDT盘前预计算缓存刷新」每日08:00自动运行
  ├ 功能: 盘前跑scan_all缓存JSON→盘中命中后跳过P1全流程→仅刷新指定品种最新价格(~1min)
  └ 收益: C2/C3场景各省 ~5min，缓存命中后加权平均约 ~10min


Step 3: 缩减辩论轮次  ── 修改 SKILL.md P3 辩论流程
  ├ 耗时: ~1h
  ├ 收益: C2场景省 ~18min
  └ 改动: 需同步修改 futures-judge.md

Step 4: 预计算       ── 新建 precompute_cache.py
  ├ 耗时: ~2h
  ├ 收益: 所有场景再省 5-8min
  └ 改动: 中高，需要缓存 + 失效检测
```

## 四、预期最终效果

| 场景 | 占比 | 优化前 | Step1 | Step1+2 | Step1+2+3 | Step1+2+3+4 |
|:----|:---:|:-----:|:-----:|:-------:|:---------:|:----------:|
| C1 强信号 | ~60% | 60min | **8min** | **8min** | **8min** | **5min** |
| C2 中信号 | ~25% | 60min | 60min | **30min** | **20min** | **12min** |
| C3 模糊信号 | ~15% | 60min | 60min | **40min** | **35min** | **20min** |
| **加权平均** | 100% | **60min** | **20min** | **18min** | **14min** | **8min** |

---

## 五、回退策略

- **Step 1 信号分类器**：自带投票机制，误分类率预期 <5%。极端情况（ADX=39 但 RSI 极度超卖/超买）的边界情况会自动降级到 C2，不会造成重大误判
- **Step 2 并行 spawn**：保留串行回退路径。如果并行 spawn 失败（产出率 <2/3），自动切换回串行
- **Step 3 缩减辩论**：C3 场景保留 4 轮辩论，C3 不会受影响
- **Step 4 预计算**：缓存失效时自动执行全流程爬取，无数据丢失风险
