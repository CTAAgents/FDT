"""
置信度校验共享模块 — 统一 validate_agent_output / quality_inspector / llm_validation 中的置信度逻辑。

去重目标:
  validate_agent_output.py 有 inline 兜底（CONFIDENCE_LABEL_MAP + normalize_confidence）
  quality_inspector.py 有独立的置信度范围检查
  validate_llm_output.py 有置信度范围检查

本模块提供上述三种场景的统一实现。
"""
from __future__ import annotations

from typing import Any

# 中文标签 → 数值映射
CONFIDENCE_LABEL_MAP: dict[str, float] = {
    "高": 0.8, "中": 0.6, "低": 0.4,
    "HIGH": 0.8, "MEDIUM": 0.6, "LOW": 0.4,
    "high": 0.8, "medium": 0.6, "low": 0.4,
}

# 受控中文标签（用于 is_valid_label 检查）
VALID_LABELS = {"高", "中", "低"}


def normalize_confidence(conf: Any) -> float:
    """将置信度归一化为 float [0, 1]。

    支持:
      - 数值: int/float 直接返回
      - 字符串数字: "0.75" → 0.75
      - 中文标签: "高"/"中"/"低"
      - 英文标签: "HIGH"/"MEDIUM"/"LOW"

    Returns:
        float in [0, 1]，无法解析时返回 0.5
    """
    if isinstance(conf, (int, float)):
        return float(conf)
    if isinstance(conf, str):
        s = conf.strip()
        try:
            return float(s)
        except ValueError:
            pass
        return CONFIDENCE_LABEL_MAP.get(s, 0.5)
    return 0.5


def is_valid_confidence(conf: Any) -> bool:
    """检查置信度值是否合法。

    Returns:
        True 表示合法
    """
    if isinstance(conf, (int, float)):
        return True
    if isinstance(conf, str):
        s = conf.strip()
        if s in CONFIDENCE_LABEL_MAP:
            return True
        try:
            float(s)
            return True
        except ValueError:
            return False
    return False


def validate_confidence_range(conf: float, min_val: float = 0.0, max_val: float = 1.0) -> str | None:
    """校验置信度是否在范围内。

    Args:
        conf: 归一化后的置信度
        min_val: 最小值
        max_val: 最大值

    Returns:
        None 表示通过，str 为错误描述
    """
    if conf < min_val or conf > max_val:
        return f"置信度 {conf} 超出 [{min_val}, {max_val}]"
    return None


def validate_confidence_type(conf: Any) -> tuple[bool, str | None]:
    """综合校验置信度类型 + 范围。

    Returns:
        (is_valid, error_msg)
    """
    if not is_valid_confidence(conf):
        return False, f"无效置信度值: {conf}"
    normalized = normalize_confidence(conf)
    err = validate_confidence_range(normalized)
    if err:
        return False, err
    return True, None
