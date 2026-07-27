# FDT Eval Framework — 架构文档

> 版本: v1.0.0 · 2026-07-27
> 关联: [06-testing.md](../docs/harness/06-testing.md) · [rhi_pairwise_eval.py](../scripts/harness/rhi_pairwise_eval.py)

---

## 1. 问题陈述

当前 FDT 的评估（Eval）逻辑散布在 7+ 个位置，各有独立的输入格式、输出格式和触发方式：

| 评估模块 | 位置 | 输出格式 | 触发方式 | 阶段 |
|:---------|:-----|:---------|:---------|:-----|
| quality_inspector | `fdt_langgraph/quality_inspector.py` | `QualityReport` (dict) | LangGraph 节点同步调用 | runtime |
| L1 Agent 校验 | `scripts/verification/validate_agent_output.py` | `{valid, error}` (dict) | CLI + exit code | runtime |
| LLM 数值校验 | `scripts/verification/validate_llm_output.py` | 自定 dict | CLI | runtime |
| 最终信号复查 | `scripts/verification/validate_final_signals.py` | `(errors, warns)` (tuple) | CLI + exit code | runtime |
| 裁决回溯验证 | `scripts/verification/validate_verdicts.py` | 3 个 JSON 文件 | CLI | post_hoc |
| RHI Pairwise | `scripts/harness/rhi_pairwise_eval.py` | `PairwisePreference` (dict) | RHI 循环调用 | evolution |
| 质量门禁 | `tests/fdt-gate/test_quality_gate.py` | pytest 结果 | pytest | gate |
| D3/D6 治理 | `tests/test_decode_control.py` 等 | pytest 结果 | pytest | gate |

### 1.1 7 个具体缺口

| # | 缺口 | 严重度 |
|:--|:-----|:------:|
| G1 | **无统一结果格式** — 7 种输出格式不可聚合、不可对比 | P1 |
| G2 | **无统一入口** — CLI/API/pytest 三种触发方式，无统一编排 | P1 |
| G3 | **重复校验** — Confidence 校验逻辑重复出现 3+ 次 | P1 |
| G4 | **无增量运行** — 每次全量重跑，数据成本高 | P1 |
| G5 | **结果无行动闭环** — 验证结果无人消费，不阻断、不告警 | P0 |
| G6 | **与 Harness 文档无集成** — 验证器清单只写 06-testing.md，不自动同步 | P1 |
| G7 | **无 Profile 区分** — dev/ci/nightly/release 无区别，全量太重 | P2 |

---

## 2. 架构方案

### 2.1 包结构

```
fdt_eval/
├── ARCHITECTURE.md              ← 本文档
├── __init__.py                  ← 版本号 + 公共导出
│
├── core/                        ← 框架核心（无业务逻辑）
│   ├── __init__.py
│   ├── base.py                  ← EvalCase 基类 + EvalResult TypedDict
│   ├── registry.py              ← 全局注册器（装饰器 + 元数据索引）
│   ├── runner.py                ← 统一运行器（Profile 解析 + 调度 + 缓存）
│   ├── store.py                 ← SQLite 结果持久化 + 趋势查询
│   └── action.py                ← EvalAction 闭环（阻断/告警/登记差距）
│
├── cases/                       ← 具体评估用例（扁平注册）
│   ├── __init__.py              ← 自动发现所有 case
│   │
│   ├── runtime/                 ← 运行时质检（stage=runtime）
│   │   ├── __init__.py
│   │   ├── quality_inspector.py    ← quality_inspector 迁入（保持对 LangGraph 的 import 兼容）
│   │   ├── agent_output.py         ← validate_agent_output 迁入
│   │   ├── llm_validation.py       ← merge validate_llm_output + 去重 confidence 校验
│   │   └── signal_review.py        ← validate_final_signals 迁入
│   │
│   ├── post_hoc/                ← 决策后验证（stage=post_hoc）
│   │   ├── __init__.py
│   │   ├── verdict_backtest.py     ← validate_verdicts 迁入
│   │   └── confidence_calibration.py ← VerdictDB.compute_calibration
│   │
│   ├── evolution/               ← 自进化评估（stage=evolution）
│   │   ├── __init__.py
│   │   └── rhi_pairwise.py        ← rhi_pairwise_eval 迁入
│   │
│   ├── gate/                    ← 门禁审计（stage=gate）
│   │   ├── __init__.py
│   │   ├── quality_gate.py         ← test_quality_gate 迁入（pytest 兼容包装）
│   │   └── d3_d6_governance.py     ← d3/d6 治理测试迁入
│   │
│   └── meta/                    ← 元评估（evaluating the evaluators）
│       ├── __init__.py
│       └── verifier_metrics.py     ← 验证器质量度量（漏放率/误杀率自动计算）
│
├── cli.py                       ← python -m fdt_eval [run|list|trend|dashboard|action]
│
└── profiles/                    ← Profile 定义
    ├── __init__.py
    ├── dev.yaml                  ← 开发调试（< 2s）
    ├── ci.yaml                   ← commit 前（< 30s）
    ├── nightly.yaml              ← 每日全量
    └── release.yaml              ← 发版全量 + 生产就绪度
```

### 2.2 核心层设计

#### 2.2.1 EvalResult — 统一结果契约

```python
# fdt_eval/core/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

EvalStatus = Literal["PASS", "FAIL", "ERROR", "SKIP"]
EvalStage = Literal["runtime", "post_hoc", "gate", "evolution", "meta"]
EvalSeverity = Literal["block", "warn", "info"]


@dataclass
class EvalMetric:
    """单个维度指标。"""
    name: str
    value: float
    threshold: float | None = None   # 此维度的独立阈值
    unit: str = ""                    # "%", "s", 等


@dataclass
class EvalAction:
    """评估结果触发的闭环动作。"""
    severity: EvalSeverity
    on_fail: str                      # "block_commit" / "log_gap" / "trigger_retrain" / "notify"
    on_pass: str | None = None        # "auto_update_doc" / None


@dataclass
class EvalResult:
    case_id: str                      # 注册的唯一 ID，如 "runtime.quality_inspector.p3_5"
    trace_id: str                     # 全链路追踪
    stage: EvalStage
    status: EvalStatus
    score: float                      # 0.0 - 1.0 归一化
    metrics: list[EvalMetric]         # 维度级指标列表
    detail: str                       # 摘要文本（单行）
    raw: dict | None = None           # 原始产出（可选，存储时裁剪）
    action: EvalAction | None = None  # 闭环动作定义
    duration_ms: float = 0.0          # 执行耗时
    cache_hit: bool = False           # 是否命中缓存
    timestamp: datetime = field(default_factory=datetime.now)
    version: str = "1.0"              # EvalResult schema 版本
```

#### 2.2.2 EvalCase — 基类契约

```python
# fdt_eval/core/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EvalContext:
    """评估上下文：由 Runner 注入。"""
    trace_id: str
    workspace: str | None = None        # FDT_REPORT_WORKSPACE
    overrides: dict = field(default_factory=dict)


class EvalCase(ABC):
    """所有评估用例的基类。"""

    # ── 注册元数据（子类覆盖）──
    case_id: str                        # 唯一标识，如 "runtime.quality_inspector.p3_5"
    stage: EvalStage                    # 所属阶段
    description: str = ""
    weight: float = 1.0                 # 聚合权重
    threshold: float = 0.9              # 通过阈值
    action: EvalAction | None = None    # 闭环动作
    
    # ── 缓存/增量 ──
    cache_ttl: int = 0                  # 缓存过期秒数（0=不缓存）
    data_cost: Literal["low", "medium", "high"] = "low"
    depends_on: list[str] = field(default_factory=list)  # 依赖的文件 glob

    @abstractmethod
    def run(self, context: EvalContext) -> EvalResult:
        """执行评估，返回 EvalResult。"""
        ...
```

#### 2.2.3 Registry — 全局注册

```python
# fdt_eval/core/registry.py

class EvalRegistry:
    """评估用例全局注册器。"""

    def __init__(self):
        self._cases: dict[str, type[EvalCase]] = {}
        self._instances: dict[str, EvalCase] = {}

    def register(self, cls: type[EvalCase]) -> type[EvalCase]:
        """装饰器注册。"""
        self._cases[cls.case_id] = cls
        return cls

    def get(self, case_id: str) -> EvalCase:
        """延迟初始化 + 返回单例。"""
        if case_id not in self._instances:
            self._instances[case_id] = self._cases[case_id]()
        return self._instances[case_id]

    def list(self, stage: EvalStage | None = None,
             profile: str | None = None) -> list[EvalCase]:
        """按 stage 或 profile 过滤。"""
        ...


# 全局单例
eval_registry = EvalRegistry()
```

**注册用法**：

```python
@eval_registry.register
class QualityInspectorP35(EvalCase):
    case_id = "runtime.quality_inspector.p3_5"
    stage = "runtime"
    weight = 0.20
    threshold = 0.90
    description = "品藻 P3.5 Scheme 校验"
    action = EvalAction(severity="block", on_fail="retry_spawn")
    cache_ttl = 0  # 运行时永不缓存
```

#### 2.2.4 Runner — 统一运行器

```python
# fdt_eval/core/runner.py

class EvalRunner:
    """统一运行器：Profile → Case 列表 → 增量判断 → 并行/串行执行 → 聚合 → 闭环。"""

    def __init__(self, store: EvalStore | None = None):
        self.store = store or EvalStore()

    def run(
        self,
        profile: str = "dev",
        context: EvalContext | None = None,
        cases: list[str] | None = None,      # 指定 case_id 子集
        stage: EvalStage | None = None,      # 指定 stage 子集
        force: bool = False,                  # 强制不缓存
    ) -> EvalReport: ...

    def run_single(
        self,
        case_id: str,
        context: EvalContext,
        force: bool = False,
    ) -> EvalResult: ...
```

**执行逻辑**：

```
Profile → case list
   │
   ├─ force=True? ──→ 直接运行
   │
   └─ force=False?
       ├─ 检查 cache: 依赖文件未变 + ttl 未过期 → return cached
       └─ 检查 cache: 命中失败 → run()
             │
             ├─ run() 成功 → store.save() → EvalAction 检查
             │     ├─ action.on_fail == "block_commit" → exit(1)
             │     ├─ action.on_fail == "log_gap"      → append to gap-analysis.md
             │     ├─ action.on_fail == "notify"       → 打印告警
             │     └─ action.on_pass == "auto_update_doc" → 更新 06-testing.md
             │
             └─ run() 异常 → EvalResult(status="ERROR") → 记录 + 继续
```

---

## 3. Profile 体系

| Profile | 场景 | 包含 cases | 预期耗时 | 数据成本 |
|:--------|:-----|:-----------|:--------:|:--------:|
| `dev` | 开发调试 | runtime.* (仅 schema 子集) | < 2s | low |
| `ci` | commit 前 | runtime.* + gate.*（不含 post_hoc） | < 30s | low |
| `nightly` | 每日全量 | 全部 stages | < 5min | high |
| `release` | 发版 | 全量 + meta.verifier_metrics | < 10min | high |

Profile YAML 示例（`profiles/ci.yaml`）：

```yaml
name: ci
description: "Commit 前质量门禁"
includes:
  - case_id: "runtime.*"          # glob pattern
  - case_id: "gate.*"
  - case_id: "meta.*"
excludes:
  - case_id: "*.post_hoc.*"       # 排除后验
options:
  force: false                    # 允许缓存
  fail_fast: true                 # 首错即停
  max_duration_ms: 30000
```

---

## 4. 增量 & 缓存机制

### 4.1 Manifest 文件

`fdt_eval/.eval_cache/manifest.json`：

```json
{
  "runtime.quality_inspector.p3_5": {
    "last_run": "2026-07-27T10:00:00",
    "cache_ttl": 0,
    "depends_on": [],
    "hash": null
  },
  "post_hoc.verdict_backtest": {
    "last_run": "2026-07-27T08:00:00",
    "cache_ttl": 3600,
    "depends_on": ["debate_output_*.json"],
    "hash": "a1b2c3d4"
  }
}
```

### 4.2 缓存命中规则

```
cache_hit = (
    cache_ttl > 0
    AND (now - last_run) < cache_ttl
    AND all(depends_on 文件 hash 未变)
)
```

- `runtime` 类：`cache_ttl = 0`，永不缓存（实时验证）
- `post_hoc` 类：`cache_ttl = 3600s`，依赖产出文件 hash
- `gate` 类：`cache_ttl = 300s`，依赖测试代码 hash

### 4.3 数据成本标签

| 标签 | 含义 | 示例 |
|:-----|:-----|:------|
| `low` | 纯内存计算或 Python 逻辑 | schema 校验、置信度检查 |
| `medium` | 少量文件 I/O 或简单计算 | JSON Schema 校验 |
| `high` | 外部 API 调用或大量数据 | 裁决回溯（拉 K 线）、回放 |

`fdt_eval run --profile nightly` 时优先跑完所有 `low` + `medium`，`high` 可选跳过（`--skip_high_cost`）。

---

## 5. 结果存储 & 趋势

### 5.1 SQLite Schema

```sql
CREATE TABLE eval_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    trace_id    TEXT NOT NULL,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL,         -- PASS / FAIL / ERROR / SKIP
    score       REAL NOT NULL,         -- 0.0 - 1.0
    metrics     TEXT,                  -- JSON array of EvalMetric
    detail      TEXT,
    duration_ms REAL,
    cache_hit   INTEGER DEFAULT 0,
    version     TEXT DEFAULT '1.0',
    profile     TEXT,                  -- 运行时的 profile 名
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_case_trace ON eval_results(case_id, trace_id);
CREATE INDEX idx_created ON eval_results(created_at);
CREATE INDEX idx_stage_status ON eval_results(stage, status);
```

### 5.2 趋势查询

```bash
# 单个 case 的趋势
python -m fdt_eval trend --case runtime.quality_inspector.p3_5  --last 30

# 按阶段聚合
python -m fdt_eval trend --stage runtime --last 7d

# 引擎整体评分趋势
python -m fdt_eval trend --agg --last 30d
```

输出示例：

```
case_id: runtime.quality_inspector.p3_5
  recent 30 runs: PASS=28 FAIL=2 (93.3%)
  score trend: 0.92 → 0.95 → 0.93 → 0.97 (↑)
  last FAIL: 2026-07-25 (缺失 entry_price)
```

---

## 6. 聚合记分公式

### 6.1 单次运行聚合

$$EvalScore = \frac{\sum_{i \in cases} w_i \cdot s_i \cdot \mathbb{1}(s_i \ge t_i)}{\sum_{i \in cases} w_i \cdot \mathbb{1}(s_i \ge t_i)} \times \left(1 - \frac{|failures|}{|total|}\right)$$

- $w_i$: 每个 case 的权重
- $s_i$: 归一化得分 [0, 1]
- $t_i$: 通过阈值
- $|failures|$: status=FAIL 的 case 数
- $|total|$: 总 case 数
- 乘数: 失败惩罚项（至少一个 FAIL 就有惩罚）

### 6.2 按 Profile 聚合

```python
def aggregate_by_profile(report: EvalReport) -> dict:
    """按 Profile 输出聚合摘要。"""
    return {
        "profile": report.profile,
        "total": len(report.results),
        "passed": sum(1 for r in report.results if r.status == "PASS"),
        "failed": sum(1 for r in report.results if r.status == "FAIL"),
        "score": _compute_aggregate(report.results),
        "stage_breakdown": {
            stage: _compute_aggregate([r for r in report.results if r.stage == stage])
            for stage in ("runtime", "post_hoc", "gate", "evolution", "meta")
        },
        "blockers": [r for r in report.results
                     if r.status == "FAIL" and r.action and r.action.severity == "block"],
    }
```

---

## 7. Eval-to-Action 闭环

| on_fail | 行为 | 适用场景 |
|:--------|:-----|:---------|
| `block_commit` | 阻断 git commit / CI，输出失败原因 | quality_gate, d3_d6_governance |
| `block_publish` | 阻断信号推送 | signal_review |
| `retry_spawn` | 触发 LangGraph 重试机制 | quality_inspector（已有，包装对齐） |
| `log_gap` | 自动追加到 `docs/harness/08-gap-analysis.md` | 长期未修复的违反 |
| `trigger_retrain` | 触发 RHI 重校权重 | verifier_metrics (漏放率超标) |
| `notify` | 打印告警到 stderr | 非阻断类警告 |

**自动写入 gap-analysis.md 的格式**：

```markdown
## [自动登记] Eval: {case_id} — {detail}

| 字段 | 值 |
|:-----|:---|
| 登记时间 | {timestamp} |
| 来源 | fdt_eval action pipeline |
| 严重度 | {action.severity} |
| 状态 | open |
| 影响 | {detail} |
```

---

## 8. 与 Harness 文档的集成

### 8.1 自动同步 06-testing.md

当 `fdt_eval run --profile ci --update_docs` 时：

1. 扫描 `fdt_eval/cases/` 所有注册的 case
2. 读取 `06-testing.md` 的 §10.4（验证器清单）
3. 比对：新增 case 自动追加，删除 case 标为 (已归档)
4. 用 `## 一致性元数据` 表格更新代码→文档映射

### 8.2 验证器质量度量联动

`cases/meta/verifier_metrics.py` 每个 case 的 `run()` 接受一个可选参数：

```python
class VerifierMetricsEval(EvalCase):
    case_id = "meta.verifier_metrics"
    stage = "meta"
    weight = 0.0   # 元评估不计入总体评分
    action = EvalAction(severity="block", on_fail="trigger_retrain")

    def run(self, context: EvalContext) -> EvalResult:
        # 从 eval_results 表读取最近 N 次运行
        # 计算每个验证器的 false_pass_rate / false_block_rate
        # 如漏放率 > 1% → status=FAIL, action.block
        # 输出到 06-testing.md §10.4 的"当前质量"列
        ...
```

---

## 9. 权重校准方法

### 9.1 初始权重

| 维度 | 建议权重 | 依据 |
|:-----|:--------:|:-----|
| runtime (运行时质检) | 0.35 | 最高频率，直接影响每轮产出质量 |
| gate (门禁审计) | 0.25 | 守护代码质量和系统稳定性 |
| post_hoc (决策后验证) | 0.25 | 长期质量，反映实际交易效果 |
| evolution (自进化) | 0.15 | RHI 对比，低频但战略价值高 |

### 9.2 自动校准（每 100 轮触发）

**方法：留一法 (Leave-One-Out) 相关性分析**

```
对于每个权重 wi:
  1. 固定其他权重
  2. 令 wi 在 [0.05, 0.50] 区间以 0.05 步长扫描
  3. 计算每种 wi 取值下，EvalScore 与"裁决后续正确率"的 Spearman 相关系数
  4. 选择使相关系数最大化的 wi
  
约束:
  - 所有 wi 之和 = 1.0
  - 每个 wi >= 0.05
```

校准通过 `python -m fdt_eval calibrate --last 100` 触发，结果写入 `profiles/weight_history.json`。

---

## 10. Profile 场景矩阵

| Profile | 触发时机 | 阻断级别 | fail_fast | 缓存 | 预期耗时 |
|:--------|:---------|:--------:|:---------:|:----:|:--------:|
| `dev` | 每次修改后手动 | block=0 | false | 全量 | < 2s |
| `ci` | commit 前 pre-commit | block≥1 阻断 | true | 是 | < 30s |
| `nightly` | 每日 02:00 调度 | block=0（仅记录） | false | 否 | < 5min |
| `release` | 发版前 | block≥1 阻断 | true | 否 | < 10min |

---

## 11. Migration Plan（双轨迁移）

### Phase 1: 框架 + 独立脚本迁入（低风险）

| 步骤 | 内容 | 验证 |
|:-----|:-----|:-----|
| 1.1 | 建立 `fdt_eval/core/` 基础架构 | `fdt_eval list` 输出空列表 |
| 1.2 | 迁入 `validate_agent_output.py` → `cases/runtime/agent_output.py` | 原地脚本保留薄代理层，import 不变 |
| 1.3 | 迁入 `validate_llm_output.py` → `cases/runtime/llm_validation.py` | 去重 confidence 校验，原地脚本 import 新实现 |
| 1.4 | 迁入 `validate_final_signals.py` → `cases/runtime/signal_review.py` | 保持 CLI 兼容 |
| 1.5 | 迁入 `validate_verdicts.py` → `cases/post_hoc/verdict_backtest.py` | 保持 CLI 兼容 |
| **验证** | `python -m fdt_eval run --profile dev` 通过 + 原地 CLI 不变 | |

### Phase 2: quality_inspector 迁入 + 去重（中等风险）

| 步骤 | 内容 | 风险 | 缓解 |
|:-----|:-----|:----|:-----|
| 2.1 | quality_inspector.py 原地保留薄代理层 `from fdt_eval.cases.runtime.quality_inspector import *` | 低 | import 不变 |
| 2.2 | 代理层测试：pytest 测试 import quality_inspector 是否正常 | 低 | conftest.py mock |
| 2.3 | 全部合并 confidence 校验到 `fdt_eval/cases/_shared/confidence_validator.py` | 中 | 审计每一处调用点 |
| **验证** | `python -m pytest tests/fdt_langgraph/ -v` 全绿 | |

### Phase 3: 门禁/演化/元评估 + 看板（零风险）

| 步骤 | 内容 | 验证 |
|:-----|:-----|:-----|
| 3.1 | 迁入 quality_gate → `cases/gate/quality_gate.py`（pytest 兼容包装） | pytest 可同时从 tests/ 和 fdt_eval/ 运行 |
| 3.2 | 迁入 d3_d6 → `cases/gate/d3_d6_governance.py` | 同上 |
| 3.3 | 迁入 rhi_pairwise → `cases/evolution/rhi_pairwise.py` | RHI 循环 import 不变 |
| 3.4 | SQLite 存储 + 趋势看板 | `fdt_eval trend` 有输出 |
| 3.5 | Pre-commit hook 集成 (ci profile) | commit 时自动触发 |
| 3.6 | docs/harness/06-testing.md 自动同步 | 运行后文档更新 |
| **验证** | `python -m fdt_eval run --profile nightly && fdt_eval dashboard` | |

---

## 12. 各 Phase 的归口职责

| 角色 | 当前 | Phase 1 后 | Phase 2 后 | Phase 3 后 |
|:-----|:-----|:----------|:----------|:----------|
| **品藻 (quality_assurance)** | 调用 quality_inspector 函数 | 调用 fdt_eval runner | 同左 | 同左 |
| **明鉴秋** | spawn + 轮询 + 调 validate_agent_output | spawn + 轮询 + 调 fdt_eval runner | 同左 | 同左 |
| **RHI** | 调 rhi_pairwise_eval.evaluate_pairwise | 调 fdt_eval runner | 同左 | 同左 |
| **pre-commit hook** | 手工检查清单 | 手工 | 手工 | `fdt_eval run --profile ci` |
| **06-testing.md** | 手动更新 | 手动 | 手动 | `fdt_eval run --update_docs` 自动 |

---

## 13. 反模式防护

| AP ID | 反模式 | 防护措施 |
|:------|:-------|:---------|
| AP02 (跳过审核) | 不经过 Eval 直接提交 | pre-commit 强制 `fdt_eval run --profile ci` |
| AP06 (无独立验证) | 验证器自身无人验证 | `cases/meta/verifier_metrics.py` 自动计算漏放率/误杀率 |
| AP08 (多循环共写状态) | Eval 结果与运行时状态耦合 | Eval 结果是只写 SQLite，不修改运行时状态 |
| AP09 (知识在 Chat 历史) | Eval 趋势在对话中丢失 | SQLite 持久化 + dashboard 可视化 |
| AP10 (一个 PR 改所有) | 一个 PR 改 20+ 文件 | Eval 结果追踪变更范围 |

---

## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `fdt_eval/core/base.py` — `EvalResult` | §2.2.1 | EvalResult 含 case_id/stage/status/score/metrics/detail | `grep -c "EvalResult" fdt_eval/core/base.py` |
| `fdt_eval/core/base.py` — `EvalCase` | §2.2.2 | EvalCase 是 ABC，含 run() 抽象方法 | `grep -c "class EvalCase" fdt_eval/core/base.py` |
| `fdt_eval/core/registry.py` | §2.2.3 | eval_registry 全局单例，支持装饰器注册 | `python -c "from fdt_eval.core.registry import eval_registry; print(eval_registry._cases)"` |
| `fdt_eval/core/runner.py` — `run()` | §2.2.4 | run() 接受 profile/cases/stage/force 参数 | `python -c "from fdt_eval.core.runner import EvalRunner; r=EvalRunner(); r.run(profile='dev')"` |
| `fdt_eval/profiles/dev.yaml` | §3 | dev profile 仅包含 runtime 子集 | `grep -c "runtime" fdt_eval/profiles/dev.yaml` |
| `fdt_eval/.eval_cache/manifest.json` | §4.1 | manifest 文件存在、格式正确 | `python -c "import json; json.load(open('fdt_eval/.eval_cache/manifest.json'))"` |
| `fdt_eval/cases/meta/verifier_metrics.py` | §8.2 | 自动计算 false_pass_rate / false_block_rate | `python -m fdt_eval run --case meta.verifier_metrics` |
| §9 权重校准 | §9.2 | calibrate 命令接受 --last 参数 | `python -m fdt_eval calibrate --last 100` |
| §10 迁移计划 | §11 | Phase 1 迁移后原地 CLI 不变 | 逐个执行原地脚本验证退出码 |
| `fdt_eval/feedback/config_store.py` — `ConfigStore` | §7 (反馈闭环) | get_position_pct() 返回 [1%,15%] | `python -c "from fdt_eval.feedback.config_store import ConfigStore; c=ConfigStore(); assert 1<=c.get_position_pct('RB',0.7)<=15"` |
| `fdt_eval/feedback/position_tuner.py` — `PositionTuner` | §7 (反馈闭环) | accuracy<0.25 时 weight=0.3 | `python -c "from fdt_eval.feedback.config_store import ConfigStore; cs=ConfigStore(); cs.update('TEST',n_validations=10,recent_accuracy=0.2); print(cs.get('TEST'))"` |
| `fdt_eval/feedback/parameter_tuner.py` — `ParameterTuner` | §7 (反馈闭环) | stop_hit_rate>0.4 时 multiplier 增加 1.2x | 测试验证: `pytest tests/fdt_eval_feedback/test_feedback.py::TestParameterTuner -v` |
| `fdt_eval/cases/meta/trading_quality_feedback.py` | §7 (反馈闭环) | 注册为 meta.trading_quality_feedback | `python -c "from fdt_eval.core.registry import eval_registry; import fdt_eval.cases; print('OK' if 'meta.trading_quality_feedback' in eval_registry.all_case_ids else 'MISS')"` |
| `tests/fdt_eval_feedback/test_feedback.py` | C6 | 16 个测试覆盖 3 个模块 | `python -m pytest tests/fdt_eval_feedback/ -q --no-cov` |
| `fdt_langgraph/_nodes_verdict.py` — `node_signal_output` | §7 (反馈闭环) | CTP 信号使用 ConfigStore 动态参数 | 三重回退链: ConfigStore → ATR+乘数 → 硬编码 0.97/1.05/3 |
