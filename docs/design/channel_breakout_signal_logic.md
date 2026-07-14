# 通道突破信号逻辑完整技术说明

> **版本对应**：`channel_breakout_strategy.py` v1.3（双通道体系）+ `settings.py` CHANNEL_BREAKOUT_CONFIG v2.3 权重
> **适用系统**：FDT 期货辩论专家团 · 数技源通道突破扫描（quant-daily）
> **最后更新**：2026-07-13（v2.3 DC20/BB 双突破权重提升）

---

## 一、策略总览

通道突破策略以**价格行为为核心**，不依赖移动均线、MACD、RSI 等滞后指标，仅用"价格是否真实穿越历史边界"作为趋势启动/延续的判断依据。

策略由**两层通道**构成，评分上采用加权汇总：

| 层 | 通道类型 | 权重 | 职责 |
|:---|:--------|:----:|:-----|
| **Layer A** | 唐奇安通道（Donchian）DC20 + DC55 | 100%（其中 DC20 主体 + DC55 趋势确认） | 识别短期突破 + 中期趋势方向 |
| **Layer B** | 布林带（Bollinger Band） | 独立加分/减分层 | 波动率扩张佐证 + %b 极端位置强度 |

> ⚠️ **v1.3 关键变更**：ADX 已从通道突破评分中**完全移除**（仅保留显示字段）。突破策略不应被趋势强度过滤——低 ADX 时突破同样有效，高 ADX 不构成否决理由。

### 评分总公式

```
total_score = dc_score + bb_score + volume_score
```

其中：
- `dc_score = dc20_score + dc55_score`
- `direction`：total_score > 0 → bull；< 0 → bear；= 0 → neutral
- `grade`：按 `abs(total_score)` 对照 `SIGNAL_GRADE_THRESHOLDS` 分级

### 信号等级阈值

| 等级 | 触发条件 | 含义 |
|:-----|:---------|:-----|
| **STRONG** | abs(total) ≥ 50 | 强信号，必进辩论流程 |
| **WATCH** | abs(total) ≥ 40 | 观察信号 |
| **WEAK** | abs(total) ≥ 20 | 弱趋势信号（= 辩论入口阈值 DEBATE_ENTRY_MIN_ABS） |
| **NOISE** | abs(total) < 20 | 噪声，不进入后续流程 |

---

## 二、Layer A — 唐奇安通道（Donchian Channel）

唐奇安通道以"N 根 K 线的最高价/最低价"为边界。本策略用两个周期：

- **DC20**：20 根 K 线（约 1 个月交易日）→ 短期突破边界
- **DC55**：55 根 K 线（约 1 个季度）→ 中期趋势边界

边界计算采用 **TDX REF 式**（不含当前 bar，避免未来函数）：
```
DC20_UPPER = REF(HHV(high, 20), 1)   # 前20根最高价的最大值
DC20_LOWER = REF(LLV(low, 20), 1)    # 前20根最低价的最小值
DC20_POS   = (close - LOWER) / (UPPER - LOWER)   # 0~1，>0.7 上轨附近
```

### A1：DC20 短期通道突破（核心评分项）

突破判定：`close ≥ DC20_UPPER`（向上突破）或 `close ≤ DC20_LOWER`（向下突破）。

突破基础分来自 `dc20.break_base_score`（v2.3: **40 分**，原为 30）。

#### 突破幅度加分（distance_pct）

突破后按"价格距边界的百分比"追加强弱分：

| 条件 | 方向 | 加分 | 标签 |
|:-----|:-----|:----:|:-----|
| `distance_pct > break_strong_pct (1.0%)` | 上破 | +`break_strong_bonus` (15) | strong |
| `distance_pct > break_moderate_pct (0.3%)` | 上破 | +`break_moderate_bonus` (8) | moderate |
| 其他（已突破但未达 0.3%） | 上破 | 0 | weak |

下破对称处理（减分）：
- 下破基础分 `-40`；强下破 `-15`；中下破 `-8`

`distance_pct` 计算：
- 上破：`(price / DC20_UPPER - 1) × 100`
- 下破：`(DC20_LOWER / price - 1) × 100`

#### DC20 位置加分（上轨附近运行）

若 `DC20_POS > pos_upper_threshold (0.7)` 且向上突破 → 再 +`pos_upper_bonus (5)`（确认在上轨上方运行，非瞬间刺穿）。

#### 成交量前置确认（E 修复）

⚠️ **无量突破不授 DC20 base 分**：A1-0 阶段先检查当前成交量是否 ≥ 20 日均量的 `normal_lower_ratio (0.8)` 倍。若 `_vol_ok = False`：
- 不授 `break_base_score`（40 分拿不到）
- `dc20_break_strength = "weak_no_vol"`
- 仅记录突破方向，但评分显著削弱

### A2：DC20 逼近判定（near_breakout，v2.3 重点提升）

当价格**尚未收盘突破**但已极度逼近 DC20 边界时，视为"趋势前夜"，给予逼近分。这是 v2.3 权重提升的核心——让刚要突破的品种提前进入辩论视野。

#### 机制一：Tick 级逼近

```
tick_size = get_tick_size(sym)
ticks_to_upper = (DC20_UPPER - price) / tick_size
ticks_to_lower = (price - DC20_LOWER) / tick_size

if 0 < ticks_to_upper <= near_breakout_ticks (7):  dc20_score += near_breakout_score (22)  # 上破逼近
if 0 < ticks_to_lower <= near_breakout_ticks (7):  dc20_score -= near_breakout_score (22)  # 下破逼近
```

含义：价格距 DC20 上轨只剩 ≤ 7 个 tick（如螺纹钢 1 元/tick，即 ≤ 7 元），即视为"随时突破"。

#### 机制二：动量逼近（v2.3 新增"结构性突破"识别）

盘中高波动时，K 线未收盘但已实质突破。判定条件：
- 当前 bar 振幅 `≥ 1.2 × ATR` **或** 单边冲动 `|close - open| ≥ 0.6 × ATR`
- 且价格距 DC20 边界 ≤ `2 × near_breakout_ticks`（即 ≤ 14 ticks）

满足则给 `near_breakout_score (22)`。即使 `dc20_score == 0`（尚未有任何突破/逼近分）也会触发。

> **设计意图**：机制一捕捉"静态逼近"，机制二捕捉"动态动能逼近"。两者独立，可叠加（但代码逻辑上机制二在 `dc20_score == 0` 时才检查，实际是互补而非叠加）。

### A3：DC55 中期通道（趋势确认）

DC55 不直接给"突破分"，而是给**位置分 + 趋势方向分**，用于确认 DC20 突破的方向是否得到中期趋势支撑。

#### DC55 价格位置分（pos_thresholds 从高到低匹配）

| DC55_POS 区间 | 分数 | 标签 |
|:--------------|:----:|:-----|
| > 0.85 | +25 | extreme_upper |
| > 0.70 | +15 | upper |
| > 0.50 | +5 | mid_upper |
| < 0.15 | -25 | extreme_lower |
| < 0.30 | -15 | lower |
| < 0.50 | -5 | mid_lower |

#### DC55 趋势方向分

DC55 趋势由"前一半中点 vs 后一半中点"比较得出（`up`/`down`/`flat`）：

- **趋势向上**（`dc55_trend == "up"`）：
  - 若 `dc55_score ≥ 0`：`+trend_base_score (10)` + `trend_alignment_bonus (5)`（方向一致）
  - 若 `dc55_score < 0`：`-trend_base_score` + `divergence_penalty (10)`（价格低位但趋势向上，背离）
- **趋势向下**（`dc55_trend == "down"`）：
  - 若 `dc55_score ≤ 0`：`-trend_base_score` - `trend_alignment_bonus`（方向一致）
  - 若 `dc55_score > 0`：`+trend_base_score` - `divergence_penalty`（价格高位但趋势向下，背离）

#### Layer A 汇总

```
dc_score = dc20_score + dc55_score
```

---

## 三、Layer B — 布林带确认（Bollinger Band）

布林带作为**独立加分/减分层**，对 DC 通道突破做波动率与极端位置佐证。三个子项：

### B1：BB 带宽扩张/收缩（波动率维度）

`bb_width_pct = (BB_UPPER - BB_LOWER) / BB_MIDDLE × 100`

| 条件 | 方向 | 分数 |
|:-----|:-----|:----:|
| `bb_width_pct > width_high_threshold (4.0)` | dc_score ≥ 0 → +；< 0 → - | `width_high_score (6)` |
| `bb_width_pct > width_moderate_threshold (2.5)` | 同上符号 | `width_moderate_score (3)` |
| 否则 | — | 0（低波动） |

> 带宽扩张 = 波动率上升 = 趋势可信度加分（符号跟随 DC 方向）。

### B2：BB 挤压检测（突破前兆）

若 `bb_squeeze == True`（带宽处于历史低位收缩）→ +`squeeze_bonus (2)`，标记 `breakout_pending`（突破前兆预警）。

### B3：BB %b 位置（极端强度，v2.3 权重大幅提升）

`bb_pos = (close - BB_LOWER) / (BB_UPPER - BB_LOWER)`，值域 0~1，> 1.0 表示突破上轨。

| 条件 | 方向 | 分数（v2.3） | 旧分 | 标签 |
|:-----|:-----|:------------:|:----:|:-----|
| `bb_pos > pos_extreme_threshold (1.05)` | + | **+20** | 6 | extreme |
| `bb_pos > pos_upper_threshold (1.0)` | + | **+15** | 4 | at_upper |
| `bb_pos > pos_mid_upper_threshold (0.7)` | + | +2 | 2 | mid_upper |
| `0.3 < bb_pos ≤ 0.7` | — | 0 | 0 | mid |
| `pos_mid_lower_threshold (0.15) < bb_pos ≤ 0.3` | - | -2 | -2 | mid_lower |
| `0 < bb_pos ≤ 0.15` | - | **-15** | -4 | at_lower |
| `bb_pos ≤ 0`（突破下轨） | - | **-20** | -6 | extreme |

#### 一致性检查（dc_consistency_bonus）

```
if dc_score > 0 and bb_pos > 0.5:  bb_score += 2   # 向上突破 + BB上半 = 一致
if dc_score < 0 and bb_pos < 0.5:  bb_score += 2   # 向下突破 + BB下半 = 一致
```

---

## 四、成交量确认层（Volume，独立加减分）

成交量不单独成层，作为 `volume_score` 直接加入总分。判定基于当前量 vs 20 日均量比（`vol_ratio`）：

| 条件 | 方向 | 分数 | 标签 |
|:-----|:-----|:----:|:-----|
| `vol_ratio > explosive_ratio (1.5)` | 跟随 dc_score 符号 | ±`explosive_score (10)` | explosive |
| `vol_ratio > elevated_ratio (1.2)` | 跟随 dc_score 符号 | ±`elevated_score (5)` | elevated |
| `normal_lower_ratio (0.8) < vol_ratio ≤ 1.2` | — | 0 | normal |
| `vol_ratio ≤ normal_lower_ratio` | — | `weak_penalty (-3)` | weak |

> 放量突破 → 加分（确认有效）；缩量 → 减分（警惕假突破）。符号与 dc_score 一致。

---

## 五、综合评分与方向/等级判定

```python
total_score = dc_score + bb_score + volume_score
direction = "bull" if total_score > 0 else ("bear" if total_score < 0 else "neutral")

abs_score = abs(total_score)
if abs_score >= 50:   grade = "STRONG"
elif abs_score >= 40: grade = "WATCH"
elif abs_score >= 20: grade = "WEAK"
else:                 grade = "NOISE"
```

---

## 六、信号类型判定（signal_type）

`signal_type` 描述信号的**性质**，与 `grade`（强度）正交。判定优先级：

| 优先级 | 条件 | signal_type |
|:------|:-----|:------------|
| 1 | `abs(dc20_score) ≥ 30` 且 `abs(dc_score) ≥ 20` | `channel_breakout`（通道突破） |
| 2 | `abs(dc20_score) ≥ 10`（逼近但未达突破） | `near_breakout`（逼近突破） |
| 3 | `abs(dc55_score) ≥ 15` | `trend_confirmation`（趋势确认） |
| 4 | `bb_squeeze == True` | `bb_squeeze_prebreakout`（布林挤压前兆） |
| 5 | 其他 | `minor_signal`（次要信号） |

### 🔴 事实优先于评分（2026-07-11 铁律）

若价格已**实际突破 DC20**（`dc20_break in ("up","down")`），即使 `dc20_score` 未达 channel_breakout 阈值（30），`signal_type` 也必须反映事实：
```python
if dc20_break in ("up", "down") and signal_type == "near_breakout":
    signal_type = "channel_breakout"
```
评分低只影响 grade（WATCH/STRONG），**不能歪曲事实说"未突破"**。

---

## 七、P0-4 伪突破重校验门禁（防御伪造突破的最后闸门）

扫描完成评分后，`scan_all.py` 调用 `_revalidate_breakouts()` 对所有突破类信号做**原始 K 线回验**。这是防止"评分高但事实未突破"的硬闸门。

### 门禁逻辑

对 `signal_type ∈ {channel_breakout, trend_confirmation, bb_squeeze_prebreakout}` 的每个信号：

取 `prior = dlist[-21:-1]`（前 20 根，排除候选突破根），`last = dlist[-1]`（末根）。

**多头方向（bull）**：
```
broke = (last_high > prior_max_high) or (last_close > prior_max_close)
if not broke:
    forged = True  # 末根 high/close 均未超前20根极值 → 伪突破
elif (last_high / prior_max_high - 1) > 50%:
    forged = True  # 末根 high 超前期 >50% → 疑似 spike 伪造
```

**空头方向（bear）**：
```
broke = (last_low < prior_min_low) or (last_close < prior_min_close)
if not broke:
    forged = True  # 末根 low/close 均未破前20根极值 → 伪突破
elif (prior_min_low / last_low - 1) > 50%:
    forged = True  # 末根 low 破前期 >50% → 疑似 spike 伪造
```

### 降级动作

命中 `forged` → 该信号被降级：
```python
r["signal_type"] = "false_breakout"
r["grade"] = "NOISE"
r["total"] = 0
r["_breakout_revalidated"] = False
r["_revalidate_reason"] = reason   # 如 "末根high/close均未超前20根极值(伪突破)"
```

> **实战效果**：2026-07-13 多个轮次扫描中，约 39~43 个品种被此门禁拦截降 NOISE（占全市场 60+ 品种的 60%+），有效过滤了"评分虚高但未真实突破"的噪声。

---

## 八、参数配置四层回落机制

所有评分参数通过 `resolve_param(section, key, symbol, chain, period)` 解析，回落链：

```
per_symbol[品种][周期]  →  per_chain[产业链][周期]  →  per_period[周期]  →  default
```

- **L4 default**：全局兜底，所有新品种/新周期自动继承（v2.3 权重在此层）
- **L3 per_period**：周期级覆盖（如 60m 成交量惩罚从轻 -3→-1，因子周期波动大）
- **L2 per_chain**：产业链级覆盖（当前为空，供产业链分组调优）
- **L1 per_symbol**：品种×周期最精确层，自优化器最终写入层

修改 `default` 层后重启扫描即生效；自优化器写 `per_symbol` / `per_chain` 层做精细化调参，不污染全局。

---

## 九、v2.3 权重调整对比（2026-07-13 实施）

**核心诉求**：FDT 进入辩论的品种，行情都已走得很远。需提升 DC20 突破 + BB 突破的评分权重，让"刚突破/刚逼近"的品种能及时进入辩论环节。

| 参数 | 旧值 | 新值（v2.3） | 影响 |
|:-----|:----:|:------------:|:-----|
| `dc20.break_base_score` | 30 | **40** | DC20 突破基础分提升 33% |
| `dc20.break_strong_bonus` | 10 | **15** | 强突破额外加分提升 |
| `dc20.break_moderate_bonus` | 5 | **8** | 中突破额外加分提升 |
| `dc20.near_breakout_ticks` | 5 | **7** | 逼近判定放宽至 7 ticks |
| `dc20.near_breakout_score` | 15 | **22** | 逼近分提升 47% |
| `bb.pos_extreme_score` | 6 | **20** | BB 极端突破权重提升 233% |
| `bb.pos_upper_score` | 4 | **15** | BB 上轨突破权重提升 275% |
| `bb.pos_lower_score` | -4 | **-15** | BB 下轨突破对称提升 |
| `bb.pos_extreme_lower_score` | -6 | **-20** | BB 极端下破对称提升 |

**调整后效果**：DC20 突破（40）与 BB 极端突破（20）成为独立触发信号。单凭 DC20 突破 + 逼近即可达 62 分（STRONG），无需等待行情走远。

---

## 十、实际计算示例

### 示例 1：螺纹钢 RB 向上突破（STRONG）

假设某日 RB 数据：
- `price = 3520`，`DC20_UPPER = 3480`，`DC20_POS = 0.95`
- `dc20_break = "up"`，`distance_pct = (3520/3480-1)×100 = 1.15%`（> 1.0% → strong）
- 成交量比 = 1.8（explosive）
- `DC55_POS = 0.88`（> 0.85 → +25），`DC55_TREND = "up"`（dc55_score=25≥0 → +10+5）
- `BB_POS = 1.08`（> 1.05 → +20），带宽 4.5%（> 4.0 → +6），一致（+2）

计算：
```
dc20_score = +40 (base) +15 (strong) +5 (pos_upper) = +60
dc55_score = +25 (pos) +10 (trend_base) +5 (align) = +40
dc_score   = +60 + 40 = +100
bb_score   = +20 (extreme) +6 (width_high) +2 (consistency) = +28
volume     = +10 (explosive, dc≥0)
total      = +100 + 28 + 10 = +138  → STRONG, bull, channel_breakout
```

### 示例 2：逼近未突破（near_breakout → 仍可达 WEAK）

假设某品种：
- `price` 距 DC20 上轨仅 3 ticks，`dc20_break = "none"`
- 成交量正常，DC55 中性，BB 中性

计算：
```
dc20_score = +22 (near_breakout tick级逼近)
dc55_score = 0
dc_score   = +22
bb_score   = 0
volume     = 0
total      = +22  → WEAK, bull, near_breakout
```
> v2.3 前：`near_breakout_score = 15` → total = 15 < 20 → NOISE，进不了辩论。
> v2.3 后：total = 22 ≥ 20 → WEAK，进入辩论视野。

### 示例 3：伪突破被拦截

某品种评分 total = +35（WATCH），`signal_type = channel_breakout`，但 P0-4 回验发现：
- `last_high = 3500`，`prior_max_high = 3510` → `last_high < prior_max_high`
- `last_close = 3495`，`prior_max_close = 3502` → `last_close < prior_max_close`
- `broke = False` → **伪突破**

降级：`signal_type = false_breakout`，`grade = NOISE`，`total = 0`。

---

## 十一、关键设计原则总结

1. **价格行为优先**：只用"是否真实穿越历史边界"判断趋势，不依赖滞后指标。
2. **ADX 已移除评分**：突破有效性不被趋势强度过滤；低 ADX 突破同样有效。
3. **事实先于评分**：实际突破的事实优先于分数高低，signal_type 必须反映真实突破。
4. **双闸门防假突破**：评分层（无量不授 base 分）+ P0-4 回验层（原始 K 线重校验）。
5. **v2.3 早跟踪**：DC20 突破（40）+ BB 突破（20）+ 逼近（22）成为独立触发信号，让刚启动的品种及时进入辩论。
6. **四层参数回落**：全局 default 调优 + 自优化器写 per_symbol/per_chain 精细化，互不影响。

---

*文档生成依据：`channel_breakout_strategy.py`（L1-560）、`scan_all.py` P0-4 门禁（L137-201）、`settings.py` CHANNEL_BREAKOUT_CONFIG（L339-438）+ SIGNAL_GRADE_THRESHOLDS（L311-314）。*
