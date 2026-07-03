---
name: quant-daily
version: 1.0.0
agent_created: true
description: 商品期货量化分析一体化skill — 数据采集+指标计算+L1-L4趋势信号评分。融合futures-data-search、commodity-trend-signal、technical-indicator-calc三skill能力，消除跨skill依赖。
---

# quant-daily — 商品期货量化分析一体化

## 定位

合并 `futures-data-search` + `commodity-trend-signal` + `technical-indicator-calc` 为一站式期货量化分析 skill。

内部按三层组织：**数据获取 → 指标计算 → 信号评分**，单向依赖，无循环引用。

## 目录结构

```
scripts/
├── scan_all.py                    # 全品种扫描入口
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
└── signals/                       # 信号评分层（依赖indicators）
    ├── scoring_system.py          # L1-L4四层打分
    ├── early_signal.py            # 早期信号检测
    ├── signal_screener.py         # 信号筛选
    ├── trade_plan.py              # 交易计划
    ├── term_basis.py              # 期限结构分析
    └── report.py                  # 报告生成
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

- **v1.0.1** (2026-07-03): [关键] 新增 `--symbols` 参数支持自定义品种扫描
  - 设计目的：消灭为特定品种集编写胶水脚本的需求
  - 辩论场景下：直接 `scan_all.py --symbols PK,RB`，禁止写自定义扫描脚本
- **v1.0.0** (2026-07-02): 初始版本
  - 合并 futures-data-search v4.1.0 + commodity-trend-signal v2.18.0 + technical-indicator-calc v2.4.2
  - 消除跨skill sys.path hack
  - 保持原有3个skill不动
