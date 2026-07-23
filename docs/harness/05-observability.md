# 05 — 可观测性

## 1. 可观测性架构

FDT 的可观测性体系由三个维度组成：

```
┌─────────────────────────────────────────────────────────────┐
│                    可观测性三大维度                           │
├─────────────────┬─────────────────┬─────────────────────────┤
│   Metrics       │   Logging       │   Tracing               │
│   (指标度量)     │   (日志记录)     │   (追踪回放)             │
├─────────────────┼─────────────────┼─────────────────────────┤
│ APM-CS 五轴     │ unified_logger  │ debate_journal.json     │
│ (D1-D5)         │ (统一日志)       │ (辩论全链路记录)          │
│                 │                 │                         │
│ 失败聚类         │ pipeline日志    │ ViBench 回放            │
│ (cluster_       │ (流水线日志)     │ (replay_harness.py)     │
│  failures.py)   │                 │                         │
│                 │                 │ held-out judge          │
│ 纪律钳制         │ scheduler日志   │ (一致性审计)             │
│ (enforce_       │ (调度器日志)     │                         │
│  discipline.py) │                 │                         │
└─────────────────┴─────────────────┴─────────────────────────┘
```

## 2. APM-CS 五轴评分卡

### 2.1 五轴定义

| 轴 | 名称 | 含义 | 计算方法 | 触发 |
|:--|:-----|:-----|:---------|:-----|
| **D1** | Coherence (一致性) | 裁决是否真正源于辩论论据 | held-out judge 一致性评分 (0-1) | 每轮辩论 |
| **D2** | Acuity (辨识力) | 信号-噪音辨识能力 | Spearman ρ(PnL,信息) − ρ(PnL,噪音) | 每周一 |
| **D3** | Composure (镇定度) | 波动率-过度反应控制 | stop~ADX 回归分析 | ≥5轮辩论自动点亮 |
| **D4** | Discipline (纪律) | 规则自检遵守度 | RuleChecker 检查 R13/R14/R-resonance | 每周一 |
| **D5** | Reliability (可靠性) | 闭环完成率 | 剔除陈旧基础设施失败后的 fresh 完成率 | 每周一 |

### 2.2 评分流程

```
每周一 08:30 (scheduler 触发)
    │
    ▼
apm_scorecard.py
    │
    ├─ 读取 memory/debate_journal.json (辩论记录)
    ├─ 读取 memory/execution_followup.json (验证结果)
    ├─ 读取 memory/validation_stats.json (统计)
    │
    ├─ D1: 对每轮辩论, 检查 held_out_judge.coherence_score
    │      → 计算平均一致性
    │
    ├─ D2: 对已验证裁决, 计算 Spearman 秩相关
    │      → 成本感知 PnL (COST_BPS=2.0)
    │      → ρ(PnL, 信息信号) − ρ(PnL, 噪音信号)
    │
    ├─ D3: 回归分析 stop_distance ~ ADX
    │      → 检查高波动时是否过度反应
    │  辩论<5轮时 fallback:
    │      → 读取 memory/generation_metrics/ 的 schema_pass_rate
    │      → <80% → degenerate（解码质量差）
    │      → ≥80% → fallback（正常）
    │
    ├─ D4: RuleChecker 检查每条裁决
    │      → R13: ADX≥70 仓位上限 3.5%
    │      → R14: ADX≥50 仓位上限 2.5%
    │      → R-resonance: 多共振仓位上限
    │
    ├─ D5: 统计闭环完成率
    │      → 剔除 >14天 的陈旧失败
    │      → fresh_completion_rate = completed / (completed + fresh_failed)
    │
    └─ 输出: memory/apm_scorecard.json
```

### 2.3 评分卡输出格式

```json
{
  "generated_at": "2026-07-10 08:30",
  "period": "2026-07-03 ~ 2026-07-09",
  "scores": {
    "D1_coherence": 0.82,
    "D2_acuity": 0.15,
    "D3_composure": null,
    "D4_discipline": 0.95,
    "D5_reliability": 0.88
  },
  "details": {
    "D1": {"avg_coherence": 0.82, "total_debates": 12},
    "D2": {"spearman_info": 0.34, "spearman_noise": 0.19, "net": 0.15},
    "D3": {"status": "not_lit", "reason": "debates < 5"},
    "D4": {"violations": 1, "total_checked": 20, "rules_checked": ["R13", "R14", "R-resonance"]},
    "D5": {"completed": 15, "fresh_failed": 2, "stale_failed": 1}
  }
}
```

### 2.4 代码位置

| 组件 | 文件 | 说明 |
|:-----|:-----|:-----|
| 评分卡主逻辑 | `scripts/apm_scorecard.py` | 五轴计算 + 输出 |
| D2 成本感知 PnL | `scripts/validate_verdicts.py` | `COST_BPS=2.0` 参数 |
| D4 纪律钳制 | `scripts/enforce_discipline.py` | R13/R14/R-resonance 仓位上限 |
| held-out judge | `agents/futures-judge-heldout.md` | D1 一致性审计 Agent |
| 种子回填 | `scripts/memory_writer.py` | `compute_heldout_coherence()` 确定性 rubric |

## 3. 统一日志框架

### 3.1 日志架构

```
unified_logger.py
    │
    ├─ 日志级别: DEBUG < INFO < WARNING < ERROR < CRITICAL
    │   ↓ 环境变量 FDB_LOG_LEVEL 控制 (默认 INFO)
    │
    ├─ 日志格式: [时间] [FDB.模块名] [级别] 消息
    │   例: [2026-07-10 14:30:15] [FDB.scan_all] [INFO] 扫描开始
    │
    ├─ 输出目标:
    │   ├─ 控制台 (StreamHandler → stdout)
    │   └─ 文件 (FileHandler → logs/fdb_{date}.log)
    │
    ├─ Logger 缓存: _loggers dict (避免重复创建)
    │
    └─ 传播控制: logger.propagate = False (不传播到根 logger)
```

### 3.2 使用方式

```python
from scripts.unified_logger import get_logger

logger = get_logger("scan_all")
logger.info("扫描开始")
logger.warning("数据延迟")
logger.error("连接失败", exc_info=True)
```

> **v9.12.0 模块重构**: `unified_logger.py`、`trace_id.py`、`fingerprint.py` 已从 `scripts/` 根目录迁移至 `scripts/core/` 子包。原路径保留向后兼容重导出存根，现有 `from scripts.unified_logger import get_logger` 用法不变。

### 3.3 日志文件清单

| 日志文件 | 路径 | 写入者 | 用途 |
|:---------|:-----|:-------|:-----|
| `fdb_{date}.log` | `logs/` | `unified_logger.py` | 统一日志 (所有模块) |
| `pipeline_{date}.log` | `Commodities/Reports/.../` | `pipeline/runner.py` | 流水线执行日志 |
| `scheduler.log` | `logs/` | `scheduler/engine.py` | 调度器心跳日志 |

### 3.4 辩论轮次指标 (v9.0.0)

P4 六阶段攻防阶段新增 `debate_round` 指标，记录辩论进行到第几轮：

| 字段 | 类型 | 说明 | 初始值 | 增量时机 |
|:-----|:-----|:-----|:-------|:---------|
| `state.debate_round` | `int` | 辩论轮次计数器 | 0 | 每步节点完成后 +1 |
| | | P4_1 (bullish_v1) → 1 | | |
| | | P4_2 (bearish_v1) → 2 | | |
| | | P4_3 (bearish_rebuttal) → 3 | | |
| | | P4_4 (bullish_rebuttal) → 4 | | |
| | | P4_5 (bear_final) → 5 | | |
| | | P4_6 (bull_final) → 6 | | |
| `MAX_DEBATE_ROUNDS` | `int` | 最大辩论轮次 | 6 | graph.py 常量 |

**追踪方式**：`debate_round` 值通过 LangGraph Checkpointer 持久化至 PostgreSQL/SQLite，可通过 `get_state_history()` 回溯每轮状态。

### 3.5 日志统一状态

> **2026-07-14 整顿**：G3 已落地——`pipeline/runner.py` L26/L66 已改为 `from scripts.unified_logger import get_logger` + `logger = get_logger("pipeline", log_dir=_log_dir)`，流水线日志与统一日志格式一致。此前「pipeline 使用 basicConfig」的注记已过时，特此校正。

## 4. 失败模式聚类 (Telescope)

### 4.1 聚类流程

```
每周一 08:00 (scheduler 触发)
    │
    ▼
cluster_failures.py
    │
    ├─ 读取 memory/execution_followup.json (所有历史裁决)
    │
    ├─ 7 维特征提取:
    │   1. direction (多/空)
    │   2. ADX 区间 (<25 / 25-50 / 50-70 / >70)
    │   3. RSI 区间 (<30 / 30-70 / >70)
    │   4. 产业链 (黑色/有色/能化/农产品/贵金属)
    │   5. signal_type (breakout/pullback/gap)
    │   6. confidence (高/中/低)
    │   7. position_pct (≤2% / 2-5% / >5%)
    │
    ├─ 聚类分析:
    │   ├─ 单维聚类 (7个维度各聚类)
    │   ├─ 二维交叉聚类 (21种组合)
    │   └─ 品种×方向聚类
    │
    ├─ 规则关联诊断:
    │   └─ 将聚类结果与 judgment_revisions.md 中的 R 规则关联
    │
    ├─ 严重度评估:
    │   ├─ 样本数 ≥5 且胜率 <40% → 🔴 高严重度
    │   ├─ 样本数 ≥3 且胜率 <50% → 🟡 中严重度
    │   └─ 其他 → 🟢 低严重度
    │
    └─ 输出: memory/failure_clusters.json
```

### 4.2 CLI 接口

```bash
python scripts/cluster_failures.py                    # 默认运行
python scripts/cluster_failures.py --min-cases 5      # 最小样本数
python scripts/cluster_failures.py --min-winrate 40   # 最小胜率阈值
```

## 5. ViBench 历史回放

### 5.1 回放架构

```
benchmarks/test_cases.json (金标准集, 20案例)
    │
    ▼
run_benchmark.py --replay
    │
    ├─ 按 (round_id, 品种) 加载历史场景
    │
    ├─ replay_harness.py (确定性回放引擎)
    │   ├─ 重放研究员资料
    │   ├─ 重放辩手论据
    │   ├─ 重放闫判官裁决
    │   └─ 计算 coherence_weighted_accuracy
    │
    └─ 输出: benchmarks/benchmark_replay.json
```

### 5.2 CLI 接口

```bash
python scripts/run_benchmark.py --build    # 构建测试集
python scripts/run_benchmark.py --run      # 运行基准
python scripts/run_benchmark.py --replay   # 回放历史
```

## 6. 自改进脚手架

### 6.1 改进闭环

```
Stage 1: APM-CS 评分卡 (apm_scorecard.py)
    │ → 识别弱轴 (D1-D5 中低于阈值的)
    │
Stage 2: 失败聚类 (cluster_failures.py)
    │ → 识别失败模式
    │
Stage 3: ViBench 回放 (run_benchmark.py)
    │ → 识别回归
    │
    ▼
self_improve.py (自改进脚手架)
    │
    ├─ 消费 APM + 聚类 + 基准 三源数据
    │
    ├─ 生成改进建议 (proposal):
    │   ├─ "D2 Acuity 偏低, 建议增加噪音过滤阈值"
    │   ├─ "黑色系空单胜率 <40%, 建议增加 ADX>50 过滤"
    │   └─ "R14 规则违反 1 次, 建议收紧仓位上限"
    │
    └─ 输出: memory/self_improve_log.json
        (proposal 模式: 不直接改 Agent, 需人工审核后部署)
```

### 6.2 Proposal 格式

```json
{
  "timestamp": "2026-07-10 09:00",
  "source": "apm+cluster+benchmark",
  "proposals": [
    {
      "id": "P-2026-0710-001",
      "severity": "high",
      "axis": "D2",
      "finding": "Acuity net=0.15, 低于阈值0.20",
      "suggestion": "增加噪音信号过滤, 提高信息信号权重",
      "affected_agents": ["futures-judge"],
      "status": "pending_review"
    }
  ]
}
```

## 7. 辩论归档

### 7.1 归档内容

`debate_archiver.py` 在每轮辩论完成后归档：

| 归档项 | 存储位置 | 格式 |
|:-------|:---------|:-----|
| 辩论日志 | `memory/debate_journal.json` | JSON (最多500条) |
| 辩论索引 | `memory/debates/INDEX.md` | Markdown 表格 |
| 事故记录 | `memory/incidents.md` | Markdown |

### 7.2 归档特性

- **幂等**: 相同 round_id 不重复写入
- **容错**: 写入失败不阻断辩论流程
- **截断**: journal 保留最近 500 条
- **双写**: canonical (`memory/debate_journal.json`) + 副本 (`skills/memory/debate_journal.json`)

### 7.3 竞态安全写入

`memory_writer.py` 解决 10 个 Agent 并发写入问题：

| 机制 | 实现 |
|:-----|:-----|
| 独立文件 | 每个 Agent 写入 `memory/{round_id}/{agent_id}_{type}.json` |
| SQLite 备份 | 同时写入 `memory/{round_id}/debate_journal.db` (支持并发) |
| 线程锁 | `_journal_lock` 保护 journal 的读-改-写操作 |
| 完整性校验 | `validate()` 检查缺失/重复/损坏 |

## 8. D6 Output 可观测性指标（v9.16.0 新增）

### 8.1 D6 输出质量度量

| 指标 | 来源 | 说明 | 阈值 |
|:-----|:-----|:-----|:-----|
| `output_quality_score` | `scripts/output_metrics.py` | 输出质量评分 (0-100) | < 60 warning, < 80 info |
| `output_version_id` | `scripts/output_versioning.py` | 每轮报告版本 ID | 唯一可追溯 |
| `output_audit_log` | `scripts/output_audit.py` | 审计日志条目 | 每次质检记录一条 |

### 8.2 D2 Tool 工具调用指标

| 指标 | 来源 | 说明 |
|:-----|:-----|:-----|
| `tool_call_count` | `scripts/tool_metrics.py` | 工具调用次数（按 Agent） |
| `tool_success_rate` | `scripts/tool_metrics.py` | 工具调用成功率 |
| `tool_latency_ms` | `scripts/tool_metrics.py` | 工具调用延迟（毫秒） |
| `tool_anomalies` | `scripts/tool_metrics.py` | 高延迟/低成功率异常检测 |

### 8.3 数据源熔断指标

| 指标 | 来源 | 说明 |
|:-----|:-----|:-----|
| `circuit_breaker_state` | `futures_data_core.core.circuit_breaker` / `scripts/tool_circuit_breaker.py` | 熔断状态 (CLOSED/OPEN/HALF_OPEN) |
| `failure_count` | 同上 | 窗口内失败次数 |
| `fallback_chain` | `multi_source_adapter.py` | 降级链使用情况 |

### 8.4 集成点

| 点 | 指标写入 | 消费 |
|:---|:---------|:-----|
| `quality_inspector.py:check_report_integrity` | `OutputMetrics.score_output()` | 输出质量评分记录到 `memory/output_metrics/` |
| `nodes.py:node_report` | `OutputVersioning.save_output()` | 输出版本记录到 `memory/output_versions/` |
| `nodes.py:node_quality_inspect` | `OutputAudit.log()` | 审计日志记录到 `memory/output_audit/` |
| `agents.py:FdtAgentExecutor.execute()` | `ToolMetrics.record_call()` | 工具调用指标记录到 `memory/tool_metrics/` |

## 9. PostgreSQL 监控指标 (v8.3.0+) — ⚠️ 未实现

> **说明**：本节 10 个 PostgreSQL 监控指标尚未实现，保留为设计参考。实际 PG 监控通过 `fdt_pg/connection.py` 健康检查和 LangGraph 运行时指标（§9.5）覆盖。

### 9.1 监控架构

```
┌──────────────────────────────────────────────────────────────┐
│                   PostgreSQL 监控体系                        │
├──────────────────┬──────────────────┬───────────────────────┤
│   OLTP 性能指标   │   OLAP 查询指标  │   连接池健康指标       │
├──────────────────┼──────────────────┼───────────────────────┤
│ query_duration   │ mv_refresh_time  │ pool_active          │
│ row_count        │ scan_rows        │ pool_idle            │
│ transaction_rate │ query_cache_hit  │ pool_waiting         │
│ deadlock_count   │ parallel_scans   │ connection_errors    │
└──────────────────┴──────────────────┴───────────────────────┘
```

### 8.2 核心监控指标

| 指标名 | 类型 | 说明 | 告警阈值 |
|:-------|:-----|:-----|:---------|
| `pg_pool_active` | Gauge | 当前活跃连接数 | > 80% of pool_max |
| `pg_pool_idle` | Gauge | 当前空闲连接数 | < 10% of pool_max |
| `pg_pool_waiting` | Gauge | 等待连接数 | > 5 |
| `pg_connection_errors` | Counter | 连接错误总数 | 持续增长 |
| `pg_query_duration_p95` | Histogram | 查询耗时 P95 | > 500ms |
| `pg_transaction_rate` | Rate | 事务/秒 | < 1 (空闲), > 100 (繁忙) |
| `pg_deadlock_count` | Counter | 死锁次数 | > 0 |
| `pg_mv_refresh_time` | Histogram | 物化视图刷新耗时 | > 300s |
| `pg_scan_rows` | Counter | 扫描行数 | 异常激增 |
| `pg_query_cache_hit` | Gauge | 查询缓存命中率 | < 0.8 |

### 8.3 日志输出规范

所有 PostgreSQL 操作日志必须包含 `trace_id`：

```python
logger.info(f"[trace_id={trace_id}] PG query executed: scan_signals, rows={row_count}, duration={duration_ms}ms")
logger.error(f"[trace_id={trace_id}] PG connection failed: {error}")
```

### 8.4 健康检查端点

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `/health` | GET | 应用健康检查 |
| `/api/v1/status` | GET | 任务运行状态统计 |
| `pg_health_check()` | 内部 | PostgreSQL 连接健康检查 |
| `run_health_check(state)` | 内部 | LangGraph 状态健康检查（节点计时/错误记录/阶段超时检测） |
| `check_graph_health(graph_config)` | 内部 | LangGraph 图配置健康检查（节点数/慢节点检测） |

### 8.5 LangGraph 运行时指标（v8.4.0+）

| 指标 | 类型 | 说明 |
|:-----|:-----|:-----|
| `node_durations` | 字典 | 各节点执行耗时（秒） |
| `n_errors` | 整数 | 节点错误数 |
| `current_phase` | 字符串 | 当前执行阶段 |
| `completed_phases` | 列表 | 已完成阶段列表 |
| `slow_nodes` | 列表 | 慢节点（>60s）名称 |
| `overall_status` | 字符串 | 健康状态（healthy/degraded） |

### 9.6 LLM 幻觉率指标（v9.6.2+）

> **来源**: `scripts/validate_llm_output.py` — LLM 输出质量校验器，检测和度量数值型幻觉

**触发条件**: 每次 Pipeline 执行后自动运行，或通过 CLI 手动触发

**核心指标**:

| 指标 | 类型 | 说明 | 阈值 |
|:-----|:-----|:-----|:-----|
| `hallucination_rate` | 百分比 | 幻觉品种数 / 总品种数 | 目标 < 5% |
| `max_deviation_rate` | 百分比 | 最大价格偏差率 | > 20% 告警 |
| `price_deviation_mean` | 百分比 | 所有异常偏差的平均值 | — |
| `confidence_issues` | 整数 | 置信度超出范围的品种数 | > 0 告警 |
| `total_verdicts` | 整数 | 校验的裁决总数 | — |
| `hallucinated_count` | 整数 | 被判定为幻觉的裁决数 | — |

**校验维度**:

| 维度 | 校验项 | 阈值 | 说明 |
|:-----|:-------|:-----|:-----|
| 价格合理性 | 入场价 vs 扫描价 | ≤ 20% | LLM 生成价格与扫描数据偏差 |
| 价格合理性 | 止损价 vs 扫描价 | ≤ 20% | 止损价偏差检测 |
| 价格合理性 | 目标价 vs 扫描价 | ≤ 20% | 目标价偏差检测 |
| 数值一致性 | 置信度范围 | [0, 1] | 置信度必须在有效范围内 |
| 数值一致性 | 评分范围 | [-100, 100] | 多空评分必须在有效范围内 |

**输出格式** (`llm_hallucination_stats.json`):

```json
{
  "generated_at": "2026-07-20T10:00:00",
  "total_verdicts": 15,
  "hallucinated_count": 1,
  "hallucination_rate": 6.67,
  "max_deviation_rate": 57.78,
  "price_deviation_mean": 57.78,
  "confidence_issues": 0,
  "details": [...]
}
```

**CLI 用法**:

```bash
# 校验单次辩论
python scripts/validate_llm_output.py --scan full_scan_summary.json --verdict verdict.json

# 批量校验历史裁决
python scripts/validate_llm_output.py --history memory/debates/

# 指定输出文件
python scripts/validate_llm_output.py --scan scan.json --verdict verdict.json --stats my_stats.json

# 自定义阈值
python scripts/validate_llm_output.py --scan scan.json --verdict verdict.json --threshold 0.15
```

### 9.7 监控文件位置

| 文件 | 路径 | 用途 |
|:-----|:-----|:-----|
| PostgreSQL 连接日志 | `logs/pg_connection.log` | 连接池状态变化 |
| 查询性能日志 | `logs/pg_query.log` | 慢查询 (>100ms) 记录 |
| API 访问日志 | `logs/api_access.log` | FastAPI 请求日志 |

### audit 指标（v9.6.8 新增）

P2 闫判官（node_judge_direction）输出新增 `audit` 字段，记录闫判官调度与 P1 信号的偏离度：

| 字段 | 类型 | 说明 | 采集方式 |
|:-----|:-----|:-----|:---------|
| `p1_signal_direction` | str | P1原始方向（bull/bear/neutral） | 从 scan_results.all_ranked 读取 |
| `p1_signal_total` | float | P1原始总分 | 从 scan_results.all_ranked 读取 |
| `p1_signal_grade` | str | P1原始等级（STRONG/WATCH/WEAK/NOISE） | 从 scan_results.all_ranked 读取 |
| `deviation` | str | "aligned"（一致）或 "diverged"（偏离） | 比较 judge_direction.direction 与 p1_signal_direction |

用途：T+1 回测验证"去锚定"后闫判官判断质量是否优于 P1 锚定模式。


### 经验库指标

| 指标 | 类型 | 来源 |
|:--|:--|:--|
| et_records_count | gauge | INDEX.json |
| gt_patterns_count | gauge | patterns/ 目录 |
| gt_staging_count | gauge | status=staging 的模式数 |
| gt_confirmed_count | gauge | status=confirmed 的模式数 |
| distillation_last_run | timestamp | 蒸馏引擎最后运行时间 |
