"""遗留 numpy 指标计算（已收编至 FDC，单一真相源）。

原 quant-daily/scripts/indicators/indicators_legacy.py 的 ``_compute_indicators_numpy`` 与其辅助函数 ``safe_float``。
指标层零逻辑变更；内部懒加载 ``from indicators.tdx_bridge import get_bridge`` 保持不变。
"""

from typing import Optional


def safe_float(val) -> Optional[float]:
    """安全转换为float。"""
    try:
        import pandas as pd

        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None


def _compute_indicators_numpy(klines, symbol: str = None, period: str = "daily") -> dict:
    """Fallback: numpy/pandas 计算全部技术指标（不依赖 tqsdk.ta）。

    RSI/ADX/ATR 使用通达信Wilder平滑（SMA(X,N,1)），与通达信公式一致。

    如传入symbol且TQ-Local可用，会用通达信实盘指标覆盖DMI/RSI/CCI/MACD。
    🐛 v2.9.1: 当period!="daily"时跳过桥接，避免日线值覆盖子周期数据。

    接受: DataFrame with columns [open,high,low,close,volume] 或 dict of arrays
    """
    import pandas as pd, numpy as np

    if isinstance(klines, dict):
        df = pd.DataFrame(klines)
    else:
        df = klines if hasattr(klines, "columns") else pd.DataFrame(klines)

    # Normalize Chinese column names to English
    cn_to_en = {
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "持仓量": "open_interest",
        "日期": "date",
    }
    df = df.rename(columns={k: v for k, v in cn_to_en.items() if k in df.columns})
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    v = df.get("volume", np.zeros_like(c))
    if hasattr(v, "values"):
        v = v.values.astype(float)

    tech = {}
    n = len(c)
    if n < 60:
        return tech

    # ---- helpers ----
    def sma(x, p):
        return pd.Series(x).rolling(p).mean().values

    def wilder_rma(x, p):
        """Wilder平滑（通达信SMA(X,N,1)）: alpha=1/p, 用于RSI/ADX/ATR"""
        out = np.zeros_like(x)
        out[p - 1] = np.mean(x[:p])
        for i in range(p, len(x)):
            out[i] = (x[i] + (p - 1) * out[i - 1]) / p
        return out

    def ema(x, p):
        a = 2 / (p + 1)
        e = np.zeros_like(x)
        e[0] = x[0]
        for i in range(1, len(x)):
            e[i] = a * x[i] + (1 - a) * e[i - 1]
        return e

    def sd(x, p):
        return pd.Series(x).rolling(p).std().values

    def md(x, p):
        return pd.Series(x).rolling(p).apply(lambda v: np.mean(np.abs(v - np.mean(v))), raw=True).values

    def max_(x, p):
        return pd.Series(x).rolling(p).max().values

    def min_(x, p):
        return pd.Series(x).rolling(p).min().values

    def atr_fn(p=14):
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        return wilder_rma(tr, p)

    # ---- MA ----
    for p in [5, 10, 20, 40, 60, 120]:
        tech[f"MA{p}"] = float(sma(c, p)[-1])

    # MA20_SLOPE (linear regression on last 5 days of MA20)
    ma20_series = sma(c, 20)
    t = np.arange(5)
    slope, _ = np.polyfit(t, ma20_series[-5:], 1) if n >= 25 else (0, 0)
    tech["MA20_SLOPE"] = float(slope)

    # ---- MACD ----
    e12 = ema(c, 12)
    e26 = ema(c, 26)
    dif = e12 - e26
    dea = ema(dif, 9)
    tech["MACD_DIF"] = float(dif[-1])
    tech["MACD_DEA"] = float(dea[-1])

    # ---- RSI14 (通达信Wilder平滑) ----
    d = np.diff(c, prepend=c[0])
    g = np.clip(d, 0, None)
    ls = np.clip(-d, 0, None)
    ag = wilder_rma(g, 14)
    al = wilder_rma(ls, 14)
    tech["RSI14"] = float(100 - 100 / (1 + ag[-1] / al[-1])) if al[-1] > 0 else 100.0

    # ---- CCI20 ----
    tp = (h + l + c) / 3
    tp_ma = sma(tp, 20)
    tp_md_ = md(tp, 20)
    tech["CCI20"] = float((tp[-1] - tp_ma[-1]) / (0.015 * tp_md_[-1])) if tp_md_[-1] > 0 else 0.0

    # ---- ATR14 ----
    a14 = atr_fn(14)
    tech["ATR14"] = float(a14[-1])
    tech["ATR_PERCENTILE"] = float(np.percentile(a14[-20:], [50])[0]) if n >= 20 else 0
    a20 = atr_fn(20) if n >= 20 else a14
    tech["ATR_RATIO_20"] = float(a14[-1] / np.mean(a20[-60:])) if n >= 60 and np.mean(a20[-60:]) > 0 else 1.0
    tech["volatility_pct"] = float(a14[-1] / c[-1] * 100) if c[-1] > 0 else 0
    tech["volatility_state"] = "high" if tech["volatility_pct"] > 3 else "normal"

    # ---- DMI / ADX (通达信Wilder平滑) ----
    up_ = h - np.roll(h, 1)
    dn_ = np.roll(l, 1) - l
    pdm = np.where((up_ > dn_) & (up_ > 0), up_, 0.0)
    mdm = np.where((dn_ > up_) & (dn_ > 0), dn_, 0.0)
    at14 = np.where(a14 == 0, 1e-10, a14)
    pdi = 100 * wilder_rma(pdm, 14) / at14
    mdi = 100 * wilder_rma(mdm, 14) / at14
    dx = 100 * np.abs(pdi - mdi) / (pdi + mdi + 1e-10)
    adx_ = wilder_rma(dx, 14)
    tech["DMI_PDI"] = float(pdi[-1])
    tech["DMI_MDI"] = float(mdi[-1])
    tech["ADX"] = float(adx_[-1])

    # ---- DC Donchian ----
    for p, suffix in [(20, ""), (55, "55")]:
        u = max_(h, p)
        lw = min_(l, p)
        tech[f"DC{suffix}_UPPER"] = float(u[-1])
        tech[f"DC{suffix}_LOWER"] = float(lw[-1])
        tech[f"DC{suffix}_MID"] = float((u[-1] + lw[-1]) / 2)
    dc20_l = tech["DC_LOWER"]
    dc20_u = tech["DC_UPPER"]
    tech["DC_POS"] = float((c[-1] - dc20_l) / (dc20_u - dc20_l)) if dc20_u > dc20_l else 0.5
    # DC55_TREND: use MA20 slope direction
    tech["DC55_TREND"] = "up" if tech["MA20_SLOPE"] > 0.01 else ("down" if tech["MA20_SLOPE"] < -0.01 else "flat")

    # ---- BB Bollinger ----
    bb_mid = sma(c, 20)
    bb_std = sd(c, 20)
    tech["BB_UPPER"] = float(bb_mid[-1] + 2 * bb_std[-1])
    tech["BB_LOWER"] = float(bb_mid[-1] - 2 * bb_std[-1])
    tech["BB_MIDDLE"] = float(bb_mid[-1])
    tech["BB_PCTB"] = (
        float((c[-1] - tech["BB_LOWER"]) / (tech["BB_UPPER"] - tech["BB_LOWER"]))
        if tech["BB_UPPER"] > tech["BB_LOWER"]
        else 0.5
    )
    tech["BB_WIDTH"] = (
        float((tech["BB_UPPER"] - tech["BB_LOWER"]) / tech["BB_MIDDLE"] * 100) if tech["BB_MIDDLE"] > 0 else 0
    )
    tech["BB_WIDTH_PCT"] = tech["BB_WIDTH"]
    bw20 = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid * 100
    tech["BB_SQUEEZE"] = bool(bw20[-1] < np.percentile(bw20[-60:], 10)) if n >= 60 else False

    # ---- SUPERTREND (10,3) ----
    at10 = atr_fn(10)
    hl = (h + l) / 2
    upper = hl + 3 * at10
    lower = hl - 3 * at10
    st_arr = np.zeros(n)
    st_dir_arr = np.zeros(n)
    trend = 1
    st_arr[0] = lower[0]
    st_dir_arr[0] = 1
    for i in range(1, n):
        if trend == 1:
            if c[i] < st_arr[i - 1]:
                trend = -1
                st_arr[i] = upper[i]
            else:
                st_arr[i] = max(lower[i], st_arr[i - 1])
        else:
            if c[i] > st_arr[i - 1]:
                trend = 1
                st_arr[i] = lower[i]
            else:
                st_arr[i] = min(upper[i], st_arr[i - 1])
        st_dir_arr[i] = trend
    tech["SUPERTREND_DIR"] = int(st_dir_arr[-1])
    tech["SUPERTREND_JUST_FLIPPED"] = st_dir_arr[-1] != st_dir_arr[-2] if n >= 3 else False

    # ---- KELTNER CHANNEL (20, 2.25) / CHANDELIER EXIT (22, 3.0) / PARABOLIC SAR ----
    # G30: 趋势跟踪指标衍生子策略所需的新字段，单点注入（scan_all + 所有回测共用）。
    try:
        from futures_data_core.indicators.tdx_compat import (
            calculate_keltner,
            calculate_chandelier_exit,
            calculate_sar,
        )
        if n >= 20:
            kc_u, kc_l, kc_m = calculate_keltner(h, l, c, period=20, atr_mult=2.25)
            tech["KC_UPPER"] = float(kc_u[-1]) if np.isfinite(kc_u[-1]) else 0.0
            tech["KC_LOWER"] = float(kc_l[-1]) if np.isfinite(kc_l[-1]) else 0.0
            tech["KC_MID"] = float(kc_m[-1]) if np.isfinite(kc_m[-1]) else 0.0
        else:
            tech["KC_UPPER"] = tech["KC_LOWER"] = tech["KC_MID"] = 0.0
        if n >= 22:
            ch_l, ch_s = calculate_chandelier_exit(h, l, c, period=22, mult=3.0)
            tech["CHANDELIER_LONG"] = float(ch_l[-1]) if np.isfinite(ch_l[-1]) else 0.0
            tech["CHANDELIER_SHORT"] = float(ch_s[-1]) if np.isfinite(ch_s[-1]) else 0.0
        else:
            tech["CHANDELIER_LONG"] = tech["CHANDELIER_SHORT"] = 0.0
        if n >= 2:
            sar_arr, sar_trend = calculate_sar(h, l)
            tech["SAR"] = float(sar_arr[-1]) if np.isfinite(sar_arr[-1]) else 0.0
            tech["SAR_TREND"] = int(sar_trend[-1])
        else:
            tech["SAR"] = 0.0
            tech["SAR_TREND"] = 0
    except Exception:
        tech["KC_UPPER"] = tech["KC_LOWER"] = tech["KC_MID"] = 0.0
        tech["CHANDELIER_LONG"] = tech["CHANDELIER_SHORT"] = 0.0
        tech["SAR"] = 0.0
        tech["SAR_TREND"] = 0

    # ---- TSMOM 时间序列动量（G31: 1/3/6/12 月收益，多窗口合成降噪） ----
    # 主管线唯一入口单点注入（scan_all + 所有回测共用），自动贯穿全链路。
    # n>=60 早退已保证 1m/3m 必算；6m(n>=127)/12m(n>=253) 按序列长度条件可用。
    try:
        from futures_data_core.indicators.tdx_compat import calculate_tsmom
        r1, r3, r6, r12 = calculate_tsmom(c, windows=(21, 63, 126, 252))
        tech["TSMOM_1M"] = float(r1) if np.isfinite(r1) else 0.0
        tech["TSMOM_3M"] = float(r3) if np.isfinite(r3) else 0.0
        tech["TSMOM_6M"] = float(r6) if np.isfinite(r6) else 0.0
        tech["TSMOM_12M"] = float(r12) if np.isfinite(r12) else 0.0
    except Exception:
        tech["TSMOM_1M"] = tech["TSMOM_3M"] = 0.0
        tech["TSMOM_6M"] = tech["TSMOM_12M"] = 0.0

    # ---- Vortex (14) ----
    vm_p = np.abs(h - np.roll(l, 1))
    vm_m = np.abs(l - np.roll(h, 1))
    tr_v_atr = atr_fn(14)
    tr_v = np.where(tr_v_atr == 0, 1e-10, tr_v_atr)
    vp = wilder_rma(vm_p, 14) / tr_v
    vm = wilder_rma(vm_m, 14) / tr_v
    tech["VI_PLUS"] = float(vp[-1])
    tech["VI_MINUS"] = float(vm[-1])

    # ---- HMA ----
    def hma_fn(x, p):
        h1 = sma(x, p // 2) * 2 - sma(x, p)
        return sma(h1, int(np.sqrt(p)))

    if n >= 20:
        tech["HMA10"] = float(hma_fn(c, 10)[-1]) if n >= 10 else 0
        tech["HMA20"] = float(hma_fn(c, 20)[-1])
        hma10_series = hma_fn(c, 10)
        tech["HMA_CROSS"] = 1 if hma10_series[-1] > tech["HMA20"] else -1
        tech["HMA_JUST_CROSSED"] = (
            hma10_series[-2] <= tech.get("HMA20_PREV", tech["HMA20"]) and tech["HMA_CROSS"] == 1
        ) or (hma10_series[-2] >= tech.get("HMA20_PREV", tech["HMA20"]) and tech["HMA_CROSS"] == -1)
    else:
        tech["HMA10"] = 0
        tech["HMA20"] = 0
        tech["HMA_CROSS"] = 0
        tech["HMA_JUST_CROSSED"] = False

    # ---- KAMA ----
    if n >= 10:
        eff = np.abs(c[-1] - c[-10]) / np.sum(np.abs(np.diff(c[-10:]))) if np.sum(np.abs(np.diff(c[-10:]))) > 0 else 0
        sc = (eff * (2 / (3) - 2 / (31)) + 2 / (31)) ** 2
        kama = c[-10]
        for i in range(-9, 0):
            kama = kama + sc * (c[i] - kama)
        tech["KAMA10"] = float(kama)
        tech["KAMA_CROSS"] = 1 if c[-1] > kama else -1
    else:
        tech["KAMA10"] = 0
        tech["KAMA_CROSS"] = 0

    # ---- CMF21 (requires volume) ----
    if np.sum(v) > 0:
        mfm = ((c - l) - (h - c)) / (h - l + 1e-10) * v  # money flow multiplier * volume
        cmf = sma(mfm, 21) / sma(v, 21)
        tech["CMF21"] = float(cmf[-1]) if np.isfinite(cmf[-1]) else 0
    else:
        tech["CMF21"] = 0

    # ---- OBV ----
    obv = np.zeros(n)
    obv[0] = v[0]
    for i in range(1, n):
        if c[i] > c[i - 1]:
            obv[i] = obv[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            obv[i] = obv[i - 1] - v[i]
        else:
            obv[i] = obv[i - 1]
    tech["OBV"] = float(obv[-1])
    tech["OBV_MA20"] = float(sma(obv, 20)[-1]) if n >= 20 else 0

    # ---- WILLR14 ----
    h14 = max_(h, 14)
    l14 = min_(l, 14)
    tech["WILLR14"] = float((h14[-1] - c[-1]) / (h14[-1] - l14[-1] + 1e-10) * -100)

    # ---- STOCH_K5 ----
    h5 = max_(h, 5)
    l5 = min_(l, 5)
    tech["STOCH_K5"] = float((c[-1] - l5[-1]) / (h5[-1] - l5[-1] + 1e-10) * 100)

    # ---- ROC10 ----
    tech["ROC10"] = float((c[-1] / c[-11] - 1) * 100) if n >= 11 else 0

    # ---- Volume indicators ----
    v5 = np.mean(v[-5:])
    v20 = np.mean(v[-20:])
    tech["VOL_5D_RATIO"] = float(v[-1] / v5) if v5 > 0 else 1
    tech["VOL_MA20"] = float(v20)
    tech["VOL_RATIO"] = float(v[-1] / v20) if v20 > 0 else 1
    tech["VOL_PRICE_DIVERGENCE"] = (
        "negative"
        if (c[-1] < c[-5] and v[-1] > v5 * 1.2)
        else ("positive" if (c[-1] > c[-5] and v[-1] > v5 * 1.2) else "none")
    )

    # ---- Price structure ----
    tech["PRICE_CHANGE_5D"] = float((c[-1] / c[-6] - 1) * 100) if n >= 6 else 0
    tech["HIGH_60"] = float(np.max(h[-60:])) if n >= 60 else 0
    tech["MA120"] = float(sma(c, 120)[-1]) if n >= 120 else 0
    tech["NEW_HIGH_60"] = c[-1] >= tech["HIGH_60"] * 0.99
    tech["NEW_LOW_60"] = c[-1] <= np.min(l[-60:]) * 1.01 if n >= 60 else False

    # HIGHER_LOW / LOWER_HIGH (swing points, last 20 bars)
    if n >= 20:
        l20 = l[-20:]
        h20 = h[-20:]
        l_min = np.argmin(l20)
        h_max = np.argmax(h20)
        recent_l = np.min(l[-5:])
        recent_h = np.max(h[-5:])
        tech["HIGHER_LOW"] = l_min < 10 and recent_l > np.min(l20[:10]) if l_min < len(l20) else False
        tech["LOWER_HIGH"] = h_max < 10 and recent_h < np.max(h20[:10]) if h_max < len(h20) else False
    else:
        tech["HIGHER_LOW"] = False
        tech["LOWER_HIGH"] = False

    # ---- OI (持仓) related ----
    if "open_interest" in df.columns or "oi" in df.columns:
        oi_col = "open_interest" if "open_interest" in df.columns else "oi"
        oi_vals = df[oi_col].values.astype(float)
        inan = ~np.isnan(oi_vals)
        if np.sum(inan) > 0:
            oi_last = oi_vals[inan][-1]
            oi_5d = oi_vals[inan][-6] if np.sum(inan) >= 6 else oi_last
            tech["OI_CHANGE_PCT"] = float((oi_last / oi_5d - 1) * 100) if oi_5d > 0 else 0
            tech["OI_INCREASING"] = oi_last > oi_5d
            tech["OI_RATE"] = float(oi_last / oi_5d) if oi_5d > 0 else 1.0

    # ---- Misc ----
    tech["PRICE_DEVIATION_PCT"] = (
        float((c[-1] - tech.get("MA20", c[-1])) / tech.get("MA20", c[-1]) * 100) if tech.get("MA20", c[-1]) > 0 else 0
    )
    tech["last_price"] = float(c[-1])

    # ── 数据源溯源（R19-R22: 子周期降级数据必须标记） ──
    if period != "daily":
        tech["_data_source"] = "numpy_raw"
        tech["_tdx_note"] = "子周期数据: 降级计算(非TDX/TqSDK), 连续合约可能异于L8, ADX等全序列指标仅供参考"

    # ── 通达信TQ-Local桥接：覆盖DMI/RSI/CCI/MACD（精确值与通达信软件一致） ──
    # 🐛 v2.9.1 修复: period!="daily"时跳过桥接，避免日线值覆盖子周期指标
    tech["_tdx_patched"] = False
    tech["_tdx_fields"] = []
    if symbol and period == "daily":
        tdx_available = False
        try:
            from indicators.tdx_bridge import get_bridge

            bridge = get_bridge()
            status = bridge.patch_indicators(tech, symbol)
            tech["_tdx_patched"] = status["patched"]
            tech["_tdx_fields"] = status["fields"]
            tdx_available = status["patched"]
            if not status["patched"] and not bridge.available:
                tech["_tdx_note"] = "TQ-Local不可用"
        except Exception:
            tech["_tdx_note"] = "TQ-Local桥接异常"

        # ── 最后保障：technical-indicator-calc 的计算引擎（通达信公式完全对齐） ──
        if not tdx_available:
            try:
                sys.path.insert(
                    0,
                    os.path.join(
                        os.path.dirname(os.path.dirname(__file__)), "..", "technical-indicator-calc", "scripts"
                    ),
                )
                from indicators.calc_core import calculate_tdx_compatible
                import numpy as np

                fallback = calculate_tdx_compatible(
                    np.array(h[-120:], dtype=np.float64),
                    np.array(l[-120:], dtype=np.float64),
                    np.array(c[-120:], dtype=np.float64),
                    volume=np.array(v[-120:], dtype=np.float64) if v is not None else None,
                )

                # 用last-resort数值覆盖未patched的字段
                fallback_fields = 0
                for fk, tk in [
                    ("rsi", "RSI14"),
                    ("cci", "CCI20"),
                    ("adx", "ADX"),
                    ("pdi", "DMI_PDI"),
                    ("mdi", "DMI_MDI"),
                    ("macd_dif", "MACD_DIF"),
                    ("macd_dea", "MACD_DEA"),
                    ("macd_hist", "MACD_HIST"),
                    ("atr", "ATR"),
                    ("atr", "ATR14"),
                    ("kdj_k", "KDJ_K"),
                    ("kdj_d", "KDJ_D"),
                    ("kdj_j", "KDJ_J"),
                    ("mfi", "MFI"),
                    ("wr1", "WILLR"),
                    ("bbi", "BBI"),
                    ("uos", "UOS"),
                    ("mtm", "MTM"),
                    ("roc", "ROC"),
                    ("psy", "PSY"),
                    ("vr", "VR"),
                ]:
                    if fk in fallback and fallback[fk] is not None and tk not in tech.get("_tdx_fields", []):
                        tech[tk] = fallback[fk]
                        fallback_fields += 1

                tech["_tdx_fallback"] = fallback_fields > 0
                tech["_tdx_note"] = f"最后保障: {fallback_fields}字段"
            except Exception as e:
                if "_tdx_note" not in tech:
                    tech["_tdx_note"] = f"最后保障异常: {e}"

    return tech
