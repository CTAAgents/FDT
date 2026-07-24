#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confidence_utils.py — 置信度归一化单一来源（#5修复·2026-07-11）

问题背景：
  FDT 系统契约（contracts/）规定 confidence 为数值型 0-1。
  但历史上部分 Agent 产出 "高/中/低" 字符串，导致下游消费点类型不一致，
  质量门控/仓位计算偶发 TypeError 或语义漂移。

本模块提供唯一归一化入口，所有消费点（validate_agent_output.py、
extract_knowledge.py、memory_writer.py 等）必须从这里 import，禁止各自实现。

映射表：
  高 -> 0.8
  中 -> 0.6
  低 -> 0.4
  数值 -> float(原值)
"""

import math
from typing import Any, Union

# 中文标签 -> 数值映射（系统唯一标准）
CONFIDENCE_LABEL_MAP = {"低": 0.4, "中": 0.6, "高": 0.8, "LOW": 0.4, "MEDIUM": 0.6, "HIGH": 0.8}
DEFAULT_CONFIDENCE = 0.5

# 数值阈值 -> 标签（用于仓位映射/展示）
HIGH_THRESHOLD = 0.7
MID_THRESHOLD = 0.4

# 量程硬边界（系统契约：confidence 必须为 0-1 有限值）
CONF_MIN = 0.0
CONF_MAX = 1.0


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _is_finite_in_range(v: float) -> bool:
    """v 必须是有限值且落在 [0,1] 量程内（P0-3 污染防御）"""
    return math.isfinite(v) and CONF_MIN <= v <= CONF_MAX


def normalize_confidence(conf: Union[str, int, float, None]) -> float:
    """
    将字符串/数值型置信度归一为 0-1 浮点。

    🔴 P0-3 修复（2026-07-11 修复·压力测试暴露）：
      非有限值(inf/nan)与超量程值(>1 或 <0)一律清洗为 DEFAULT_CONFIDENCE，
      且绝不返回非有限/越界值。门控拦截由 is_valid_confidence() 负责，
      归一化仅在"已被门控放行"后提供数值；若门控未放行而被调用，
      返回安全兜底值避免下游 TypeError。

    无法解析时返回 DEFAULT_CONFIDENCE(0.5)，保证调用方永不抛 TypeError。
    """
    if conf is None:
        return DEFAULT_CONFIDENCE
    if isinstance(conf, (int, float)):
        if not _is_finite_in_range(float(conf)):
            # 非有限/越界 → 清洗为兜底值（门控侧会拦截为无效）
            return DEFAULT_CONFIDENCE
        return float(conf)
    if isinstance(conf, str):
        s = conf.strip()
        # 直接是数字字符串（如 "0.6"）
        if _is_numeric(s):
            v = float(s)
            if not _is_finite_in_range(v):
                return DEFAULT_CONFIDENCE
            return v
        # 精确匹配中文标签
        if s in CONFIDENCE_LABEL_MAP:
            return CONFIDENCE_LABEL_MAP[s]
        # 兼容 "高置信" / "中等" 等包含标签的词
        for k, v in CONFIDENCE_LABEL_MAP.items():
            if k in s:
                return v
    return DEFAULT_CONFIDENCE


def confidence_label(conf: Union[str, int, float, None]) -> str:
    """将置信度转为 高/中/低 标签，供人类可读展示/仓位映射。"""
    v = normalize_confidence(conf)
    if not math.isfinite(v):
        return "低"
    if v >= HIGH_THRESHOLD:
        return "高"
    if v >= MID_THRESHOLD:
        return "中"
    return "低"


def confidence_label(conf: Union[str, int, float, None]) -> str:
    """将置信度转为 高/中/低 标签，供人类可读展示/仓位映射。"""
    v = normalize_confidence(conf)
    if v >= HIGH_THRESHOLD:
        return "高"
    if v >= MID_THRESHOLD:
        return "中"
    return "低"


def is_valid_confidence(conf: Any) -> bool:
    """
    校验 confidence 是否为系统接受的类型（0-1 有限值 或 受控中文标签）。
    用于 L1 门禁拒绝任意裸字符串/非有限值/越界值（防类型漂移+污染泄漏）。

    🔴 P0-3 修复（2026-07-11 压力测试暴露）：
      此前 inf/nan/超量程(>1 或 <0) 均返回 True，污染可直穿门控。
      现严格断言 math.isfinite + [0,1] 量程。
    """
    if isinstance(conf, (int, float)):
        return _is_finite_in_range(float(conf))
    if isinstance(conf, str):
        s = conf.strip()
        if s in CONFIDENCE_LABEL_MAP:
            return True
        if _is_numeric(s):
            v = float(s)
            return _is_finite_in_range(v)
    return False
