# -*- coding: utf-8 -*-
"""chains.py 单元测试 - 100%覆盖 + 跨链品种/全品种覆盖/边界条件。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.chains import (
    CHAIN_CORRELATION_MATRIX,
    CHAIN_PRODUCTS,
    CROSS_CHAIN_VARIETIES,
    DEBATE_UNITS,
    WITHIN_CHAIN_HIGH_CORRELATION,
    WITHIN_CHAIN_INDEPENDENT,
    classify_chain,
    cluster_chains,
    get_all_chains_for_symbol,
    get_all_products,
    get_chain_for_symbol,
    get_cross_chain_info,
    get_dominant_chain,
    get_secondary_chain,
    is_cross_chain_variety,
    select_leader,
)


class TestChainProducts(unittest.TestCase):
    def test_13_chains(self):
        self.assertEqual(len(CHAIN_PRODUCTS), 13)

    def test_black_chain_members(self):
        self.assertIn("rb", CHAIN_PRODUCTS["黑色系"])
        self.assertIn("i", CHAIN_PRODUCTS["黑色系"])

    def test_paper_chain_has_op(self):
        self.assertIn("op", CHAIN_PRODUCTS["纸浆造纸"])

    def test_energy_lowercase(self):
        for p in CHAIN_PRODUCTS["能源链"]:
            self.assertTrue(p.islower() or p in ["sc", "lu", "fu", "bu", "pg"])


class TestDebateUnits(unittest.TestCase):
    def test_all_chains_have_units(self):
        for chain in CHAIN_PRODUCTS:
            self.assertIn(chain, DEBATE_UNITS)

    def test_unit_has_focus(self):
        for chain, du in DEBATE_UNITS.items():
            self.assertIn("focus", du)
            self.assertGreater(len(du["focus"]), 0)


class TestClassifyChain(unittest.TestCase):
    def test_strong_bull(self):
        self.assertEqual(classify_chain(25), "多头趋势")

    def test_weak_bull(self):
        self.assertEqual(classify_chain(10), "偏多震荡")

    def test_strong_bear(self):
        self.assertEqual(classify_chain(-25), "空头趋势")

    def test_weak_bear(self):
        self.assertEqual(classify_chain(-10), "偏空震荡")

    def test_neutral(self):
        self.assertEqual(classify_chain(0), "震荡")

    def test_boundary_bull(self):
        self.assertEqual(classify_chain(20), "多头趋势")

    def test_boundary_bear(self):
        self.assertEqual(classify_chain(-20), "空头趋势")

    def test_boundary_weak_bull(self):
        self.assertEqual(classify_chain(5), "偏多震荡")

    def test_boundary_weak_bear(self):
        self.assertEqual(classify_chain(-5), "偏空震荡")


class TestSelectLeader(unittest.TestCase):
    def test_bull_leader(self):
        symbols = [
            {"product_id": "a", "tech": {"score": 30}, "last_price": 100},
            {"product_id": "b", "tech": {"score": 50}, "last_price": 200},
        ]
        leader, reason = select_leader(symbols, "多头趋势")
        # 无direction字段时选score最低(最抗跌)
        self.assertEqual(leader["product_id"], "a")
        self.assertIn("抗跌", reason)

    def test_bear_leader(self):
        symbols = [
            {"product_id": "a", "tech": {"score": -30}, "last_price": 100},
            {"product_id": "b", "tech": {"score": -50}, "last_price": 200},
        ]
        leader, reason = select_leader(symbols, "空头趋势")
        # 无direction字段时选score最高(最抗涨)
        self.assertEqual(leader["product_id"], "a")
        self.assertIn("抗涨", reason)

    def test_neutral_leader_uses_atr(self):
        symbols = [
            {"product_id": "a", "tech": {"score": 0, "ATR14": 10}, "last_price": 100},
            {"product_id": "b", "tech": {"score": 0, "ATR14": 50}, "last_price": 200},
        ]
        leader, reason = select_leader(symbols, "震荡")
        self.assertEqual(leader["product_id"], "b")
        self.assertIn("波动率", reason)


class TestClusterChains(unittest.TestCase):
    def _make_sym(self, pid, price, score, oi=50000, exchange="DCE"):
        return {
            "product_id": pid,
            "exchange_id": exchange,
            "last_price": price,
            "open_interest": oi,
            "tech": {"score": score, "trend": "neutral", "ATR14": 10},
        }

    def test_basic_clustering(self):
        symbols = [
            self._make_sym("rb", 3500, -20, exchange="SHFE"),
            self._make_sym("i", 800, -10, exchange="DCE"),
        ]
        result = cluster_chains(symbols)
        self.assertIn("黑色系", result)
        self.assertEqual(result["黑色系"]["count"], 2)

    def test_empty_symbols(self):
        result = cluster_chains([])
        self.assertEqual(len(result), 0)

    def test_leader_selected(self):
        symbols = [
            self._make_sym("rb", 3500, -30, exchange="SHFE"),
            self._make_sym("i", 800, -10, exchange="DCE"),
        ]
        result = cluster_chains(symbols)
        # 空头趋势下选score最高(最抗涨)
        self.assertEqual(result["黑色系"]["leader"], "i")

    def test_members_populated(self):
        symbols = [self._make_sym("au", 950, -20, exchange="SHFE")]
        result = cluster_chains(symbols)
        self.assertEqual(len(result["贵金属"]["members"]), 1)

    def test_unmatched_symbols_ignored(self):
        symbols = [self._make_sym("ZZZZ", 100, 0)]
        result = cluster_chains(symbols)
        self.assertNotIn("ZZZZ", str(result))


class TestCorrelationMatrix(unittest.TestCase):
    def test_black_correlated_with_energy(self):
        self.assertIn("能源链", CHAIN_CORRELATION_MATRIX["黑色系"])
        self.assertGreater(CHAIN_CORRELATION_MATRIX["黑色系"]["能源链"], 0)

    def test_all_values_between_0_and_1(self):
        for chain, corrs in CHAIN_CORRELATION_MATRIX.items():
            for other, val in corrs.items():
                self.assertGreaterEqual(val, 0)
                self.assertLessEqual(val, 1)


# ========================================================================
# 跨链品种测试（v2.14 新增）
# ========================================================================
class TestCrossChainVarieties(unittest.TestCase):
    """跨链品种的 is_cross_chain_variety / get_cross_chain_info / get_dominant_chain 测试"""

    def test_ma_is_cross_chain(self):
        self.assertTrue(is_cross_chain_variety("MA"))
        self.assertTrue(is_cross_chain_variety("ma"))  # 大小写不敏感

    def test_rb_is_not_cross_chain(self):
        self.assertFalse(is_cross_chain_variety("rb"))

    def test_cross_chain_count(self):
        self.assertEqual(len(CROSS_CHAIN_VARIETIES), 7)

    def test_all_cross_chain_known(self):
        """确保每个跨链品种都有 primary/secondary/judgment"""
        expected = {"MA", "SA", "UR", "EG", "LC", "SI", "AL"}
        self.assertEqual(set(CROSS_CHAIN_VARIETIES.keys()), expected)

    def test_get_cross_chain_info(self):
        info = get_cross_chain_info("SA")
        self.assertEqual(info["primary"], "建材")
        self.assertIn("新能源", info["secondary"])

    def test_get_secondary_chain_ma(self):
        sec = get_secondary_chain("MA")
        self.assertIn("能源链", sec)
        self.assertIn("油化工", sec)

    def test_get_all_chains_single(self):
        """非跨链品种应只返回一个链"""
        chains = get_all_chains_for_symbol("RB")
        self.assertEqual(len(chains), 1)
        self.assertIn("黑色系", chains)

    def test_get_all_chains_cross(self):
        """跨链品种应返回主链+副链"""
        chains = get_all_chains_for_symbol("SA")
        self.assertIn("建材", chains)
        self.assertIn("新能源", chains)

    def test_get_all_chains_upper_lower(self):
        chains_upper = get_all_chains_for_symbol("MA")
        chains_lower = get_all_chains_for_symbol("ma")
        self.assertEqual(chains_upper, chains_lower)

    def test_dominant_chain_default(self):
        chain, reason = get_dominant_chain("AL")
        self.assertEqual(chain, "有色")
        self.assertTrue(len(reason) > 0)

    def test_dominant_chain_cost_push(self):
        chain, reason = get_dominant_chain("AL", "cost_push")
        self.assertEqual(chain, "能源链")

    def test_dominant_chain_ma_cost_push(self):
        chain, reason = get_dominant_chain("MA", "cost_push")
        self.assertEqual(chain, "煤化工")

    def test_dominant_chain_ma_demand_pull(self):
        chain, reason = get_dominant_chain("MA", "demand_pull")
        self.assertEqual(chain, "油化工")

    def test_dominant_chain_sa_policy_shift(self):
        chain, reason = get_dominant_chain("SA", "policy_shift")
        self.assertEqual(chain, "新能源")

    def test_dominant_chain_ur_demand_pull(self):
        chain, reason = get_dominant_chain("UR", "demand_pull")
        self.assertEqual(chain, "谷物软商品")

    def test_dominant_chain_non_cross(self):
        chain, reason = get_dominant_chain("RB")
        self.assertEqual(chain, "黑色系")

    def test_dominant_chain_invalid_market_state(self):
        """不存在的 market_state 应返回默认行为"""
        chain, reason = get_dominant_chain("MA", "invalid_state")
        self.assertEqual(chain, "煤化工")  # 默认主链


# ========================================================================
# 全品种覆盖验证（v2.14 新增）
# ========================================================================
class TestFullCoverage(unittest.TestCase):
    """验证 CHAIN_PRODUCTS 完全覆盖 ALL_VARIETIES 的 66 个品种"""

    # futures-data-search 的 canonical variety list
    ALL_VARIETIES = [
        "rb",
        "hc",
        "i",
        "j",
        "jm",
        "SF",
        "SM",
        "sc",
        "lu",
        "fu",
        "bu",
        "pg",
        "PX",
        "TA",
        "PF",
        "PR",
        "eg",
        "eb",
        "v",
        "pp",
        "l",
        "MA",
        "SH",
        "cu",
        "al",
        "zn",
        "pb",
        "ni",
        "sn",
        "ao",
        "SS",
        "au",
        "ag",
        "a",
        "b",
        "m",
        "y",
        "p",
        "OI",
        "RM",
        "PK",
        "c",
        "cs",
        "SR",
        "CF",
        "jd",
        "lh",
        "AP",
        "CJ",
        "FG",
        "SA",
        "UR",
        "ru",
        "nr",
        "br",
        "sp",
        "op",
        "lc",
        "si",
        "ps",
        "ec",
        "rr",
        "ad",
        "CY",
        "PL",
        "bz",
    ]

    def test_all_varieties_mapped(self):
        """每个 ALL_VARIETIES 品种都能找到所属链"""
        unmapped = []
        for v in self.ALL_VARIETIES:
            chain = get_chain_for_symbol(v)
            if chain is None:
                unmapped.append(v)
        self.assertEqual(unmapped, [], f"未映射品种: {unmapped}")

    def test_no_duplicate_chains(self):
        """每个品种应只映射到一条主链（跨链品种的副链由 CROSS_CHAIN_VARIETIES 管理）"""
        seen = {}
        for chain, products in CHAIN_PRODUCTS.items():
            for p in products:
                p_upper = p.upper()
                if p_upper in seen:
                    self.fail(f"{p} 同时出现在 {seen[p_upper]} 和 {chain}")
                seen[p_upper] = chain

    def test_cross_chain_varieties_in_chain_products(self):
        """所有跨链品种的 primary chain 必须在 CHAIN_PRODUCTS 中有对应"""
        for var, info in CROSS_CHAIN_VARIETIES.items():
            found = False
            for chain, prods in CHAIN_PRODUCTS.items():
                if var.upper() in [p.upper() for p in prods]:
                    found = True
                    break
            self.assertTrue(found, f"{var} 不在 CHAIN_PRODUCTS 中")

    def test_get_all_products_count(self):
        products = get_all_products()
        self.assertGreaterEqual(len(products), 66)

    def test_unknown_variety_returns_none(self):
        chain = get_chain_for_symbol("UNKNOWN_VARIETY_XYZ")
        self.assertIsNone(chain)

    def test_empty_string_returns_none(self):
        chain = get_chain_for_symbol("")
        self.assertIsNone(chain)


# ========================================================================
# 聚类输出增强测试（v2.14 新增：cross_chain_info 字段）
# ========================================================================
class TestClusterChainsExtended(unittest.TestCase):
    """验证 cluster_chains 的 cross_chain_info 输出"""

    def _make_sym(self, pid, price, score, direction="HOLD", oi=50000, exchange="DCE"):
        return {
            "product_id": pid,
            "exchange_id": exchange,
            "last_price": price,
            "open_interest": oi,
            "direction": direction,
            "tech": {"score": score, "trend": "neutral", "ATR14": 10},
        }

    def test_cross_chain_info_in_output(self):
        """跨链品种应产出 cross_chain_info"""
        symbols = [self._make_sym("SA", 1800, 30, "BUY", exchange="CZCE")]
        result = cluster_chains(symbols)
        self.assertIn("建材", result)
        info = result["建材"]["cross_chain_info"]
        self.assertIsNotNone(info)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["pid"], "SA")
        self.assertIn("dominant_chain", info[0])

    def test_non_cross_chain_no_info(self):
        """非跨链品种的 cross_chain_info 应为 None"""
        symbols = [self._make_sym("RB", 3500, -20, "SELL", exchange="SHFE")]
        result = cluster_chains(symbols)
        self.assertIn("黑色系", result)
        self.assertIsNone(result["黑色系"]["cross_chain_info"])

    def test_cross_chain_with_market_state(self):
        """传入 market_state 应影响跨链品种的主导链判断"""
        symbols = [self._make_sym("MA", 2600, 20, "BUY", exchange="CZCE")]
        result = cluster_chains(symbols, market_state="cost_push")
        info = result["煤化工"]["cross_chain_info"]
        self.assertEqual(info[0]["dominant_chain"], "煤化工")

    def test_direction_based_clustering(self):
        """direction 字段应影响 classify_chain 的产业链趋势判断"""
        # 超过70%的品种是SELL（3/4 = 75% > 70%）
        symbols = [
            self._make_sym("rb", 3500, -20, "SELL", exchange="SHFE"),
            self._make_sym("hc", 3800, -30, "SELL", exchange="SHFE"),
            self._make_sym("i", 800, -10, "SELL", exchange="DCE"),
            self._make_sym("jm", 1200, 5, "BUY", exchange="DCE"),
        ]
        result = cluster_chains(symbols)
        self.assertIn("黑色系", result)
        self.assertIn("偏空", result["黑色系"]["overall_trend"])

    def test_mixed_direction_clustering(self):
        """方向不统一时应判断为震荡"""
        symbols = [
            self._make_sym("rb", 3500, 15, "BUY", exchange="SHFE"),
            self._make_sym("hc", 3800, 20, "SELL", exchange="SHFE"),
            self._make_sym("i", 800, -10, "SELL", exchange="DCE"),
        ]
        result = cluster_chains(symbols)
        self.assertIn("黑色系", result)
        self.assertIn("震荡", result["黑色系"]["overall_trend"])


# ========================================================================
# 冗余检测数据结构测试（v2.14 新增）
# ========================================================================
class TestRedundancyStructure(unittest.TestCase):
    """WITHIN_CHAIN_HIGH_CORRELATION 和 WITHIN_CHAIN_INDEPENDENT 的结构验证"""

    def test_high_corr_format(self):
        """WITHIN_CHAIN_HIGH_CORRELATION 格式验证"""
        for chain, pairs in WITHIN_CHAIN_HIGH_CORRELATION.items():
            for pair in pairs:
                self.assertEqual(len(pair), 2)
                # 确保品种确实属于该链
                for var in pair:
                    chain_for_var = get_chain_for_symbol(var)
                    self.assertIn(chain, get_all_chains_for_symbol(var))

    def test_independent_format(self):
        """WITHIN_CHAIN_INDEPENDENT 格式验证"""
        for chain, vars_list in WITHIN_CHAIN_INDEPENDENT.items():
            for var in vars_list:
                self.assertIn(chain, get_all_chains_for_symbol(var))

    def test_rb_hc_high_corr(self):
        self.assertIn(("rb", "hc"), WITHIN_CHAIN_HIGH_CORRELATION["黑色系"])

    def test_sm_sf_independent(self):
        for var in ("SM", "SF"):
            self.assertIn(var, WITHIN_CHAIN_INDEPENDENT["黑色系"])


if __name__ == "__main__":
    unittest.main()
