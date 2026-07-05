---
name: fundamental-data-collector
version: 1.0.0
description: 基本面数据采集器 v1.0.0 — 为辩论专家团·基本面研究员（探源）提供供给、需求、库存、利润、期限结构的真实数据查询。权重策略归位于独立 skill，不再耦合 commodity-chain-analysis。
agent_created: true
user_invocable: false
triggers:
  - 基本面查询
  - 供需数据
  - 库存
  - 期限结构
  - 利润
---

# 基本面数据采集器 v1.0.0

## 定位

独立 skill，专门为 **futures-debate-team** 的 **基本面研究员（探源）** Agent 提供数据工具。
与 `commodity-chain-analysis` 解耦——链分析只做链内聚类+一致性验证，基本面数据采集合独立迭代。

## 依赖

- **futures-data-search**：期货行情+K线数据（DuckDB 统一存储）
- **WebSearch/WebFetch**：行业机构公开数据（Mysteel/MPOB/隆众/钢联/卓创）
- **Python 3.10+**

## 模块说明

| 模块 | 功能 | 数据源 |
|:----|:----|:------|
| `supply.py` | 产量、开工率、进口到港、产能利用率 | WebSearch+行业网站 |
| `demand.py` | 下游开工、订单、出口、表观消费 | WebSearch+行业网站 |
| `inventory.py` | 社库/厂库/仓单、同比环比、季节性分位数 | WebSearch+Futures-data |
| `margin.py` | 产业链各环节毛利、加工费 | WebSearch+利润模型 |
| `term_basis.py` | 期限结构(contango/back)、基差 | futures-data-search |
| `web_collector.py` | 联网搜索统一路由（含时效验证） | WebSearch/WebFetch |

## 🔴 数据质量铁律

1. **数据必须附带时间戳和来源**：`"五大钢材总库存1600.99万吨（来源：Mysteel周度数据，截至6月30日）"`
2. **禁止无时间戳的泛化表述**：如"库存偏高""需求疲弱"
3. **禁止无来源陈述**：如"市场普遍认为"
4. **数据时效规则**：

| 类别 | 有效窗口 | 超窗处理 |
|:----|:--------:|:---------|
| 价格/行情 | ≤1天 | 超窗丢弃 |
| 突发新闻 | ≤3天 | 标注"X天前"+降置信度 |
| 周度数据(库存/开工率) | ≤7天 | 标注间隔天数 |
| 月度数据(产量/进出口) | ≤31天 | 标注月份+降一级 |
| 季度/半年报 | ≤45天 | 标注"可能已过时" |

5. **搜索查询必须包含时间限定词**：如 `"纯碱 库存 2026年7月 最新 周度"`
6. **搜索无结果时如实报告**："未找到近期数据"，不得用LLM内部知识替代

## 探源 Agent 接口

当 `futures-debate-team` 的 **探源** Agent 加载本 skill 时，按以下方式使用：

### 工具调用规范

```json
{"module": "fundamental-data-collector.scripts.supply", "func": "query_supply", "args": {"symbol": "PK"}}
```

### 6个工具函数

| 函数 | 输入 | 输出 | 说明 |
|:----|:----|:----|:-----|
| `query_supply(symbol)` | 品种代码 | 开工率/产量/进口 → dict | 优先用 futures-data-search DuckDB 数据，不足走 WebSearch |
| `query_demand(symbol)` | 品种代码 | 下游开工/出口 → dict | 同上 |
| `query_inventory(symbol)` | 品种代码 | 库存量化数据 → dict | 含同比环比+季节性分位数 |
| `query_margin(symbol)` | 品种代码 | 毛利/加工费 → dict | 产业链各环节成本利润 |
| `query_term(symbol)` | 品种代码 | 期限结构+基差 → dict | 依赖 futures-data-search |
| `query_web(keywords)` | 搜索词 | 搜索结果摘要 → str | 联网搜索标注"待验证" |

### 探源 Agent 的边界约束

- ❌ **不下多空结论**（verdict=null 强制校验）
- ❌ **不做交易计划**
- ❌ **不参与辩论**
- ✅ 只提供基本面事实，供多空双方取用

## 使用方法

```python
from fundamental_data_collector.scripts.supply import query_supply
from fundamental_data_collector.scripts.inventory import query_inventory

# 查询品种供给
result = query_supply("PK")
print(result)

# 查询库存
inv = query_inventory("RB")
print(inv)
```

## 版本历史

### v1.0.0 (2026-07-04)
- 从 commodity-chain-analysis 剥离独立
- 继承 researcher_tools.py 的6个 query_* 函数
- 新增 WebSearch 数据采集路由
- 数据源可扩展架构
