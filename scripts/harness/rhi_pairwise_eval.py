"""
RHI Pairwise Evaluator — 两轮辩论产出的四维对比评估。

对应 RHI Algorithm 1 中的 Leval 函数：
  Leval(outputⁱ, outputⁱ⁻¹; x_eval) → preference

评估维度 (G21 §3.4):
  - 质检通过率 (0.35): quality_report error/warning 数
  - 风控通过率 (0.25): risk_level distribution
  - 信号质量   (0.25): signal count + confidence mean
  - 报告完整性 (0.15): missing sections, placeholders

参考:
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from contracts.rhi_harness_spec import PairwisePreference

logger = logging.getLogger(__name__)

# ── 四维评估权重 (G21 §3.4) ──
EVAL_WEIGHTS = {
    "quality_pass": 0.35,
    "risk_pass": 0.25,
    "signal_quality": 0.25,
    "report_integrity": 0.15,
}


def _load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[RHI] 无法加载 {path}: {e}")
        return {}


def _score_quality_pass(state: dict) -> float:
    """质检通过率评分。从 state.quality_report 中提取。"""
    qr = state.get("quality_report", {})
    if not qr:
        return 0.0
    issues = qr.get("issues", [])
    if not issues:
        return 1.0
    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    # error-free → 1.0; 每多 1 个 error -0.2; warning -0.05
    score = 1.0 - errors * 0.2 - warnings * 0.05
    return max(0.0, score)


def _score_risk_pass(state: dict) -> float:
    """风控通过率评分。从 state.risk_check 中提取。"""
    risk = state.get("risk_check", {})
    if not risk:
        return 0.0
    level = risk.get("risk_level", "red")
    mapping = {"green": 1.0, "yellow": 0.5, "red": 0.0}
    return mapping.get(level, 0.0)


def _score_signal_quality(state: dict) -> float:
    """信号质量评分。从 state.signal_report 中提取。"""
    signals = state.get("signal_report", {}).get("signals", [])
    if not signals:
        # 也可能是 state.ctp_signals
        ctp = state.get("ctp_signals", {})
        signals = ctp.get("signals", []) if isinstance(ctp, dict) else []
    if not signals:
        return 0.0
    confidences = [s.get("confidence", 0) for s in signals if isinstance(s.get("confidence"), (int, float))]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0
    # score = min(signal_count / 3, 1.0) * 0.5 + mean_conf * 0.5
    count_score = min(len(signals) / 3.0, 1.0) * 0.5
    conf_score = mean_conf * 0.5
    return min(count_score + conf_score, 1.0)


def _score_report_integrity(state: dict) -> float:
    """报告完整性评分。检查必需区块是否存在。"""
    required = ["symbols", "final_verdicts", "debate_results"]
    present = sum(1 for s in required if state.get(s))
    # 检查占位文本
    data_str = str(state)
    placeholders = ["（未触发）", "待补充", "TBD", "暂无数据"]
    has_placeholder = any(m in data_str for m in placeholders)
    base = present / len(required)
    if has_placeholder:
        base *= 0.8
    return base


def _extract_state_from_output(output_path: str | Path) -> dict:
    """从辩论产出路径中提取 state 字典。

    支持两种格式:
      1. debate_output_{trace_id}.json — 完整 state dump
      2. debate_report_{trace_id}.html — HTML 报告（尝试解析）
    """
    p = Path(output_path)
    if not p.exists():
        logger.warning(f"[RHI] 产出文件不存在: {output_path}")
        return {}

    if p.suffix == ".json":
        return _load_json(p)

    if p.suffix == ".html":
        # 从 HTML 中提取 embedded JSON（如果报告中有 data-state 属性）
        try:
            text = p.read_text(encoding="utf-8")
            import re
            m = re.search(r'data-state=\'({.+?})\'', text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
        except Exception:
            pass
        return {}

    return {}


def evaluate_pairwise(
    output_path_current: str | Path,
    output_path_previous: str | Path,
    iteration: int = 0,
) -> PairwisePreference:
    """执行 pairwise 比较（Leval），返回结构化偏好结果。

    Args:
        output_path_current: 本轮 (Hⁱ) 的产出路径
        output_path_previous: 上轮 (Hⁱ⁻¹) 的产出路径
        iteration: 当前迭代轮次

    Returns:
        PairwisePreference
    """
    state_cur = _extract_state_from_output(output_path_current)
    state_prev = _extract_state_from_output(output_path_previous)

    # 四维评分
    dims = {
        "quality_pass": EVAL_WEIGHTS["quality_pass"],
        "risk_pass": EVAL_WEIGHTS["risk_pass"],
        "signal_quality": EVAL_WEIGHTS["signal_quality"],
        "report_integrity": EVAL_WEIGHTS["report_integrity"],
    }
    scores_cur = {k: _score_quality_pass(state_cur) if k == "quality_pass"
                       else _score_risk_pass(state_cur) if k == "risk_pass"
                       else _score_signal_quality(state_cur) if k == "signal_quality"
                       else _score_report_integrity(state_cur)
                  for k in dims}
    scores_prev = {k: _score_quality_pass(state_prev) if k == "quality_pass"
                       else _score_risk_pass(state_prev) if k == "risk_pass"
                       else _score_signal_quality(state_prev) if k == "signal_quality"
                       else _score_report_integrity(state_prev)
                   for k in dims}

    total_cur = sum(scores_cur[k] * w for k, w in dims.items())
    total_prev = sum(scores_prev[k] * w for k, w in dims.items())

    # 确定偏好
    delta = total_cur - total_prev
    if delta > 0.02:
        preference = "improve"
    elif delta < -0.02:
        preference = "regress"
    else:
        preference = "tie"

    # 生成 key_diffs
    key_diffs = []
    for k in dims:
        d = scores_cur[k] - scores_prev[k]
        if abs(d) >= 0.05:
            direction = "+" if d > 0 else ""
            key_diffs.append(f"{k}: {direction}{d:.3f}")

    rationale = (
        f"综合评分: cur={total_cur:.3f}, prev={total_prev:.3f}, delta={delta:+.3f}. "
        f"偏好={preference}. 维度差异: {'; '.join(key_diffs) if key_diffs else '无显著差异'}"
    )

    return {
        "iteration": iteration,
        "preference": preference,
        "score_current": round(total_cur, 4),
        "score_previous": round(total_prev, 4),
        "score_breakdown": {
            "current": {k: round(v, 4) for k, v in scores_cur.items()},
            "previous": {k: round(v, 4) for k, v in scores_prev.items()},
        },
        "rationale": rationale,
        "key_diffs": key_diffs,
    }


def compute_improvement_rate(preferences: list[PairwisePreference]) -> float:
    """计算改进率 sⁱ = (改进次数 / 总比较次数)。

    对应 RHI Algorithm 1:
      sⁱ = (¹/n) Σ 1[outputᵏ ≻ outputᵏ⁻¹]
    """
    if not preferences:
        return 0.0
    improves = sum(1 for p in preferences if p.get("preference") == "improve")
    return improves / len(preferences)
