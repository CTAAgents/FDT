# 技术选型决策记录

> **目的**: 记录 FDT 项目中每项关键技术的选型背景、候选方案、决策理由和已知代价。
> 避免"为什么用这个"的疑问在团队更替后丢失。
> **最后更新**: 2026-07-18 | 对应版本: v9.0.0

---

## 1. 编排框架：LangGraph vs AutoGen vs CrewAI

### 问题
CTA 辩论系统需要一个多 Agent 协作框架，支持：显式状态机、多轮交叉质询、条件路由、断点恢复。

### 候选方案

| 方案 | 核心模型 | 状态管理 | 循环控制 | 持久化 |
|:-----|:---------|:---------|:---------|:-------|
| **LangGraph** | StateGraph + 条件边 | TypedDict + Reducer | 条件边明确控制 | Checkpointer (SQLite/PG) |
| AutoGen | 自由对话 (AssistantAgent) | 消息列表隐式状态 | 靠 StopMessage 终止 | 无原生支持 |
| CrewAI | 顺序/层级流程 | 内存传递 | Task 队列 | 无原生支持 |

### 选型理由（LangGraph）

1. **显式状态机匹配辩论场景**：辩论的每一步（立论→质疑→反驳→裁决）是确定性的状态转换，不是自由对话。LangGraph 的 StateGraph + 条件边可以精确控制"if round < 3 → continue"。

2. **Reducer 合并机制是辩论刚需**：`Annotated[list, operator.add]` 让多头/空头各自发言自动追加到同一字段，不会互相覆盖。AutoGen 的消息列表需要手动维护。

3. **Checkpointer 生产级稳定性**：SQLite/PostgreSQL 双后端 Checkpointer 实现断点续跑。AutoGen 和 CrewAI 无持久化——爬虫断网、LLM 超时、程序崩溃后状态全部丢失。

4. **条件路由精确控制 Token 消耗**：期货量化对成本敏感。LangGraph 的条件边能强制终止循环（如 `debate_round >= MAX_ROUNDS → verdict`），避免 AutoGen 自由对话中常见的"无限闲聊"导致 Token 爆炸。

### 代价 / 限制

- **学习曲线较陡**：StateGraph + Reducer + Checkpointer 的概念栈比 AutoGen 的 AssistantAgent 重
- **图修改成本高**：节点/边变更后需重新 `graph.compile()`，调试比线性代码慢
- **较新生态**：LangGraph v0.2+ 尚未完全稳定，API 有小幅变动风险

### 可能的替代路径

- 如果未来需求变为"完全自由辩论"（Agent 自主决定话题和轮次），AutoGen 可能更适合
- 如果只需要顺序执行（无需条件路由），CrewAI 的 Task 队列更轻量

---

## 2. 持久化存储：PostgreSQL vs DuckDB vs 文件系统

### 问题
辩论系统需要存储：扫描信号、技术面数据、基本面数据、辩论论据、裁决记录、状态历史。要求：事务完整性、并发安全、可分析。

### 候选方案

| 方案 | 类型 | 并发安全 | 分析能力 | 运维成本 |
|:-----|:-----|:---------|:---------|:---------|
| **PostgreSQL** | OLTP + OLAP 混合 | ✅ MVCC | ✅ 物化视图 + GIN/BRIN 索引 | 中（需部署） |
| DuckDB | OLAP 嵌入式 | ❌ 单连接 | ✅ 列式存储 + SQL | 低（嵌入） |
| 文件系统 (JSON) | 无 | ❌ 无 | ❌ 无 | 最低 |

### 选型理由（PostgreSQL）

1. **OLTP + OLAP 混合需求**：辩论过程是 OLTP（逐条写入 scan_signals、debate_verdicts），事后分析是 OLAP（v_signal_performance 视图）。PG 一库解决两个问题。

2. **事务完整性**：`node_scan` 写入 scan_results 和 `node_report` 写入报告之间可能崩溃。PG 的事务保证要么全部写入要么全部回滚。JSON 文件系统无此保证。

3. **LangGraph Checkpointer 的原生支持**：`PostgresSaver` 是 LangGraph 官方支持的 Checkpointer 后端，与 StateGraph 深度集成。

4. **物化视图支撑复盘**：`v_debate_summary`、`v_signal_performance`、`v_agent_effectiveness` 三个 OLAP 视图让每周的策略复盘可以直接 SQL 查询，不需要 ETL。

### 代价 / 限制

- **部署复杂度**：需要 PostgreSQL 16+ 服务器，增加了 CI/CD 和运维负担
- **连接管理**：需要连接池 + 健康检查 + 自动重连（`fdt_pg/connection.py` 约 150 行）
- **开发期摩擦**：本地开发需要安装 PG 或使用 SQLite 降级（`FDT_CHECKPOINTER=sqlite`）

### 可能的替代路径

- 如果未来完全云原生（无自建数据库），可迁移到 Supabase / Neon Serverless PG
- 如果分析需求超过 OLTP 承载，可引入 ClickHouse 做纯 OLAP 层，PG 只做 OLTP

---

## 3. Checkpointer 后端：SQLite vs PostgreSQL vs Redis

### 问题
LangGraph 需要 Checkpointer 持久化状态历史。选择哪个后端取决于：部署环境、性能要求、可用性需求。

### 选型逻辑

```
graph._get_checkpointer()
    │
    ├─ FDT_CHECKPOINTER=pg → PostgreSQL (PostgresSaver)
    │   ├─ 生产环境（多进程/多实例）
    │   ├─ 需要跨进程状态共享
    │   └─ 连接失败 → 自动降级 SQLite
    │
    └─ 默认 → SQLite (SqliteSaver)
        ├─ 本地开发 / 单机测试
        └─ 零配置，文件级持久化
```

| 维度 | SQLite | PostgreSQL | Redis |
|:-----|:-------|:-----------|:------|
| 单机开发 | ✅ 零配置 | ❌ 需安装 | ❌ 需安装 |
| 状态历史查询 | ✅ `get_state_history()` | ✅ 同上 | ❌ 无 SQL |
| 多进程共享 | ❌ 文件锁竞争 | ✅ MVCC | ✅ 原生 |
| 数据持久性 | ✅ 文件系统 | ✅ WAL | ❌ 宕机丢数据 |
| 配置复杂度 | 最低 | 中 | 低 |

### 未选 Redis 的原因

- **数据持久性不足**：宕机可能导致 Checkpointer 状态丢失，期货系统不能接受
- **无 SQL 查询能力**：`get_state_history()` 返回无法直接做分析查询
- **需要额外基础设施**：Redis 服务器部署和维护成本

---

## 4. Agent 执行器：FdtAgentExecutor vs LangChain Agent/Tool

### 问题
辩论 Agent 需要调用 LLM、读取文件、搜索网络。是复用 LangChain Agent/Tool 体系还是自己封装？

### 选型理由（自有封装）

1. **LLM 调用路径简单**：FDT 的 Agent 大部分是"读文件 + 分析 + 写 JSON"模式，不需要 LangChain Agent 的复杂工具路由。自封装的 `FdtAgentExecutor.run(prompt, trace_id)` 约 130 行，远轻于 LangChain Agent。

2. **避免 LangChain 版本依赖**：LangChain 的 API 变动频繁（v0.1→v0.2→v0.3），自有封装隔离了上游变动。FDT 核心的 LLM 调用逻辑不受 LangChain 大版本影响。

3. **trace_id 全链路注入**：自有封装可以强制 `trace_id` 贯穿每次 LLM 调用，LangChain 的 Callback 机制需要额外配置。

4. **工具需求极简**：FDT 的 Agent 只用到 `Read`（读文件）、`Write`（写 JSON）、`WebSearch`（研究员用）。LangChain 的 Tool 体系为通用场景设计（SQL、API、计算器等），大部分功能浪费。

### 代价 / 限制

- **无 LangSmith 原生追踪**：LangChain 生态的 LangSmith 在 Agent 层面需要额外适配
- **无 Tool 复用**：如果未来需要 LangChain 社区的工具（如 `GoogleSearch`、`PythonREPL`），需要手动封装
- **维护自有代码**：`FdtAgentExecutor` 的 LLM 调用逻辑需要自行维护 API 兼容性

### 可能的替代路径

- 如果未来 Agent 的工具需求变复杂（如需要 SQL 查询、API 调用链），可考虑迁移到 LangGraph 的 `ToolNode`
- 如果 LangGraph 的 `AagentExecutor` API 稳定化，可直接替换 `FdtAgentExecutor`

---

## 5. 辩论模式：交叉质询 vs 平行对比

### 问题
P4 辩论阶段，多头和空头分析员应该并行产出论据，还是串行交叉质询？

### 演进历史

| 版本 | 模式 | 问题 |
|:-----|:-----|:-----|
| v8.8.9 及之前 | **平行对比**：多头和空头同时并行调用 LLM | 双方论据互不知晓，没有反驳链，冗余论据多 |
| v8.9.0 | **交叉质询**：串行三步（bullish_v1→bearish_v1→rebuttal_v2） | 反方能针对性质疑，正方能针对性反驳 |

### 选型理由（交叉质询）

1. **更接近真实辩论**：平行对比本质上是"两个独立的分析报告"，交叉质询才是"一方立论、另一方质疑、再反驳"的辩论结构。

2. **论据质量更高**：空头分析员读过多头论据后再质疑，可以精准定位逻辑漏洞。平行对比模式下空头只能泛泛分析。

3. **Token 效率**：平行对比需要双方对同一份数据做两次完整分析（冗余）。交叉质询中，rebuttal 只需要针对质疑点反驳，输出量更少。

### 代价 / 限制

- **耗时增加**：串行执行的总耗时 = 三节点耗时之和，比并行耗时（max 两节点）长
- **失败点增加**：三步中任一步失败会影响后续步骤，需要更精细的降级策略
- **复杂度提升**：需要 `debate_round` 计数器 + 条件边路由

### 可能的替代路径

- 如果对延迟敏感（如日内高频），fast 模式可跳过交叉质询直达裁决
- 如果未来需要多方辩论（3+ 角色），可扩展到 tournament 模式

---

## 6. LLM 模型选择：DeepSeek vs GPT vs 本地模型

### 问题
辩论系统中所有 Agent 的推理引擎选型。

### 当前选型

| Agent 角色 | temperature | model（默认） | 自定义环境变量 |
|:-----------|:-----------:|:-------------|:---------------|
| 观澜（技术面研究员） | 0.1 | deepseek-chat | `FDT_LLM_TECHNICAL_RESEARCHER_MODEL` |
| 探源（基本面研究员） | 0.1 | deepseek-chat | `FDT_LLM_FUNDAMENTAL_RESEARCHER_MODEL` |
| 多头/空头分析员 | 0.4 | deepseek-chat | `FDT_LLM_BULLISH_ANALYST_MODEL` / `_BEARISH_ANALYST_MODEL` |
| 闫判官（裁决官） | 0.0 | deepseek-chat | `FDT_LLM_JUDGE_MODEL` |
| 风控明（风控审核） | 0.2 | deepseek-chat | `FDT_LLM_RISK_MANAGER_MODEL` |

> **默认模型**：`deepseek-chat`（代码层默认值，见 `agents.py` L92）。
> **自定义**：每个 Agent 可通过 `FDT_LLM_{AGENT}_MODEL` 环境变量覆盖，粒度到 model/api_base/api_key。
> **全局覆盖**：`FDT_LLM_MODEL` 环境变量可改变所有 Agent 的默认模型。
> **deeepseek-v4-flash**：在 `fdt-spawn-debate.md` 中作为建议值出现，非代码强制约束。

### 选型理由

1. **结构化输出能力**：DeepSeek 系列在 JSON 格式遵循度上表现稳定，辩论系统严重依赖 JSON fence 解析。

2. **价格优势**：相对于 GPT-4，DeepSeek 的 API 价格低约 5-10x。期货量化策略每日运行多次，成本敏感度高。

3. **角色温度分化**：研究类角色（观澜/探源）用低温度（0.1）确保事实准确性；辩论类角色（多头/空头）用中温度（0.4）保留论证多样性；裁决类角色（闫判官/风控明）用 0.0 温度确保决策一致性。

4. **逐 Agent 配置能力**：通过 `FdtAgentExecutor._resolve_llm_config()` 支持 per-Agent 的 model/api_base/api_key 独立配置，同一系统内可混合使用不同模型（如裁决用更强模型、研究用经济模型）。

### 代价 / 限制

- **中文语境依赖**：DeepSeek 在中文期货产业数据的理解和引用细节上优于 GPT-4
- **长上下文限制**：多轮辩论累积 prompt 可能超出上下文窗口，需要 v1→v2 的数据摘要策略
- **API 可用性风险**：依赖单一 API 提供商，建议配置 fallback 模型（通过环境变量动态切换）
- **代码默认值不等于推荐值**：`deepseek-chat` 是代码层的安全默认，实际部署应根据任务精度要求选择具体版本（如 flash、v2、v4）

---

## 7. 策略管线：NO_FUSION vs 信号融合

### 问题
8 个策略（趋势跟踪 × 10 子信号、均值回归 × 3 子信号等）各自产出信号后，是融合为统一信号还是各自独立透传？

### 选型理由（NO_FUSION）

- **（历史教训）**：v8.1.8 之前采用 `StrategyFusion.fuse()` 将不同哲学的信号按权重坍缩为单信号，导致"跨策略/子信号互相污染"——趋势跟踪看多、均值回归看空时，融合信号变成中性，丧失了辩论的素材。
- **当前方案**：各策略子信号独立 emit，辩论层看到的是原始信号多样性。闫判官在看过双方论据后做裁决，而不是在策略层做预融合。

---

## 8. 数据源降级链：TDX → WebFallback → QMT → TqSDK

### 问题
期货行情数据源各有可用性风险，如何确保断网/限流/反爬时有备用路径？

### 选型

```
TQ-Local (通达信)         # priority=0，本地客户端，最快最稳定
    ↓ 失败
WebFallback (新浪+东方财富)  # priority=1，免费公开 API，TQ-Local 失败首选降级
    ↓ 失败
QMT/xtquant              # priority=2，本地 TCP 直取，全周期能力
    ↓ 失败
TqSDK (天勤量化)          # priority=98，云端 API，末位兜底（close 偶发挂死）
    ↓ 全部实时源失败
缓存兜底 (PG / Redis)     # CACHED 等级
    ↓ 缓存未命中
UNAVAILABLE              # 无数据
```

**关键决策**：
- TQ-Local 超时设为 3s（G26 从 15s 下调），快速失败不阻塞降级链
- **WebFallback 前置于 TqSDK**（v9.0.0 / 2026-07-15 调整）：TqSDK `TqApi.close()` 偶发挂死 300s，放末位兜底，由超时保护（建连15s + 拉取25s + close守护5s）兜住
- 基差数据从 100ppi.com 迁移到近月合约代理（v8.8.9，因 100ppi 启用 HW_CHECK 反爬）
- 每个采集器配独立熔断器（连续失败5次屏蔽60s），避免重复踩坑
- 新鲜度断路器 7 项阈值（成功率/条数/时效/成交量/耗时/体积/重试），数据质量不达标直接告警
