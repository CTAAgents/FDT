# -*- coding: utf-8 -*-
"""配置管理模块（产业链分析版）：产业链特有指标、辩论权重、类型映射。"""

# ============================================================
# 产业链特有指标
# ============================================================
CONFIG_MANAGER = {
    'chain_specific_indicators': {
        '贵金属':   {'required': ['实际利率', '美元指数DXY', '央行购金', 'ETF持仓'], 'type': 'macro_driven'},
        '油脂油料': {'required': ['天气因子', 'USDA报告', '压榨利润', '库存'], 'type': 'supply_driven'},
        '谷物软商品': {'required': ['天气因子', '产量预估', '政策因子', '库存'], 'type': 'supply_driven'},
        '黑色系':   {'required': ['钢厂利润', '房地产数据', '基建投资', '仓单'], 'type': 'demand_driven'},
        '能源链':   {'required': ['裂解价差', '原油库存', 'OPEC+政策', '炼油厂开工率'], 'type': 'supply_demand'},
    },

    # 产业链辩论权重
    'chain_debate_weights': {
        '黑色系':   {'technical_weight': 1.2, 'fundamental_weight': 1.3, 'chain_logic_weight': 1.1, 'macro_weight': 0.8},
        '能源链':   {'technical_weight': 1.0, 'fundamental_weight': 1.4, 'chain_logic_weight': 1.3, 'macro_weight': 1.2},
        '聚酯链':   {'technical_weight': 1.0, 'fundamental_weight': 1.2, 'chain_logic_weight': 1.2, 'macro_weight': 0.9},
        '油化工':   {'technical_weight': 1.0, 'fundamental_weight': 1.1, 'chain_logic_weight': 1.2, 'macro_weight': 1.1},
        '煤化工':   {'technical_weight': 1.0, 'fundamental_weight': 1.0, 'chain_logic_weight': 1.3, 'macro_weight': 0.7},
        '有色':     {'technical_weight': 1.1, 'fundamental_weight': 1.2, 'chain_logic_weight': 1.0, 'macro_weight': 1.3},
        '新能源':   {'technical_weight': 1.0, 'fundamental_weight': 1.3, 'chain_logic_weight': 1.2, 'macro_weight': 1.1},
        '贵金属':   {'technical_weight': 0.7, 'fundamental_weight': 0.8, 'chain_logic_weight': 0.5, 'macro_weight': 1.8},
        '油脂油料': {'technical_weight': 0.8, 'fundamental_weight': 1.4, 'chain_logic_weight': 1.2, 'macro_weight': 0.6},
        '谷物软商品': {'technical_weight': 0.7, 'fundamental_weight': 1.5, 'chain_logic_weight': 0.8, 'macro_weight': 0.5},
        '建材':     {'technical_weight': 1.1, 'fundamental_weight': 0.9, 'chain_logic_weight': 1.2, 'macro_weight': 1.0},
        '橡胶':     {'technical_weight': 1.0, 'fundamental_weight': 1.1, 'chain_logic_weight': 0.8, 'macro_weight': 0.7},
        '纸浆造纸': {'technical_weight': 1.0, 'fundamental_weight': 1.0, 'chain_logic_weight': 1.1, 'macro_weight': 0.6},
    },
}

# 产业链类型映射
CHAIN_TYPE_MAPPING = {
    '黑色系': 'industrial', '能源链': 'industrial', '聚酯链': 'industrial',
    '油化工': 'industrial', '煤化工': 'industrial',
    '有色金属': 'nonferrous', '有色': 'nonferrous', '新能源': 'new_energy',
    '贵金属': 'precious',
    '油脂油料': 'agricultural', '谷物软商品': 'agricultural',
    '建材': 'industrial', '橡胶': 'industrial', '纸浆造纸': 'industrial',
}

# 产业链阈值映射
CHAIN_THRESHOLD_MAPPING = {
    '黑色系': 'black', '能源链': 'energy', '聚酯链': 'energy',
    '油化工': 'energy', '煤化工': 'energy',
    '有色金属': 'nonferrous', '有色': 'nonferrous', '新能源': 'nonferrous',
    '贵金属': 'precious',
    '油脂油料': 'agricultural', '谷物软商品': 'agricultural',
    '建材': 'nonferrous', '橡胶': 'nonferrous', '纸浆造纸': 'nonferrous',
}


def get_chain_debate_weight(chain_name: str) -> dict:
    """获取产业链辩论权重。"""
    return CONFIG_MANAGER['chain_debate_weights'].get(
        chain_name,
        {'technical_weight': 1.0, 'fundamental_weight': 1.0, 'chain_logic_weight': 1.0, 'macro_weight': 1.0}
    )
