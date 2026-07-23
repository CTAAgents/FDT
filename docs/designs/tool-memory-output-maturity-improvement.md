# D2/D5/D6 工程成熟度提升计划

> 版本 v1.0 | 2026-07-23
> 覆盖: D2 Tool（工具交互）、D5 Memory（跨调用状态持久化）、D6 Output（输出处理）

## 1. 当前成熟度评估

### D2 Tool — 工具交互（当前 1.5/5）

| 维度 | 当前状态 | 成熟度 |
|:-----|:---------|:------:|
| 工具调用记录 | `tool_metrics.py` 存在，有单测 | 4/5 |
| 工具熔断 | `tool_circuit_breaker.py` 存在（滑动窗口+状态机），有单测 | 4/5 |
| **运行时集成** | **两个脚本均未接入 pipeline** — 无任何文件引用它们 | **0/5** |
| 工具注册表 | 无统一工具注册表，Agent 通过硬编码路径调用工具 | 0/5 |
| 工具版本管理 | 无工具版本记录，数据源升级不可追溯 | 0/5 |

### D5 Memory — 跨调用状态持久化（当前 2.5/5）

| 维度 | 当前状态 | 成熟度 |
|:-----|:---------|:------:|
| 辩论记忆 | `memory/debate_journal.json` + `memory/debates/INDEX.md` | 4/5 |
| 验证记忆 | `memory/execution_followup.json` + `memory/validation_stats.json` | 4/5 |
| Agent 进化记忆 | `memory/agent_profiles.json` | 4/5 |
| **陈旧上下文清理** | **无过期数据淘汰机制**，memory 文件持续膨胀 | **0/5** |
| **Trace 摘要** | **无 trace summarization**，历史回放依赖原始文件 | **1/5** |
| **自进化闭环阻塞** | `execution_followup.json` 仅 6 条记录，0 条已验证 | **1/5** |
| 知识图谱 | `kb_store` MCP 可用，但未被 pipeline 消费 | 2/5 |

### D6 Output — 输出处理（当前 1.5/5）

| 维度 | 当前状态 | 成熟度 |
|:-----|:---------|:------:|
| 输出质量度量 | `output_metrics.py` 存在，有单测（218行）| 4/5 |
| 输出版本化 | `output_versioning.py` 存在，有单测 | 4/5 |
| 输出反馈闭环 | `output_feedback.py` 存在，有单测 | 4/5 |
| 输出审计日志 | `output_audit.py` 存在，有单测 | 4/5 |
| **pipeline 集成** | **以上 4 个脚本均为孤岛** — 0 处被 `fdt_langgraph/` 引用 | **0/5** |
| **APM 评分卡自动化** | 手动运行，未接入 scheduler | **0/5** |

### 综合成熟度

| 维度 | 当前 | 目标 |
|:-----|:---:|:----:|
| D2 Tool | **1.5/5** | 4.0/5 |
| D5 Memory | **2.5/5** | 4.0/5 |
| D6 Output | **1.5/5** | 4.5/5 |

## 2. 实施计划

### Phase 1 — D6 Output pipeline 集成（P1，3-5 天）

**目标**：将 output_metrics/output_versioning/output_feedback/output_audit 嵌入实际 pipeline。

#### 步骤 1.1：output_metrics 接入品藻质检

在 `fdt_langgraph/quality_inspector.py` 的 `check_report_integrity()` 中增加 `OutputMetrics.score_output()` 调用：

```python
from scripts.output_metrics import OutputMetrics

# 在 check_report_integrity 的末尾增加
om = OutputMetrics()
score = om.score_output(report_data, agent_name="quality_assurance")
if score["total_score"] < 60:
    issues.append(_issue("output_quality", f"输出质量评分偏低: {score['total_score']}/100", "warning"))
```

**改动量**：~15 行，1 文件。

#### 步骤 1.2：output_versioning 接入 node_report

在 `node_report` 写入 HTML 报告后，调用 `OutputVersioning.save_output()` 记录版本：

```python
from scripts.output_versioning import OutputVersioning

ov = OutputVersioning("debate_report")
vid = ov.save_output({
    "trace_id": trace_id,
    "report_path": report_path,
    "symbols": symbols,
    "verdict_count": len(verdicts),
}, agent_name="quality_assurance")
```

**改动量**：~20 行，1 文件。

#### 步骤 1.3：output_audit 接入 node_quality_inspect

在 `node_quality_inspect` 中增加审计日志记录：

```python
from scripts.output_audit import OutputAudit

audit = OutputAudit()
audit.log(
    agent_name="quality_assurance",
    action="quality_inspect",
    resource=f"verdict:{symbol}",
    status=overall_status,
    metadata={"retry_count": retries, "issues_count": len(all_issues)},
)
```

**改动量**：~15 行，1 文件。

#### 步骤 1.4：APM 评分卡自动化

在 `master_state.py _get_default_schedules()` 中注册每周一 08:30 的 APM 任务（纯 Python datetime 调度，无需 APScheduler）：

```python
# _get_default_schedules() 中返回的调度条目示例
ScheduleEntry(
    task_id="apm_scorecard",
    cron="30 8 * * 1",      # 每周一 08:30
    description="生成 APM 评分卡",
    enabled=True,
)
```

**改动量**：~10 行，1 文件。

### Phase 2 — D2 Tool pipeline 集成（P2，2-3 天）

**目标**：将 tool_metrics/tool_circuit_breaker 嵌入 Agent 执行流程。

#### 步骤 2.1：tool_metrics 接入 FdtAgentExecutor.execute()

在 `fdt_langgraph/agents.py` 的 `execute()` 方法中增加工具调用记录：

```python
from scripts.tool_metrics import ToolMetrics

def execute(self, prompt, trace_id="", **kwargs):
    tm = ToolMetrics()
    start = time.time()
    try:
        result = self._do_execute(prompt, trace_id, **kwargs)
        tm.record_call(self.agent_name, success=True,
                       latency_ms=(time.time() - start) * 1000)
        return result
    except Exception as e:
        tm.record_call(self.agent_name, success=False,
                       latency_ms=(time.time() - start) * 1000)
        raise
```

**改动量**：~20 行，1 文件。

#### 步骤 2.2：tool_circuit_breaker 接入数据源调用

在 `futures_data_core` 的数据采集入口增加熔断检查。连续 3 次失败的数据源自动熔断，切换到降级链下一级。

```python
from scripts.tool_circuit_breaker import CircuitBreaker

cb = CircuitBreaker()
if not cb.is_allowed(source_name):
    logger.warning(f"[CircuitBreaker] {source_name} 已熔断，切换到降级源")
    return fallback_source()
cb.record_call(source_name, success=result is not None)
```

**改动量**：~20 行，2-3 文件。

### Phase 3 — D5 Memory 清理 + 自进化闭环激活（P1，2-3 天）

**目标**：激活自进化闭环，增加过期数据清理机制。

#### 步骤 3.1：memory 过期清理机制

新增 `scripts/memory_cleaner.py` 增强版，增加：

```python
# 清理超过 90 天未更新的 memory 文件
# 删除超过 30 天的临时 JSON 数据
# 压缩 debate_journal.json（保留最近 100 条+月度摘要）
```

`memory_cleaner.py` 已存在，需增强其清理逻辑。

**改动量**：~30 行，1 文件。

#### 步骤 3.2：自进化闭环激活

检查 `master_state.py _get_default_schedules()` 是否已注册 validate_verdicts → calibrate → evolve 链。未注册则追加：

```python
# _get_default_schedules() 中返回的调度条目示例
ScheduleEntry(
    task_id="validate_verdicts",
    cron="15 9 * * *",       # 每日 09:15（辩论完成后 15 分钟）
    description="执行验证",
    enabled=True,
),
ScheduleEntry(
    task_id="calibrate_and_evolve",
    cron="0 */6 * * *",      # 每 6 小时
    description="验证 ≥5 条后自动触发 calibrate + evolve",
    enabled=True,
),
```

**改动量**：~20 行，1 文件。

### Phase 4 — 品藻 Prompt 优化（P2，1 天）

**目标**：通过实际辩论流程测试品藻角色的质检效果。

- 运行一次完整辩论流程（全量或单品种）
- 检查 `node_quality_inspect` 是否正常输出 QualityReport
- 根据输出调整 `decode_config.yaml` 中 `quality_assurance` 的参数
- 验证 `check_report_integrity` 的内容安全检测

**改动量**：无代码改动，纯测试和参数调优。

## 3. 文件改动总览

| Phase | 文件 | 改动量 | 类型 |
|:------|:-----|:------:|:-----|
| 1.1 | `fdt_langgraph/quality_inspector.py` | +15 | 修改 |
| 1.2 | `fdt_langgraph/nodes.py` | +20 | 修改 |
| 1.3 | `fdt_langgraph/nodes.py` | +15 | 修改 |
| 1.4 | `master_graph.py` | +10 | 修改 |
| 2.1 | `fdt_langgraph/agents.py` | +20 | 修改 |
| 2.2 | `futures_data_core/core/multi_source_adapter.py` | +20 | 修改 |
| 3.1 | `scripts/memory_cleaner.py` | +30 | 修改 |
| 3.2 | `master_graph.py` | +20 | 修改 |
| 文档 | `harness/05-observability.md` | +10 | 更新 |
| 文档 | `harness/03-configuration.md` | +10 | 更新 |
| 文档 | `harness/07-operations.md` | +5 | 更新 |
| 版本 | `pyproject.toml` | +1 | bump |

## 4. 时间线

```
Phase 1 (D6 pipeline) ─── 2-3h
    ↓
Phase 2 (D2 pipeline) ─── 1-2h
    ↓
Phase 3 (Memory + 自进化) ── 2-3h
    ↓
Phase 4 (品藻验证) ─── 1h
```

## 5. 验收标准

- [ ] `node_quality_inspect` 调用 `OutputMetrics.score_output()`，低分报告含 warning
- [ ] `node_report` 调用 `OutputVersioning.save_output()`，每轮报告有版本 ID 可追溯
- [ ] `node_quality_inspect` 调用 `OutputAudit.log()`，审计日志可查
- [ ] APM 评分卡每周一 08:30 自动运行
- [ ] `FdtAgentExecutor.execute()` 调用 `ToolMetrics.record_call()`
- [ ] 数据源采集入口调用 `CircuitBreaker.is_allowed()`，连续 3 次失败自动熔断
- [ ] `memory_cleaner` 可自动清理 >90 天未更新的 memory 文件
- [ ] `scheduler` 注册了 validate_verdicts 定时任务
- [ ] 所有新代码有对应单元测试
- [ ] 预提交 12 项检查全部通过
