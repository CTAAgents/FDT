# -*- coding: utf-8 -*-
"""三方风险评估与风险主管裁决。"""


def aggressive_risk_assessment(trade_plan: dict, chain_data: dict = None) -> dict:
    """激进风险分析师：强调上行空间。"""
    assessment = {'type': 'aggressive', 'score': 0, 'arguments': []}
    if trade_plan['decision'] == 'BUY':
        assessment['score'] = 8
        assessment['arguments'].extend(['上行空间充足', '趋势向好', '再不上车可能错过行情'])
    elif trade_plan['decision'] == 'SELL':
        assessment['score'] = 7
        assessment['arguments'].extend(['下跌空间充足', '空头趋势明显', '再不进场可能错过下跌'])
    else:
        assessment['score'] = 3
        assessment['arguments'].extend(['观望可能错失机会', '但至少不会亏损'])
    return assessment


def conservative_risk_assessment(trade_plan: dict, chain_data: dict = None) -> dict:
    """保守风险分析师：揭示下行风险。"""
    assessment = {'type': 'conservative', 'score': 0, 'arguments': []}
    if trade_plan['decision'] in ('BUY', 'SELL'):
        assessment['score'] = 4
        assessment['arguments'].extend(['下行风险5%', '技术指标滞后', '宏观不确定性'])
    else:
        assessment['score'] = 7
        assessment['arguments'].extend(['观望最安全', '避免不必要风险'])
    return assessment


def neutral_risk_assessment(trade_plan: dict, chain_data: dict = None) -> dict:
    """中性风险分析师：平衡视角。"""
    assessment = {'type': 'neutral', 'score': 0, 'arguments': []}
    if trade_plan['decision'] in ('BUY', 'SELL'):
        assessment['score'] = 6
        assessment['arguments'].extend(['风险可控', '止损明确', '建议分批建仓'])
    else:
        assessment['score'] = 6
        assessment['arguments'].extend(['观望合理', '可先小仓位试探'])
    return assessment


def risk_manager_decision(aggressive: dict, conservative: dict, neutral: dict, trade_plan: dict) -> dict:
    """风险主管：裁决三方风险辩论。"""
    avg_score = (aggressive['score'] + conservative['score'] + neutral['score']) / 3.0

    if avg_score >= 6:
        final = trade_plan['decision']
        adj = '维持原仓位'
        reasoning = f'风险评估良好({avg_score:.1f})，建议执行原计划'
    elif avg_score >= 4:
        final = trade_plan['decision']
        adj = '减半仓位'
        reasoning = f'风险评估中等({avg_score:.1f})，建议减半仓位'
    else:
        final = 'HOLD'
        adj = '取消交易'
        reasoning = f'风险评估较差({avg_score:.1f})，建议取消交易'

    return {
        'final_decision': final,
        'risk_score': round(avg_score, 1),
        'position_adjustment': adj,
        'reasoning': reasoning,
    }
