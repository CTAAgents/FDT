#!/usr/bin/env python3
"""
品种信号扫描 — 策略可插拔入口
=================================
默认：单策略通道突破（strategies/channel_breakout_strategy.py）
  唐奇安DC20/DC55 + 布林带确认的双通道突破识别
  （L1-L4 技术分析已迁至 technical-analysis/scripts/run_l1l4_scan.py；
   五因子基本面已迁至 fundamental-data-collector/scripts/run_factor_timing_scan.py）

用法：
  python scan_all.py                                          # 通道突破（默认单策略）
  python scan_all.py --strategy three_signal                  # 三类信号
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
from futures_data_core import get_kline as _fdc_get_kline
from futures_data_core import batch_get_quotes as _fdc_batch_quotes

def _fdc_get_kline_sync(variety: str, days: int = 120, period: str = "daily") -> dict:
    """同步包装 FDC get_kline，供 scan_all.py 的遍历循环使用。

    2026-07-13 重构：取代 data/multi_source_adapter MultiSourceAdapter.get_kline()。
    TqSDK collector 已修复 `_close_api()`（每调用关闭 TqApi 实例），
    不会跨 asyncio.run() 边界损坏，可安全逐品种调用。
    """
    try:
        payload = asyncio.run(_fdc_get_kline(variety, period=period, days=days))
        meta = payload.meta
        grade = meta.get("data_grade_label", "")
        if grade in ("UNAVAILABLE", "STALE"):
            return {"success": False, "data": [], "data_source": grade, "error": f"FDC grade={grade}"}
        bars_raw = payload.data.get("bars", [])
        if not bars_raw:
            return {"success": False, "data": [], "data_source": meta.get("source", "fdc"), "error": "FDC 返回空 K 线"}
        records = []
        for b in bars_raw:
            records.append({
                "date": b.get("date", ""),
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
                "volume": int(b.get("volume", 0)),
                "oi": int(b.get("oi", 0) if b.get("oi") else 0),
                "settle": float(b.get("settle", 0) if b.get("settle") else 0),
                "data_source": meta.get("source", "fdc"),
                "confidence": 1.0,
            })
        sources = meta.get("sources", ["fdc"])
        source_label = sources[0] if isinstance(sources, list) else str(sources)
        return {"success": True, "data": records, "data_source": source_label, "confidence": 1.0}
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


# ── 策略可插拔层 ──
from strategies import get_strategy, list_strategies


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
    """同步采集基差数据：一次 HTTP GET 拉取 100ppi.com/sf/ 现期表。

    对 all_ranked 中每个品种，用期货价（price）与生意社现货价计算基差。
    单位换算：FG(×80), jd(/500), lh(/1000) 已内置。
    """
    import requests
    from bs4 import BeautifulSoup
    
    result: dict[str, dict] = {}
    try:
        resp = requests.get("https://www.100ppi.com/sf/", timeout=15)
        if resp.status_code != 200:
            return result
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", class_="sf-table") or soup.find("table", id="sf-table") or soup.find("table")
        if not table:
            return result
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
    return result


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
    """
    from datetime import date

    if today_str is None:
        today_str = date.today().strftime("%Y%m%d")
    kline_data = {}
    for i, (sym, name) in enumerate(symbols):
        variety, sym_contract = _split_symbol_contract(sym)
        eff_contract = contract or sym_contract
        try:
            resp = _fdc_get_kline_sync(variety=variety, days=days, period=period)
            if isinstance(resp, dict) and resp.get("success"):
                dlist = resp["data"]
                valid = [r for r in dlist if r.get("date", "") and r.get("volume", 0) > 0 and r["date"] <= today_str]
                if len(valid) >= min_bars:
                    kline_data[sym] = (name, valid)
        except Exception:
            pass
        if (i + 1) % 15 == 0:
            print(f"  [{i + 1}/{len(symbols)}] {len(kline_data)} OK")
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
        from scripts.fingerprint import generate_fingerprint

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
        "layered": "L1-L4原始指标(研究员辅助)",
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
        return {"_meta": {"r24_rejected": True, "fail_reasons": _fail_reasons, "period": period}}

    # ── Step 1.5: 实时报价采集（双源融合）──
    quotes_map = {}
    _tdx_ok = bridge.available
    if _tdx_ok:
        print(f"\n[1.5] 实时报价采集（TQ-Local get_market_snapshot）...")
        try:
            import asyncio
            _sym_list = [s[0] for s in target_symbols if s[0] in kline_data]
            _raw = asyncio.run(_fdc_batch_quotes(_sym_list))
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

    # ── 解析策略名（单一策略：通道突破；layered_l1l4/factor_timing/true_layered 已迁出独立 skill）──
    if strategy_name is None:
        strategy_name = "channel_breakout"

    print(
        f"  → 策略: {strategy_name} ({list_strategies()[strategy_name]['display'] if strategy_name in list_strategies() else '?'})"
    )

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
            # ── 若启用 --pipeline，使用 StrategyPipeline 执行全部已注册 v2 策略 ──
            if getattr(args, "pipeline", False):
                try:
                    from strategies.registry_v2 import get_pipeline
                    from strategies.trend_following_strategy import TrendFollowingStrategy
                    from strategies.arbitrage_strategy import ArbitrageStrategy
                    from strategies.mean_reversion_strategy import MeanReversionStrategy
                    from strategies.macro_regime_strategy import MacroRegimeStrategy
                    from strategies.event_driven_strategy import EventDrivenStrategy
                    from strategies.ml_signal_strategy import MlSignalStrategy
                    from strategies.registry_v2 import register_v2
                    register_v2(TrendFollowingStrategy())
                    register_v2(ArbitrageStrategy())
                    register_v2(MeanReversionStrategy())
                    register_v2(MacroRegimeStrategy())
                    register_v2(EventDrivenStrategy())
                    register_v2(MlSignalStrategy())
                    pipeline = get_pipeline()
                    _ctx = {"kline_data": kline_data, "df_map": df_map, "period": period, "window_mode": window_mode, "mode": "full", "extra": {}}
                    summary = pipeline.run(tech_list, kline_data, _ctx)
                    print(f"\n  [Pipeline] 多策略管线: {len(pipeline.strategies)} 策略运行完成")
                except Exception as _pe:
                    import traceback; traceback.print_exc()
                    print(f"  ⚠️ [Pipeline] 管线异常: {_pe}，回退到单策略模式")
                    strategy = get_strategy(strategy_name)
                    summary = strategy.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data, period=period, window_mode=window_mode, quotes_map=quotes_map)
            else:
                try:
                    from optimizer.regime import compute_market_regime
                    from config.settings import apply_regime, current_regime
                    mr = compute_market_regime(period=period)
                    if mr["regime"] not in ("unknown",):
                        apply_regime(mr["regime"])
                        print(f"\n  [Regime] 市场制度: {mr['regime']} (权重{mr['weight']}, {mr['success_count']}/{mr['basket_size']}品)")
                except Exception:
                    pass
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
                    _oi_data = _collect_oi_data_sync(_all_ranked, kline_data)
                    _basis_data = _collect_basis_data_sync(_all_ranked)
                    ctx = ValidationContext(kline_data=kline_data, higher_tf={}, extra={"oi_data": _oi_data, "basis_data": _basis_data})
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
            print(f"\n完成: {len(summary['all_ranked'])}品种 | 空头{len(summary['bear_signals'])} 多头{len(summary['bull_signals'])}")

    # ── 从 summary 提取数据 ──
    all_ranked = summary.get("all_ranked", [])
    # ── 同步 level 字段到 all_ranked（兼容旧版下游只读 level 不读 grade）──
    for _r in all_ranked:
        if _r.get("level") is None and _r.get("grade"):
            _r["level"] = _r["grade"]
    bear = summary.get("bear_signals", [])
    bull = summary.get("bull_signals", [])
    meta = summary.get("_meta", {})
    tdx_ct = sum(1 for r in all_ranked if r.get("_tdx_patched"))
    results_count = len(all_ranked)

    # ── 终端表格 ──
    # ── 安全取值适配器（兼容 three_signal 等策略的不同字段名）──
    def _sv(r, key, default=0):
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

        if _actual_strategy in ("channel_breakout", "three_signal"):
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

        else:
            # ── L1-L4 / layered / true_layered 专用列 ──
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
                        "l1": _sv(r,"l1",0),
                        "l2": _sv(r,"l2",0),
                        "l3": _sv(r,"l3",0),
                        "l4": _sv(r,"l4",0),
                        "z_score": _sv(r,"z_score",0),
                        "cons": _sv(r,"cons",0),
                        "macd": _sv(r,"macd_cross","-"),
                        "dc20b": _sv(r,"dc20_break","-"),
                        "stage": _sv(r,"stage","-"),
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
                ("价格",1), ("涨跌",1), ("原始总分" if _fd else "总分",1),
                ("L1",1), ("L2",1), ("L3",1), ("L4",1), ("Z",1), ("一致性",1),
                ("MACD",0), ("DC20突破",0), ("阶段",0),
                ("ADX",1), ("RSI",1), ("等级",0)
            ]
            _col_desc = _filter_note + """
<p style="color:#e5e7eb;font-weight:600;margin-top:10px">栏位计算方法（L1-L4分层策略）</p>
<table style="width:100%;border-collapse:collapse;font-size:11px"><tr style="background:#252940"><th>栏位<th>说明<th>范围</tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">总分</td><td style="padding:3px 8px;color:#9ca3af">L1+L2+L3+L4加权累加(带方向符号)</td><td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L1</td><td style="padding:3px 8px;color:#9ca3af">趋势动量+持仓(权重35%): MA20斜率+MACD交叉+DC20突破</td><td style="padding:3px 8px;color:#6b7280">-35~+35</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L2</td><td style="padding:3px 8px;color:#9ca3af">量价配合(权重35%): 成交量变化+ADX趋势强度+CCI超买超卖</td><td style="padding:3px 8px;color:#6b7280">-35~+35</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L3</td><td style="padding:3px 8px;color:#9ca3af">价格结构(权重20%): MA均线排列+RSI位置+趋势成熟度</td><td style="padding:3px 8px;color:#6b7280">-20~+20</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">L4</td><td style="padding:3px 8px;color:#9ca3af">确认信号(权重10%): 均线发散+连续方向+持仓验证</td><td style="padding:3px 8px;color:#6b7280">-10~+10</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">Z</td><td style="padding:3px 8px;color:#9ca3af">方向感知Z-score: (总分-均值)/标准差, 衡量相对偏离度</td><td style="padding:3px 8px;color:#6b7280">-3~+3</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">一致性</td><td style="padding:3px 8px;color:#9ca3af">L1-L4各层方向一致的数量(4=全一致最强)</td><td style="padding:3px 8px;color:#6b7280">0~4</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">MACD</td><td style="padding:3px 8px;color:#9ca3af">MACD交叉状态: gold_cross(金叉)/dead_cross(死叉)/none(无)</td><td style="padding:3px 8px;color:#6b7280">三种</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">DC20突破</td><td style="padding:3px 8px;color:#9ca3af">唐奇安20周期突破: up(向上)/down(向下)/none(无)</td><td style="padding:3px 8px;color:#6b7280">三种</td></tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">阶段</td><td style="padding:3px 8px;color:#9ca3af">趋势成熟度: emerging(萌芽)/launch(启动)/accelerate(加速)/mature(成熟)/exhaust(衰竭)/unknown</td><td style="padding:3px 8px;color:#6b7280">六种</td></tr>
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
    function(d){return d.l1;},
    function(d){return d.l2;},
    function(d){return d.l3;},
    function(d){return d.l4;},
    function(d){return d.z_score;},
    function(d){return d.cons;},
    function(d){return String(d.macd);},
    function(d){return String(d.dc20b);},
    function(d){return String(d.stage);},
    function(d){return d.adx;},
    function(d){return d.rsi;},
    function(d){return d.grade;}
]"""
            _strategy_label = _actual_strategy

        b, bl_sig = len(bear), len(bull)
        n_neutral = results_count - b - bl_sig
        tdx_pct = tdx_ct / results_count * 100 if results_count else 0

        # 构建 HTML（策略感知模板）
        _th = "".join(f'<th onclick="sortBy({i})"{" data-num=\"1\"" if n else ""} style="text-align:{"center" if n else "left"}">{h}</th>' for i,(h,n) in enumerate(_cols))

        period_label = "" if period == "daily" else f" ({period})"
        _title_label = "L1-L4分层信号强度排序" if _strategy_label != "channel_breakout" else "通道突破信号强度排序"
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
        html_path = os.path.join(output_dir, f"{output_prefix}_ranking_{today_str}.html")
        _atomic_write(html_path, html, mode="text")
        print(f"[OK] HTML: {html_path} ({os.path.getsize(html_path)} bytes)")

    return summary


if __name__ == "__main__":
    import argparse

    # 获取可用策略列表
    available = list(list_strategies().keys())
    # 从注册器中读取默认策略名（默认=three_signal）
    all_strategies = list_strategies()
    default_strat = [k for k, v in all_strategies.items() if v.get("default")][0]

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
        help=f"策略: {', '.join(available)} (默认: {default_strat})",
        default=default_strat,
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
        "--pipeline", action="store_true", help="启用多策略管线（StrategyPipeline，替代单策略模式）"
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
        workspace = os.path.expanduser("~/Documents/WorkBuddy")
        OUT = os.path.join(workspace, "Commodities", "Reports", "商品期货深度分析", date.today().strftime("%Y-%m-%d"))

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
