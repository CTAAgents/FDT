"""优化器 CLI 入口 — 品种×周期参数自优化

用法:
  # 状态查询
  python -m scripts.optimizer.run --status                    # 数据统计

  # 实时辩论数据优化（需要积累辩论记录）
  python -m scripts.optimizer.run --optimize                   # 全品种优化
  python -m scripts.optimizer.run --symbol rb --optimize       # 单品种优化

  # ★ 历史回测优化（无需等待辩论数据，立即开始）
  python -m scripts.optimizer.run --backtest                   # 全品种日线WF回测优化
  python -m scripts.optimizer.run --backtest --period daily    # 同上（全品种日线）
  python -m scripts.optimizer.run --backtest --period 60m      # 全品种60分钟线
  python -m scripts.optimizer.run --backtest --symbol rb       # 单品种日线
  python -m scripts.optimizer.run --backtest --auto-write      # 优化后自动写入配置
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from config.symbols import ALL_SYMBOLS
from optimizer.data_tracker import get_stats
from optimizer.param_optimizer import analyze_symbol_patterns, optimize_symbol


def cmd_status():
    """显示数据统计"""
    stats = get_stats()
    print("\n" + "=" * 55)
    print("  自优化数据统计")
    print("=" * 55)
    print(f"  总训练记录: {stats['total_records']}")
    print(f"  已辩论: {stats['debated']}")
    print(f"  已出结果: {stats['with_outcome']}")
    print(f"  覆盖品种: {stats['symbols_covered']}")
    print()

    for sym_name, _ in ALL_SYMBOLS:
        s = get_stats(symbol=sym_name)
        if s["total_scans"] > 0:
            print(f"  {sym_name:4s}: {s['total_scans']:3d}次扫描, "
                  f"{s['debated']}次辩论, {s['with_outcome']}次已出结果")


def cmd_analyze(symbol: str, period: str = "daily"):
    """分析单个品种"""
    analyze_symbol_patterns(symbol, period, verbose=True)


def cmd_optimize(symbol: Optional[str] = None, period: str = "daily",
                 auto_write: bool = False):
    """执行实时辩论数据优化"""
    if symbol:
        result = optimize_symbol(symbol, period, auto_write=auto_write, verbose=True)
        if result:
            print(f"\n  ✅ {symbol} 优化完成")
    else:
        print("\n" + "=" * 55)
        print("  全品种参数优化")
        print("=" * 55)
        results = []
        for sym_name, _ in ALL_SYMBOLS:
            result = optimize_symbol(sym_name, period, auto_write=auto_write, verbose=False)
            if result:
                results.append(result)

        if results:
            print(f"\n  完成: {len(results)}/{len(ALL_SYMBOLS)} 品种有足够样本")
            for r in results:
                status = "已写入" if r["auto_written"] else "未写入"
                print(f"  {r['symbol']}: 样本={r['samples']} "
                      f"当前胜率={r['current']['win_rate']:.0%} "
                      f"最优={r['best']['param']} {status}")
        else:
            print("\n  ⚠ 没有品种有足够的训练数据（至少需5个有效样本）")


def cmd_backtest(symbol: Optional[str] = None, period: str = "daily",
                 auto_write: bool = False):
    """执行历史回测优化"""
    from optimizer.backtest_optimizer import optimize_period

    symbols = [(sym, name) for sym, name in ALL_SYMBOLS
               if symbol is None or sym == symbol]

    results = optimize_period(
        period=period,
        symbols=symbols,
        auto_write=auto_write,
        verbose=True,
    )

    # 打印汇总
    if results:
        print(f"\n{'='*55}")
        print(f"  优化汇总 — {period}")
        print(f"{'='*55}")
        for r in sorted(results, key=lambda x: x.get("test_metrics", {}).get("accuracy", 0), reverse=True):
            tm = r.get("test_metrics", {})
            tr = r.get("train_metrics", {})
            params = r.get("params", {})
            param_str = "; ".join(f"{s}={dict(v)}" for s, v in params.items()) if params else "N/A"
            print(f"  {r['symbol']:4s}: 训练={tr.get('accuracy',0):.0%} "
                  f"测试={tm.get('accuracy',0):.0%} "
                  f"信号={tm.get('signals',0)} "
                  f"pnl={tm.get('avg_pnl',0):.2f} | {param_str}")
    else:
        print("\n  ⚠ 所有品种数据不足，无法优化")


# ── 监测配置更新（方案B: 从 Signal/update_monitoring_config.py 整合进 FDT CLI） ──
def cmd_update_monitoring_config(config_out: str, period: str = "all",
                                  light: bool = False):
    """运行 WF 优化 → 重建 monitoring_symbols.json（写入 config_out）

    品种宇宙单一来源: ALL_SYMBOLS (config/symbols.py)。
    优化参数镜像自洽写入本目录 optimized_params.json（不再硬编码用户目录）。
    本函数即原 Signal 侧 update_monitoring_config.py 的全部核心逻辑，已迁移至此。
    """
    from config.settings import CHANNEL_BREAKOUT_CONFIG
    from optimizer.backtest_optimizer import optimize_period

    _OPT_DIR = os.path.dirname(os.path.abspath(__file__))  # scripts/optimizer

    # 结构单一来源: 从 backtest_optimizer.WF_CONFIG 派生(冻结+版本化)
    from optimizer.backtest_optimizer import (
        WF_CONFIG,
        WF_CONFIG_VERSION,
        classify_tier,
    )
    TIER_THRESHOLDS = {
        per: {"good": WF_CONFIG["tiers"][per]["good"],
              "medium": WF_CONFIG["tiers"][per]["medium"]}
        for per in ("daily",)
    }
    CORE_UNIVERSE = set(WF_CONFIG["core_universe"])
    HYSTERESIS_WEEKS = WF_CONFIG["hysteresis_weeks"]
    _STATE_PATH = os.path.join(os.path.dirname(config_out), "monitoring_state.json")

    def _get_name(sym):
        for s, n in ALL_SYMBOLS:
            if s.lower() == sym.lower():
                return n
        return sym

    def _tier(per, acc, signals=0, use_ci=True):
        """基于置信下界定级(替代点估计); 小样本→unknown。
        use_ci=False 时退回点估计(供 --light 重建路径使用)。"""
        if not use_ci:
            t = TIER_THRESHOLDS[per]
            if acc >= t["good"]:
                return "good"
            elif acc >= t["medium"]:
                return "medium"
            return "weak"
        return classify_tier(per, acc / 100.0, signals)

    def _tier_label(per, tier):
        t = TIER_THRESHOLDS[per]
        return {
            "good": f"优质（≥{t['good']}%）",
            "medium": f"中等（{t['medium']}-{t['good']-1}%）",
            "weak": f"弱信号（<{t['medium']}%）",
            "unknown": f"未知（样本不足{WF_CONFIG['min_test_signals_for_ci']}）",
        }.get(tier, tier)

    def _build_full_symbol_list():
        return [(s, n) for s, n in ALL_SYMBOLS]

    def _save_optimized_params():
        opt_path = os.path.join(_OPT_DIR, "optimized_params.json")
        with open(opt_path, "w", encoding="utf-8") as f:
            json.dump({"per_symbol": CHANNEL_BREAKOUT_CONFIG["per_symbol"]}, f,
                      ensure_ascii=False, indent=2)

    def run_daily_wf():
        print("=" * 55)
        print("  日线 WF — 全62品种")
        print("=" * 55)
        sym_list = _build_full_symbol_list()
        results = optimize_period(period="daily", symbols=sym_list,
                                  auto_write=True, verbose=True)
        _save_optimized_params()
        rv = {}
        for r in results:
            sym = r["symbol"]
            tm = r.get("test_metrics", {})
            acc = round(tm.get("accuracy", 0) * 100)
            sig = tm.get("signals", 0)
            rv[sym] = {"accuracy": acc, "signals": sig,
                       "tier": _tier("daily", acc, sig), "name": _get_name(sym)}
        written = sum(1 for r in results if r.get("test_metrics", {}).get("accuracy", 0) > 0.5)
        print(f"\n  日线完成: {len(results)}/62 品种有结果, {written} 个写入per_symbol\n")
        return rv

    # 120m(2小时线)优化已废弃 — 掌柜 2026-07-11 决策：仅保留日线(daily)优化

    def _load_state():
        if os.path.exists(_STATE_PATH):
            try:
                with open(_STATE_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"version": WF_CONFIG_VERSION, "included": {}, "history": {}}

    def _save_state(state):
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _resolve_inclusion(period, results, state):
        """稳定核心宇宙 + 滞后确认: 返回最终 symbol_list 与 tiers 分组。

        滞后确认: 单周 tier 翻转不直接生效, 需连续 HYSTERESIS_WEEKS 周一致才增删,
        否则维持现状 —— 直接消掉小样本 WF 噪声造成的宇宙抖动。
        unknown(样本不足) → 维持现状, 不触发任何增删。
        """
        if not state.get("included"):
            cur = set()
            if os.path.exists(config_out):
                try:
                    with open(config_out, encoding="utf-8") as f:
                        cur = set(json.load(f).get(period, {}).get("symbol_list", []))
                except Exception:
                    pass
            for s, _ in ALL_SYMBOLS:
                state["included"][s] = (s in cur)
                state["history"].setdefault(s, [])
        new_included = {}
        tiers = {"good": [], "medium": [], "weak": [], "unknown": []}
        for s, n in ALL_SYMBOLS:
            info = results.get(s, {"accuracy": 0, "tier": "weak", "signals": 0})
            tier = info["tier"]
            tiers.setdefault(tier, []).append(s)
            is_core = s.lower() in CORE_UNIVERSE
            cur_in = state["included"].get(s, False)
            desired = cur_in if tier == "unknown" else (tier in ("good", "medium"))
            hist = state["history"].get(s, [])
            if desired == cur_in:
                new_included[s] = cur_in
                state["history"][s] = []
            else:
                hist.append(desired)
                state["history"][s] = hist[-HYSTERESIS_WEEKS:]
                if (len(state["history"][s]) >= HYSTERESIS_WEEKS
                        and all(h == desired for h in state["history"][s])):
                    new_included[s] = desired
                    state["history"][s] = []
                else:
                    new_included[s] = cur_in  # 未达滞后阈值, 维持现状
            if is_core:  # 稳定核心宇宙: 永不自动剔除
                new_included[s] = True
        state["included"] = new_included
        return [s for s in new_included if new_included[s]], tiers

    def build_monitoring_config(daily_results):
        today = datetime.now().strftime("%Y-%m-%d")
        state = _load_state()

        daily_sym_list, daily_tiers = _resolve_inclusion("daily", daily_results, state)
        _save_state(state)

        daily_all = []
        for s, n in ALL_SYMBOLS:
            info = daily_results.get(s, {"accuracy": 0, "tier": "weak", "signals": 0})
            daily_all.append({"symbol": s, "name": n, "wf_accuracy": info["accuracy"],
                              "tier": info["tier"], "in_monitor": s in daily_sym_list})
        daily_config = {
            "all": daily_all,
            "symbol_list": daily_sym_list,
            "tiers": {k: {"label": _tier_label("daily", k), "symbols": daily_tiers.get(k, [])}
                      for k in ("good", "medium", "weak", "unknown")},
        }
        # (120m 配置块已废弃 — 仅保留日线监测配置)
        config = {
            "version": today,
            "wf_config_version": WF_CONFIG_VERSION,
            "_comment": "自动监测品种配置 — WF优化后更新。稳定核心宇宙+滞后确认(连续3周一致才增删), 结构冻结见 WF_CONFIG。每日更新: scan_monitored.py --period daily",
            "daily": daily_config,
        }
        with open(config_out, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        core_n = sum(1 for s, _ in ALL_SYMBOLS if s.lower() in CORE_UNIVERSE)
        print(f"✅ monitoring_symbols.json 已重建 ({today}) -> {config_out}")
        print(f"   日线监测: {len(daily_sym_list)}/{len(ALL_SYMBOLS)} 品种 (核心宇宙 {core_n} 强制包含)")
        print(f"     good={len(daily_tiers.get('good', []))}, medium={len(daily_tiers.get('medium', []))}, "
              f"weak={len(daily_tiers.get('weak', []))}, unknown={len(daily_tiers.get('unknown', []))}")
        return config

    def _light_load_results(per):
        opt_path = os.path.join(_OPT_DIR, "optimized_params.json")
        opt_data = {}
        if os.path.exists(opt_path):
            with open(opt_path, encoding="utf-8") as f:
                opt_data = json.load(f).get("per_symbol", {})
        existing = {}
        if os.path.exists(config_out):
            with open(config_out, encoding="utf-8") as f:
                existing = json.load(f)
        rv = {}
        for s, n in ALL_SYMBOLS:
            sym_entry = opt_data.get(s, {})
            period_cfg = sym_entry.get(per, {})
            acc = 0
            has_existing = False
            for e in existing.get(per, {}).get("all", []):
                if e.get("symbol") == s:
                    existing_acc = e.get("wf_accuracy", 0)
                    if period_cfg:
                        acc = max(existing_acc, TIER_THRESHOLDS[per]["good"])
                    else:
                        acc = existing_acc
                    has_existing = True
                    break
            if not has_existing:
                acc = TIER_THRESHOLDS[per]["good"] + 5 if period_cfg else 0
            rv[s] = {
                "accuracy": acc,
                "signals": 999,  # light 重建路径: 视为可靠, 退回点估计
                "tier": _tier(per, acc, use_ci=False) if acc > 0 else "weak",
                "name": n,
                "has_signal": True,
            }
        print(f"  [轻量] {per}: 从已有数据加载 {len(ALL_SYMBOLS)} 品种结果")
        print(f"         optimized_params.json 中有 {sum(1 for s in opt_data if per in opt_data[s])} 个 {per} 覆盖")
        return rv

    daily_rv = {}
    if period in ("daily", "all"):
        daily_rv = _light_load_results("daily") if light else run_daily_wf()
        print()
    build_monitoring_config(daily_rv)


def cmd_regime(symbol: str, period: str = "daily", out_path: str = None,
               from_json: str = None):
    """计算单品种日频 regime 权重(轻量指标, 仅用于信号权重, 不参与纳入/剔除)

    设计意图: 趋势跟踪"当下是否值得跟"应由当前市况(regime)决定, 而非每周重写
    监测宇宙。本命令用低成本指标(ADX 长期分位 / 波动率比值 / 价格斜率)估算
    regime, 输出权重乘数(0.5~1.5)供 scan_monitored 后续乘到信号总分。
    """
    from optimizer.regime import build_regime_from_kline, compute_regime
    if from_json:
        with open(from_json, encoding="utf-8") as f:
            data = json.load(f)
        adx = data.get("adx", [])
        atr_pct = data.get("atr_pct", [])
        slope = data.get("slope", 0.0)
    else:
        adx, atr_pct, slope = build_regime_from_kline(symbol, period)
    regime, weight = compute_regime(adx, atr_pct, slope)
    result = {"symbol": symbol, "period": period, "regime": regime,
              "weight": weight, "adx_len": len(adx)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description="品种×周期参数自优化器")
    parser.add_argument("--symbol", "-s", type=str, default=None,
                        help="品种代码，不传则全品种")
    parser.add_argument("--period", "-p", type=str, default="daily",
                        help="周期 (daily/60m/15m)")
    parser.add_argument("--optimize", "-o", action="store_true",
                        help="执行实时辩论数据优化")
    parser.add_argument("--backtest", "-b", action="store_true",
                        help="★ 执行历史回测优化（Walk-Forward）")
    parser.add_argument("--auto-write", "-w", action="store_true",
                        help="优化后自动写入 per_symbol 层")
    parser.add_argument("--status", action="store_true",
                        help="显示数据统计")
    parser.add_argument("--update-config", action="store_true",
                        help="运行WF优化并重建监测配置(配合 --config-out)")
    parser.add_argument("--config-out", type=str, default=None,
                        help="monitoring_symbols.json 输出路径(Signal运行配置)")
    parser.add_argument("--light", action="store_true",
                        help="(仅--update-config) 轻量模式: 不重跑WF, 从已有数据重建配置")
    parser.add_argument("--regime", action="store_true",
                        help="计算单品种日频regime权重(轻量, 不参与纳入/剔除)")
    parser.add_argument("--regime-out", type=str, default=None,
                        help="regime结果输出路径(JSON)")
    parser.add_argument("--from-json", type=str, default=None,
                        help="(仅--regime) 从JSON读取预计算序列{adx[],atr_pct[],slope}")

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.update_config:
        if not args.config_out:
            parser.error("--update-config 需要配合 --config-out <path>")
        cmd_update_monitoring_config(args.config_out, args.period, args.light)
    elif args.regime:
        if not args.symbol:
            parser.error("--regime 需要配合 --symbol <代码>")
        cmd_regime(args.symbol, args.period, args.regime_out, args.from_json)
    elif args.backtest:
        cmd_backtest(args.symbol, args.period, args.auto_write)
    elif args.optimize:
        cmd_optimize(args.symbol, args.period, args.auto_write)
    elif args.symbol:
        cmd_analyze(args.symbol, args.period)
    else:
        cmd_status()


if __name__ == "__main__":
    main()
