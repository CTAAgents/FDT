# -*- coding: utf-8 -*-
"""配置管理模块（趋势信号发现版）：系统参数、自适应权重、品种阈值、指标配置、打分系统。"""

# ============================================================
# 系统配置
# ============================================================
CONFIG_MANAGER = {
    "system": {
        "version": "2.13",
        "debug": False,
        "log_level": "INFO",
        "max_symbols": 50,
        "min_open_interest": 10000,
        "enable_cache": True,
        "cache_ttl": 300,
        "parallel_processing": True,
        "max_workers": 4,
    },
    # 自适应权重系统
    "adaptive_weights": {
        "market_state_factors": {
            "trending": {
                "MA": 1.2,
                "MACD": 1.1,
                "RSI": 0.8,
                "DMI": 1.3,
                "VOLUME": 0.9,
                "PRICE_POSITION": 1.0,
                "CHANNEL_BREAKOUT": 1.3,
                "CHANNEL_POSITION": 1.1,
            },
            "ranging": {
                "MA": 0.8,
                "MACD": 0.9,
                "RSI": 1.3,
                "DMI": 0.7,
                "VOLUME": 1.2,
                "PRICE_POSITION": 1.1,
                "CHANNEL_BREAKOUT": 0.6,
                "CHANNEL_POSITION": 0.8,
            },
            "volatile": {
                "MA": 0.9,
                "MACD": 1.0,
                "RSI": 1.1,
                "DMI": 1.0,
                "VOLUME": 1.3,
                "PRICE_POSITION": 0.8,
                "CHANNEL_BREAKOUT": 1.1,
                "CHANNEL_POSITION": 0.9,
            },
        },
        "product_type_factors": {
            "industrial": {
                "MA": 1.0,
                "MACD": 1.1,
                "RSI": 0.9,
                "DMI": 1.2,
                "VOLUME": 1.0,
                "PRICE_POSITION": 1.0,
                "CHANNEL_BREAKOUT": 1.1,
                "CHANNEL_POSITION": 1.0,
            },
            "agricultural": {
                "MA": 0.9,
                "MACD": 0.8,
                "RSI": 1.2,
                "DMI": 0.9,
                "VOLUME": 1.3,
                "PRICE_POSITION": 1.1,
                "CHANNEL_BREAKOUT": 1.0,
                "CHANNEL_POSITION": 1.2,
            },
            "financial": {
                "MA": 1.1,
                "MACD": 1.0,
                "RSI": 1.0,
                "DMI": 1.1,
                "VOLUME": 0.9,
                "PRICE_POSITION": 1.0,
                "CHANNEL_BREAKOUT": 1.2,
                "CHANNEL_POSITION": 1.0,
            },
        },
        "default_weights": {
            "MA": 30,
            "MACD": 20,
            "RSI": 10,
            "DMI": 20,
            "VOLUME": 10,
            "PRICE_POSITION": 15,
            "CHANNEL_BREAKOUT": 15,
            "CHANNEL_POSITION": 10,
        },
    },
    # 品种特异性阈值
    "product_thresholds": {
        "black": {"warrant_low": 800, "warrant_high": 4000, "volatility_threshold": 2.5},
        "energy": {"warrant_low": 1000, "warrant_high": 5000, "volatility_threshold": 3.0},
        "nonferrous": {"warrant_low": 1200, "warrant_high": 6000, "volatility_threshold": 2.8},
        "precious": {"warrant_low": 500, "warrant_high": 3000, "volatility_threshold": 2.0},
        "agricultural": {"warrant_low": 1500, "warrant_high": 7000, "volatility_threshold": 3.5},
        "default": {"warrant_low": 1000, "warrant_high": 5000, "volatility_threshold": 3.0},
    },
    # 市场状态识别
    "market_state": {
        "trend_threshold": 25,
        "range_threshold": 10,
        "volatile_threshold": 2.0,
        "adx_trend": 25,
        "adx_range": 20,
    },
    # 交易参数
    "trading": {
        "entry_atr_multiplier": 0.5,
        "entry_validity_hours": 4,
        "use_market_order": True,
        "target_return": 0.10,
        "atr_multiplier": 2.0,
        "max_position": 8,
        "min_position": 2,
        "base_position": 5,
    },
    # 风险参数
    "risk": {
        "max_drawdown": 20,
        "sharpe_ratio_min": 1.0,
        "win_rate_min": 50,
    },
}

# 兼容性别名
ADAPTIVE_WEIGHT_SYSTEM = CONFIG_MANAGER["adaptive_weights"]
PRODUCT_THRESHOLDS = CONFIG_MANAGER["product_thresholds"]
MARKET_STATE_SYSTEM = CONFIG_MANAGER["market_state"]

# 产业链类型映射（用于品种分类，非产业链分析）
CHAIN_TYPE_MAPPING = {
    "黑色系": "industrial",
    "能源链": "industrial",
    "聚酯链": "industrial",
    "油化工": "industrial",
    "煤化工": "industrial",
    "有色金属": "nonferrous",
    "有色": "nonferrous",
    "贵金属": "precious",
    "油脂油料": "agricultural",
    "谷物软商品": "agricultural",
    "建材": "industrial",
    "橡胶": "industrial",
    "纸浆造纸": "industrial",
}

# 产业链阈值映射
CHAIN_THRESHOLD_MAPPING = {
    "黑色系": "black",
    "能源链": "energy",
    "聚酯链": "energy",
    "油化工": "energy",
    "煤化工": "energy",
    "有色金属": "nonferrous",
    "有色": "nonferrous",
    "贵金属": "precious",
    "油脂油料": "agricultural",
    "谷物软商品": "agricultural",
    "建材": "nonferrous",
    "橡胶": "nonferrous",
    "纸浆造纸": "nonferrous",
}

# 指标参数配置
INDICATOR_CONFIG = {
    "MA": {"periods": [5, 10, 20, 40, 60, 120], "weight": 30},
    "MACD": {"fast": 12, "slow": 26, "signal": 9, "weight": 20},
    "RSI": {"period": 14, "overbought": 70, "oversold": 30, "weight": 10},
    "DMI": {"period": 14, "smooth": 6, "weight": 20},
    "ATR": {"period": 14, "high_threshold": 3.0, "low_threshold": 1.0, "use_for_scoring": False},
    "VOLUME": {"obv_ma_period": 20, "weight": 10},
    "PRICE_POSITION": {"ma_period": 20, "weight": 15},
    "CHANNEL_BREAKOUT": {"bb_period": 20, "bb_std": 2, "dc_period": 20, "weight": 15},
    "CHANNEL_POSITION": {"bb_period": 20, "dc_period": 20, "weight": 10},
}


# ============================================================
# 100分制打分系统配置（v2.13 L1-L4四层架构）
# ============================================================
SCORING_CONFIG = {
    "thresholds": {
        "strong_signal": 75,  # ≥75分：T2主仓信号
        "watch_signal": 60,  # 60-74分：T1观察/预加载
        "weak_signal": 40,  # 40-59分：弱信号
        "noise": 0,  # <40分：噪音，忽略
        "overheat": 90,  # >90分：警惕过热
    },
    "dimensions": {
        "L1_germination": {"max": 35, "weight": 0.35, "type": "L1萌芽/资金结构"},
        "L2_volume_price": {"max": 35, "weight": 0.35, "type": "L2量价领先"},
        "L3_structure": {"max": 20, "weight": 0.20, "type": "L3价格结构"},
        "L4_confirmation": {"max": 10, "weight": 0.10, "type": "L4确认"},
        "veto": {"max": -20, "weight": 0.0, "type": "否决"},
    },
    "layer_description": {
        "L1": "最早信号（10-30根K）：OI三角、基差、期限结构、ROC零轴、%b过0.5、ATR百分位、HH/HL、OBV/CMF",
        "L2": "次早信号（3-10根K）：Vortex、CCI、Supertrend、HMA、KAMA、量价背离",
        "L3": "中等信号（2-5根K）：RSI健康区、DMI方向、前高突破",
        "L4": "确认信号（0根K，基准）：通道突破、均线排列、MACD、ADX",
    },
    "tier_system": {
        "T2_main": {"min": 75, "max": 90, "desc": "主仓信号，正常仓位"},
        "T1_watch": {"min": 60, "max": 75, "desc": "观察/预加载，轻仓试探"},
        "T3_caution": {"min": 90, "max": 100, "desc": "警惕过热，减仓或观望"},
        "T0_ignore": {"min": 0, "max": 60, "desc": "弱信号/噪音，忽略"},
    },
    "ranking": {
        "use_ranking": True,  # 启用排序赛马制
        "top_n": 10,  # 取前10名
        "min_absolute_score": 40,  # 最低绝对分
    },
    "time_decay": {
        "enabled": True,
        "decay_curve": {
            0: 1.0,  # 当天：100%
            3: 0.9,  # 3天：90%
            7: 0.7,  # 7天：70%
            14: 0.5,  # 14天：50%
            20: 0.3,  # 20天+：30%
        },
    },
    # 期货专属配置
    "futures_specific": {
        "oi_building_threshold": 1.1,  # OI建仓阈值：OI/MA20 > 1.1
        "oi_confirmation_threshold": 1.05,  # OI确认阈值
        "basis_ma_short": 5,  # 基差短期MA
        "basis_ma_long": 20,  # 基差长期MA
        "spread_slope_threshold": 0.2,  # Spread斜率阈值
        "term_structure_weight": 4,  # 期限结构分值
        "basis_weight": 4,  # 基差分值
        "oi_weight": 6,  # OI分值
        "spread_weight": 3,  # Spread分值
    },
}


# ============================================================
# 市场类型参数适配表（v2.11）
# ============================================================
MARKET_PARAMS = {
    "commodity": {
        "name": "大宗商品",
        "examples": "螺纹、原油、铜",
        "dc_period_short": 20,
        "dc_period_long": 55,
        "bb_period": 20,
        "bb_std": 2,
        "vol_filter_mult": 1.5,
        "atr_stop_mult": 1.5,
        "atr_target_mult": 2.5,
        "note": "关注持仓量变化，增仓上行最健康",
    },
    "stock_index": {
        "name": "A股/指数",
        "examples": "沪深300、行业ETF",
        "dc_period_short": 20,
        "dc_period_long": 60,
        "bb_period": 20,
        "bb_std": 2,
        "vol_filter_mult": 1.8,
        "atr_stop_mult": 1.5,
        "atr_target_mult": 2.0,
        "note": "容易缩量上涨，量能要求可适当放宽，侧重均线结构",
    },
    "crypto": {
        "name": "数字货币",
        "examples": "BTC、ETH",
        "dc_period_short": 20,
        "dc_period_long": 55,
        "bb_period": 20,
        "bb_std": 2,
        "vol_filter_mult": 1.2,
        "atr_stop_mult": 2.0,
        "atr_target_mult": 3.0,
        "note": "波动率极大，ATR止损倍数建议设为2.0，防止被洗盘",
    },
    "forex": {
        "name": "外汇",
        "examples": "EUR/USD, GBP/USD",
        "dc_period_short": 20,
        "dc_period_long": 50,
        "bb_period": 20,
        "bb_std": 2,
        "vol_filter_mult": 0,
        "atr_stop_mult": 1.5,
        "atr_target_mult": 2.0,
        "note": "关注宏观数据发布时间，假突破较多，侧重通道边界K线形态",
    },
}


def get_market_params(chain_name: str) -> dict:
    """根据产业链名称获取市场参数。默认使用commodity参数。"""
    return MARKET_PARAMS.get("commodity", MARKET_PARAMS["commodity"])


# ============================================================
# 工具函数
# ============================================================


def get_product_type(chain_name: str) -> str:
    """获取产业链品种类型。"""
    return CHAIN_TYPE_MAPPING.get(chain_name, "industrial")


def get_product_thresholds(chain_name: str) -> dict:
    """获取品种特异性阈值。"""
    threshold_type = CHAIN_THRESHOLD_MAPPING.get(chain_name, "default")
    return PRODUCT_THRESHOLDS.get(threshold_type, PRODUCT_THRESHOLDS["default"])


def get_adaptive_weights(product_type: str = "industrial", market_state: str = "trending") -> dict:
    """获取自适应权重。"""
    base_weights = ADAPTIVE_WEIGHT_SYSTEM["default_weights"].copy()

    state_factors = ADAPTIVE_WEIGHT_SYSTEM["market_state_factors"].get(market_state, {})
    for indicator, factor in state_factors.items():
        if indicator in base_weights:
            base_weights[indicator] *= factor

    type_factors = ADAPTIVE_WEIGHT_SYSTEM["product_type_factors"].get(product_type, {})
    for indicator, factor in type_factors.items():
        if indicator in base_weights:
            base_weights[indicator] *= factor

    total_weight = sum(base_weights.values())
    if total_weight > 0:
        for indicator in base_weights:
            base_weights[indicator] = (base_weights[indicator] / total_weight) * 100

    return base_weights


def calculate_position_size(confidence: str, volatility_state: str) -> str:
    """计算动态仓位。"""
    base = CONFIG_MANAGER["trading"]["base_position"]
    if confidence == "高":
        pos = base * 1.5
    elif confidence == "中":
        pos = base * 1.0
    else:
        pos = base * 0.5

    if volatility_state == "high":
        pos *= 0.7
    elif volatility_state == "low":
        pos *= 1.3

    pos = min(pos, CONFIG_MANAGER["trading"]["max_position"])
    pos = max(pos, CONFIG_MANAGER["trading"]["min_position"])
    return f"{pos:.1f}%"


def calculate_atr_stop_loss(current_price: float, atr_value: float, direction: str) -> float:
    """计算ATR动态止损。"""
    if atr_value > 0:
        mult = CONFIG_MANAGER["trading"]["atr_multiplier"]
        dist = atr_value * mult
        return current_price - dist if direction == "BUY" else current_price + dist
    return current_price * 0.95 if direction == "BUY" else current_price * 1.05


def get_atr_adaptive_thresholds(chain_name: str, atr_pct: float) -> dict:
    """ATR自适应趋势阈值。"""
    chain_atr_factor = {
        "黑色系": 1.5,
        "能源链": 1.3,
        "聚酯链": 1.0,
        "油化工": 1.0,
        "煤化工": 1.1,
        "有色": 1.0,
        "贵金属": 0.6,
        "油脂油料": 1.2,
        "谷物软商品": 1.1,
        "建材": 1.2,
        "橡胶": 1.3,
        "纸浆造纸": 0.6,
    }
    factor = chain_atr_factor.get(chain_name, 1.0)
    if atr_pct > 3.0:
        factor *= 1.3
    elif atr_pct < 1.0:
        factor *= 0.7

    base = {"strong_bullish": 30, "weak_bullish": 10, "strong_bearish": -30, "weak_bearish": -10}
    return {k: v * factor for k, v in base.items()}
