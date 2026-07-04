# -*- coding: utf-8 -*-
"""risk.py 单元测试 - 100%覆盖。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.risk import (
    aggressive_risk_assessment, conservative_risk_assessment,
    neutral_risk_assessment, risk_manager_decision,
)


class TestAggressiveRisk(unittest.TestCase):

    def test_buy(self):
        r = aggressive_risk_assessment({'decision': 'BUY'})
        self.assertEqual(r['type'], 'aggressive')
        self.assertEqual(r['score'], 8)

    def test_sell(self):
        r = aggressive_risk_assessment({'decision': 'SELL'})
        self.assertEqual(r['score'], 7)

    def test_hold(self):
        r = aggressive_risk_assessment({'decision': 'HOLD'})
        self.assertEqual(r['score'], 3)


class TestConservativeRisk(unittest.TestCase):

    def test_buy(self):
        r = conservative_risk_assessment({'decision': 'BUY'})
        self.assertEqual(r['type'], 'conservative')
        self.assertEqual(r['score'], 4)

    def test_sell(self):
        r = conservative_risk_assessment({'decision': 'SELL'})
        self.assertEqual(r['score'], 4)

    def test_hold(self):
        r = conservative_risk_assessment({'decision': 'HOLD'})
        self.assertEqual(r['score'], 7)


class TestNeutralRisk(unittest.TestCase):

    def test_buy(self):
        r = neutral_risk_assessment({'decision': 'BUY'})
        self.assertEqual(r['type'], 'neutral')
        self.assertEqual(r['score'], 6)

    def test_sell(self):
        r = neutral_risk_assessment({'decision': 'SELL'})
        self.assertEqual(r['score'], 6)

    def test_hold(self):
        r = neutral_risk_assessment({'decision': 'HOLD'})
        self.assertEqual(r['score'], 6)


class TestRiskManagerDecision(unittest.TestCase):

    def test_high_score_maintain(self):
        agg = {'score': 8}
        con = {'score': 7}
        neu = {'score': 6}
        tp = {'decision': 'BUY'}
        result = risk_manager_decision(agg, con, neu, tp)
        self.assertEqual(result['final_decision'], 'BUY')
        self.assertEqual(result['position_adjustment'], '维持原仓位')

    def test_medium_score_reduce(self):
        agg = {'score': 5}
        con = {'score': 4}
        neu = {'score': 4}
        tp = {'decision': 'SELL'}
        result = risk_manager_decision(agg, con, neu, tp)
        self.assertEqual(result['final_decision'], 'SELL')
        self.assertEqual(result['position_adjustment'], '减半仓位')

    def test_low_score_cancel(self):
        agg = {'score': 2}
        con = {'score': 2}
        neu = {'score': 2}
        tp = {'decision': 'BUY'}
        result = risk_manager_decision(agg, con, neu, tp)
        self.assertEqual(result['final_decision'], 'HOLD')
        self.assertEqual(result['position_adjustment'], '取消交易')

    def test_score_format(self):
        agg = {'score': 8}
        con = {'score': 4}
        neu = {'score': 6}
        tp = {'decision': 'BUY'}
        result = risk_manager_decision(agg, con, neu, tp)
        self.assertIsInstance(result['risk_score'], float)

    def test_reasoning_contains_score(self):
        agg = {'score': 8}
        con = {'score': 4}
        neu = {'score': 6}
        tp = {'decision': 'BUY'}
        result = risk_manager_decision(agg, con, neu, tp)
        self.assertIn(str(result['risk_score']), result['reasoning'])


if __name__ == '__main__':
    unittest.main()
