# -*- coding: utf-8 -*-
"""交易日志与 PnL 反馈闭环 — 记录交易执行结果，反向标注技术Agent预测。

流程:
1. Trader 执行交易 → record_trade() → trade_journal.json
2. 交易平仓 → close_trade() → 计算 PnL
3. PnL 结算后 → annotate_prediction() → 反向标注技术Agent的方向/概率/置信度
4. 错例进入 replay buffer → 定期用于模型 finetune
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

TRADE_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trade_journal", "journal.json"
)

REPLAY_BUFFER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trade_journal", "replay_buffer.json"
)


def record_trade(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    lots: int,
    entry_date: str,
    strategy: str = "debate",
    tech_prediction: Optional[Dict] = None,
    trader_notes: str = "",
) -> Dict:
    """记录一笔新交易。

    Args:
        symbol: 品种代码
        direction: "long"/"short"
        entry_price: 入场价
        stop_price: 止损价
        target_price: 目标价
        lots: 手数
        entry_date: 入场日期 "2026-07-05"
        strategy: 策略来源
        tech_prediction: 技术Agent当时的预测 {"prob", "direction", "confidence"}
        trader_notes: 交易员备注

    Returns:
        交易记录 dict
    """
    import hashlib

    trade_id = hashlib.md5(f"{symbol}{entry_date}{entry_price}{datetime.now().timestamp()}".encode()).hexdigest()[:12]

    trade = {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "lots": lots,
        "entry_date": entry_date,
        "strategy": strategy,
        "status": "open",
        "tech_prediction": tech_prediction or {},
        "trader_notes": trader_notes,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": None,
        "exit_price": None,
        "pnl_points": None,
        "pnl_pct": None,
        "annotation": None,
    }

    _append_journal(trade)
    return trade


def close_trade(
    trade_id: str, exit_price: float, exit_date: str, multiplier: float = 10, annotation: Optional[Dict] = None
) -> Dict:
    """平仓并计算 PnL。

    Args:
        trade_id: 交易ID
        exit_price: 出场价
        exit_date: 出场日期
        multiplier: 合约乘数
        annotation: 可选，手动标注
    """
    journal = _load_journal()
    for t in journal:
        if t.get("trade_id") == trade_id:
            direction = t.get("direction", "long")
            entry = t.get("entry_price", 0)
            lots = t.get("lots", 1)

            # PnL 计算
            if direction == "long":
                pnl_points = exit_price - entry
            else:
                pnl_points = entry - exit_price

            pnl_amount = pnl_points * multiplier * lots
            pnl_pct = pnl_amount / (entry * multiplier * lots) * 100 if entry > 0 else 0

            t["status"] = "closed"
            t["exit_price"] = exit_price
            t["closed_at"] = f"{exit_date} {datetime.now().strftime('%H:%M:%S')}"
            t["pnl_points"] = round(pnl_points, 1)
            t["pnl_pct"] = round(pnl_pct, 2)
            if annotation:
                t["annotation"] = annotation

            _save_journal(journal)

            # 如果有关联的技术预测，触发标注
            tech = t.get("tech_prediction", {})
            if tech and t.get("status") == "closed":
                ann_result = annotate_prediction(trade_id, tech, direction, pnl_pct)
                t["annotation"] = ann_result.get("annotation")
                t["annotation_detail"] = ann_result
                _save_journal(journal)
                t["annotation"] = ann_result.get("annotation")
                t["annotation_detail"] = ann_result

            _save_journal(journal)
            t["_annotation_detail"] = t.pop("annotation_detail", t.get("annotation_detail"))

            return t
    return {"error": f"trade_id {trade_id} not found"}


def annotate_prediction(trade_id: str, prediction: Dict, actual_direction: str, pnl_pct: float) -> Dict:
    """反向标注技术Agent的预测 — PnL 结算后的反馈。

    判断标准:
    - prediction direction == actual direction AND pnl > 0 → "correct"
    - prediction direction != actual direction → "wrong"
    - prediction confidence > 70 but wrong → "confident_mistake" (高信错判)
    - prediction confidence < 50 but correct → "lucky" (蒙对的)
    """
    pred_dir = prediction.get("direction", 0)
    pred_conf = prediction.get("confidence", 50)
    actual_dir = 1 if actual_direction == "long" else -1

    if pred_dir == actual_dir and pnl_pct > 0:
        label = "correct"
    elif pred_dir != actual_dir and pnl_pct < 0:
        label = "wrong"
    elif pred_dir == actual_dir and pnl_pct < 0:
        label = "direction_right_stop_hit"
    elif pred_conf >= 70 and pred_dir != actual_dir:
        label = "confident_mistake"
    elif pred_conf < 50 and pred_dir == actual_dir:
        label = "lucky"
    else:
        label = "mixed"

    annotation = {
        "trade_id": trade_id,
        "prediction": prediction,
        "actual_direction": actual_direction,
        "pnl_pct": round(pnl_pct, 2),
        "annotation": label,
        "annotated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 错例进 replay buffer
    if label in ("wrong", "confident_mistake"):
        _append_replay_buffer(
            {
                "trade_id": trade_id,
                "prediction": prediction,
                "annotation": label,
                "pnl_pct": round(pnl_pct, 2),
                "annotated_at": annotation["annotated_at"],
            }
        )

    return annotation


def get_replay_buffer() -> List[Dict]:
    """获取 replay buffer（错例集合）"""
    if not os.path.exists(REPLAY_BUFFER_PATH):
        return []
    with open(REPLAY_BUFFER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def query_history(symbol: str, lookback_days: int = 30) -> List[Dict]:
    """查询某品种近期历史交易决策。

    供闫判官做跨轮次学习：
    - 同品种上次看多看亏了钱→本次更保守
    - 同方向历史胜率统计

    Args:
        symbol: 品种代码
        lookback_days: 回溯天数

    Returns:
        历史交易记录列表（closed状态），按时间倒序
    """
    journal = _load_journal()
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # 筛选品种+日期范围+已平仓
    history = []
    for t in journal:
        if t.get("symbol", "").upper() != symbol.upper():
            continue
        entry_date = t.get("entry_date", "")
        if entry_date < cutoff:
            continue
        if t.get("status") != "closed":
            continue
        history.append(t)

    # 按时间倒序
    history.sort(key=lambda x: x.get("entry_date", ""), reverse=True)
    return history


def get_performance_summary() -> Dict:
    """生成技术Agent预测性能汇总。"""
    journal = _load_journal()
    closed = [t for t in journal if t.get("status") == "closed"]
    if not closed:
        return {"total_trades": 0}

    total = len(closed)
    winning = sum(1 for t in closed if t.get("pnl_pct", 0) > 0)
    annotated = [t for t in closed if t.get("annotation")]
    correct = sum(1 for t in annotated if t.get("annotation") == "correct")
    confident_mistakes = sum(1 for t in annotated if t.get("annotation") == "confident_mistake")

    return {
        "total_trades": total,
        "win_rate": round(winning / max(total, 1) * 100, 1),
        "avg_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in closed) / max(total, 1), 2),
        "annotation_count": len(annotated),
        "accuracy": round(correct / max(len(annotated), 1) * 100, 1),
        "confident_mistakes": confident_mistakes,
    }


# ── 内部持久化 ──


def _load_journal() -> List[Dict]:
    if not os.path.exists(TRADE_JOURNAL_PATH):
        return []
    with open(TRADE_JOURNAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_journal(journal: List[Dict]):
    os.makedirs(os.path.dirname(TRADE_JOURNAL_PATH), exist_ok=True)
    with open(TRADE_JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)


def _append_journal(record: Dict):
    journal = _load_journal()
    journal.append(record)
    _save_journal(journal)


def _append_replay_buffer(record: Dict):
    buffer = []
    if os.path.exists(REPLAY_BUFFER_PATH):
        with open(REPLAY_BUFFER_PATH, "r", encoding="utf-8") as f:
            buffer = json.load(f)
    buffer.append(record)
    if len(buffer) > 500:
        buffer = buffer[-500:]
    os.makedirs(os.path.dirname(REPLAY_BUFFER_PATH), exist_ok=True)
    with open(REPLAY_BUFFER_PATH, "w", encoding="utf-8") as f:
        json.dump(buffer, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════
# v4.4 升级版交易日志（信号→执行→风控→结果）
# ═══════════════════════════════════════════════

TRADE_LOG_SCHEMA = {
    "round_id": str,  # "RB_20260705"
    "mode": str,  # "paper" / "live"
    "signal": dict,  # {direction, confidence, rule_vote, ml_vote, sentiment_vote}
    "execution": dict,  # {contract, entry_price, lots_filled, slippage_ticks, commission}
    "risk": dict,  # {stop_loss, take_profit, margin, risk_verdict}
    "outcome": dict,  # {exit_price, pnl, exit_reason, duration_hours}
}


def record_trade_v2(trade: dict) -> str:
    """v2 交易记录（完整 schema）。"""
    trade_id = f"T{trade.get('round_id', 'UNKNOWN')}_{datetime.now().strftime('%H%M%S')}"
    trade["trade_id"] = trade_id
    trade["recorded_at"] = datetime.now().isoformat()
    _append_journal(trade)
    return trade_id


def daily_review(symbol: str = None, days: int = 1) -> dict:
    """每日复盘分析。

    Args:
        symbol: 品种筛选（可选）
        days: 回顾天数

    Returns:
        {"summary": {...}, "by_confidence": [...], "ml_vs_rule": {...}}
    """
    trades = query_history(symbol=symbol or "", lookback_days=days)
    if not trades:
        return {"trades": 0, "note": "今日无交易"}

    closed = [t for t in trades if t.get("outcome", {}).get("exit_price")]
    if not closed:
        return {"trades": len(trades), "note": "所有交易未平仓"}

    wins = sum(1 for t in closed if t.get("outcome", {}).get("pnl", 0) > 0)
    total_pnl = sum(t.get("outcome", {}).get("pnl", 0) for t in closed)
    gross_profit = sum(max(t.get("outcome", {}).get("pnl", 0), 0) for t in closed)
    gross_loss = abs(sum(min(t.get("outcome", {}).get("pnl", 0), 0) for t in closed))

    # 按置信度分组
    by_confidence = {}
    for t in closed:
        conf = t.get("signal", {}).get("confidence", 0.5)
        bucket = "high" if conf >= 0.7 else "medium" if conf >= 0.5 else "low"
        if bucket not in by_confidence:
            by_confidence[bucket] = {"trades": 0, "wins": 0, "pnl": 0}
        by_confidence[bucket]["trades"] += 1
        by_confidence[bucket]["wins"] += 1 if t.get("outcome", {}).get("pnl", 0) > 0 else 0
        by_confidence[bucket]["pnl"] += t.get("outcome", {}).get("pnl", 0)

    # ML vs 规则表现
    ml_correct = sum(
        1
        for t in closed
        if t.get("signal", {}).get("ml_vote", 0) * (1 if t.get("outcome", {}).get("pnl", 0) > 0 else -1) > 0
    )
    rule_correct = sum(
        1
        for t in closed
        if t.get("signal", {}).get("rule_vote", 0) * (1 if t.get("outcome", {}).get("pnl", 0) > 0 else -1) > 0
    )

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": {
            "total_trades": len(closed),
            "win_rate": round(wins / len(closed), 4),
            "profit_factor": round(gross_profit / max(gross_loss, 1), 2),
            "total_pnl": round(total_pnl, 2),
        },
        "by_confidence": by_confidence,
        "ml_vs_rule": {
            "ml_correct": ml_correct,
            "rule_correct": rule_correct,
            "ml_win_rate": round(ml_correct / max(len(closed), 1), 3),
            "rule_win_rate": round(rule_correct / max(len(closed), 1), 3),
        },
    }
