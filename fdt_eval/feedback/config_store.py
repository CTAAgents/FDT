"""
品种参数配置存储 — 持久化 feedback 调整后的交易参数。

每个品种维护以下可调参数:
    position_base_pct:  基准仓位百分比 (默认 3.0)
    position_weight:    该品种的权重系数 (基于历史准确率, 0.3-2.0)
    atr_stop_multiplier: ATR 止损乘数 (默认 2.0)
    atr_target_multiplier: ATR 目标乘数 (默认 3.0)
    confidence_offset:  置信度偏移修正 (默认 0.0)
    min_accuracy:       准入最低准确率 (默认 0.0)

文件存储: fdt_eval/feedback/_config/symbol_params.json
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent / "_config"
CONFIG_PATH = CONFIG_DIR / "symbol_params.json"


@dataclass
class SymbolConfig:
    """单个品种的可调参数。"""
    # 仓位
    position_base_pct: float = 3.0
    position_weight: float = 1.0          # 0.3 - 2.0

    # 止损/目标
    atr_stop_multiplier: float = 2.0
    atr_target_multiplier: float = 3.0

    # 置信度
    confidence_offset: float = 0.0        # -0.3 - +0.3

    # 准入
    min_accuracy: float = 0.0

    # 元数据
    updated_at: float = 0.0
    n_validations: int = 0               # 参与统计的验证次数
    recent_accuracy: float = 0.0         # 最近准确率
    version: int = 1


@dataclass
class FeedbackConfig:
    """全局反馈配置。"""
    enabled: bool = True
    min_samples_per_symbol: int = 3       # 最少样本数才启用调整
    position_min_pct: float = 1.0         # 仓位下限
    position_max_pct: float = 15.0        # 仓位上限
    weight_min: float = 0.3
    weight_max: float = 2.0
    confidence_offset_range: tuple[float, float] = (-0.3, 0.3)
    auto_tune: bool = True                # 是否自动调整
    last_tuned_at: float = 0.0


class ConfigStore:
    """品种参数持久化存储。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path or CONFIG_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._config: dict[str, SymbolConfig] = {}
        self._global: FeedbackConfig = FeedbackConfig()
        self._load()

    # ── 持久化 ──

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for symbol, data in raw.get("symbols", {}).items():
                self._config[symbol] = SymbolConfig(**data)
            if "global" in raw:
                self._global = FeedbackConfig(**raw["global"])
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        data = {
            "symbols": {sym: asdict(cfg) for sym, cfg in self._config.items()},
            "global": asdict(self._global),
            "saved_at": time.time(),
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 品种配置读写 ──

    def get(self, symbol: str) -> SymbolConfig:
        """获取品种配置，不存在时返回默认值。"""
        return self._config.get(symbol.upper(), SymbolConfig())

    def set(self, symbol: str, cfg: SymbolConfig) -> None:
        """设置品种配置。"""
        cfg.updated_at = time.time()
        cfg.version += 1
        self._config[symbol.upper()] = cfg
        self.save()

    def update(self, symbol: str, **kwargs) -> SymbolConfig:
        """更新品种配置的部分字段。"""
        sym = symbol.upper()
        cfg = self.get(sym)
        for k, v in kwargs.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.updated_at = time.time()
        cfg.version += 1
        self._config[sym] = cfg
        self.save()
        return cfg

    def all_symbols(self) -> dict[str, SymbolConfig]:
        return dict(self._config)

    # ── 全局配置 ──

    @property
    def global_config(self) -> FeedbackConfig:
        return self._global

    def set_global(self, cfg: FeedbackConfig) -> None:
        self._global = cfg
        self.save()

    # ── 给 signal_output 用的查询接口 ──

    def get_position_pct(self, symbol: str, base_confidence: float = 0.5) -> float:
        """计算该品种的建议仓位百分比。

        Args:
            symbol: 品种代码
            base_confidence: LLM 给出的置信度 [0, 1]

        Returns:
            仓位百分比
        """
        cfg = self.get(symbol)
        if not self._global.enabled:
            return cfg.position_base_pct

        # 置信度调整: 基础置信度 + 偏移
        adjusted_conf = max(0.0, min(1.0, base_confidence + cfg.confidence_offset))

        # 仓位 = 基础仓位 × 品种权重 × 置信度映射
        # confidence >= 0.7 → 满仓, 0.4-0.7 → 半仓, < 0.4 → 1/4 仓
        if adjusted_conf >= 0.7:
            conf_factor = 1.0
        elif adjusted_conf >= 0.4:
            conf_factor = 0.5
        else:
            conf_factor = 0.25

        pct = cfg.position_base_pct * cfg.position_weight * conf_factor

        # 硬约束
        return max(
            self._global.position_min_pct,
            min(self._global.position_max_pct, pct),
        )

    def get_stop_params(self, symbol: str, atr: float) -> tuple[float, float]:
        """获取止损价和目标价的计算参数。

        Returns:
            (stop_distance, target_distance) — 基于 ATR 的距离
        """
        cfg = self.get(symbol)
        stop_dist = cfg.atr_stop_multiplier * atr
        target_dist = cfg.atr_target_multiplier * atr
        return (stop_dist, target_dist)

    def get_effective_confidence(self, symbol: str, raw_confidence: float) -> float:
        """获取校准后的有效置信度。"""
        cfg = self.get(symbol)
        return max(0.0, min(1.0, raw_confidence + cfg.confidence_offset))
