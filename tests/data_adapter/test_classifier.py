"""品种分类器 — 单元测试"""

from data_adapter.instrument_classifier import classify, MarketType, get_market_label


class TestInstrumentClassifier:
    """验证品种分类器的市场类型识别"""

    def test_commodity_futures(self):
        """商品期货 → COMMODITY_FUTURES"""
        for sym in ["RB", "CU", "AU", "SC", "MA", "CF", "P", "Y", "JM", "FG"]:
            assert classify(sym) == MarketType.COMMODITY_FUTURES, f"{sym} 应是商品期货"

    def test_index_futures(self):
        """股指期货 → INDEX_FUTURES"""
        for sym in ["IF", "IC", "IH", "IM"]:
            assert classify(sym) == MarketType.INDEX_FUTURES, f"{sym} 应是股指期货"

    def test_bond_futures(self):
        """国债期货 → BOND_FUTURES"""
        for sym in ["T", "TF", "TS", "TL"]:
            assert classify(sym) == MarketType.BOND_FUTURES, f"{sym} 应是国债期货"

    def test_etf_with_suffix(self):
        """带后缀的 ETF 代码 → ETF"""
        assert classify("510050.SH") == MarketType.ETF
        assert classify("159915.SZ") == MarketType.ETF

    def test_etf_without_suffix(self):
        """无后缀的 ETF 数字代码 → ETF"""
        assert classify("510050") == MarketType.ETF
        assert classify("510300") == MarketType.ETF
        assert classify("159915") == MarketType.ETF
        assert classify("588000") == MarketType.ETF

    def test_lowercase(self):
        """不区分大小写"""
        assert classify("if") == MarketType.INDEX_FUTURES
        assert classify("t") == MarketType.BOND_FUTURES
        assert classify("rb") == MarketType.COMMODITY_FUTURES

    def test_get_market_label(self):
        """中文标签"""
        assert get_market_label(MarketType.INDEX_FUTURES) == "股指期货"
        assert get_market_label(MarketType.BOND_FUTURES) == "国债期货"
        assert get_market_label(MarketType.ETF) == "ETF"
        assert get_market_label(MarketType.COMMODITY_FUTURES) == "商品期货"
