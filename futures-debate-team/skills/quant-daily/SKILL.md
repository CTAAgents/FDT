---
name: quant-daily
version: 2.1.1
agent_created: true
description: 商品期货量化分析一体化skill — L1-L4四层累加打分。融合futures-data-search、commodity-trend-signal、technical-indicator-calc三skill能力。
---

# quant-daily — 商品期货量化分析一体化

## 🔴 重要：L1-L4为唯一正确模式（2026-07-04修正）

**默认模式**：`layered`（L1-L4四层累加打分，原有逻辑，向后兼容）

```bash
# L1-L4全品种扫描（正确模式·默认）
python scripts/scan_all.py

# 指定输出目录+文件前缀
python scripts/scan_all.py -o ./reports -p full_scan

# 自定义品种
python scripts/scan_all.py --symbols PK,RB,B,UR
```

> **⚠️ 禁止使用 scan_true_layered.py（包括 --reverse）**
>
> 2026-07-04 实盘验证：`true_layered`模式的 `--reverse` 参数导致6/62品种出现"因子方向与信号方向完全矛盾"的严重错误（如PK的D1趋势=93↑却被标为做空）。该模式的IC=-0.039(20日，胜率43%)回测统计不显著，产生大量虚假信号。已被回退。

## L1-L4四层打分权重

```python
WL1 = 35  # L1 萌芽/资金结构 — 趋势动量+持仓变化
WL2 = 35  # L2 量价领先 — 成交量+价格变动配合
WL3 = 20  # L3 价格结构 — ADX+RSI+均线排列
WL4 = 10  # L4 确认 — MACD金叉/死叉+突破+一致性
```

## scan_all.py CLI

| 参数 | 说明 | 示例 |
|:----|:-----|:-----|
| `--mode`, `-m` | 打分模式: `layered`(默认) / `true_layered` / `compare` | `-m layered` |
| `--output`, `-o` | 输出目录 | `-o ./reports` |
| `--prefix`, `-p` | 文件名前缀 | `-p full_scan` |
| `--symbols`, `-s` | 指定品种（逗号分隔），不传则全品种 | `-s PK,RB,B` |

## 权重配置（仅 L1-L4 传统模式使用）

```python
WL1 = 35  # L1 萌芽/资金结构
WL2 = 35  # L2 量价领先
WL3 = 20  # L3 价格结构
WL4 = 10  # L4 确认
```

**注意**：真分层打分不使用此权重配置。真分层使用`signals/true_layered_scoring.py`中的7因子等权投票 + 九宫格分类。

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
│   ├── true_layered_scoring.py    # 真分层打分核心引擎（7因子截面排序+九宫格分类）
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
  - 新增 true_layered_scoring 模块（7因子等权投票、否决降权、趋势成熟度）
  - 新增九宫格模糊分类器（高斯隶属度、左右侧识别）
  - 新增 D7 期限结构因子（term_signal）
  - 新增 scan_true_layered.py（通达信TDX实盘 + AKShare OI注入）
  - 新增 backtest/backtest_true_layered.py 回测框架（107截面×59品种）
  - 新增 `--reverse` 反向信号模式（IC为负，反向有效）
  - 新增合格信号筛选 + Agent JSON输出 + 九宫格side字段
  - SKILL.md 默认命令改为 `scan_true_layered.py --reverse`
  - 代码审计17轮（死代码清理、命名规范、编码兼容、bare except修复）
- **v1.0.1** (2026-07-03): [关键] 新增 `--symbols` 参数支持自定义品种扫描
  - 设计目的：消灭为特定品种集编写胶水脚本的需求
  - 辩论场景下：直接 `scan_all.py --symbols PK,RB`，禁止写自定义扫描脚本
- **v1.0.0** (2026-07-02): 初始版本
  - 合并 futures-data-search v4.1.0 + commodity-trend-signal v2.18.0 + technical-indicator-calc v2.4.2
  - 消除跨skill sys.path hack
  - 保持原有3个skill不动
