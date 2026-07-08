#!/usr/bin/env python3
"""
目标品种量化分析脚本
数据采集 → 指标计算 → L1-L4信号评分

用法:
  python analyze_targets.py                          # 默认: PK,RB,B,UR
  python analyze_targets.py --symbols PK,RB,B,UR     # 指定品种
  python analyze_targets.py --symbols SA,RB,FU       # 自定义
"""

import sys, os, json, math
from datetime import date, datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from data.multi_source_adapter import MultiSourceAdapter
from indicators.core import assess_trend_maturity
from signals.scoring_system import calculate_composite_score
from config.symbols import ALL_SYMBOLS, SYMBOL_DETAILS

try:
    from indicators.indicators_legacy import _compute_indicators_numpy
except ImportError:
    from indicators.calc_core import calculate_tdx_compatible as _compute_indicators_numpy

import pandas as pd
import numpy as np

# ── CLI 参数 ──
import argparse

parser = argparse.ArgumentParser(description="目标品种量化分析")
parser.add_argument("--symbols", "-s", help="品种代码(逗号分隔)，如: PK,RB,B,UR", default="PK,RB,B,UR")
args = parser.parse_args()

# 构建目标品种列表
raw_pids = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
# 从 ALL_SYMBOLS 查找名称
SYMBOL_NAME_MAP = dict(ALL_SYMBOLS)  # {'rb':'螺纹钢', 'sc':'原油', ...}
TARGETS = []
TARGET_NAMES = {}
for pid in raw_pids:
    # 尝试精确匹配
    if pid in SYMBOL_NAME_MAP:
        TARGETS.append(pid)
        TARGET_NAMES[pid] = SYMBOL_NAME_MAP[pid]
    elif pid.lower() in SYMBOL_NAME_MAP:
        TARGETS.append(pid)
        TARGET_NAMES[pid] = SYMBOL_NAME_MAP[pid.lower()]
    else:
        TARGET_NAMES[pid] = pid
        TARGETS.append(pid)

if not TARGETS:
    print("[x] 未指定有效品种")
    sys.exit(1)

today = date.today()
today_str = today.strftime("%Y%m%d")

print(f"{'=' * 60}")
print(f"目标品种量化分析 — {today}")
print(f"品种: {' '.join([f'{s}({TARGET_NAMES[s]})' for s in TARGETS])}")
print(f"{'=' * 60}")

# ── Step 1: 数据采集 ──
print("\n[1] 数据采集（MultiSourceAdapter）...")
adapter = MultiSourceAdapter()

kline_data = {}
for sym in TARGETS:
    try:
        resp = adapter.get_kline(variety=sym, days=120)
        if isinstance(resp, dict) and resp.get("success"):
            dlist = resp["data"]
            valid = [r for r in dlist if r.get("date", "") and r.get("volume", 0) > 0 and r["date"] <= today_str]
            if len(valid) >= 50:
                kline_data[sym] = valid
                print(f"  [OK] {sym} ({TARGET_NAMES[sym]}): {len(valid)} bars")
            else:
                print(f"  [!] {sym}: only {len(valid)} valid bars (need ≥50)")
        else:
            print(f"  [x] {sym}: data fetch failed - {resp}")
    except Exception as e:
        print(f"  [x] {sym}: {e}")

print(f"  成功采集: {len(kline_data)}/{len(TARGETS)}")

# ── Step 2: 指标计算 + L1-L4评分 ──
print("\n[2] 指标计算 + L1-L4评分...")

results = {}
detailed = {}

for sym in TARGETS:
    if sym not in kline_data:
        print(f"  ⏭️ {sym}: 跳过（无数据）")
        continue

    try:
        dlist = kline_data[sym]
        df = pd.DataFrame(
            {
                "open": [float(r["open"]) for r in dlist],
                "high": [float(r["high"]) for r in dlist],
                "low": [float(r["low"]) for r in dlist],
                "close": [float(r["close"]) for r in dlist],
                "volume": [float(r.get("volume", 0)) for r in dlist],
            }
        )

        # ── 计算技术指标 ──
        # Use calc_core's calculate_tdx_compatible for full 45-field output
        from indicators.calc_core import (
            calculate_adx,
            calculate_rsi,
            calculate_cci,
            calculate_macd,
            calculate_ma as _sma_numpy,
            calculate_ema as _ema_numpy,
            calculate_bollinger_bands,
            calculate_donchian,
            calculate_donchian_trend,
            calculate_vortex,
            calculate_hma,
            calculate_cmf,
            calculate_obv,
            calculate_atr,
            calculate_ma_slope,
            calculate_bb_squeeze,
            calculate_bb_pctb,
            calculate_supertrend,
            calculate_bb_width,
            calculate_williams_r,
            calculate_roc,
            calculate_stoch,
            detect_higher_high_lower_low,
            detect_volume_price_divergence,
            calculate_kama,
        )

        c = df["close"].values.astype(np.float64)
        h = df["high"].values.astype(np.float64)
        l = df["low"].values.astype(np.float64)
        o = df["open"].values.astype(np.float64)
        v = df["volume"].values.astype(np.float64)

        n = len(c)

        # MA values
        ma5 = _sma_numpy(c, 5)
        ma10 = _sma_numpy(c, 10)
        ma20 = _sma_numpy(c, 20)
        ma40 = _sma_numpy(c, 40)

        # RSI
        rsi_arr = calculate_rsi(c, 14)

        # CCI
        cci_arr = calculate_cci(h, l, c, 20)

        # MACD
        macd_dif, macd_dea, macd_hist = calculate_macd(c, 12, 26, 9)

        # ADX/DMI
        adx_arr, pdi_arr, mdi_arr = calculate_adx(h, l, c, 14)

        # Bollinger Bands
        bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(c, 20, 2)

        # Donchian Channels
        dc20_u, dc20_m, dc20_l = calculate_donchian(h, l, 20)
        dc55_u, dc55_m, dc55_l = calculate_donchian(h, l, 55)
        dc55_trend = calculate_donchian_trend(h, 55)

        # Vortex
        vi_plus, vi_minus = calculate_vortex(h, l, c, 14)

        # HMA
        hma10 = calculate_hma(c, 10)
        hma20 = calculate_hma(c, 20)

        # SuperTrend
        st, st_dir = calculate_supertrend(h, l, c, 10, 3.0)

        # ATR
        atr_arr = calculate_atr(h, l, c, 14)

        # MA Slope
        ma20_slope = calculate_ma_slope(c, 20)

        # BB metrics
        bbw = calculate_bb_width(c, 20)
        bbpctb = calculate_bb_pctb(c, 20)
        bbsq = calculate_bb_squeeze(c, 20)

        # Volume / OBV / CMF
        obv = calculate_obv(c, v)
        obv_ma20 = _sma_numpy(obv, 20)
        cmf21 = calculate_cmf(h, l, c, v, 21)

        # ROC
        roc10 = calculate_roc(c, 10)

        # Williams %R
        wr14 = calculate_williams_r(h, l, c, 14)

        # KDJ
        k_val, d_val = calculate_stoch(h, l, c, 9, 3)

        # Volume ratios
        vol_ma5 = _sma_numpy(v, 5)
        vol_ma20 = _sma_numpy(v, 20)

        # HH/HL pattern
        hhc, hlc, hl_pattern = detect_higher_high_lower_low(h, l)

        # Vol price divergence
        vpd = detect_volume_price_divergence(c, v, 14)

        # KAMA
        kama = calculate_kama(c, 10)

        # ── Get latest values ──
        def safe_latest(arr, min_len=1):
            if len(arr) >= min_len and not np.isnan(arr[-1]):
                return float(arr[-1])
            return None

        def safe_bool(arr, min_len=1):
            if len(arr) >= min_len:
                return bool(arr[-1])
            return None

        last_price = float(c[-1])

        # Assemble tech dict for scoring
        tech = {
            "last_price": last_price,
            "MA5": safe_latest(ma5),
            "MA10": safe_latest(ma10),
            "MA20": safe_latest(ma20),
            "MA40": safe_latest(ma40),
            "RSI14": safe_latest(rsi_arr, 14),
            "CCI20": safe_latest(cci_arr, 20),
            "MACD_DIF": safe_latest(macd_dif),
            "MACD_DEA": safe_latest(macd_dea),
            "MACD_HIST": safe_latest(macd_hist),
            "ADX": safe_latest(adx_arr, 14),
            "DMI_PDI": safe_latest(pdi_arr, 14),
            "DMI_MDI": safe_latest(mdi_arr, 14),
            "BB_UPPER": safe_latest(bb_upper, 20),
            "BB_MIDDLE": safe_latest(bb_mid, 20),
            "BB_LOWER": safe_latest(bb_lower, 20),
            "BB_SQUEEZE": safe_bool(bbsq, 40),
            "BB_WIDTH_PCT": safe_latest(bbw, 20),
            "BB_PCTB": safe_latest(bbpctb, 20),
            "DC_UPPER": safe_latest(dc20_u, 20),
            "DC_MID": safe_latest(dc20_m, 20),
            "DC_LOWER": safe_latest(dc20_l, 20),
            "DC55_UPPER": safe_latest(dc55_u, 55),
            "DC55_MID": safe_latest(dc55_m, 55),
            "DC55_LOWER": safe_latest(dc55_l, 55),
            "DC55_TREND": dc55_trend,
            "VI_PLUS": safe_latest(vi_plus, 14),
            "VI_MINUS": safe_latest(vi_minus, 14),
            "HMA10": safe_latest(hma10, 10),
            "HMA20": safe_latest(hma20, 20),
            "SUPERTREND_DIR": safe_latest(st_dir, 10),
            "ATR": safe_latest(atr_arr, 14),
            "MA20_SLOPE": safe_latest(ma20_slope, 25),
            "OBV": safe_latest(obv),
            "OBV_MA20": safe_latest(obv_ma20, 20),
            "CMF21": safe_latest(cmf21, 21),
            "ROC10": safe_latest(roc10, 10),
            "WR14": safe_latest(wr14, 14),
            "STOCH_K": safe_latest(k_val, 9),
            "STOCH_D": safe_latest(d_val, 9),
            "VOL_MA5": safe_latest(vol_ma5, 5),
            "VOL_MA20": safe_latest(vol_ma20, 20),
            "KAMA": safe_latest(kama, 10),
            "_hl_pattern": hl_pattern,
            "_vpd": int(vpd[-1]) if len(vpd) > 0 else 0,
            "_hhc": hhc,
            "_hlc": hlc,
        }

        # Compute OI_RATE from volume (as proxy)
        if safe_latest(vol_ma20, 20) and safe_latest(v):
            tech["OI_RATE"] = float(v[-1]) / float(vol_ma20[-1])
            tech["OI_CHANGE_PCT"] = (float(v[-1]) / float(v[-2]) - 1) * 100 if len(v) > 1 else 0
        else:
            tech["OI_RATE"] = None
            tech["OI_CHANGE_PCT"] = None

        # PRICE_CHANGE_5D
        if n >= 5:
            tech["PRICE_CHANGE_5D"] = (float(c[-1]) / float(c[-5]) - 1) * 100
        else:
            tech["PRICE_CHANGE_5D"] = 0

        # VOL_RATIO
        if safe_latest(vol_ma5, 5) and safe_latest(vol_ma20, 20):
            tech["VOL_RATIO"] = float(vol_ma5[-1]) / float(vol_ma20[-1]) if float(vol_ma20[-1]) > 0 else 1.0
        else:
            tech["VOL_RATIO"] = 1.0

        # Higher Low / Lower High detection
        if n >= 20:
            mid = n // 2
            low1, low2 = float(min(c[:mid])), float(min(c[mid:]))
            high1, high2 = float(max(c[:mid])), float(max(c[mid:]))
            tech["HIGHER_LOW"] = low2 > low1 * 1.003
            tech["LOWER_HIGH"] = high2 < high1 * 0.997
        else:
            tech["HIGHER_LOW"] = False
            tech["LOWER_HIGH"] = False

        # VOL_PRICE_DIVERGENCE
        tech["VOL_PRICE_DIVERGENCE"] = abs(tech.get("PRICE_CHANGE_5D", 0)) < 3.0 and tech.get("VOL_RATIO", 1.0) >= 1.2

        # VOL_5D_RATIO
        if safe_latest(vol_ma5, 5) and safe_latest(vol_ma20, 20):
            tech["VOL_5D_RATIO"] = float(vol_ma5[-1]) / float(vol_ma20[-1]) if float(vol_ma20[-1]) > 0 else 1.0
        else:
            tech["VOL_5D_RATIO"] = 1.0

        # NEW_HIGH_60 / NEW_LOW_60
        if n >= 60:
            tech["NEW_HIGH_60"] = float(c[-1]) >= float(max(c[-60:]))
            tech["NEW_LOW_60"] = float(c[-1]) <= float(min(c[-60:]))
        else:
            lookback = min(n, 30)
            tech["NEW_HIGH_60"] = float(c[-1]) >= float(max(c[-lookback:]))
            tech["NEW_LOW_60"] = float(c[-1]) <= float(min(c[-lookback:]))

        # MACD cross
        if len(macd_dif) >= 2 and len(macd_dea) >= 2:
            prev_dif = float(macd_dif[-2])
            prev_dea = float(macd_dea[-2])
            curr_dif = float(macd_dif[-1])
            curr_dea = float(macd_dea[-1])
            if prev_dif < prev_dea and curr_dif >= curr_dea:
                tech["macd_cross"] = "golden"
            elif prev_dif > prev_dea and curr_dif <= curr_dea:
                tech["macd_cross"] = "death"
            else:
                tech["macd_cross"] = "none"
        else:
            tech["macd_cross"] = "none"

        # DC break
        if dc20_u is not None and dc20_l is not None and last_price:
            u_val, l_val = float(dc20_u[-1]), float(dc20_l[-1])
            if last_price > u_val:
                tech["dc20_break"] = "up"
            elif last_price < l_val:
                tech["dc20_break"] = "down"
            else:
                tech["dc20_break"] = "none"
        else:
            tech["dc20_break"] = "none"

        # MA align
        if ma5 is not None and ma10 is not None and ma20 is not None:
            ma5_v, ma10_v, ma20_v = float(ma5[-1]), float(ma10[-1]), float(ma20[-1])
            if ma5_v > ma10_v > ma20_v:
                tech["ma_align"] = "bull"
            elif ma5_v < ma10_v < ma20_v:
                tech["ma_align"] = "bear"
            else:
                tech["ma_align"] = "mixed"
        else:
            tech["ma_align"] = "mixed"

        tech["_tdx_patched"] = False

        # ── Calculate composite score ──
        sym_data = {"last_price": last_price, "open_interest": float(v[-1])}
        kline_closes = c.tolist()

        sc = calculate_composite_score(tech, sym_data, 0, kline_closes, None)

        direction = "bull" if sc["direction"] == "BUY" else ("bear" if sc["direction"] == "SELL" else "neutral")
        s = 1 if direction == "bull" else (-1 if direction == "bear" else 0)
        stage = sc["maturity"]["stage"]

        # ── Compute layer agreement ──
        l1_signed = sc["L1_score"] * s
        l2_signed = sc["L2_score"] * s
        l3_signed = sc["L3_score"] * s
        l4_signed = sc["L4_score"] * s

        layers = [l1_signed, l2_signed, l3_signed, l4_signed]
        cons = sum(1 for l in layers if (l > 0 and s > 0) or (l < 0 and s < 0))

        # ── Compute total signed score ──
        total = sc["total"] * s if s != 0 else -sc["total"]  # preserve sign

        # Grade
        abs_total = abs(total)
        if abs_total >= 75:
            grade = "STRONG"
        elif abs_total >= 60:
            grade = "WATCH"
        elif abs_total >= 40:
            grade = "WEAK"
        else:
            grade = "NOISE"

        # ── Layer disagreement warnings ──
        layer_warnings = []
        layer_signs = [1 if l > 0 else (-1 if l < 0 else 0) for l in [l1_signed, l2_signed, l3_signed, l4_signed]]
        for i in range(4):
            for j in range(i + 1, 4):
                if layer_signs[i] * layer_signs[j] < 0:
                    layer_warnings.append(f"L{i + 1} vs L{j + 1}方向矛盾")

        # ── Key support/resistance levels ──
        support = last_price * 0.97  # 3% below
        resistance = last_price * 1.03  # 3% above

        if dc20_l is not None and safe_latest(dc20_l, 20):
            support = min(support, float(dc20_l[-1]))
        if dc20_u is not None and safe_latest(dc20_u, 20):
            resistance = max(resistance, float(dc20_u[-1]))

        # ── Veto check ──
        veto_pass = sc["veto_score"] >= -5  # mild veto is ok, severe veto fails

        # ── Assemble result ──
        result_entry = {
            "symbol": sym,
            "name": TARGET_NAMES[sym],
            "price": round(last_price, 1),
            "change_pct": round((float(c[-1]) / float(c[-2]) - 1) * 100, 2) if n > 1 else 0,
            "total": total,
            "abs": sc["total"],
            "l1": l1_signed,
            "l2": l2_signed,
            "l3": l3_signed,
            "l4": l4_signed,
            "veto": sc["veto_score"],
            "direction": direction,
            "grade": grade,
            "adx": round(float(adx_arr[-1]), 1) if len(adx_arr) >= 14 and not np.isnan(adx_arr[-1]) else 0,
            "rsi": round(float(rsi_arr[-1]), 1) if len(rsi_arr) >= 14 and not np.isnan(rsi_arr[-1]) else 0,
            "cci": round(float(cci_arr[-1]), 1) if len(cci_arr) >= 20 and not np.isnan(cci_arr[-1]) else 0,
            "ma_slope": round(float(ma20_slope[-1]), 4) if not np.isnan(ma20_slope[-1]) else 0,
            "macd_cross": tech.get("macd_cross", "none"),
            "dc20_break": tech.get("dc20_break", "none"),
            "ma_align": tech.get("ma_align", "mixed"),
            "stage": stage,
            "cons": f"{cons}/4",
            "layer_warnings": layer_warnings,
            "veto_pass": veto_pass,
            "support": round(support, 1),
            "resistance": round(resistance, 1),
            "notes": [],
        }

        # Build notes
        notes = []
        if sc["reasons"]:
            for r in sc["reasons"][:8]:
                notes.append(r)
        if layer_warnings:
            notes.append(f"[!] 层间矛盾: {'; '.join(layer_warnings)}")
        if not veto_pass:
            notes.append(f"[x] 否决项触发(veto={sc['veto_score']})")
        else:
            notes.append(f"[OK] 否决项通过(veto={sc['veto_score']})")

        notes.append(f"ADX={result_entry['adx']} | RSI={result_entry['rsi']} | CCI={result_entry['cci']}")
        notes.append(f"MA排列: {result_entry['ma_align']} | DC: {result_entry['dc20_break']}")
        notes.append(f"趋势阶段: {stage} | 等级: {grade}")
        result_entry["notes"] = notes

        results[sym] = result_entry
        detailed[sym] = {
            "tech": {k: v for k, v in tech.items() if not k.startswith("_") and v is not None},
            "scoring": {
                "total": sc["total"],
                "direction": direction,
                "grade": grade,
                "stage": stage,
                "L1_score": sc["L1_score"],
                "L2_score": sc["L2_score"],
                "L3_score": sc["L3_score"],
                "L4_score": sc["L4_score"],
                "veto_score": sc["veto_score"],
                "reasons": sc["reasons"],
            },
            "dimensions": {
                "L1": {
                    "score": sc["dimensions"]["L1_germination"]["score"],
                    "raw": sc["dimensions"]["L1_germination"]["raw_score"],
                    "reasons": sc["dimensions"]["L1_germination"]["reasons"],
                },
                "L2": {
                    "score": sc["dimensions"]["L2_volume_price"]["score"],
                    "raw": sc["dimensions"]["L2_volume_price"]["raw_score"],
                    "reasons": sc["dimensions"]["L2_volume_price"]["reasons"],
                },
                "L3": {
                    "score": sc["dimensions"]["L3_structure"]["score"],
                    "raw": sc["dimensions"]["L3_structure"]["raw_score"],
                    "reasons": sc["dimensions"]["L3_structure"]["reasons"],
                },
                "L4": {
                    "score": sc["dimensions"]["L4_confirmation"]["score"],
                    "raw": sc["dimensions"]["L4_confirmation"]["raw_score"],
                    "reasons": sc["dimensions"]["L4_confirmation"]["reasons"],
                },
                "veto": {"score": sc["dimensions"]["veto"]["score"], "reasons": sc["dimensions"]["veto"]["reasons"]},
            },
        }

        print(f"  [OK] {sym} ({TARGET_NAMES[sym]}): {direction} | 总分{total:.0f} | {grade} | {stage}")

    except Exception as e:
        import traceback

        print(f"  [x] {sym}: 分析失败 - {e}")
        traceback.print_exc()
        continue

# ── Output ──
print(f"\n{'=' * 60}")
print(f"分析完成: {len(results)}/{len(TARGETS)}品种")
print(f"{'=' * 60}")

# Print summary table
print(
    f"\n{'品种':<6} {'方向':<6} {'价格':>8} {'涨跌':>6} {'总分':>5} {'L1':>4} {'L2':>4} {'L3':>4} {'L4':>4} {'否决':>4} {'ADX':>5} {'RSI':>5} {'阶段':>10} {'等级':>6}"
)
print("-" * 80)
for sym in TARGETS:
    if sym not in results:
        continue
    r = results[sym]
    d = "多头" if r["direction"] == "bull" else ("空头" if r["direction"] == "bear" else "中性")
    chg_str = f"{r['change_pct']:>+5.1f}%"
    print(
        f"{sym:<6} {d:<6} {r['price']:>8.0f} {chg_str:>6} {r['total']:>+4.0f} {r['l1']:>+3} {r['l2']:>+3} {r['l3']:>+3} {r['l4']:>+3} {r['veto']:>+3} {r['adx']:>5.1f} {r['rsi']:>5.1f} {r['stage']:>10} {r['grade']:>6}"
    )

# ── Build JSON output ──
verdict_map = {"bull": "多头上涨", "bear": "空头下跌", "neutral": "中性震荡"}
confidence_map = {
    "STRONG": "高",
    "WATCH": "中",
    "WEAK": "低",
    "NOISE": "低",
}

output = {
    "variant": "tech_analysis",
    "contracts": TARGETS,
    "key_prices": {},
    "verdicts": {},
    "trend_stages": {},
    "confidence": {},
    "veto_status": {},
    "key_levels": {},
    "all_actionable": [],
    "notes": {},
}

for sym in TARGETS:
    if sym not in results:
        continue
    r = results[sym]
    output["key_prices"][sym] = r["price"]
    output["verdicts"][sym] = verdict_map.get(r["direction"], "中性")
    output["trend_stages"][sym] = r["stage"]
    output["confidence"][sym] = confidence_map.get(r["grade"], "低")
    output["veto_status"][sym] = "pass" if r["veto_pass"] else "fail"
    output["key_levels"][sym] = {"支撑": r["support"], "阻力": r["resistance"]}
    output["all_actionable"].append(
        {
            "symbol": sym,
            "L1": r["l1"],
            "L2": r["l2"],
            "L3": r["l3"],
            "L4": r["l4"],
            "total": round(r["total"], 0),
            "direction": r["direction"],
            "trend_stage": r["stage"],
            "grade": r["grade"],
            "cons": r["cons"],
        }
    )
    output["notes"][sym] = r["notes"]

print("\n\n=== 结构化JSON输出 ===")
print(json.dumps(output, ensure_ascii=False, indent=2))

# Save to file
output_dir = os.path.join(SKILL_DIR, "reports")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, f"target_analysis_{today_str}.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n[OK] 输出已保存: {output_path}")
