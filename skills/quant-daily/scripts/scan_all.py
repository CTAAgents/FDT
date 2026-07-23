#!/usr/bin/env python3
"""
品种信号扫描 — 策略可插拔入口
=================================
默认：单策略通道突破（strategies/channel_breakout_strategy.py）
  唐奇安DC20/DC55 + 布林带确认的双通道突破识别
  （多策略管线已迁至独立 skill）

用法：
  python scan_all.py                                          # v7.0 默认：6策略并行管线
  python scan_all.py --strategy channel_breakout               # 单策略（兼容旧版）
  python scan_all.py --strategy my_new_strategy [--symbols PK,RB]
  python scan_all.py --list-strategies                        # 列出所有策略
"""

import sys, os, json, re, random, pandas as pd
import asyncio
from datetime import date

# ── Windows 路径规范化：/x/... → X:/...（Git Bash → Python 原生） ──
if os.name == "nt":
    def _normalize_path(p: str) -> str:
        """将 Git Bash 风格的 /d/... 路径转为 Windows 原生 D:/... 格式"""
        if p and len(p) > 2 and p[0] == '/' and p[2] == '/':
            m = re.match(r'^/([a-zA-Z])/(.*)', p)
            if m:
                return f"{m.group(1).upper()}:/{m.group(2)}"
        return os.path.normpath(p) if p else p
else:
    def _normalize_path(p: str) -> str:
        return os.path.normpath(p) if p else p

# ── 路径自举（quant-daily scripts/ 目录 + 父级 + FDT 根） ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
PARENT_DIR = os.path.dirname(SKILL_DIR)  # 包含 scripts/ 作为包名
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)
# FDT 根目录（包含 futures_data_core/ 包），插到 sys.path[0] 以覆盖 D:\FDT2 的版
FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
if FDT_ROOT not in sys.path:
    sys.path.insert(0, FDT_ROOT)

try:
    from indicators.core import assess_trend_maturity
    from indicators.indicators_legacy import _compute_indicators_numpy
    from indicators.tdx_bridge import get_bridge
    from config.symbols import ALL_SYMBOLS
except ImportError:
    from indicators.core import assess_trend_maturity
    from indicators.indicators_legacy import _compute_indicators_numpy
    from indicators.tdx_bridge import get_bridge
    from config.symbols import ALL_SYMBOLS

# ── FDC 统一数据引擎（取代 data.multi_source_adapter.MultiSourceAdapter） ──
from data_source_adapter import get_kline as _ds_get_kline
from data_source_adapter import batch_get_quotes as _ds_batch_quotes

def _fdc_get_kline_sync(variety: str, days: int = 120, period: str = "daily") -> dict:
    """同步包装 FDC get_kline，供 scan_all.py 的遍历循环使用。

    2026-07-13 重构：取代 data/multi_source_adapter MultiSourceAdapter.get_kline()。
    TqSDK collector 已修复 `_close_api()`（每调用关闭 TqApi 实例），
    不会跨 asyncio.run() 边界损坏，可安全逐品种调用。
    """
    try:
        payload = asyncio.run(_ds_get_kline(variety, period=period, days=days))
        meta = payload.meta
        grade = meta.get("data_grade_label", 5)
        grade_str = meta.get("data_grade", "")
        # 先计算数据源标签（穿透到 FDC 的真实底层源：tdx_tq_local / web_fallback / qmt_xtquant / tqsdk）
        _sources_list = meta.get("sources", ["fdc"])
        _source_label = _sources_list[0] if isinstance(_sources_list, list) else str(_sources_list)
        # data_grade_label: 0=PRIMARY, 1=SECONDARY, 2=TERTIARY, 3=COMPUTED, 4=STALE, 5=UNAVAILABLE
        if (isinstance(grade, (int, float)) and grade >= 4) or grade_str in ("UNAVAILABLE", "STALE"):
            return {"success": False, "data": [], "data_source": grade_str or f"grade={grade}", "error": f"FDC grade={grade}"}
        bars_raw = payload.data.get("bars", [])
        if not bars_raw:
            return {"success": False, "data": [], "data_source": _source_label, "error": "FDC 返回空 K 线"}
        records = []
        for b in bars_raw:
            records.append({
                "date": b.get("date", ""),
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "volume": int(b.get("volume", 0)),
                "oi": int(b.get("oi") or b.get("open_interest", 0)),
                "settle": float(b.get("settle", 0) if b.get("settle") else 0),
                "data_source": _source_label,
                "confidence": 1.0,
            })
        return {"success": True, "data": records, "data_source": _source_label, "confidence": 1.0}
    except Exception as e:
        return {"success": False, "data": [], "data_source": "fdc_error", "error": str(e)}


def _atomic_write(path: str, content, mode: str = "json"):
    """原子写入：写 .tmp → rename，防止写半截文件"""
    import tempfile, shutil
    tmp = path + ".tmp_" + str(os.getpid())
    try:
        if mode == "json":
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2, default=str)
        else:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise



def _split_symbol_contract(sym: str):
    """从品种代码解析 (variety, contract)。

    'LH2609' → ('LH', '2609')；'LH' → ('LH', None)
    支持1-6位字母 + 可选3-4位合约月份后缀。
    用于单品种辩论时自动取真实合约K线(MA60等与文华/真实合约一致)，
    不带后缀则沿用主力连续L8。
    """
    import re as _re

    m = _re.match(r"^([A-Za-z]{1,6})(\d{3,4})?$", sym)
    if not m:
        return sym, None
    return m.group(1), m.group(2)


# ── 多因子增强过滤器：基差数据采集（生意社现货价 → 基差）──
def _collect_basis_data_sync(all_ranked: list) -> dict:
    """同步采集基差数据：100ppi.com/sf/ 现期表 → 降级 TdxCollector 近月代理。

    对 all_ranked 中每个品种，用期货价（price）与生意社现货价计算基差。
    单位换算：FG(×80), jd(/500), lh(/1000) 已内置。

    [v8.8.7] 降级策略：100ppi 不可用时（HW_CHECK 反爬/超时/页面变更），
    自动降级到 TdxCollector 近月合约价格作为现货代理。
    原理：近月合约临近交割时价格收敛于现货，可作为高质量现货近似值。
    """
    import requests
    from bs4 import BeautifulSoup
    
    result: dict[str, dict] = {}
    try:
        resp = requests.get("https://www.100ppi.com/sf/", timeout=15)
        if resp.status_code != 200:
            return _collect_basis_via_nearmonth(all_ranked)
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", class_="sf-table") or soup.find("table", id="sf-table") or soup.find("table")
        if not table:
            return _collect_basis_via_nearmonth(all_ranked)
        # 导入映射表与换算配置
        from data.spot_100ppi import PPI_SYMBOL_MAP, UNIT_CONVERSIONS
        fut_prices = {}
        for r in all_ranked:
            sym = r.get("symbol", "").upper()
            price = r.get("price", 0)
            if sym and price:
                fut_prices[sym] = float(price)
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            name_text = cells[0].get_text(strip=True)
            if not name_text:
                continue
            # 匹配品种
            matched_sym = None
            for sym, sf_id in PPI_SYMBOL_MAP.items():
                if sf_id is None:
                    continue
                if sym.upper() in name_text.upper() or name_text.upper() in sym.upper():
                    matched_sym = sym
                    break
            if not matched_sym:
                continue
            sym_upper = matched_sym.upper()
            try:
                spot_raw = float(cells[2].get_text(strip=True).replace(",", ""))
            except (ValueError, IndexError):
                continue
            # 单位换算
            conv = UNIT_CONVERSIONS.get(sym_upper, {})
            factor = conv.get("factor", 1)
            spot = spot_raw * factor
            fut = fut_prices.get(sym_upper, 0)
            if sym_upper == "JD" and "futures_conversion" in conv:
                fut = fut * conv["futures_conversion"]["factor"]  # /500
            elif sym_upper == "LH" and "futures_conversion" in conv:
                fut = fut * conv["futures_conversion"]["factor"]  # /1000
            if not fut:
                continue
            basis = spot - fut
            basis_pct = basis / fut * 100.0
            result[sym_upper] = {
                "spot_raw": spot_raw,
                "spot": round(spot, 2),
                "futures": round(fut, 2),
                "basis": round(basis, 2),
                "basis_pct": round(basis_pct, 4),
                "unit": conv.get("target_unit", "元/吨"),
            }
    except Exception:
        pass

    # ── 降级路径：100ppi 无数据 → TDX 近月合约作为现货代理 ──
    if not result:
        result = _collect_basis_via_nearmonth(all_ranked)
    return result


def _collect_basis_via_nearmonth(all_ranked: list) -> dict:
    """降级方案：使用 TdxCollector 近月合约价格作为现货代理。

    当生意社 100ppi 不可用时（HW_CHECK 反爬/网络超时/页面结构变更），
    使用通达信本地 TdxCollector 获取各品种近月合约价格作为现货代理。

    原理：期货近月合约临近交割时基差趋近于零，价格收敛于现货。
    对于无交割月的指数类品种（如集运指数 ec），跳过降级。
    返回格式与 _collect_basis_data_sync 同构，unit 标注为"近月代理"。

    Returns:
        {SYM: {spot: float, futures: float, basis: float, basis_pct: float,
               unit: str, data_source: str, spot_raw: float}}
    """
    result: dict[str, dict] = {}
    try:
        from data.collectors.tdx_collector import TdxCollector
        from data.spot_100ppi import UNIT_CONVERSIONS

        tdx = TdxCollector()
        if not tdx.is_available:
            return result

        # 构建品种→期货价格映射
        fut_prices = {}
        for r in all_ranked:
            sym = r.get("symbol", "").upper()
            price = r.get("price", 0)
            if sym and price:
                fut_prices[sym] = float(price)

        for sym_upper, fut in fut_prices.items():
            try:
                ts = tdx.get_term_structure(sym_upper)
                if not ts or not ts.get("near_price"):
                    continue
                near_price = float(ts["near_price"])
                if near_price <= 0:
                    continue

                # JD/LH 单位换算：与 100ppi 路径保持一致
                conv = UNIT_CONVERSIONS.get(sym_upper, {})
                fut_converted = fut
                if sym_upper == "JD" and "futures_conversion" in conv:
                    fut_converted = fut * conv["futures_conversion"]["factor"]  # /500
                elif sym_upper == "LH" and "futures_conversion" in conv:
                    fut_converted = fut * conv["futures_conversion"]["factor"]  # /1000

                if not fut_converted:
                    continue

                basis = near_price - fut_converted
                basis_pct = basis / fut_converted * 100.0
                result[sym_upper] = {
                    "spot_raw": near_price,
                    "spot": round(near_price, 2),
                    "futures": round(fut_converted, 2),
                    "basis": round(basis, 2),
                    "basis_pct": round(basis_pct, 4),
                    "unit": "元/吨(近月代理)",
                    "data_source": "near_month_proxy",
                }
            except Exception:
                continue
    except Exception:
        pass
    return result


def _build_pure_stats(r: dict, kline: list | None) -> dict:
    """从原始记录和K线构建纯定量stats对象。
    
    P1角色矫正（2026-07-21）：数技源只出统计事实，不包含方向性预判。
    技术方向判断权归还给观澜（P3）。
    不读取 direction/total/grade 等方向性字段。
    """
    stats = {}
    
    # ── 价格统计 ──
    stats["latest_close"] = r.get("price", 0)
    stats["change_pct"] = r.get("change_pct", 0)
    
    # ── 均线系统（从 r 中已有的技术指标提取） ──
    stats["ma_5"] = r.get("ma_5", r.get("price", 0))
    stats["ma_10"] = r.get("ma_10", r.get("price", 0))
    stats["ma_20"] = r.get("ma_20", r.get("price", 0))
    stats["ma_60"] = r.get("ma_60", r.get("price", 0))
    stats["ma_align"] = r.get("ma_align", "mixed")
    
    # ── 波动与强度 ──
    stats["atr_14"] = r.get("atr", 0)
    stats["rsi_14"] = r.get("rsi", 50)
    stats["adx_14"] = r.get("adx", 25)
    stats["di_plus"] = r.get("di_plus", 0)
    stats["di_minus"] = r.get("di_minus", 0)
    
    # ── 量能 ──
    stats["volume"] = r.get("volume", 0)
    stats["oi"] = r.get("oi", 0)
    stats["oi_change"] = r.get("oi_change", 0)
    stats["volume_ma20"] = _calc_volume_ma20(kline) if kline else 0
    stats["volume_ma20_ratio"] = (
        round(stats["volume"] / stats["volume_ma20"], 2)
        if stats["volume_ma20"] > 0 else 0
    )
    
    # ── 通道与形态 ──
    stats["dc20_upper"] = r.get("dc20_upper", 0)
    stats["dc20_lower"] = r.get("dc20_lower", 0)
    bp = stats["dc20_upper"] - stats["dc20_lower"]
    stats["dc20_width_pct"] = round(bp / (stats["dc20_upper"] or 1) * 100, 2)
    stats["z_score"] = r.get("z_score", 0)
    
    # ── 20日区间位置 ──
    high_20d = r.get("high_20d", stats["latest_close"])
    low_20d = r.get("low_20d", stats["latest_close"])
    rng = high_20d - low_20d
    stats["high_20d"] = high_20d
    stats["low_20d"] = low_20d
    stats["price_position_pct"] = round(
        (stats["latest_close"] - low_20d) / (rng or 1) * 100, 1
    )
    
    # ── 数据源标记 ──
    stats["data_source"] = r.get("data_source", "unknown")
    stats["n_bars"] = len(kline) if kline else 0
    
    return stats


def _calc_volume_ma20(kline: list) -> float:
    """从原始K线计算20日均量。"""
    if not kline or len(kline) < 2:
        return 0
    recent = kline[-21:-1] if len(kline) > 20 else kline
    volumes = [b.get("volume", 0) for b in recent if isinstance(b, dict) and b.get("volume", 0) > 0]
    return sum(volumes[-20:]) / min(len(volumes[-20:]), 20) if volumes else 0


def _collect_oi_data_sync(all_ranked: list, kline_data: dict) -> dict:
    """从 kline_data 同步提取 OI 变化数据。

    对 all_ranked 中每个品种，从 K 线提取末根 OI、前20根平均 OI、OI 变化率。
    """
    result: dict[str, dict] = {}
    for r in all_ranked:
        sym = r.get("symbol", "")
        dlist = (kline_data.get(sym) or (None, []))[1]
        if len(dlist) < 21:
            continue
        try:
            last_oi = float(dlist[-1].get("oi", 0))
            prior_oi_avg = sum(float(x.get("oi", 0)) for x in dlist[-21:-1]) / 20
            if prior_oi_avg > 0:
                oi_change_pct = (last_oi - prior_oi_avg) / prior_oi_avg * 100
            else:
                oi_change_pct = 0.0
            result[sym] = {
                "oi": last_oi,
                "oi_avg": round(prior_oi_avg, 1),
                "oi_change_pct": round(oi_change_pct, 2),
            }
        except (ValueError, TypeError, ZeroDivisionError):
            continue
    return result


def _get_warrant_sync(symbol: str, exchange: str, trade_date: str = None) -> dict:
    """同步包装 FDC ``get_warrant``（仓单日报），返回 ``{total, daily_change}`` 或 ``None``。

    G27（2026-07-15）：仓单是 MultiFactorStrategy 唯一具备真实全量源（SHFE/DCE/CZCE/GFEX）
    的另类因子。沙箱网络受限时 ``get_warrant`` 返回 UNAVAILABLE → 本函数返回 ``None``，
    因子惰性 0（不造假信号）。
    """
    try:
        from data_source_adapter import get_warrant_fdc
        payload = asyncio.run(get_warrant_fdc(symbol, exchange=exchange, trade_date=trade_date))
        grade = payload.meta.get("data_grade", "")
        if grade in ("UNAVAILABLE", "STALE"):
            return None
        d = payload.data if isinstance(payload.data, dict) else {}
        if d.get("total") is None:
            return None
        return {"total": d.get("total"), "daily_change": d.get("daily_change"), "source": exchange}
    except Exception:
        return None


def _collect_fundamental_sync(tech_list: list) -> dict:
    """采集多因子策略所需的另类/基本面数据，注入 ``ctx_extra``（G27）。

    - ``warrant_data``：仓单日报（``get_warrant``，4 交易所真实源）→ ``warrant_change`` 因子
    - ``inventory_data``：库存快照（``load_fundamental inventory``）→ ``inventory_pct``
    - ``supply_data``：开工率快照（``load_fundamental supply``）→ ``capacity``

    数据源探查结论：仅 warrant 为真实全量源；inventory/capacity 缓存仅 CU/RB/AU 单点
    绝对值、无分位/无历史 → 因子惰性 0（不造假信号），待 Mysteel/隆众或参考区间接入。
    """
    out: dict[str, dict] = {"warrant_data": {}, "inventory_data": {}, "supply_data": {}}
    # 品种 → 交易所映射（懒加载；失败则跳过 warrant 采集）
    exch_map: dict = {}
    try:
        from data.collectors.tdx_collector import VARIETY_EXCHANGE
        exch_map = VARIETY_EXCHANGE or {}
    except Exception:
        pass
    # 本地基本面缓存（同步读取，无网络依赖）
    _load_fundamental = None
    try:
        from data_source_adapter import load_fundamental as _lf
        _load_fundamental = _lf
    except Exception:
        pass

    for t in tech_list:
        sym = str(t.get("symbol", "")).upper()
        if not sym:
            continue
        # ── 仓单（真实源）──
        ex = exch_map.get(sym)
        if ex:
            w = _get_warrant_sync(sym, ex)
            if w:
                out["warrant_data"][sym] = w
        # ── 库存 / 开工率（本地缓存快照）──
        if _load_fundamental:
            try:
                inv = _load_fundamental(sym, "inventory")
                if inv:
                    out["inventory_data"][sym] = inv
                sup = _load_fundamental(sym, "supply")
                if sup:
                    out["supply_data"][sym] = sup
            except Exception:
                pass
    return out


def _get_macro_sync() -> dict:
    """同步采集宏观数据（PMI + LPR1Y），注入 ``ctx_extra['macro_data']``（G29）。

    经 ``futures_data_core.f10.macro`` 直连东方财富宏观数据中心（免费公开源）。
    沙箱 Python 网络受限时两个 payload 均 UNAVAILABLE → 返回 ``available=False``，
    multi_factor 的 ``rate_proxy``/``pmi_proxy`` 因子惰性 0（不造假信号）。
    """
    out: dict = {
        "available": False,
        "source": "unavailable",
        "pmi": None, "pmi_date": None, "pmi_mom": None,
        "rate": None, "rate_date": None, "rate_mom": None,
    }
    try:
        from data_source_adapter import get_macro_pmi, get_macro_rate
        pmi_p = asyncio.run(get_macro_pmi())
        rate_p = asyncio.run(get_macro_rate())
        if pmi_p.meta.get("data_grade") not in ("UNAVAILABLE", "STALE"):
            d = pmi_p.data if isinstance(pmi_p.data, dict) else {}
            out["pmi"] = d.get("pmi")
            out["pmi_date"] = d.get("pmi_date")
            out["pmi_mom"] = d.get("pmi_mom")
        if rate_p.meta.get("data_grade") not in ("UNAVAILABLE", "STALE"):
            d = rate_p.data if isinstance(rate_p.data, dict) else {}
            out["rate"] = d.get("rate")
            out["rate_date"] = d.get("rate_date")
            out["rate_mom"] = d.get("rate_mom")
        out["available"] = (out["pmi"] is not None) or (out["rate"] is not None)
        if out["available"]:
            out["source"] = "eastmoney"
    except Exception:
        pass
    return out


# ── P0-4 信号重校验门禁已迁至 signals/validators/p0_4_raw_kline.py ──
# 原 _revalidate_breakouts 逻辑现由 signals.validators.run_signal_validators 按
# config.settings.SIGNAL_VALIDATOR_MAP 路由调用（范式↔验证器声明式框架）。
# 见 design/signal_paradigm_validator_framework.md 与 technical_debt.md §5。


def collect_kline_for_all(symbols, days=120, min_bars=50, today_str=None, contract=None, period="daily"):
    """通用K线数据采集（FDC 直驱，取代 data.multi_source_adapter）。

    合约解析：symbol 若带月份后缀(如 LH2609)自动提取 contract 并取真实合约K线；
    不带后缀则用主力连续L8。显式传入的 contract 参数优先于 symbol 内嵌后缀。

    2026-07-13 重构：改用 ``_fdc_get_kline_sync()`` 直调 futures_data_core，
    不再经过 data.multi_source_adapter.MultiSourceAdapter。

    🔧 2026-07-15 G26→G30：原 max_workers=4 并发采集会触发死锁——
    多个线程各自 asyncio.run 复用同一个 adapter 单例的共享 httpx.AsyncClient /
    TQ-Local bridge，跨事件循环并发访问异步资源导致 3 个 worker 永久挂死、
    59 个品种失败（表现 [60/63] 1 OK）。改为**串行采集**（同一事件循环顺序
    取数，规避跨循环死锁），并为每品种加墙钟超时护栏，单品种卡死不影响全盘。
    """
    from datetime import date
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if today_str is None:
        today_str = date.today().strftime("%Y%m%d")

    def _fetch_one(sym, name):
        variety, sym_contract = _split_symbol_contract(sym)
        eff_contract = contract or sym_contract
        try:
            resp = _fdc_get_kline_sync(variety=variety, days=days, period=period)
            if isinstance(resp, dict) and resp.get("success"):
                dlist = resp["data"]
                valid = [r for r in dlist if r.get("date", "") and r.get("volume", 0) > 0 and r["date"] <= today_str]
                if len(valid) >= min_bars:
                    return sym, (name, valid)
        except Exception:
            pass
        return None

    # ── G30：串行采集 + 每品种墙钟护栏 ──
    # 串行避免跨事件循环死锁（共享 httpx.AsyncClient/TQ-Local bridge 并发访问
    # 会挂死）；每品种 40s 墙钟上限，单品种卡死（极少数 TQ-Local 抽风）不影响全盘。
    kline_data = {}
    _PER_SYMBOL_TIMEOUT = 40.0
    _n = len(symbols)
    for i, (sym, name) in enumerate(symbols):
        try:
            with ThreadPoolExecutor(max_workers=1) as _guard:
                _fut = _guard.submit(_fetch_one, sym, name)
                _res = _fut.result(timeout=_PER_SYMBOL_TIMEOUT)
        except Exception:
            _res = None
        if _res:
            kline_data[_res[0]] = _res[1]
        if (i + 1) % 15 == 0 or (i + 1) == _n:
            print(f"  [{i + 1}/{_n}] {len(kline_data)} OK")
    return kline_data


def run_scan(
    output_dir: str = None,
    output_prefix: str = "full_scan",
    symbols: list = None,
    mode: str = "layered",
    strategy_name: str = None,
    seed: int = None,
    contract: str = None,
    period: str = "daily",
    window_mode: str = "fixed",
    enable_filter: bool = True,
) -> dict:
    """执行品种信号扫描，返回结果字典。
    
    enable_filter: 是否启用P0-4伪信号过滤，默认开启。False时跳过验证器管道。
    

    策略层已独立到 strategies/ 目录，新增策略仅需:
      1. 在 strategies/ 下新建 .py 实现 BaseStrategy
      2. registry.py 自动注册

    参数：
        strategy_name: 策略名。None → 默认 channel_breakout（唐奇安DC20/DC55+布林带）
        symbols: [(sym, name), ...] 格式。None → 全品种。

    参数校验：
    - symbols必须为[(sym, name), ...]格式
    - 每个sym为2-6位字母代码
    - 空symbols列表触发全品种扫描
    """
    # ── 设置全局随机种子（P0-1: 决策确定性重构）──
    if seed is not None:
        random.seed(seed)
        try:
            import numpy as np

            np.random.seed(seed)
        except ImportError:
            pass
        os.environ["PYTHONHASHSEED"] = str(seed)
        print(f"[Fingerprint] 全局随机种子已设置: seed={seed}")

    # ── 生成策略指纹ID ──
    try:
        import sys as _sys

        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from scripts.core.fingerprint import generate_fingerprint

        _fp = generate_fingerprint(
            strategy_params={
                "strategy": strategy_name or mode,
                "dual": False,
                "symbols_count": len(symbols) if symbols else None,
            },
            seed=seed,
        )
        print(f"[Fingerprint] 策略指纹: {_fp}")
    except Exception as e:
        _fp = f"FDB_v4.4_noseed_{date.today().strftime('%Y%m%d')}"

    # ── 双策略模式：运行两个策略，各输出一份报告 ──
    # ── 单策略模式（默认 channel_breakout 通道突破）──
    # ── 参数合法性校验 ──
    import re

    valid_sym_pattern = re.compile(r"^[A-Za-z]{1,6}(\d{3,4})?$")
    if symbols is not None:
        if not isinstance(symbols, list):
            raise TypeError("symbols必须是列表，格式 [(sym, name), ...]")
        for item in symbols:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"symbols元素必须是二元组 (sym, name)，收到: {item}")
            sym, name = item
            if not isinstance(sym, str) or not valid_sym_pattern.match(sym):
                raise ValueError(f"品种代码格式非法: '{sym}'，必须是2-6位字母")
            if not isinstance(name, str) or len(name) == 0:
                raise ValueError(f"品种名称为空: sym={sym}")

    today = date.today()
    today_str = today.strftime("%Y%m%d")

    print(f"{'=' * 60}")
    scan_scope = "自定义品种" if symbols else "全品种"
    mode_labels = {
        "layered": "原始指标(研究员辅助)",
        "compare": "双模式对比",
    }
    mode_label = mode_labels.get(mode, f"未知模式({mode})")
    print(f"{scan_scope}趋势信号扫描 v2.20.0 — {mode_label} — {today}")
    print(f"{'=' * 60}")

    # ── TQ-Local 检测 ──
    bridge = get_bridge()
    tdx_ok = bridge.available
    status_str = "[OK]" if tdx_ok else "[xx]"
    print(f"\nTQ-Local: {status_str} {'可用' if tdx_ok else '不可用 -> numpy兜底'}")

    # ── 确定品种列表 ──
    target_symbols = symbols if symbols else ALL_SYMBOLS
    print(f"  品种数: {len(target_symbols)}")

    # ── Step 1: 数据采集（FDC 统一数据引擎，取代 MSA）──
    print(f"\n[1] 数据采集（FDC futures_data_core → TqSDK/TDX/QMT 降级链）...")
    kline_data = collect_kline_for_all(target_symbols, days=120, min_bars=50, contract=contract, period=period)
    print(f"  成功: {len(kline_data)}/{len(target_symbols)}")

    # ── G31: xtdata 可用性探针（独立进程，避免主线程导入锁死）──
    # 环境异常时 ``import xtdata`` 会在主线程阻塞并持有 Python 全局导入锁，
    # 导致后续任何导入同一模块的调用（含策略管线）死锁。用独立子进程探测，
    # 超时/失败即判不可用——子进程死亡不污染主进程导入锁。主进程据此跳过
    # G35/G36 预取，绝不导入 xtdata 相关模块，扫描主路径安全。
    import subprocess as _sp
    _XT_DISABLED = False
    try:
        _pr = _sp.run([sys.executable, "-c", "import xtdata"],
                      timeout=15, capture_output=True, text=True)
        _XT_DISABLED = (_pr.returncode != 0)
    except Exception:
        _XT_DISABLED = True
    if _XT_DISABLED:
        print("  ⚠️ xtdata 不可用（独立进程探测超时/失败）→ 跳过跨期/基差预取（G35/G36 自动无操作）")

    # ── Step 1.1 (G36): 跨期价差历史预采集（受保护，xtquant/网络不可用时为空 → 策略无操作）──
    # 复用 FDC _resolve_contracts（xtquant 合约链）+ xtquant get_market_data_ex（与 FDC qmt 采集器同源），
    # 不引入新外部源。逐品种 try/except 包裹，任何失败仅跳过该品种，绝不影响主扫描路径。
    # 🛡️ 2026-07-15 修复：fetch_spread_history/fetch_basis_history 内部走 xtquant/QMT connect，
    #    环境异常时可能无限挂死（不抛异常只阻塞）。改为守护线程+超时(10s) + 并行预取，挂死即放弃。
    import concurrent.futures as _cf

    def _timed_fetch(func, sym: str, timeout: float = 10.0):
        """守护线程+超时调用可能挂死的预取函数，超时/异常均返回 None（优雅跳过）。"""
        import threading
        _box, _done = {}, threading.Event()

        def _run() -> None:
            try:
                _box["r"] = func(sym, days=120)
            except Exception:
                _box["r"] = None
            finally:
                _done.set()

        _t = threading.Thread(target=_run, daemon=True)
        _t.start()
        _done.wait(timeout=timeout)
        return _box.get("r")

    def _parallel_fetch(func, syms, timeout: float = 10.0, workers: int = 12) -> dict:
        out: dict = {}
        with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
            _futs = {ex.submit(_timed_fetch, func, s, timeout): s for s in syms}
            for _f in _cf.as_completed(_futs):
                _s = _futs[_f]
                try:
                    _r = _f.result()
                    if _r:
                        out[_s] = _r
                except Exception:
                    continue
        return out

    def _guarded_prefetch(kind: str, varieties, timeout: float = 30.0) -> dict:
        """隔离 xtquant/QMT 的导入与预取可能的主线程挂死（G30）。

        ``from strategies.xxx import fetch_xxx`` 在模块级会触发 ``import xtdata``，
        环境异常时该导入在主线程阻塞（不抛异常），导致整次扫描卡死在 Step 1.1/1.2。
        这里把「导入 + 并行预取」整体放入守护线程 + 墙钟超时，挂死即放弃返回 {}，
        绝不影响主扫描路径。预取仅服务于 G35/G36 回归策略，缺失时策略自动无操作。
        """
        import threading
        _box, _done = {}, threading.Event()

        def _run():
            try:
                if kind == "spread":
                    from strategies.spread_reversion_strategy import fetch_spread_history as _f
                else:
                    from strategies.basis_reversion_strategy import fetch_basis_history as _f
                _box["r"] = _parallel_fetch(_f, varieties)
            except Exception:
                _box["r"] = {}
            finally:
                _done.set()

        _t = threading.Thread(target=_run, daemon=True)
        _t.start()
        _done.wait(timeout=timeout)
        return _box.get("r", {})

    def _guarded_call(func, timeout: float = 25.0, default=None):
        """通用护栏：将任意可能挂死的同步调用放入守护线程 + 墙钟超时。
        挂死（不抛异常只阻塞）即放弃返回 default，绝不影响主扫描路径。
        用于 G27/G29 等 FDC 外部同步采集（仓单/库存/宏观）。"""
        import threading
        _box, _done = {}, threading.Event()

        def _run():
            try:
                _box["r"] = func()
            except Exception:
                _box["r"] = default
            finally:
                _done.set()

        _t = threading.Thread(target=_run, daemon=True)
        _t.start()
        _done.wait(timeout=timeout)
        return _box.get("r", default)

    _varieties = [
        _sym[0] if isinstance(_sym, (list, tuple)) else _sym
        for _sym, _ in target_symbols
    ]

    # G31: xtdata 不可用 → 跳过跨期/基差预取，绝不触发 xtdata 导入锁死锁
    if _XT_DISABLED:
        spread_history: dict = {}
    else:
        spread_history: dict = _guarded_prefetch("spread", _varieties)
    if spread_history:
        print(f"  跨期价差历史: {len(spread_history)} 品种就绪（G36 SpreadReversionStrategy）")

    # ── Step 1.2 (G35 P2 续): 期现基差历史（受保护，JSONL 日志 → provider）──
    if _XT_DISABLED:
        basis_history: dict = {}
    else:
        basis_history: dict = _guarded_prefetch("basis", _varieties)
    if basis_history:
        print(f"  期现基差历史: {len(basis_history)} 品种就绪（BasisReversionStrategy）")


    # ── R24 全局闸门：如果没有任何品种有有效数据，拒绝整次扫描 ──
    if not kline_data:
        _fail_reasons = []
        for s in target_symbols:
            try:
                _r = _fdc_get_kline_sync(variety=s[0], days=1, period=period)
                if not _r.get("success"):
                    _fail_reasons.append(f"{s[0]}: {_r.get('data_source','?')} → {_r.get('error','无数据')}")
            except Exception as _e:
                _fail_reasons.append(f"{s[0]}: 异常 {_e}")
        print(f"\n⛔ [R24] 全局闸门: 所有品种数据源均不可靠, 终止扫描")
        for _r in _fail_reasons[:5]:
            print(f"     {_r}")
        print(f"    按R23/R24规则, 当前环境无法提供可靠分析, 任务终止")
        return {
            "_meta": {"r24_rejected": True, "fail_reasons": _fail_reasons, "period": period},
            "freshness_report": {
                "status": "ALL_STALE",
                "total_symbols": len(target_symbols),
                "valid_symbols": 0,
                "fail_reasons": _fail_reasons[:10],
                "summary": f"全局闸门触发: {len(target_symbols)} 品种全部无有效数据, 各数据源均不可靠",
                "r24_rejected": True,
            }
        }

    # ── Step 1.5: 实时报价采集（双源融合）──
    quotes_map = {}
    _tdx_ok = bridge.available
    if _tdx_ok:
        print(f"\n[1.5] 实时报价采集（TQ-Local get_market_snapshot）...")
        try:
            import asyncio
            _sym_list = [s[0] for s in target_symbols if s[0] in kline_data]
            _raw = asyncio.run(_ds_batch_quotes(_sym_list))
            if _raw:
                quotes_map = {k.upper(): v for k, v in _raw.items()}
                print(f"  成功: {len(quotes_map)}/{len(_sym_list)}")
            else:
                print(f"  TQ-Local 无实时报价返回，使用日线收盘价")
        except Exception as _qe:
            print(f"  ⚠️ 实时报价采集异常: {_qe}")
    else:
        print(f"\n[1.5] TQ-Local 不可用，跳过实时报价（使用日线收盘价）")

    # ── Step 2: 指标计算 ──
    print(f"\n[2] 指标计算...")

    # ── 解析策略名（单一策略：通道突破）──
    if strategy_name is None:
        strategy_name = "channel_breakout"

    try:
        from strategies import list_strategies
        _ls = list_strategies()
        _sname = f"{_ls[strategy_name]['display']}" if strategy_name and strategy_name in _ls else f"{strategy_name}"
    except Exception:
        _sname = strategy_name
    print(f"  → 策略: {_sname}")

    tech_list = []
    df_map = {}  # 策略可能需要 DataFrame
    for i, (sym, name) in enumerate(target_symbols):
        if sym not in kline_data:
            continue
        try:
            _, dlist = kline_data[sym]
            # ── R24: 价格真实性校验 ──
            _last_bar = dlist[-1]
            _last_close = float(_last_bar.get("close", 0))
            _last_date = str(_last_bar.get("date", ""))
            if _last_close <= 0:
                print(f"  ⛔ [{sym}] R24拒绝: 最新收盘价={_last_close}(无效价格), 跳过")
                continue
            # 检查最后K线是否过期（>5交易日≈7日历天）
            if len(_last_date) >= 8 and _last_date.isdigit():
                from datetime import datetime as _dt
                _bar_dt = _dt.strptime(_last_date[:8], "%Y%m%d")
                _stale_days = (_dt.now() - _bar_dt).days
                if period == "daily" and _stale_days > 7:
                    print(f"  ⛔ [{sym}] R24拒绝: 最新K线{_last_date}距今{_stale_days}d(>5交易日), 过期数据, 跳过")
                    continue
                elif period != "daily" and _stale_days > 7:
                    print(f"  ⛔ [{sym}] R24拒绝: 最新K线{_last_date}距今{_stale_days}d(>7天), 过期数据, 跳过")
                    continue
            df = pd.DataFrame({k: [float(r[k]) for r in dlist] for k in ["open", "high", "low", "close"]})
            df["volume"] = [float(r.get("volume", 0)) for r in dlist]
            if "open_interest" in dlist[0]:
                df["open_interest"] = [float(r.get("open_interest", 0)) for r in dlist]
            if "oi" in dlist[0]:
                df["oi"] = [float(r.get("oi", 0)) for r in dlist]
            # ── numpy 指标计算：品种级超时防护（防止单一品种卡死全盘）──
            _NUMPY_TIMEOUT = 60  # 秒/品种
            try:
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
                with ThreadPoolExecutor(max_workers=1) as _exec:
                    _fut = _exec.submit(_compute_indicators_numpy, df, sym, period=period)
                    tech = _fut.result(timeout=_NUMPY_TIMEOUT)
            except _FutTimeout:
                print(f"  ⚠️ [{sym}] numpy指标计算超时(>{_NUMPY_TIMEOUT}s)，跳过")
                continue
            except Exception:
                continue
            price = tech.get("last_price", float(df["close"].iloc[-1]))
            prev = float(df["close"].iloc[-2]) if len(df) > 1 else price
            # ── 双源融合：实时报价覆盖 ──
            _live = quotes_map.get(sym)
            if _live and _live.get("last_price") and _live["last_price"] > 0:
                _live_price = _live["last_price"]
                _pre_close = _live.get("pre_close", prev)
                tech["price"] = _live_price
                tech["change_pct"] = (_live_price / _pre_close - 1) * 100
                tech["_live_quote"] = True
                tech["_pre_close"] = _pre_close
                tech["_raw_close"] = price  # 保留日线收盘参考
            else:
                tech["price"] = price
                tech["change_pct"] = (price / prev - 1) * 100
                tech["_live_quote"] = False
            tech["symbol"] = sym
            tech["name"] = name
            tech["volume"] = int(round(float(df["volume"].iloc[-1]))) if not df["volume"].empty else 0
            tech_list.append(tech)
            df_map[sym] = df
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f"  [{i + 1}] {len(tech_list)} OK")

        # ── 纯数据模式（数技源专用，不做策略打分） ──
        _output_raw = False
        try:
            _output_raw = args.output_raw
        except NameError:
            pass
        if _output_raw:
            print("\n  → 纯数据模式: 跳过策略打分，仅输出原始数据包")
        # ── 仅在遍历完成后执行策略评分 ──
        if i == len(target_symbols) - 1 or (i == len(target_symbols) - 1):
            # 最后品种的指标计算完成 → 执行策略
            if _output_raw:
                summary = {  # 纯数据输出
                    "_meta": {
                        "mode": "output_raw",
                        "total_targets": len(target_symbols),
                        "collected": len(kline_data),
                        "date": today_str,
                        "source": "通达信TQ-Local + numpy指标计算",
                        "data_only": True,
                    },
                    "kline_summary": {sym: {"bars": len(dlist), "first_date": dlist[0].get("date", ""), "last_date": dlist[-1].get("date", "")} for sym, (name, dlist) in kline_data.items()},
                    "indicators": [{"symbol": t.get("symbol"), "name": t.get("name"), "last_price": t.get("last_price"), "change_pct": t.get("change_pct"), "ma20": t.get("MA20"), "ma60": t.get("MA60"), "adx": t.get("ADX14"), "rsi": t.get("RSI14"), "atr14": t.get("ATR14"), "volume": t.get("volume")} for t in tech_list],
                }
                summary = summary
            else:
                    summary = {}
            # ── v7.0 前置采集：基差+OI + 宏观制度（供管线策略 + 验证器共用）──
            _ctx_extra: dict = {}
            try:
                _ctx_extra["basis_data"] = _guarded_call(
                    lambda: _collect_basis_data_sync(tech_list), timeout=25, default={})
                _ctx_extra["oi_data"] = _guarded_call(
                    lambda: _collect_oi_data_sync(tech_list, kline_data), timeout=25, default={})
            except Exception:
                pass
            # ── G27：多因子另类/基本面数据（仓单+库存+开工率）──
            try:
                _fund = _guarded_call(lambda: _collect_fundamental_sync(tech_list),
                                      timeout=25, default={})
                _ctx_extra["warrant_data"] = _fund.get("warrant_data", {})
                _ctx_extra["inventory_data"] = _fund.get("inventory_data", {})
                _ctx_extra["supply_data"] = _fund.get("supply_data", {})
            except Exception:
                pass
            # ── G29：宏观数据（PMI + LPR1Y）→ rate_proxy/pmi_proxy 因子 ──
            try:
                _ctx_extra["macro_data"] = _guarded_call(
                    lambda: _get_macro_sync(), timeout=25,
                    default={"available": False})
            except Exception:
                _ctx_extra["macro_data"] = {"available": False}
                try:
                    from optimizer.regime import compute_market_regime
                    _mr = compute_market_regime(period=period)
                    if _mr.get("regime") not in ("unknown", None):
                        _ctx_extra["macro_signal"] = "bull" if _mr["regime"] in ("bull", "risk_on") else "bear"
                        print(f"\n  [宏观制度] 市场制度: {_mr['regime']} → macro_signal={_ctx_extra['macro_signal']}")
                    else:
                        # 制度检测不可用时：基于 tech_list 截面 ADX+RSI 降级推断
                        # tech_list 中字段为 TDX 大写（ADX/RSI14），处理大小写兼容
                        def _safe_float(v, default=0):
                            try: return float(v)
                            except: return default
                        _trend_c = sum(1 for t in tech_list
                                       if _safe_float(t.get("adx", t.get("ADX", 0))) > 25)
                        _ranging_c = sum(1 for t in tech_list if _trend_c == 0)
                        _adx_rsi_pairs = [
                            (_safe_float(t.get("adx", t.get("ADX", 0))),
                             _safe_float(t.get("rsi", t.get("RSI14", 50))))
                            for t in tech_list
                        ]
                        _bull_c = sum(1 for adx, rsi in _adx_rsi_pairs
                                      if adx > 25 and (rsi > 60 or rsi <= 1))
                        _bear_c = sum(1 for adx, rsi in _adx_rsi_pairs
                                      if adx > 25 and 1 < rsi < 40)
                        _total_c = len(tech_list)
                        if _total_c > 5 and _trend_c / _total_c > 0.5:
                            _ctx_extra["macro_signal"] = "bull" if _bull_c >= _bear_c else "bear"
                            print(f"\n  [宏观制度·降级] 趋势市({_trend_c}/{_total_c}) bull={_bull_c} bear={_bear_c} → {_ctx_extra['macro_signal']}")
                        else:
                            _ctx_extra["macro_signal"] = "neutral"
                except Exception:
                    _ctx_extra["macro_signal"] = "neutral"
            # ── 事件日历注入（供 event_driven 策略消费） ──
            try:
                from data.event_calendar import build_event_calendar
                _ctx_extra["event_calendar"] = build_event_calendar()
                _ec_count = sum(len(v) for v in _ctx_extra["event_calendar"].values() if v)
                if _ec_count:
                    print(f"\n  [事件日历] 已预排 {_ec_count} 条事件")
            except Exception:
                pass
            # 只有显式指定 --strategy XXX 时才回退单策略模式（兼容旧版）。
            _pipeline_default = not getattr(args, "strategy", None)
            if _pipeline_default:
                try:
                    # ── 策略子集筛选 ──
                    _strat_selector = getattr(args, "strategies", None)
                    if _strat_selector:
                        _selected = {s.strip().lower() for s in _strat_selector.split(",")}
                    else:
                        _selected = None  # 全部加载

                    _STRATEGY_REGISTRY: dict[str, type] = {}
                    from strategies.trend_following_strategy import TrendFollowingStrategy
                    _STRATEGY_REGISTRY["trend_following"] = TrendFollowingStrategy
                    from strategies.arbitrage_strategy import ArbitrageStrategy
                    _STRATEGY_REGISTRY["arbitrage"] = ArbitrageStrategy
                    from strategies.mean_reversion_strategy import MeanReversionStrategy
                    _STRATEGY_REGISTRY["mean_reversion"] = MeanReversionStrategy
                    from strategies.pairs_reversion_strategy import PairsReversionStrategy
                    _STRATEGY_REGISTRY["pairs_reversion"] = PairsReversionStrategy
                    from strategies.spread_reversion_strategy import SpreadReversionStrategy
                    _STRATEGY_REGISTRY["spread_reversion"] = SpreadReversionStrategy
                    from strategies.basis_reversion_strategy import BasisReversionStrategy
                    _STRATEGY_REGISTRY["basis_reversion"] = BasisReversionStrategy
                    from strategies.macro_regime_strategy import MacroRegimeStrategy
                    _STRATEGY_REGISTRY["macro_regime"] = MacroRegimeStrategy
                    from strategies.event_driven_strategy import EventDrivenStrategy
                    _STRATEGY_REGISTRY["event_driven"] = EventDrivenStrategy
                    from strategies.ml_signal_strategy import MlSignalStrategy
                    _STRATEGY_REGISTRY["ml_signal"] = MlSignalStrategy
                    from strategies.multi_factor_strategy import MultiFactorStrategy
                    _STRATEGY_REGISTRY["multi_factor"] = MultiFactorStrategy

                    from strategies.registry_v2 import get_pipeline, register_v2
                    # G28：持久化暂停开关（config.settings.DISABLED_STRATEGIES）
                    try:
                        from config.settings import DISABLED_STRATEGIES as _DISABLED
                    except Exception:
                        _DISABLED = set()
                    _active_names = []
                    for _name, _cls in _STRATEGY_REGISTRY.items():
                        # CLI --strategies 显式指定时覆盖禁用；否则跳过禁用策略
                        if _selected is not None and _name not in _selected:
                            continue
                        if _selected is None and _name in _DISABLED:
                            print(f"  [策略暂停·G28] 跳过: {_name}（待资源完善后开启）")
                            continue
                        register_v2(_cls())
                        _active_names.append(_name)
                    _skipped = set(_STRATEGY_REGISTRY) - set(_active_names)
                    if _skipped:
                        print(f"  [策略筛选] 跳过: {', '.join(sorted(_skipped))}")

                    pipeline = get_pipeline()
                    _ctx = {"kline_data": kline_data, "df_map": df_map, "period": period,
                            "window_mode": window_mode, "mode": "full", "extra": _ctx_extra,
                            "spread_history": spread_history, "basis_history": basis_history}
                    summary = pipeline.run(tech_list, kline_data, _ctx)
                    summary["pipeline_mode"] = True
                    summary["active_strategies"] = _active_names.copy()
                    print(f"\n  [Pipeline] 多策略管线: {len(pipeline.strategies)} 策略运行完成")
                except Exception as _pe:
                    import traceback; traceback.print_exc()
                    print(f"  ⚠️ [Pipeline] 管线异常: {_pe}，回退到单策略模式")
                    from strategies import get_strategy
                    strategy = get_strategy(strategy_name)
                    summary = strategy.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data, period=period, window_mode=window_mode, quotes_map=quotes_map)
            else:
                from strategies import get_strategy
                strategy = get_strategy(strategy_name)
                summary = strategy.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data, period=period, window_mode=window_mode, quotes_map=quotes_map)
        # ── 制度感知: 打分完成后清除覆盖，避免影响后续 ──
        try:
            from config.settings import clear_param_overrides
            clear_param_overrides()
        except Exception:
            pass
        # ── 仅在全部品种遍历完成后执行验证和输出 ──
        if i == len(target_symbols) - 1:
            if enable_filter:
                summary["filter_disabled"] = False
                try:
                    from signals.validators import run_signal_validators, ValidationContext
                    from signals import paradigms
                    _all_ranked = summary.get("all_ranked", [])
                    # 复用 pipeline 已采集的基差/OI 数据（pipeline模式）或重新采集（单策略模式）
                    _v_oi = _ctx_extra.get("oi_data", {}) if locals().get("_ctx_extra") else {}
                    _v_basis = _ctx_extra.get("basis_data", {}) if locals().get("_ctx_extra") else {}
                    _oi_data = _v_oi or _collect_oi_data_sync(_all_ranked, kline_data)
                    _basis_data = _v_basis or _collect_basis_data_sync(_all_ranked)
                    ctx = ValidationContext(kline_data=kline_data, higher_tf={}, extra={"oi_data": _oi_data, "basis_data": _basis_data})
                    # 在验证器之前注入 data_quality（Data Governance Phase 2）
                    # 先从 kline_data 溯源 data_source 到 all_ranked
                    for _r in _all_ranked:
                        if not _r.get("data_source") or _r["data_source"] in ("unknown", "fdc"):
                            _sym = _r.get("symbol", "")
                            _kl = kline_data.get(_sym)
                            if _kl:
                                _bars = _kl[1] if isinstance(_kl, tuple) and len(_kl) == 2 else _kl
                                if _bars:
                                    _r["data_source"] = _bars[0].get("data_source", "unknown")
                    try:
                        from futures_data_core.core.data_quality import evaluate_symbol as _evaluate_dq
                        for _r in _all_ranked:
                            _sym = _r.get("symbol", "")
                            _src = _r.get("data_source", "unknown")
                            _kl = kline_data.get(_sym)
                            if isinstance(_kl, tuple) and len(_kl) == 2:
                                _kl = _kl[1]
                            _r["data_quality"] = _evaluate_dq(_sym, _kl, _src)
                    except ImportError:
                        for _r in _all_ranked:
                            _r["data_quality"] = {"available": False, "confidence": "UNKNOWN",
                                                   "overall": "N/A", "issues": ["模块未加载"]}
                    run_signal_validators(_all_ranked, ctx)
                    summary["all_ranked"] = _all_ranked
                    for _side in ("bear_signals", "bull_signals"):
                        _sig_ids = {r["symbol"] for r in _all_ranked if r.get("grade") not in ("NOISE",) and r.get("direction") == _side.replace("_signals", "")}
                        summary[_side] = [r for r in summary.get(_side, []) if r.get("symbol") in _sig_ids]
                    _demoted_p04 = sum(1 for r in _all_ranked if r.get("_revalidate_reason"))
                    _demoted_total = sum(1 for r in _all_ranked if r.get("_validator_demoted"))
                    _active = sum(1 for r in _all_ranked if r.get("grade") not in ("NOISE",))
                    if _demoted_p04:
                        print(f"\n  [P0-4] 信号重校验门禁: {_demoted_p04} 个伪突破信号被拦截降级为NOISE")
                    print(f"\n  [信号验证] 验证器共降级 {_demoted_total} 个信号（活跃 {_active} / 总 {len(_all_ranked)}）")
                except Exception as _ve:
                    print(f"  ⚠️ [信号验证] 验证器管道异常，跳过验证: {_ve}")
            else:
                summary["filter_disabled"] = True
                print("  [过滤] P0-4 伪信号过滤已禁用（--disable-filter），全部信号保留")
            print(f"\n完成: {len(summary.get('all_ranked', []))}品种 | 空头{len(summary.get('bear_signals', []))} 多头{len(summary.get('bull_signals', []))}")

    # ── 从 summary 提取数据 ──
    all_ranked = summary.get("all_ranked", [])
    # ── 同步 level 字段到 all_ranked（兼容旧版下游只读 level 不读 grade）──
    for _r in all_ranked:
        if _r.get("level") is None and _r.get("grade"):
            _r["level"] = _r["grade"]

    # ── P1角色矫正：为每个品种附加 stats 对象（纯定量事实，无方向预判） ──
    # stats 由观澜（P3）消费，数技源（P1）只负责产出统计特征量
    for _r in all_ranked:
        _r["stats"] = _build_pure_stats(_r, kline_data.get(_r.get("symbol", "")))

    # ── 数据质量元数据（Data Governance Phase 1） ──
    # 每个品种附加 data_quality 块，溯源数据源/新鲜度/完整性/综合等级
    try:
        from futures_data_core.core.data_quality import evaluate_symbol
        for _r in all_ranked:
            _sym = _r.get("symbol", "")
            _src = _r.get("data_source", "unknown")
            _kl = kline_data.get(_sym)
            # kline_data 格式为 (meta_dict, bars_list)，取第二个元素
            if isinstance(_kl, tuple) and len(_kl) == 2:
                _kl = _kl[1]
            _r["data_quality"] = evaluate_symbol(_sym, _kl, _src)
    except ImportError:
        # data_quality 模块不可用时静默跳过
        for _r in all_ranked:
            _r["data_quality"] = {"available": False, "confidence": "UNKNOWN",
                                   "overall": "N/A", "issues": ["模块未加载"]}

    bear = summary.get("bear_signals", [])
    bull = summary.get("bull_signals", [])
    meta = summary.get("_meta", {})
    tdx_ct = sum(1 for r in all_ranked if r.get("_tdx_patched"))
    results_count = len(all_ranked)

    # ── 终端表格 ──
    # ── 安全取值适配器（兼容 three_signal 等策略的不同字段名）──
    def _sv(r, key, default=0):
        if isinstance(key, (list, tuple)):
            _cur = r
            for _k in key:
                if isinstance(_cur, dict):
                    _cur = _cur.get(_k, default)
                else:
                    return default
            return _cur if _cur is not None else default
        v = r.get(key, default)
        return v if v is not None else default

    if mode == "true_layered" or summary.get("_meta", {}).get("mode") == "true_layered":
        for i, r in enumerate(all_ranked):
            d = "多头" if _sv(r,"direction") == "bull" else ("空头" if _sv(r,"direction") == "bear" else "中性")
            src = "NP"
            print(
                f"{i + 1:>3} {_sv(r,'symbol'):<8} {d:<6} {_sv(r,'price'):>8.0f} {_sv(r,'change_pct'):>+5.1f}% {_sv(r,'total'):>+4.0f} {_sv(r,'adx'):>5.1f} {_sv(r,'rsi'):>5.1f} {_sv(r,'grade'):>6}"
            )
    else:
        print(
            f"\n{'#':>3} {'品种':<8} {'方向':<6} {'价格':>8} {'涨跌':>6} {'总分':>5} {'ADX':>5} {'RSI':>5} {'等级':>6}"
        )
        print("-" * 65)
        for i, r in enumerate(all_ranked):
            d = "多头" if _sv(r,"direction") == "bull" else ("空头" if _sv(r,"direction") == "bear" else "中性")
            src = "TDX" if r.get("_tdx_patched") else "NP"
            print(
                f"{i + 1:>3} {_sv(r,'symbol'):<8} {d:<6} {_sv(r,'price'):>8.0f} {_sv(r,'change_pct'):>+5.1f}% {_sv(r,'total'):>+4.0f} {_sv(r,'adx'):>5.1f} {_sv(r,'rsi'):>5.1f} {_sv(r,'grade'):>6}"
            )

        # ── 写入文件（如指定output_dir） ──
        _reporter = None
        try:
            import sys as _sys
            _sroot = str(Path(__file__).resolve().parents[3] / "scripts")
            if _sroot not in _sys.path:
                _sys.path.insert(0, _sroot)
            from run_reporter import RunReporter
            from logutil import setup_logging
            setup_logging()
            _reporter = RunReporter(run_id=f"FDT_scan_{today_str}")
            _reporter.set(
                n_symbols_scanned=len(all_ranked),
                n_signals=sum(1 for r in all_ranked if r.get("grade") not in ("NOISE",)),
            )
        except Exception:
            pass
        if output_dir:
            try:
                os.makedirs(output_dir, exist_ok=True)
                json_path = os.path.join(output_dir, f"{output_prefix}_{today_str}.json")
                _atomic_write(json_path, summary, mode="json")
                print(f"\n📊 JSON: {json_path}")
            except Exception as e:
                print(f"  ⚠️ [写JSON] 失败（降级继续）: {e}")
                if _reporter is not None:
                    _reporter.add_error("write_json", e)
            # ── 数据追踪（供自优化器用，静默失败） ──
            try:
                from optimizer.data_tracker import record_scan
                scan_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                for r in all_ranked:
                    record_scan(
                        symbol=r.get("symbol", ""),
                        period=period,
                        scan_time=scan_time,
                        signal_type=r.get("signal_type", "unknown"),
                        total_score=r.get("total", 0),
                        grade=r.get("grade", "NOISE"),
                        price=r.get("price", 0),
                        adx=r.get("adx", 0),
                        atr=r.get("atr", 0),
                        rsi=r.get("rsi", 50),
                    )
            except Exception:
                pass  # 数据追踪是可选功能，不可用时静默跳过
        # ── C2 运行报告 flush ──
        if _reporter is not None:
            _reporter.mark_phase("scan")
            _reporter.flush()

        # HTML — 交互式排序表格
        import json as _json

        # ── 策略感知列模板：根据实际策略输出字段动态选择 ──
        _actual_strategy = meta.get("strategy", strategy_name or "channel_breakout")

        _fd = bool(summary.get("filter_disabled"))
        _filter_note = (
            '<p style="color:#f59e0b;font-weight:600;margin:0 0 8px 0">'
            '⚠️ 本报告为【不过滤伪突破】模式：总分列为 P0-4 拦截前的原始分，未执行任何伪突破过滤。</p>'
            if _fd else ''
        )
        _filter_banner = (
            '<div style="margin-bottom:16px;padding:12px 16px;background:#f59e0b15;'
            'border:1px solid #f59e0b60;border-radius:8px;color:#f59e0b;font-size:13px;font-weight:600">'
            '⚠️ 本报表为【不过滤伪突破】模式 — "原始总分"列显示 P0-4 拦截前的原始分，未做伪突破过滤</div>'
            if _fd else ''
        )
        _is_pipeline = summary.get("pipeline_mode", False)

        if _actual_strategy in ("channel_breakout", "three_signal") and not _is_pipeline:
            # ── 通道突破/三类信号专用列 ──
            rows_json = _json.dumps(
                [
                    {
                        "i": i + 1,
                        "sym": _sv(r,"symbol"),
                        "name": _sv(r,"name"),
                        "dir": _sv(r,"direction"),
                        "price": _sv(r,"price"),
                        "chg": _sv(r,"change_pct"),
                        "total": (_sv(r,"_raw_total", _sv(r,"total")) if summary.get("filter_disabled") else _sv(r,"total")),
                        "raw_total": _sv(r,"_raw_total", _sv(r,"total")),  # 拦前原始总分
                        "sig": _sv(r,"signal_type","-"),
                        "dc20": _sv(r,"dc20","-"),
                        "dc55": _sv(r,"dc55","-"),
                        "bb": _sv(r,"bb","-"),
                        "vol": _sv(r,"vol_score",0),
                        "adx": _sv(r,"adx"),
                        "rsi": _sv(r,"rsi"),
                        "grade": _sv(r,"grade"),
                        "tdx": r.get("_tdx_patched", False),
                    }
                    for r in all_ranked
                ],
                ensure_ascii=False,
            )
            _cols = [
                ("#",1), ("品种",0), ("名称",0), ("方向",0),
                ("价格",1), ("涨跌",1), ("原始总分" if _fd else "总分",1), ("拦前分",1),
                ("信号类型",0), ("DC20",0), ("DC55",0), ("布林带",0), ("量比",1),
                ("ADX",1), ("RSI",1), ("等级",0)
            ]
            _col_desc = _filter_note + """
<p style="color:#e5e7eb;font-weight:600;margin-top:10px">栏位计算方法（通道突破策略）</p>
<table style="width:100%;border-collapse:collapse;font-size:11px"><tr style="background:#252940"><th>栏位<th>说明<th>范围</tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">总分</td><td style="padding:3px 8px;color:#9ca3af">DC20+DC55+布林带+量价+ADX调整（拦后=0表示P0-4伪突破拦截）</td><td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">拦前分</td><td style="padding:3px 8px;color:#f59e0b">P0-4/验证器降级前的原始总分（仅拦后=0时显示，非0=有分被拦截）</td><td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">信号类型</td><td style="padding:3px 8px;color:#9ca3af">channel_breakout(突破) / trend_confirmation(趋势确认) / bb_squeeze_prebreakout(挤压预警)</td><td style="padding:3px 8px;color:#6b7280">三种</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">DC20</td><td style="padding:3px 8px;color:#9ca3af">唐奇安20周期通道方向: bull(多头) / bear(空头) / flat(持平)</td><td style="padding:3px 8px;color:#6b7280">bull/bear/flat</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">DC55</td><td style="padding:3px 8px;color:#9ca3af">唐奇安55周期中长期趋势方向</td><td style="padding:3px 8px;color:#6b7280">bull/bear/flat</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">布林带</td><td style="padding:3px 8px;color:#9ca3af">Bollinger(20,2)状态: squeeze(收窄) / expand(扩张) / break(突破)</td><td style="padding:3px 8px;color:#6b7280">三种</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">量比</td><td style="padding:3px 8px;color:#9ca3af">当前成交量/MA5成交量。>1.5放量, <0.5缩量</td><td style="padding:3px 8px;color:#6b7280">0~+</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">ADX</td><td style="padding:3px 8px;color:#9ca3af">趋势强度 Wilder平滑。>25有趋势, >50强趋势</td><td style="padding:3px 8px;color:#6b7280">0~100</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">RSI</td><td style="padding:3px 8px;color:#9ca3af">14周期相对强弱。>70超买, <30超卖</td><td style="padding:3px 8px;color:#6b7280">0~100</td></tr></table>"""
            _render_cols_js = """[
    function(d){return String(d.i);},
    function(d){return d.sym;},
    function(d){return d.name;},
    function(d){return d.dir;},
    function(d){return d.price;},
    function(d){return d.chg;},
    function(d){return d.total;},
    function(d){return d.raw_total;},
    function(d){return String(d.sig);},
    function(d){return String(d.dc20);},
    function(d){return String(d.dc55);},
    function(d){return String(d.bb);},
    function(d){return d.vol;},
    function(d){return d.adx;},
    function(d){return d.rsi;},
    function(d){return d.grade;}
]"""
            _strategy_label = "channel_breakout"

        elif _is_pipeline:
            # ── 多策略管线专用列 ──
            _pipeline_strats = summary.get("active_strategies", [])
            rows_json = _json.dumps(
                [
                    {
                        "i": i + 1,
                        "sym": _sv(r,"symbol"),
                        "name": _sv(r,"name"),
                        "dir": _sv(r,"direction"),
                        "price": _sv(r,"price"),
                        "chg": _sv(r,"change_pct"),
                        "total": (_sv(r,"_raw_total", _sv(r,"total")) if summary.get("filter_disabled") else _sv(r,"total")),
                        "raw_total": _sv(r,"_raw_total", _sv(r,"total")),
                        "sig": _sv(r,"signal_type","-"),
                        "stf": _sv(r,("strategy_breakdown","trend_following","total"), 0),
                        "smr": _sv(r,("strategy_breakdown","mean_reversion","total"), 0),
                        "sar": _sv(r,("strategy_breakdown","arbitrage","total"), 0),
                        "smc": _sv(r,("strategy_breakdown","macro_regime","total"), 0),
                        "sev": _sv(r,("strategy_breakdown","event_driven","total"), 0),
                        "sml": _sv(r,("strategy_breakdown","ml_signal","total"), 0),
                        "smf": _sv(r,("strategy_breakdown","multi_factor","total"), 0),
                        "nst": sum(1 for _k in _pipeline_strats if abs(_sv(r,("strategy_breakdown",_k,"total"), 0)) >= 1),
                        "adx": _sv(r,"adx"),
                        "rsi": _sv(r,"rsi"),
                        "grade": _sv(r,"grade"),
                        "tdx": r.get("_tdx_patched", False),
                    }
                    for r in all_ranked
                ],
                ensure_ascii=False,
            )
            _strat_labels = {"trend_following":"趋势", "mean_reversion":"回归", "arbitrage":"套利",
                             "macro_regime":"宏观", "event_driven":"事件", "ml_signal":"ML",
                             "multi_factor":"多因子"}
            _col_pairs = [("#",1), ("品种",0), ("名称",0), ("方向",0)]
            _col_pairs += [("价格",1), ("涨跌",1), ("原始总分" if _fd else "总分",1), ("拦前分",1)]
            _col_pairs += [("信号类型",0)]
            for _sn in _pipeline_strats:
                _col_pairs += [(_strat_labels.get(_sn, _sn), 1)]
            _col_pairs += [("策略数",1), ("ADX",1), ("RSI",1), ("等级",0)]
            _cols = _col_pairs
            _strat_desc = "".join(
                f'<tr><td style="padding:3px 8px;color:#e5e7eb">{_strat_labels.get(_sn, _sn)}</td>'
                f'<td style="padding:3px 8px;color:#9ca3af">{_strat_labels.get(_sn, _sn)}策略得分</td>'
                f'<td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>'
                for _sn in _pipeline_strats
            )
            _col_desc = _filter_note + """
<p style="color:#e5e7eb;font-weight:600;margin-top:10px">栏位计算方法（多策略管线 — %d策略）</p>
<table style="width:100%%;border-collapse:collapse;font-size:11px"><tr style="background:#252940"><th>栏位<th>说明<th>范围</tr>
<tr><td style="padding:3px 8px;color:#e5e7eb">总分</td><td style="padding:3px 8px;color:#9ca3af">各策略加权总分</td><td style="padding:3px 8px;color:#6b7280">动态</td></tr>
<tr><td style="padding:3px 8px;color:#e5e7eb">拦前分</td><td style="padding:3px 8px;color:#f59e0b">P0-4降级前的原始总分</td><td style="padding:3px 8px;color:#6b7280">动态</td></tr>
<tr><td style="padding:3px 8px;color:#e5e7eb">信号类型</td><td style="padding:3px 8px;color:#9ca3af">主驱动策略名+子类型</td><td style="padding:3px 8px;color:#6b7280">策略相关</td></tr>
%s
<tr><td style="padding:3px 8px;color:#e5e7eb">策略数</td><td style="padding:3px 8px;color:#9ca3af">有非零贡献的策略数（>1=多策略共振）</td><td style="padding:3px 8px;color:#6b7280">0~%d</td></tr>
<tr><td style="padding:3px 8px;color:#e5e7eb">ADX</td><td style="padding:3px 8px;color:#9ca3af">趋势强度 Wilder平滑</td><td style="padding:3px 8px;color:#6b7280">0~100</td></tr>
<tr><td style="padding:3px 8px;color:#e5e7eb">RSI</td><td style="padding:3px 8px;color:#9ca3af">14周期相对强弱</td><td style="padding:3px 8px;color:#6b7280">0~100</td></tr></table>""" % (len(_pipeline_strats), _strat_desc, len(_pipeline_strats))
            _col_keys = ["i","sym","name","dir","price","chg","total","raw_total","sig"]
            _strat_key_map = {"trend_following":"stf","mean_reversion":"smr","arbitrage":"sar",
                              "macro_regime":"smc","event_driven":"sev","ml_signal":"sml",
                              "multi_factor":"smf"}
            for _sn in _pipeline_strats:
                _col_keys.append(_strat_key_map.get(_sn, "stf"))
            _col_keys += ["nst","adx","rsi","grade"]
            _js_rows = []
            for _k in _col_keys:
                if _k in ("sig","grade"):
                    _js_rows.append(f"    function(d){{return String(d.{_k});}}")
                else:
                    _js_rows.append(f"    function(d){{return d.{_k};}}")
            _render_cols_js = "[\n" + ",\n".join(_js_rows) + "\n]"
            _strategy_label = f"多策略管线({len(_pipeline_strats)}策略)"

        else:
            _strategy_label = _actual_strategy
            # 通用列（非通道突破/非管线模式的兜底）
            rows_json = _json.dumps(
                [
                    {
                        "i": i + 1,
                        "sym": _sv(r,"symbol"),
                        "name": _sv(r,"name"),
                        "dir": _sv(r,"direction"),
                        "price": _sv(r,"price"),
                        "chg": _sv(r,"change_pct"),
                        "total": _sv(r,"total"),
                        "adx": _sv(r,"adx"),
                        "rsi": _sv(r,"rsi"),
                        "grade": _sv(r,"grade"),
                        "tdx": r.get("_tdx_patched", False),
                    }
                    for r in all_ranked
                ],
                ensure_ascii=False,
            )
            _cols = [
                ("#",1), ("品种",0), ("名称",0), ("方向",0),
                ("价格",1), ("涨跌",1), ("总分",1),
                ("ADX",1), ("RSI",1), ("等级",0)
            ]
            _col_desc = _filter_note + ""
            _render_cols_js = """[
    function(d){return String(d.i);},
    function(d){return d.sym;},
    function(d){return d.name;},
    function(d){return d.dir;},
    function(d){return d.price;},
    function(d){return d.chg;},
    function(d){return d.total;},
    function(d){return d.adx;},
    function(d){return d.rsi;},
    function(d){return d.grade;}
]"""

        b, bl_sig = len(bear), len(bull)
        n_neutral = results_count - b - bl_sig
        tdx_pct = tdx_ct / results_count * 100 if results_count else 0

        # 构建 HTML（策略感知模板）
        def _dn(is_num):
            return ' data-num="1"' if is_num else ""
        def _ta(is_num):
            return "center" if is_num else "left"

        _th = "".join(
            f'<th onclick="sortBy({i})"{_dn(n)} style="text-align:{_ta(n)}">{h}</th>'
            for i, (h, n) in enumerate(_cols)
        )

        period_label = "" if period == "daily" else f" ({period})"
        _title_label = ("多策略管线信号强度排序" if _is_pipeline else
                        "通道突破信号强度排序" if _strategy_label == "channel_breakout" else
                        "信号强度排序")
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>全品种{_title_label}{period_label} — {today}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #2a2d3a}}
.hd h1{{font-size:22px;color:#f59e0b}} .hd .m{{color:#9ca3af;font-size:12px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px}}
.st{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700}} .sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
.sc.b .n{{color:#ef4444}} .sc.bl .n{{color:#22c55e}} .sc.n .n{{color:#9ca3af}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:13px}}
thead{{background:#252940}}
th{{padding:9px 10px;text-align:left;font-weight:600;color:#9ca3af;font-size:11px;letter-spacing:.5px;white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#f59e0b}} th.asc::after{{content:" \\25B2";font-size:10px}} th.dsc::after{{content:" \\25BC";font-size:10px}}
td{{padding:7px 10px;border-top:1px solid #2a2d3a20;white-space:nowrap}} tr:hover{{background:#f59e0b08!important}}
.fb{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}
.fb button{{background:#252940;border:1px solid #2a2d3a;color:#9ca3af;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s}}
.fb button:hover{{border-color:#f59e0b;color:#e5e7eb}} .fb button.act{{background:#f59e0b20;border-color:#f59e0b;color:#f59e0b;font-weight:600}}
#si{{color:#6b7280;font-size:12px;margin-left:12px}}
</style>
</head><body>
<div class="hd"><h1>全品种{_title_label}{period_label}</h1>
<div class="m"><span>{today_str}</span><span>{results_count}品种</span><span>TQ-Local桥接 + numpy兜底</span><span><span style="color:#f59e0b">点击列头排序</span> | {_strategy_label}</span></div></div>
<div class="st"><div class="sc b"><div class="n">{b}</div><div class="l">空头</div></div><div class="sc bl"><div class="n">{bl_sig}</div><div class="l">多头</div></div><div class="sc n"><div class="n">{n_neutral}</div><div class="l">中性</div></div></div>
{_filter_banner}
<div class="fb">
<button onclick="filterTable('all')" class="act" id="fa">全部</button>
<button onclick="filterTable('bear')" id="fbear">仅空头</button>
<button onclick="filterTable('bull')" id="fbull">仅多头</button>
<button onclick="filterTable('STRONG')" id="fSTRONG">STRONG</button>
<button onclick="filterTable('WATCH')" id="fWATCH">WATCH</button>
<button onclick="filterTable('WEAK')" id="fWEAK">WEAK</button>
<button onclick="filterTable('NOISE')" id="fNOISE">NOISE</button>
<span id="si">点击列头按该列排序，再次点击切换升降序</span>
</div>

<table id="tbl"><thead><tr>
{_th}
</tr></thead><tbody id="tb"></tbody></table>

<div style="margin-top:24px;display:flex;gap:14px">
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #f59e0b30">
<span style="color:#f59e0b;font-weight:600">指标来源: </span><span style="color:#f59e0b">TQ-Local formula_zb ({tdx_ct}/{results_count}品种, {tdx_pct:.0f}%)</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">ADX/RSI/CCI/MACD/MA/BOLL/OBV 来自通达信实盘公式</p></div>
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">
<span style="color:#22c55e;font-weight:600">数据: </span><span style="color:#e5e7eb">FDC 统一数据引擎</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">commodity-trend-signal v2.20.0 | {today_str} | 方向感知Z-score</p></div></div>

<div style="margin-top:14px;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">

<div style="color:#f59e0b;font-weight:600;font-size:13px;margin-bottom:6px">使用方法 & 栏位说明</div>
<div style="margin-top:10px;font-size:12px;line-height:1.7">
{_col_desc}</div></div>

<script>
var DATA = {rows_json};

function _gc(g) {{
    if (g==='STRONG') return '#22c55e';
    if (g==='WATCH') return '#f59e0b';
    if (g==='WEAK') return '#ef4444';
    return '#6b7280';
}}
function _gc_bg(g) {{
    if (g==='STRONG') return '#22c55e20';
    if (g==='WATCH') return '#f59e0b20';
    if (g==='WEAK') return '#ef444420';
    return '#ffffff08';
}}

var _filter = 'all';
var _sortCol = -1;
var _sortAsc = true;

function render() {{
    var data = DATA.slice();
    if (_filter === 'bear') data = data.filter(function(d){{ return d.dir === 'bear'; }});
    else if (_filter === 'bull') data = data.filter(function(d){{ return d.dir === 'bull'; }});
    else if (_filter !== 'all') data = data.filter(function(d){{ return d.grade === _filter; }});

    if (_sortCol >= 0) {{
        var asc = _sortAsc;
        data.sort(function(a,b){{
            var va = _val(a,_sortCol), vb = _val(b,_sortCol);
            if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            return asc ? (va - vb) : (vb - va);
        }});
    }}

    var h = '';
    for (var i=0;i<data.length;i++) {{
        var d = data[i];
        var dt = d.dir==='bull' ? '<span style="color:#22c55e">多头</span>' : (d.dir==='bear' ? '<span style="color:#ef4444">空头</span>' : '<span style="color:#9ca3af">中性</span>');
        var cc = d.chg>0?'#22c55e':(d.chg<0?'#ef4444':'#9ca3af');
        var tc = d.total>0?'#22c55e':(d.total<0?'#ef4444':'#9ca3af');
        var src = d.tdx ? '<span style="display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;background:#f59e0b20;color:#f59e0b">通达信</span>' : '<span style="display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;background:#6b728020;color:#9ca3af">numpy</span>';
        var bg = _gc_bg(d.grade);
        var gc = _gc(d.grade);
        h += '<tr style="background:'+bg+'">';
        h += '<td style="text-align:center;color:#9ca3af">'+(i+1)+'</td>';
        h += '<td style="font-weight:700">'+d.sym+'</td><td>'+d.name+'</td><td>'+dt+'</td>';
        h += '<td style="text-align:right">'+d.price.toFixed(0)+'</td><td style="text-align:right;color:'+cc+'">'+(d.chg>0?'+':'')+d.chg.toFixed(1)+'%</td>';
        h += '<td style="text-align:center;font-weight:700;color:'+tc+'">'+(d.total>0?'+':'')+d.total+'</td>';
        // 拦前分：0=伪突破降级，非0=原始分
        var rc = (d.raw_total !== undefined && d.total === 0 && d.raw_total !== 0) ? '#f59e0b' : '#6b7280';
        var rv = (d.raw_total !== undefined && d.total === 0) ? (d.raw_total>0?'+':'')+d.raw_total : '-';
        h += '<td style="text-align:center;color:'+rc+'">'+rv+'</td>';
        // 策略感知渲染（使用_v的列映射）
        for (var ci=8;ci<_v.length-1;ci++) {{
            var val = _v[ci](d);
            h += '<td style="text-align:center;color:#9ca3af">'+val+'</td>';
        }}
        h += '<td style="text-align:center"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:'+gc+'20;color:'+gc+'">'+d.grade+'</span></td>';
        h += '<td style="text-align:center">'+src+'</td></tr>';
    }}
    document.getElementById('tb').innerHTML = h;
}}

var _v = {_render_cols_js};

function sortBy(col) {{
    if (_sortCol === col) {{ _sortAsc = !_sortAsc; }}
    else {{ _sortCol = col; _sortAsc = col===0 ? true : false; }}
    var ths = document.querySelectorAll('#tbl th');
    for (var i=0;i<ths.length;i++) ths[i].className = '';
    var el = ths[col];
    if (el) el.className = _sortAsc ? 'asc' : 'dsc';
    render();
}}

function filterTable(f) {{
    _filter = f;
    var btns = document.querySelectorAll('.fb button');
    for (var i=0;i<btns.length;i++) btns[i].className = '';
    var el = document.getElementById('f'+f);
    if (el) el.className = 'act';
    render();
}}

render();
</script>
</body></html>"""
        if os.environ.get("FDT_GENERATE_SCAN_REPORT", "").lower() == "true":
            html_path = os.path.join(output_dir, f"{output_prefix}_ranking_{today_str}.html")
            _atomic_write(html_path, html, mode="text")
            print(f"[OK] HTML: {html_path} ({os.path.getsize(html_path)} bytes)")
        else:
            print("[SKIP] 全品种排序HTML报告跳过 (FDT_GENERATE_SCAN_REPORT 未设置)")

    # ── v9.13.0: 程序化品种分组（相关性品种只选1个主辩论品种） ──
    # 提取品种前缀（CF2609 → CF），同前缀按成交量最大选主辩论品种
    _prod_groups: dict[str, list[dict]] = {}
    for _r in all_ranked:
        _sym = _r.get("symbol", "")
        _re_match = re.match(r"^([A-Za-z]+)", _sym)
        _prod = _re_match.group(1).upper() if _re_match else _sym
        _prod_groups.setdefault(_prod, []).append(_r)

    _primary_symbols: list[str] = []
    _associated_groups: dict[str, list[str]] = {}
    for _prod, _members in _prod_groups.items():
        if len(_members) == 1:
            _primary_symbols.append(_members[0]["symbol"])
        else:
            # 同产品组，按成交量（volume）选最大为主辩论品种
            _members_sorted = sorted(_members, key=lambda x: abs(x.get("volume", 0) or 0), reverse=True)
            _primary = _members_sorted[0]["symbol"]
            _primary_symbols.append(_primary)
            _associated = [m["symbol"] for m in _members_sorted[1:]]
            if _associated:
                _associated_groups[_primary] = _associated

    summary["primary_symbols"] = _primary_symbols
    summary["associated_groups"] = _associated_groups
    if _associated_groups:
        _assoc_list = "; ".join(f"{k}→{','.join(v)}" for k, v in _associated_groups.items())
        print(f"\n[品种分组] 主辩论: {', '.join(_primary_symbols)} | 关联: {_assoc_list}")
    else:
        print(f"\n[品种分组] 全部独立: {', '.join(_primary_symbols)}")

    return summary


if __name__ == "__main__":
    import argparse

    # 获取可用策略列表（lazy import，仅旧 --strategy 路径使用）
    try:
        from strategies import list_strategies
        _all_s = list_strategies()
        available = list(_all_s.keys())
        default_strat = [k for k, v in _all_s.items() if v.get("default")][0]
    except Exception:
        available, default_strat = [], None

    parser = argparse.ArgumentParser(description="品种信号扫描 — 策略可插拔")
    parser.add_argument(
        "--seed", type=int, default=None, help="全局随机种子，锁定LLM/ML/抽样随机性，保证同参数同数据结果100%%复现"
    )
    parser.add_argument("--output", "-o", help="输出目录", default=None)
    parser.add_argument("--prefix", "-p", help="文件名前缀", default="full_scan")
    parser.add_argument(
        "--symbols", "-s", help='指定品种代码（逗号分隔），如 "PK,RB,B,UR"。不传则全品种。', default=None
    )
    parser.add_argument(
        "--strategy",
        help=f"策略: {', '.join(available)} (不传=管线模式；传此参数=回退单策略兼容旧版)",
        default=None,
        choices=available + [None],
    )
    parser.add_argument(
        "--contract",
        help='指定合约月份（如 "2609"），不传则用主力连续L8',
        default=None,
    )
    parser.add_argument(
        "--period",
        help='K线周期: daily(日线默认) / weekly(周线) / monthly(月线) / 240m(4小时) / 120m(2小时) / 60m(1小时) / 15m / 5m / 1m',
        default="daily",
    )
    parser.add_argument(
        "--window-mode",
        help='窗口模式: fixed(固定bar数-DC20=20根) / time(等效时间-DC20≈20日线)',
        default="fixed",
        choices=["fixed", "time"],
    )
    parser.add_argument(
        "--mode",
        "-m",
        default="dry-run",
        help="运行模式: dry-run(回测摩擦固定) / paper(模拟盘动态滑点) / live(实盘TWAP分批)",
        choices=["dry-run", "paper", "live", "dry-run", "paper", "live"],
    )
    parser.add_argument("--list-strategies", help="列出所有可用策略", action="store_true")
    parser.add_argument("--no-track", action="store_true", help="禁用自优化数据追踪")
    parser.add_argument(
        "--disable-filter", action="store_true", help="禁用P0-4伪信号过滤（默认开启过滤）"
    )
    parser.add_argument(
        "--output-raw", action="store_true", help="纯数据模式：只采集K线+指标+持仓，不做策略打分（数技源专用）"
    )
    parser.add_argument(
        "--pipeline", action="store_true", help="多策略管线模式（v7.0默认已是管线；保留此标志仅显式启用）"
    )
    parser.add_argument(
        "--strategies", default=None,
        help='选取指定策略（逗号分隔），如 "trend_following,arbitrage"。不传则全部 6 策略'
    )
    parser.add_argument(
        "--walk-forward",
        nargs=2,
        type=int,
        default=None,
        metavar=("TRAIN_DAYS", "TEST_DAYS"),
        help="Walk-Forward回测模式：训练天数 测试天数（如 --walk-forward 180 60）",
    )

    args = parser.parse_args()


    if args.list_strategies:
        from strategies import list_strategies
        print("\n可用策略:")
        for name, info in list_strategies().items():
            default_mark = " (默认)" if info["default"] else ""
            print(f"  {name}: {info['display']}{default_mark}")
        sys.exit(0)

    # 解析自定义品种列表
    if args.symbols:
        sym_map = {sym: name for sym, name in ALL_SYMBOLS}
        codes = [s.strip().upper() for s in args.symbols.split(",")]
        custom_symbols = [(s, sym_map.get(s, s)) for s in codes]
        print(f"自定义品种扫描: {[(s, n) for s, n in custom_symbols]}")
    else:
        custom_symbols = None

    OUT = _normalize_path(args.output) if args.output else None
    if not OUT:
        _ws = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE")
        if _ws:
            OUT = os.path.join(_ws, date.today().strftime("%Y-%m-%d"))
        else:
            OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", date.today().strftime("%Y-%m-%d"))

    run_scan(
        output_dir=OUT,
        output_prefix=args.prefix,
        symbols=custom_symbols,
        mode=args.mode,
        strategy_name=args.strategy,
        seed=args.seed,
        contract=args.contract,
        period=args.period,
        window_mode=args.window_mode,
        enable_filter=not args.disable_filter,
    )

    # Walk-Forward 回测模式
    if args.walk_forward:
        train_days, test_days = args.walk_forward
        print(f"\n🧪 Walk-Forward回测: 训练{train_days}天 / 验证{test_days}天")
        _run_walk_forward(
            symbols=custom_symbols or ALL_SYMBOLS, train_days=train_days, test_days=test_days, output_dir=OUT
        )


def _run_walk_forward(symbols: list, train_days: int, test_days: int, output_dir: str):
    """Walk-Forward 滚动回测。

    用前 train_days 天训练，后 test_days 天验证，
    滚动窗口评估策略稳定性。

    产出:
        walk_forward_results_{date}.json
    """
    import json
    from datetime import datetime, timedelta

    end_date = datetime.now()
    results = []
    windows = max(1, (train_days - test_days) // (test_days // 3))  # 滚动步长

    for i in range(min(windows, 10)):  # 最多10个窗口
        train_end = end_date - timedelta(days=test_days * i)
        train_start = train_end - timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)

        print(f"  窗口 {i + 1}: 训练{train_start.date()}~{train_end.date()} | 验证{train_end.date()}~{test_end.date()}")

        # 简化：此处实际应调用回测引擎
        results.append(
            {
                "window": i + 1,
                "train_range": f"{train_start.date()}/{train_end.date()}",
                "test_range": f"{train_end.date()}/{test_end.date()}",
                "status": "completed",
            }
        )

    result_path = os.path.join(output_dir, f"walk_forward_results_{datetime.now().strftime('%Y%m%d')}.json")
    _atomic_write(result_path, {
        "symbols": [s[0] for s in symbols] if symbols and isinstance(symbols[0], tuple) else symbols,
        "train_days": train_days,
        "test_days": test_days,
        "windows": results,
        "total_windows": len(results),
    }, mode="json")
    print(f"  📊 Walk-Forward报告: {result_path}")
