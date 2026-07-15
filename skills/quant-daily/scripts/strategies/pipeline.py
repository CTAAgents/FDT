"""
多策略编排器 — StrategyPipeline + StrategyFusion。

编排多策略执行（按依赖拓扑）、策略内验证器路由、跨策略得分融合。
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Optional
from collections import defaultdict

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


# ════════════════════════════════════════════════════════════
# 字段名归一化（TDX/numpy 大写 → v2 策略标准化小写）
# ════════════════════════════════════════════════════════════

_FIELD_MAP = {
    # RSI
    "rsi14": "rsi", "RSI14": "rsi",
    # CCI
    "cci20": "cci", "CCI20": "cci",
    # ATR
    "atr14": "atr", "ATR14": "atr",
    # ADX / DMI
    "adx": "adx", "ADX": "adx",
    "dmi_pdi": "pdi", "DMI_PDI": "pdi",
    "dmi_mdi": "mdi", "DMI_MDI": "mdi",
    # 布林带
    "bb_pctb": "bb", "BB_PCTB": "bb",
    "bb_width": "bb_width", "BB_WIDTH": "bb_width",
    "bb_squeeze": "bb_squeeze", "BB_SQUEEZE": "bb_squeeze",
    # MA
    "ma20_slope": "ma_slope", "MA20_SLOPE": "ma_slope",
    "ma120": "ma120", "MA120": "ma120",
    # 唐奇安通道
    "dc_pos": "dc20", "DC_POS": "dc20",
    "dc_upper": "dc20_high", "DC_UPPER": "dc20_high",
    "dc_lower": "dc20_low", "DC_LOWER": "dc20_low",
    "dc_mid": "dc20_mid", "DC_MID": "dc20_mid",
    "dc55_upper": "dc55_high", "DC55_UPPER": "dc55_high",
    "dc55_lower": "dc55_low", "DC55_LOWER": "dc55_low",
    "dc55_mid": "dc55_mid", "DC55_MID": "dc55_mid",
    "dc55_trend": "dc55_trend", "DC55_TREND": "dc55_trend",
    # MACD
    "macd_dif": "macd_dif", "MACD_DIF": "macd_dif",
    "macd_dea": "macd_dea", "MACD_DEA": "macd_dea",
    # 成交量
    "vol_ratio": "vol_ratio", "VOL_RATIO": "vol_ratio",
    "vol_5d_ratio": "vol_5d_ratio", "VOL_5D_RATIO": "vol_5d_ratio",
    "vol_price_divergence": "vol_price_divergence",
    "VOL_PRICE_DIVERGENCE": "vol_price_divergence",
    # OI
    "oi_change_pct": "oi_change_pct", "OI_CHANGE_PCT": "oi_change_pct",
    "oi_increasing": "oi_increasing", "OI_INCREASING": "oi_increasing",
    "oi_rate": "oi_rate", "OI_RATE": "oi_rate",
    # 价格
    "last_price": "last_price",
    "price_change_5d": "change_5d", "PRICE_CHANGE_5D": "change_5d",
    "high_60": "high_60", "HIGH_60": "high_60",
    "new_high_60": "new_high_60", "NEW_HIGH_60": "new_high_60",
    "new_low_60": "new_low_60", "NEW_LOW_60": "new_low_60",
    "volatility_pct": "volatility_pct",
    "willr14": "willr", "WILLR14": "willr",
    "stoch_k5": "stoch_k", "STOCH_K5": "stoch_k",
    "roc10": "roc", "ROC10": "roc",
    "cmf21": "cmf", "CMF21": "cmf",
    "obv": "obv", "OBV": "obv",
    "obv_ma20": "obv_ma", "OBV_MA20": "obv_ma",
    # supertrend
    "supertrend_dir": "supertrend", "SUPERTREND_DIR": "supertrend",
    # G30 指标衍生趋势子策略字段
    "kc_upper": "kc_upper", "KC_UPPER": "kc_upper",
    "kc_lower": "kc_lower", "KC_LOWER": "kc_lower",
    "kc_mid": "kc_mid", "KC_MID": "kc_mid",
    "chandelier_long": "chandelier_long", "CHANDELIER_LONG": "chandelier_long",
    "chandelier_short": "chandelier_short", "CHANDELIER_SHORT": "chandelier_short",
    "sar": "sar", "SAR": "sar",
    "sar_trend": "sar_trend", "SAR_TREND": "sar_trend",
    # G31 时间序列动量 TSMOM
    "tsmom_1m": "tsmom_1m", "TSMOM_1M": "tsmom_1m",
    "tsmom_3m": "tsmom_3m", "TSMOM_3M": "tsmom_3m",
    "tsmom_6m": "tsmom_6m", "TSMOM_6M": "tsmom_6m",
    "tsmom_12m": "tsmom_12m", "TSMOM_12M": "tsmom_12m",
    # G32 波动率目标化 Vol Targeting
    "realized_vol": "realized_vol", "REALIZED_VOL": "realized_vol",
    "vol_scale": "vol_target_scale", "VOL_SCALE": "vol_target_scale",
    # 均值/标准差
    "price_deviation_pct": "price_deviation", "PRICE_DEVIATION_PCT": "price_deviation",
}


def normalize_tech_fields(tech_list: list[dict]) -> list[dict]:
    """将 TDX/numpy 大写字段名标准化为 v2 策略使用的小写名。

    为每个已知大写字段添加小写别名（不删除原字段，兼容 v1 消费者）。
    """
    for t in tech_list:
        # 找所有大写或混合大小写的字段
        to_add: dict[str, Any] = {}
        for k, v in t.items():
            mapped = _FIELD_MAP.get(k)
            if mapped and mapped != k:
                to_add[mapped] = v
        # 派生 macd_cross 字段（如果未直接提供）
        if "macd_dif" not in t and "macd_dif" not in to_add:
            dif = t.get("MACD_DIF") or t.get("macd_dif")
            dea = t.get("MACD_DEA") or t.get("macd_dea")
            if dif is not None and dea is not None:
                try:
                    to_add["macd_cross"] = "golden" if float(dif) > float(dea) else "death" if float(dif) < float(dea) else "none"
                except (ValueError, TypeError):
                    to_add["macd_cross"] = "none"
        # 添加 price 别名
        if "price" not in t and "price" not in to_add:
            lp = t.get("last_price")
            if lp is not None:
                to_add["price"] = lp
        t.update(to_add)
    return tech_list
# ════════════════════════════════════════════════════════════

def _topo_sort(strategies: list[BaseStrategyV2]) -> list[BaseStrategyV2]:
    """按依赖关系拓扑排序，无依赖的策略在前。"""
    names = {s.name for s in strategies}
    visited: set[str] = set()
    sorted_list: list[BaseStrategyV2] = []
    temp_mark: set[str] = set()

    def _visit(s: BaseStrategyV2):
        if s.name in temp_mark:
            raise ValueError(f"Circular dependency detected: {s.name}")
        if s.name in visited:
            return
        temp_mark.add(s.name)
        for dep_name in s.depends_on:
            dep = next((st for st in strategies if st.name == dep_name), None)
            if dep is None:
                raise ValueError(f"Strategy '{s.name}' depends on '{dep_name}' which is not registered")
            _visit(dep)
        temp_mark.discard(s.name)
        visited.add(s.name)
        sorted_list.append(s)

    for s in strategies:
        if s.name not in visited:
            _visit(s)
    return sorted_list


# ════════════════════════════════════════════════════════════
# 策略融合
# ════════════════════════════════════════════════════════════

class StrategyFusion:
    """跨策略得分融合。

    支持多种融合策略，通过 fusion_method 参数选择。
    """

    # 融合模式
    WEIGHTED_MAX = "weighted_max"       # 取最高权重策略的分数
    WEIGHTED_AVG = "weighted_avg"       # 加权平均
    SIGNAL_STACK = "signal_stack"       # 保留多重信号，取高分者
    NO_FUSION = "no_fusion"             # 零融合：各策略信号扁平输出，冲突留给 debate

    def __init__(self, fusion_method: str = NO_FUSION):
        if fusion_method not in (self.WEIGHTED_MAX, self.WEIGHTED_AVG, self.SIGNAL_STACK, self.NO_FUSION):
            raise ValueError(f"Unknown fusion method: {fusion_method}")
        self.fusion_method = fusion_method

    def fuse(self,
             per_strategy: dict[str, list[ScoredSignal]]
             ) -> list[ScoredSignal]:
        """融合多策略打分结果为一个统一候选列表。

        Args:
            per_strategy: {strategy_name: [ScoredSignal, ...]}

        Returns:
            融合后的 ScoredSignal 列表
        """
        # NO_FUSION：零融合，所有信号扁平输出，冲突留给 debate
        if self.fusion_method == self.NO_FUSION:
            all_sigs: list[ScoredSignal] = []
            for signals in per_strategy.values():
                all_sigs.extend(signals)
            all_sigs.sort(key=lambda s: s.abs_score, reverse=True)
            return all_sigs

        by_symbol: dict[str, list[ScoredSignal]] = defaultdict(list)
        for sname, signals in per_strategy.items():
            for sig in signals:
                by_symbol[sig.symbol].append(sig)

        fused: list[ScoredSignal] = []
        for symbol, sigs in by_symbol.items():
            candidates = self._fuse_one(symbol, sigs)
            if candidates:
                if isinstance(candidates, list):
                    fused.extend(candidates)
                else:
                    fused.append(candidates)

        # 按 abs_score 降序
        fused.sort(key=lambda s: s.abs_score, reverse=True)
        return fused

    def _fuse_one(self, symbol: str,
                  signals: list[ScoredSignal]) -> ScoredSignal | list[ScoredSignal] | None:
        """融合单个品种的多策略信号。

        当方向冲突且冲突方信号有效（grade≠NOISE）时拆分输出，
        让下游 debate 环节自行裁决，避免权重碾压丢失信息。
        """
        if not signals:
            return None

        if self.fusion_method == self.SIGNAL_STACK:
            best = max(signals, key=lambda s: s.abs_score)
            best.extra["strategy_breakdown"] = {
                s.strategy_name: {"total": s.total, "weight": s.weight}
                for s in signals
            }
            return best

        sorted_sigs = sorted(signals, key=lambda s: s.weight, reverse=True)

        # ══════════════════════════════════════════════════
        # 方向冲突拆分逻辑（所有融合模式共享）
        # ══════════════════════════════════════════════════
        dirs = {s.direction for s in signals if s.direction not in ("neutral",)}
        if len(dirs) > 1:
            # 按方向分组
            bull_sigs = [s for s in signals if s.direction == "bull"]
            bear_sigs = [s for s in signals if s.direction == "bear"]
            # 只保留有效信号（NOISE 级别的不参与冲突）
            bull_active = [s for s in bull_sigs if s.grade != "NOISE"]
            bear_active = [s for s in bear_sigs if s.grade != "NOISE"]

            if bull_active and bear_active:
                # 双方都有有效信号 → 拆分输出
                bull_fused = self._fuse_dir(symbol, bull_active, "bull")
                bear_fused = self._fuse_dir(symbol, bear_active, "bear")
                result = []
                if bull_fused:
                    bull_fused.extra["direction_conflict"] = True
                    bull_fused.extra["conflict_with"] = [s.signal_type for s in bear_active]
                    result.append(bull_fused)
                if bear_fused:
                    bear_fused.extra["direction_conflict"] = True
                    bear_fused.extra["conflict_with"] = [s.signal_type for s in bull_active]
                    result.append(bear_fused)
                return result if result else None

        # 无冲突或单方向 → 正常融合
        return self._fuse_dir(symbol, signals, None)

    def _fuse_dir(self, symbol: str, signals: list[ScoredSignal],
                  preferred_dir: str | None = None) -> Optional[ScoredSignal]:
        """融合同一方向的策略信号。"""
        if not signals:
            return None
        sorted_sigs = sorted(signals, key=lambda s: s.weight, reverse=True)

        if self.fusion_method == self.WEIGHTED_MAX:
            best = sorted_sigs[0]
            best.extra["strategy_breakdown"] = {
                s.strategy_name: {"total": s.total, "weight": s.weight}
                for s in signals
            }
            if preferred_dir:
                best.direction = preferred_dir
            return best

        if self.fusion_method == self.WEIGHTED_AVG:
            total_weight = sum(s.weight for s in signals)
            if total_weight == 0:
                return sorted_sigs[0]
            avg_total = sum(s.total * s.weight for s in signals) / total_weight
            avg_abs = sum(s.abs_score * s.weight for s in signals) / total_weight
            direction = preferred_dir or sorted_sigs[0].direction

            result = ScoredSignal(
                symbol=symbol,
                direction=direction,
                signal_type="fused",
                strategy_name="fused",
                total=round(avg_total, 1),
                abs_score=round(avg_abs, 1),
                grade="STRONG" if abs(avg_total) >= 75 else
                      "WATCH" if abs(avg_total) >= 60 else
                      "WEAK" if abs(avg_total) >= 40 else "NOISE",
                sub_scores={s.strategy_name: s.total for s in signals},
                weight=1.0,
            )
            result.extra["strategy_breakdown"] = {
                s.strategy_name: {"total": s.total, "weight": s.weight}
                for s in signals
            }
            result.extra["fusion_method"] = self.WEIGHTED_AVG
            return result

        return sorted_sigs[0]


# ════════════════════════════════════════════════════════════
# 策略管线
# ════════════════════════════════════════════════════════════

class StrategyPipeline:
    """多策略编排器。

    流程:
      1. 按依赖拓扑排序策略
      2. 逐策略执行 compute → filter → score
      3. 策略内验证器按 signal_type 路由
      4. 跨策略融合
      5. 打包为统一输出格式
    """

    def __init__(self, strategies: list[BaseStrategyV2],
                 fusion: Optional[StrategyFusion] = None):
        if not strategies:
            raise ValueError("At least one strategy required")
        self.strategies = _topo_sort(strategies)
        self.fusion = fusion or StrategyFusion()

    def run(self, tech_list: list[dict], kline_data: dict,
            context: dict | None = None) -> dict:
        """完整执行管线。

        Args:
            tech_list: 指标引擎产出的每品种 tech dict 列表
            kline_data: {sym: (name, [bar_dict, ...])}
            context: 共享上下文（含验证器需要的数据）

        Returns:
            {
                "all_ranked": [ScoredSignal.to_dict(), ...],
                "bull_signals": [dict, ...],     # direction=="bull"
                "bear_signals": [dict, ...],     # direction=="bear"
                "per_strategy": {name: signals_dict, ...},
                "_meta": {strategies_run, fusion_method, ...}
            }
        """
        ctx = context or {}

        # Phase 0: 字段名归一化（TDX/numpy 大写 → v2 标准化小写）
        tech_list = normalize_tech_fields(tech_list)

        # Phase 1: 执行所有策略
        strategy_outputs: dict[str, list[ScoredSignal]] = {}
        for s in self.strategies:
            raw = s.compute(tech_list, kline_data, ctx)
            filtered = s.filter(raw, ctx)
            scored = s.score(filtered, tech_list, ctx)
            strategy_outputs[s.name] = scored

        # Phase 2: 策略内验证器（从 validators 注册表查找）
        try:
            from signals.validators import get_validator, ValidationContext
            # 将管线上下文包装为 ValidationContext（验证器需要 .kline_data 属性）
            _vc_extra: dict = ctx.get("extra", {}) if isinstance(ctx, dict) else {}
            vctx = ValidationContext(
                kline_data=ctx.get("kline_data", {}) if isinstance(ctx, dict) else {},
                higher_tf={},
                extra=_vc_extra,
            )
            for s in self.strategies:
                for signal in strategy_outputs.get(s.name, []):
                    sig_dict = signal.to_dict()
                    for vid in s.validators:
                        vfn = get_validator(vid)
                        if vfn:
                            vfn(sig_dict, vctx)
                    # 同步验证器修改回 ScoredSignal
                    signal._validator_demoted = sig_dict.get("_validator_demoted", False)
                    signal._validator_reason = sig_dict.get("_validator_reason", "")
                    if sig_dict.get("grade") != signal.grade:
                        signal.grade = sig_dict.get("grade", signal.grade)
                    if sig_dict.get("total", signal.total) != signal.total:
                        signal.total = sig_dict.get("total", signal.total)
        except ImportError:
            pass  # 验证器不可用时不崩溃

        # Phase 3: 跨策略融合
        fused = self.fusion.fuse(strategy_outputs)

        # Phase 4: 全局闸门（crowding 等）
        try:
            from signals.validators import get_validator
            global_vids = ["crowding"]
            fused_dicts = [s.to_dict() for s in fused]
            for vid in global_vids:
                vfn = get_validator(vid)
                if vfn:
                    vfn(fused_dicts, vctx)
            # 同步回 ScoredSignal
            fd_map = {d["symbol"]: d for d in fused_dicts}
            for s in fused:
                if s.symbol in fd_map:
                    fd = fd_map[s.symbol]
                    s.grade = fd.get("grade", s.grade)
                    s.total = fd.get("total", s.total)
                    s._validator_demoted = fd.get("_validator_demoted", False)
        except ImportError:
            pass

        # Phase 4.5: 波动率目标化 overlay（G32）— 执行/风险层缩放
        # 对每个融合后信号注入 vol_target_scale / realized_vol / note。
        # NO_FUSION 与各融合模式统一生效；overlay 不可用时不崩溃。
        try:
            from strategies.vol_targeting import VolTargetingOverlay
            _tech_by_symbol = {t.get("symbol"): t for t in tech_list if isinstance(t, dict)}
            _overlay = VolTargetingOverlay()
            for s in fused:
                _overlay.apply(s, _tech_by_symbol.get(s.symbol, {}))
        except Exception:
            pass

        # Phase 5: 打包输出
        all_dicts = [s.to_dict() for s in fused]
        bull = [d for d in all_dicts if d.get("direction") == "bull" and d.get("grade") != "NOISE"]
        bear = [d for d in all_dicts if d.get("direction") == "bear" and d.get("grade") != "NOISE"]

        per_strategy_dict = {}
        for sname, signals in strategy_outputs.items():
            per_strategy_dict[sname] = {
                "all_ranked": [sig.to_dict() for sig in signals],
                "count": len(signals),
            }

        return {
            "all_ranked": all_dicts,
            "bull_signals": bull,
            "bear_signals": bear,
            "per_strategy": per_strategy_dict,
            "_meta": {
                "strategies_run": [s.name for s in self.strategies],
                "fusion_method": self.fusion.fusion_method,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "total": len(all_dicts),
                "bull": len(bull),
                "bear": len(bear),
            },
        }
