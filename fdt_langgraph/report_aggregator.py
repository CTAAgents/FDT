"""
全量辩论报告聚合器 — 收集单品种辩论报告，聚合为跨品种全量分析报告。

功能:
  1. ReportAggregator 类，收集所有单品种辩论报告，聚合为全量分析报告
  2. Top-N 排序矩阵：按裁决置信度排序，输出前 N 个品种
  3. 跨品种相关性热力图数据：使用 FDC 数据生成相关性矩阵
  4. 产业链组报告：按产业链分组，输出产业链联动分析
  5. 全量模板回退：无单品种数据时返回空报告

用法:
    aggregator = ReportAggregator(trace_id="xxx")
    aggregator.add_symbol_report("RB", verdict_data, fdc_data)
    full_report = aggregator.generate_full_report()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReportAggregator:
    """全量辩论报告聚合器。

    收集逐品种辩论结果，提供排序、相关性、产业链分组等聚合分析能力。
    纯数据计算，无外部服务依赖。
    """

    def __init__(self, trace_id: str) -> None:
        """初始化报告聚合器。

        Args:
            trace_id: 全链路追踪 ID
        """
        self._trace_id = trace_id
        self._symbols: dict[str, dict[str, Any]] = {}

    # ── 数据收集 ──────────────────────────────────────────

    def add_symbol_report(self, symbol: str, verdict: dict, fdc_data: dict) -> None:
        """添加单品种辩论报告数据。

        Args:
            symbol: 品种代码（如 "RB", "CU"）
            verdict: 闫判官裁决数据。顶层结构为
                {"direction", "confidence", "per_symbol": {symbol: {...}}, ...}
                或直传 per_symbol[symbol] 结构。
            fdc_data: FDC 预采集数据，结构见 FdcSymbolData
                (kline/indicators/term_structure/spread/basis/warrant/fundamental/...)
        """
        self._symbols[symbol.upper()] = {
            "symbol": symbol.upper(),
            "verdict": verdict,
            "fdc_data": fdc_data,
        }

    # ── Top-N 排序矩阵 ─────────────────────────────────────

    def build_top_n_matrix(self, n: int = 10) -> list[dict]:
        """构建 Top-N 排序矩阵：按裁决置信度排序，输出前 N 个品种。

        从每个品种的裁决数据中提取:
          - symbol: 品种代码
          - direction: 方向 (bull/bear/neutral)
          - confidence: 置信度数值
          - entry_price / stop_loss_price / target_price: 交易参数
          - risk_reward_ratio: 盈亏比
          - grade: 评分等级

        Args:
            n: 返回前 N 个品种，默认 10

        Returns:
            按置信度降序排列的 dict 列表。无数据时返回空列表。
        """
        rows: list[dict] = []

        for sym, data in self._symbols.items():
            verdict = data.get("verdict", {})
            if not verdict:
                continue

            # 支持两种裁决结构: "per_symbol" 容器 或 直接字段
            per_sym = verdict.get("per_symbol", {})
            sv: dict = {}
            if isinstance(per_sym, dict):
                sv = per_sym.get(sym, per_sym.get(sym.lower(), {}))
            if not isinstance(sv, dict):
                sv = {}

            direction = sv.get("direction", verdict.get("direction", "neutral"))
            confidence_raw = sv.get("confidence", verdict.get("confidence", 0.5))
            confidence = self._to_float(confidence_raw)
            entry_price = self._to_float(sv.get("entry_price", verdict.get("entry_price", 0)))
            stop_loss = self._to_float(sv.get("stop_loss_price", verdict.get("stop_loss_price", 0)))
            target_price = self._to_float(sv.get("target_price", verdict.get("target_price", 0)))
            rr = self._to_float(sv.get("risk_reward_ratio", verdict.get("risk_reward_ratio", 0)))
            grade = str(sv.get("grade", verdict.get("grade", "")))

            rows.append({
                "symbol": sym,
                "direction": direction,
                "confidence": confidence,
                "entry_price": entry_price,
                "stop_loss_price": stop_loss,
                "target_price": target_price,
                "risk_reward_ratio": rr,
                "grade": grade,
            })

        rows.sort(key=lambda r: r["confidence"], reverse=True)
        return rows[:n]

    # ── 跨品种相关性 ───────────────────────────────────────

    def build_correlation_data(self) -> dict:
        """构建跨品种相关性热力图数据。

        使用 FDC K 线数据提取各品种的收盘价序列，计算 pairwise Pearson 相关系数。

        Returns:
            {
                "symbols": ["RB", "CU", ...],        # 品种列表（有 K 线数据）
                "matrix": [[1.0, 0.5, ...], ...],     # N×N 相关性矩阵
                "pairs": [                            # 非冗余品种对
                    {"symbol1": "RB", "symbol2": "CU", "correlation": 0.5}
                ]
            }
            无可计算数据时返回 {"symbols": [], "matrix": [], "pairs": []}
        """
        # 提取各品种收盘价序列
        close_series: dict[str, list[float]] = {}
        for sym, data in self._symbols.items():
            fdc = data.get("fdc_data", {})
            closes = self._extract_close_prices(fdc)
            if len(closes) >= 10:  # 至少 10 根 K 线才有意义
                close_series[sym] = closes

        if len(close_series) < 2:
            return {"symbols": [], "matrix": [], "pairs": []}

        # 对齐各品种序列至相同长度（取最短）
        symbols = sorted(close_series.keys())
        min_len = min(len(v) for v in close_series.values())
        aligned = {sym: series[-min_len:] for sym, series in close_series.items()}

        # 计算日收益率
        returns: dict[str, list[float]] = {}
        for sym, prices in aligned.items():
            r = []
            for i in range(1, len(prices)):
                if prices[i - 1] != 0:
                    r.append((prices[i] - prices[i - 1]) / prices[i - 1])
            if len(r) >= 5:  # 至少 5 个收益率数据点
                returns[sym] = r

        if len(returns) < 2:
            return {"symbols": [], "matrix": [], "pairs": []}

        # 二次对齐
        symbols = sorted(returns.keys())
        min_len = min(len(v) for v in returns.values())
        aligned_ret = {sym: ret[-min_len:] for sym, ret in returns.items()}

        import numpy as np
        n = len(symbols)
        matrix = np.eye(n, dtype=np.float64)

        pairs: list[dict] = []
        for i in range(n):
            for j in range(i + 1, n):
                a = np.array(aligned_ret[symbols[i]], dtype=np.float64)
                b = np.array(aligned_ret[symbols[j]], dtype=np.float64)
                # 处理常数序列（标准差为 0 时相关系数为 0）
                if a.std() < 1e-10 or b.std() < 1e-10:
                    corr = 0.0
                else:
                    corr = float(np.corrcoef(a, b)[0, 1])
                    corr = round(corr, 4)
                matrix[i, j] = corr
                matrix[j, i] = corr
                pairs.append({
                    "symbol1": symbols[i],
                    "symbol2": symbols[j],
                    "correlation": corr,
                })

        pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

        return {
            "symbols": symbols,
            "matrix": matrix.tolist(),
            "pairs": pairs,
        }

    # ── 产业链组报告 ───────────────────────────────────────

    def build_chain_report(self) -> dict:
        """构建产业链组报告：按产业链分组，输出产业链联动分析。

        从每个品种的 FDC 数据中提取产业链信息（f10_summary 或 profile 中的 chain 字段），
        按产业链分组聚合各品种的裁决方向和置信度。

        Returns:
            {
                "chains": {
                    "黑色系": {
                        "symbols": ["RB", "HC", "I"],
                        "total": 3,
                        "bull_count": 2,
                        "bear_count": 0,
                        "neutral_count": 1,
                        "avg_confidence": 0.65,
                        "dominant_direction": "bull",
                        "verdicts": [{"symbol": "RB", "direction": "bull", "confidence": 0.8}, ...]
                    },
                    ...
                }
            }
            无可用数据时返回 {"chains": {}}。
        """
        from collections import defaultdict

        chain_groups: dict[str, list[dict]] = defaultdict(list)

        for sym, data in self._symbols.items():
            chain_name = self._extract_chain(data)
            verdict = data.get("verdict", {})
            per_sym = verdict.get("per_symbol", {}) if isinstance(verdict, dict) else {}
            sv: dict = {}
            if isinstance(per_sym, dict):
                sv = per_sym.get(sym, per_sym.get(sym.lower(), {}))
            if not isinstance(sv, dict):
                sv = {}

            direction = sv.get("direction", verdict.get("direction", "neutral"))
            confidence = self._to_float(
                sv.get("confidence", verdict.get("confidence", 0.5))
            )

            chain_groups[chain_name].append({
                "symbol": sym,
                "direction": direction,
                "confidence": confidence,
            })

        chains: dict[str, dict] = {}
        for chain_name, verdicts in sorted(chain_groups.items()):
            bull_c = sum(1 for v in verdicts if v["direction"] in ("bull", "buy"))
            bear_c = sum(1 for v in verdicts if v["direction"] in ("bear", "sell"))
            neutral_c = sum(1 for v in verdicts if v["direction"] in ("neutral", "hold", ""))
            confs = [v["confidence"] for v in verdicts if v["confidence"] > 0]
            avg_conf = sum(confs) / len(confs) if confs else 0.0

            # 主导方向
            dom = "neutral"
            if bull_c > bear_c and bull_c > neutral_c:
                dom = "bull"
            elif bear_c > bull_c and bear_c > neutral_c:
                dom = "bear"

            chains[chain_name] = {
                "symbols": [v["symbol"] for v in verdicts],
                "total": len(verdicts),
                "bull_count": bull_c,
                "bear_count": bear_c,
                "neutral_count": neutral_c,
                "avg_confidence": round(avg_conf, 4),
                "dominant_direction": dom,
                "verdicts": verdicts,
            }

        return {"chains": chains}

    # ── 全量报告 ───────────────────────────────────────────

    def generate_full_report(self) -> dict:
        """生成完整全量分析报告。

        聚合 Top-N 排序矩阵、相关性数据、产业链组报告，组装为统一输出。

        Returns:
            {
                "trace_id": str,
                "timestamp": str,
                "symbol_count": int,
                "symbols": list[str],
                "top_n_matrix": [...],
                "correlation_data": {...},
                "chain_report": {...},
            }
            无单品种数据时返回包含空容器的报告。
        """
        from datetime import datetime

        return {
            "trace_id": self._trace_id,
            "timestamp": datetime.now().isoformat(),
            "symbol_count": len(self._symbols),
            "symbols": sorted(self._symbols.keys()),
            "top_n_matrix": self.build_top_n_matrix(),
            "correlation_data": self.build_correlation_data(),
            "chain_report": self.build_chain_report(),
        }

    # ── 内部工具方法 ───────────────────────────────────────

    @staticmethod
    def _to_float(v: Any) -> float:
        """安全地将值转为 float，无法转换时返回 0.0。"""
        if v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _extract_close_prices(fdc_data: dict) -> list[float]:
        """从 FDC 数据中提取 K 线收盘价序列。

        兼容两种 K 线格式：
          - list[dict]: 直接为 K 线列表
          - dict {"bars": list[dict]}: 嵌套在 bars 键下

        Args:
            fdc_data: FDC 品种数据 dict

        Returns:
            收盘价 float 列表，空列表表示无可提取数据
        """
        kline_raw = fdc_data.get("kline", [])
        if isinstance(kline_raw, dict) and "bars" in kline_raw:
            bars = kline_raw["bars"]
        elif isinstance(kline_raw, list):
            bars = kline_raw
        else:
            bars = []

        closes: list[float] = []
        for bar in bars:
            if isinstance(bar, dict):
                close = bar.get("close")
            elif isinstance(bar, (list, tuple)) and len(bar) >= 5:
                # 假设顺序为 [open, high, low, close, volume, ...]
                close = bar[3]
            else:
                continue
            try:
                closes.append(float(close))
            except (ValueError, TypeError):
                continue

        return closes

    @staticmethod
    def _extract_chain(symbol_data: dict) -> str:
        """从品种数据中提取产业链名称。

        查找优先级:
          1. fdc_data → f10_summary → chain
          2. 回退为 "未分类"

        Args:
            symbol_data: 品种完整数据

        Returns:
            产业链名称
        """
        fdc = symbol_data.get("fdc_data", {})
        if isinstance(fdc, dict):
            f10 = fdc.get("f10_summary", {})
            if isinstance(f10, dict):
                chain = f10.get("chain", "")
                if chain:
                    return str(chain)
        return "未分类"
