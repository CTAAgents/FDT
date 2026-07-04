---
name: technical-analysis
version: 1.0.0
description: 技术面分析 skill v1.0.0 — 为辩论专家团·技术面研究员（观澜）提供趋势判定、量价分析、背离捕捉、席位资金流、假突破验证的独立分析工具。
agent_created: true
user_invocable: false
triggers:
  - 技术面分析
  - 量价分析
  - 背离检测
  - 假突破验证
  - 席位资金流
---

# 技术面分析 v1.0.0

## 定位

独立 skill，专门为 **futures-debate-team** 的 **技术面研究员（观澜）** Agent 提供量价/持仓/背离/资金流的分析工具。
从 `quant-daily` 的 scan_all.py 获取原始数据后，调用本 skill 做技术面解读。

## 模块说明

| 模块 | 功能 | 核心函数 |
|:----|:----|:--------|
| `trend_analysis.py` | 趋势判定、动量检查 | `analyze_trend()`, `check_momentum()` |
| `volume_price.py` | 量价配合、假突破验证 | `analyze_volume_price()`, `check_fake_breakout()` |
| `divergence.py` | 价量/价持仓/MACD/RSI背离 | `check_divergence()` |
| `flow_analysis.py` | 席位资金流、多空比 | `analyze_seat_flow()`, `estimate_long_short_ratio()` |

## 🔴 边界约束

- ❌ 不下多空结论（verdict=null 强制校验）
- ❌ 不做交易计划
- ❌ 不参与辩论
- ✅ 只提供量价持仓事实，供多空双方取用
- ✅ 突破必须标注是否带量
- ✅ 持仓变化必须区分多空方向
- ✅ 背离必须标清级别

## 观澜 Agent 接口

当 `futures-debate-team` 的 **观澜** Agent 加载本 skill 时，按以下方式使用工具：

```json
{"module": "technical-analysis.scripts.trend_analysis", "func": "analyze_trend", "args": {"symbol": "RB", "kline_data": {...}}}
```

### 工具函数一览

| 函数 | 输入 | 输出 |
|:----|:----|:----|
| `analyze_trend(symbol, kline_data)` | 品种+可选的K线数据 | MA排列/ADX/波段方向 |
| `check_momentum(symbol, rsi, cci)` | RSI14+CCI值 | 超买超卖判断 |
| `analyze_volume_price(oi_pct, price_pct, vol_ratio)` | 持仓变化/价格变化/量比 | 仓价配合解读 |
| `check_fake_breakout(direction, vol_ratio, confirmed, tests)` | 方向/量比/确认/测试次数 | 真假突破判定 |
| `check_divergence(price, vol, oi, macd, rsi)` | 各维度趋势方向 | 背离列表+严重度 |
| `analyze_seat_flow(net_long, change, direction, seats)` | 前20净多+变化+风向标 | 席位资金流解读 |
| `estimate_long_short_ratio(long_v, short_v)` | 多空成交量 | 多空比+解读 |

## 使用方法

```python
from technical_analysis.scripts.trend_analysis import analyze_trend
from technical_analysis.scripts.volume_price import check_fake_breakout
from technical_analysis.scripts.divergence import check_divergence

# 趋势判定
trend = analyze_trend("RB", {"ma20": 3100, "ma60": 3200, "ma250": 3300, "adx": 50})

# 假突破验证
breakout = check_fake_breakout("up", 2.5, True)

# 背离检测
div = check_divergence(price_trend="up", volume_trend="down", macd_trend="down")
```

## 版本历史

### v1.0.0 (2026-07-04)
- 创建独立技术面分析 skill，解耦观澜对 quant-daily 的依赖
- 4模块：趋势判定/量价分析/背离捕捉/席位资金流
- 假突破验证专用函数
