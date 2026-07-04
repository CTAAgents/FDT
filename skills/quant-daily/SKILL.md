---
name: quant-daily
version: 2.0.0
agent_created: true
description: 商品期货量化分析一体化skill — 真分层打分(True Layered Portfolio Sort) + 反向交易信号。融合futures-data-search、commodity-trend-signal、technical-indicator-calc三skill能力。默认使用AKShare OI数据+通达信TDX指标补丁。
---

# quant-daily — 商品期货量化分析一体化

## 默认扫描：真分层打分（2026-07-04 设为默认）

**默认模式**：`true_layered`（取代原有L1-L4阶段打分）

```bash
# 全品种真分层扫描 + 反向交易信号（默认）
python scripts/scan_true_layered.py --reverse

# 扫描并输出JSON/HTML
python scripts/scan_true_layered.py --reverse -o ./reports
```

**数据源方案**（回测AKShare vs 实盘TDX 双轨制）：
| 场景 | 价量数据 | OI持仓量 | 技术指标 |
|:---|:--------|:--------|:--------|
| 实盘信号 | 通达信TQ-Local | AKShare注入 | TDX bridge补丁 |
| 回测/训练 | AKShare | AKShare自带 | TDX bridge补丁 |

实盘命令：`scan_true_layered.py --reverse`（如上）
回测命令：`python -m backtest.backtest_true_layered`（自动走AKShare）

**策略定位**：截面均值回归（Contrarian）
- 排名高的品种 = 最超买 → 做空（预期下跌）
- 排名低的品种 = 最超卖 → 做多（预期上涨）
- 持仓5-10个交易日，等权分配，±3%止损

**因子法官席**（7独立裁判·全部全场景活跃）：
| # | 风格 | 因子 | 原始指标 |
|:-:|:---|:---|:--------|
| D1 | 趋势 | ROC10 | 最近10日变化率 |
| D2 | 回归 | -BIAS乖离率 | 价格偏离MA20的负值 |
| D3 | 回归 | -(RSI14-50) | RSI以50为中点的反向 |
| D4 | 资金 | OI_CHANGE_PCT | 持仓量变化率 |
| D5 | 资金 | CMF21 | 21日资金流量 |
| D6 | 确认 | 放量×方向 | 量比乘以价格变动方向 |
| D7 | **期限** | **term_signal** | **期限结构方向(contango~/backwardation~)** |

**回测绩效**（107截面×59品种，AKShare数据，2026-07-04修正）：
| 持有期 | IC均值 | IC胜率 | t值 | Top10多空价差 |
|:-----:|:-----:|:-----:|:---:|:------------:|
| 5日 | -0.004 | 46% | -0.21 | -0.06% |
| 10日 | -0.028 | 47% | -1.70 | -0.32% |
| 20日 | **-0.039** | 43% | **-2.33** | **-0.75%** |

> 旧27截面回测（IC=+0.09）因样本量不足严重过拟合。107截面结果表明仅20日持有期IC统计显著，策略需重构因子后方可交易。

## 权重配置（仅 L1-L4 传统模式使用）

```python
WL1 = 35  # L1 萌芽/资金结构
WL2 = 35  # L2 量价领先
WL3 = 20  # L3 价格结构
WL4 = 10  # L4 确认
```

**注意**：真分层打分不使用此权重配置。真分层使用`signals/true_layered_scoring.py`中的6因子等权投票。

---

## 回测框架

`scripts/backtest/` 目录包含回测工具：

| 文件 | 用途 | 用法 |
|------|------|------|
| `backtest_true_layered.py` | **真分层回测（主框架）** | `python -m backtest.backtest_true_layered` |
| `evaluate.py` | 历史回放评估（遗留 L1-L4） | `python -m scripts.backtest.evaluate` |
| `optimize_weights.py` | 权重网格搜索（遗留 L1-L4） | `python -m scripts.backtest.optimize_weights` |
| `run_backtest.py` | 全量回测多截面（遗留） | `python -m scripts.backtest.run_backtest` |

**推荐**：所有新回测使用 `backtest_true_layered.py`（AKShare数据源，多截面多空评估，IC分析）。

---

## Data Quality Circuit Breaker（全局强制）

| 防呆机制 | 规则 | 触发后果 |
|:---------|:----|:---------|
| 品种扫描成功率 | **≥90%**（62品种中至少56品种成功） | 低于则标注"数据不完整"并终止评分 |
| 单品种K线条数 | **≥30条** | 不足30条K线的品种标记"数据不足"并跳过评分 |
| 数据时效性 | 最新K线日期与运行日期**间隔≤5个交易日** | 超间隔标注"数据过期"并降级评分 |
| 成交量有效性 | volume字段必须存在且>0的K线占比**≥50%** | 低于则标注"成交量数据质量差" |
| scan_all.py运行时间 | 全量扫描**≤120秒** | 超限终止并输出已有结果 |
| 多源降级次数 | 单品种降级次数**≤2次** | 超限标记"数据源耗尽，跳过" |
| 输出JSON大小 | **≤5MB** | 超限裁剪低频/无用字段 |

**数据质量分级**（每次扫描输出时在`_meta`中标注）：
- [OK] **正常**: 成功率≥95% + 时效正常 + 成交量完整
- [!] **降级**: 成功率90-94% 或 时效延迟1-3天
- [x] **不可用**: 成功率<90% 或 时效延迟>5天

## 定位

合并 `futures-data-search` + `commodity-trend-signal` + `technical-indicator-calc` 为一站式期货量化分析 skill。

内部按三层组织：**数据获取 → 指标计算 → 信号评分**，单向依赖，无循环引用。

## 目录结构

```
scripts/
├── scan_all.py                    # 全品种扫描入口（L1-L4 / true_layered 双模式）
├── scan_true_layered.py           # 真分层打分入口（TDX实盘+AKShare OI注入）
├── config/                        # 配置层（零依赖）
│   ├── symbols.py                 # 62品种列表 + 交易所映射
│   └── settings.py                # 系统参数配置
├── data/                          # 数据获取层（依赖config）
│   ├── multi_source_adapter.py    # 统一调度 + 多源降级
│   ├── duckdb_store.py            # DuckDB存储引擎
│   ├── data_source_config.py      # 数据源YAML配置
│   ├── data_freshness_monitor.py  # 数据新鲜度监控
│   ├── dominant_mapping.py        # 主力合约映射算法
│   └── collectors/
│       ├── tdx_collector.py       # 通达信TQ-Local HTTP采集器
│       └── eastmoney_collector.py # 东方财富API采集器
├── indicators/                    # 指标计算层（依赖config，不依赖data）
│   ├── tdx_bridge.py              # formula_zb桥接器
│   ├── calc_core.py               # numpy向量化（通达信100%对齐，45字段）
│   └── core.py                    # 统一指标引擎（待合并）
├── signals/                       # 信号评分层（依赖indicators）
│   ├── true_layered_scoring.py    # 真分层打分核心引擎（6因子截面排序）
│   ├── scoring_system.py          # L1-L4四层打分（遗留）
│   ├── early_signal.py            # 早期信号检测
│   ├── signal_screener.py         # 信号筛选
│   ├── trade_plan.py              # 交易计划
│   ├── term_basis.py              # 期限结构分析
│   └── report.py                  # 报告生成
└── backtest/                      # 回测框架
    ├── backtest_true_layered.py   # 真分层回测（AKShare，多截面多空评估）
    ├── evaluate.py                # 历史回放评估
    ├── optimize_weights.py        # 权重网格搜索
    ├── run_backtest.py            # 全量回测（遗留）
    └── daily_signal_tracker.py    # 实盘信号追踪
```

## 三级指标获取管道

```
第一优先: TdxCollector.get_indicators()  → formula_zb直取，44项
第二优先: tdx_bridge.patch_indicators()  → 委托TdxCollector，35字段补丁
最后保障: calc_core.calculate_tdx_compatible() → numpy向量化，45字段
```

## 使用方法

详见 [USER_GUIDE.md](USER_GUIDE.md)

```bash
# 全品种信号扫描
python scripts/scan_all.py

# 自定义品种扫描（消除胶水脚本，2026-07-03新增）
python scripts/scan_all.py --symbols PK,RB,B,UR

# 指定输出目录
python scripts/scan_all.py -o /path/to/output -p custom_scan --symbols PK,RB
```

> **设计原则**：`--symbols` 参数的设计目的就是消灭"为特定品种集写胶水脚本"的需求。任何辩论场景下如需扫描指定品种，应直接调用 `scan_all.py --symbols`，不得自行编写 `phase1_custom_scan.py` 之类的一次性脚本。

## 版本历史

- **v2.0.0** (2026-07-04): 真分层打分设为默认
  - 新增 true_layered_scoring 模块（6因子等权投票、ADX风格感知、否决降权）
  - 新增 scan_true_layered.py（通达信TDX实盘 + AKShare OI注入）
  - 新增 backtest/backtest_true_layered.py 回测框架（AKShare 27截面）
  - 新增 `--reverse` 反向信号模式（IC为负，反向有效）
  - 新增合格信号筛选 + Agent JSON输出
  - SKILL.md 默认命令改为 `scan_true_layered.py --reverse`
- **v1.0.1** (2026-07-03): [关键] 新增 `--symbols` 参数支持自定义品种扫描
  - 设计目的：消灭为特定品种集编写胶水脚本的需求
  - 辩论场景下：直接 `scan_all.py --symbols PK,RB`，禁止写自定义扫描脚本
- **v1.0.0** (2026-07-02): 初始版本
  - 合并 futures-data-search v4.1.0 + commodity-trend-signal v2.18.0 + technical-indicator-calc v2.4.2
  - 消除跨skill sys.path hack
  - 保持原有3个skill不动
