# -*- coding: utf-8 -*-
"""chains.py 单元测试 - 100%覆盖。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.chains import (
    CHAIN_PRODUCTS, DEBATE_UNITS, CHAIN_CORRELATION_MATRIX,
    classify_chain, select_leader, cluster_chains,
)


class TestChainProducts(unittest.TestCase):

    def test_13_chains(self):
        self.assertEqual(len(CHAIN_PRODUCTS), 13)

    def test_black_chain_members(self):
        self.assertIn('rb', CHAIN_PRODUCTS['黑色系'])
        self.assertIn('i', CHAIN_PRODUCTS['黑色系'])

    def test_paper_chain_has_op(self):
        self.assertIn('op', CHAIN_PRODUCTS['纸浆造纸'])

    def test_energy_lowercase(self):
        for p in CHAIN_PRODUCTS['能源链']:
            self.assertTrue(p.islower() or p in ['sc', 'lu', 'fu', 'bu', 'pg'])


class TestDebateUnits(unittest.TestCase):

    def test_all_chains_have_units(self):
        for chain in CHAIN_PRODUCTS:
            self.assertIn(chain, DEBATE_UNITS)

    def test_unit_has_focus(self):
        for chain, du in DEBATE_UNITS.items():
            self.assertIn('focus', du)
            self.assertGreater(len(du['focus']), 0)


class TestClassifyChain(unittest.TestCase):

    def test_strong_bull(self):
        self.assertEqual(classify_chain(25), '多头趋势')

    def test_weak_bull(self):
        self.assertEqual(classify_chain(10), '偏多震荡')

    def test_strong_bear(self):
        self.assertEqual(classify_chain(-25), '空头趋势')

    def test_weak_bear(self):
        self.assertEqual(classify_chain(-10), '偏空震荡')

    def test_neutral(self):
        self.assertEqual(classify_chain(0), '震荡')

    def test_boundary_bull(self):
        self.assertEqual(classify_chain(20), '多头趋势')

    def test_boundary_bear(self):
        self.assertEqual(classify_chain(-20), '空头趋势')

    def test_boundary_weak_bull(self):
        self.assertEqual(classify_chain(5), '偏多震荡')

    def test_boundary_weak_bear(self):
        self.assertEqual(classify_chain(-5), '偏空震荡')


class TestSelectLeader(unittest.TestCase):

    def test_bull_leader(self):
        symbols = [
            {'product_id': 'a', 'tech': {'score': 30}, 'last_price': 100},
            {'product_id': 'b', 'tech': {'score': 50}, 'last_price': 200},
        ]
        leader, reason = select_leader(symbols, '多头趋势')
        # 无direction字段时选score最低(最抗跌)
        self.assertEqual(leader['product_id'], 'a')
        self.assertIn('抗跌', reason)

    def test_bear_leader(self):
        symbols = [
            {'product_id': 'a', 'tech': {'score': -30}, 'last_price': 100},
            {'product_id': 'b', 'tech': {'score': -50}, 'last_price': 200},
        ]
        leader, reason = select_leader(symbols, '空头趋势')
        # 无direction字段时选score最高(最抗涨)
        self.assertEqual(leader['product_id'], 'a')
        self.assertIn('抗涨', reason)

    def test_neutral_leader_uses_atr(self):
        symbols = [
            {'product_id': 'a', 'tech': {'score': 0, 'ATR14': 10}, 'last_price': 100},
            {'product_id': 'b', 'tech': {'score': 0, 'ATR14': 50}, 'last_price': 200},
        ]
        leader, reason = select_leader(symbols, '震荡')
        self.assertEqual(leader['product_id'], 'b')
        self.assertIn('波动率', reason)


class TestClusterChains(unittest.TestCase):

    def _make_sym(self, pid, price, score, oi=50000, exchange='DCE'):
        return {
            'product_id': pid,
            'exchange_id': exchange,
            'last_price': price,
            'open_interest': oi,
            'tech': {'score': score, 'trend': 'neutral', 'ATR14': 10},
        }

    def test_basic_clustering(self):
        symbols = [
            self._make_sym('rb', 3500, -20, exchange='SHFE'),
            self._make_sym('i', 800, -10, exchange='DCE'),
        ]
        result = cluster_chains(symbols)
        self.assertIn('黑色系', result)
        self.assertEqual(result['黑色系']['count'], 2)

    def test_empty_symbols(self):
        result = cluster_chains([])
        self.assertEqual(len(result), 0)

    def test_leader_selected(self):
        symbols = [
            self._make_sym('rb', 3500, -30, exchange='SHFE'),
            self._make_sym('i', 800, -10, exchange='DCE'),
        ]
        result = cluster_chains(symbols)
        # 空头趋势下选score最高(最抗涨)
        self.assertEqual(result['黑色系']['leader'], 'i')

    def test_members_populated(self):
        symbols = [self._make_sym('au', 950, -20, exchange='SHFE')]
        result = cluster_chains(symbols)
        self.assertEqual(len(result['贵金属']['members']), 1)

    def test_unmatched_symbols_ignored(self):
        symbols = [self._make_sym('ZZZZ', 100, 0)]
        result = cluster_chains(symbols)
        self.assertNotIn('ZZZZ', str(result))


class TestCorrelationMatrix(unittest.TestCase):

    def test_black_correlated_with_energy(self):
        self.assertIn('能源链', CHAIN_CORRELATION_MATRIX['黑色系'])
        self.assertGreater(CHAIN_CORRELATION_MATRIX['黑色系']['能源链'], 0)

    def test_all_values_between_0_and_1(self):
        for chain, corrs in CHAIN_CORRELATION_MATRIX.items():
            for other, val in corrs.items():
                self.assertGreaterEqual(val, 0)
                self.assertLessEqual(val, 1)


if __name__ == '__main__':
    unittest.main()
