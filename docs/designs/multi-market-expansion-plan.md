# FDT 全市场辩论扩展 — Phase 0~3 实施计划

> 基于 [multi-market-expansion-feasibility.md](multi-market-expansion-feasibility.md) 的 Phase 0-3 详细设计
> 创建: 2026-07-26 | 目标版本: v10.6.0
> 关联文档: [01-architecture.md](../harness/01-architecture.md), [delegation-protocol.md](delegation-protocol.md)

---

## 1. 目标范围

本次实施新增三种市场类型：

| 类型 | 品种示例 | 当前状态 | 目标 |
|:-----|:---------|:---------|:-----|
| **股指期货** | IF, IC, IH, IM | 已注册为"金融期货"，但无辩论记录，被当作商品期货处理 | 正确的宏观驱动分析，跳过链证源/供需 |
| **国债期货** | T, TF, TS, TL | 同股指期货 | 债市分析方法（收益率曲线/货币政ce） |
| **ETF** | 510050.SH, 159915.SZ 等 | 完全不存在于系统中 | 新增品种索引 + 数据源 + 因子 |

**非目标：** 股票(A股)、REITs、可转债（后续 Phase）

---

## 2. 改造影响评估

### 2.1 无需修改的组件

| 组件 | 理由 |
|:-----|:------|
| LangGraph 编排 (`graph.py`) | 状态机与市场类型无关 |
| 六阶段辩论框架 | 多空攻防框架通用 |
| P4 闫判官裁决 | 推理逻辑市场无关 |
| P3.5 品藻质检 | Schema 校验市场无关 |
| P6 报告模板 | HTML 框架可复用 |
| 自进化闭环 | APM-CS/RHI 市场无关 |
| Memory 系统 | MemoryManager 市场无关 |
| LLM 适配层 | 市场无关 |
| K 线级清洗 (OHLC/去重/离群值) | 市场无关 |

### 2.2 需要修改的组件

| 组件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `data_adapter/__init__.py` + 新增 `classifier.py` | 中 | 新增品种分类路由 |
| `data_adapter/akshare_source.py` | 中 | 扩展 ETF 数据接口 |
| `fdt_langgraph/state.py` | 小 | 新增 `market_type` 字段 |
| `fdt_langgraph/_nodes_prepare.py` | 中 | 注入市场类型到 state |
| `fdt_langgraph/_nodes_context.py` | 中 | Agent prompt 市场上下文注入 |
| `fdt_langgraph/_nodes_research.py` | 小 | 跳过链证源（金融期货） |
| `fdt_langgraph/_nodes_verdict.py` | 小 | 风控参数按市场类型调整 |
| `memory/knowledge/variety_index.json` | 小 | 新增 ETF 品种索引 |
| `memory/rules/` | 小 | 新增市场规则集 |

### 2.3 需要新增的组件

| 文件 | 说明 |
|:-----|:------|
| `data_adapter/instrument_classifier.py` | 品种分类器（识别 market_type） |
| `data_adapter/sources/etf_source.py` | ETF 专属数据源（NAV/折溢价/持仓） |
| `data_adapter/factors/etf_factors.py` | ETF 因子（跟踪误差/份额变化） |
| `tests/data_adapter/test_classifier.py` | 分类器单元测试 |

---

## 3. 架构变更

### 3.1 市场类型定义

```python
# data_adapter/instrument_classifier.py
from enum import Enum

class MarketType(str, Enum):
    COMMODITY_FUTURES = "commodity_futures"   # 商品期货（现有）
    INDEX_FUTURES = "index_futures"           # 股指期货（新增）
    BOND_FUTURES = "bond_futures"            # 国债期货（新增）
    ETF = "etf"                               # ETF（新增）
```

### 3.2 分类规则

```yaml
# instrument_classifier 分类逻辑
classification_rules:
  index_futures:
    symbols: [IF, IC, IH, IM]
    exchange: CFFEX
    logic: "代码匹配 + 交易所 CFFEX"
  bond_futures:
    symbols: [T, TF, TS, TL]
    exchange: CFFEX
    logic: "代码匹配 + 交易所 CFFEX"
  etf:
    suffix: [".SH", ".SZ"]
    logic: "代码含.SH或.SZ后缀，且品种索引标记为ETF"
```

### 3.3 State 扩展

```python
# fdt_langgraph/state.py 新增字段
market_type: NotRequired[MarketType]  # "commodity_futures" / "index_futures" / "bond_futures" / "etf"
```

### 3.4 数据管线差异

| 数据维度 | 商品期货 | 股指期货 | 国债期货 | ETF |
|:---------|:---------|:---------|:---------|:----|
| **K 线** | ✅ AKShare | ✅ AKShare | ✅ AKShare | ✅ AKShare |
| **基差** | ✅ 期货-现货 | ❌ 不适用 | ❌ 不适用 | ❌ 不适用 |
| **期限结构** | ✅ 近远月价差 | ❌ 不适用 | ✅ 收益率曲线 | ❌ 不适用 |
| **仓单** | ✅ 交割库仓单 | ❌ 不适用 | ❌ 不适用 | ❌ 不适用 |
| **持仓排名** | ✅ 期货公司排名 | ✅ 期货公司排名 | ✅ 期货公司排名 | ❌ 不适用 |
| **资金流向** | ✅ 多空比 | ✅ 多空比 | ✅ 多空比 | ✅ 份额变化 |
| **基本面** | 供需/库存/利润 | 宏观经济/估值 | 货币政策/CPI | 成分股/指数 |
| **外盘** | LME/COMEX 等 | 境外股指期货 | 境外国债期货 | 境外 ETF |

### 3.5 Agent 调度差异

| Agent | 商品期货 | 股指期货 | 国债期货 | ETF |
|:------|:---------|:---------|:---------|:----|
| **链证源** | ✅ 产业链分析 | ❌ 跳过 | ❌ 跳过 | ❌ 跳过 |
| **观澜** | ✅ 技术面 | ✅ 技术面 | ✅ 技术面 | ✅ 技术面 |
| **探源** | ✅ 供需/库存 | ✅ 宏观/估值 | ✅ 货币/利率 | ✅ 指数/持仓 |
| **读心** | ✅ 新闻情绪 | ✅ 新闻情绪 | ✅ 新闻情绪 | ✅ 新闻情绪 |

---

## 4. Agent Prompt 变更

### 4.1 探源 Prompt 扩展

当前探源 prompt （`_nodes_research.py` 第 475 行）仅支持商品期货的供需分析。
扩展为按市场类型注入不同的分析指令：

```python
# 在 node_fundamental() 中追加
market_analysis_instructions = {
    "index_futures": """
【股指期货特别说明】
- 基本面分析重心：宏观经济（PMI/GDP/CPI）、货币政策（利率/准备金）、
  财政政策、市场估值（PE/PB）、资金面（北向/两融）
- 不做供需平衡分析，不做库存周期分析
- 关注成分股结构、权重股表现、行业轮动
- leading_signals 应为宏观领先指标（社融/信贷/PMI 新订单）
""",
    "bond_futures": """
【国债期货特别说明】
- 基本面分析重心：货币政ce（OMO/MLF/LPR）、通胀（CPI/PPI）、
  经济增长预期、财政赤字、信用利差、收益率曲线形态
- 不做供需平衡分析，不做库存周期分析
- 关注期限利差（10-2Y）、中美利差、银行间流动性
- leading_signals 应为利率领先指标（CPI/PPI/社融）
""",
    "etf": """
【ETF 特别说明】
- 基本面分析重心：标的指数估值（PE/PB）、成分股结构、权重集中度、
  行业分布、溢价率/折价率、份额变化趋势
- 分析跟踪误差、流动性（日均成交额）
- 不做供需/库存/基差分析
- leading_signals 应为指数驱动因素
""",
}
```

### 4.2 观澜 Prompt 扩展

当前观澜 prompt 通用技术分析框架，需追加市场参数：

```python
market_technical_params = {
    "index_futures": "趋势判断应结合成分股指数结构",
    "bond_futures": "注意国债期货的 CTD 券转换和交割月效应",
    "etf": "注意折溢价对技术分析的干扰",
}
```

### 4.3 链证源跳过

```python
# 在 graph.py 的 _get_p3_node_names() 中
def _get_p3_node_names(mode: str, market_type: str = "commodity_futures") -> list[str]:
    p3 = []
    # 链证源仅适用于商品期货
    if market_type == "commodity_futures":
        p3.append("chain")
    ...
```

---

## 5. ETF 新增数据源

### 5.1 AKShare ETF 接口

AKShare 提供以下 ETF 相关函数（可直接复用现有 `akshare_source.py` 的数据获取模式）：

| AKShare 函数 | 返回数据 | FDT 用途 |
|:-------------|:---------|:---------|
| `fund_etf_hist_em()` | ETF 日 K 线（含净值） | K 线 + NAV 历史 |
| `fund_etf_spot_em()` | ETF 实时行情 | 最新价 + 折溢价 |
| `fund_etf_fund_info_em()` | ETF 基本信息 | 基金管理人/成立日 |
| `fund_etf_portfolio_hold()` | ETF 持仓 | 成分股权重 |

### 5.2 ETF 品种索引

在 `variety_index.json` 中新增 ETF 条目：

```json
{
  "510050": {
    "name": "上证50ETF",
    "exchange": "SH",
    "chain": "ETF-指数",
    "market_type": "etf",
    "profile": true,
    "drivers": true,
    "patterns": false,
    "key_levels": false,
    "data_quality": true,
    "total_debates": 0,
    "effective_patterns": 0
  }
}
```

---

## 6. 实施步骤

### Step 1: 品种分类器

**文件:** `data_adapter/instrument_classifier.py`
**改动:** 新增 ~80 行
**测试:** 6 个用例（IF=股指, T=国债, RB=商品, 510050.SH=ETF, 未知→默认商品）
**影响:** 无，纯新增文件，不影响现有代码

### Step 2: State 扩展

**文件:** `fdt_langgraph/state.py`
**改动:** 新增 `market_type` 字段（1 行）
**影响:** 无，可选字段，不存在时默认商品期货

### Step 3: 数据准备节点注入 market_type

**文件:** `fdt_langgraph/_nodes_prepare.py`
**改动:** 在 `node_prepare_data` 中调用 classifier，注入 state.market_type（~20 行）
**影响:** 所有品种在 P0 阶段获得正确的市场类型标签

### Step 4: Agent Prompt 注入

**文件:** `fdt_langgraph/_nodes_context.py`
**改动:** 在 `_build_market_fundamental_context` 中追加市场类型指令区块（~40 行）
**影响:** 探源 Agent 收到正确的分析框架

### Step 5: 链证源跳过

**文件:** `fdt_langgraph/graph.py`, `fdt_langgraph/agents.py`
**改动:** `_get_p3_node_names` 接收 market_type 参数，非商品期货跳过链证源（~10 行）
**影响:** 金融期货和 ETF 不再触发产业链分析

### Step 6: ETF 品种索引 + 数据接口

**文件:** `memory/knowledge/variety_index.json`, `data_adapter/sources/akshare_source.py`
**改动:** 新增 ETF 品种 + 扩展 AKShare ETF 数据接口（~50 行）
**影响:** ETF 品种可被正常采集 K 线数据

### Step 7: 测试

**文件:** `tests/data_adapter/test_classifier.py`
**测试:** 6 个用例，覆盖所有市场类型
**影响:** 保障回归

---

## 7. 风险

| 风险 | 等级 | 缓解 |
|:-----|:----:|:-----|
| ETF 品种数量多（~800+），品种索引膨胀 | 🟡 | 仅添加首批 10-20 个主流 ETF，按需扩展 |
| 国债期货收益率曲线数据需额外采集 | 🟠 | Phase 1 先用探源 WebSearch 补充，后续专门化 |
| 金融期货 vs 商品期货的"边界品种"（如商品指数期货） | 🟢 | 默认归为商品期货，不影响正确性 |
| 链证源跳过后 P3 四源数量不一致 | 🟢 | P3 合并节点已支持源数量可变的 fan-in |

---

## 8. 版本计划

- v10.5.x: 本设计文档 + 品种分类器 + State 扩展 (Step 1-2)
- v10.6.0: Agent Prompt 注入 + 链证源跳过 + ETF 数据 (Step 3-6)
- v10.6.1: 测试 + 调试 + 首批品种辩论验证 (Step 7)
