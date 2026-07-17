"""
FDT 周期发现引擎（v5.11.0）— 零硬编码周期 · 全参数化配置

设计原则（掌柜铁律）：
  1. 周期清单只来自 config.settings.PERIOD_REGISTRY，本文件不出现任何周期字面量
  2. 权重来自 PERIOD_FITNESS_WEIGHTS，不写死在函数里
  3. 复用既有资产，不重复造轮子：
       - strategies.base.BaseStrategy.score(period=...)  周期无关评分器
       - config.settings.resolve_param                 四层参数回落（周期参数化）
       - optimizer.knowledge_bridge.get_symbol_knowledge  WF 测试准确率数据源
  4. 扫描获取通过 scan_fn 注入解耦（调用方决定如何拿到各周期评分），引擎本身零副作用

discover() 为纯函数：输入某品种「各周期已评分信号」，输出最优周期 + 执行风格。
"""

import os
import sys
import json
from datetime import datetime

# 确保 scripts/ 在 path（本文件位于 scripts/signals/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    enabled_periods,
    period_meta,
    PERIOD_FITNESS_WEIGHTS,
    EXEC_STYLE_MAP,
)
from optimizer.knowledge_bridge import get_symbol_knowledge

# |total| 达到该值即信号强度满分（归一化分母，可随策略调整）
SIGNAL_FULL_SCALE = 100.0


def _norm_signal(total: float) -> float:
    return min(abs(total) / SIGNAL_FULL_SCALE, 1.0)


def discover(symbol: str, chain: str, period_signals: dict, knowledge: dict = None) -> dict:
    """
    周期发现核心（纯函数，零副作用）。

    参数:
        symbol:         品种
        chain:          产业链
        period_signals: {period: {"total","grade","direction","gap_risk"(可选)}}
                        只含已成功评分的周期；缺失周期自动跳过
        knowledge:      get_symbol_knowledge(symbol) 结果（含 wf_key 字段）；
                        缺省时内部自动获取
    返回:
        {
          "symbol","chain","best_period","ranked_periods":[{period,adapt,...}],
          "gap_risk","exec_style","scores":{...},"has_signal":bool
        }
    """
    if knowledge is None:
        knowledge = get_symbol_knowledge(symbol)

    scores = {}
    for p in enabled_periods():
        sig = period_signals.get(p)
        if not sig:
            continue
        meta = period_meta(p)

        # WF 准确率维度（无 wf_key → 该维贡献 0）
        wf_raw = knowledge.get(meta["wf_key"]) if meta.get("wf_key") else None
        wf_norm = (wf_raw / 100.0) if (wf_raw is not None) else 0.0

        # 信号强度维度
        sig_norm = _norm_signal(sig.get("total", 0))

        # 缺口风险维度（越低越好）
        gap = float(sig.get("gap_risk", 0.0) or 0.0)
        gap_norm = min(max(gap, 0.0), 1.0)

        w = PERIOD_FITNESS_WEIGHTS
        adapt = (w["wf_acc"] * wf_norm
                 + w["signal_strength"] * sig_norm
                 + w["gap_risk"] * (1.0 - gap_norm))

        scores[p] = {
            "adapt": round(adapt, 4),
            "wf_acc": wf_raw,
            "signal_strength": abs(sig.get("total", 0)),
            "gap_risk": round(gap_norm, 4),
            "direction": sig.get("direction", "neutral"),
            "grade": sig.get("grade", "NOISE"),
        }

    ranked = sorted(scores.items(), key=lambda kv: kv[1]["adapt"], reverse=True)
    if not ranked:
        return {
            "symbol": symbol,
            "chain": chain,
            "best_period": None,
            "ranked_periods": [],
            "gap_risk": 0.0,
            "exec_style": EXEC_STYLE_MAP["next_bar_market"],
            "scores": {},
            "has_signal": False,
        }

    best_p, best_s = ranked[0]
    return {
        "symbol": symbol,
        "chain": chain,
        "best_period": best_p,
        "ranked_periods": [{"period": p, **s} for p, s in ranked],
        "gap_risk": best_s["gap_risk"],
        "exec_style": EXEC_STYLE_MAP[period_meta(best_p)["exec_default"]],
        "scores": scores,
        "has_signal": True,
    }


def _collect_period_signals(symbol: str, scan_fn) -> dict:
    """对各启用周期调 scan_fn(period, symbol) 收集评分信号（解耦扫描源）。"""
    out = {}
    for p in enabled_periods():
        try:
            res = scan_fn(p, symbol)
            if res:
                out[p] = res
        except Exception:
            continue
    return out


def build_period_fitness(symbols, scan_fn, output_dir: str, date: str = None) -> str:
    """
    批量周期发现，写 period_fitness_{date}.json。

    参数:
        symbols:   [(symbol, chain), ...]
        scan_fn:   callable(period, symbol) -> {"total","grade","direction","gap_risk"} | None
                   由各周期扫描产物或 run_scan 提供（调用方注入，本引擎不硬编码扫描方式）
        output_dir: 输出目录
        date:      日期串（默认今天）
    返回: 写出文件路径
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    records = []
    for sym, chain in symbols:
        period_signals = _collect_period_signals(sym, scan_fn)
        rec = discover(sym, chain, period_signals)
        records.append(rec)

    payload = {
        "_meta": {
            "type": "period_fitness",
            "version": "1.0.0",
            "date": date,
            "periods": enabled_periods(),
            "weights": PERIOD_FITNESS_WEIGHTS,
            "source": "fdt period discovery engine (config-driven, zero hardcoded periods)",
        },
        "records": records,
    }
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"period_fitness_{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


if __name__ == "__main__":
    # Demo 入口: python period_fitness.py --demo cu lc
    # 用 run_scan 作为 scan_fn 真实扫描各启用周期（需 TqSdk 行情环境）
    import sys
    from config.settings import SYMBOL_CHAIN_MAP
    from scan_all import run_scan

    demo_syms = sys.argv[2:] or ["cu", "lc"]
    out_dir = "/tmp/fdt_pf_demo"

    def _scan(period, symbol):
        r = run_scan(
            output_dir=out_dir,
            output_prefix=f"pf_{period}",
            symbols=[(symbol, symbol)],
            strategy_name="channel_breakout",
            period=period,
        )
        for e in r.get("all_ranked", []):
            if e["symbol"] == symbol:
                return {
                    "total": e.get("total", 0),
                    "grade": e.get("grade", "NOISE"),
                    "direction": e.get("direction", "neutral"),
                }
        return None

    out = build_period_fitness(
        [(s, SYMBOL_CHAIN_MAP.get(s, "未知")) for s in demo_syms], _scan, out_dir
    )
    with open(out, encoding="utf-8") as f:
        _data = json.load(f)
    print(json.dumps(_data, ensure_ascii=False, indent=2))
