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
import sys
import os
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPTS_DIR)

from optimizer.data_tracker import get_stats
from optimizer.param_optimizer import analyze_symbol_patterns, optimize_symbol
from config.symbols import ALL_SYMBOLS


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

    args = parser.parse_args()

    if args.status:
        cmd_status()
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
