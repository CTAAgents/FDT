"""Phase 2a: 偏差检测器 — 裁决偏差分析 + EvoMem 补丁创建。

MASE 中环（经验反馈）的核心组件：
1. 辩论完成后，获取实际市场走势
2. 比较裁决方向 vs 实际走势
3. 偏差案例自动创建 EvoMem 格式补丁
4. 正确案例记录准确率统计
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── 偏差分类（中文，用于补丁 rationale） ──
DEVIATION_CATEGORIES: dict[str, str] = {
    "data_error": "P1数据源有误或数据缺失",
    "logical_flaw": "P2/P3分析逻辑缺陷或遗漏关键因素",
    "weight_misallocation": "P4权重分配不当",
    "sentiment_miss": "P3情绪分析方向错误",
    "unforeseen_event": "不可预见的突发事件（黑天鹅）",
    "structural_change": "市场结构或规则变化",
}

# ── 方向归一化映射 ──
_VERDICT_DIR_MAP: dict[str, str] = {
    "bull": "bullish", "bullish": "bullish", "BUY": "bullish",
    "bear": "bearish", "bearish": "bearish", "SELL": "bearish",
}


async def detect_and_patch(
    verdict: dict,
    trace_id: str,
    memory_manager: Any | None = None,
    fetcher: Callable | None = None,
    lookback_days: int = 3,
) -> dict[str, Any]:
    """执行完整的偏差检测 → 补丁创建流程。

    Args:
        verdict: 裁决结果 dict（含 per_symbol）。
        trace_id: 全链路追踪 ID。
        memory_manager: MemoryManager 实例（用于存储补丁）。
        fetcher: 异步函数 async def(symbol, days) → {"movement_pct": float, "latest_price": float}。
                 传入 None 时跳过实际走势获取（仅分类分析）。
        lookback_days: 验证天数（向后回溯）。

    Returns:
        dict:
          - trace_id / timestamp
          - total_symbols: int
          - accurate_symbols: list[str]  方向正确的品种
          - deviations: list[dict]       偏差品种详情
          - accuracy: float              准确率
          - created_patches: list[str]   创建的补丁 ID 列表
    """
    report: dict[str, Any] = {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_symbols": 0,
        "accurate_symbols": [],
        "deviations": [],
        "created_patches": [],
        "accuracy": 0.0,
    }

    per_symbol = (verdict or {}).get("per_symbol", {})
    if not per_symbol:
        logger.info("[DevDetect] verdict 无 per_symbol 数据，跳过")
        return report

    report["total_symbols"] = len(per_symbol)

    # ── Step 1: 逐品种检测偏差 ──
    accurate: list[str] = []
    deviations: list[dict] = []

    for sym, sv in per_symbol.items():
        if not isinstance(sv, dict):
            continue
        direction = sv.get("direction", "neutral")
        if direction in ("neutral", None, "none", ""):
            continue

        # 获取实际走势
        actual: dict | None = None
        if fetcher is not None:
            actual = await _fetch_actual(fetcher, sym, lookback_days)

        if actual is None:
            # 无实际数据时仍做偏离分类
            outcome = "no_data"
        else:
            outcome = _compare(
                _VERDICT_DIR_MAP.get(direction, direction),
                actual.get("movement_pct", 0),
            )

        if outcome == "correct":
            accurate.append(sym)
        elif outcome != "no_data":
            deviation: dict[str, Any] = {
                "symbol": sym,
                "verdict_direction": direction,
                "confidence": sv.get("confidence", 0.5),
                "movement_pct": round(actual.get("movement_pct", 0), 2) if actual else 0,
                "latest_price": (actual or {}).get("latest_price"),
                "entry_price": sv.get("entry_price"),
                "outcome": outcome,
                "category": _classify(sv.get("confidence", 0.5)),
            }
            deviations.append(deviation)

    report["accurate_symbols"] = accurate
    report["deviations"] = deviations

    # 计算准确率（排除 neutral 品种）
    non_neutral = report["total_symbols"] - sum(
        1 for v in per_symbol.values()
        if isinstance(v, dict) and v.get("direction") in ("neutral", None, "none", "")
    )
    report["accuracy"] = len(accurate) / max(non_neutral, 1)

    # ── Step 2: 为偏差案例创建 EvoMem 补丁 ──
    if deviations and memory_manager is not None:
        report["created_patches"] = await _create_patches(deviations, trace_id, memory_manager)

    logger.info(
        "[DevDetect] 偏差检测完成: total=%d, non_neutral=%d, accurate=%d, deviations=%d, patches=%d",
        report["total_symbols"], non_neutral, len(accurate), len(deviations), len(report["created_patches"]),
    )
    return report


# ═══════════════════════════════════════════════════════
# 内部函数
# ═══════════════════════════════════════════════════════


async def _fetch_actual(
    fetcher: Callable, symbol: str, days: int,
) -> dict | None:
    """获取品种的 N 日实际走势。"""
    try:
        return await fetcher(symbol, days)
    except Exception as e:
        logger.debug("[DevDetect] %s 走势获取失败: %s", symbol, e)
        return None


def _compare(verdict_dir: str, movement_pct: float) -> str:
    """比较裁决方向与实际走势百分比变动。

    Returns:
        "correct" / "incorrect" / "neutral_miss"
    """
    threshold = 0.5  # 最小有效波动百分比
    if abs(movement_pct) < threshold:
        return "neutral_miss"
    if verdict_dir == "bullish" and movement_pct > 0:
        return "correct"
    if verdict_dir == "bearish" and movement_pct < 0:
        return "correct"
    return "incorrect"


def _classify(confidence: float) -> str:
    """基于置信度做简单偏差分类。

    可根据未来更多信号升级为 LLM 驱动的根因分析。
    """
    if confidence < 0.5:
        return "weight_misallocation"
    if confidence > 0.85:
        return "unforeseen_event"
    return "logical_flaw"


async def _create_patches(
    deviations: list[dict], trace_id: str, mm: Any,
) -> list[str]:
    """为偏差列表创建 EvoMem 补丁。"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    created: list[str] = []

    for i, dev in enumerate(deviations):
        cat = dev.get("category", "logical_flaw")
        cat_label = DEVIATION_CATEGORIES.get(cat, "未知")
        pid = f"patch-deviation-{today}-{i+1:03d}"

        try:
            mm.store_patch({
                "patch_id": pid,
                "domain": f"{dev['symbol']}|裁决偏差|{cat}",
                "pre_state": (
                    f"裁决方向={dev['verdict_direction']}（置信度={dev['confidence']}），"
                    f"入场价={dev.get('entry_price', '?')}"
                ),
                "post_state": (
                    f"实际走势={dev['movement_pct']}%，"
                    f"最新价={dev.get('latest_price', '?')}，"
                    f"偏差分类：{cat_label}"
                ),
                "rationale": (
                    f"{cat_label}：{dev['symbol']} "
                    f"裁决={dev['verdict_direction']}（{dev['confidence']}）→"
                    f"实际{dev['movement_pct']}%"
                ),
                "evidence": [
                    f"trace_id:{trace_id}",
                    f"category:{cat}",
                ],
                "conditions": {
                    "applicable_regime": [],
                    "valid_from": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                },
                "trace_id": trace_id,
                "intent": f"裁决偏差补丁：{dev['symbol']} {dev['verdict_direction']}",
                "outcome": "incorrect",
            })
            created.append(pid)
            logger.info("[DevPatch] 创建补丁 %s: %s %s", pid, dev["symbol"], cat)
        except Exception as e:
            logger.warning("[DevPatch] 补丁存储失败 %s: %s", pid, e)

    return created
