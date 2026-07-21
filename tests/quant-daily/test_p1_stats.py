"""P1角色矫正（v9.6.8）测试 — stats产出 / 数据质量闸门 / audit偏离度"""

import sys, os
import pytest

# ── 路径自举 ──
SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "skills", "quant-daily", "scripts")
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if FDT_ROOT not in sys.path:
    sys.path.insert(0, FDT_ROOT)

# ── 导入被测函数 ──
from scan_all import _build_pure_stats, _calc_volume_ma20
from run_debate import select_triggers


# ═══════════════════════════════════════
# TC-STATS-001: _build_pure_stats 不含方向性字段
# ═══════════════════════════════════════
class TestBuildPureStats:
    def test_no_directional_fields(self):
        """stats 不应包含 direction/total/grade"""
        record = {
            "price": 3992, "change_pct": 0.55, "direction": "bear",
            "total": -60, "grade": "STRONG", "atr": 45, "rsi": 45,
            "adx": 28, "volume": 6299, "ma_align": "bear",
        }
        stats = _build_pure_stats(record, None)
        assert "direction" not in stats, "stats 不应包含 direction"
        assert "total" not in stats, "stats 不应包含 total"
        assert "grade" not in stats, "stats 不应包含 grade"

    def test_returns_dict(self):
        """stats 必须返回 dict"""
        stats = _build_pure_stats({}, None)
        assert isinstance(stats, dict)

    def test_stats_keys_exist(self):
        """stats 应包含核心统计字段"""
        record = {"price": 100, "volume": 5000, "atr": 10, "rsi": 50, "adx": 25}
        stats = _build_pure_stats(record, None)
        for key in ["latest_close", "change_pct", "atr_14", "rsi_14", "adx_14", "volume", "n_bars"]:
            assert key in stats, f"stats 缺少字段: {key}"


# ═══════════════════════════════════════
# TC-STATS-002: 缺失字段时的默认值
# ═══════════════════════════════════════
class TestBuildPureStatsDefaults:
    def test_empty_record_defaults(self):
        """空 record + None kline 的默认值应合理"""
        stats = _build_pure_stats({}, None)
        assert stats["rsi_14"] == 50, "rsi 默认值应为 50"
        assert stats["adx_14"] == 25, "adx 默认值应为 25"
        assert stats["volume_ma20_ratio"] == 0, "无 kline 时量能比应为 0"
        assert stats["n_bars"] == 0, "无 kline 时 n_bars 应为 0"
        assert stats["price_position_pct"] == 0.0, "无区间数据时（high=low=price）位置应为 0%"


# ═══════════════════════════════════════
# TC-STATS-003: _calc_volume_ma20 计算正确性
# ═══════════════════════════════════════
class TestCalcVolumeMa20:
    def test_none_input(self):
        """None 输入返回 0"""
        assert _calc_volume_ma20(None) == 0

    def test_empty_list(self):
        """空列表返回 0"""
        assert _calc_volume_ma20([]) == 0

    def test_single_bar(self):
        """单根K线返回 0（不足计算）"""
        assert _calc_volume_ma20([{"volume": 100}]) == 0

    def test_exact_20_bars(self):
        """20根K线应计算均值（排除最后一根）"""
        kline = [{"volume": i * 10} for i in range(1, 22)]  # 21 根
        result = _calc_volume_ma20(kline)
        # 排除最后一根(volume=210)，取前20根均值
        expected = sum(range(10, 210, 10)) / 20
        assert abs(result - expected) < 0.001, f"期望 {expected}, 实际 {result}"

    def test_less_than_20_bars(self):
        """不足20根时用全部可用数据"""
        kline = [{"volume": 10}, {"volume": 20}, {"volume": 30}]
        result = _calc_volume_ma20(kline)
        assert result == 20.0, f"3根K线均量应为 20, 实际 {result}"


# ═══════════════════════════════════════
# TC-GATE-001: select_triggers 过滤无stats记录
# ═══════════════════════════════════════
class TestSelectTriggersDataQuality:
    def test_no_stats_filtered(self):
        """无 stats 的记录应被过滤"""
        scan = {"all_ranked": [{"symbol": "RB", "price": 3000, "grade": "STRONG"}]}
        passed = select_triggers(scan, threshold=20)
        assert len(passed) == 0

    def test_insufficient_bars_filtered(self):
        """K线不足 20 根的记录应被过滤"""
        scan = {"all_ranked": [
            {"symbol": "RB", "stats": {"n_bars": 15, "volume": 5000, "oi": 10000}}
        ]}
        passed = select_triggers(scan, threshold=20)
        assert len(passed) == 0

    def test_zero_volume_oi_filtered(self):
        """零成交+零持仓的记录应被过滤"""
        scan = {"all_ranked": [
            {"symbol": "RB", "stats": {"n_bars": 100, "volume": 0, "oi": 0}}
        ]}
        passed = select_triggers(scan, threshold=20)
        assert len(passed) == 0

    def test_valid_record_passed(self):
        """有效记录应通过闸门"""
        scan = {"all_ranked": [
            {"symbol": "RB", "stats": {"n_bars": 120, "volume": 50000, "oi": 100000}}
        ]}
        passed = select_triggers(scan, threshold=20)
        assert len(passed) == 1
        assert passed[0]["symbol"] == "RB"

    def test_sort_by_volume(self):
        """结果应按成交量降序排列"""
        scan = {"all_ranked": [
            {"symbol": "A", "stats": {"n_bars": 100, "volume": 1000, "oi": 5000}},
            {"symbol": "B", "stats": {"n_bars": 100, "volume": 3000, "oi": 5000}},
            {"symbol": "C", "stats": {"n_bars": 100, "volume": 2000, "oi": 5000}},
        ]}
        passed = select_triggers(scan, threshold=20)
        symbols = [r["symbol"] for r in passed]
        assert symbols == ["B", "C", "A"], f"应按成交量降序排列: {symbols}"

    def test_legacy_fields_preserved(self):
        """旧的 grade/total/direction 应保留在记录中"""
        record = {
            "symbol": "RB", "direction": "bear", "total": -60, "grade": "STRONG",
            "stats": {"n_bars": 100, "volume": 5000, "oi": 10000}
        }
        scan = {"all_ranked": [record]}
        passed = select_triggers(scan, threshold=20)
        assert passed[0]["direction"] == "bear"
        assert passed[0]["total"] == -60
        assert passed[0]["grade"] == "STRONG"