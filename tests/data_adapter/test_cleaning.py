"""清洗层全模块测试 — OHLC / 离群值 / 复权 / 时间轴。

覆盖策略：每个清洗函数覆盖成功路径 + 边界条件 + 异常输入。
"""

from __future__ import annotations

import math

import pytest

from data_adapter.cleaning.ohlc import clean_ohlc
from data_adapter.cleaning.outlier import clean_outliers
from data_adapter.cleaning.adjustment import clean_adjustment
from data_adapter.cleaning.timeline import clean_timeline
from data_adapter.cleaning import clean_kline
from data_adapter.types import CleaningAction, CleaningReport


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def normal_bars() -> list[dict]:
    """标准 10 根日 K 线（无异常）。"""
    return [
        {"date": "20260710", "open": 6000, "high": 6050, "low": 5980, "close": 6030, "volume": 10000, "open_interest": 50000},
        {"date": "20260711", "open": 6030, "high": 6080, "low": 6010, "close": 6070, "volume": 11000, "open_interest": 50100},
        {"date": "20260712", "open": 6070, "high": 6100, "low": 6050, "close": 6090, "volume": 12000, "open_interest": 50200},
        {"date": "20260713", "open": 6090, "high": 6150, "low": 6080, "close": 6130, "volume": 13000, "open_interest": 50300},
        {"date": "20260714", "open": 6130, "high": 6180, "low": 6110, "close": 6160, "volume": 14000, "open_interest": 50400},
        {"date": "20260715", "open": 6160, "high": 6200, "low": 6140, "close": 6180, "volume": 15000, "open_interest": 50500},
        {"date": "20260716", "open": 6180, "high": 6220, "low": 6160, "close": 6200, "volume": 16000, "open_interest": 50600},
        {"date": "20260717", "open": 6200, "high": 6250, "low": 6180, "close": 6230, "volume": 17000, "open_interest": 50700},
        {"date": "20260718", "open": 6230, "high": 6280, "low": 6210, "close": 6260, "volume": 18000, "open_interest": 50800},
        {"date": "20260719", "open": 6260, "high": 6300, "low": 6240, "close": 6280, "volume": 19000, "open_interest": 50900},
    ]


# ═══════════════════════════════════════════════════════════════
#  OHLC 清洗测试
# ═══════════════════════════════════════════════════════════════

class TestCleanOhlc:

    def test_normal_bars_no_change(self, normal_bars):
        """正常 K 线不变。"""
        result, report = clean_ohlc(normal_bars)
        assert len(result) == len(normal_bars)
        assert report.total_actions == 0

    def test_high_low_swapped(self):
        """high<low 交换。"""
        bars = [{"date": "20260710", "open": 100, "high": 90, "low": 110, "close": 105, "volume": 1000, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["high"] == 110
        assert result[0]["low"] == 90
        assert any(a.action == "fixed" and "high<low swapped" in a.reason for a in report.actions)

    def test_close_outside_high_low(self):
        """close>high 封顶。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 120, "volume": 1000, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["close"] == 110
        assert any("close>high capped" in a.reason for a in report.actions)

    def test_close_below_low(self):
        """close<low 拉升。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 95, "close": 90, "volume": 1000, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["close"] == 95
        assert any("close<low raised" in a.reason for a in report.actions)

    def test_open_outside_high(self):
        """open>high 封顶。"""
        bars = [{"date": "20260710", "open": 120, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["open"] == 110
        assert any("open>high capped" in a.reason for a in report.actions)

    def test_open_below_low(self):
        """open<low 拉升。"""
        bars = [{"date": "20260710", "open": 80, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["open"] == 90
        assert any("open<low raised" in a.reason for a in report.actions)

    def test_negative_volume_zeroed(self):
        """负成交量归零。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": -100, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert result[0]["volume"] == 0
        assert any("negative volume zeroed" in a.reason for a in report.actions)

    def test_negative_oi_zeroed(self):
        """负持仓归零。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": -50}]
        result, report = clean_ohlc(bars)
        assert result[0]["open_interest"] == 0
        assert any("negative oi zeroed" in a.reason for a in report.actions)

    def test_zero_volume_and_oi_removed(self):
        """volume==0 且 open_interest==0 移除。"""
        bars = [
            {"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500},
            {"date": "20260711", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0, "open_interest": 0},
        ]
        result, report = clean_ohlc(bars)
        assert len(result) == 1
        assert report.removed_count == 1

    def test_volume_zero_but_oi_nonzero_kept(self):
        """volume=0 但持仓非零，保留。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 0, "open_interest": 500}]
        result, report = clean_ohlc(bars)
        assert len(result) == 1
        assert report.removed_count == 0

    def test_multiple_fixes(self):
        """多条修复同时发生。"""
        bars = [
            {"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500},
            {"date": "20260711", "open": 200, "high": 150, "low": 210, "close": 300, "volume": -500, "open_interest": -10},
        ]
        result, report = clean_ohlc(bars)
        assert len(result) == 2
        # 第二条：high<low 交换 + close>high 封顶 + 负成交量 + 负持仓
        assert report.fixed_count >= 4

    def test_empty_input(self):
        """空列表。"""
        result, report = clean_ohlc([])
        assert result == []
        assert report.total_actions == 0

    def test_actions_index_refers_to_original_list(self):
        """index 引用原始列表索引。"""
        bars = [
            {"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500},
            {"date": "20260711", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0, "open_interest": 0},
            {"date": "20260712", "open": 110, "high": 120, "low": 100, "close": 115, "volume": 2000, "open_interest": 600},
        ]
        result, report = clean_ohlc(bars)
        # 第 1 条移除，index=1
        removed_actions = [a for a in report.actions if a.action == "removed"]
        assert any(a.index == 1 for a in removed_actions)


# ═══════════════════════════════════════════════════════════════
#  时间轴清洗测试
# ═══════════════════════════════════════════════════════════════

class TestCleanTimeline:

    def test_normal_bars_no_change(self, normal_bars):
        """正常序列不变。"""
        result, report = clean_timeline(normal_bars)
        assert len(result) == len(normal_bars)
        assert report.removed_count == 0

    def test_duplicate_dates_deduped(self):
        """重复日期去重。"""
        bars = [
            {"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500},
            {"date": "20260710", "close": 105, "volume": 1100, "open_interest": 600},
        ]
        result, report = clean_timeline(bars)
        assert len(result) == 1
        assert result[0]["close"] == 105  # 保留最后一条
        assert report.total_actions >= 1

    def test_unsorted_bars_sorted(self):
        """乱序升序。"""
        bars = [
            {"date": "20260712", "close": 110, "volume": 1000, "open_interest": 500},
            {"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500},
            {"date": "20260711", "close": 105, "volume": 1000, "open_interest": 500},
        ]
        result, report = clean_timeline(bars)
        assert len(result) == 3
        dates = [b["date"] for b in result]
        assert dates == ["20260710", "20260711", "20260712"]

    def test_invalid_date_format_removed(self):
        """非8位日期移除。"""
        bars = [
            {"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500},
            {"date": "invalid", "close": 105, "volume": 1000, "open_interest": 500},
        ]
        result, report = clean_timeline(bars)
        assert len(result) == 1
        assert report.removed_count == 1

    def test_missing_bars_marked(self):
        """缺失日K插入标记。"""
        bars = [
            {"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500},
            {"date": "20260712", "close": 105, "volume": 1000, "open_interest": 500},
        ]
        result, report = clean_timeline(bars)
        assert len(result) == 3  # 10, 11(missing), 12
        missing = [b for b in result if b.get("_missing")]
        assert len(missing) == 1
        assert missing[0]["date"] == "20260711"
        assert any(a.action == "marked" for a in report.actions)

    def test_max_5_missing_bars(self):
        """最多插入5个缺失标记。"""
        bars = [
            {"date": "20260701", "close": 100, "volume": 1000, "open_interest": 500},
            {"date": "20260720", "close": 105, "volume": 1000, "open_interest": 500},
        ]
        result, report = clean_timeline(bars)
        missing = [b for b in result if b.get("_missing")]
        assert len(missing) == 5

    def test_empty_input(self):
        """空列表。"""
        result, report = clean_timeline([])
        assert result == []
        assert report.total_actions == 0


# ═══════════════════════════════════════════════════════════════
#  离群值检测测试
# ═══════════════════════════════════════════════════════════════

class TestCleanOutliers:

    def test_normal_bars_no_change(self, normal_bars):
        """正常序列不变。"""
        result, report = clean_outliers(normal_bars)
        assert len(result) == len(normal_bars)
        assert report.fixed_count == 0

    def test_price_spike_fixed(self):
        """价格毛刺修复（长序列单个突刺）。"""
        bars = []
        base = 100
        for i in range(20):
            bars.append({
                "date": f"202607{i+1:02d}", "close": base + i, "high": base + i + 5, "low": base + i - 5,
                "open": base + i, "volume": 1000, "open_interest": 500,
            })
        # 在第 10 根插入毛刺（close 从 109 跳到 500）
        bars[10]["close"] = 500
        bars[10]["high"] = 505
        bars[10]["low"] = 495
        result, report = clean_outliers(bars, z_threshold=3.0)
        # 毛刺应被检测到
        assert report.fixed_count >= 1
        # 修复后的 close 应接近邻居（109 和 111 之间 ≈ 110）
        fixed_action = [a for a in report.actions if a.action == "fixed" and a.field == "close"]
        assert len(fixed_action) >= 1
        assert abs(result[10]["close"] - 110) < 10

    def test_volume_spike_smoothed(self):
        """孤立暴增量平滑。"""
        bars = []
        for i in range(10):
            bars.append({
                "date": f"202607{i+10:02d}", "close": 100 + i, "high": 105 + i, "low": 95 + i,
                "open": 100 + i, "volume": 1000, "open_interest": 500,
            })
        bars[5]["volume"] = 50000  # 50 倍暴增
        result, report = clean_outliers(bars, z_threshold=3.0)
        # 暴增量应被平滑
        assert result[5]["volume"] < 10000  # 被平滑到均值附近

    def test_too_few_bars_skipped(self):
        """不足3根跳过毛刺检测。"""
        bars = [{"date": "20260710", "close": 100, "high": 105, "low": 95, "open": 100, "volume": 1000, "open_interest": 500}]
        result, report = clean_outliers(bars)
        assert result == bars
        assert report.fixed_count == 0

    def test_empty_input(self):
        """空列表。"""
        result, report = clean_outliers([])
        assert result == []
        assert report.total_actions == 0


# ═══════════════════════════════════════════════════════════════
#  复权处理测试
# ═══════════════════════════════════════════════════════════════

class TestCleanAdjustment:

    def test_normal_bars_no_change(self, normal_bars):
        """连续上涨无跳空。"""
        result, report = clean_adjustment(normal_bars, method="forward")
        assert len(result) == len(normal_bars)
        assert report.fixed_count == 0

    def test_roll_gap_marked(self):
        """换月跳空标记。"""
        # 构造一个在中间有跳空的序列
        bars = [
            {"date": "20260710", "close": 100, "high": 105, "low": 95, "open": 100, "volume": 10000, "open_interest": 50000},
            {"date": "20260711", "close": 102, "high": 107, "low": 97, "open": 102, "volume": 11000, "open_interest": 50100},
            {"date": "20260712", "close": 80, "high": 85, "low": 75, "open": 80, "volume": 12000, "open_interest": 50200},
            {"date": "20260713", "close": 82, "high": 87, "low": 77, "open": 82, "volume": 13000, "open_interest": 50300},
            {"date": "20260714", "close": 84, "high": 89, "low": 79, "open": 84, "volume": 14000, "open_interest": 50400},
        ]
        result, report = clean_adjustment(bars, method="forward", gap_threshold=0.03)
        # 102→80 跳空 22% > 3%，且成交量和前一根差不多，应该被标记为换月
        gap_bars = [b for b in result if b.get("_roll_gap")]
        assert len(gap_bars) >= 1
        # 跳空之后的 close 应该被前复权修正（连续）
        assert report.total_actions >= 1

    def test_too_few_bars_skipped(self):
        """不足5根跳过。"""
        bars = [{"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500, "high": 105, "low": 95, "open": 100}]
        result, report = clean_adjustment(bars)
        assert result == bars
        assert report.total_actions == 0

    def test_no_adjustment_method_none(self):
        """method="none" 只标记不调整。"""
        bars = [
            {"date": "20260710", "close": 100, "high": 105, "low": 95, "open": 100, "volume": 10000, "open_interest": 50000},
            {"date": "20260711", "close": 102, "high": 107, "low": 97, "open": 102, "volume": 11000, "open_interest": 50100},
            {"date": "20260712", "close": 80, "high": 85, "low": 75, "open": 80, "volume": 12000, "open_interest": 50200},
            {"date": "20260713", "close": 82, "high": 87, "low": 77, "open": 82, "volume": 13000, "open_interest": 50300},
            {"date": "20260714", "close": 84, "high": 89, "low": 79, "open": 84, "volume": 14000, "open_interest": 50400},
        ]
        result, report = clean_adjustment(bars, method="none", gap_threshold=0.03)
        gap_bars = [b for b in result if b.get("_roll_gap")]
        assert len(gap_bars) >= 1  # 标记存在
        assert report.fixed_count == 0  # 没有调整

    def test_volume_surge_not_marked_as_gap(self):
        """成交量暴增的跳空不当成换月。"""
        bars = [
            {"date": "20260710", "close": 100, "high": 105, "low": 95, "open": 100, "volume": 10000, "open_interest": 50000},
            {"date": "20260711", "close": 102, "high": 107, "low": 97, "open": 102, "volume": 11000, "open_interest": 50100},
            {"date": "20260712", "close": 80, "high": 85, "low": 75, "open": 80, "volume": 50000, "open_interest": 50200},
            {"date": "20260713", "close": 82, "high": 87, "low": 77, "open": 82, "volume": 13000, "open_interest": 50300},
        ]
        result, report = clean_adjustment(bars, method="forward", gap_threshold=0.03)
        # 虽然 102→80 跳空22%，但成交量暴增到5倍，不判定为换月
        gap_bars = [b for b in result if b.get("_roll_gap")]
        assert len(gap_bars) == 0

    def test_empty_input(self):
        """空列表。"""
        result, report = clean_adjustment([])
        assert result == []
        assert report.total_actions == 0


# ═══════════════════════════════════════════════════════════════
#  期货专项清洗测试
# ═══════════════════════════════════════════════════════════════

class TestCleanFutures:

    def test_main_continuous_skipped(self):
        """主力连续品种跳过交割月过滤。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [{"date": "20260710", "close": 100, "volume": 1000, "open_interest": 500, "high": 105, "low": 95, "open": 100}]
        result, report = clean_futures(bars, symbol="RB0")
        assert len(result) == 1
        assert report.removed_count == 0

    def test_delivery_month_filtered(self):
        """具体合约交割月前过滤。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260915", "close": 100, "volume": 1000, "open_interest": 500, "high": 105, "low": 95, "open": 100},
            {"date": "20260920", "close": 102, "volume": 1100, "open_interest": 600, "high": 107, "low": 97, "open": 102},
            {"date": "20260925", "close": 101, "volume": 500, "open_interest": 300, "high": 106, "low": 96, "open": 101},
            {"date": "20260928", "close": 103, "volume": 200, "open_interest": 100, "high": 108, "low": 98, "open": 103},
        ]
        # RB2609 交割月为 2026-09，排除前 15 天 → 2026-09-15 后的全部排除
        result, report = clean_futures(bars, symbol="RB2609", delivery_exclude_days=15)
        assert report.removed_count >= 1
        # 9月28日最接近交割，应该被剔除
        assert any("2609" in a.reason for a in report.actions)

    def test_delivery_month_far_dates_kept(self):
        """远月合约保留。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260301", "close": 100, "volume": 1000, "open_interest": 500, "high": 105, "low": 95, "open": 100},
            {"date": "20260302", "close": 102, "volume": 1100, "open_interest": 600, "high": 107, "low": 97, "open": 102},
        ]
        result, report = clean_futures(bars, symbol="RB2609", delivery_exclude_days=15)
        # 3月份距离交割月（9月）很远，全部保留
        assert len(result) == 2
        assert report.removed_count == 0

    def test_limit_up_detected(self):
        """涨停封板检测。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260710", "close": 100, "volume": 10000, "open_interest": 50000, "high": 105, "low": 95, "open": 100},
            # 涨停日：涨幅 5% ≥ RB阈值5%*0.9，成交量骤降到 10%
            {"date": "20260711", "close": 105, "volume": 1000, "open_interest": 50000, "high": 105, "low": 104, "open": 105},
        ]
        result, report = clean_futures(bars, symbol="RB")
        limit_up = [b for b in result if b.get("_limit_up")]
        assert len(limit_up) == 1
        assert any("limit up" in a.reason for a in report.actions)

    def test_limit_down_detected(self):
        """跌停封板检测。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260710", "close": 100, "volume": 10000, "open_interest": 50000, "high": 105, "low": 95, "open": 100},
            # 跌停日：跌幅 5% 且成交量骤降
            {"date": "20260711", "close": 95, "volume": 800, "open_interest": 50000, "high": 95, "low": 94, "open": 95},
        ]
        result, report = clean_futures(bars, symbol="RB")
        limit_down = [b for b in result if b.get("_limit_down")]
        assert len(limit_down) == 1
        assert any("limit down" in a.reason for a in report.actions)

    def test_limit_normal_volume_not_marked(self):
        """正常成交量不标记。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260710", "close": 100, "volume": 10000, "open_interest": 50000, "high": 105, "low": 95, "open": 100},
            # 涨幅 5% 但成交量正常（>30%），不标记
            {"date": "20260711", "close": 105, "volume": 8000, "open_interest": 50000, "high": 105, "low": 100, "open": 100},
        ]
        result, report = clean_futures(bars, symbol="RB")
        limit_up = [b for b in result if b.get("_limit_up")]
        assert len(limit_up) == 0

    def test_small_change_not_marked(self):
        """小涨不标记。"""
        from data_adapter.cleaning.futures import clean_futures
        bars = [
            {"date": "20260710", "close": 100, "volume": 10000, "open_interest": 50000, "high": 105, "low": 95, "open": 100},
            {"date": "20260711", "close": 101, "volume": 500, "open_interest": 50000, "high": 102, "low": 100, "open": 100},
        ]
        result, report = clean_futures(bars, symbol="RB")
        assert report.total_actions == 0

    def test_get_limit_threshold(self):
        """涨跌停阈值查询。"""
        from data_adapter.cleaning.futures import _get_limit_threshold
        assert _get_limit_threshold("IF") == 0.10
        assert _get_limit_threshold("AU") == 0.04
        assert _get_limit_threshold("UNKNOWN") == 0.05  # 默认

    def test_parse_contract_month(self):
        """合约交割月解析。"""
        from data_adapter.cleaning.futures import _parse_contract_month
        assert _parse_contract_month("RB2610") == "202610"
        assert _parse_contract_month("CF2609") == "202609"
        assert _parse_contract_month("RB") is None
        assert _parse_contract_month("RB0") is None
        assert _parse_contract_month("RB888") is None
        assert _parse_contract_month("") is None
        assert _parse_contract_month("MAIN") is None

    def test_empty_input(self):
        """空列表。"""
        from data_adapter.cleaning.futures import clean_futures
        result, report = clean_futures([], symbol="RB")
        assert result == []
        assert report.total_actions == 0


# ═══════════════════════════════════════════════════════════════
#  基本面清洗测试（Phase 3）
# ═══════════════════════════════════════════════════════════════

class TestCleanFundamental:

    # ── 缺失字段 ──

    def test_handle_missing_basis(self):
        """基缺少 spot_price。"""
        from data_adapter.cleaning.fundamental import handle_missing_fields
        data = {"data": {"symbol": "RB"}, "data_grade": "PRIMARY"}
        result, actions = handle_missing_fields(data, "basis")
        assert any("missing" in a.reason and "spot_price" in a.reason for a in actions)

    def test_handle_missing_warrant_ok(self):
        """仓单字段完整。"""
        from data_adapter.cleaning.fundamental import handle_missing_fields
        data = {"data": {"total": 10000, "daily_change": 500}, "data_grade": "PRIMARY"}
        result, actions = handle_missing_fields(data, "warrant")
        missing = [a for a in actions if "missing" in a.reason]
        assert len(missing) == 0

    def test_missing_over_half_downgraded(self):
        """缺失超 50% 降级。"""
        from data_adapter.cleaning.fundamental import handle_missing_fields
        data = {"data": {"symbol": "RB"}, "data_grade": "PRIMARY"}
        result, actions = handle_missing_fields(data, "position_ranking")
        assert result.get("data_grade") == "DEGRADED"

    # ── 值有效性 ──

    def test_negative_total_absolved(self):
        """负仓单总量取绝对值。"""
        from data_adapter.cleaning.fundamental import validate_snapshot_values
        data = {"data": {"total": -10000, "daily_change": 500}, "data_grade": "PRIMARY"}
        result, actions = validate_snapshot_values(data, "warrant")
        assert result["data"]["total"] == 10000
        assert any("absolved" in a.reason for a in actions)

    def test_spot_price_below_min_clipped(self):
        """现货价低于下限钳制。"""
        from data_adapter.cleaning.fundamental import validate_snapshot_values
        data = {"data": {"spot_price": 0.0001}, "data_grade": "PRIMARY"}
        result, actions = validate_snapshot_values(data, "basis")
        assert result["data"]["spot_price"] == 0.001

    def test_non_numeric_fixed(self):
        """非数字字段置 None。"""
        from data_adapter.cleaning.fundamental import validate_snapshot_values
        data = {"data": {"total_oi": "N/A"}, "data_grade": "PRIMARY"}
        result, actions = validate_snapshot_values(data, "fund_flow")
        assert result["data"]["total_oi"] is None
        assert any("non-numeric" in a.reason for a in actions)

    # ── 交叉校验 ──

    def test_net_long_consistency_fixed(self):
        """net_long 与 long_volume - short_volume 不一致时修正。"""
        from data_adapter.cleaning.fundamental import validate_snapshot_values
        data = {"data": {"long_volume": 100000, "short_volume": 80000, "net_long": 5000}, "data_grade": "PRIMARY"}
        result, actions = validate_snapshot_values(data, "position_ranking")
        assert result["data"]["net_long"] == 20000  # 100k - 80k
        assert any("recalculated" in a.reason for a in actions)

    def test_non_positive_ratio_fixed(self):
        """非正多空比修正为 1.0。"""
        from data_adapter.cleaning.fundamental import validate_snapshot_values
        data = {"data": {"total_oi": 50000, "long_short_ratio": -1}, "data_grade": "PRIMARY"}
        result, actions = validate_snapshot_values(data, "fund_flow")
        assert result["data"]["long_short_ratio"] == 1.0

    # ── 新鲜度 ──

    def test_fresh_basis_no_action(self):
        """当日数据 = FRESH。"""
        from data_adapter.cleaning.fundamental import rate_freshness
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        data = {"data": {"data_date": today}, "data_grade": "PRIMARY"}
        result, actions = rate_freshness(data, "basis")
        assert result["data"]["freshness_level"] == "FRESH"
        assert len(actions) == 0

    def test_stale_data_warning(self):
        """过时数据标记 STALE_WARNING + 降级。"""
        from data_adapter.cleaning.fundamental import rate_freshness
        data = {"data": {"data_date": "20200101"}, "data_grade": "PRIMARY"}
        result, actions = rate_freshness(data, "basis")
        assert result["data"]["freshness_level"] == "STALE_WARNING"
        assert result["data_grade"] == "STALE"

    def test_no_date_unknown(self):
        """无日期字段 = UNKNOWN。"""
        from data_adapter.cleaning.fundamental import rate_freshness
        data = {"data": {"value": 100}, "data_grade": "PRIMARY"}
        result, actions = rate_freshness(data, "basis")
        assert result["data"]["freshness_level"] == "UNKNOWN"
        assert result["data"]["freshness_days"] is None

    # ── 口径变更 ──

    def test_caliber_change_detected(self):
        """SA 口径变更事件被检测。"""
        from data_adapter.cleaning.fundamental import detect_caliber_change
        data = {"data": {"margin_rate": 0.12}, "data_grade": "PRIMARY"}
        result, actions = detect_caliber_change(data, "basis", symbol="SA")
        assert len(actions) >= 1
        assert any("caliber" in a.reason for a in actions)
        assert "_caliber_warnings" in result

    def test_caliber_no_match(self):
        """无匹配品种无告警。"""
        from data_adapter.cleaning.fundamental import detect_caliber_change
        data = {"data": {"margin_rate": 0.05}, "data_grade": "PRIMARY"}
        result, actions = detect_caliber_change(data, "basis", symbol="RB")
        assert len(actions) == 0

    # ── 修订追踪 ──

    def test_revision_tracked(self):
        """修订版追踪标记。"""
        from data_adapter.cleaning.fundamental import track_revision
        data = {"data": {"value": 100}, "data_grade": "PRIMARY"}
        result, actions = track_revision(data, "basis")
        assert "_revision" in result["data"]
        assert result["data"]["_revision"]["version"] == "v1"
        assert result["data"]["_revision"]["tracked_at"] is not None

    # ── 统一入口 ──

    def test_clean_fundamental_snapshot_basis(self):
        """基差全链路清洗。"""
        from data_adapter.cleaning.fundamental import clean_fundamental_snapshot
        data = {"data": {"symbol": "RB", "spot_price": 3500}, "data_grade": "PRIMARY"}
        result, report = clean_fundamental_snapshot(data, "basis", symbol="RB")
        assert isinstance(report, CleaningReport)
        assert result["data"].get("freshness_level") in ("FRESH", "STALE", "STALE_WARNING", "UNKNOWN")
        assert "_revision" in result["data"]

    def test_clean_fundamental_pipeline_disabled(self):
        """关闭时原样返回。"""
        from data_adapter.cleaning import clean_fundamental
        data = {"data": {"value": 100}, "data_grade": "PRIMARY"}
        result, report = clean_fundamental(data, "basis", enabled=False)
        assert result == data
        assert report.total_actions == 0

    def test_clean_fundamental_warrant(self):
        """仓单全链路清洗。"""
        from data_adapter.cleaning import clean_fundamental
        data = {"data": {"symbol": "CU", "total": 50000, "daily_change": -200}, "data_grade": "PRIMARY"}
        result, report = clean_fundamental(data, "warrant", symbol="CU")
        assert isinstance(report, CleaningReport)
        assert result["data"].get("freshness_level") is not None

    def test_clean_fundamental_data_batch(self):
        """批量清洗 fdc_data。"""
        from data_adapter.cleaning import clean_fundamental_data
        fdc_data = {
            "RB": {
                "basis": {"data": {"spot_price": 3500}, "data_grade": "PRIMARY"},
                "warrant": {"data": {"total": 10000}, "data_grade": "PRIMARY"},
                "kline": {"data": {}, "data_grade": "PRIMARY"},
            }
        }
        result = clean_fundamental_data(fdc_data, cleaning_enabled=True)
        assert "RB" in result
        assert "_cleaning" in result["RB"]["basis"]
        assert "_cleaning" in result["RB"]["warrant"]
        # kline 不在 _FUNDAMENTAL_TYPES 中，不洗
        assert "_cleaning" not in result["RB"].get("kline", {})

    def test_clean_fundamental_data_disabled(self):
        """批量清洗关闭时原样返回。"""
        from data_adapter.cleaning import clean_fundamental_data
        fdc_data = {"RB": {"basis": {"data": {"spot_price": 3500}, "data_grade": "PRIMARY"}}}
        result = clean_fundamental_data(fdc_data, cleaning_enabled=False)
        assert "_cleaning" not in result["RB"].get("basis", {})

    def test_empty_input(self):
        """空列表/空字典。"""
        from data_adapter.cleaning.fundamental import clean_fundamental_snapshot
        data = {}
        result, report = clean_fundamental_snapshot(data, "basis")
        assert isinstance(report, CleaningReport)


# ═══════════════════════════════════════════════════════════════
#  全链路集成测试
# ═══════════════════════════════════════════════════════════════

class TestCleanKline:

    def test_normal_bars_passthrough(self, normal_bars):
        """正常 K 线经全链路无异常。"""
        result, report = clean_kline(normal_bars)
        assert len(result) == len(normal_bars)
        assert isinstance(report, CleaningReport)
        assert report.cleaning_id != ""

    def test_dirty_bars_cleaned(self):
        """脏数据全链路清洗。"""
        bars = [
            {"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500},
            {"date": "20260710", "open": 102, "high": 112, "low": 92, "close": 107, "volume": 1100, "open_interest": 600},  # 重复
            {"date": "20260712", "open": 200, "high": 150, "low": 210, "close": 300, "volume": -500, "open_interest": -10},  # OHLC异常
            {"date": "20260714", "open": 110, "high": 115, "low": 105, "close": 112, "volume": 2000, "open_interest": 700},
        ]
        result, report = clean_kline(bars)
        assert len(result) >= 3  # 去重后至少3条
        assert report.total_actions >= 1  # 有清洗动作
        # 检查时间轴清洗（去重）
        dedup = [a for a in report.actions if a.action == "deduped"]
        assert len(dedup) >= 1
        # 检查 OHLC 修复
        fixed = [a for a in report.actions if a.action == "fixed"]
        assert len(fixed) >= 1

    def test_config_disabled_all(self):
        """全部清洗关闭时原样返回。"""
        bars = [{"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500}]
        result, report = clean_kline(bars, config={
            "enable_ohlc": False,
            "enable_outlier": False,
            "enable_adjustment": False,
            "enable_timeline": False,
        })
        assert result == bars
        assert report.total_actions == 0

    def test_config_partial(self):
        """部分清洗开启。"""
        bars = [
            {"date": "20260710", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "open_interest": 500},
            {"date": "20260710", "open": 102, "high": 112, "low": 92, "close": 107, "volume": 1100, "open_interest": 600},
        ]
        # 只开 timeline（去重），关 OHLC
        result, report = clean_kline(bars, config={
            "enable_ohlc": False,
            "enable_outlier": False,
            "enable_adjustment": False,
            "enable_timeline": True,
        })
        assert len(result) == 1  # 去重
        assert report.total_actions >= 1

    def test_cleaning_report_properties(self):
        """CleaningReport 属性计算正确。"""
        report = CleaningReport(cleaning_id="test", actions=[
            CleaningAction(action="removed", field="volume", index=0, reason="zero"),
            CleaningAction(action="fixed", field="close", index=1, reason="spike"),
            CleaningAction(action="marked", field="date", index=2, reason="missing bar"),
        ])
        assert report.total_actions == 3
        assert report.removed_count == 1
        assert report.fixed_count == 1
