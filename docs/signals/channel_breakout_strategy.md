# 通道突破信号策略 — 详细逻辑

> FDT 核心信号引擎 · v1.3 · 对应源文件：`skills/quant-daily/scripts/strategies/channel_breakout_strategy.py`

---

## 一、策略定位

通道突破是 FDT 的核心信号引擎，**不依赖移动均线、MACD、RSI 等滞后指标**，直接以价格行为为核心，识别趋势启动与延续。

**设计哲学**：事实优先于评分 — 价格已突破 = signal_type 必须反映事实，评分只影响 grade（WATCH/STRONG）。

---

## 二、双重通道体系架构

```
┌─────────────────────────────────────────────────────────┐
│              Layer A: 唐奇安通道 (权重 75%)               │
│  ├── DC20 短期通道 — 价格突破20日边界 = 短期趋势启动      │
│  │   (40% × 75% = 30% 总分)                             │
│  └── DC55 中期通道 — 价格位置 + 趋势方向 = 中期趋势确认   │
│       (35% × 75% = 26.25% 总分)                         │
├─────────────────────────────────────────────────────────┤
│              Layer B: 布林带 (权重 25%)                   │
│  ├── B1: BB带宽扩张/收缩 (10%) — 波动率佐证              │
│  ├── B2: BB挤压检测 (5%) — 突破前兆预警                  │
│  └── B3: BB %b 位置 (10%) — 趋势强度佐证                 │
├─────────────────────────────────────────────────────────┤
│              成交量确认 (独立加减分，不单独成层)            │
└─────────────────────────────────────────────────────────┘
```

---

## 三、DC20 短期通道突破（Layer A1）

### 3.1 通道计算 — TDX REF 式

采用 **TDX REF 式通道**（关键区别：不含当前 bar）：

```python
# TDX 对齐: REF(HHV, 1) — 取前20根的HIGH最大值，不含当前bar
dc20_upper = np.max(highs[-21:-1])   # 前20根的HIGH最大值
dc20_lower = np.min(lows[-21:-1])    # 前20根的LOW最小值
```

DC20_POS = (close - lower) / (upper - lower)，范围 0-1。
- > 0.7 = 上轨附近
- < 0.3 = 下轨附近

### 3.2 突破检测 — 三层扫描（优先级递减）

#### 第一层：上游指标层检测

`analyze_targets.py` 从原始 K 线数据计算：

```
c_high >= DC20_UPPER  →  dc20_break = "up"
c_low  <= DC20_LOWER  →  dc20_break = "down"
否则                   →  dc20_break = "none"
```

#### 第二层：策略层 TDX REF 重判

当上游未填充 `dc20_break`（="none"）时，策略自身从 `df_map` 的原始 K 线重新计算 TDX REF 式边界并检测。

#### 第三层：实时报价突破 — 双源融合

支持 `quotes_map` 传入盘中实时报价，`last_price` 越过 DC20 边界时即时重判：

- 实时价突破 → `dc20_break_source = "realtime_quote"`
- 即使日线未突破，signal_type 也升级为 `channel_breakout`

### 3.3 评分因子（默认值）

| 因子 | 默认值 | 说明 |
|:-----|:------:|:-----|
| `break_base_score` | ±40.0 | 突破基础分 |
| `break_strong_bonus` | ±15.0 | 大幅突破（>1.0% 距边界）追加 |
| `break_moderate_bonus` | ±8.0 | 中等突破（>0.3%）追加 |
| `pos_upper_bonus` | +5.0 | 位置在上轨区（POS>0.7）加分 |
| `pos_lower_bonus` | -5.0 | 位置在下轨区（POS<0.3）减分 |

### 3.4 量能确认前置（v1.3 关键修复）

```
_avg_vol_20 = df["volume"].iloc[-20:].mean()
_vol_ratio  = volume / _avg_vol_20
_vol_ok     = _vol_ratio >= 0.8   # normal_lower_ratio
```

- `_vol_ok=True`：正常授 `break_base_score`
- `_vol_ok=False`：`dc20_break_strength = "weak_no_vol"`，仅记录突破事实，不给基础分

### 3.5 逼近判定 — "趋势前夜"识别（v2.3 增强）

#### 普通逼近

价格距 DC20 边界 ≤ 7 ticks → 加 ±22.0 分

#### 动量逼近（v2.3）

当当前 bar 满足以下条件之一时，检测窗口放宽至 14 ticks：

- 振幅 ≥ 1.2 × ATR
- 单边运行（|close - open| ≥ 0.6 × ATR）

识别为"结构性突破前兆"，同样加 ±22.0 分。

### 3.6 ADX 已移除评分（v1.3）

ADX 仅保留 `info_only` 显示，**不再作为评分依据**。理由：突破策略不应被趋势强度过滤。

---

## 四、DC55 中期通道确认（Layer A2）

### 4.1 通道计算

```python
dc55_upper = np.max(highs[-55:])   # 55根HIGH最大值
dc55_lower = np.min(lows[-55:])    # 55根LOW最小值
dc55_pos = (close - lower) / (upper - lower)  # 0-1 位置
```

### 4.2 趋势方向

两种计算方式：

**方式一（legacy_numpy）** — 用 MA20_SLOPE 方向：

```python
"up" if MA20_SLOPE > 0.01 else ("down" if MA20_SLOPE < -0.01 else "flat")
```

**方式二（time window / tdx_compat）** — 比较前后两段中点：

```python
mid_first = (max(highs[-55:-27]) + min(lows[-55:-27])) / 2
mid_last  = (max(highs[-27:]) + min(lows[-27:])) / 2
# mid_last > mid_first → "up"
```

### 4.3 评分因子

**位置评分**（遍历阈值从高到低匹配）：

| %b 位置范围 | 得分 | 标签 |
|:-----------|:----:|:-----|
| > 0.85 | +25.0 | extreme_upper |
| > 0.70 | +15.0 | upper |
| > 0.50 | +5.0 | mid_upper |
| < 0.15 | -25.0 | extreme_lower |
| < 0.30 | -15.0 | lower |
| < 0.50 | -5.0 | mid_lower |

**趋势方向**：

| 条件 | 得分 | 说明 |
|:-----|:----:|:-----|
| `trend_base_score` | ±10.0 | 方向基础分 |
| `trend_alignment_bonus` | ±5.0 | 方向与位置一致时追加 |
| `divergence_penalty` | ±10.0 | 方向与位置不一致时惩罚 |

---

## 五、布林带确认（Layer B，权重 25%）

### 5.1 BB 带宽扩张/收缩（10%）

| 带宽条件 | 得分 | 标签 |
|:---------|:----:|:-----|
| BB_WIDTH > 4.0% | ±6.0 | high volatility |
| BB_WIDTH > 2.5% | ±3.0 | moderate volatility |
| 否则 | 0 | low |

得分方向跟随 DC 总评分方向。

### 5.2 BB 挤压检测（5%）

当 `BB_WIDTH` 处于近60根K线的10%分位以下 → `bb_squeeze=True` → 加 +2.0 分，标记 `"breakout_pending"`。

### 5.3 BB %b 位置（10%）

| %b 位置 | 得分 | 标签 |
|:--------|:----:|:-----|
| > 1.05 | +20.0 | extreme overbought |
| > 1.00 | +15.0 | at upper |
| 0.70 ~ 1.00 | +2.0 | mid_upper |
| 0.15 ~ 0.30 | -2.0 | mid_lower |
| 0 ~ 0.15 | -15.0 | at lower |
| ≤ 0 | -20.0 | extreme oversold |

**一致性检查**：DC 方向与 BB %b 方向一致（DC>0 且 bb_pos>0.5）→ 追加 +2.0。

---

## 六、成交量确认（独立加减分）

| 成交量条件 | 得分 | 标签 |
|:----------|:----:|:-----|
| 当前量 > 20日均量 × 1.5 | ±10.0 | explosive |
| 当前量 > 20日均量 × 1.2 | ±5.0 | elevated |
| 0.8 ~ 1.2 | 0 | normal |
| < 0.8 | -3.0 | weak |

得分方向跟随 DC 方向。

**子周期覆盖**：

| 周期 | weak_penalty | normal_lower_ratio |
|:----|:------------:|:------------------:|
| daily | -3.0 | 0.8 |
| 120m | -2.0 | 0.6 |
| 60m | -1.0 | 0.5 |

---

## 七、综合评分与分级

### 7.1 总分公式

```
total_score = dc_score(75%) + bb_score(25%) + volume_score(独立)
```

各分量典型范围：dc_score ≈ [-50, 50], bb_score ≈ [-16, 16], vol_score ≈ [-10, 10]。

### 7.2 分级阈值

| 等级 | 条件 | 含义 |
|:----|:----:|:-----|
| **STRONG** | abs ≥ 50 | 进入辩论流程 |
| **WATCH** | abs ≥ 40 | 观察信号 |
| **WEAK** | abs ≥ 20 | 弱趋势 |
| **NOISE** | < 20 | 噪音过滤 |

### 7.3 信号类型判定

```
if abs(dc20_score) >= 30 AND abs(dc_total) >= 20:
    signal_type = "channel_breakout"       # 通道实质突破
elif abs(dc20_score) >= 10:
    signal_type = "near_breakout"          # 逼近（趋势前夜）
elif abs(dc55_score) >= 15:
    signal_type = "trend_confirmation"     # DC55趋势确认
elif bb_squeeze:
    signal_type = "bb_squeeze_prebreakout" # BB挤压（突破前兆）
else:
    signal_type = "minor_signal"           # 微弱信号
```

### 7.4 事实优先覆写（2026-07-11 JD 告警修复）

若 `dc20_break` 为 "up"/"down" 但 signal_type 被判定为 "near_breakout"，**强制升级为 "channel_breakout"**。评分低只影响 grade，不能歪曲突破事实。

### 7.5 方向判定

```
total_score > 0  →  direction = "bull"
total_score < 0  →  direction = "bear"
total_score = 0  →  direction = "neutral"
```

---

## 八、时间窗口缩放（window_mode="time"）

当使用分钟级 K 线时，将固定 bar 数缩放为等效天数：

```python
scale = trading_min_per_day(345min) / bar_min(周期分钟数)
dc20_period = int(20 × scale)       # 等效20个交易日的bar数
dc55_period = int(55 × scale)
ma60_period  = int(60 × scale)
```

不同周期的 bar_min：

| 周期 | bar_min |
|:----|:-------:|
| 1m | 1 |
| 5m | 5 |
| 15m | 15 |
| 30m | 30 |
| 60m | 60 |
| 120m | 120 |
| 240m | 240 |
| daily | 1440 |

---

## 九、参数回落链（四层覆盖）

所有参数通过 `resolve_param()` 实现四层回落：

```
L1: per_symbol(品种级) → L2: per_chain(产业链级) → L3: per_period(周期级) → L4: default(默认值)
```

当前 L1 和 L2 为空，仅在 L3 有 60m/120m 的 volume 覆盖。

配置位置：`skills/quant-daily/scripts/config/settings.py` 第 386-481 行。

### 默认参数完整清单

```python
"dc20": {
    "break_base_score": 40.0,        # 突破基础分
    "break_strong_pct": 1.0,         # 大幅突破阈值(%)
    "break_strong_bonus": 15.0,      # 大幅突破加减分
    "break_moderate_pct": 0.3,       # 中等突破阈值(%)
    "break_moderate_bonus": 8.0,     # 中等突破加减分
    "pos_upper_threshold": 0.7,      # 上轨附近阈值
    "pos_upper_bonus": 5.0,          # 上轨位置加分
    "pos_lower_threshold": 0.3,      # 下轨附近阈值
    "pos_lower_bonus": -5.0,         # 下轨位置减分
    "near_breakout_ticks": 7,        # 逼近判定tick数
    "near_breakout_score": 22.0,     # 逼近得分
},
"dc55": {
    "pos_thresholds": [...],         # 6档位置评分
    "trend_base_score": 10.0,
    "trend_alignment_bonus": 5.0,
    "divergence_penalty": 10.0,
},
"bb": {
    "width_high_threshold": 4.0,     "width_high_score": 6.0,
    "width_moderate_threshold": 2.5, "width_moderate_score": 3.0,
    "squeeze_bonus": 2.0,
    "pos_extreme_threshold": 1.05,   "pos_extreme_score": 20.0,
    "pos_upper_threshold": 1.0,      "pos_upper_score": 15.0,
    "pos_mid_upper_threshold": 0.7,  "pos_mid_upper_score": 2.0,
    "pos_mid_lower_threshold": 0.15, "pos_mid_lower_score": -2.0,
    "pos_lower_score": -15.0,
    "pos_extreme_lower_score": -20.0,
    "dc_consistency_bonus": 2.0,
},
"volume": {
    "ma_period": 20,
    "explosive_ratio": 1.5,  "explosive_score": 10.0,
    "elevated_ratio": 1.2,   "elevated_score": 5.0,
    "normal_lower_ratio": 0.8,
    "weak_penalty": -3.0,
},
```

---

## 十、范式注册与验证器

通道突破范式注册于 `skills/quant-daily/scripts/signals/paradigms/breakout.py`：

| 属性 | 值 |
|:-----|:----|
| 范式ID | `breakout` |
| 覆盖 signal_type | `channel_breakout`, `trend_confirmation`, `bb_squeeze_prebreakout`, `near_breakout` |
| 计算引擎 | `strategies.channel_breakout_strategy.ChannelBreakoutStrategy` |

**关联验证器**：

| signal_type | 验证器 |
|:------------|:-------|
| channel_breakout | p0_4_raw_kline, volume_confirm, atr_vol_timing, trend_direction |
| trend_confirmation | p0_4_raw_kline, trend_direction, stability |
| near_breakout | volume_confirm, atr_vol_timing |
| bb_squeeze_prebreakout | (无) |

---

## 十一、数据流全链路

```
原始K线 (通达信/东方财富/AKShare)
    ↓
futures_data_core/indicators/legacy_numpy.py: calculate_tech_indicators()
  → DC20_UPPER / LOWER / POS
  → DC55_UPPER / LOWER / POS / TREND
  → BB_UPPER / MIDDLE / LOWER / PCTB / WIDTH_PCT / SQUEEZE
  → ATR14, ADX14 (仅显示)
    ↓
analyze_targets.py: c_high >= DC20_UPPER → dc20_break
    ↓
channel_breakout_strategy.py: score()
  → ① 读取上游指标 & df_map 原始K线
  → ② TDX REF 重判 (上游未填充时)
  → ③ 量能确认前置检查
  → ④ DC20评分 (层级A1)
  → ⑤ DC55评分 (层级A2)
  → ⑥ BB评分 (层级B)
  → ⑦ 成交量评分
  → ⑧ 实时报价双源融合 (quotes_map)
  → ⑨ 综合评分 → 分级 → 信号类型
    ↓
输出: { all_ranked[], bull_signals[], bear_signals[], _meta }
    ↓
下游: debate_brief.py → 多空辩论 → 闫判官裁决
```

---

## 十二、更新历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| v1.0 | - | 初始双通道突破策略 |
| v1.3 | - | 移除ADX评分；增加量能确认前置；TDX REF式通道对齐 |
| v2.3 | - | 提高DC20基础分(30→40)；动量逼近识别；BB极端权重提升 |
| - | 2026-07-11 | 事实优先覆写修复（JD告警） |
