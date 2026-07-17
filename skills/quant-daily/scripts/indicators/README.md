---
name: technical-indicator-calc
version: 2.4.0
description: 技术指标计算最后保障 —
  通达信公式完全对齐。当TdxCollector.get_indicators()失败时，提供与通达信100%一致的numpy向量化计算。18组公式/44项指标，Wilder平滑/EMA/SMA参数完全对齐TDX。支持Donchian/Vortex/HMA/CMF/BB等高级指标。
agent_created: true
user_invocable: true
triggers:
  - 技术指标计算
  - 通达信指标降级
  - 最后保障指标
  - TDX fallback
  - MACD计算
  - RSI计算
  - 技术分析
  - 指标计算
  - 布林带
  - KAMA
  - SAR
  - 线性回归
  - 唐奇安通道
  - 涡流指标
  - 赫尔均线
  - 超级趋势
  - 资金流量
  - 量价背离
  - K线形态识别
disable: false
---

# Technical Indicator Calculator — Last Resort Fallback v2.4.0

## 定位：通达信指标的最后保障

本技能在整个指标获取管道中扮演**最后保障**角色：

```
┌─ 第一优先 ──────────────────────────────────────┐
│  TdxCollector.get_indicators()                  │
│  → 通达信TQ-Local formula_zb 直接获取 (44项)     │
│  → 与通达信客户端数值100%一致                    │
└─────────────────────────────────────────────────┘
                        ↓ 失败时
┌─ 第二优先 ──────────────────────────────────────┐
│  tdx_bridge.py (commodity-trend-signal)         │
│  → 委托TdxCollector，降级本地formula_zb直连      │
│  → 35字段补丁 (16+19新增)                       │
└─────────────────────────────────────────────────┘
                        ↓ 失败时
┌─ 最后保障 ──────────────────────────────────────┐
│  calc_technical_indicators.py ← 本技能          │
│  → numpy向量化计算，所有公式与通达信完全对齐      │
│  → Wilder平滑 / SMA/EMA 参数与TDX公式100%一致    │
│  → 输出字段名兼容TdxCollector.get_indicators()   │
└─────────────────────────────────────────────────┘
```

## 概述

通用技术指标计算工具，支持**45项**技术指标计算。覆盖 commodity-trend-signal 全部技术指标，兼容 技术分析评分四层打分系统。**引擎升级：pandas→numpy向量化，核心计算性能提升5-10x。**

**关键修正：使用正序数据（从旧到新）计算EMA/MACD，避免数据顺序错误。**

## 支持的技术指标（45项）

| 类别 | 指标 | 参数 | TA-Lib对应 | 说明 |
|------|------|------|-----------|------|
| **移动平均线** | MA | 5,10,20,60 | SMA | 简单移动平均 |
| | EMA | 12,26 | EMA | 指数移动平均 |
| **动量指标** | RSI | 14 | RSI | 相对强弱指数 |
| | STOCH | 9,6 | STOCH | 随机指标 |
| | STOCHRSI | 14 | STOCHRSI | 随机RSI |
| | Williams %R | 14 | WILLR | 威廉指标 |
| | CCI | 14 | CCI | 商品通道指数 |
| | ROC | 12 | ROC | 变动率 |
| | **PPO** ⭐ | 12,26,9 | PPO | 百分比价格振荡器 |
| **趋势指标** | MACD | 12,26,9 | MACD | 移动平均收敛发散 |
| | ADX | 14 | ADX | 平均趋向指数 |
| | **SAR** ⭐ | 0.02/0.20 | SAR | 抛物线转向（含多空判断） |
| | **SUPERTREND** ⭐ | 10,3.0 | — | 超级趋势（ATR动态通道） |
| | **DC(20/55)** ⭐ | 20,55 | — | 唐奇安通道（双周期） |
| | **DC55_TREND** ⭐ | 55 | — | 长周期通道方向 |
| | **VI± (Vortex)** ⭐ | 14 | — | 涡流指标（趋势方向+强度） |
| | **HMA** ⭐ | 10,20 | — | 赫尔移动平均（低延迟） |
| **波动率指标** | ATR | 14 | ATR | 平均真实波幅 |
| | **NATR** ⭐ | 14 | NATR | 归一化ATR（ATR/Close%） |
| | Highs/Lows | 14 | MIN/MAX | n日最高/最低 |
| | **Bollinger Bands** ⭐ | 20,2 | BBANDS | 布林带上/中/下轨 |
| | **BB_WIDTH** ⭐ | 20 | — | 布林带带宽（波动率） |
| | **BB_PCTB** ⭐ | 20 | — | %b价格在布林带中的位置 |
| | **BB_SQUEEZE** ⭐ | 20 | — | 挤压检测 |
| **综合指标** | Ultimate Oscillator | 7,14,28 | ULTOSC | 终极震荡指标 |
| | Bull/Bear Power | 13 | — | 多空力量 |
| | **MA_SLOPE** ⭐ | 20,5 | — | 均线斜率（线性回归） |
| | **HH/HL** ⭐ | 5 | — | 更高高点/更低低点模式 |
| | **VPD** ⭐ | 14 | — | 量价背离检测 |
| **资金流** | **CMF(21)** ⭐ | 21 | — | 蔡金资金流量（需volume） |
| **K线形态** | **Doji** ⭐ | — | CDLDOJI | 十字星检测 |
| | **Hammer** ⭐ | — | CDLHAMMER | 锤子线检测 |
| | **Engulfing** ⭐ | — | CDLENGULFING | 吞没形态检测 |
| **成交量** | **OBV** ⭐ | — | OBV | 能量潮（需volume） |
| | **MFI** ⭐ | 14 | MFI | 资金流量指数（需volume） |

> ⭐ = v2.0新增（基础），★ = v2.2新增（commodity-trend-signal兼容）

## 性能对比

| 计算场景 | v1.0 (pandas) | v2.0 (numpy) | 倍率 |
|---------|---------------|-------------|------|
| 4品种×29项指标 | ~2.5s | ~0.3s | **~8x** |
| 100品种×29项指标 | ~62s | ~8s | **~7.5x** |
| CCI单独计算 | ~0.4s | ~0.03s | **~13x** |

## ⚠️ 关键注意事项：数据顺序

### 问题描述

EMA（指数移动平均）和MACD等指标的计算**必须使用正序数据**（从旧到新）。如果使用倒序数据（从新到旧），会导致：

1. EMA计算错误（使用了"未来数据"）
2. MACD金叉/死叉判断错误
3. 柱状图方向错误

### 正确做法

```python
# ❌ 错误：使用倒序数据（最新数据在第一行）
data = pd.DataFrame({
    'date': ['2026-06-26', '2026-06-25', ...],  # 最新在前
    'close': [4103, 4041.6, ...]
})

# ✅ 正确：将数据转换为正序（从旧到新）
data_forward = data.iloc[::-1].reset_index(drop=True)
macd_line, signal_line, histogram = calculate_macd(data_forward['close'])
```

### 验证方法

计算完成后，检查：
1. MACD线和信号线的符号是否合理（通常在零轴附近）
2. 柱状图的方向是否与价格趋势一致
3. 金叉/死叉判断是否与实际走势匹配

## 使用方法

### 1. 直接调用脚本

```bash
python scripts/calc_technical_indicators.py
```

### 2. 作为模块导入

```python
from scripts.calc_technical_indicators import (
    analyze_metal,        # 全指标分析（推荐，返回45项指标）
    calculate_tdx_compatible,  # 输出兼容TdxCollector的44项指标 (v2.4.0)
    calculate_ma,
    calculate_rsi,
    calculate_macd,
    calculate_cci,
    calculate_atr,
    calculate_supertrend,
    calculate_vortex,
    calculate_hma,
    calculate_donchian,
    calculate_cmf,
    calculate_bollinger_bands,
    detect_doji,
    detect_hammer,
)

# 方式A：全指标分析（推荐）
import pandas as pd
df = pd.DataFrame({
    'open': [...], 'last': [...], 'high': [...], 'low': [...],
    'volume': [...]          # 可选
})
results = analyze_metal(df, "品种名称", has_volume=True)

# 方式B：单指标计算（数据需为正序，从旧到新）
ma5 = calculate_ma(price_series, 5)
rsi = calculate_rsi(price_series, 14)
macd_line, signal_line, histogram = calculate_macd(price_series)
```

## 输出格式

脚本输出JSON格式的技术指标数据（45项指标）：

```json
{
  "version": "2.2.0",
  "timestamp": "2026-06-28 08:52:00",
  "indicators_count": 45,
  "engine": "numpy-vectorized",
  "gold": {
    "price": 4103.0,
    "change": 61.40,
    "change_pct": 1.52,
    "indicators": {
      "ma5": 4099.94, "ma10": 4186.08, "ma20": 4271.01, "ma_trend": "震荡",
      "rsi": 37.65, "cci": -99.64, "atr": 124.74,
      "macd": -101.50, "macd_signal": -82.55, "macd_histogram": -18.96,
      "supertrend": 4588.34, "supertrend_dir": -1,
      "vi_plus": 0.804, "vi_minus": 1.143,
      "hma10": 4027.98,
      "dc_upper20": 4577.30, "dc_lower20": 3975.70,
      "bb_width": 14.05, "bb_pctb": 0.220, "bb_squeeze": false,
      "ma20_slope": -0.15,
      "hl_pattern": "HH",
      "doji": 0, "hammer": 0, "engulfing": 0,
      "obv": -126230, "mfi": 42.19,
      "cmf": null, "vpd": 0
    }
  }
}
```

完整的输出字段见 `analyze_metal()` 返回的dict。

## 信号判断规则

### MACD信号

| 状态 | 条件 | 含义 |
|------|------|------|
| **金叉形成** | MACD线从下向上穿过信号线 | 多头动能启动 |
| **死叉形成** | MACD线从上向下穿过信号线 | 空头动能启动 |
| **金叉延续** | MACD线 > 信号线（非今日形成） | 多头动能延续 |
| **死叉延续** | MACD线 < 信号线（非今日形成） | 空头动能延续 |

### 柱状图趋势

| 状态 | 条件 | 含义 |
|------|------|------|
| **红柱放大** | 柱状图 > 0 且绝对值增加 | 多头动能增强 |
| **红柱缩小** | 柱状图 > 0 且绝对值减少 | 多头动能减弱 |
| **绿柱放大** | 柱状图 < 0 且绝对值增加 | 空头动能增强 |
| **绿柱缩小** | 柱状图 < 0 且绝对值减少 | 空头动能减弱 |

### RSI信号

| 区间 | 状态 | 说明 |
|------|------|------|
| > 70 | 超买 | 注意回调风险 |
| 50-70 | 偏强 | 多头主导 |
| 30-50 | 偏弱 | 空头主导 |
| < 30 | 超卖 | 注意反弹机会 |

### CCI信号

| 区间 | 状态 | 说明 |
|------|------|------|
| > 100 | 超买 | 价格偏离均值+1个标准差 |
| -100 ~ 100 | 正常 | 价格在均值附近 |
| < -100 | 超卖 | 价格偏离均值-1个标准差 |

### SAR信号

| 状态 | 含义 |
|------|------|
| 价格在SAR上方 | 多头趋势 |
| 价格在SAR下方 | 空头趋势 |
| SAR翻转 | 趋势可能反转 |

### SUPERTREND信号

| 状态 | 含义 |
|------|------|
| 价格在SUPERTREND下方 | 多头趋势（上升通道） |
| 价格在SUPERTREND上方 | 空头趋势（下降通道） |
| 趋势翻转 | 价格穿越SUPERTREND线即反转 |

### 线性回归信号

| 斜率 | 含义 |
|------|------|
| > 0 | 整体趋势向上 |
| < 0 | 整体趋势向下 |
| 角度绝对值 | 趋势强度（单位：度） |

### 布林带信号

| 状态 | 含义 |
|------|------|
| 价格触及上轨 | 可能超买 |
| 价格触及下轨 | 可能超卖 |
| 带宽收窄 | 即将突破（Squeeze） |
| 带宽扩大 | 趋势延续 |

### K线形态信号

| 形态 | 含义 |
|------|------|
| **Doji** | 多空力量均衡，趋势可能反转 |
| **Hammer** | 下跌后出现，可能底部反转 |
| **Engulfing(多头吞没)** | 阳线吞没前阴，强反转信号 |
| **Engulfing(空头吞没)** | 阴线吞没前阳，强反转信号 |

### Vortex信号

| 状态 | 含义 |
|------|------|
| VI+ > VI- | 多头主导 |
| VI- > VI+ | 空头主导 |
| VI+ / VI- 交叉 | 趋势可能反转 |

### Donchian通道信号

| 状态 | 含义 |
|------|------|
| 价格突破DC20上轨 | 短期多头突破 |
| 价格跌破DC20下轨 | 短期空头突破 |
| DC55趋势向上 | 长期多头趋势 |
| DC55趋势向下 | 长期空头趋势 |

### 布林带辅助信号

| 状态 | 含义 |
|------|------|
| %b > 1.0 | 价格在上轨之上（超买） |
| %b < 0.0 | 价格在下轨之下（超卖） |
| %b = 0.5 | 价格在中轨 |
| BB_Squeeze=true | 带宽收窄，即将突破 |

## 文件结构

```
technical-indicator-calc/
├── SKILL.md                           # 本文件
├── _user_meta.json                    # 元数据
└── scripts/
    └── calc_technical_indicators.py   # 核心计算脚本
```

## 依赖

- Python 3.7+
- pandas
- numpy

## 版本历史

- **v2.4.0** (2026-07-02): 最后保障定位 + TDX字段兼容
  - 新增 `calculate_tdx_compatible()` 输出与TdxCollector兼容的44项指标
  - 明确管道定位：TDX直取→桥接→numpy计算(最后保障)
  - 所有公式与通达信完全对齐（Wilder平滑/参数/计算方法）
- **v2.3.0** (2026-06-29): 通达信公式统一
  - RSI/ADX/ATR切换为通达信Wilder平滑（SMA(X,N,1), alpha=1/N）
  - 新增 `_wilders_rma_numpy()` 辅助函数
  - 同步 `commodity-trend-signal` v2.14.2 指标计算
- **v2.2.0** (2026-06-28): 覆盖commodity-trend-signal全部技术指标
  - 新增DC(20/55)唐奇安通道 + DC55趋势方向
  - 新增VI±涡流指标（Vortex）
  - 新增HMA赫尔移动平均
  - 新增CMF蔡金资金流量（需volume）
  - 新增BB_WIDTH/BB_PCTB/BB_SQUEEZE布林带分析
  - 新增MA_SLOPE均线斜率
  - 新增HH/HL更高高点/更低低点模式
  - 新增VPD量价背离检测
  - 总量45项指标
- **v2.1.0** (2026-06-28): 新增SUPERTREND
  - 新增SUPERTREND超级趋势指标（10日/3.0倍ATR）
  - 总量30项指标
- **v2.0.0** (2026-06-28): 引擎全面升级
  - pandas→numpy向量化，性能提升5-10x
  - 新增10项指标（BBANDS/SAR/KAMA/LINEARREG/PPO/NATR/Doji/Hammer/Engulfing/OBV/MFI）
  - 新增 `analyze_metal()` 全指标分析入口
  - 新增K线形态识别模块（Doji/Hammer/Engulfing）
  - 新增成交量指标模块（OBV/MFI，需volume数据）
  - 修复 `_sma_numpy` NaN传播问题
  - 移除pandas `rolling().apply(lambda)` 性能瓶颈
  - 总量29项指标
- **v1.0.0** (2026-06-28): 初始版本
  - 19项基础技术指标
  - ⚠️ 数据顺序修正：EMA/MACD必须使用正序数据

---

**维护者**: CTAAgents  
**仓库**: [CTAAgents/quant-skills](https://github.com/CTAAgents/quant-skills)