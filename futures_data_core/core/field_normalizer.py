"""Agent 间字段标准化器 [INDEPENDENT]。

解决 FDT 系统各子 Agent 间数据请求栏位不一致问题（共 8 类已知差距），
在数据边界处统一转换为规范字段名。

规范约定（COMMIT 级别）:
    direction:        Literal["bull", "bear", "neutral"]
    oi:               int（持仓量，废弃 open_interest / OI）
    total:            float（信号总分，正值=多头强度，负值=空头强度；仓单总量用 receipt_total）
    confidence:       float（0-1，废弃 0-100 int / 中文等级）
    entry_price:      float（入场价）
    stop_loss_price:  float（止损价）
    target_price:     float（目标价）
    position_pct:     float（仓位百分比 0-100）
    grade:            Literal["STRONG", "WATCH", "WEAK", "NOISE"]
    data_source:      str（数据来源，meta 内用 source 作为子字段）
    risk_color:       Literal["green", "yellow", "red"]
    date:             str（YYYY-MM-DD）
    symbol:           str（品种代码，废弃 pid / sym）
    position_size:    float → position_pct（不一致的仓位字段）
    risk_reward:      float → risk_reward_ratio

使用方式:
    row = normalize_kline_row(raw_dict)
    sig = normalize_signal_row(raw_dict)
    v   = normalize_verdict(raw_dict)
    r   = normalize_risk_check(raw_dict)
"""

from __future__ import annotations

from typing import Any

# ── 规范字段名常量 ──────────────────────────────────────────


class CanonicalField:
    """规范字段名 — 所有子 Agent 间交换数据时应使用的名称。"""

    # ── K 线 ──
    DATE = "date"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    AMOUNT = "amount"
    OI = "oi"                     # 统一：废弃 open_interest / OI
    SETTLEMENT = "settlement"

    # ── 方向/信号 ──
    DIRECTION = "direction"       # "bull" / "bear" / "neutral" (废弃 verdict / decision / winner / signal)
    TOTAL = "total"               # 信号总分（仓单总量用 RECEIPT_TOTAL）
    RECEIPT_TOTAL = "receipt_total"
    CONFIDENCE = "confidence"     # 0-1 float（废弃 0-100 int / 中文等级）
    GRADE = "grade"               # "STRONG" / "WATCH" / "WEAK" / "NOISE" (废弃 level)

    # ── 交易参数 ──
    ENTRY_PRICE = "entry_price"   # 废弃 entry
    STOP_LOSS_PRICE = "stop_loss_price"   # 废弃 stop_loss
    TARGET_PRICE = "target_price"          # 废弃 target / target1 / target2
    POSITION_PCT = "position_pct"          # 废弃 position_size
    RISK_REWARD_RATIO = "risk_reward_ratio"  # 废弃 risk_reward

    # ── 风控 ──
    RISK_COLOR = "risk_color"     # "green" / "yellow" / "red" (废弃 risk_level 字符串)
    RISK_LEVEL = "risk_level"     # 风控分类级别

    # ── 元数据 ──
    SYMBOL = "symbol"             # 废弃 pid / sym
    DATA_SOURCE = "data_source"   # 数据来源（meta 内用 source 作为子字段）
    SOURCE = "source"             # meta 内子字段

    # ── 名称别名（不作为输出字段，仅用于入站转换映射） ──
    _DIRECTION_MAP = {
        "bull": "bull", "bullish": "bull", "BUY": "bull", "buy": "bull",
        "bear": "bear", "bearish": "bear", "SELL": "bear", "sell": "bear",
        "neutral": "neutral", "hold": "neutral", "HOLD": "neutral",
        "": "neutral",
    }
    _GRADE_MAP = {
        "STRONG": "STRONG", "strong": "STRONG", "S": "STRONG",
        "WATCH": "WATCH", "watch": "WATCH", "W": "WATCH",
        "WEAK": "WEAK", "weak": "WEAK",
        "NOISE": "NOISE", "noise": "NOISE", "N": "NOISE",
    }
    _CONFIDENCE_STR_MAP = {
        "高": 0.85, "high": 0.85, "HIGH": 0.85,
        "中": 0.55, "medium": 0.55, "MEDIUM": 0.55,
        "低": 0.25, "low": 0.25, "LOW": 0.25,
    }
    _RISK_COLOR_MAP = {
        "green": "green", "GREEN": "green",
        "yellow": "yellow", "YELLOW": "yellow",
        "red": "red", "RED": "red",
    }


# ── K 线行标准化 ────────────────────────────────────────────


def normalize_kline_row(row: dict) -> dict:
    """标准化单条 K 线记录。

    入口: scan_all.py 采集 → nodes.py 消费 / Data-Core 输出 → FDT
    """
    out: dict = {}
    out[CanonicalField.DATE] = _pick_date(row)
    out[CanonicalField.OPEN] = _float(row, "open")
    out[CanonicalField.HIGH] = _float(row, "high")
    out[CanonicalField.LOW] = _float(row, "low")
    out[CanonicalField.CLOSE] = _float(row, "close")
    out[CanonicalField.VOLUME] = _float(row, "volume")
    out[CanonicalField.AMOUNT] = _float(row, "amount")
    out[CanonicalField.OI] = _int_any(row, "oi", "open_interest", "OI")
    out[CanonicalField.SETTLEMENT] = _float(row, "settlement")
    out[CanonicalField.DATA_SOURCE] = str(
        row.get("data_source") or row.get("source", "")
    )
    return out


def normalize_kline_list(rows: list[dict]) -> list[dict]:
    """批量标准化 K 线列表。"""
    return [normalize_kline_row(r) for r in rows]


# ── 信号行标准化 ────────────────────────────────────────────


def normalize_signal_row(row: dict) -> dict:
    """标准化扫描信号行。

    入口: scan_all.py 输出 all_ranked 列表 → nodes.py / graph.py 消费
    """
    out: dict = {}
    out[CanonicalField.SYMBOL] = str(
        row.get("symbol") or row.get("pid") or row.get("sym", "")
    )
    out[CanonicalField.DIRECTION] = _normalize_direction(
        row.get("direction") or row.get("dir") or ""
    )
    out[CanonicalField.TOTAL] = _float(row, "total", "raw_total", "score")
    out[CanonicalField.CONFIDENCE] = _normalize_confidence(
        row.get("confidence") or row.get("score", 0),
        _float(row, "total", "raw_total", "score"),
    )
    out[CanonicalField.GRADE] = _normalize_grade(
        row.get("grade") or row.get("level") or ""
    )
    out["price"] = _float(row, "price")
    out["adx"] = _float(row, "adx", "ADX", "ADX14")
    out["rsi"] = _float(row, "rsi", "RSI14", "RSI")
    out["atr"] = _float(row, "atr")
    out["stage"] = str(row.get("stage", ""))
    out["name"] = str(row.get("name", ""))
    return out


def normalize_signal_list(rows: list[dict]) -> list[dict]:
    """批量标准化信号列表。"""
    return [normalize_signal_row(r) for r in rows]


# ── 裁决标准化 ──────────────────────────────────────────────


def normalize_verdict(verdict: dict) -> dict:
    """标准化裁决输出。

    入口: node_verdict 输出 → node_risk_check / node_report 消费
    """
    out: dict = {}
    out[CanonicalField.DIRECTION] = _normalize_direction(
        verdict.get("direction") or verdict.get("verdict") or verdict.get("winner", "")
    )
    out[CanonicalField.CONFIDENCE] = _normalize_confidence(
        verdict.get("confidence", 0.5), 0.5
    )
    out[CanonicalField.ENTRY_PRICE] = _float(
        verdict, "entry_price", "entry", "price"
    )
    out[CanonicalField.STOP_LOSS_PRICE] = _float(
        verdict, "stop_loss_price", "stop_loss"
    )
    out[CanonicalField.TARGET_PRICE] = _float(
        verdict, "target_price", "target", "target1"
    )
    out[CanonicalField.POSITION_PCT] = _float(
        verdict, "position_pct", "position_size"
    )
    out[CanonicalField.RISK_REWARD_RATIO] = _float(
        verdict, "risk_reward_ratio", "risk_reward"
    )
    out["reason"] = str(verdict.get("reason", "") or "")
    out["contract"] = str(verdict.get("contract", "") or "")
    out["symbols"] = verdict.get("symbols", verdict.get("selected_symbols", []))
    out[CanonicalField.GRADE] = _normalize_grade(
        verdict.get("grade") or verdict.get("level") or ""
    )
    # 保留原 verdict 中的额外字段
    for k in ("overturn_scan", "divergence", "score", "scores"):
        if k in verdict:
            out[k] = verdict[k]
    return out


# ── 风控标准化 ──────────────────────────────────────────────


def normalize_risk_check(risk: dict) -> dict:
    """标准化风控审核输出。

    入口: node_risk_check 输出 → node_report / node_signal_output 消费
    """
    out: dict = {}
    rc = str(risk.get("risk_color") or risk.get("risk_level", "yellow")).lower()
    out[CanonicalField.RISK_COLOR] = CanonicalField._RISK_COLOR_MAP.get(rc, "yellow")
    out[CanonicalField.RISK_LEVEL] = str(risk.get("risk_level", "—"))
    out[CanonicalField.CONFIDENCE] = _normalize_confidence(
        risk.get("confidence", 0.5), 0.5
    )
    out["approved"] = bool(risk.get("approved", True))
    out["warnings"] = list(risk.get("warnings", []) or [])
    out["risk_score"] = _float(risk, "risk_score")
    return out


# ── 方向统一 ────────────────────────────────────────────────


def normalize_direction_raw(raw: str) -> str:
    """将任意方向表示为 ``"bull"`` / ``"bear"`` / ``"neutral"``。"""
    return _normalize_direction(raw)


def normalize_direction_to_signal(direction: str) -> str:
    """将规范方向转换为信号方向 ``"BUY"`` / ``"SELL"`` / ``"HOLD"``。
    
    显示层用，不做数据交换。
    """
    n = _normalize_direction(direction)
    return {"bull": "BUY", "bear": "SELL", "neutral": "HOLD"}.get(n, "HOLD")


# ── 置信度统一 ──────────────────────────────────────────────


def normalize_confidence_raw(raw: Any, fallback: float = 0.5) -> float:
    """将任意置信度格式转为 0-1 float。"""
    return _normalize_confidence(raw, fallback)


# ── 等级统一 ──────────────────────────────────────────────


def normalize_grade_raw(raw: str) -> str:
    """将任意等级格式转为规范 grade。"""
    return _normalize_grade(raw)


# ── 内部辅助 ──────────────────────────────────────────────


def _normalize_direction(raw: str) -> str:
    if not raw:
        return "neutral"
    r = str(raw).lower().strip()
    # 处理 winner 风格 (bull_win / bear_win)
    if r in ("bull_win",):
        return "bull"
    if r in ("bear_win",):
        return "bear"
    return CanonicalField._DIRECTION_MAP.get(r, "neutral")


def _normalize_confidence(raw: Any, score_fallback: float = 0.0) -> float:
    """将置信度转为 0-1 float。

    支持:
        - float 0-1: 直接返回
        - float 0-100: 除以 100
        - str "高"/"中"/"低" 或 "HIGH"/"MEDIUM"/"LOW": 映射
        - int 0-100: 除以 100
    """
    if raw is None:
        return min(max(score_fallback / 100.0, 0.0), 1.0)
    if isinstance(raw, str):
        mapped = CanonicalField._CONFIDENCE_STR_MAP.get(raw)
        if mapped is not None:
            return mapped
        try:
            val = float(raw)
        except (ValueError, TypeError):
            return 0.5
        return min(max(val / 100.0 if val > 1 else val, 0.0), 1.0)
    if isinstance(raw, (int, float)):
        if raw > 1:
            return min(max(raw / 100.0, 0.0), 1.0)
        return min(max(raw, 0.0), 1.0)
    return 0.5


def _normalize_grade(raw: str) -> str:
    if not raw:
        return "NOISE"
    r = str(raw).upper().strip()
    return CanonicalField._GRADE_MAP.get(r, "NOISE")


def _float(row: dict, *keys: str) -> float:
    """从 row 中依次尝试 key，返回第一个有效 float。"""
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return 0.0


def _int_any(row: dict, *keys: str) -> int:
    """从 row 中依次尝试 key，返回第一个有效 int。"""
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return int(v)
            except (ValueError, TypeError):
                continue
    return 0


def _pick_date(row: dict) -> str:
    """从 row 中提取日期（支持多种字段名和格式）。"""
    for key in ("date", "datetime", "trade_date", "Date"):
        v = row.get(key)
        if v and isinstance(v, str):
            v = v.strip()
            if not v:
                continue
            if " " in v:
                return v.split(" ")[0]
            if "T" in v:
                return v.split("T")[0]
            # YYYY-MM-DD 或 YYYYMMDD
            if v.replace("-", "").isdigit() or v.isdigit():
                return v
    return ""


__all__ = [
    "CanonicalField",
    "normalize_kline_row",
    "normalize_kline_list",
    "normalize_signal_row",
    "normalize_signal_list",
    "normalize_verdict",
    "normalize_risk_check",
    "normalize_direction_raw",
    "normalize_direction_to_signal",
    "normalize_confidence_raw",
    "normalize_grade_raw",
]
