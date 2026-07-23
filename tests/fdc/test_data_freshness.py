"""测试数据新鲜度计算 — 支持 %Y%m%d 和 %Y-%m-%d 两种格式"""
import sys
sys.path.insert(0, r'D:\Programs\FDT')

from datetime import date, timedelta
from futures_data_core.core.data_quality import _calc_freshness_days


def test_freshness_yyyymmdd_format():
    """%Y%m%d 格式日期（WebFallback 格式）"""
    today = date.today()
    days_ago = (today - timedelta(days=3)).strftime("%Y%m%d")
    result = _calc_freshness_days(days_ago)
    assert isinstance(result, int)
    assert result > 0
    assert result <= 3  # 3自然日 * 0.7 ≈ 2交易日


def test_freshness_yyyy_mm_dd_format():
    """%Y-%m-%d 格式日期（DataCore 格式）"""
    today = date.today()
    days_ago = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    result = _calc_freshness_days(days_ago)
    assert isinstance(result, int)
    assert result > 0
    assert result <= 3


def test_freshness_today():
    """当天日期应返回 0 或接近 0"""
    today_str = date.today().strftime("%Y%m%d")
    result = _calc_freshness_days(today_str)
    assert result >= 0
    assert result <= 1


def test_freshness_stale_data():
    """旧数据应返回大值"""
    stale = "20260119"
    result = _calc_freshness_days(stale)
    assert result >= 100  # >100 交易日


def test_freshness_empty_string():
    """空字符串返回 999"""
    assert _calc_freshness_days("") == 999


def test_freshness_invalid_format():
    """无效格式返回 999"""
    assert _calc_freshness_days("not-a-date") == 999
