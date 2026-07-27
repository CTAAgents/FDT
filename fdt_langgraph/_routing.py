"""辩论图路由/辅助函数 — 从 graph.py 提取，打破循环导入。

graph.py 和 per_symbol_graph.py 都依赖这些函数，
独立到此文件后两个模块均可安全导入而不产生循环引用。
"""

from __future__ import annotations

import logging
from typing import Any

from fdt_langgraph.state import DebateState

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════


def _get_current_symbol(state: DebateState) -> str:
    """获取当前处理的品种代码。

    使用 _original_symbols 而非 selected_symbols，因为 prepare_one_symbol
    会将 selected_symbols 覆盖为单元素列表，导致第2品种起 current_sym 为空。
    """
    symbols = state.get("_original_symbols", state.get("selected_symbols", []))
    idx = state.get("symbol_index", -1)
    if 0 <= idx < len(symbols):
        return symbols[idx]
    logger.warning("G19 修复: _get_current_symbol 无法定位品种(idx=%d, symbols=%s)", idx, symbols)
    return ""


def _get_p3_node_names(mode: str) -> list[str]:
    """根据 mode 返回需要激活的四源节点列表"""
    p3: list[str] = []
    _full = {"default", "deep_research", "tournament", "fast"}
    if mode in _full or "chain" in mode:
        p3.append("chain")
    if mode in _full or "technical" in mode:
        p3.append("technical")
    if mode in _full or "fundamental" in mode:
        p3.append("fundamental")
    if mode in _full or "sentiment" in mode:
        p3.append("sentiment")
    return p3


def calculate_divergence(state: DebateState) -> float:
    """计算多空分歧度 — 支持 v9.0 六阶段辩论"""
    bull_score = 0.0
    bear_score = 0.0
    for entry in state.get("bullish_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bearish_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    for entry in state.get("bullish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bearish_rebuttal_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    for entry in state.get("bull_final_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bull_score += float(sdata.get("confidence", 0))
    for entry in state.get("bear_final_arguments", []):
        if isinstance(entry, dict) and entry.get("symbols"):
            for sdata in entry["symbols"].values():
                bear_score += float(sdata.get("confidence", 0))
    total = bull_score + bear_score
    if total == 0:
        return 0.0
    return abs(bull_score - bear_score) / total


# ═══════════════════════════════════════════════════════
# 路由函数
# ═══════════════════════════════════════════════════════


def route_after_merge_research(state: DebateState) -> str:
    """P3 合并研究数据后：判断是否进入辩论"""
    if state.get("mode", "default") == "fast":
        return "verdict"       # fast 模式跳过辩论
    return "bullish_v1"        # 进入多空头攻防六节点


def route_after_freshness(state: DebateState) -> str:
    """P0b 新鲜度闸门路由: PASS → judge_direction / FAIL → aggregate_results (D06 降级)。"""
    freshness = state.get("freshness_report", {})
    status = freshness.get("status", "PASS")
    if status in ("ALL_STALE", "NO_VALID_SYMBOLS"):
        logger.warning("[路由] P0b 新鲜度闸门阻断 (%s), 路由到 D06 aggregate_results", status)
        return "aggregate_results"
    return "judge_direction"


def route_after_quality_inspect(state: DebateState) -> str:
    """质检后路由（Phase 3 Data Governance）。

    逻辑:
      - 当前品种质检 FAIL + 重试 < 2 次 → 退回重修（prepare_one_symbol）
      - 否则 → 存入结果（store_per_symbol_result）
      - G19 修复: 无有效品种时跳转到 aggregate_results，避免死循环
    """
    current_sym = _get_current_symbol(state)
    report = state.get("quality_report")
    counters: dict[str, int] = state.get("rework_counters", {})
    retries = counters.get(current_sym, 0)

    # G19: 如果 current_sym 为空且重试计数器不在预期位置，则跳转到 aggregate_results
    symbols = state.get("selected_symbols", [])
    _original = state.get("_original_symbols", [])
    idx = state.get("symbol_index", -1)
    if not symbols and not _original:
        logger.warning("G19 修复: 无任何品种可处理，跳转到 aggregate_results")
        return "aggregate_results"
    if not current_sym and idx < 0:
        logger.warning("G19 修复: 无法确定当前品种(current_sym为空, idx=%s)，跳转到 aggregate_results", idx)
        return "aggregate_results"

    if report and report.get("status") == "FAIL" and retries < 2:
        return "prepare_one_symbol"
    return "store_per_symbol_result"


def _should_skip_p3_source(state: DebateState, source_name: str) -> bool:
    """Phase D R01: 检查 P3 源是否应主动跳过（连续 N 轮准确率 < 40%）"""
    try:
        from pathlib import Path

        from memory.verdict.verdict_db import VerdictDB

        import os
        vdb = VerdictDB(Path(os.getcwd()) / "memory")
        current_sym = _get_current_symbol(state)
        if not current_sym:
            return False

        accuracy_threshold = float(os.environ.get("FDT_DELEGATION_ACCURACY_THRESHOLD", "0.4"))
        consecutive_rounds = int(os.environ.get("FDT_DELEGATION_CONSECUTIVE_ROUNDS", "5"))

        acc = vdb.query(symbol=current_sym, limit=500)
        with_outcome = [r for r in acc if r.get("outcome_actual") in ("correct", "wrong")]
        if len(with_outcome) < consecutive_rounds:
            return False

        recent = with_outcome[-consecutive_rounds:]
        correct = sum(1 for r in recent if r.get("outcome_actual") == "correct")
        accuracy = correct / len(recent) if recent else 0.0

        should_skip = accuracy < accuracy_threshold
        if should_skip:
            logger.info(
                "[Delegation R01] %s %s 跳过: 近%d轮准确率=%.1f%% < %.0f%%",
                current_sym, source_name, consecutive_rounds,
                accuracy * 100, accuracy_threshold * 100,
            )
            delegation_log: list = state.setdefault("delegation_log", [])
            delegation_log.append({
                "rule": "r01_skip_p3_source",
                "symbol": current_sym,
                "source": source_name,
                "accuracy": round(accuracy, 3),
                "trigger": f"近{consecutive_rounds}轮准确率={accuracy:.1%}",
            })
        return should_skip
    except Exception:
        return False
