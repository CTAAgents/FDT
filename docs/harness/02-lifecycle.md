# 02 — 生命周期与编排

## 1. 入口引导 (Bootstrap) — 独立运行模式

### 1.1 三种启动模式（独立运行）

| 模式 | 命令 | 用途 | 退出条件 |
|:-----|:-----|:-----|:---------|
| `cli once` | `python fdt_cli.py --once` | 单次执行完整辩论流程 | 执行完即退出 |
| `cli daemon` | `python fdt_cli.py daemon` | 后台守护进程 (LangGraph Master Graph) | 收到 SIGINT/SIGTERM |
| `api` | `python fdt_api.py --host 0.0.0.0 --port 8000` | FastAPI HTTP 服务 | 收到 SIGINT/SIGTERM |
| `api trigger` | `POST /api/v1/debate` | API 触发单次辩论 | 执行完返回 |

### 1.1a 已删除的历史模式

| 模式 | 删除版本 | 替代方案 |
|:-----|:---------|:---------|
| `scheduler/engine.py` (60s心跳) | v9.18.1 | `fdt_cli.py daemon` (Master Graph) |
| `bootstrap.py` | v9.18.1 | `fdt_cli.py` |
| `scripts/scheduler.py` | v9.18.1 | `fdt_cli.py daemon` |

> **说明**: FDT 所有自动化任务统一由 LangGraph Master Graph 编排，零第三方调度依赖。

### 1.2 启动序列

```
fdt_cli.py main()
    │
    ├─ 1. 路径校准: os.chdir(_ROOT) + sys.path.insert
    │
    ├─ 2. 模式分发:
    │     ├─ daemon → run_master_daemon() (LangGraph Master Graph)
    │     ├─ master → run_master_once() (单次检查到期任务)
    │     └─ run   → run_debate() (一次辩论)
    │
    └─ 3. daemon 模式:
          ├─ 每 60s 检查所有到期任务
          └─ 纯 Python time.sleep 循环
```

### 1.3 代码位置

| 组件 | 文件 | 行号 |
|:-----|:-----|:-----|
| 入口函数 | `fdt_cli.py` | `main()` |
| Master Graph | `fdt_langgraph/master_graph.py` | `run_master_daemon()` / `run_master_once()` |
| 调度注册表 | `fdt_langgraph/master_state.py` | `_get_default_schedules()` |
| 节点函数 | `fdt_langgraph/master_nodes.py` | 14 个任务节点 |

## 2. 六阶段流水线 (P1-P6) + 前置检查

### 2.1 阶段状态机（v8.3.0+ 按需并行版本 + v9.6.5+ 新鲜度闸门）

```
                    ┌────────────────────────────────────┐
                    │   自进化前置 (自动)                 │
                    │   validate → calibrate             │
                    │   → evolve → ML check              │
                    └───────────┬────────────────────────┘
                                │
                    ┌───────────▼────────────────────────┐
                    │   P0b: 数据新鲜度闸门               │
                    │   检查各品种行情/资金数据新鲜度    │
                    │   freshness_level: 0/1/2 评级       │
                    │   stale_ratio>30% → 中止并告警     │
                    └───────────┬────────────────────────┘
                                │
                    ┌───────────▼────────────────────────┐
              ┌─────│   P1: 可插拔多策略扫描              │
              │     │   数技源 (scan_all.py)              │
              │     │   trend_following(10信号)           │
              │     │   mean_reversion(3信号)             │
              │     │   + 自定义策略插件                  │
              │     └───────────┬────────────────────────┘
              │                 │
              │     ┌───────────▼────────────────────────┐
              │     │  P2 信号过滤闸门                       │
              │     │  select_triggers()                  │
              │     │  filter=ON: |total|                 │
              │     │  filter=OFF: |_raw_total|           │
              │     └───┬───────────────┬────────────────┘
              │         │ Yes           │ No
              │         ▼               ▼
              │  ┌──────────────┐  ┌──────────────────┐
              │  │ P2: 闫判官   │  │ 提前终止          │
              │  │ 选品种+调度  │  │ 汇报"无信号"      │
              │  │ + 调度决策    │  └──────────────────┘
              │  └──────┬───────┘
              │         │
              │         ▼ (按需并行调度)
              │  ┌──────────────────────────┐
              │  │  P2: 四源并行 (按需)    │
              │  │  ┌──────────┬──────────┐ │
              │  │  │ 链证源   │ 观澜    │ │
              │  │  │ 产业链   │ 技术面  │ │
              │  │  ├──────────┼──────────┤ │
              │  │  │ 探源     │ 读心    │ │
              │  │  │ 基本面   │ 新闻情绪│ │
              │  │  └──────────┴──────────┘ │
              │  └──────┬────────────────────┘
              │         │
              │  ┌──────▼───────┐
              │  │  P3: 六阶段攻防 │ ← 串行六步
              │  │ bullish_v1→  │
              │  │ bearish_v1→ │
              │  │ bearish_    │
              │  │ rebuttal→   │
              │  │ bullish_    │
              │  │ rebuttal→   │
              │  │ bear_final→ │
              │  │ bull_final  │
              │  └──────┬───────┘
              │         │
              │  ┌──────▼───────┐
              │  │ P4: 闫判官终裁│ ← 串行
              │  │ 含完整交易参数│
              │  └──────┬───────┘
              │         │
              │  ┌──────▼───────┐
              │  │ P5: 风控明   │
              │  │ green/yellow │
              │  │ /red 审核    │
              │  └──────┬───────┘
              │         │
              │  ┌──────▼───────┐
              │  │P3.5: 品藻     │  ← 质检+报告角色
              │  │ 质检(Schema) │
              │  │ verdict+risk │
              │  └──┬───────┬───┘
              │     │PASS   │FAIL
              │     ▼       ▼
              │  ┌────┐ ┌───────┐
              │  │存入│ │重试<2 │
              │  │结果│ │ →重修 │
              │  └────┘ │retry≥2│
              │         │→跳过  │
              │         └───┬───┘
              │             │ (退回prepare_one_symbol)
              └─────────────┘ (循环每个品种)
                        │
              ┌─────────▼─────────┐
              │ P6: 品藻汇编      │
              │ 组装→核验→JSON→   │
              │ HTML               │
              └─────────┬─────────┘
                        │
              ┌─────────▼─────────┐
              │ P6a: CTP信号输出  │
              │ 交易参数→CTP指令  │
              │ (风控明审核通过后) │
              └─────────┬─────────┘
                        │
              ┌─────────▼─────────┐
              │ 归档               │
              │ pg.execution_followup│
              └───────────────────┘
```

> **阶段变更说明**:
> - **v9.18.0 (Master Orchestrator Graph)**: 全量自动化迁移至 LangGraph。新增 Master Graph（`master_state.py`/`master_nodes.py`/`master_graph.py`），统一编排日常辩论/数据采集/APM评分/自动发布，纯 Python datetime 调度判断。`fdt_cli.py daemon` 模式替换 APScheduler 为 `run_master_daemon()`。零第三方依赖。
> - **v9.17.0 (LangGraph Evolution Graph)**: 自进化闭环从 scheduler 迁移至 LangGraph 子图。新增 `evolution_state.py`(APM五轴驱动状态)、`evolution_nodes.py`(8节点)、`evolution_graph.py`(编译图)。辩论后 `FDT_RUN_EVOLUTION=true` 自动触发，或 `fdt_cli.py evolve` 独立运行。基于 APM 评分 + 样本量条件路由：collect_metrics→apm_eval→decide_actions→[improve|calibrate|evolve|ml_train]→complete
> - **v9.16.0 (D2/D5/D6 pipeline 集成)**: D2 ToolMetrics 接入 Agent 执行入口 → 工具调用指标全量采集；D5 memory_cleaner 增强 → debate_journal 压缩 + generation_metrics 自动清理；D6 Output pipeline 集成 → `quality_inspector` 输出质量评分、`node_report` 输出版本化、`node_quality_inspect` 审计日志、scheduler apm_scorecard 定时任务
> - **P0b 新增 (v9.6.5)**: 数据新鲜度闸门作为 pre_loop 必查步骤，对标数据新鲜度分级标准
> - **P1 重构**: 从"通道突破扫描"升级为"可插拔多策略并行扫描"，支持 trend_following(10子信号)、mean_reversion(3子信号) 及自定义策略插件
> - **P2 信号闸门（非链证源）**: 当前 P2 是信号过滤闸门（三层门禁），与链证源无关。链证源已归入 P2 与观澜/探源/读心并行
> - **P2 增强**: 闫判官新增"调度决策"能力，决定 P2 需要哪些数据源
> - **P2 重构**: 改为"按需并行数据源"（链证源/观澜/探源/读心四源并行），由闫判官调度并行执行
> - **P3**: 六阶段攻防辩论（串行六步）
> - **P4+P5**: 闫判官终裁（含交易参数）→ 风控明审核

### 2.2 阶段详细规格（按需并行数据源 v8.3.0+ / 新鲜度闸门 v9.6.5+）

| 阶段 | 名称 | 执行者 | 输入 | 输出 | 超时 | 降级 |
|:-----|:-----|:-------|:-----|:-----|:-----|:-----|
| P0 | 自进化前置 | 系统 | `pg.execution_followup` | `pg.calibration` + `pg.agent_profiles` 更新 | 60s/步 | 跳过该步 |
| **P0b** | **数据新鲜度闸门** | **系统** | **PG中行情/资金数据** | **`debate_state.freshness_report`（各品种新鲜度评级）** | **120s** | **D06 降级（新鲜度不足→降级裁决）** |
| P1 | 数技源信号扫描 | 数技源 | 品种列表 | `pg.scan_signals` + **`all_ranked[].stats` 纯统计特征（MA/ATR/RSI/ADX/量能比/通道位置/20日区间位置）** + **P1 阶段报告 `scan_report_path`** | 600s | 提前终止 |
| P2 | 闫判官调度决策 | 闫判官（**调度权**） | P1 信号 | `pg.judge_direction`（选品种+**调度哪些源**） | 420s | D06 降级 |
| P2 | **四源并行** | 闫判官(调度)+链证源+观澜+探源+读心（闫判官按需调度） | P2 调度指令 | `pg.judge_direction` + `pg.chain_analysis` + `pg.technical_scores` + `pg.fundamental_scores` + `pg.sentiment_scores` + **P2 阶段报告 `research_report_path`** | **max(被调度的源)** | 单源失败不影响其他源 |
| P2a | 链证源产业链（按需） | 链证源 | 品种+产业链 | `pg.chain_analysis` | 300s | 跳过链分析 |
| P2b | 观澜技术面（按需） | 观澜 | 品种+方向 | `pg.technical_scores` | 420s | 跳过技术面 |
| P2c | 探源基本面（按需） | 探源 | 品种+方向 | `pg.fundamental_scores` | 420s | 跳过基本面 |
| P2d | 读心新闻情绪（按需） | 读心 | 品种+方向 | `pg.sentiment_scores` | 420s | 跳过新闻情绪 |
| P3 步1 | 多头立论 v1 | 多头分析员 | P2 合并分析结果 | `state.bullish_arguments`（round=1, v1） | 420s | D06 降级 |
| P3 步2 | 空头立论 v1 | 空头分析员 | P2 合并分析结果 | `state.bearish_arguments`（round=2, v1） | 420s | D06 降级 |
| P3 步3 | 空头反驳多头 | 空头分析员 | 多头立论 + P2 合并分析 | `state.bearish_rebuttal_arguments`（round=3, rebuttal_v1） | 420s | D06 降级 |
| P3 步4 | 多头反驳空头 | 多头分析员 | 空头立论+空头反驳 + P2 | `state.bullish_rebuttal_arguments`（round=4, rebuttal_v1） | 420s | D06 降级 |
| P3 步5 | 空头最终陈述 | 空头分析员 | 整合空头所有论据 | `state.bear_final_arguments`（round=5, final） | 420s | D06 降级 |
| P3 步6 | 多头最终陈述 | 多头分析员 | 整合多头所有论据 | `state.bull_final_arguments`（round=6, final） | 420s | D06 降级 |
| P4 | 闫判官终裁 | 闫判官(含交易参数) | P3 辩论论据 | `pg.debate_verdicts`(含交易参数) + **P4 阶段报告 `verdict_report_path`** | 420s | D06 降级 |
| P5 | 风控明审核 | 风控明 | 闫判官裁决 | `pg.risk_checks` | 120s | 品藻兜底 |
| P3.5 | 辩论质检 | 品藻 | 闫判官裁决 + 风控明审核 | `state.quality_report`（PASS/FAIL + issues） | 30s | 品藻汇总时兜底 |
| P6 | 汇总输出 | 品藻 | 全部产出 | HTML辩论报告 `report_path` + `pg.debate_index` | 120s | 拒绝生成报告 |
| P6a | CTP信号输出 | 品藻 | P6 汇总 + 风控明审核 | CTP交易指令 (`pg.ctp_signals`) + **P6a 阶段报告 `signal_report_path`** | 60s | 跳过信号输出 |

> **v9.6.5 变更 — LangGraph 迁移全部完成 (G93-G96)**:
> - **G93**: `coordinator.py` 已删除，Profile 切换逻辑由 `graph.py` 的 `build_debate_graph_with_profile()` 替代
> - **G94**: `debate_protocol_v2.py` 已删除，辩论协议常量（ATTACK_DIMENSIONS/EVIDENCE_WEIGHT_FACTORS/DEBATE_DIVERGENCE_THRESHOLDS）内联到 `nodes.py`
> - **G95**: `agent_runner.py` 已删除，`run_agent()` 由 `agents.py` 的 `DebateAgentExecutor.run_single()` 替代
> - **G96**: `deploy.py` 的 `migrate_json_to_pg()` 已实现 INSERT 写入逻辑（DebateVerdicts/ExecutionFollowup/AgentProfiles）
>
> **v9.6.5 变更 — 数据新鲜度闸门 (G21)**:
> - **P0b 新增**: 辩论启动前数据新鲜度闸门，对标数据新鲜度分级标准
> - 行情数据须在上一交易日内；资金/持仓须为最新交易日；过时品种>30%中止并告警
>
> **阶段变更说明 (v8.3.0)**:
> - **P1-P2-P3 重构**: 从「数技源串行 → 旧闸门 → P2 闫判官 → P3 研究」改为「P1 数技源 → P2 闫判官**调度决策** → P2 **四源并行**链证源+观澜+探源+读心」
> - **调度权**: 闫判官在 P2 阶段不仅选品种，还决定需要哪些数据源（如趋势信号侧重观澜、周期品种侧重链证源）
> - **四源归入 P2**: 链证源/观澜/探源/读心从原独立阶段移至 P2 四源并行
> - **数据存储**: 所有中间产出从文件系统迁移到 PostgreSQL (OLTP 层)
> - **并行粒度**: 被调度的源在 LangGraph 中通过 `ParallelMap` 并发执行，超时取 max 而非 sum
>
> **v8.9.0 变更**:
> - **P4 重构**: 从「证真+慎思并行一次调用」改为「串行三步骤交叉质询」：bullish_v1（多头立论）→ bearish_v1（空头质疑）→ rebuttal_v2（多头反驳，max=1）
> - **Redux**: 引入 `Annotated[list, operator.add]` reducer 自动追加多轮辩论产物，不覆盖
> - **路由**: 新增 `debate_round` 计数器 + `MAX_DEBATE_ROUNDS` 常量精确控制轮次

> **v9.6.8 变更 — P1 角色矫正**: P1 数技源从"策略评分器"回归"数据统计器"角色，新增 `all_ranked[].stats` 纯统计特征产出（MA/ATR/RSI/ADX/量能比/通道位置/20日区间位置），`total`/`direction`/`grade` 降级为内部参考。`select_triggers()` 从基于 grade+total 的方向性过滤改为数据质量闸门（stats完整性+K线数量+流动性）。

> **v9.12.0 变更 — Data Governance Phase 2 数据质量门禁**: 信号验证器管道新增 V8 `data_quality` 验证器（注册为 `__global__` 列表级闸门），在 P0-4 伪信号过滤之前运行。该验证器读取 `all_ranked[].data_quality` 元数据（由 FDC 在验证器之前注入），依据 `overall` 等级触发阻断：D级→直接降级 NOISE（数据不可靠）、C级→标记 `_dq_penalty`（信号保留但可靠性存疑）、web_fallback 源→标记 `_dq_web_fallback`（低优先级）。数据源已穿透到 FDC 真实底层源（tdx_tq_local / web_fallback / qmt_xtquant / tqsdk），从 kline_data 自动传播到 all_ranked 条目。
>
> > **补充 — F10/技术指标/新闻质量评估（增量）**: `node_prepare_data` (P2.5) 新增 `evaluate_f10_data()` 和 `evaluate_indicators()` 评估。`node_sentiment` 新增 `evaluate_jin10_context()` 评估快讯数量/新鲜度/时效分布。F10 逐字段（基差/期限结构/仓单/持仓排名/基本面）检查可用性、数值合理性、A2A grade。

> > **v9.14.0 变更 — Data Governance Phase 3 辩论输出质量治理 + 品藻角色拆分 + Generation 解码控制成熟度提升**: 新增 `node_quality_inspect` 节点（品藻质检），在 P4 裁决→P5 风控之后运行，校验 Schema 合规性。不合格+重试<2次→退回重修；通过或超限→存入 `store_per_symbol_result`。重试硬上限 2 次，熔断直接跳过。新增 `contracts/debate_quality_schema.py`（ARGUMENT/VERDICT/RISK 三套 Schema）和 `fdt_langgraph/quality_inspector.py`（纯函数质检器）。state 新增 `quality_report`/`rework_counters`/`phase_timings` 字段。`route_after_quality_inspect` 条件边实现退回/放行路由。**品藻拆分**：将质检+报告职责从明鉴秋剥离，成立独立角色品藻（`agents/futures-quality-assurance.md`），P3.5+P6 由品藻执行。明鉴秋保留调度/编排职责。**Generation 解码控制**：FdtAgentExecutor 运行时加载 decode_config.yaml；agent_waiter 接入 enforce_structured_output 自动校验；check_report_integrity 接入 content_filter；apm_scorecard D3 fallback via generation_metrics；retry_with_temperature_escalation 升温重试闭环。

### P2 逐品种循环（v9.13.0）
每个品种独立走完整数据链：
1. `prepare_one_symbol` — 只准备当前品种 FDC 数据
2. 四源并行（chain/tech/fund/sent）— 只分析当前品种
3. `merge_research` — 合并当前品种研究数据
4. 六阶段辩论 — 只辩论当前品种
5. `verdict` + `risk_check` — 只裁决/审核当前品种
6. `store_per_symbol_result` — 存入逐品种结果，递增索引
7. `route_next_symbol` — 判断是否还有下一个品种

所有品种完成后：
8. `aggregate_results` — 从 `per_symbol_results` 重建完整裁决

### 2.2a 运行模式

FDT 支持两种执行模式：

1. **全量分析模式**（默认）：现有六阶段流水线不变 — P0b 新鲜度闸门 → P1 信号扫描 → P2 闫判官+四源并行 → P3 六阶段攻防辩论 → P4 闫判官终裁 → P5 风控明 → P6 汇总输出。从品种列表全量扫描开始，逐级传递。

2. **指定品种辩论模式**：当设置 `FDT_DIRECT_DEBATE=true` 和 `FDT_DEBATE_SYMBOLS=SF,SM,SC` 时，跳过 P1 扫描阶段。系统从 `fdt_cache/` 本地 SQLite 缓存直接加载指定品种的 K 线数据、基本面数据和基差数据，进入 P0b→P2→P3→P4→P5→P6 流程。适用于快速对已缓存品种启动辩论，无需等待实时扫描信号。

**配置方式**：通过环境变量 `FDT_DIRECT_DEBATE`（启用开关）和 `FDT_DEBATE_SYMBOLS`（品种列表，逗号分隔）控制。缓存目录由 `FDT_CACHE_DIR` 指定（默认 `FDT_ROOT/memory/`）。详见 [03-configuration.md](03-configuration.md)。

> **调度权边界（2026-07-14 澄清，见 G18）**：辩论调度权（决定辩论品种/产业链/方向、dispatch 哪些分析师）属于**闫判官**；链证源/观澜/探源只做各自分析、**无调度权**；明鉴秋负责按闫判官指令执行 spawn 与资源/生命周期管控。该边界已在 `docs/execution_modes_flowchart.md` v4.1 与 `docs/business_flow.md` 固化。

### 2.3 Agent 生成与销毁

FDT 的 Agent 不是常驻进程，而是按需 spawn 的 LLM 子任务。生命周期如下：

```
明鉴秋 (常驻)
    │
    ├─ build_spawn_file_instruction(output_path, agent_name)
    │   → 生成文件输出指令，追加到 spawn prompt
    │
    ├─ Agent tool spawn (subagent_type: "general-purpose")
    │   │
    │   ├─ Agent 执行任务 (读文件 → 分析 → 写文件)
    │   │
    │   └─ SendMessage(recipient="main", content="产出已写入 {path}")
    │       → 通知完成 (非阻塞)
    │
    ├─ poll_file_ready(filepath, timeout=900)
    │   │
    │   ├─ 每 15s 检查文件是否存在 + size 稳定 ≥5s
    │   │
    │   ├─ 就绪 → 读取 JSON → 传入下一阶段
    │   │
    │   └─ 超时 → D06 降级 (返回 None，基于已有数据裁决)
    │
    └─ Agent 实例销毁 (spawn 完成后自动回收)
```

**关键约束**:
- **D05 铁律**: 辩论 Agent 必须用 `subagent_type: "general-purpose"` spawn（expert 类型 Write 工具不可用）
- **S02 铁律**: Agent 之间禁止 SendMessage，统一由明鉴秋通过文件传递
- **S03 铁律**: Agent 写文件先写 `.tmp`，完成后 rename

### 2.4 报告层数据存储 (v8.8.0+)

明鉴秋负责 P0/P1/P3/P5/P6/P6a 五个阶段报告的调度与输出。报告输出目录由环境变量决定：

| 环境变量 | 作用 | 默认 |
|:---------|:-----|:-----|
| `FDT_REPORT_WORKSPACE` | 用户指定工作空间根目录 | 无 |
| `FDT_DAILY_WORKSPACE` | 每日自动化任务工作空间（D:\FDTWorkspace 之类） | 无 |
| 无环境变量 | 使用系统临时目录 `tempfile.gettempdir()/fdt_reports` | 兜底 |

**目录规则**：所有报告按日期归档至 `{workspace}/{YYYY-MM-DD}/` 子目录。

**阶段报告字段映射**（位于 `DebateState`）：

| 字段 | 阶段 | 文件名模式 | 格式 |
|:-----|:-----|:-----------|:-----|
| `freshness_report` | P0b 新鲜度闸门 | `freshness_report_{trace_id}.json` | JSON |
| `scan_report_path` | P1 信号扫描 | `scan_report_{trace_id}.html` | HTML |
| `research_report_path` | P2 四源并行 | `research_report_{trace_id}.html` | HTML |
| `verdict_report_path` | P4 闫判官终裁 | `verdict_report_{trace_id}.html` | HTML |
| `report_path` | P6 辩论汇总 | `debate_report_{date}.html` | HTML |
| `signal_report_path` | P6a CTP信号 | `signal_report_{date}.html` | HTML |

**降级策略**：
- P0b 新鲜度闸门失败时，走 D06 降级，记录 stale_data_warning 到日志
- P1/P2/P4/P6a 报告生成失败时，记录 warning 不中断主流程
- P6 辩论报告失败时，fallback 写入工作空间下的 `debate_report_{trace_id}.html`，保证 `report_path` 永远有效
- 所有 fallback 报告统一使用 `_render_html()` 模板，trace_id 全链路贯穿

## 3. 自进化闭环

### 3.1 自进化状态机

```
                    ┌─────────────────────────┐
                    │  检查 execution_followup │
                    │  有未验证裁决?           │
                    └───────┬─────────┬───────┘
                            │ Yes     │ No
                            ▼         │
                ┌───────────────────┐ │
                │ validate_verdicts │ │
                │ (拉T+1 K线验证)   │ │
                └───────┬───────────┘ │
                        │             │
                ┌───────▼───────────┐ │
                │ 已验证 ≥ 5 条?    │ │
                └───┬───────────┬───┘ │
                    │ Yes       │ No  │
                    ▼           │     │
            ┌───────────────┐   │     │
            │ calibrate_   │   │     │
            │ weights.py   │   │     │
            └───────┬───────┘   │     │
                    │           │     │
            ┌───────▼───────────┐     │
            │ total_samples ≥5? │     │
            └───┬───────────┬───┘     │
                │ Yes       │ No      │
                ▼           │         │
        ┌───────────────┐   │         │
        │ evolve_agents│   │         │
        │ .py (7Agent) │   │         │
        └───────┬───────┘   │         │
                │           │         │
        ┌───────▼───────────┐         │
        │ 新样本 ≥ 50 条?   │         │
        └───┬───────────┬───┘         │
            │ Yes       │ No          │
            ▼           │             │
    ┌───────────────┐   │             │
    │ ML Training   │   │             │
    │ Orchestrator  │   │             │
    └───────┬───────┘   │             │
            │           │             │
            └───────────┴─────────────┘
                        │
            ┌───────────▼───────────┐
            │ 加载最新 calibration  │
            │ + agent_profiles      │
            │ → 注入当前会话        │
            └───────────────────────┘
```

### 3.2 自进化脚本矩阵

| 脚本 | 触发条件 | 输入 | 输出 | CLI |
|:-----|:---------|:-----|:-----|:----|
| `validate_verdicts.py` | 有未验证裁决 + K线已更新 | execution_followup.json | validation_stats.json | `--t1` `--t3` `--cost-bps` |
| `validate_llm_output.py` | 每轮辩论结束后自动运行 | scan_results.json + verdict.json | llm_hallucination_stats.json | `--scan` `--verdict` `--history` `--threshold` |
| `calibrate_weights.py` | 已验证 ≥5 条 | validation_stats.json + llm_hallucination_stats.json | calibration.json | `--min-samples` `--lr` `--hallucination-stats` |
| `evolve_agents.py` | total_samples ≥5 | calibration.json + agent_profiles.json + llm_hallucination_stats.json | agent_profiles.json (更新) | `--hallucination-patterns` |
| `record_verdicts.py` | 每轮辩论结束 | debate_results.json | execution_followup.json | `--input` |
| `ml/trainer.py` | 新样本 ≥50 | debate_journal.json | models/*.txt (LightGBM) | `run_daily_check()` |
| `update_matrix.py` | 每次裁决后 | execution_followup.json | instrument_strategy_matrix.json | `--symbol` `--family` `--correct` |

## 4. Master Graph 调度器

调度逻辑定义在 `fdt_langgraph/master_nodes.py`，纯 Python datetime 判断，零第三方依赖。

```python
# master_nodes.py — 核心检查 (简化)
def node_check_time(state):
    for task_name, sched in state["schedules"].items():
        if time_match(sched, now) or data_trigger_match(sched, last_triggered):
            task_queue.append(task_name)
    return state
```

详见 [07-operations.md §3](07-operations.md#3-master-graph-运维) 完整调度注册表。


## 5. 全自动流水线 (Pipeline Runner)

### 5.1 六步管道

`pipeline/runner.py` 实现了无人值守的全自动管道：

| 步骤 | 函数 | 脚本 | 失败策略 |
|:-----|:-----|:-----|:---------|
| 1/6 | `step_scan()` | `scan_all.py`(channel_breakout) | 文件缺失则告警继续 |
| 2/6 | `step_chain_analysis()` | `analyze_chain.py` | 跳过链分析 |
| 3/6 | `step_debate_brief()` | `debate_brief.py` | 跳过品种精选 |
| 4/6 | `step_assemble_intermediate()` | `assemble_intermediate_data.py` | 跳过数据适配 |
| 5/6 | `step_generate_report()` | `phase3_generate_report.py` | 标记报告未生成 |
| 6/6 | `step_record_history()` | `debate/history.py` + `record_verdicts.py` + `ml/trainer.py` | 各子步骤独立容错 |



### 5.3 基差数据来源 (v8.8.9+)

P1 扫描阶段的基差数据通过 `_collect_basis_data_sync()` 获取，数据来源优先级：

1. **100ppi.com/sf/ 现期表**（主源）— 生意社公开页面，覆盖 ~50 个期货品种的现货价
2. **TDX 近月合约代理**（降级，v8.8.9 新增）— 当 100ppi 不可用时（HW_CHECK 反爬/超时/页面变更），自动降级使用 TdxCollector 的近月合约价格作为现货价格代理
3. **无数据** — 以上均不可用时返回空字典，验证器退化为纯 ATR%/K线重校验判断

**近月代理标注**：返回数据的 `unit` 字段为 `"元/吨(近月代理)"`，`data_source` 为 `"near_month_proxy"`。消费方应据此区分真实基差与代理基差。

### 5.2 容错原则

- **每步失败不阻断后续**: `check=False` 传递给 `run_cmd()`
- **超时保护**: 每步 600s 超时
- **日志双写**: 控制台 + 文件 (`pipeline_{date}.log`)
- **UTF-8 强制**: `PYTHONIOENCODING=utf-8` 环境变量注入

### 5.3 代码位置

| 组件 | 文件 | 关键函数 |
|:-----|:-----|:---------|
| 管道主流程 | `pipeline/runner.py` | `main()` L383 |
| 命令执行器 | `pipeline/runner.py` | `run_cmd()` L77 |
| 日志配置 | `pipeline/runner.py` | L22-30 (logging.basicConfig) |
| ML 训练检查 | `pipeline/runner.py` | `step_record_history()` L271 |
| 单品种报告 | `fdt_langgraph/single_symbol_report.py` | `generate_single_symbol_report()` |

> **支持文档**：`docs/signals/channel_breakout_strategy.md` — 通道突破信号策略完整逻辑说明（唐奇安DC20/DC55 + 布林带 + 成交量确认）。


## 6. Loop Engineering：循环生命周期

### 6.1 双层循环架构

FDT 的生命周期管理从单次运行（Inner Loop）扩展到跨会话的持续进化（Outer Loop）：

```
┌─────────────────────────────────────────────────────────────┐
│  Outer Loop（外循环）— 跨会话的 Harness 进化                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  触发: 有未验证裁决 / 累计样本达标                      │  │
│  │  执行: validate → calibrate → evolve → ML train        │  │
│  │  产出: calibration.json + agent_profiles.json + 模型    │  │
│  │  注入: 下一轮辩论加载最新配置                           │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Inner Loop（内循环）— 单次辩论的六阶段攻防                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  P0b新鲜度闸门 → P1扫描 → P2调度 → P3并行研究         │  │
│  │  → P4六阶段攻防 → P5裁决链 → P6输出                   │  │
│  │  含 D06 降级、Maker-Checker 分离、分歧度控制           │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Loop Contract 六维度契约

每个自动化循环必须在 `docs/harness/loop-contracts/` 下有对应的 `.contract.yaml` 文件，定义六维度：

| 维度 | 键 | 说明 | FDT 实现 |
|------|-----|------|----------|
| **触发条件** | `trigger` | 何时启动 | cron / API / 手动 / 事件 |
| **作用范围** | `scope` | 能碰什么、不能碰什么 | allow/deny 路径清单 |
| **具体行为** | `action` | pipeline 步骤 | 预循环 → 主管道 → 后循环 |
| **预算红线** | `budget` | 资源上限 | 时间/Token/成本/重试/品种数 |
| **停止条件** | `stop` | 正常完成 + 安全网 | 完成条件 + 熔断条件 |
| **上报通道** | `report` | 正常输出 + 异常通知 | HTML报告 + PG归档 + 日志 |

详细规范见 [loop-contracts/README.md](loop-contracts/README.md)。

### 6.3 验证档位与权限匹配

| 验证档位 | 权限档位 | FDT 循环示例 | 晋级门槛 |
|----------|----------|-------------|----------|
| L1 (self) | 只读 (RO) | 数据采集、健康自检 | — |
| L2 (test_suite) | 草稿 (Draft) | 自进化闭环、ML 训练 | 影子模式 ≥5 轮，准确率 ≥90% |
| L3 (independent_agent) | 外部写入 (Write) | 每日自动辩论（含 CTP 输出） | 连续 ≥20 次零回退，漏放率 ≈0 |

### 6.4 多循环协作

FDT 多个循环之间通过 handoff 消息协作，不共享状态：

```
[数据采集循环] ──handoff──→ [每日辩论循环] ──handoff──→ [自进化循环]
       │                         │                          │
       ▼                         ▼                          ▼
  state/data-collect/     state/daily-debate/       state/self-evolve/
```

**铁律**：状态跟循环走。每循环自有独立 state 目录，仅本循环读写；协作不靠共享状态，靠 handoff 消息。


### 经验库循环（Experience Loop）

- **记录循环**：daily-debate post_loop → experience_recorder → memory/experience/records/
- **蒸馏循环**：self-evolve pipeline → pattern_distiller → memory/experience/patterns/ (staging)
- **审查步骤**：人工确认 staging → confirmed（通过 pattern_reviewer CLI）
- **适配循环**：daily-debate pre_loop → harness_adapter → W(x_j)（Phase C）
