"""测试字段标准化 — normalize_kline_row 对多种日期格式的处理"""
import sys
sys.path.insert(0, r'D:\Programs\FDT')

from futures_data_core.core.field_normalizer import normalize_kline_row


def test_normalize_yyyymmdd_date():
    """%Y%m%d 格式日期（TqSDK/WebFallback）"""
    row = {"date": "20260723", "open": 5884, "high": 5888, "low": 5832, "close": 5868, "volume": 128032}
    out = normalize_kline_row(row)
    assert out["date"] == "20260723"
    assert out["open"] == 5884.0
    assert out["close"] == 5868.0
    assert out["volume"] == 128032.0


def test_normalize_yyyy_mm_dd_date():
    """%Y-%m-%d 格式日期（DataCore）"""
    row = {"date": "2026-07-23", "open": 5884, "high": 5888, "low": 5832, "close": 5868, "volume": 128032}
    out = normalize_kline_row(row)
    assert out["date"] == "2026-07-23"
    assert out["open"] == 5884.0


def test_normalize_oi_field():
    """oi 字段统一（废弃 open_interest）"""
    row = {"date": "20260723", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100, "oi": 553333}
    out = normalize_kline_row(row)
    assert out["oi"] == 553333


def test_normalize_open_interest_fallback():
    """open_interest → oi 回退"""
    row = {"date": "20260723", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100, "open_interest": 553333}
    out = normalize_kline_row(row)
    assert out["oi"] == 553333
