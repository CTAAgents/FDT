"""
inference_gate.py — IGP 推理门控模块 v1.0.0
======================================

适用范围: FDT 辩论专家团（futures-debate-team）
设计来源: AgenticAITA (arXiv:2605.12532) §3.2-3.3

功能:
  1. 互斥锁（Mutex Lock）— 同一时间只允许一个 Agent 占用推理通道
  2. 冷却期（Cooldown）— Agent 释放锁后有 1800s 冷却窗
  3. 审计三表（Audit Trail）— audit_log / pipeline_log / cost_log
  4. 装饰器（@with_gate）— 一行接入现有 Agent 函数

用法:
  from scripts.inference_gate import gate, InferenceProposal, with_gate

  # 在闫判官初始化时
  gate = InferenceGate()

  # 装饰 Agent 函数
  @with_gate(gate)
  def run_datatech(agent_name, intent, resources, estimated_tokens):
      ...

  # 或手动使用
  proposal = InferenceProposal(agent_name="数技源", intent="定论点", ...)
  if gate.acquire(proposal):
      try:
          result = do_work()
      finally:
          gate.release(InferenceResult(...))

  # 会话结束时
  gate.save_audit()
"""

import time
import json
import threading
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

# ── 配置 ──────────────────────────────────────

COOLDOWN_SECONDS = 1800       # 全局冷却期（30分钟）
SESSION_LOCK_TIMEOUT = 600    # 会话锁超时（10分钟）
AUDIT_DIR = Path(__file__).resolve().parent.parent / "audit"


# ── 数据结构 ──────────────────────────────────

@dataclass
class InferenceProposal:
    agent_name: str
    intent: str
    required_resources: Optional[list] = None
    estimated_cost_tokens: int = 0
    priority: int = 5

    def __post_init__(self):
        if self.required_resources is None:
            self.required_resources = []


@dataclass
class InferenceResult:
    agent_name: str
    success: bool
    duration_seconds: float
    output_path: str = ""
    error: Optional[str] = None
    token_used: int = 0


@dataclass
class AuditRecord:
    timestamp: str
    agent: str
    action: str
    proposal: Optional[dict] = None
    result: Optional[dict] = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ── 门控实现 ──────────────────────────────────

class InferenceGate:
    """
    全局推理门控。
    互斥锁 + 冷却期 + 审计三表。
    """

    def __init__(self, cooldown: int = COOLDOWN_SECONDS,
                 timeout: int = SESSION_LOCK_TIMEOUT):
        self._lock = threading.Lock()
        self._pipeline_busy = False
        self._pipeline_owner: Optional[str] = None
        self._last_release_time: float = 0.0
        self._cooldown = cooldown
        self._timeout = timeout
        self._session_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 审计三表
        self.audit_log: list[AuditRecord] = []
        self.pipeline_log: list[dict] = []
        self.cost_log: list[dict] = []

        AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 互斥锁 ──

    def acquire(self, proposal: InferenceProposal) -> bool:
        now = time.time()

        # 冷却期检查 — 独立于 pipeline_busy 状态
        # 上次释放后未满冷却期则拒绝新的获取请求
        if self._last_release_time > 0:
            elapsed = now - self._last_release_time
            remaining = self._cooldown - elapsed
            if remaining > 0:
                self._record(AuditRecord(
                    timestamp=datetime.now().isoformat(),
                    agent=proposal.agent_name,
                    action="cooldown",
                    proposal=asdict(proposal),
                    metadata={"cooldown_remaining": round(remaining, 1)}
                ))
                return False

        with self._lock:
            if self._pipeline_busy:
                self._record(AuditRecord(
                    timestamp=datetime.now().isoformat(),
                    agent=proposal.agent_name,
                    action="pipeline_busy",
                    proposal=asdict(proposal)
                ))
                return False

            self._pipeline_busy = True
            self._pipeline_owner = proposal.agent_name

            self.pipeline_log.append({
                "event": "acquire",
                "agent": proposal.agent_name,
                "intent": proposal.intent,
                "timestamp": datetime.now().isoformat(),
            })

            self._record(AuditRecord(
                timestamp=datetime.now().isoformat(),
                agent=proposal.agent_name,
                action="lock_acquired",
                proposal=asdict(proposal)
            ))
            return True

    def release(self, result: InferenceResult):
        with self._lock:
            self._pipeline_busy = False
            self._pipeline_owner = None
            self._last_release_time = time.time()

            self.pipeline_log.append({
                "event": "release",
                "agent": result.agent_name,
                "success": result.success,
                "duration": round(result.duration_seconds, 2),
                "timestamp": datetime.now().isoformat(),
            })

            action = "completed" if result.success else "failed"
            self._record(AuditRecord(
                timestamp=datetime.now().isoformat(),
                agent=result.agent_name,
                action=action,
                result=asdict(result),
            ))

            self.cost_log.append({
                "session_id": self._session_id,
                "agent": result.agent_name,
                "tokens": result.token_used,
                "duration": round(result.duration_seconds, 2),
                "success": result.success,
                "timestamp": datetime.now().isoformat(),
            })

    # ── 审计 ──

    def _record(self, record: AuditRecord):
        self.audit_log.append(record)

    def save_audit(self) -> str:
        session_dir = AUDIT_DIR / f"session_{self._session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        with open(session_dir / "audit_log.json", "w") as f:
            json.dump([asdict(r) for r in self.audit_log], f,
                      ensure_ascii=False, indent=2)

        with open(session_dir / "pipeline_log.json", "w") as f:
            json.dump(self.pipeline_log, f, ensure_ascii=False, indent=2)

        with open(session_dir / "cost_log.json", "w") as f:
            json.dump(self.cost_log, f, ensure_ascii=False, indent=2)

        return str(session_dir)


# ── 装饰器：集成到 Agent 调用中 ──────────────

def with_gate(gate: InferenceGate):
    def decorator(func: Callable):
        def wrapper(agent_name: str, *args, **kwargs):
            proposal = InferenceProposal(
                agent_name=agent_name,
                intent=kwargs.pop("intent", "unspecified"),
                required_resources=kwargs.pop("resources", []),
                estimated_cost_tokens=kwargs.pop("estimated_tokens", 0),
            )
            if not gate.acquire(proposal):
                return {"status": "blocked",
                        "reason": "pipeline_busy_or_cooldown"}

            start = time.time()
            try:
                output = func(agent_name, *args, **kwargs)
                duration = time.time() - start
                out_path = str(output) if isinstance(output, Path) else "inline"
                result = InferenceResult(
                    agent_name=agent_name,
                    success=True,
                    duration_seconds=duration,
                    output_path=out_path,
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
                    token_used=proposal.estimated_cost_tokens,
                )
                raise
            finally:
                gate.release(result)
        return wrapper
    return decorator


# ── 便利 API ─────────────────────────────────

def create_gate(cooldown: int = COOLDOWN_SECONDS) -> InferenceGate:
    """创建并返回 IGP 门控实例"""
    return InferenceGate(cooldown=cooldown)
