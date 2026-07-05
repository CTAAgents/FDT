---
name: technical-analysis
version: 2.1.0
description: 技术面分析 skill v2.2.0 — 为辩论专家团·技术面研究员（观澜）提供ZigZag支撑阻力(硬软分类/ATR容差/失效条件/多周期共振/OI确认)+动态阈值量价+多时间框架趋势+事件日历+跨品种联动。
agent_created: true
user_invocable: false
triggers:
  - 技术面分析
  - 量价分析
  - 背离检测
  - 假突破验证
  - 席位资金流
  - 支撑阻力
---

# 技术面分析 v1.0.0

## 定位

独立 skill，专门为 **futures-debate-team** 的 **技术面研究员（观澜）** Agent 提供量价/持仓/背离/资金流的分析工具。
从 `quant-daily` 的 scan_all.py 获取原始数据后，调用本 skill 做技术面解读。

## 模块说明

| 模块 | 功能 | 核心函数 |
|:----|:----|:--------|
| `trend_analysis.py` | 趋势判定、动量检查（v2.0: 多时间框架） | `analyze_trend()`, `check_momentum()` |
| `volume_price.py` | 量价配合、假突破验证（v2.0: 动态阈值+中性描述） | `analyze_volume_price()`, `check_fake_breakout()` |
| `divergence.py` | 价量/价持仓/MACD/RSI背离 | `check_divergence()` |
| `flow_analysis.py` | 席位资金流、多空比 | `analyze_seat_flow()`, `estimate_long_short_ratio()` |
| `support_resistance.py` | **支撑/阻力位计算 v2.1（v2.0:硬软分类+ATR容差+失效条件+OI确认）** | `find_swing_points()`, `identify_key_levels()`, `calculate_poc()`, `cross_validate_timeframes()`, `_check_oi_confirmation()` |
| `event_calendar.py` | **事件日历mask（v2.1新增）** | `check_event_impact()`, `get_events_for_date()` |
| `cross_correlation.py` | **跨品种联动（v2.1新增）** | `calc_correlation()`, `get_correlation_peers()`, `build_correlation_matrix()` |

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
| `analyze_trend(symbol, kline_data, timeframe)` | 品种+可选的K线数据+时间框架 | MA排列/ADX/波段方向 |
| `check_momentum(symbol, rsi, cci)` | RSI14+CCI值 | 超买超卖判断 |
| `analyze_volume_price(oi_pct, price_pct, vol_ratio, reference_prices)` | 持仓变化/价格变化/量比/参考价序列 | 中性仓价解读（动态ATR阈值） |
| `check_fake_breakout(direction, vol_ratio, closes_after_breakout, breakout_price)` | 方向/量比/突破后K线收盘价序列/突破价 | 真假突破判定（自动收盘确认） |
| `check_divergence(price, vol, oi, macd, rsi)` | 各维度趋势方向 | 背离列表+严重度 |
| `analyze_seat_flow(net_long, change, direction, seats)` | 前20净多+变化+风向标 | 席位资金流解读 |
| `estimate_long_short_ratio(long_v, short_v)` | 多空成交量 | 多空比+解读 |
| `find_swing_points(highs, lows, lookback, rollover_indices)` | 高低点序列+换月跳空索引 | ZigZag拐点（前高前低+强度） |
| `identify_key_levels(highs, lows, closes, volumes, ma20, ma60, atr, oi_series)` | K线+均线+ATR+OI序列 | 支撑阻力数组（hardness/容差/失效条件/OI确认） |
| `calculate_poc(highs, lows, volumes)` | 高低点+成交量 | POC/VAH/VAL（成交量分布图） |
| `cross_validate_timeframes(daily, h1, m15)` | 日线/1H/15min关键位 | 共振标签+TF来源 |
| `check_event_impact(today, symbol)` | 日期+品种 | 事件影响+置信度折扣 |
| `get_correlation_peers(symbol, price_dict, window)` | 品种+价格字典+窗口 | 关联品种列表+相关系数 |

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

### v2.1.0 (2026-07-05)
- support_resistance.py v2.1: 硬/软分类(hard/medium/soft) + ATR容差带 + 失效条件标注 + 多周期共振验证 + OI/量能确认集成
- 新增 `event_calendar.py`: 全年宏观事件自动生成(FOMC/NFP/EIA/CPI/USDA)，品种受影响判断，置信度折扣
- 新增 `cross_correlation.py`: 滚动皮尔逊相关系数(20天窗口)，板块内关联品种查询，全品种相关性矩阵
- find_swing_points() 新增 rollover_indices 参数: 换月跳空附近的拐点自动屏蔽
- identify_key_levels() 新增 oi_series 参数: OI趋势+量比→hardness 升降调整
- SKILL.md 版本号和描述更新

### v2.0.0 (2026-07-05)
- 新增 support_resistance.py: ZigZag找前高前低 + Volume Profile(POC/VAH/VAL) + 价位聚合 + 强度标记
- trend_analysis.py 重写: 多时间框架支持(daily/60min/15min), ADX 5档分级, 均线4种状态
- volume_price.py 重写: 动态ATR阈值(按品种近20日ATR%计算), oi_price_direction改为中性描述, check_fake_breakout增加自动收盘确认
- 观澜 strict-prompt 更新: 加入新工具函数引用

### v1.0.0 (2026-07-04)
- 创建独立技术面分析 skill，解耦观澜对 quant-daily 的依赖
- 4模块：趋势判定/量价分析/背离捕捉/席位资金流
- 假突破验证专用函数
