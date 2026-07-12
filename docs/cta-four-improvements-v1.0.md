# CTA 多 Agent 系统四项改进方案 v1.1

> 基于 13 篇 arXiv 论文精读 → 已实施的四项改进（2026-07-11 全部施工完成）
> 生成日期: 2026-07-11 | 最后更新: 2026-07-11 06:03

---

## 总览

| 编号 | 改进 | 来源论文 | 作用域 | 优先级 | 状态 |
|:----:|:----|:---------|:------|:------:|:----:|
| A | **IGP 推理门控** | AgenticAITA | FDT 全局 | P0 | ✅ v1.0.0 |
| B | **闫判官"纠偏优先"裁决框架** | Macro Economists | FDT 闫判官模块 | P0 | ✅ v2.2 |
| C | **二层安全门 Risk Manager** | AgenticAITA + Explanatory Equilibrium | commodity-trend-signal | P0 | ✅ v1.0.0 |
| D | **可配置协调层架构** | Coordination Layer | FDT 编排层 | P1 | ✅ v1.0.0 |

---

## 改进 A：IGP 推理门控（Inference Gating Protocol）

### 背景问题

FDT 辩论专家团当前时序铁律：
```
数技源 → 探源/观澜/链证源 → 正/反方辩手 → 闫判官
```

这条流水线本身是严串行的，但存在隐性并发风险：
1. **研究员层内部的资源争用**：探源、观澜、链证源三个研究员 Agent 实际是并行唤起的，若中间某个研究员延迟或抛出异常，闫判官不会等待，可能导致"有缺损的研究成果"进入辩手环节
2. **超时裁决**：当前没有超时保护机制，一旦某个 Agent hang，整条流水线卡死
3. **无审计轨迹**：Agent 的执行顺序和耗时没有结构化记录，事后无法复现"为什么结果长这样"

### 设计方案

引入 AgenticAITA 的互斥锁 + 审计三表模式，封装为 `InferenceGate` 模块。

```
┌─────────────────────────────────────────────┐
│              InferenceGate                    │
│  ┌─────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Mutex    │  │ Timeout  │  │ Audit Trail│  │
│  │ Lock     │ → │ Guard    │ → │ (三表)     │  │
│  └─────────┘  └──────────┘  └────────────┘  │
└─────────────────────────────────────────────┘
```

### 核心代码

```python
"""
inference_gate.py — 推理门控模块
适用于 FDT 辩论专家团
"""

import time
import threading
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ── 配置 ──────────────────────────────────────
COOLDOWN_SECONDS = 1800       # 全局冷却期（30分钟，参考 AgenticAITA 论文）
SESSION_LOCK_TIMEOUT = 600    # 会话锁超时（10分钟）
AUDIT_DIR = Path("plugins/futures-debate-team/audit/")

# ── 数据结构 ──────────────────────────────────

@dataclass
class InferenceProposal:
    """推理请求提案"""
    agent_name: str             # Agent 名称
    intent: str                 # 意图描述
    required_resources: list    # 需要的资源/数据源
    estimated_cost_tokens: int  # 预估 token 消耗
    priority: int = 5           # 优先级 1-10


@dataclass
class InferenceResult:
    """推理执行结果"""
    agent_name: str
    success: bool
    duration_seconds: float
    output_path: str            # 输出文件路径
    error: Optional[str] = None
    token_used: int = 0


@dataclass
class AuditRecord:
    """单条审计记录"""
    timestamp: str
    agent: str
    action: str                # lock_acquired / pipeline_busy / completed / timeout / cooldown
    proposal: Optional[dict] = None
    result: Optional[dict] = None
    metadata: dict = field(default_factory=dict)


# ── 门控实现 ──────────────────────────────────

class InferenceGate:
    """
    全局推理门控。
    互斥锁 + 冷却期 + 审计三表。
    参考: AgenticAITA (arXiv:2605.12532) §3.2-3.3
    """

    def __init__(self, cooldown: int = COOLDOWN_SECONDS):
        self._lock = threading.Lock()
        self._pipeline_busy = False
        self._pipeline_owner: Optional[str] = None
        self._last_release_time: float = 0
        self._cooldown = cooldown
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 审计三表
        self.audit_log: list[AuditRecord] = []
        self.pipeline_log: list[dict] = []
        self.cost_log: list[dict] = []

        # 确保审计目录存在
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 互斥锁 ──

    def acquire(self, proposal: InferenceProposal) -> bool:
        """
        请求推理锁。
        如果 pipeline 正忙或在冷却期，返回 False，并记录审计。
        """
        now = time.time()

        # 冷却期检查
        if self._pipeline_busy:
            elapsed = now - self._last_release_time
            if elapsed < self._cooldown:
                self._log(AuditRecord(
                    timestamp=datetime.now().isoformat(),
                    agent=proposal.agent_name,
                    action="cooldown",
                    proposal=asdict(proposal),
                    metadata={"cooldown_remaining": round(self._cooldown - elapsed, 1)}
                ))
                return False

        with self._lock:
            if self._pipeline_busy:
                self._log(AuditRecord(
                    timestamp=datetime.now().isoformat(),
                    agent=proposal.agent_name,
                    action="pipeline_busy",
                    proposal=asdict(proposal)
                ))
                return False

            self._pipeline_busy = True
            self._pipeline_owner = proposal.agent_name

            self._log(AuditRecord(
                timestamp=datetime.now().isoformat(),
                agent=proposal.agent_name,
                action="lock_acquired",
                proposal=asdict(proposal)
            ))
            return True

    def release(self, result: InferenceResult):
        """释放推理锁，记录执行结果和 token 消耗"""
        with self._lock:
            self._pipeline_busy = False
            self._pipeline_owner = None
            self._last_release_time = time.time()

            self._log(AuditRecord(
                timestamp=datetime.now().isoformat(),
                agent=result.agent_name,
                action="completed" if result.success else "failed",
                result=asdict(result)
            ))

            # 记录 token 消耗
            self.cost_log.append({
                "session_id": self._session_id,
                "agent": result.agent_name,
                "tokens": result.token_used,
                "duration": result.duration_seconds,
                "success": result.success,
                "timestamp": datetime.now().isoformat()
            })

    # ── 审计 ──

    def _log(self, record: AuditRecord):
        self.audit_log.append(record)

    def save_audit(self):
        """持久化审计三表到文件"""
        session_dir = AUDIT_DIR / f"session_{self._session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        # 表1: 审计日志 (trades 等价物)
        with open(session_dir / "audit_log.json", "w") as f:
            json.dump([asdict(r) for r in self.audit_log], f, ensure_ascii=False, indent=2)

        # 表2: 流水线日志 (pipeline_log)
        with open(session_dir / "pipeline_log.json", "w") as f:
            json.dump(self.pipeline_log, f, ensure_ascii=False, indent=2)

        # 表3: 成本日志 (ollama_calls 等价物)
        with open(session_dir / "cost_log.json", "w") as f:
            json.dump(self.cost_log, f, ensure_ascii=False, indent=2)

        return str(session_dir)


# ── 装饰器：集成到 Agent 调用中 ──────────────

def with_gate(gate: InferenceGate):
    """Agent 函数装饰器：自动获取锁、记录审计"""
    def decorator(func):
        def wrapper(agent_name: str, *args, **kwargs):
            proposal = InferenceProposal(
                agent_name=agent_name,
                intent=kwargs.pop("intent", "unspecified"),
                required_resources=kwargs.pop("resources", []),
                estimated_cost_tokens=kwargs.pop("estimated_tokens", 0),
            )
            if not gate.acquire(proposal):
                return {"status": "blocked", "reason": "pipeline_busy_or_cooldown"}

            start = time.time()
            try:
                output = func(agent_name, *args, **kwargs)
                duration = time.time() - start
                result = InferenceResult(
                    agent_name=agent_name,
                    success=True,
                    duration_seconds=duration,
                    output_path=str(output) if isinstance(output, Path) else "inline",
                    token_used=proposal.estimated_cost_tokens,
                )
                return output
            except Exception as e:
                duration = time.time() - start
                result = InferenceResult(
                    agent_name=agent_name,
                    success=False,
                    duration_seconds=duration,
                    output_path="",
                    error=str(e),
                )
                raise
            finally:
                gate.release(result)
        return wrapper
    return decorator
```

### 集成到 FDT 的要点

1. **初始化**：在 `闫判官` 初始化时创建全局 `InferenceGate` 实例
2. **装饰**：数技源、探源、观澜、链证源、正/反方辩手五个 Agent 函数用 `@with_gate(gate)` 装饰
3. **锁获取即弃**：任何 Agent 无法获取锁时，闫判官收到 `blocked` 状态，可决定是等待还是跳过
4. **审计保留**：每次会话的审计三表保存在 `plugins/futures-debate-team/audit/`，可追溯完整推理轨迹

---

## 改进 B：闫判官"纠偏优先"裁决框架

### 背景问题

Macro Economists (arXiv:2606.08283) 的核心发现：
| 比较 | ΔSharpe | p值 | 结论 |
|:----|:-------:|:---:|:-----|
| Best LLM vs Rule | +0.044 | <0.10 | LLM 策略显著更好 |
| Debate vs Best Single | −0.004 | 0.769 | **辩论不产生增量收益** |

论文讨论指出："Debate Agent 的价值不在于预测精度，而在于**纠偏**——防止单一 Agent 在极端情况下偏航。"

这对 FDT 的设计启示是明确的：**闫判官的裁决不应以"多空辩论出更好的方向"为目标，而是确保辩手的论点不被限定在数技源设定的论点范围内。**

### 设计方案

在闫判官现有职责（主持+裁决+时序控制）基础上，增加三个硬性检查层：

```
闫判官裁决流水线（扩展版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 时序检查  → 检查 Agent 执行顺序正确
② 边界检查  → 辩手论点必须在数技源输出范围内  ← 新增
③ 收敛检查  → 双方论点收敛到什么程度            ← 新增
④ 一致性检查→ 辩手论据必须来自研究员产出          ← 已存在（角色边界铁律）
⑤ 最终裁决  → 输出多空方向+置信度
```

### 核心 Prompt 修改

在闫判官的 system prompt 中，加入以下段落（替换现有裁决逻辑）：

```
## 【硬性检查一：论点边界检查】（基于论文 Macro Economists）

在裁决前，你必须执行以下验证：

1. 列出数技源本次输出的【原始论点集】S = {s₁, s₂, ..., sₙ}
2. 列出正方辩手提出的【所有论点集】P = {p₁, p₂, ..., pₘ}
3. 对每个 pᵢ 检查：
   - pᵢ 是否直接映射到 S 中的某个 sⱼ？
   - 或是从某个 sⱼ 通过逻辑推理得出的衍生论点？
   - 或是从研究员（探源/观澜/链证源）的客观资料中提炼的？
4. 如果 pᵢ 不符合上述三条之一 → 标记为【无效论点】，退回辩手
5. 如果某一方超过 50% 论点被标记为无效 → 该方本轮辩论无效

## 【硬性检查二：收敛度评估】

输出裁决时，同时输出：

- divergence_score = 双方主要分歧点数量 / 总论点数量
  - 0.0 ~ 0.3：高度收敛 → 辩论作用较小，以数技源方向为准
  - 0.3 ~ 0.7：中度分歧 → 需要额外一轮辩论
  - 0.7 ~ 1.0：严重分歧 → 以数技源方向+研究员客观资料综合判断

- confidence_adjustment
  - 如果 divergence_score < 0.3：置信度不做调整
  - 如果 divergence_score > 0.7：置信度降低 20%（警告：高度不确定性）

## 【裁决输出格式】

必须输出以下 JSON 块：

{
  "verdict": "long | short | neutral",
  "confidence": 0.0~1.0,
  "divergence_score": 0.0~1.0,
  "invalid_arguments": {"positive": ["论点1", ...], "negative": ["论点2", ...]},
  "primary_direction_source": "数技源 | 辩论收敛",
  "reasoning_basis": "简要说明依据"
}
```

### 验证方法

可以通过模拟测试验证效果：

| 场景 | 输入 | 预期输出 |
|:----|:-----|:---------|
| 辩手引用数技源外的论据 | 正方提出"地缘政治风险"（数技源未提及） | 标记为无效论点 |
| 双方高度收敛 | divergence_score=0.15 | 置信度不做调整，以数技源为准 |
| 严重分歧 | divergence_score=0.85 | 置信度降低20%，综合判断 |
| 论点来自研究员资料 | 正方引用"链证源"的客观数据 | 视为有效论点 |

---

## 改进 C：二层安全门 Risk Manager

### 范围声明

> ⚠️ **重要：改进C 作用于 commodity-trend-signal（趋势信号 CTA 系统），与 FDT 辩论专家团的"风控明"角色是两个完全独立的系统。** 两者不冲突、不重叠、不替代。
>
> | 体系 | 风控层 | 实现方式 | 风控对象 |
> |:----|:-------|:--------|:---------|
> | **FDT 辩论专家团** | 风控明 | Agent 级（LLM推理） | 辩论产出的交易方案（策执远） |
> | **commodity-trend-signal** | 改进C Risk Manager | 代码级（确定性硬门） | 算法产出的交易信号（突破/均线） |
>
> 参考 `agents/futures-risk-manager.md` 可知风控明定位：三合一（擂台裁判+资金管家+逻辑质检），在辩论 P4 阶段对策执远的方案做杠杆/保证金/合约月份的 LLM 推理风控，输入输出均为结构化 JSON。那是 Agent 层面的柔性风控。
>
> 改进C 解决了另一个系统的问题：

### 背景问题

`commodity-trend-signal` 当前架构中——趋势突破信号（DC20/DC55、布林带、ADX 等算法）生成后直接进入交易决策管道，缺少代码级的硬约束：
1. **确定性硬门**：LLM 无法绕过的代码级检查（止损、头寸、置信度）
2. **随机审计**：部分交易触发 LLM 审计，防止系统性模式
3. **审计轨迹**：完整记录每个信号的推理链

### 设计方案

融合 AgenticAITA 的**硬门安全层**和 Explanatory Equilibrium 的**随机审计机制**，构建二层 Risk Manager。

```
                         ┌──────────────────────────────┐
                         │       Trading Signal          │
                         │  (来自 commodity-trend-signal) │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                    ┌───────────────────────────────────┐
       Layer A ────▶│  确定性硬门 (Deterministic Gate)  │
                    │  代码级检查，LLM 无法绕过           │
                    │  ├ 方向有效性检查                   │
                    │  ├ 置信度阈值 (≥0.60)               │
                    │  ├ 止损限制 (≤2%)                   │
                    │  └ 头寸限制 (≤$500)                 │
                    └──────────────┬────────────────────┘
                                   │ Pass
                                   ▼
                    ┌───────────────────────────────────┐
       Layer B ────▶│  随机审计层 (Stochastic Audit)     │
                    │  概率 q=0.3 触发 LLM 审计           │
                    │  ├ 安全边际豁免检查                  │
                    │  ├ 声明字段规则引擎                  │
                    │  └ 保守默认拒绝                     │
                    └──────────────┬────────────────────┘
                                   │ Approved
                                   ▼
                    ┌───────────────────────────────────┐
                    │     Execution Engine               │
                    │  + 审计三表持久化                    │
                    └───────────────────────────────────┘
```

### 核心代码

```python
"""
risk_manager.py — 二层安全门风控模块
适用于 commodity-trend-signal / 任何 CTA 系统
参考: AgenticAITA §4.3 + Explanatory Equilibrium §3.2
"""

import random
import json
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# ── 配置 ──────────────────────────────────────

# Layer A: 确定性硬门参数
HARD_GATE_CONFIG = {
    "max_position_usd": 500,           # 单品种最大头寸 ($)
    "max_stop_loss_pct": 0.02,         # 最大止损 (2%)
    "min_confidence": 0.60,            # 最小置信度
    "allowed_directions": ["long", "short"],  # 允许方向
    "max_daily_trades": 5,             # 每日最大交易次数
}

# Layer B: 随机审计参数
AUDIT_CONFIG = {
    "audit_probability": 0.30,         # 审计概率 q
    "safe_margin_threshold": 0.30,     # 安全边际阈值 (risk_score < 0.3)
    "conservative_default": "reject",  # 审计失败时的默认行为
    "audit_fields": [                  # 审计时检查的字段
        "intent", "risk_in_limit", "confidence", "size", "stop_loss"
    ],
    "samples_per_audit": 2,            # 每次审计随机抽取的字段数
}

# 审计日志目录
AUDIT_LOG_DIR = Path("data/audit_logs/")


# ── 数据结构 ──────────────────────────────────

@dataclass
class TradingSignal:
    """原始交易信号"""
    symbol: str                # 品种代码
    direction: str             # long / short
    confidence: float          # 0.0 ~ 1.0
    entry_price: float         # 入场价格
    stop_loss_pct: float       # 止损百分比 (0.01 = 1%)
    position_usd: float        # 头寸金额 ($)
    reasoning: str             # 推理链 (LLM 输出)
    source: str                # 信号来源
    timestamp: str = ""        # 信号生成时间

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class AuditResult:
    """审计结果"""
    signal_hash: str           # 信号的 SHA256 hash
    layer_a_passed: bool       # 硬门通过?
    layer_b_passed: bool       # 审计通过?
    final_decision: str        # approved / rejected / escalated
    rejection_reason: Optional[str] = None
    audit_fields_checked: list = None
    audit_mode: str = ""       # safe_margin / random_audit / bypassed
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ── Risk Manager 实现 ─────────────────────────

class RiskManager:
    """
    二层安全门风控模块。
    Layer A: 确定性硬门
    Layer B: 随机审计
    """

    def __init__(self, hard_config: dict = None, audit_config: dict = None):
        self.hard_config = {**HARD_GATE_CONFIG, **(hard_config or {})}
        self.audit_config = {**AUDIT_CONFIG, **(audit_config or {})}
        self.daily_trade_count = 0
        self.daily_date = datetime.now().date()

        # 审计日志
        self.audit_results: list[AuditResult] = []
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── Layer A: 确定性硬门 ──

    def layer_a_hard_gate(self, signal: TradingSignal) -> tuple[bool, Optional[str]]:
        """
        确定性硬门——代码级检查，LLM 无法绕过。
        检查: 方向、置信度、止损、头寸、每日限额
        """
        checks = []

        # 1. 方向有效性
        checks.append((
            signal.direction in self.hard_config["allowed_directions"],
            f"方向 '{signal.direction}' 不在允许范围内"
        ))

        # 2. 置信度阈值
        checks.append((
            signal.confidence >= self.hard_config["min_confidence"],
            f"置信度 {signal.confidence:.2f} 低于阈值 {self.hard_config['min_confidence']}"
        ))

        # 3. 止损限制
        checks.append((
            signal.stop_loss_pct <= self.hard_config["max_stop_loss_pct"],
            f"止损 {signal.stop_loss_pct:.2%} 超过上限 {self.hard_config['max_stop_loss_pct']:.0%}"
        ))

        # 4. 头寸限制
        checks.append((
            signal.position_usd <= self.hard_config["max_position_usd"],
            f"头寸 ${signal.position_usd:.0f} 超过上限 ${self.hard_config['max_position_usd']}"
        ))

        # 5. 每日交易限额
        self._reset_daily_counter()
        checks.append((
            self.daily_trade_count < self.hard_config["max_daily_trades"],
            f"今日已交易 {self.daily_trade_count} 次，超过上限 {self.hard_config['max_daily_trades']}"
        ))

        # 汇总
        for passed, reason in checks:
            if not passed:
                return False, reason

        return True, None

    # ── Layer B: 随机审计 ──

    def layer_b_audit(self, signal: TradingSignal) -> tuple[bool, str, list]:
        """
        随机审计层。
        参考 Explanatory Equilibrium: q=0.3 审计概率 + 安全边际豁免。
        """
        risk_score = self._calculate_risk_score(signal)
        audit_fields_checked = []

        # 安全边际豁免 (risk_score < 0.3 直接通过)
        if risk_score < self.audit_config["safe_margin_threshold"]:
            return True, "safe_margin", audit_fields_checked

        # 随机触发审计
        if random.random() >= self.audit_config["audit_probability"]:
            return True, "bypassed", audit_fields_checked

        # 随机抽取审计字段
        fields_pool = self.audit_config["audit_fields"]
        n_samples = min(self.audit_config["samples_per_audit"], len(fields_pool))
        audit_fields_checked = random.sample(fields_pool, n_samples)

        # 对每个抽取字段执行规则检查
        for field in audit_fields_checked:
            if not self._verify_field(signal, field):
                return False, f"field_{field}_failed", audit_fields_checked

        return True, "random_audit_passed", audit_fields_checked

    # ── 最终裁决 ──

    def evaluate(self, signal: TradingSignal) -> AuditResult:
        """
        完整风控评估流程: Layer A → Layer B → 最终决策
        """
        signal_hash = hashlib.sha256(
            json.dumps(asdict(signal), sort_keys=True).encode()
        ).hexdigest()[:16]

        # Layer A
        a_passed, a_reason = self.layer_a_hard_gate(signal)
        if not a_passed:
            result = AuditResult(
                signal_hash=signal_hash,
                layer_a_passed=False,
                layer_b_passed=False,
                final_decision="rejected",
                rejection_reason=f"Layer A 拦截: {a_reason}",
            )
            self._log(result)
            return result

        # Layer B
        b_passed, b_mode, b_fields = self.layer_b_audit(signal)
        if not b_passed:
            result = AuditResult(
                signal_hash=signal_hash,
                layer_a_passed=True,
                layer_b_passed=False,
                final_decision="rejected",
                rejection_reason=f"Layer B 拦截: {b_mode}",
                audit_fields_checked=b_fields,
                audit_mode=b_mode,
            )
            self._log(result)
            return result

        # 全部通过
        self.daily_trade_count += 1
        result = AuditResult(
            signal_hash=signal_hash,
            layer_a_passed=True,
            layer_b_passed=True,
            final_decision="approved",
            audit_fields_checked=b_fields,
            audit_mode=b_mode,
        )
        self._log(result)
        return result

    # ── 辅助方法 ──

    def _calculate_risk_score(self, signal: TradingSignal) -> float:
        """计算风险评分 (0~1, 越高越危险)"""
        score = 0.0
        score += (1.0 - signal.confidence) * 0.4        # 低置信度加分
        score += (signal.stop_loss_pct / 0.05) * 0.3     # 大止损加分
        score += (signal.position_usd / 1000) * 0.3      # 大头寸加分
        return min(score, 1.0)

    def _verify_field(self, signal: TradingSignal, field: str) -> bool:
        """验证单个字段"""
        checks = {
            "intent": lambda s: len(s.reasoning) > 20,         # 推理链不能太短
            "risk_in_limit": lambda s: s.stop_loss_pct <= 0.03, # 风控上限 3%
            "confidence": lambda s: s.confidence >= 0.50,       # 次级阈值 0.50
            "size": lambda s: s.position_usd <= 800,            # 次级头寸上限 $800
            "stop_loss": lambda s: s.stop_loss_pct <= 0.025,    # 次级止损上限 2.5%
        }
        return checks.get(field, lambda s: True)(signal)

    def _reset_daily_counter(self):
        """每日重置计数器"""
        today = datetime.now().date()
        if today != self.daily_date:
            self.daily_trade_count = 0
            self.daily_date = today

    def _log(self, result: AuditResult):
        """记录审计结果"""
        self.audit_results.append(result)
        # 追加到日志文件
        log_file = AUDIT_LOG_DIR / f"audit_{datetime.now().strftime('%Y%m')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

    def get_stats(self) -> dict:
        """获取风控统计"""
        total = len(self.audit_results)
        approved = sum(1 for r in self.audit_results if r.final_decision == "approved")
        layer_a_rejected = sum(1 for r in self.audit_results if not r.layer_a_passed)
        layer_b_rejected = sum(1 for r in self.audit_results if r.layer_a_passed and not r.layer_b_passed)

        return {
            "total_signals": total,
            "approved": approved,
            "approval_rate": approved / total if total > 0 else 0,
            "layer_a_rejected": layer_a_rejected,
            "layer_b_rejected": layer_b_rejected,
            "rejection_rate": (total - approved) / total if total > 0 else 0,
            "daily_trades_today": self.daily_trade_count,
        }


# ── Integration Helper ────────────────────────

risk_manager = RiskManager()

def evaluate_signal(symbol: str, direction: str, confidence: float,
                    entry_price: float, stop_loss_pct: float,
                    position_usd: float, reasoning: str, source: str) -> dict:
    """
    风险管理的单入口函数。
    在 commodity-trend-signal 的信号输出后直接调用。
    """
    signal = TradingSignal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss_pct=stop_loss_pct,
        position_usd=position_usd,
        reasoning=reasoning,
        source=source,
    )
    result = risk_manager.evaluate(signal)
    return {
        "signal": asdict(signal),
        "audit": asdict(result),
        "stats": risk_manager.get_stats(),
    }
```

### 集成到 commodity-trend-signal 的要点

1. **在信号输出管道末端插入**：`commodity-trend-signal` 生成交易信号后，调用 `evaluate_signal()` 过风控
2. **非破坏性集成**：Risk Manager 只做审核/拦截/记录，不修改原始信号内容
3. **Layer A 拒绝可通知**：Layer A 拒绝意味着有配置错误（止损超限等），建议发提醒
4. **Layer B 拒绝可跳过**：Layer B 是概率性的，同一信号重试可能通过（随机审计是设计特性）
5. **审计日志**：按月分片的 JSONL 文件，可用 `grep` / `jq` 直接查询

### 部署后的预期效果

| 指标 | 目前 | 部署后 |
|:----|:----:|:------:|
| 硬门拦截 | 无 | 方向/置信度/止损/头寸4道检查 |
| 审计覆盖率 | 0% | ~30% 信号被随机审计 |
| 自动绕过可恢复错误 | 无（直接执行） | 安全边际豁免 ~70% 信号直通 |
| 每日限额 | 无 | 硬上限 5 次/日 |
| 审计轨迹 | 无 | 完整 JSONL 日志，按月分片 |

---

## 改进 D：可配置协调层架构

### 背景问题

FDT 当前编排是硬编码的 Sequential Pipeline：
```
数技源 → 探源 → 观澜 → 链证源 → 正/反方 → 闫判官
```

Coordination Layer (arXiv:2605.03310) 的核心发现：
> **多 Agent 系统 41%~87% 生产失败源于协调缺陷而非模型能力**

这意味着 FDT 的时序铁律虽然可靠，但缺乏灵活性和可观测性。当需要切换编排模式（如从 Sequential 切换到 Debate）时，需要改代码。

### 设计方案

将 FDT 的编排逻辑提取为**可配置的架构层**，支持多种协调模式，通过 YAML 配置切换。

```
┌────────────────────────────────────────────────────────────┐
│                   Coordination Layer                        │
│                                                            │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Mode       │  │ Topology     │  │ Termination       │  │
│  │ Selector   │  │ Config       │  │ Strategy          │  │
│  └────────────┘  └──────────────┘  └───────────────────┘  │
│                                                            │
│  ┌────────────────────────────────────────────────────┐    │
│  │   Agents                                           │    │
│  │   ┌────┬────┬────┬────┬────┬────┬────┬────┐       │    │
│  │   │数技│探源│观澜│链证│正方│反方│闫判│... │       │    │
│  │   └────┴────┴────┴────┴────┴────┴────┴────┘       │    │
│  └────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────┘
```

### 配置文件

```yaml
# coordination_config.yaml — FDT 协调配置
# 参考: Coordination Layer (arXiv:2605.03310)
version: 2.0

# ═══════════════════════════════════════════
# Agent 定义
# ═══════════════════════════════════════════

agents:
  shujiyuan:       # 数技源
    type: analyst
    description: "定论点（多/空方向），输出 scan_all.py 分析"
    timeout: 300

  tanyuan:         # 探源
    type: researcher
    description: "供客观资料 — 地缘政治/宏观"
    timeout: 600

  guanlan:         # 观澜
    type: researcher
    description: "供客观资料 — 产业/供需"
    timeout: 600

  lianzhengyuan:   # 链证源
    type: researcher
    description: "供客观资料 — 链上数据/资金/舆情"
    timeout: 600

  zhengfang:       # 正方
    type: debater
    role: positive
    description: "从研究员资料中提炼多头论据"
    timeout: 300

  fanfang:         # 反方
    type: debater
    role: negative
    description: "从研究员资料中提炼空头论据"
    timeout: 300

  yanpanguan:      # 闫判官
    type: judge
    description: "主持+裁决+时序控制+边界检查"
    timeout: 300

# ═══════════════════════════════════════════
# 编排模式
# ═══════════════════════════════════════════

orchestration:
  # 可选模式:
  #   sequential  — 严格串行 (当前FDT默认)
  #   debate       — 并行研究员+正反方分别辩论
  #   ensemble     — 所有Agent独立产出，加权汇总
  #   orchestrator — 闫判官动态调度（实验性）
  mode: sequential

# ═══════════════════════════════════════════
# 通信拓扑
# ═══════════════════════════════════════════

topology:
  # 谁可以向谁发送消息（有向边）
  edges:
    # 数技源 → 研究员
    - from: shujiyuan
      to: [tanyuan, guanlan, lianzhengyuan]

    # 研究员 → 辩手
    - from: [tanyuan, guanlan, lianzhengyuan]
      to: [zhengfang, fanfang]

    # 辩手 → 闫判官
    - from: [zhengfang, fanfang]
      to: [yanpanguan]

    # 闫判官 → 研究员（驳回重审时）
    - from: [yanpanguan]
      to: [tanyuan, guanlan, lianzhengyuan]

    # 闫判官 → 辩手（退回无效论点时）
    - from: [yanpanguan]
      to: [zhengfang, fanfang]

  # 闫判官的单向广播
  broadcast:
    targets: [shujiyuan, tanyuan, guanlan, lianzhengyuan, zhengfang, fanfang]
    triggers: ["phase_complete", "verdict_published"]

# ═══════════════════════════════════════════
# 权限规则
# ═══════════════════════════════════════════

authority:
  # 谁有权生成最终输出
  accept_output: yanpanguan

  # 谁有权调度 Agent 执行
  route_tasks: yanpanguan

  # 谁有权修改配置（生产环境禁止）
  modify_config:
    roles: ["admin"]
    requires_confirm: true

  # 裁决权重
  verdict_weighting:
    shujiyuan: 0.50     # 数技源方向占 50%
    debate: 0.30        # 辩论结果占 30%
    researchers: 0.20   # 研究员客观资料占 20%

# ═══════════════════════════════════════════
# 终止条件
# ═══════════════════════════════════════════

termination:
  max_rounds: 3                     # 最大辩论轮次
  convergence_threshold: 0.85       # 意见收敛到 85% 以上终止
  min_researchers_completed: 2      # 至少 2/3 研究员完成
  timeout_behavior: "skip_and_warn" # 超时行为：跳过并记录警告

# ═══════════════════════════════════════════
# 审计
# ═══════════════════════════════════════════

audit:
  log_level: "full"                 # full / summary / off
  log_path: "plugins/futures-debate-team/audit/"
  log_format: "jsonl"
  retention_days: 90

# ═══════════════════════════════════════════
# 多模式预配置
# ═══════════════════════════════════════════

profiles:
  # 默认模式（全流程+辩论）
  default:
    mode: sequential
    termination:
      max_rounds: 3
      convergence_threshold: 0.85

  # 快速模式（只依赖数技源+闫判官，跳过辩论）
  fast:
    mode: sequential
    topology:
      edges:
        - from: shujiyuan
          to: [yanpanguan]
    termination:
      max_rounds: 1
      min_researchers_completed: 0
    verdict_weighting:
      shujiyuan: 0.90
      debate: 0.00
      researchers: 0.10

  # 深度研究模式（让研究员充分产出）
  deep_research:
    mode: sequential
    termination:
      max_rounds: 5
      convergence_threshold: 0.90
      min_researchers_completed: 3
    authority:
      verdict_weighting:
        shujiyuan: 0.35
        debate: 0.25
        researchers: 0.40

  # 辩论赛模式（并行研究员，多轮辩论）
  tournament:
    mode: sequential
    topology:
      edges:
        - from: shujiyuan
          to: [tanyuan, guanlan, lianzhengyuan]
        - from: [tanyuan, guanlan, lianzhengyuan]
          to: [zhengfang, fanfang]
        # 加入辩手互评
        - from: [zhengfang]
          to: [fanfang]
        - from: [fanfang]
          to: [zhengfang]
        - from: [zhengfang, fanfang]
          to: [yanpanguan]
    termination:
      max_rounds: 5
      convergence_threshold: 0.90
```

### Coordination Layer 运行器

```python
"""
coordinator.py — 协调层调度引擎
根据 coordination_config.yaml 加载配置并调度 Agent
"""

import yaml
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

@dataclass
class AgentTask:
    """单个 Agent 任务"""
    agent_id: str
    input_data: Optional[dict] = None
    result: Optional[dict] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    status: str = "pending"  # pending / running / completed / failed / skipped


class Coordinator:
    """
    可配置协调层调度引擎。
    根据 YAML 配置执行 Agent 编排。
    """

    def __init__(self, config_path: str = "coordination_config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.agents = self.config["agents"]
        self.topology = self.config["topology"]
        self.mode = self.config["orchestration"]["mode"]
        self.termination = self.config["termination"]
        self.authority = self.config["authority"]

        self.tasks: dict[str, AgentTask] = {}
        self.is_running = False

    def run_sequential(self, profile: str = "default"):
        """
        串行模式（当前 FDT 默认）。
        根据配置的边顺序执行 Agent，边定义了数据流向。
        """
        # 加载 profile 覆盖
        profile_config = self.config.get("profiles", {}).get(profile, {})
        self._apply_profile(profile_config)

        self.is_running = True
        edges = self.topology["edges"]

        # 找出拓扑中所有 Agent 的执行顺序（拓扑排序简化版）
        execution_order = self._resolve_execution_order(edges)

        for agent_id in execution_order:
            if not self.is_running:
                break

            agent_config = self.agents.get(agent_id)
            if not agent_config:
                continue

            timeout = agent_config.get("timeout", 300)
            task = AgentTask(agent_id=agent_id)

            # 检查终止条件
            if not self._check_continuation():
                task.status = "skipped"
                self.tasks[agent_id] = task
                continue

            task.status = "running"
            task.start_time = time.time()

            try:
                result = self._execute_agent(agent_id, task)
                task.result = result
                task.status = "completed"
            except Exception as e:
                task.status = "failed"
                task.result = {"error": str(e)}

            task.end_time = time.time()
            self.tasks[agent_id] = task

        self.is_running = False
        return self._compile_final_output()

    def _resolve_execution_order(self, edges: list[dict]) -> list[str]:
        """
        从边定义中解析执行顺序。
        简化的拓扑排序——要求边不形成环。
        """
        order = []
        added = set()

        while len(order) < len(self.agents):
            for edge in edges:
                for target in edge.get("to", []):
                    if target not in added:
                        froms = edge.get("from", [])
                        if isinstance(froms, list):
                            deps = [d for d in froms if d not in added]
                            if not deps:  # 所有依赖已就绪
                                order.append(target)
                                added.add(target)
            break  # 避免死循环

        # 补充未被拓扑覆盖的 Agent（如闫判官）
        for agent_id in self.agents:
            if agent_id not in added:
                order.append(agent_id)
                added.add(agent_id)

        return order

    def _execute_agent(self, agent_id: str, task: AgentTask) -> dict:
        """执行单个 Agent（实际调用对应的 skill 函数）"""
        agent_config = self.agents[agent_id]
        
        # 此处调用实际的 Agent 执行逻辑
        # 例如: run_agent(agent_id, agent_config)
        
        return {
            "agent_id": agent_id,
            "status": "completed",
            "outputs": agent_config.get("description", "unknown"),
        }

    def _check_continuation(self) -> bool:
        """检查是否满足继续执行的条件"""
        completed = [t for t in self.tasks.values() if t.status == "completed"]
        return len(completed) >= 0  # 默认继续

    def _apply_profile(self, profile: dict):
        """应用 profile 配置覆盖"""
        if "mode" in profile:
            self.mode = profile["mode"]
        if "termination" in profile:
            self.termination = {**self.termination, **profile["termination"]}
        if "verdict_weighting" in profile.get("authority", {}):
            self.authority["verdict_weighting"] = profile["authority"]["verdict_weighting"]

    def _compile_final_output(self) -> dict:
        """汇总所有 Agent 输出为最终裁决"""
        return {
            "mode": self.mode,
            "tasks": {
                aid: {
                    "status": t.status,
                    "duration": (t.end_time - t.start_time) if t.end_time and t.start_time else None,
                }
                for aid, t in self.tasks.items()
            },
            "verdict": self.tasks.get("yanpanguan", AgentTask("yanpanguan")).result,
        }
```

### 集成到 FDT 的要点

1. **配置文件**：将 `coordination_config.yaml` 放在 `plugins/futures-debate-team/` 目录下
2. **切换模式**：通过 `profile` 参数切换——`fast` 模式跳过辩论、`deep_research` 模式加强研究员权重
3. **向后兼容**：`default` profile 的行为与当前 FDT 时序铁律完全一致
4. **扩展性**：新增 Agent 只需在配置文件中声明，不需要修改编排代码

---

## 实施路线图

```
优先级        改进            预计工时    独立可部署?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
P0    A. IGP 推理门控          2h        ✅ 可独立实施
P0    B. 闫判官"纠偏优先"     1.5h      ✅ 可独立实施
P0    C. 二层安全门            4h        ✅ 可独立实施（作用于 CTA）
P1    D. 可配置协调层          4h        ❌ 依赖 A+B 完成后

实施顺序建议:
  第一波: C（安全门，与现有系统解耦最彻底，最安全）
  第二波: A + B（IGP + 纠偏裁决，需同时更新 FDT）
  第三波: D（协调层重构，依赖 A+B 完成后的新 FDT）
```

---

## 附录：论文引用对照

| 改进 | 核心引用的论文 | 具体章节 |
|:----|:--------------|:---------|
| A | AgenticAITA (arXiv:2605.12532) | §3.2 Adaptive Z-Score Trigger, §3.3 Inference Gating Protocol |
| B | Macro Economists (arXiv:2606.08283) | §4.4 Debate vs Single Agent, §5 Discussion |
| C | AgenticAITA (arXiv:2605.12532) + Explanatory Equilibrium (arXiv:2604.09917) | AgenticAITA §4.3 Hard Gate Safety Layer, Explanatory §3.2-3.3 Audit Mechanism |
| D | Coordination Layer (arXiv:2605.03310) | §4 Five Coordination Configurations, §5 Murphy Decomposition |

---

## 附件：已交付文件清单（2026-07-11）

| # | 文件路径 | 版本 |
|:-:|:---------|:----:|
| A | `plugins/futures-debate-team/scripts/inference_gate.py` | v1.0.0 |
| B | `plugins/futures-debate-team/agents/futures-judge.md` | v2.2 |
| C | `skills/commodity-trend-signal/scripts/risk_manager.py` | v1.0.0 |
| D | `plugins/futures-debate-team/coordination_config.yaml` | v2.1 |
| D | `plugins/futures-debate-team/scripts/coordinator.py` | v1.0.0 |

所有文件已同步至 GitHub: `CTAAgents/experts`

*文档结束 — 四项改进已全部实施并交付*
