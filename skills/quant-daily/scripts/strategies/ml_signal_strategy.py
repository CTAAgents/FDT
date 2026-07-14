"""
ML 信号策略 — XGB/LGBM/ONNX 推理桥接。

当前为接口定义 + 降级 fallback 模式（无模型时返回空）。
当 ONNX 模型就位后，注册到 MODEL_REGISTRY 即可激活。
"""

from __future__ import annotations
import json
import os
from typing import Any, Callable, Optional

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal

# ── 模型注册表 ──
# {model_name: {"path": str, "loader": callable, "features": [str, ...]}}
MODEL_REGISTRY: dict[str, dict[str, Any]] = {}

# 自动发现模型目录
_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "models")
if os.path.isdir(_MODEL_DIR):
    for fname in os.listdir(_MODEL_DIR):
        if fname.endswith(".onnx"):
            name = fname.replace(".onnx", "")
            MODEL_REGISTRY[name] = {
                "path": os.path.join(_MODEL_DIR, fname),
                "loader": None,  # 运行时用 onnxruntime 加载
                "features": [],
            }


def _try_load_model(name: str) -> Optional[Any]:
    """加载 ONNX 模型（如果可用）。"""
    entry = MODEL_REGISTRY.get(name)
    if not entry:
        return None
    model_path = entry["path"]
    if not os.path.isfile(model_path):
        return None
    try:
        import onnxruntime as ort
        session = ort.InferenceSession(model_path)
        entry["loader"] = session
        return session
    except ImportError:
        return None


def _predict(session: Any, features: list[float]) -> float:
    """用 ONNX session 推理。"""
    if session is None:
        return 0.0
    try:
        input_name = session.get_inputs()[0].name
        import numpy as np
        result = session.run(None, {input_name: np.array([features], dtype=np.float32)})
        return float(result[0][0])
    except Exception:
        return 0.0


# ── 内置特征列（与 factor_timing 五因子对齐） ──
FEATURE_NAMES = ["carry", "momentum", "inventory_pct", "skew", "corr"]


class MlSignalStrategy(BaseStrategyV2):
    """ML 信号策略 — ONNX 模型推理。"""

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or ""
        self._session = _try_load_model(model_name) if model_name else None

    @property
    def name(self) -> str:
        return "ml_signal"

    @property
    def display_name(self) -> str:
        return f"ML信号({self._model_name or 'fallback'})"

    @property
    def signal_type(self) -> str:
        return "ml_signal"

    @property
    def validators(self) -> list[str]:
        return ["stability"]

    @property
    def weight(self) -> float:
        return 0.8  # ML 信号权重较高

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        if self._session is None:
            # 无模型时返回空（优雅降级）
            return []

        signals: list[RawSignal] = []
        for t in tech_list:
            sym = t.get("symbol", "")
            features = [float(t.get(f, 0)) for f in FEATURE_NAMES]
            prob = _predict(self._session, features)
            if abs(prob - 0.5) < 0.1:
                continue  # 概率接近 0.5，不交易
            direction = "bull" if prob > 0.5 else "bear"
            signals.append(RawSignal(
                symbol=sym,
                direction=direction,
                signal_type=f"{self.signal_type}.prob",
                raw_score=abs(prob - 0.5) * 2,
                strategy_name=self.name,
                meta={"probability": round(prob, 4), "model": self._model_name},
            ))
        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100
            grade = "WATCH" if raw > 0.6 else "WEAK"
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade=grade,
                weight=self.weight,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
