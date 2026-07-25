"""测试技术评分代码化模块。"""

from data_adapter.factors.technical_score import (
    _momentum_score,
    _trend_score,
    _volume_score,
    _volatility_score,
    compute_technical_score,
)


def test_compute_technical_score_bullish():
    """验证多头排列下的评分 > 50。"""
    indicators = {
        "MA5": 5020.0,
        "MA10": 5000.0,
        "MA20": 4980.0,
        "MA60": 4950.0,
        "RSI14": 55.0,
        "ADX": 30.0,
        "VOL_RATIO": 1.5,
        "volatility_pct": 0.8,
        "SUPERTREND_DIR": 1,
        "DC_POS": 0.85,
        "MACD_DIF": 20.0,
        "MACD_DEA": 15.0,
    }
    score = compute_technical_score("TEST", indicators)
    assert 50 < score <= 100, f"Bullish market should score > 50, got {score}"


def test_compute_technical_score_bearish():
    """验证空头排列下的评分 < 50。"""
    indicators = {
        "MA5": 4800.0,
        "MA10": 4850.0,
        "MA20": 4900.0,
        "MA60": 4950.0,
        "RSI14": 35.0,
        "ADX": 28.0,
        "VOL_RATIO": 1.5,
        "volatility_pct": 0.8,
        "SUPERTREND_DIR": -1,
        "DC_POS": 0.15,
        "MACD_DIF": -10.0,
        "MACD_DEA": -5.0,
    }
    score = compute_technical_score("TEST", indicators)
    assert 0 <= score < 50, f"Bearish market should score < 50, got {score}"


def test_compute_technical_score_neutral():
    """验证震荡行情下评分接近 50。"""
    indicators = {
        "MA5": 5000.0,
        "MA10": 5000.0,
        "MA20": 5000.0,
        "MA60": 5000.0,
        "RSI14": 50.0,
        "ADX": 15.0,
        "VOL_RATIO": 0.9,
        "volatility_pct": 0.8,
        "MACD_DIF": 0.0,
        "MACD_DEA": 0.0,
    }
    score = compute_technical_score("TEST", indicators)
    assert 30 <= score <= 70, f"Neutral market should score ~50, got {score}"


def test_compute_technical_score_minimal_data():
    """验证数据不足时的兜底行为。"""
    indicators = {"MA5": 5000.0, "MA20": 4980.0}
    score = compute_technical_score("TEST", indicators)
    assert 0 <= score <= 100, f"Should produce a valid score, got {score}"
    # 仅有趋势分时应在 50 附近
    assert 40 <= score <= 70, f"Minimal data should score near 50, got {score}"


def test_compute_technical_score_empty():
    """验证空数据时的行为。"""
    score = compute_technical_score("TEST", {})
    assert score == 50, f"Empty data should return baseline 50, got {score}"


def test_trend_score_bullish():
    """验证多头排列趋势分。"""
    ind = {"MA5": 5100, "MA20": 5000, "MA60": 4900}
    s = _trend_score(ind)
    assert s > 0, f"Bullish alignment should give positive trend score, got {s}"


def test_trend_score_bearish():
    """验证空头排列趋势分。"""
    ind = {"MA5": 4900, "MA20": 5000, "MA60": 5100}
    s = _trend_score(ind)
    assert s < 0, f"Bearish alignment should give negative trend score, got {s}"


def test_momentum_score_oversold():
    """验证超卖区动量分。"""
    ind = {"RSI14": 25.0}
    s = _momentum_score(ind)
    assert s > 0, f"Oversold should give positive momentum score, got {s}"


def test_momentum_score_overbought():
    """验证超买区动量分。"""
    ind = {"RSI14": 75.0}
    s = _momentum_score(ind)
    assert s < 0, f"Overbought should give negative momentum score, got {s}"


def test_volume_score_bullish():
    """验证放量上涨的成交量分。"""
    ind = {"VOL_RATIO": 1.5, "MA5": 5100, "MA20": 5000}
    s = _volume_score(ind)
    assert s > 0, f"Bullish volume should give positive score, got {s}"


def test_volume_score_bearish():
    """验证放量下跌的成交量分。"""
    ind = {"VOL_RATIO": 1.5, "MA5": 4900, "MA20": 5000}
    s = _volume_score(ind)
    assert s < 0, f"Bearish volume should give negative score, got {s}"


def test_volatility_score_low():
    """验证低波动率场景。"""
    ind = {"volatility_pct": 0.3}
    s = _volatility_score(ind)
    assert s > 0, f"Low volatility should give positive score, got {s}"


def test_volatility_score_high():
    """验证高波动率场景。"""
    ind = {"volatility_pct": 2.5}
    s = _volatility_score(ind)
    assert s < 0, f"High volatility should give negative score, got {s}"


def test_reproducibility():
    """验证相同输入产生相同输出。"""
    indicators = {
        "MA5": 5020.0,
        "MA10": 5000.0,
        "MA20": 4980.0,
        "MA60": 4950.0,
        "RSI14": 55.0,
        "ADX": 30.0,
        "VOL_RATIO": 1.5,
        "volatility_pct": 0.8,
        "SUPERTREND_DIR": 1,
        "DC_POS": 0.85,
        "MACD_DIF": 20.0,
        "MACD_DEA": 15.0,
        "close": 5000.0,
    }
    score1 = compute_technical_score("TEST", indicators)
    score2 = compute_technical_score("TEST", indicators)
    assert score1 == score2, f"Same inputs should give same score: {score1} vs {score2}"
