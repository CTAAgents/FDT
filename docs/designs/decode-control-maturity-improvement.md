# Generation（解码控制）成熟度提升计划

> 版本 v1.0 | 2026-07-23

## 1. 当前成熟度评估

| 维度 | 当前状态 | 成熟度 | 目标 |
|:-----|:---------|:------:|:----:|
| D3 配置定义 | `decode_config.yaml` 10个Agent全覆盖 + JSON Schema | 5/5 | 5/5 |
| 结构化输出强制 | `enforce_structured_output.py` 脚本存在+单测 | 4/5 | 5/5 |
| 内容安全过滤 | `content_filter.py` 脚本存在+单测 | 4/5 | 5/5 |
| 解码质量度量 | `generation_metrics.py` 脚本存在+单测 | 4/5 | 5/5 |
| **运行时集成** | `agents.py` **未加载** `decode_config.yaml`，使用 `agents.yaml` 默认值 | **1/5** | **5/5** |
| **Schema校验嵌入** | 脚本存在但**未在 agent_waiter.py 调用** | **1/5** | **5/5** |
| **APM D3 镇定度** | `not_lit`（辩论 < 5 轮） | 0/5 | 5/5 |
| **内容过滤接入** | 脚本存在但**未在 node_report 调用** | **1/5** | **5/5** |
| **解码参数反馈闭环** | 无自动化降级/重试 | 0/5 | 3/5 |

**整体成熟度：约 2.2/5.0 → 目标 4.5/5.0**

## 2. 根因分析：4 个断裂处

```
decode_config.yaml ──(断裂①)──→ agents.py (不使用配置, 用 agents.yaml 默认值)
enforce_structured_output.py ──(断裂②)──→ agent_waiter.py (不接入校验)
content_filter.py ──(断裂③)──→ node_report (不调用过滤)
generation_metrics.py ──(断裂④)──→ APM 评分卡 (metrics 写入了但没被消费)
```

## 3. 实施计划

### 阶段 1 — 运行时集成（P0，断裂①②修复）

**目标**：将 `decode_config.yaml` 接入 `agents.py` 运行时，`enforce_structured_output` 接入 `agent_waiter.py`。

#### 步骤 1.1：agents.py FdtAgentExecutor 加载 decode_config.yaml

```python
# 在 __init__ 或 _load_from_registry 中增加：
from pathlib import Path
import yaml

def _load_decode_config(self, agent_name: str) -> dict:
    """加载 decode_config.yaml 中对应 Agent 的解码参数"""
    path = Path(__file__).resolve().parent.parent / "config" / "agents" / "decode_config.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        config = yaml.safe_load(f)
    return config.get("agents", {}).get(agent_name, {})
```

- 优先级：`decode_config.yaml > agents.yaml > 硬编码默认值`
- 覆盖参数：`temperature`, `max_tokens`, `top_p`, `response_format`, `retry_config`

#### 步骤 1.2：agent_waiter.py 接入 enforce_structured_output

```python
# wait_for_agent_output 中，成功读取文件后：
from scripts.enforce_structured_output import enforce_structured_output

result = enforce_structured_output(content, agent_name=agent_name)
if not result.get("success"):
    logger.warning(f"[DecodeControl] {agent_name} 结构化输出校验失败: {result.get('errors')}")
    # 不阻断，记录 metrics 供后续改进
    from scripts.generation_metrics import GenerationMetrics
    metrics = GenerationMetrics()
    metrics.record(agent_name, success=False, latency_ms=0, schema_valid=False)
```

- **非阻断式**：校验失败记录 metrics，不阻断流程
- 后续可升级为：校验失败 → 自动降级温度 → 重试

#### 步骤 1.3：decode_config.yaml 新增品藻配置

新增 `quality_assurance` 条目（较低温度确保质检一致性）。

### 阶段 2 — 监控闭环（P1，断裂④修复）

**目标**：将 `generation_metrics` 接入 `apm_scorecard.py`，点亮 D3 镇定度。

#### 步骤 2.1：apm_scorecard.py D3 fallback 计算

```python
# 在 D3 计算逻辑中增加：
# 若 debates < 5 轮 → 从 generation_metrics 读取 schema_pass_rate
# schema_pass_rate < 80% → D3 扣分
# 状态标记为 "fallback" 而非 "not_lit"
```

#### 步骤 2.2：generation_metrics 指标定义

| 指标 | 含义 | 阈值 | 影响维度 |
|:-----|:-----|:-----|:---------|
| `schema_pass_rate` | 结构化输出校验通过率 | > 80% | D3 fallback |
| `avg_latency_ms` | 平均解码延迟 | < 5000ms | D5 |
| `retry_rate` | 重试占比 | < 10% | D1/D3 |

### 阶段 3 — 内容安全接入（P2，断裂③修复）

**目标**：`content_filter` 接入 `node_report` 和 `node_quality_inspect`。

#### 步骤 3.1：node_report 增加内容过滤

在报告生成前对裁决文本做内容安全过滤，`blocked=true` 时标记报告状态而非阻断输出。

#### 步骤 3.2：node_quality_inspect 增加内容安全检查

在质检环节增加 `content_filter.check_compliance()` 作为附加检查项。

### 阶段 4 — 反馈闭环（P3，可选）

**目标**：Schema 校验失败 → 自动升温重试。

- 从 `decode_config.yaml` 读取 `retry_config.temperature_multiplier`
- `agent_waiter.py` 校验失败时，按 multiplier 升温重试
- 重试仍失败 → 记录 gap → 登记到 `08-gap-analysis.md`

## 4. 文件改动清单

| 步骤 | 文件 | 改动类型 | 预估行数 |
|:-----|:-----|:---------|:--------:|
| 1.1 | `fdt_langgraph/agents.py` | 修改 | ~25 |
| 1.2 | `scripts/agent_waiter.py` | 修改 | ~20 |
| 1.3 | `config/agents/decode_config.yaml` | 修改 | ~15 |
| 2.1 | `scripts/apm_scorecard.py` | 修改 | ~20 |
| 3.1 | `fdt_langgraph/nodes.py` | 修改 | ~15 |
| 4.1 | `docs/harness/05-observability.md` | 更新 | ~20 |
| 4.2 | `docs/harness/10-coding-standards.md` | 更新 | ~10 |
| 4.3 | `docs/harness/06-testing.md` | 更新 | ~5 |
| 4.4 | `docs/harness/07-operations.md` | 更新 | ~5 |

## 5. 验收标准

- [ ] `agents.py` 运行时正确加载 `decode_config.yaml` 并覆盖 temperature/max_tokens
- [ ] `agent_waiter.py` 每次成功读取产出后自动调用 `enforce_structured_output`
- [ ] `decode_config.yaml` 包含 `quality_assurance` 条目
- [ ] `apm_scorecard.py` D3 维度不再为 `not_lit`，至少为 `fallback`
- [ ] 所有修改已通过预提交 12 项检查
- [ ] 版本号已 bump
