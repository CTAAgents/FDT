"""验证器公共基类 — 运行上下文 + 降级辅助契约。

所有信号验证器共享同一个 ValidationContext（由 scan_all 构建并传入），
并通过 demote() 统一降级为噪声（伪信号）。无黑盒因子，因子全部来自公开主流定义。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationContext:
    """验证器运行上下文。

    kline_data:  sym -> (meta, dlist) 原始K线，与 scan_all 内部格式一致
    higher_tf:   sym -> "bull"/"bear"/"neutral" 高周期方向（未计算时为空，V4 自动跳过）
    extra:       杂项扩展位（未来可放训练数据/制度等）
    """

    kline_data: dict = field(default_factory=dict)
    higher_tf: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def demote(r: dict, reason: str, new_type: str = "false_breakout") -> None:
    """将一条信号降级为噪声（伪信号）。统一降级契约。

    Args:
        r:         信号记录（会被原地修改）
        reason:    降级原因（写入 _validator_reason 供下游追溯）
        new_type:  降级后的 signal_type；伪突破过滤器用默认 "false_breakout"，
                   稳定性/拥挤度等不重定义的验证器传原 signal_type 仅压 grade。
    """
    r["_raw_grade"] = r.get("grade", "NOISE")  # 保留原始等级（供多因子增强撤销降级用）
    r["_raw_total"] = r.get("total", 0)        # 保留原始总分
    r["signal_type"] = new_type
    r["grade"] = "NOISE"
    r["total"] = 0
    r["_validator_demoted"] = True
    r["_validator_reason"] = reason


def undemote(r: dict, reason: str) -> None:
    """撤销降级：恢复 grade 和 total（供多因子增强验证器使用）。

    仅在 r["_raw_grade"] 和 r["_raw_total"] 存在时生效。
    """
    if "_raw_grade" not in r or "_raw_total" not in r:
        return
    r["grade"] = r["_raw_grade"]
    r["total"] = r["_raw_total"]
    r["_validator_demoted"] = False
    r["_validator_reason"] = f"增强覆写: {reason}"
