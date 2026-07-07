---
name: fundamental-data-collector
version: 1.3.0
description: 基本面数据采集器 v1.1.0 — 为辩论专家团·基本面研究员（探源）提供5大维度基本面数据查询。匹配探源v2 "基本面状态向量"输出框架。
agent_created: true
user_invocable: false
triggers:
  - 基本面查询
  - 供需数据
  - 库存
  - 期限结构
  - 利润
  - 平衡表
  - 宏观联动
---

# 基本面数据采集器 v1.1.0

## 定位

独立 skill，专门为 **futures-debate-team** 的 **基本面研究员（探源）** Agent 提供数据工具。

> 探源的输出是 **"基本面状态向量"** —— 结构化的多维数据快照，被闫判官（选辩论品种）、证真（挑利多）、慎思（挑利空）三方消费。

与 `commodity-chain-analysis` 的边界：
- **链证源**（commodity-chain-analysis）：搭产业链骨架（黑色/有色/能化链条结构、景气度）
- **探源**（fundamental-data-collector）：在骨架上填"当下供需天平往哪偏"的供需库存利润数据

## 依赖

- **futures-data-search**：期货行情+K线数据（DuckDB 统一存储）
- **WebSearch/WebFetch**：行业机构公开数据（Mysteel/MPOB/隆众/钢联/卓创）
- **Python 3.10+**

## 模块说明（5大维度匹配探源分析框架）

| 模块 | 功能 | 对应探源维度 | 数据源 |
|:----|:-----|:-----------|:------|
| `supply.py` | 产量、开工率、进口到港、产能利用率 | ①供需平衡表 | WebSearch+行业网站 |
| `demand.py` | 下游开工、订单、出口、表观消费 | ①供需平衡表 | WebSearch+行业网站 |
| `inventory.py` | 社库/厂库/仓单、同比环比、**库存结构分类（主动/被动累库/去库）** | ②库存周期定位 | WebSearch+Futures-data |
| `margin.py` | 产业链各环节毛利、加工费、利润分位数 | ③利润&开工传导 | WebSearch+利润模型 |
| `term_basis.py` | 基差、期限结构(contango/back)、持有成本理论价 | ④基差&期限结构 | futures-data-search |
| `macro_link.py` | 宏观/外盘联动指标（美元、原油、政策、USDA等） | ⑤宏观&外盘联动 | WebSearch+公开API |
| `chain_balance.py` | 供需平衡表估算（供给−需求滚动差、1-3月边际变化） | ①供需平衡表 | 调用supply+demand+模型 |
| `web_collector.py` | 联网搜索统一路由（含时效验证） | 通用补充 | WebSearch/WebFetch |

## 探源 Agent 输出格式（基本面状态向量 v2）

探源 Agent 输出必须采用以下结构化JSON格式，替代v1.0的扁平文本：

```json
{
  "symbol": "RB2410",
  "supply_demand_balance": {
    "current": "小幅短缺",
    "trend_4w": "转向宽松",
    "driver": "高炉开工回升+地产新开工同比-12%"
  },
  "inventory": {
    "social": {"value": 580, "unit": "万吨", "yoy": -8, "mom": 3, "percentile_5y": 35},
    "mill": {"yoy": 5, "structure": "厂库升_社库降=被动累"},
    "warehouse_receipt": {"trend": "持续注销", "note": "临近换月，仓单扰动"}
  },
  "profit": {
    "rebar_gross": 180,
    "percentile_5y": 68,
    "trend": "高位回落",
    "warning": null
  },
  "basis": {
    "spot": 3920,
    "futures": 3880,
    "basis": 40,
    "curve": "backwardation",
    "signal": "现货偏紧"
  },
  "leading_indicators": [
    {"name": "地产销售_30城", "value": -15, "unit": "%", "lead": "8-12周", "implication": "远期需求承压"}
  ],
  "narrative_for_bull": ["库存同比-8%，季节性低位", "基差走强"],
  "narrative_for_bear": ["利润68%分位，高位释放预期", "地产领先指标-15%"],
  "expectation_gap": {
    "market_priced_in": "市场已price-in季节性去库",
    "actual_vs_expected": "去库幅度略弱于预期",
    "implication": "边际偏空"
  },
  "confidence": 70,
  "data_reliable": false,
  "data_staleness_days": 5,
  "warning": "临近换月，仓单扰动，库存结构可能失真"
}
```

### 关键字段约束

| 字段 | 类型 | 必填 | 说明 |
|:-----|:-----|:----|:-----|
| `supply_demand_balance` | object | ✅ | `current`: 缺/松/紧平衡; `trend_4w`: 未来方向; `driver`: 核心驱动 |
| `inventory.social.structure` | string | ✅ | 库存结构组合判断：`社库降_厂库降=真实消化` / `厂库升_社库降=被动累` / 等 |
| `inventory.mill.structure` | string | ✅ | 厂库结构性质 |
| `profit.warning` | string | ❌ | 利润>80%分位时填"高利润供给释放预期" |
| `leading_indicators[].lead` | string | ✅ | 领先时长（如"8-12周""2-4周"） |
| `narrative_for_bull` | string[] | ✅ | 预先标注能被多方引用的数据条目 |
| `narrative_for_bear` | string[] | ✅ | 预先标注能被空方引用的数据条目 |
| `expectation_gap` | object | ❌ | 仅在能判断预期差时填入 |
| `confidence` | integer | ✅ | 0-100，探源对自身结论的置信度 |
| `data_reliable` | boolean | ✅ | 临近换月或数据质量低时设为false |
| `data_staleness_days` | integer | ✅ | 数据截止到当前的天数差 |
| `warning` | string | ❌ | 重大风险提示（换月扰动/政策突变/数据断更） |

---

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

---

## 探源 Agent 接口

当 `futures-debate-team` 的 **探源** Agent 加载本 skill 时，按以下方式使用：

### 工具调用规范

```json
{"module": "fundamental-data-collector.scripts.supply", "func": "query_supply", "args": {"symbol": "PK"}}
```

### 8个工具函数

| 函数 | 输入 | 输出 | 说明 |
|:----|:----|:----|:-----|
| `query_supply(symbol)` | 品种代码 | 开工率/产量/进口 → dict | 优先用 futures-data-search DuckDB 数据，不足走 WebSearch |
| `query_demand(symbol)` | 品种代码 | 下游开工/出口 → dict | 同上 |
| `query_inventory(symbol)` | 品种代码 | 库存量化数据 → dict | 含同比环比+季节性分位数+**库存结构分类** |
| `query_margin(symbol)` | 品种代码 | 毛利/加工费 → dict | 产业链各环节成本利润+分位数 |
| `query_basis(symbol)` | 品种代码 | 基差+期限结构+持有成本理论价 → dict | 依赖 futures-data-search |
| `query_macro(symbol)` | 品种代码 | 宏观/外盘联动指标 → dict | 美元/原油/政策/USDA等 |
| `query_chain_balance(symbol)` | 品种代码 | 供需平衡表估算 → dict | 调用supply+demand+模型推算 |
| `query_web(keywords)` | 搜索词 | 搜索结果摘要 → str | 联网搜索标注"待验证" |

### 探源 Agent 的边界约束

- ❌ **不下多空结论**（verdict=null 强制校验，禁止在output中出现）
- ❌ **不做交易计划**
- ❌ **不参与辩论**
- ✅ 只提供基本面状态向量，供多空双方取用

### 输出校验规则

探源 Agent 每次输出的基本面状态向量必须通过以下校验：

```
□ supply_demand_balance.current 不为空
□ inventory.social.yoy 不为空
□ inventory.mill.structure 不为空（标注主动/被动）
□ narrative_for_bull 和 narrative_for_bear 均不为空（至少各1条）
□ leading_indicators 不为空（至少1条）
□ confidence 在 0-100 区间
□ data_staleness_days 如实填报
□ 无 verdict 字段
□ 无"看多/看空/做多/做空"等方向性表述
```

---

## 使用方法

```python
from fundamental_data_collector.scripts.supply import query_supply
from fundamental_data_collector.scripts.inventory import query_inventory
from fundamental_data_collector.scripts.term_basis import query_basis

# 查询品种供给
result = query_supply("PK")
print(result)

# 查询库存（含结构分类）
inv = query_inventory("RB")
print(inv["structure"])  # "厂库升_社库降=被动累"

# 查询基差与期限结构
basis = query_basis("RB")
print(basis["curve"])  # "backwardation"
```

---

## 版本历史

### v1.1.0 (2026-07-06)
- 新增 `macro_link.py` 模块 — 宏观/外盘联动指标
- 新增 `chain_balance.py` 模块 — 供需平衡表估算
- `term_basis.py` 升级 → 改名为 `query_basis()`，新增持有成本理论价
- `inventory.py` 升级：新增库存结构分类输出（主动/被动累库/去库）
- 对齐探源 Agent v2 的"基本面状态向量"输出框架
- 新增 `narrative_for_bull/bear` 双向标记规范
- 新增 `expectation_gap` 预期差字段规范
- 新增 `data_staleness_days` / `data_reliable` 数据保鲜标记
- 新增输出校验规则9条

### v1.0.0 (2026-07-04)
- 从 commodity-chain-analysis 剥离独立
- 继承 researcher_tools.py 的6个 query_* 函数
- 新增 WebSearch 数据采集路由
- 数据源可扩展架构
- **v1.3.0** — 新增恒生期货数据中心(徽商智汇)数据源
  - 3100+ 基本面数据主题（库存/产量/开工率/价格/基差/供需）
  - 本地 DuckDB 缓存，`data_interface.py` 提供 `get_fundamentals(symbol)` 接口
  - 品种中文名搜索映射（覆盖62个主力品种）
  - 探源通过 `from scripts.data_interface import get_fundamentals` 调用
