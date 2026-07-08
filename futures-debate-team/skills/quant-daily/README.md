# quant-daily — 商品期货量化分析一体化

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-2.11.0-orange)

**quant-daily** 是一套面向中国商品期货市场的量化分析系统，覆盖 **数据采集 → 指标计算 → 策略可插拔打分** 全流程。策略层已独立，新增策略只需新建一个文件。

- 覆盖 **62个主力品种**，14个板块
- 多周期支持：**日线/周线/月线/240m/120m/60m** 全周期扫描
- 子周期数据源：TDX(120m无数据)→AKShare分钟→东方财富→TqSDK(15s超时保护)
- 双轨数据源：**通达信TQ-Local**（实盘） + **AKShare**（回测）
- **策略可插拔**：`strategies/` 目录，`--strategy` 参数切换
- **默认策略**：**channel_breakout**（唐奇安DC20/DC55+布林带通道突破）
- **Data Quality Circuit Breaker**：7道全局防呆机制

## 快速开始

```bash
# L1-L4全品种扫描（默认·正确模式）
python scripts/scan_all.py

# 子周期扫描（v2.11.0+）
python scripts/scan_all.py --period 60m    # 1小时
python scripts/scan_all.py --period 120m   # 2小时
python scripts/scan_all.py --period 240m   # 4小时

# 列出可用策略
python scripts/scan_all.py --list-strategies

# 指定策略
python scripts/scan_all.py --strategy layered_l1l4

# 自定义品种
python scripts/scan_all.py --symbols PK,RB,B,UR

# 指定输出目录
python scripts/scan_all.py -o ./reports -p full_scan
```

## 策略可插拔架构

```
data/   →  indicators/   →   strategies/   →   scan_all.py
 不变       不变              可插拔              --strategy
```

### 当前策略

| 策略名 | 文件 | 状态 |
|:-------|:-----|:----|
| `layered_l1l4` | `strategies/layered_l1l4.py` | ✅ 默认（活跃） |
| `true_layered` | `strategies/true_layered.py` | ⛔ 已废弃 |

### 新增一个策略

```python
# strategies/my_new.py
from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy

class MyStrategy(BaseStrategy):
    @property
    def name(self): return "my_new"
    @property
    def display_name(self): return "我的新策略"
    def score(self, tech_list, mode, kline_data=None, df_map=None):
        # tech_list: 每个品种的tech dict（含ADX/RSI/MACD等44项指标）
        results = []
        for tech in tech_list:
            results.append(SignalResult(
                symbol=tech["symbol"], total=..., 
                direction="bull"/"bear", grade="WATCH", ...
            ))
        return {"all_ranked": [...], "bull_signals": [...], "bear_signals": [...]}

register_strategy(MyStrategy)

# 使用
# python scan_all.py --strategy my_new
```

无需修改 `data/` 和 `indicators/` 层的任何代码。

## L1-L4 四层打分权重

| 层 | 名称 | 权重 | 指标 |
|:--:|:----|:---:|:-----|
| L1 | 萌芽/资金结构 | **35** | OI变化、基差、期限结构、ROC |
| L2 | 量价领先 | **35** | Vortex、CCI、Supertrend、HMA |
| L3 | 价格结构 | **20** | RSI健康区、DMI方向、ADX趋势强度 |
| L4 | 确认信号 | **10** | 通道突破、均线排列、MACD金叉/死叉 |

否决项：ADX震荡、RSI极端、缩量、统计偏离（-20 ~ 0）

## CLI 参数

| 参数 | 说明 |
|:----|:-----|
| `--output, -o` | 输出目录 |
| `--prefix, -p` | 文件名前缀（默认 `full_scan`） |
| `--symbols, -s` | 指定品种（逗号分隔），如 `PK,RB,B,UR` |
| `--strategy` | 策略名（默认 `layered_l1l4`） |
| `--list-strategies` | 列出所有可用策略 |
| `--mode, -m` | [废弃] 旧版模式参数 |

输出：`{prefix}_{YYYYMMDD}.json` + `{prefix}_ranking_{YYYYMMDD}.html`

## 信号等级

| 等级 | 总分范围 | 含义 |
|:----|:--------:|------|
| **STRONG** | ≥ 75 | 最强信号，多层共振 |
| **WATCH** | 60-74 | 重点信号，方向一致 |
| **WEAK** | 40-59 | 信号质量一般 |
| **NOISE** | < 40 | 噪音，忽略 |

## 三级指标获取管道

```
第一优先: TdxCollector.get_indicators()  → formula_zb 44项（通达信100%对齐）
第二优先: tdx_bridge.patch_indicators()  → 35字段补丁
最后保障: calc_core.calculate_tdx_compatible() → numpy向量化，45字段
```

## 数据质量熔断器

| 检查项 | 阈值 | 后果 |
|:-------|:----:|:-----|
| 品种成功率 | ≥90% | 低于终止 |
| K线条数 | ≥30 | 不足跳过 |
| 时效性 | ≤5交易日 | 标注过期 |
| 成交量 | >0占比≥50% | 标注降级 |
| 扫描耗时 | ≤120秒 | 超限终止 |
| 降级次数 | ≤2次/品种 | 跳过 |
| 输出JSON | ≤5MB | 裁剪字段 |

## 目录结构

```
scripts/
├── scan_all.py              ← 策略入口（--strategy 切换）
├── strategies/              ← 策略可插拔层
│   ├── base.py              ← BaseStrategy 抽象基类
│   ├── registry.py          ← 注册器
│   ├── layered_l1l4.py      ← L1-L4策略（默认）
│   └── true_layered.py      ← 真分层（已废弃）
├── config/                  ← 品种列表 + 系统参数
├── data/                    ← 数据采集（多源降级）
├── indicators/              ← 指标计算（TDX桥接+numpy）
├── signals/                 ← 信号评分（旧）
└── backtest/                ← 回测框架

data/（用户数据目录）
├── futures.db               ← DuckDB 持久化
└── dominant_maps/           ← 主力合约映射
```

## 版本历史

- **v2.2.0** (2026-07-04): 策略可插拔架构 — `strategies/` 独立层 + registry
- **v2.1.1** (2026-07-04): L1-L4恢复为默认模式，废弃 true_layered --reverse
- **v2.1.0** (2026-07-04): 九宫格模糊分类器 + D7期限结构因子
- **v2.0.0** (2026-07-04): 真分层打分设为默认
- **v1.1.0** (2026-07-03): 权重优化，真分层评分系统
- **v1.0.0** (2026-07-02): 初始版本

## 许可

本项目基于 MIT 许可证开源。
