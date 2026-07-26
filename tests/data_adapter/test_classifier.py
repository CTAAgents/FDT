"""品种分类器 — 单元测试（G23 扩展至 7 种市场类型）"""

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

    # ── G23 新增：股票 ──
    def test_stock_shanghai(self):
        """沪主板/科创板 → STOCK"""
        assert classify("600519") == MarketType.STOCK   # 贵州茅台（沪主板）
        assert classify("601318") == MarketType.STOCK   # 中国平安（沪主板）
        assert classify("688981") == MarketType.STOCK   # 中芯国际（科创板）
        assert classify("600519.SH") == MarketType.STOCK

    def test_stock_shenzhen(self):
        """深主板/创业板 → STOCK"""
        assert classify("000001") == MarketType.STOCK   # 平安银行（深主板）
        assert classify("300750") == MarketType.STOCK   # 宁德时代（创业板）
        assert classify("000001.SZ") == MarketType.STOCK

    def test_stock_beijing(self):
        """北交所 → STOCK"""
        assert classify("430017") == MarketType.STOCK   # 北交所
        assert classify("830799") == MarketType.STOCK   # 北交所

    # ── G23 新增：REITs ──
    def test_reit(self):
        """REITs → REIT"""
        assert classify("180801") == MarketType.REIT   # 深 REIT
        assert classify("508099") == MarketType.REIT   # 沪 REIT
        assert classify("180801.SZ") == MarketType.REIT

    # ── G23 新增：可转债 ──
    def test_convertible_bond(self):
        """可转债 → CONVERTIBLE_BOND"""
        assert classify("110045") == MarketType.CONVERTIBLE_BOND  # 沪可转债
        assert classify("123456") == MarketType.CONVERTIBLE_BOND  # 深可转债
        assert classify("113044") == MarketType.CONVERTIBLE_BOND

    def test_no_false_positive_stock(self):
        """期货代码不应误识别为股票"""
        assert classify("RB") == MarketType.COMMODITY_FUTURES
        assert classify("IF") == MarketType.INDEX_FUTURES
        assert classify("T") == MarketType.BOND_FUTURES
        # 期货主力合约格式
        assert classify("RB2510") == MarketType.COMMODITY_FUTURES

    def test_lowercase(self):
        """不区分大小写"""
        assert classify("if") == MarketType.INDEX_FUTURES
        assert classify("t") == MarketType.BOND_FUTURES
        assert classify("rb") == MarketType.COMMODITY_FUTURES
        assert classify("600519") == MarketType.STOCK

    def test_get_market_label(self):
        """中文标签（含 G23 新增）"""
        assert get_market_label(MarketType.INDEX_FUTURES) == "股指期货"
        assert get_market_label(MarketType.BOND_FUTURES) == "国债期货"
        assert get_market_label(MarketType.ETF) == "ETF"
        assert get_market_label(MarketType.COMMODITY_FUTURES) == "商品期货"
        assert get_market_label(MarketType.STOCK) == "A股个股"
        assert get_market_label(MarketType.REIT) == "REITs"
        assert get_market_label(MarketType.CONVERTIBLE_BOND) == "可转债"
