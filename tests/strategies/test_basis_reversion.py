"""BasisReversionStrategy（期现基差 OU 均值回归）测试。

覆盖：
  - store_basis_snapshot + fetch_basis_history（JSONL 读写）
  - BasisReversionStrategy.compute（基差偏高/偏低/无偏离/非回复/空上下文）
  - BasisReversionStrategy.score（方向符号 + grade + weight=0.7）
"""

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from strategies.basis_reversion_strategy import (
    BasisReversionStrategy,
    store_basis_snapshot,
    fetch_basis_history,
    _basis_log_path,
)


# ── 存储层测试 ──

class TestBasisStore:
    def _make_tmp_path(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        p = tmp.name
        tmp.close()
        return p

    def test_store_and_read_roundtrip(self, monkeypatch):
        p = self._make_tmp_path()
        monkeypatch.setattr("strategies.basis_reversion_strategy._basis_log_path",
                           lambda: p)
        try:
            # 写 60 笔以上确保 MIN_BARS 通过
            for day in range(1, 62):
                items = {"cu": {"spot_price": 70000 + day,
                                "futures_price": 70500 + day,
                                "basis": -500 + day // 10,
                                "basis_pct": -0.71 + day / 1000}}
                store_basis_snapshot(items, data_date=f"2026-{day:02d}-01")
            sh = fetch_basis_history("CU", days=120)
            assert sh is not None
            assert sh["variety"] == "CU"
            assert abs(sh["basis"][-1] - (-500 + 61 // 10)) < 0.1
        finally:
            if os.path.isfile(p):
                os.unlink(p)

    def test_empty_items_no_write(self, monkeypatch):
        p = self._make_tmp_path()
        monkeypatch.setattr("strategies.basis_reversion_strategy._basis_log_path",
                           lambda: p)
        try:
            store_basis_snapshot({}, data_date="2026-07-15")
            assert not os.path.isfile(p) or os.path.getsize(p) == 0
        finally:
            if os.path.isfile(p):
                os.unlink(p)


# ── 策略 compute 测试 ──

def _make_basis_history(series, variety="CU"):
    return {
        variety: {
            "basis": list(series),
            "basis_pct": [s / 100.0 for s in series],
            "dates": [f"2026-{i:02d}-01" for i in range(len(series))],
            "variety": variety,
        }
    }


class TestBasisReversionCompute:
    def test_basis_overpriced_bear(self):
        # 基差大幅正偏离（现货 >> 期货）→ bear（做空基差回归）
        rng = np.random.default_rng(15)
        basis = np.zeros(120)
        for i in range(1, 120):
            basis[i] = 0.85 * basis[i - 1] + rng.normal(0, 1)
        std30 = max(float(np.std(basis[-30:])), 0.01)
        basis[-1] += 8.0 * std30  # 单 bar 极端 → z >> 2
        ctx = {"basis_history": _make_basis_history(list(basis))}
        sigs = BasisReversionStrategy().compute([], {}, ctx)
        assert len(sigs) == 1
        assert sigs[0].direction == "bear"  # basis 偏高→做空回归（price down）

    def test_basis_underpriced_bull(self):
        rng = np.random.default_rng(16)
        basis = np.zeros(120)
        for i in range(1, 120):
            basis[i] = 0.85 * basis[i - 1] + rng.normal(0, 1)
        std30 = max(float(np.std(basis[-30:])), 0.01)
        basis[-1] -= 8.0 * std30
        ctx = {"basis_history": _make_basis_history(list(basis))}
        sigs = BasisReversionStrategy().compute([], {}, ctx)
        assert len(sigs) == 1
        assert sigs[0].direction == "bull"

    def test_no_deviation_no_signal(self):
        rng = np.random.default_rng(17)
        basis = 10.0 + rng.normal(0, 0.3, 120)
        ctx = {"basis_history": _make_basis_history(list(basis))}
        sigs = BasisReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_non_reverting_no_signal(self):
        basis = list(np.arange(300, dtype=float))
        ctx = {"basis_history": _make_basis_history(basis)}
        sigs = BasisReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_insufficient_history_no_signal(self):
        basis = list(np.arange(30))
        ctx = {"basis_history": _make_basis_history(basis)}
        sigs = BasisReversionStrategy().compute([], {}, ctx)
        assert sigs == []

    def test_empty_context_no_signal(self):
        s = BasisReversionStrategy()
        assert s.compute([], {}, {}) == []
        assert s.compute([], {}, None) == []


# ── 评分测试 ──

class TestBasisReversionScore:
    def test_score_direction_and_weight(self):
        from strategies.base_v2 import RawSignal
        raw = RawSignal(
            symbol="CU", direction="bear",
            signal_type="basis_reversion.cu",
            raw_score=0.9, strategy_name="basis_reversion",
            meta={"z_score": 3.0, "half_life": 12.0},
        )
        s = BasisReversionStrategy()
        scored = s.score([raw], [], {})
        assert len(scored) == 1
        ss = scored[0]
        assert ss.direction == "bear"
        assert ss.total < 0
        assert ss.abs_score == 90.0
        assert ss.weight == 0.7
        assert ss.grade == "WATCH"
