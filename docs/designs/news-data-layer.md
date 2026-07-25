# 新闻情绪数据层 — 架构设计

## 背景

当前新闻情绪模块（读心 Agent）存在 3 个问题：

1. **金十搜索返回空**：`jin10_adapter.search_flash` 对大宗商品关键词经常返回空结果（尤其非交易日）
2. **WebSearch 兜底失效**：prompt 提示 LLM "使用 WebSearch"，但 `FdtAgentExecutor` 不支持工具调用，LLM 无法执行搜索
3. **架构不统一**：`jin10_adapter` 是独立模块，未对齐 `DataSource` 插件范式

## 读心（读心）的双职责

读心 Agent 在辩论专家团中承担两个层次的信号采集，均属于"情绪因子"范畴，但数据性质和使用方式不同：

| 职责 | 数据源 | 因子性质 | 业界依据 |
|:-----|:-------|:---------|:---------|
| **新闻情绪监测** | 金十、交易所公告、卓创资讯等固定新闻源 | **正向因子** — 事实驱动的市场情绪信号 | Tetlock (2007) 新闻情绪影响股价 |
| **社区情绪观测** | 雪球、东方财富股吧、微博等社交平台 | **反向/极端指标** — 观点驱动的羊群效应信号 | Da, Engelberg & Gao (2015) 社交媒体极端值有预测能力 |

**两类情绪分开采集，统一分析：**

```
数据采集层（分开，结构不同）
┌──────────────────────┐  ┌──────────────────────────┐
│ NewsRouter           │  │ CommunityRouter（本次预留）│
│ 固定新闻源            │  │ 雪球/东方财富股吧/微博    │
│ NewsItem[]           │  │ PostItem[]               │
│ 已实现                │  │ 下一步实施                │
└──────────┬───────────┘  └───────────┬──────────────┘
           │                          │
           ▼                          ▼
    统一注入 LLM context（分两段，标注来源）
           │                          │
           └──────────┬───────────────┘
                      ▼
            读心 Agent（统一分析）
            • 新闻情绪评分（正向因子）
            • 社区情绪热度（观测极端分位）
            • 分歧评估（两方方向背离 > 0.3 时标记 divergence）
                      │
                      ▼
             SentimentStateVector
             (schema 不改，divergence 字段已存在)
```

分歧处理规则：

| 新闻情绪 | 社区情绪 | 分歧标记 | 含义 |
|:---------|:---------|:--------:|:-----|
| 看多 | 温和 | 无 | 正常 |
| 看多 | 极度看多 | >0.3 | 市场过热，降权 |
| 看空 | 极度看多 | >0.3 | 方向背离，最有价值的辩论素材 |
| 看多 | 极度看空 | >0.3 | 社区恐慌，可能是抄底信号 |

## 一期架构（本次实施）

```
data_adapter/news/
├── __init__.py               # NewsRouter — 统一入口 + 多源聚合 + 自动降级
├── types.py                  # NewsItem / NewsQuery / NewsResult
└── sources/
    ├── __init__.py           # NewsSourceBase 抽象基类
    ├── jin10_source.py       # Jin10NewsSource — 封装 jin10_adapter
    └── web_search_source.py  # WebSearchSource — Python 级 HTTP 搜索
```

### NewsSourceBase

抽象基类，定义新闻源接口：

| 方法 | 说明 |
|:-----|:------|
| `fetch(query) -> NewsResult` | 按品种+关键词拉取新闻 |
| `health_check() -> bool` | 连通性检测 |
| `source_name` / `priority` | 标识和优先级 |

### Jin10NewsSource（优先级 10）

封装现有 `data_adapter.sources.jin10_adapter`，将 `search_flash` 返回的原生数据转换为 `NewsItem`。内置关键词事件分类（policy / supply_demand / macro / geopolitics / other）。

### WebSearchSource（优先级 50）

Python 层直接执行 HTTP 请求（新浪期货 RSS + 东方财富 API），**不依赖 LLM 工具调用**。通过正文中文关键词反向匹配品种。

### NewsRouter

```
fetch(query):
  1. 并行调用所有注册源的 fetch()
  2. 合并去重（content[:150] + source_name）
  3. 时效过滤（max_age_hours）
  4. 每品种限条数（max_per_symbol）
  5. 若有效条目 < min_news_threshold → data_incomplete=True
  6. 返回 NewsResult{items, source_stats, data_incomplete}
```

对外辅助方法：
- `build_prompt_context(result)` — 格式化为 LLM prompt context 文本
- `build_quality_report(result, symbols)` — 逐品种数据质量报告
- `build_symbol_summaries(result, symbols)` — 逐品种情绪汇总

### node_sentiment 改造

移除 `_build_jin10_context`，替换为：

```
NewsRouter.fetch(symbols) → NewsResult → build_prompt_context() → LLM context
```

读心 Agent 的 prompt 中原有的 WebSearch 提示改为：数据已由聚合器预采集，Agent 只分析。

## 数据流

```
node_sentiment(state)
  → NewsRouter.fetch(selected_symbols)
    → Jin10NewsSource.fetch()    # 并行
    → WebSearchSource.fetch()    # 并行
  → 去重/时效/限数
  → build_prompt_context(result)
  → [预留] 若有 CommunityRouter 数据，追加社区情绪段
  → LLM 分析（只分析不搜索，不分歧则正常输出，分歧则标记 divergence）
  → 输出 SentimentStateVector
  → 写入 state.sentiment_data
```

## 二期预留：社区情绪层

接口约定（**本期不做，仅定义契约**）：

```
data_adapter/community/                    # 二期新增
├── __init__.py                            # CommunityRouter
├── types.py                               # PostItem / CommunityQuery / CommunityResult
└── sources/
    ├── __init__.py                        # CommunitySourceBase
    ├── xueqiu_source.py                   # 雪球热帖
    └── eastmoney_guba_source.py           # 东方财富股吧
```

### CommunityResult 数据结构

```python
@dataclass
class PostItem:
    symbol: str                # 关联品种
    source_name: str           # 雪球/股吧
    title: str
    content: str
    time: str
    author: str
    bullish_ratio: float       # 看多比例 0~1
    reply_count: int           # 回复数（热度）
    read_count: int            # 阅读数
    source_type: str = "community"
    sentiment_score: float = 0.0  # NLP 情绪分 -1~1

@dataclass
class CommunityResult:
    items: list[PostItem]
    source_stats: dict
    total_count: int
    errors: list[str]
    data_incomplete: bool = False
```

### node_sentiment 社区段接入方式

```python
# node_sentiment 中（二期追加）
if community_available:
    community_result = await CommunityRouter().fetch(symbols)
    community_context = _format_community_context(community_result)
    full_context = news_context + "\n\n" + community_context
else:
    full_context = news_context
```

## 降级策略

| 场景 | 一期行为 | 二期补充 |
|:-----|:---------|:---------|
| Jin10 超时/空数据 | WebSearch 自动补充 | 同左 |
| 两源均无数据 | `data_incomplete=True` | 社区情绪可独立输出 |
| 社区源不可用 | 不涉及 | 仅标记告警，不阻断新闻情绪流程 |
| 所有源失效 | 返回空 NewsResult，不崩溃 | 同左 |

## 边界与兼容性

- 不改下游 `SentimentStateVector` 契约（`divergence` 字段已存在，可承载分歧标记）
- 不改 `fundamental_researcher`、探源节点
- `node_fundamental` 也使用 `NewsRouter` 替代独立 `_build_jin10_context` 调用（复用）
- 新增新闻源只需实现 `NewsSourceBase`，`NewsRouter.register_source()` 注册
- 社区情绪二期接入时，`node_sentiment` 只需追加一个 context 段落，不动核心分析逻辑
