"""
A2A 数据信封规范 — 统一输出格式

所有对外 API 返回统一的 A2APayload 信封，符合 Agent-to-Agent 协议规范。

用法:
    from contracts.a2a_payload import A2APayload, a2a_basis, a2a_debate

    # 简单构造
    p = A2APayload(
        type="fdc.basis",
        runtime_mode="independent",
        meta={"data_grade": "PRIMARY", ...},
        data={"symbol": "CU", "basis": -150},
        summary="铜主力贴水0.21%"
    )
    p.to_dict()  # → dict（含 validation）

    # 快捷构造
    p = a2a_basis("CU", 72150, 72300, "100ppi.com")  # → A2APayload
    p = a2a_debate("m", "HOLD", 0.6, "弱势突破")     # → A2APayload
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

# ── runtime_mode ──
RUNTIME_INDEPENDENT = "independent"       # 纯数据，无LLM参与
RUNTIME_LLM = "llm_enhanced"              # LLM参与分析/合成

# ── data_grade ──
GRADE_PRIMARY = "PRIMARY"                 # 一手数据（交易所直采）
GRADE_SECONDARY = "SECONDARY"             # 二手数据（聚合/加工）
GRADE_LLM = "LLM_GENERATED"               # LLM生成（含推理）
GRADE_DERIVED = "DERIVED"                 # 衍生计算（指标/模型）
GRADE_UNKNOWN = "UNKNOWN"                 # 等级未确定

GRADE_LABEL = {
    GRADE_PRIMARY: 0,
    GRADE_SECONDARY: 1,
    GRADE_LLM: 2,
    GRADE_DERIVED: 3,
    GRADE_UNKNOWN: 9,
}


@dataclass
class A2APayload:
    """统一数据输出信封。

    Fields:
        type:         数据类型标识，如 "fdc.basis" / "fdt.debate"
        runtime_mode: 运行模式 ("independent" / "llm_enhanced")
        meta:         元信息字典（数据等级、来源、时效等）
        data:         纯业务数据字典
        summary:      自然语言描述（≤200字）
    """
    type: str
    runtime_mode: str
    meta: dict
    data: dict
    summary: str

    # ── 可选的协议字段 ──
    jsonrpc: str = "2.0"
    method: str = "tasks/send"

    def to_dict(self) -> dict:
        """序列化 → 普通 dict，确保无 None / 空值合规。"""
        d = asdict(self)
        # 保证 meta 必备键
        if "data_grade" not in d["meta"]:
            d["meta"]["data_grade"] = GRADE_UNKNOWN
        if "data_grade_label" not in d["meta"]:
            d["meta"]["data_grade_label"] = GRADE_LABEL.get(
                d["meta"]["data_grade"], 9
            )
        if "sources" not in d["meta"]:
            d["meta"]["sources"] = []
        if "cached_at" not in d["meta"]:
            d["meta"]["cached_at"] = None
        if "llm_used" not in d["meta"]:
            d["meta"]["llm_used"] = False
        return d

    def to_json(self, **kw) -> str:
        """序列化 → JSON 字符串。"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)


# ── 快捷构造器 ──

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def a2a_basis(
    symbol: str,
    spot_price: float,
    futures_price: float,
    source: str = "unknown",
    runtime_mode: str = RUNTIME_INDEPENDENT,
) -> A2APayload:
    """构造基差数据信封。"""
    basis = spot_price - futures_price
    return A2APayload(
        type="fdc.basis",
        runtime_mode=runtime_mode,
        meta={
            "data_grade": GRADE_PRIMARY,
            "data_grade_label": 0,
            "sources": [source],
            "cached_at": None,
            "llm_used": runtime_mode == RUNTIME_LLM,
        },
        data={
            "symbol": symbol,
            "spot_price": spot_price,
            "futures_price": futures_price,
            "basis": round(basis, 2),
            "basis_pct": round(basis / futures_price * 100, 3) if futures_price else 0,
        },
        summary=(
            f"{symbol}基差{basis:+.0f}元/吨"
            f"({'贴水' if basis < 0 else '升水'}{abs(basis)/futures_price*100:.2f}%)"
        ),
    )


def a2a_inventory(
    symbol: str,
    inventory: float | None,
    change_pct: float | None,
    source: str = "unknown",
) -> A2APayload:
    """构造库存数据信封。"""
    return A2APayload(
        type="fdc.inventory",
        runtime_mode=RUNTIME_INDEPENDENT,
        meta={
            "data_grade": GRADE_PRIMARY,
            "data_grade_label": 0,
            "sources": [source],
            "cached_at": None,
            "llm_used": False,
        },
        data={
            "symbol": symbol,
            "inventory": inventory,
            "change_pct": change_pct,
        },
        summary=(
            f"{symbol}库存{inventory:,.0f}吨"
            f"({'涨' + str(change_pct) + '%' if change_pct else ''})"
            if inventory else f"{symbol}库存数据暂缺"
        ),
    )


def a2a_debate(
    symbol: str,
    decision: str,
    confidence: float,
    reasoning: str,
    entry: float | None = None,
    stop_loss: float | None = None,
    target: float | None = None,
    direction: str = "NEUTRAL",
) -> A2APayload:
    """构造辩论裁决信封。"""
    return A2APayload(
        type="fdt.debate",
        runtime_mode=RUNTIME_LLM,
        meta={
            "data_grade": GRADE_LLM,
            "data_grade_label": 2,
            "sources": ["FDT-debate-team"],
            "cached_at": None,
            "llm_used": True,
        },
        data={
            "symbol": symbol,
            "decision": decision,
            "direction": direction,
            "confidence": confidence,
            "entry": {"price": entry} if entry else None,
            "stop_loss": {"price": stop_loss} if stop_loss else None,
            "target": {"price": target} if target else None,
            "reasoning_preview": reasoning[:300] if reasoning else "",
        },
        summary=f"{symbol} {decision}（置信度{confidence:.0%}, 方向{direction}）",
    )


def a2a_scan_summary(
    total_symbols: int,
    triggered: list[dict],
    generated_at: str | None = None,
) -> A2APayload:
    """构造扫描汇总信封。"""
    return A2APayload(
        type="fdt.scan",
        runtime_mode=RUNTIME_INDEPENDENT,
        meta={
            "data_grade": GRADE_PRIMARY,
            "data_grade_label": 0,
            "sources": ["TQ-Local", "TDX"],
            "cached_at": None,
            "llm_used": False,
        },
        data={
            "total_symbols": total_symbols,
            "triggered_count": len(triggered),
            "signals": [
                {
                    "symbol": s.get("symbol"),
                    "direction": s.get("direction", ""),
                    "grade": s.get("grade", ""),
                    "total": s.get("total", 0),
                    "adx": s.get("adx"),
                    "rsi": s.get("rsi"),
                }
                for s in triggered
            ],
        },
        summary=f"扫描{total_symbols}品种，{len(triggered)}个触发辩论信号",
    )
