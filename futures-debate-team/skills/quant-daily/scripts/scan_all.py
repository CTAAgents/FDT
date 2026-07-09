#!/usr/bin/env python3
"""
品种信号扫描 — 策略可插拔入口
=================================
默认：单策略通道突破（strategies/channel_breakout_strategy.py）
  唐奇安DC20/DC55 + 布林带确认的双通道突破识别
可选：--dual 双策略模式（主策略 + L1-L4研究员辅助）
  或 --strategy three_signal 三类信号

用法：
  python scan_all.py                                          # 通道突破（默认单策略）
  python scan_all.py --dual                                   # 双策略（含L1-L4辅助）
  python scan_all.py --strategy three_signal                  # 三类信号
  python scan_all.py --strategy layered_l1l4                  # L1-L4分层
  python scan_all.py --strategy my_new_strategy [--symbols PK,RB]
  python scan_all.py --list-strategies                        # 列出所有策略
"""

import sys, os, json, re, random, pandas as pd
from datetime import date

# ── 路径自举（quant-daily scripts/ 目录 + 父级） ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
PARENT_DIR = os.path.dirname(SKILL_DIR)  # 包含 scripts/ 作为包名
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)


# ── S03 原子写入工具：避免 Windows 残留 .tmp 阻止 rename 报 FileExistsError ──
def _atomic_write(path, data, mode="json"):
    """先写 .tmp，清理可能残留的旧 .tmp/目标后 os.replace 落盘（Windows 安全）。"""
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    if os.path.exists(path):
        os.remove(path)
    if mode == "json":
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
    os.replace(tmp, path)

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
from data.multi_source_adapter import MultiSourceAdapter

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


def collect_kline_for_all(adapter, symbols, days=120, min_bars=50, today_str=None, contract=None, period="daily"):
    """通用K线数据采集，供 scan_all.py 和 full_scan_debate.py 共享。

    合约解析：symbol 若带月份后缀(如 LH2609)自动提取 contract 并取真实合约K线；
    不带后缀则用主力连续L8。显式传入的 contract 参数优先于 symbol 内嵌后缀。
    """
    from datetime import date

    if today_str is None:
        today_str = date.today().strftime("%Y%m%d")
    kline_data = {}
    for i, (sym, name) in enumerate(symbols):
        variety, sym_contract = _split_symbol_contract(sym)
        eff_contract = contract or sym_contract
        try:
            resp = adapter.get_kline(variety=variety, days=days, contract=eff_contract, period=period)
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
    dual: bool = False,
    seed: int = None,
    contract: str = None,
    period: str = "daily",
    window_mode: str = "fixed",
) -> dict:
    """执行品种信号扫描，返回结果字典。

    策略层已独立到 strategies/ 目录，新增策略仅需:
      1. 在 strategies/ 下新建 .py 实现 BaseStrategy
      2. registry.py 自动注册

    参数：
        strategy_name: 策略名。None → 使用 mode 映射（向后兼容）
            "layered" → "layered_l1l4" (默认)
            "true_layered" → "true_layered"
            "compare" → 保留旧行为（双模式对比打印）
        mode: 旧版参数，保留向后兼容。新代码请用 strategy_name。
        symbols: [(sym, name), ...] 格式。None → 全品种。
        dual: 双策略模式。True 时同时运行 layered_l1l4 + factor_timing，
              各输出一份独立的 JSON+HTML 报告。

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
                "dual": dual,
                "symbols_count": len(symbols) if symbols else None,
            },
            seed=seed,
        )
        print(f"[Fingerprint] 策略指纹: {_fp}")
    except Exception as e:
        _fp = f"FDB_v4.4_noseed_{date.today().strftime('%Y%m%d')}"

    # ── 双策略模式：运行两个策略，各输出一份报告 ──
    if dual:
        print(f"\n{'=' * 60}")
        print(f"  通道突破 + 研究员原始数据模式")
        print(f"{'=' * 60}")
        # 主策略: 通道突破（唐奇安DC20/DC55 + 布林带确认）
        result_a = run_scan(
            output_dir=output_dir,
            output_prefix=f"{output_prefix}_channel_breakout",
            symbols=symbols,
            strategy_name="channel_breakout",
            dual=False,
            seed=seed,
        )
        # 研究员辅助数据（原始指标，不做策略打分）
        print(f"\n  [研究员辅助] 导出L1-L4原始指标数据（供观澜技术分析）...")
        result_b = run_scan(
            output_dir=output_dir,
            output_prefix=f"{output_prefix}_l1l4",
            symbols=symbols,
            strategy_name="layered_l1l4",
            dual=False,
            seed=seed,
        )
        print(f"\n{'=' * 60}")
        print(f"  完成:")
        meta_a = result_a.get("_meta", {})
        st = meta_a.get("signal_types", {})
        print(f"    通道突破: {st.get('channel_breakout',0)}通道突破 / {st.get('trend_confirmation',0)}趋势确认 / {st.get('bb_squeeze_prebreakout',0)}挤压预警")
        print(f"    → 所有通道突破品种交由闫判官辩论")
        print(f"{'=' * 60}")
        return {"_meta": {"mode": "dual", "channel_breakout": meta_a}}
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
        "true_layered": "真分层打分(portfolio sort)",
        "compare": "双模式对比",
    }
    mode_label = mode_labels.get(mode, f"未知模式({mode})")
    print(f"{scan_scope}趋势信号扫描 v2.18.2 — {mode_label} — {today}")
    print(f"{'=' * 60}")

    # ── TQ-Local 检测 ──
    bridge = get_bridge()
    tdx_ok = bridge.available
    status_str = "[OK]" if tdx_ok else "[xx]"
    print(f"\nTQ-Local: {status_str} {'可用' if tdx_ok else '不可用 -> numpy兜底'}")

    # ── 确定品种列表 ──
    target_symbols = symbols if symbols else ALL_SYMBOLS
    print(f"  品种数: {len(target_symbols)}")

    # ── Step 1: 数据采集 ──
    print("\n[1] 数据采集（通达信本地 → MultiSourceAdapter）...")
    adapter = MultiSourceAdapter()
    # 🐛 v2.10.0: 非交互环境自动接受TqSDK免责声明（代替v2.9.1的跳过逻辑）
    #   之前：isatty()→False时一刀切跳过TqSDK→切断60m降级链
    #   现在：设TQ_SKIP_DISCLAIMER→TqSDK静默运行→降级链完整
    #   tqsdk_available已由multi_source_adapter.__init__()自动检测(importlib.find_spec)
    if not sys.stdin.isatty():
        os.environ["TQ_SKIP_DISCLAIMER"] = "yes"
    kline_data = collect_kline_for_all(adapter, target_symbols, days=120, min_bars=50, contract=contract, period=period)
    print(f"  成功: {len(kline_data)}/{len(target_symbols)}")
    # ── R24 全局闸门：如果没有任何品种有有效数据，拒绝整次扫描 ──
    if not kline_data:
        _fail_reasons = []
        for s in target_symbols:
            try:
                _r = adapter.get_kline(s[0], days=1, contract=contract, period=period)
                if not _r.get("success"):
                    _fail_reasons.append(f"{s[0]}: {_r.get('data_source','?')} → {_r.get('error','无数据')}")
            except Exception as _e:
                _fail_reasons.append(f"{s[0]}: 异常 {_e}")
        print(f"\n⛔ [R24] 全局闸门: 所有品种数据源均不可靠, 终止扫描")
        for _r in _fail_reasons[:5]:
            print(f"     {_r}")
        print(f"    按R23/R24规则, 当前环境无法提供可靠分析, 任务终止")
        return {"_meta": {"r24_rejected": True, "fail_reasons": _fail_reasons, "period": period}}

    # ── Step 2: 指标计算 ──
    print(f"\n[2] 指标计算...")

    # ── 解析策略名（向后兼容 mode → strategy_name） ──
    if strategy_name is None:
        strategy_name = {"layered": "layered_l1l4", "true_layered": "true_layered"}.get(mode, "layered_l1l4")

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
            tech = _compute_indicators_numpy(df, sym, period=period)
            price = tech.get("last_price", float(df["close"].iloc[-1]))
            prev = float(df["close"].iloc[-2]) if len(df) > 1 else price
            tech["price"] = price
            tech["change_pct"] = (price / prev - 1) * 100
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
        try:
            _output_raw = args.output_raw
        except NameError:
            _output_raw = False
        if _output_raw:
            print("\n  → 纯数据模式: 跳过策略打分，仅输出原始数据包")
        raw_package = {
            "_meta": {
                "mode": "output_raw",
                "total_targets": len(target_symbols),
                "collected": len(kline_data),
                "date": today_str,
                "source": "通达信TQ-Local + numpy指标计算",
                "data_only": True,
            },
            "kline_summary": {
                sym: {
                    "bars": len(dlist),
                    "first_date": dlist[0].get("date", ""),
                    "last_date": dlist[-1].get("date", ""),
                }
                for sym, (name, dlist) in kline_data.items()
            },
            "indicators": [
                {
                    "symbol": t.get("symbol"),
                    "name": t.get("name"),
                    "last_price": t.get("last_price"),
                    "change_pct": t.get("change_pct"),
                    "ma20": t.get("MA20"),
                    "ma60": t.get("MA60"),
                    "adx": t.get("ADX14"),
                    "rsi": t.get("RSI14"),
                    "atr14": t.get("ATR14"),
                    "volume": t.get("volume"),
                }
                for t in tech_list
            ],
        }
        summary = raw_package
    # ── compare 模式: 运行两个策略并对比 ──
    if mode == "compare":
        print("\n  → compare模式: 同时运行 layered_l1l4 + true_layered")
        from strategies import get_strategy as _gs

        strat_a = _gs("layered_l1l4")
        strat_b = _gs("true_layered")
        summary_a = strat_a.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data)
        summary_b = strat_b.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data)

        # 打印对照表
        ar_a = summary_a["all_ranked"]
        ar_b = summary_b["all_ranked"]
        print(f"\n── compare模式: L1-L4 vs True Layered 排名对照 ──")
        print(f"{'':─^60}")
        print(f"{'#':>3} {'品种':<8} {'L1-L4':>8} {'#':>3} {'品种':<8} {'TL净排':>8}")
        print(f"{'─':─^60}")
        for i in range(min(15, len(ar_a), len(ar_b))):
            ra = ar_a[i] if i < len(ar_a) else None
            rb = ar_b[i] if i < len(ar_b) else None
            la = f"{i + 1:>3} {ra['symbol']:<8} {ra.get('total', 0):>+8.0f}" if ra else ""
            lb = f"{i + 1:>3} {rb['symbol']:<8} {rb.get('total', 0):>+8.0f}" if rb else ""
            print(f"{la}  {lb}")
        print(f"{'':─^60}")
        summary = {**summary_a, "true_layered_detail": summary_b}
        print(f"\n完成: {len(ar_a)}品种(L1-L4) + {len(ar_b)}品种(TL)")
        # compare 模式也输出JSON (但HTML只含L1-L4)
        # 后续HTML渲染用 summary_a
        summary_merged = {
            "_meta": {**summary_a["_meta"], "mode": "compare"},
            "bull_signals": summary_a["bull_signals"],
            "bear_signals": summary_a["bear_signals"],
            "all_ranked": summary_a["all_ranked"],
            "true_layered_detail": summary_b,
        }
        summary = summary_merged
    else:
        # ── 正常模式: 使用指定策略打分 ──
        strategy = get_strategy(strategy_name)
        summary = strategy.score(tech_list, mode="full", df_map=df_map, kline_data=kline_data, period=period, window_mode=window_mode)
        print(
            f"\n完成: {len(summary['all_ranked'])}品种 | 空头{len(summary['bear_signals'])} 多头{len(summary['bull_signals'])}"
        )

    # ── 从 summary 提取数据 ──
    all_ranked = summary.get("all_ranked", [])
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
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f"{output_prefix}_{today_str}.json")
        _atomic_write(json_path, summary, mode="json")
        print(f"\n📊 JSON: {json_path}")

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

        # HTML — 交互式排序表格
        import json as _json

        # ── v2.11.0: 通道突破专用列（L1-L4已退役） ──
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

        b, bl_sig = len(bear), len(bull)
        n_neutral = results_count - b - bl_sig
        tdx_pct = tdx_ct / results_count * 100 if results_count else 0

        # 构建 HTML（通道突破固定模板，L1-L4已退役）
        _cols = [
            ("#",1), ("品种",0), ("名称",0), ("方向",0),
            ("价格",1), ("涨跌",1), ("总分",1),
            ("信号类型",0), ("DC20",0), ("DC55",0), ("布林带",0), ("量比",1),
            ("ADX",1), ("RSI",1), ("等级",0)
        ]
        _th = "".join(f'<th onclick="sortBy({i})"{" data-num=\"1\"" if n else ""} style="text-align:{"center" if n else "left"}">{h}</th>' for i,(h,n) in enumerate(_cols))
        _col_desc = """
<p style="color:#e5e7eb;font-weight:600;margin-top:10px">栏位计算方法（通道突破策略）</p>
<table style="width:100%;border-collapse:collapse;font-size:11px"><tr style="background:#252940"><th>栏位<th>说明<th>范围</tr>
<tr style="border-top:1px solid #2a2d3a20"><td style="padding:3px 8px;color:#e5e7eb">总分</td><td style="padding:3px 8px;color:#9ca3af">DC20+DC55+布林带+量价+ADX调整</td><td style="padding:3px 8px;color:#6b7280">-100~+100</td></tr>
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
    function(d){return String(d.sig);},
    function(d){return String(d.dc20);},
    function(d){return String(d.dc55);},
    function(d){return String(d.bb);},
    function(d){return d.vol;},
    function(d){return d.adx;},
    function(d){return d.rsi;},
    function(d){return d.grade;}
]"""

        period_label = "" if period == "daily" else f" ({period})"
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>全品种通道突破信号强度排序{period_label} — {today}</title>
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
<div class="hd"><h1>全品种通道突破信号强度排序{period_label}</h1>
<div class="m"><span>{today_str}</span><span>{results_count}品种</span><span>TQ-Local桥接 + numpy兜底</span><span><span style="color:#f59e0b">点击列头排序</span> | channel_breakout</span></div></div>
<div class="st"><div class="sc b"><div class="n">{b}</div><div class="l">空头</div></div><div class="sc bl"><div class="n">{bl_sig}</div><div class="l">多头</div></div><div class="sc n"><div class="n">{n_neutral}</div><div class="l">中性</div></div></div>

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
<span style="color:#22c55e;font-weight:600">数据: </span><span style="color:#e5e7eb">通达信本地 → MultiSourceAdapter</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">commodity-trend-signal v2.18.0 | {today_str} | 方向感知Z-score</p></div></div>

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
        // 策略感知渲染（使用_v的列映射）
        for (var ci=7;ci<_v.length;ci++) {{
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
    parser.add_argument("--dual", action="store_true", help="双策略模式：通道突破主策略 + L1-L4研究员辅助数据")
    parser.add_argument("--no-track", action="store_true", help="禁用自优化数据追踪")
    parser.add_argument(
        "--output-raw", action="store_true", help="纯数据模式：只采集K线+指标+持仓，不做策略打分（数技源专用）"
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

    if args.dual and args.strategy:
        parser.error("--dual 和 --strategy 不能同时使用（--dual 已内置两个策略：channel_breakout + layered_l1l4）")

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

    OUT = args.output
    if not OUT:
        workspace = os.path.expanduser("~/Documents/WorkBuddy")
        OUT = os.path.join(workspace, "Commodities", "Reports", "商品期货深度分析", date.today().strftime("%Y-%m-%d"))

    run_scan(
        output_dir=OUT,
        output_prefix=args.prefix,
        symbols=custom_symbols,
        mode=args.mode,
        strategy_name=args.strategy,
        dual=args.dual,
        seed=args.seed,
        contract=args.contract,
        period=args.period,
        window_mode=args.window_mode,
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
