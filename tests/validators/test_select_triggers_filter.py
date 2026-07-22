"""
select_triggers disable_filter 测试
====================================
验证：
1. filter=ON → 读 total（旧行为，过滤后）
2. filter=OFF → 读 _raw_total（无过滤，原始分）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 清除 scripts 缓存，确保从已设置的 sys.path 加载
if "scripts" in sys.modules:
    del sys.modules["scripts"]
for k in list(sys.modules.keys()):
    if k.startswith("scripts."):
        del sys.modules[k]

from scripts.run_debate import select_triggers


def _make_scan(all_ranked):
    return {"all_ranked": all_ranked, "_meta": {"total": len(all_ranked)}}


class TestSelectTriggersFilter:
    """select_triggers 过滤开关测试"""

    def test_filter_on_reads_total(self):
        """filter=ON → 读 total"""
        records = [
            {"symbol": "SA", "total": 0, "_raw_total": -81, "grade": "NOISE"},
            {"symbol": "PB", "total": -46, "_raw_total": -46, "grade": "WATCH"},
            {"symbol": "SC", "total": -26, "_raw_total": -26, "grade": "WEAK"},
            {"symbol": "L", "total": 0, "_raw_total": -26, "grade": "NOISE"},
        ]
        scan = _make_scan(records)
        triggers = select_triggers(scan, threshold=20, disable_filter=False)
        symbols = [t["symbol"] for t in triggers]
        assert "SA" not in symbols, "SA total=0 应被过滤"
        assert "L" not in symbols, "L total=0 应被过滤"
        assert "PB" in symbols, "PB total=-46 应触发"
        assert "SC" in symbols, "SC total=-26 应触发"
        assert len(triggers) == 2, "filter=ON 只应有 2 个触发品种"

    def test_filter_off_reads_raw_total(self):
        """filter=OFF → 读 _raw_total"""
        records = [
            {"symbol": "SA", "total": 0, "_raw_total": -81, "grade": "NOISE"},
            {"symbol": "PB", "total": -46, "_raw_total": -46, "grade": "WATCH"},
            {"symbol": "SC", "total": -26, "_raw_total": -26, "grade": "WEAK"},
            {"symbol": "L", "total": 0, "_raw_total": -26, "grade": "NOISE"},
            {"symbol": "J", "total": 0, "_raw_total": -66, "grade": "NOISE"},
        ]
        scan = _make_scan(records)
        triggers = select_triggers(scan, threshold=20, disable_filter=True)
        symbols = [t["symbol"] for t in triggers]
        assert "SA" in symbols, "SA _raw_total=-81 应触发"
        assert "J" in symbols, "J _raw_total=-66 应触发"
        assert "PB" in symbols, "PB 应触发"
        assert "SC" in symbols, "SC 应触发"
        assert "L" in symbols, "L _raw_total=-26 应触发"
        assert len(triggers) == 5, "filter=OFF 5 品种应全部触发"

    def test_fallback_to_total_when_no_raw_total(self):
        """没有 _raw_total 时降级回 total"""
        records = [
            {"symbol": "RB", "total": -38, "grade": "WEAK"},
            {"symbol": "CU", "total": 0, "grade": "NOISE"},
        ]
        scan = _make_scan(records)
        triggers = select_triggers(scan, threshold=20, disable_filter=True)
        symbols = [t["symbol"] for t in triggers]
        assert "RB" in symbols, "无 _raw_total 但 total=-38 应触发"
        assert "CU" not in symbols, "CU total=0 不应触发"
