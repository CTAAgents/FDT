"""
因子IC计算引擎 — factor_timing 策略的IC追踪框架
=====================================================
计算5个核心因子（ts/mom/inv/skew/pv）的截面Rank IC，
持久化到DuckDB，支持IC衰减加权。

用法:
    python scripts/factor_ic.py                      # 计算最新一日IC
    python scripts/factor_ic.py --date 2026-07-05     # 指定日期
    python scripts/factor_ic.py --list                # 查看IC历史
    python scripts/factor_ic.py --plot                # IC趋势图(需matplotlib)

IC计算流程:
  1. 获取某日各品种的因子暴露值（5因子z-score）
  2. 获取次日收益率
  3. 计算Spearman Rank IC（因子暴露 vs 次日收益）
  4. 存储到DuckDB

作者: factor_timing策略组
日期: 2026-07-05
"""

import sys, os, json, argparse
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

# ── 路径自举 ──
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ── 延迟导入（避免循环依赖） ──
FACTOR_NAMES = ["ts", "mom", "inv", "skew", "pv"]


@dataclass
class FactorICResult:
    """单日IC计算结果"""
    trade_date: str               # 因子暴露日期 YYYY-MM-DD
    factor_name: str              # 因子名
    rank_ic: float                # Spearman Rank IC
    pearson_ic: float             # Pearson IC（参考）
    ic_std: float                 # IC截面标准差
    n_contracts: int              # 有效品种数
    next_day_abs_ret: float = 0  # 次日平均绝对收益（验证信号有效性）


class FactorICTracker:
    """因子IC追踪器 — 计算、存储、加载IC历史"""

    DB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", "futures.db"
    )

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else Path(self.DB_PATH)
        self._db = None

    def _get_db(self):
        """延迟获取DB连接"""
        if self._db is None:
            _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
            if _data_dir not in sys.path:
                sys.path.insert(0, _data_dir)
            from duckdb_store import DuckDBStore, DUCKDB_AVAILABLE
            if not DUCKDB_AVAILABLE:
                raise ImportError("duckdb not installed. pip install duckdb")
            self._db = DuckDBStore(db_path=self.db_path)
            self._init_factor_ic_table()
        return self._db

    def _init_factor_ic_table(self):
        """初始化 factor_ic 表"""
        db = self._get_db()
        db.safe_execute("""
            CREATE TABLE IF NOT EXISTS factor_ic (
                trade_date    DATE    NOT NULL,
                factor_name   VARCHAR NOT NULL,
                rank_ic       DOUBLE,
                pearson_ic    DOUBLE,
                ic_std        DOUBLE,
                n_contracts   INTEGER,
                next_day_abs_ret DOUBLE,
                computed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, factor_name)
            )
        """)

    def compute_rank_ic(
        self,
        factor_series: pd.Series,
        return_series: pd.Series
    ) -> float:
        """
        计算截面Rank IC（Spearman秩相关）。

        参数:
            factor_series: 因子暴露值 Series (index=symbol)
            return_series: 次日收益率 Series (index=symbol)

        返回:
            float: Rank IC 值
        """
        # 对齐索引
        common = factor_series.index.intersection(return_series.index)
        if len(common) < 10:
            return 0.0

        f = factor_series[common].rank()
        r = return_series[common].rank()
        return float(f.corr(r))

    def compute_pearson_ic(
        self,
        factor_series: pd.Series,
        return_series: pd.Series
    ) -> float:
        """计算Pearson IC"""
        common = factor_series.index.intersection(return_series.index)
        if len(common) < 10:
            return 0.0
        return float(factor_series[common].corr(return_series[common]))

    def compute_daily_ic(
        self,
        factor_df: pd.DataFrame,
        return_series: pd.Series,
        trade_date: str
    ) -> List[FactorICResult]:
        """
        计算一日内所有因子的IC。

        参数:
            factor_df: 因子DataFrame (index=symbol, columns=factor_names)
            return_series: 次日收益率 Series (index=symbol)
            trade_date: 交易日字符串

        返回:
            List[FactorICResult]
        """
        results = []
        for col in FACTOR_NAMES:
            if col not in factor_df.columns:
                continue
            fv = factor_df[col]
            rank_ic = self.compute_rank_ic(fv, return_series)
            pearson_ic = self.compute_pearson_ic(fv, return_series)

            # IC截面标准差
            common = fv.index.intersection(return_series.index)
            ic_std = float(fv[common].std()) if len(common) > 1 else 0.0

            results.append(FactorICResult(
                trade_date=trade_date,
                factor_name=col,
                rank_ic=round(rank_ic, 4),
                pearson_ic=round(pearson_ic, 4),
                ic_std=round(ic_std, 4),
                n_contracts=len(common),
                next_day_abs_ret=round(float(return_series[common].abs().mean()), 4),
            ))
        return results

    def save_ic_results(self, results: List[FactorICResult]):
        """持久化IC计算结果到DuckDB"""
        if not results:
            return
        for r in results:
            self._get_db().safe_execute("""
                INSERT OR REPLACE INTO factor_ic
                (trade_date, factor_name, rank_ic, pearson_ic,
                 ic_std, n_contracts, next_day_abs_ret)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [r.trade_date, r.factor_name, r.rank_ic, r.pearson_ic,
                  r.ic_std, r.n_contracts, r.next_day_abs_ret])
        print(f"[IC] 已保存 {len(results)} 条IC记录")

    def load_ic_history(
        self,
        factor_name: str,
        lookback: int = 63
    ) -> np.ndarray:
        """
        加载某个因子的历史IC序列。

        参数:
            factor_name: 因子名 (ts/mom/inv/skew/pv)
            lookback: 回溯天数

        返回:
            ndarray: IC序列，从旧到新排列
        """
        rows = self._get_db().safe_execute("""
            SELECT rank_ic FROM factor_ic
            WHERE factor_name = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [factor_name, lookback]).fetchall()

        if not rows:
            return np.array([])

        # 从旧到新排列
        ics = np.array([r[0] for r in rows][::-1])
        return ics

    def load_all_ic_history(self, lookback: int = 63) -> Dict[str, np.ndarray]:
        """
        加载所有5个因子的历史IC序列。

        返回:
            {factor_name: ndarray}
        """
        history = {}
        for fn in FACTOR_NAMES:
            ics = self.load_ic_history(fn, lookback)
            if len(ics) > 0:
                history[fn] = ics
        return history

    def get_ic_summary(self, days: int = 30) -> pd.DataFrame:
        """
        获取IC汇总统计。

        返回:
            DataFrame: [factor, mean_ic, std_ic, icir, pos_ratio, n_days]
        """
        rows = self._get_db().safe_execute(f"""
            SELECT factor_name,
                   AVG(rank_ic) AS mean_ic,
                   STDDEV(rank_ic) AS std_ic,
                   AVG(rank_ic) / NULLIF(STDDEV(rank_ic), 0) AS icir,
                   SUM(CASE WHEN rank_ic > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS pos_ratio,
                   COUNT(*) AS n_days
            FROM factor_ic
            WHERE trade_date >= CURRENT_DATE - INTERVAL '{days}' DAY
            GROUP BY factor_name
            ORDER BY ABS(mean_ic) DESC
        """).fetchdf()

        if rows.empty:
            return pd.DataFrame()

        rows['factor_name'] = rows['factor_name'].astype(str)
        for col in ['mean_ic', 'std_ic', 'icir']:
            if col in rows.columns:
                rows[col] = rows[col].round(4)
        return rows

    def get_latest_scan_date(self) -> Optional[str]:
        """获取最新一次IC计算的日期"""
        row = self._get_db().safe_execute("""
            SELECT MAX(trade_date) FROM factor_ic
        """).fetchone()
        if row and row[0]:
            return str(row[0])
        return None

    def get_missing_dates(self, lookback: int = 63) -> List[str]:
        """
        获取缺失IC计算的日期列表（用于增量补算）。
        """
        # 获取最近 lookback 天的所有交易日（从K线数据推断）
        rows = self._get_db().safe_execute(f"""
            SELECT DISTINCT trade_date FROM factor_ic
            ORDER BY trade_date DESC
            LIMIT {lookback}
        """).fetchall()
        return [str(r[0]) for r in rows] if rows else []


# ===================== CLI 入口 =====================

def run_daily_ic(
    factor_df: pd.DataFrame,
    return_series: pd.Series,
    trade_date: str,
    tracker: Optional[FactorICTracker] = None
) -> List[FactorICResult]:
    """
    运行单日IC计算（供外部调用）。
    """
    if tracker is None:
        tracker = FactorICTracker()
    results = tracker.compute_daily_ic(factor_df, return_series, trade_date)
    tracker.save_ic_results(results)
    return results


def print_ic_report(history: Dict[str, np.ndarray]):
    """打印IC汇总报告"""
    print("\n" + "=" * 70)
    print("因子IC汇总报告")
    print("=" * 70)
    print(f"{'因子':>8} {'IC均值':>10} {'IC标准差':>10} {'ICIR':>8} {'胜率':>8} {'天数':>6}")
    print("-" * 70)

    for fn in FACTOR_NAMES:
        ics = history.get(fn, np.array([]))
        if len(ics) == 0:
            print(f"{fn:>8} {'N/A':>10} {'N/A':>10} {'N/A':>8} {'N/A':>8} {'0':>6}")
            continue
        ic_mean = np.mean(ics)
        ic_std = np.std(ics)
        icir = ic_mean / ic_std if ic_std > 0 else 0
        pos_ratio = np.sum(ics > 0) / len(ics)
        print(f"{fn:>8} {ic_mean:>+10.4f} {ic_std:>10.4f} {icir:>+8.2f} {pos_ratio:>7.1%} {len(ics):>6}")

    print("-" * 70)
    print("ICIR > 0.3 = 因子有效  |  ICIR > 1.0 = 强因子")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='因子IC计算引擎')
    parser.add_argument('--date', help='交易日 YYYY-MM-DD, 默认最新')
    parser.add_argument('--lookback', type=int, default=63, help='回溯天数')
    parser.add_argument('--list', action='store_true', help='查看IC历史')
    parser.add_argument('--plot', action='store_true', help='绘制IC趋势图')
    parser.add_argument('--init-db', action='store_true', help='仅初始化DB表')
    args = parser.parse_args()

    tracker = FactorICTracker()

    if args.init_db:
        print("[IC] 数据库表已就绪")
        return

    if args.list:
        summary = tracker.get_ic_summary(days=args.lookback)
        if summary.empty:
            print("[IC] 暂无IC数据，请先运行 factor_ic.py")
        else:
            print("\nIC汇总统计 (过去 %d 天):" % args.lookback)
            print(summary.to_string(index=False))

        history = tracker.load_all_ic_history(lookback=args.lookback)
        if history:
            print_ic_report(history)
        return

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            history = tracker.load_all_ic_history(lookback=args.lookback)
            if not history:
                print("[IC] 暂无IC数据")
                return

            fig, axes = plt.subplots(3, 2, figsize=(14, 10))
            axes = axes.flatten()
            for i, (fn, ics) in enumerate(history.items()):
                if i >= len(axes):
                    break
                ax = axes[i]
                ax.plot(ics, label=fn, linewidth=1.5)
                ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
                ax.axhline(y=np.mean(ics), color='red', linestyle='-', alpha=0.7,
                           label=f'mean={np.mean(ics):.4f}')
                ax.fill_between(range(len(ics)), ics, 0, alpha=0.1)
                ax.set_title(f'{fn} IC时序 (ICIR={np.mean(ics)/np.std(ics):.2f})')
                ax.legend(fontsize=8)
                ax.grid(True, alpha=0.3)

            # 累计IC图
            ax = axes[-1] if len(axes) > len(FACTOR_NAMES) else axes[len(FACTOR_NAMES)-1]
            ax.set_visible(False)

            plt.tight_layout()
            output_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                '..', 'ic_trend.png'
            )
            plt.savefig(output_path, dpi=150)
            print(f"[IC] IC趋势图已保存: {output_path}")
        except ImportError:
            print("[IC] 需要matplotlib: pip install matplotlib")
        return

    # 默认：显示已有IC的汇总
    summary = tracker.get_ic_summary(days=args.lookback)
    if summary.empty:
        print("[IC] 暂无IC数据。请先通过 scan_all.py 积累因子数据，\n"
              "     或从外部计算IC后写入DuckDB。")
        print("\n使用方式:")
        print("  查看IC历史:  python scripts/factor_ic.py --list")
        print("  绘制IC图:   python scripts/factor_ic.py --plot")
        print("  初始化DB:   python scripts/factor_ic.py --init-db")
    else:
        print("\nIC汇总统计 (过去 %d 天):" % args.lookback)
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
