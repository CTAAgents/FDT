"""120m K线重采样扫描 — 从TDX 60m数据合并为120m, 自含评分逻辑

用法:
  python 120m_resampler.py [--symbols PX,TA,PR] [--prefix 120m_scan]

不依赖 strategies/ 包的 import 链（registry→layered_l1l4→broken）。
评分逻辑直接内联自 channel_breakout_strategy.py。
"""

import sys, os, json, shutil, math
from datetime import datetime
from copy import deepcopy

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)

import numpy as np
import pandas as pd

# ── 安全导入（不触发 broken 的 import 链） ──
from config.settings import resolve_param, SYMBOL_CHAIN_MAP, SIGNAL_GRADE_THRESHOLDS
from data.multi_source_adapter import MultiSourceAdapter
from indicators.calc_core import calculate_tdx_compatible

try:
    from strategies.base import SignalResult
except ImportError:
    # 兜底：自建 SignalResult 类
    class SignalResult:
        pass

# ── 全局配置 ──
OUTPUT_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "reports")
COMMODITIES_DIR = r"C:\Users\yangd\Documents\Signal\Commodities"

HOURLY_SYMBOLS = ["PX","PR","V","L","TA","EG","SA","PB","NI","AG",
                  "M","Y","RM","C","SR","CF","JD","AP","FG","OP","LC"]
_BAR_MIN_MAP = {"1m":1,"5m":5,"10m":10,"15m":15,"30m":30,"60m":60,"120m":120,"240m":240,"daily":1440}


def resample_60m_to_120m(df_60m: pd.DataFrame) -> pd.DataFrame:
    """60m→120m合并 — 会话感知: 仅在同一交易时段内合并, 不跨夜盘/午休边界

    交易所默认120m划分规则(以主力品种夜盘23:00收盘为例):
      夜盘:   21:00-23:00 → 60m bar×2 → 合并为1根120m bar
      上午:   9:00-11:30  → 60m bar×2 → 合并为1根120m bar
      下午:   13:30-15:00 → 60m bar×2 → 合并为1根120m bar

    检测方式: 相邻bar时间差>120分钟 → 会话边界 → 不合并
    """
    if df_60m is None or len(df_60m) < 2:
        return pd.DataFrame()
    df = df_60m.copy()
    if "datetime" in df.columns:
        df["_dt"] = pd.to_datetime(df["datetime"])
    elif "date" in df.columns:
        df["_dt"] = pd.to_datetime(df["date"])
    else:
        return pd.DataFrame()
    df = df.sort_values("_dt").reset_index(drop=True)

    # ── 按会话分组: 时间差>120min → 新会话 ──
    sessions = []
    current_session = [0]
    for i in range(1, len(df)):
        gap_min = (df["_dt"].iloc[i] - df["_dt"].iloc[i-1]).total_seconds() / 60
        if gap_min > 120:
            sessions.append(current_session)
            current_session = [i]
        else:
            current_session.append(i)
    sessions.append(current_session)

    # ── 每个会话内两两合并 ──
    bars = []
    for sess_indices in sessions:
        n = len(sess_indices)
        m = (n // 2) * 2
        for j in range(0, m, 2):
            b1 = df.iloc[sess_indices[j]]
            b2 = df.iloc[sess_indices[j+1]]
            bars.append({
                "date": b1["_dt"],
                "open": float(b1["open"]),
                "high": max(float(b1["high"]), float(b2["high"])),
                "low": min(float(b1["low"]), float(b2["low"])),
                "close": float(b2["close"]),
                "volume": float(b1.get("volume", 0)) + float(b2.get("volume", 0)),
                "oi": float(b2.get("oi", b2.get("hold", 0))),
                "settle": float(b2.get("settle", 0)),
            })
        # 会话内单数个bar → 最后一根保留原样
        if n % 2 == 1:
            b = df.iloc[sess_indices[-1]]
            bars.append({
                "date": b["_dt"],
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume", 0)),
                "oi": float(b.get("oi", b.get("hold", 0))),
                "settle": float(b.get("settle", 0)),
            })
    return pd.DataFrame(bars)


# ═══════════════════════════════════════════
# 内联评分逻辑（来自 channel_breakout_strategy.py）
# ═══════════════════════════════════════════
def _get_chain(sym: str) -> str:
    return SYMBOL_CHAIN_MAP.get(sym, "其他")

def score_channel_breakout(tech_list: list, df_map: dict, period: str = "120m") -> dict:
    """通道突破评分（精简版，跳过 window_mode="time" 的复杂缩放）"""
    _r = lambda sec, key, sym="", chain="", per=period: resolve_param(sec, key, sym, chain, per)

    results = []
    for tech in tech_list:
        sym = tech.get("symbol", "")
        chain_name = _get_chain(sym)
        name = tech.get("name", sym)
        price = tech.get("last_price", tech.get("price", 0))
        adx_val = tech.get("ADX14", tech.get("adx", 0))
        atr = tech.get("ATR14", tech.get("atr", 0))
        dc20_pos = tech.get("DC20_POS")
        dc55_pos = tech.get("DC55_POS")
        dc55_trend = tech.get("DC55_TREND", "flat")
        bb_width_pct = tech.get("BB_WIDTH_PCT", 0)
        bb_squeeze = tech.get("BB_SQUEEZE", False)

        dc20_score = 0.0
        dc_detail = {}

        # dc20_break 检测 — TDX对齐: HIGH>=周期高点(上破) / LOW<=周期低点(下破)
        dc20_upper = tech.get("DC20_UPPER")
        dc20_lower = tech.get("DC20_LOWER")
        c_high = tech.get("c_high", price)
        c_low = tech.get("c_low", price)
        dc20_break = "none"
        if dc20_upper and dc20_lower and c_high and c_low:
            if c_high >= dc20_upper:
                dc20_break = "up"
            elif c_low <= dc20_lower:
                dc20_break = "down"

        if dc20_break == "up":
            dc20_score += _r("dc20","break_base_score",sym,chain_name,period)
            dc_detail["dc20_direction"] = "up"
            distance_pct = (price/dc20_upper-1)*100
            if distance_pct > _r("dc20","break_strong_pct",sym,chain_name,period):
                dc20_score += _r("dc20","break_strong_bonus",sym,chain_name,period)
            elif distance_pct > _r("dc20","break_moderate_pct",sym,chain_name,period):
                dc20_score += _r("dc20","break_moderate_bonus",sym,chain_name,period)
            if dc20_pos is not None and dc20_pos > _r("dc20","pos_upper_threshold",sym,chain_name,period):
                dc20_score += _r("dc20","pos_upper_bonus",sym,chain_name,period)
            dc_detail["adx_signal"] = "info_only"
        elif dc20_break == "down":
            dc20_score -= _r("dc20","break_base_score",sym,chain_name,period)
            dc_detail["dc20_direction"] = "down"
            distance_pct = (dc20_lower/price-1)*100
            if distance_pct > _r("dc20","break_strong_pct",sym,chain_name,period):
                dc20_score -= _r("dc20","break_strong_bonus",sym,chain_name,period)
            elif distance_pct > _r("dc20","break_moderate_pct",sym,chain_name,period):
                dc20_score -= _r("dc20","break_moderate_bonus",sym,chain_name,period)
            if dc20_pos is not None and dc20_pos < _r("dc20","pos_lower_threshold",sym,chain_name,period):
                dc20_score += _r("dc20","pos_lower_bonus",sym,chain_name,period)
            dc_detail["adx_signal"] = "info_only"
        else:
            dc_detail["dc20_direction"] = "none"

        dc_detail["dc20_raw_score"] = round(dc20_score, 1)

        # DC55
        dc55_score = 0.0
        if dc55_pos is not None and price:
            pos_thresholds = _r("dc55","pos_thresholds",sym,chain_name,period)
            for pt in pos_thresholds:
                if "min" in pt and dc55_pos > pt["min"]:
                    dc55_score += pt["score"]
                    break
                if "max" in pt and dc55_pos < pt["max"]:
                    dc55_score += pt["score"]
                    break
        # DC55 trend alignment
        if dc55_trend in ("up","down"):
            dc55_score += _r("dc55","trend_base_score",sym,chain_name,period)
            dc_detail["dc55_aligned"] = True

        # BB
        bb_score = 0.0
        bb_pos = tech.get("BB_POS")
        if bb_width_pct:
            if bb_width_pct > _r("bb","width_high_threshold",sym,chain_name,period):
                bb_score += _r("bb","width_high_score",sym,chain_name,period)
            elif bb_width_pct > _r("bb","width_moderate_threshold",sym,chain_name,period):
                bb_score += _r("bb","width_moderate_score",sym,chain_name,period)
        if bb_squeeze:
            bb_score += _r("bb","squeeze_bonus",sym,chain_name,period)

        # Volume
        vol_score = 0.0
        vol_ratio = tech.get("vol_ratio", 1.0)
        if vol_ratio > _r("volume","explosive_ratio",sym,chain_name,period):
            vol_score += _r("volume","explosive_score",sym,chain_name,period)
        elif vol_ratio > _r("volume","elevated_ratio",sym,chain_name,period):
            vol_score += _r("volume","elevated_score",sym,chain_name,period)
        elif vol_ratio < _r("volume","normal_lower_ratio",sym,chain_name,period):
            vol_score += _r("volume","weak_penalty",sym,chain_name,period)

        # 方向判定
        total = dc20_score + dc55_score + bb_score + vol_score
        direction = "bull" if total > 0 else ("bear" if total < 0 else "neutral")
        abs_total = abs(total)
        # 等级
        if abs_total >= SIGNAL_GRADE_THRESHOLDS["strong"]:
            grade = "STRONG"
        elif abs_total >= SIGNAL_GRADE_THRESHOLDS["watch"]:
            grade = "WATCH"
        elif abs_total >= SIGNAL_GRADE_THRESHOLDS["weak"]:
            grade = "WEAK"
        else:
            grade = "NOISE"

        # 信号类型
        _dc_total = dc20_score + dc55_score
        sig_type = "channel_breakout" if dc20_break != "none" and abs(_dc_total) >= 20 else "trend_confirmation"

        result = {
            "symbol": sym, "name": name,
            "price": round(price, 1), "total": round(total),
            "abs": round(abs_total), "direction": direction, "grade": grade,
            "adx": round(adx_val, 1) if adx_val else 0,
            "rsi": round(tech.get("RSI14", tech.get("rsi", 50)), 1),
            "dc20": round(dc20_score), "dc55": round(dc55_score),
            "bb": round(bb_score), "vol_score": round(vol_score),
            "signal_type": sig_type,
            "atr": round(atr, 1) if atr else 0,
            "dc20_break": dc20_break,
            "ma_align": tech.get("ma_align", "mixed"),
            "macd_cross": tech.get("macd_cross", "none"),
        }
        results.append(result)

    results.sort(key=lambda x: abs(x["total"]), reverse=True)
    return {"all_ranked": results}


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════
def run_120m_scan(symbols: list = None, output_prefix: str = "120m_scan") -> dict:
    if symbols is None:
        symbols = [(s, "") for s in HOURLY_SYMBOLS]

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")
    timestamp = now.strftime("%Y%m%d_%H%M")

    print(f"\n{'='*55}")
    print(f"  120m扫描（60m重采样）— {date_str}")
    print(f"  品种: {len(symbols)}")
    print(f"{'='*55}")

    adapter = MultiSourceAdapter()
    tech_list = []
    df_map = {}

    for sym, name in symbols:
        if not name:
            from config.symbols import ALL_SYMBOLS as _S
            for s, n in _S:
                if s == sym: name = n; break
            if not name: name = sym

        print(f"  [{sym}] 获取60m K线...", end="")
        result = adapter.get_kline(sym, days=90, period="60m")
        if not result or not result.get("success"):
            print(" ❌")
            continue
        raw = result.get("data", [])
        if len(raw) < 20:
            print(f" ⚠ 仅{len(raw)}条")
            continue

        df_60m = pd.DataFrame(raw)
        if "date" not in df_60m.columns:
            print(" ⚠ 无date")
            continue
        df_60m["date"] = pd.to_datetime(df_60m["date"], errors="coerce")
        df_60m = df_60m.dropna(subset=["date"])
        df_60m = df_60m.sort_values("date").reset_index(drop=True)

        df_120m = resample_60m_to_120m(df_60m)
        if len(df_120m) < 30:
            print(f" ⚠ 重采样后仅{len(df_120m)}条")
            continue

        closes = df_120m["close"].values.astype(float)
        highs = df_120m["high"].values.astype(float)
        lows = df_120m["low"].values.astype(float)
        volumes = df_120m["volume"].values.astype(float) if "volume" in df_120m.columns else None

        # DC通道 — TDX对齐: REF(HHV, N) 不含当前bar
        dc20_upper = float(np.max(highs[-21:-1])) if len(highs) >= 21 else (float(np.max(highs[-20:])) if len(highs) >= 20 else 0)
        dc20_lower = float(np.min(lows[-21:-1])) if len(lows) >= 21 else (float(np.min(lows[-20:])) if len(lows) >= 20 else 0)
        dc55_upper = float(np.max(highs[-55:])) if len(highs) >= 55 else 0
        dc55_lower = float(np.min(lows[-55:])) if len(lows) >= 55 else 0
        half = min(28, len(closes)//2)
        mid_first = float(np.max(highs[-55:-half]) + np.min(lows[-55:-half]))/2 if half > 0 else (dc55_upper+dc55_lower)/2
        mid_last = float(np.max(highs[-half:]) + np.min(lows[-half:]))/2 if half > 0 else (dc55_upper+dc55_lower)/2

        tech = {
            "symbol": sym, "name": name,
            "last_price": float(closes[-1]), "price": float(closes[-1]),
            "c_high": float(highs[-1]), "c_low": float(lows[-1]),
            "change_pct": (closes[-1]/closes[-2]-1)*100 if len(closes)>1 else 0,
            "volume": int(volumes[-1]) if volumes is not None else 0,
            "DC20_UPPER": dc20_upper, "DC20_LOWER": dc20_lower,
            "DC20_POS": (closes[-1]-dc20_lower)/(dc20_upper-dc20_lower+1e-10) if dc20_upper>0 else 0.5,
            "DC55_UPPER": dc55_upper, "DC55_LOWER": dc55_lower,
            "DC55_POS": (closes[-1]-dc55_lower)/(dc55_upper-dc55_lower+1e-10) if dc55_upper>0 else 0.5,
            "DC55_TREND": "up" if mid_last > mid_first else "down",
        }

        # calc_core
        try:
            ind = calculate_tdx_compatible(
                high=highs, low=lows, close=closes,
                open_price=df_120m["open"].values.astype(float),
                volume=volumes,
            )
            tech.update(ind)
        except Exception as e:
            print(f"  ⚠ 指标: {e}")

        # vol_ratio
        avg_vol = float(np.mean(volumes[-20:])) if volumes is not None and len(volumes) >= 20 else 1
        tech["vol_ratio"] = volumes[-1]/avg_vol if avg_vol > 0 else 1.0

        tech_list.append(tech)
        df_map[sym] = df_120m
        print(f" ✅ {len(df_120m)} bars")

    if not tech_list:
        print("\n  ⚠ 无有效品种")
        return {"all_ranked": [], "total": 0, "strong": 0, "watch": 0}

    print(f"\n  [评分] {len(tech_list)}品种...")
    score_result = score_channel_breakout(tech_list, df_map, period="120m")
    all_ranked = score_result.get("all_ranked", [])
    strong = [s for s in all_ranked if s.get("grade") == "STRONG"]
    watch = [s for s in all_ranked if s.get("grade") == "WATCH"]

    result = {
        "all_ranked": all_ranked, "total": len(all_ranked),
        "strong": len(strong), "watch": len(watch), "timestamp": timestamp,
    }

    # 输出
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(COMMODITIES_DIR, exist_ok=True)

    json_path = os.path.join(OUTPUT_DIR, f"{output_prefix}_{timestamp}_{now.strftime('%Y%m%d')}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📊 JSON: {json_path}")

    # HTML
    rows = ""
    for s in all_ranked:
        dir_icon = "🟢" if s["direction"] == "bull" else ("🔴" if s["direction"] == "bear" else "⚪")
        rows += f"<tr><td>{s['symbol']}</td><td>{dir_icon} {s['direction']}</td><td>{s['total']}</td><td>{s['grade']}</td><td>{s['adx']:.1f}</td><td>{s['rsi']:.0f}</td><td>{s['dc20']}</td><td>{s['dc55']}</td><td>{s['bb']}</td><td>{s['vol_score']}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>120m扫描(60m重采样) — {date_str}</title>
<style>
body{{font-family:'Segoe UI',sans-serif;padding:20px;background:#f5f5f5;}}
h1{{font-size:18px;color:#333;}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;}}
th{{background:#f8f9fa;padding:8px 10px;text-align:left;font-size:12px;color:#666;border-bottom:2px solid #eee;}}
td{{padding:8px 10px;font-size:13px;border-bottom:1px solid #f0f0f0;}}
.info{{font-size:12px;color:#999;margin:10px 0;}}
</style></head><body>
<h1>📊 120m通道突破扫描（60m重采样）</h1>
<div class="info">{date_str} | 品种{len(all_ranked)}个 | STRONG={len(strong)} WATCH={len(watch)}</div>
<table>
<tr><th>品种</th><th>方向</th><th>总分</th><th>等级</th><th>ADX</th><th>RSI</th><th>DC20</th><th>DC55</th><th>BB</th><th>Vol</th></tr>
{rows}
</table>
<div class="info">数据: 通达信TQ-Local(60m) → 重采样120m | per_period[120m].[volume]已配置</div>
</body></html>"""
    html_path = os.path.join(OUTPUT_DIR, f"{output_prefix}_{timestamp}_ranking_{now.strftime('%Y%m%d')}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    latest = os.path.join(COMMODITIES_DIR, "120m_scan_latest.html")
    shutil.copy2(html_path, latest)
    print(f"  [OK] HTML: {html_path}")
    print(f"  同步: {latest}")
    print(f"\n  STRONG={result['strong']}  WATCH={result['watch']}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default="")
    parser.add_argument("--prefix", type=str, default="120m_scan")
    args = parser.parse_args()
    syms = [(s.strip(),"") for s in args.symbols.split(",")] if args.symbols else [(s,"") for s in HOURLY_SYMBOLS]
    r = run_120m_scan(syms, args.prefix)
    if r["total"] > 0:
        print(f"\n【结果】共{r['total']}品种, STRONG={r['strong']} WATCH={r['watch']}")
    else:
        print("\n【结果】无有效数据")
