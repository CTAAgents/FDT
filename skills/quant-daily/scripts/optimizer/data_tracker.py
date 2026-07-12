"""数据追踪模块 — 采集扫描+辩论+实盘结果，供优化器使用。

每次全量扫描时调用 record_scan()，辩论后调用 record_debate()，
实盘结果出来后调用 record_outcome()。
数据累积在 training_data.json 中，按 (symbol, period) 索引。
"""

import json
import os
from datetime import datetime
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(_SCRIPTS_DIR, "optimizer", "training_data.json")


def _load() -> list:
    """加载全部训练数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save(records: list):
    """保存训练数据"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def record_scan(
    symbol: str,
    period: str,
    scan_time: str,
    signal_type: str,
    total_score: float,
    grade: str,
    price: float,
    adx: float,
    atr: float,
    rsi: float,
    params_snapshot: Optional[dict] = None,
):
    """记录一次扫描结果（不覆盖已存在的同品种同期记录，先检查后追加）"""
    records = _load()
    rec = {
        "symbol": symbol,
        "period": period,
        "scan_time": scan_time,
        "record_type": "scan",
        "signal_type": signal_type,
        "total_score": total_score,
        "grade": grade,
        "price": price,
        "adx": adx,
        "atr": atr,
        "rsi": rsi,
        "params_snapshot": params_snapshot or {},
        "debate": None,  # 待辩论填充
        "outcome": None,  # 待实盘填充
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    records.append(rec)
    _save(records)
    return rec


def record_debate(
    symbol: str,
    period: str,
    debate_direction: str,
    confidence: str,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    verdict_score: float = 0,
):
    """找到最近一条 scan 记录，关联辩论结果"""
    records = _load()
    # 从后往前找最匹配的 scan 记录
    for rec in reversed(records):
        if (rec.get("symbol") == symbol
                and rec.get("period") == period
                and rec.get("record_type") == "scan"
                and rec.get("debate") is None):
            rec["debate"] = {
                "direction": debate_direction,
                "confidence": confidence,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "verdict_score": verdict_score,
                "debated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            _save(records)
            return True
    return False


def record_outcome(
    symbol: str,
    period: str,
    actual_change_pct: float,
    hit_stop: bool = False,
    hit_target: bool = False,
    max_favorable_pct: float = 0,
    max_adverse_pct: float = 0,
):
    """实盘结果出来后，填入最近的 debate 记录"""
    records = _load()
    for rec in reversed(records):
        if (rec.get("symbol") == symbol
                and rec.get("period") == period
                and rec.get("debate") is not None
                and rec.get("outcome") is None):
            debate = rec["debate"]
            direction = debate["direction"]
            # 计算方向正确与否
            correct = None
            if direction == "bull":
                correct = actual_change_pct > 0
            elif direction == "bear":
                correct = actual_change_pct < 0
            else:
                correct = abs(actual_change_pct) < 0.3

            rec["outcome"] = {
                "actual_change_pct": actual_change_pct,
                "correct": correct,
                "hit_stop": hit_stop,
                "hit_target": hit_target,
                "max_favorable_pct": max_favorable_pct,
                "max_adverse_pct": max_adverse_pct,
                "pnl_pct": _calc_pnl(direction, actual_change_pct, hit_stop),
                "outcome_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            _save(records)
            return True
    return False


def _calc_pnl(direction: str, change_pct: float, hit_stop: bool) -> float:
    """估算盈亏比例（简化模型）"""
    if hit_stop:
        return -1.0  # 止损 = -1R
    if direction == "bull":
        return change_pct
    elif direction == "bear":
        return -change_pct
    return 0.0


def get_training_data(
    symbol: Optional[str] = None,
    period: Optional[str] = None,
    min_samples: int = 1,
) -> list:
    """按条件筛选训练数据，只有 scan+debate+outcome 全齐的才算有效样本"""
    records = _load()
    filtered = []
    for rec in records:
        if symbol and rec.get("symbol") != symbol:
            continue
        if period and rec.get("period") != period:
            continue
        if rec.get("debate") and rec.get("outcome"):
            filtered.append(rec)
    return filtered


def get_stats(symbol: Optional[str] = None, period: Optional[str] = "daily") -> dict:
    """查看某品种/周期的数据统计"""
    records = _load()
    total = len(records)
    with_debate = sum(1 for r in records if r.get("debate"))
    with_outcome = sum(1 for r in records if r.get("outcome"))

    if symbol:
        sym_records = [r for r in records if r.get("symbol") == symbol]
        sym_debate = sum(1 for r in sym_records if r.get("debate"))
        sym_outcome = sum(1 for r in sym_records if r.get("outcome"))
        return {
            "symbol": symbol,
            "total_scans": len(sym_records),
            "debated": sym_debate,
            "with_outcome": sym_outcome,
            "scan_dates": list(set(r["scan_time"][:10] for r in sym_records)),
        }

    return {
        "total_records": total,
        "debated": with_debate,
        "with_outcome": with_outcome,
        "symbols_covered": len(set(r["symbol"] for r in records)),
    }


def clear():
    """清空训练数据（慎用）"""
    _save([])
