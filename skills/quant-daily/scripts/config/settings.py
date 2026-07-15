# -*- coding: utf-8 -*-
"""配置管理模块（趋势信号发现版）：系统参数、自适应权重、品种阈值、指标配置、打分系统。"""

import os
import json

# ============================================================
# 策略启用控制（G28，2026-07-15）
# ============================================================
# 持久化暂停开关：列入此集合的 v2 策略将不进入管线（代码零删除，
# 暂停=加名至此集合，恢复=移出）。CLI --strategies 显式指定时覆盖本禁用。
# 当前暂停（缺资源，待完善后开启）：
#   multi_factor  — 因子源缺口（inventory/capacity/rate/pmi 无分位/无源，G27）
#   ml_signal     — 缺 ONNX 模型（MODEL_REGISTRY 空，无模型→降级空信号）
#   event_driven  — 事件宇宙仅 34 条预排宏观/农报，无实时突发源
DISABLED_STRATEGIES: set[str] = {
    "multi_factor",
    "ml_signal",
    "event_driven",
}

# ============================================================
# 系统配置
# ============================================================
CONFIG_MANAGER = {
    "system": {
        "version": "2.15",
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
# 通道突破策略 — 信号等级阈值（v1.1 自进化可调）
# ============================================================
SIGNAL_GRADE_THRESHOLDS = {
    "strong": 50,      # STRONG: abs>=50 → 进入辩论流程
    "watch": 40,       # WATCH: abs>=40 → 观察信号
    "weak": 20,        # WEAK: abs>=20 → 弱趋势
    "noise": 0,        # NOISE: <20 → 噪音过滤
}

# ============================================================
# 辩论入口阈值 — 统一配置（单一真相源·不分散）
# ============================================================
# ⚠️ 是否进入辩论的阈值唯一真相源 = DEBATE_ENTRY_MIN_ABS。
#    所有位置（team-lead 信号闸门 / fdt-spawn-debate / L3 信号门 /
#    daily_debate / hourly_debate）一律读取本值，禁止各自写死阈值。
#    （2026-07-11 掌柜确立：是否可辩论的阈值应统一配置，不分散在各位置）
# quant-daily 仅做「负向过滤」：排除无数据/无市场的品种，全量监控其余品种；
# 评分(score) 只作为方向初始值与辩论优先级，不作为进入辩论的硬性门槛。
# 入口底线 = 存在方向性信号（|total| ≥ DEBATE_ENTRY_MIN_ABS）即进入辩论候选池；
#   哪些品种更适合交易，由下游 辩论→策略→风控→裁决 环节决定。
# 当前值=20 → 过滤 NOISE 级（|total|<20），仅 WEAK 及以上进入辩论候选池。
DEBATE_ENTRY_MIN_ABS = 20


# ============================================================
# 通道突破策略完整参数集（v1.2 品种×周期多层次可优化）
# 所有通道突破策略的评分参数集中在此。
# 四层回落: per_symbol[sym][period] → per_chain[chain][period] → per_period[period] → default
# 修改后重启扫描生效。自优化器写 per_symbol / per_chain 层即可。
# ============================================================
CHANNEL_BREAKOUT_CONFIG = {
    # L4 全局默认值 — 兜底，所有新品种/新周期自动继承
    "default": {
        "time_window": {
            "trading_min_per_day": 345,      # 1个交易日的交易分钟数
            "dc20_period": 20,               # DC20周期（bar数）
            "dc55_period": 55,               # DC55周期（bar数）
            "ma60_period": 60,               # MA60周期（bar数）
            "min_bars_required": 60,         # 品种最小K线要求
        },
        "dc20": {
            "break_base_score": 40.0,        # DC20突破基础分（±）v2.3: 30→40，提升DC20分量
            "break_strong_pct": 1.0,         # 大幅突破阈值（%）
            "break_strong_bonus": 15.0,      # 大幅突破加减分（±）v2.3: 10→15
            "break_moderate_pct": 0.3,       # 中等突破阈值（%）
            "break_moderate_bonus": 8.0,     # 中等突破加减分（±）v2.3: 5→8
            "pos_upper_threshold": 0.7,      # 上轨附近阈值（DC20_POS）
            "pos_upper_bonus": 5.0,          # 上轨位置加分
            "pos_lower_threshold": 0.3,      # 下轨附近阈值（DC20_POS）
            "pos_lower_bonus": -5.0,         # 下轨位置减分
            "near_breakout_ticks": 7,        # 接近边界：距DC20边界≤N个tick视为"逼近" v2.3: 5→7
            "near_breakout_score": 22.0,     # 逼近得分（±）v2.3: 15→22
        },
        "adx": {
            "_deprecated": "v1.3: ADX已从通道突破评分中移除, 仅保留显示。突破策略不应被趋势强度过滤。",
            "exhaustion_threshold": 60,
            "exhaustion_penalty": 0.0,       # 已禁用
            "trend_threshold": 25,
            "trend_bonus": 0.0,              # 已禁用
        },
        "dc55": {
            "pos_thresholds": [
                {"min": 0.85, "score": 25.0, "label": "extreme_upper"},
                {"min": 0.70, "score": 15.0, "label": "upper"},
                {"min": 0.50, "score": 5.0,  "label": "mid_upper"},
                {"max": 0.15, "score": -25.0,"label": "extreme_lower"},
                {"max": 0.30, "score": -15.0,"label": "lower"},
                {"max": 0.50, "score": -5.0, "label": "mid_lower"},
            ],
            "trend_base_score": 10.0,
            "trend_alignment_bonus": 5.0,
            "divergence_penalty": 10.0,
        },
        "bb": {
            "width_high_threshold": 4.0,
            "width_high_score": 6.0,
            "width_moderate_threshold": 2.5,
            "width_moderate_score": 3.0,
            "squeeze_bonus": 2.0,
            "pos_extreme_threshold": 1.05,
            "pos_extreme_score": 20.0,         # v2.3: 6→20，BB极端突破权重提升
            "pos_upper_threshold": 1.0,
            "pos_upper_score": 15.0,           # v2.3: 4→15，BB上轨突破权重提升
            "pos_mid_upper_threshold": 0.7,
            "pos_mid_upper_score": 2.0,
            "pos_mid_lower_threshold": 0.15,
            "pos_mid_lower_score": -2.0,
            "pos_lower_score": -15.0,          # v2.3: -4→-15，BB下轨突破对称提升
            "pos_extreme_lower_score": -20.0,  # v2.3: -6→-20
            "dc_consistency_bonus": 2.0,
        },
        "volume": {
            "ma_period": 20,
            "explosive_ratio": 1.5,
            "explosive_score": 10.0,
            "elevated_ratio": 1.2,
            "elevated_score": 5.0,
            "normal_lower_ratio": 0.8,
            "weak_penalty": -3.0,
        },
        "signal_type": {
            "channel_breakout_dc20_min": 30,
            "channel_breakout_dc_total_min": 20,
            "trend_confirmation_dc55_min": 15,
            "near_breakout_dc20_min": 10,
        },
    },

    # L3 周期级覆盖 — 所有品种在此周期下共享
    "per_period": {
        "60m": {
            "volume": {
                "weak_penalty": -1.0,        # 60m默认-3→-1：子周期成交量波动大，减轻惩罚
                "normal_lower_ratio": 0.5,   # 60m默认0.8→0.5：更低阈值才判定缩量
            },
        },
        "120m": {
            "volume": {
                "weak_penalty": -2.0,        # 120m介于日线(-3)和60m(-1)之间
                "normal_lower_ratio": 0.6,   # 120m介于日线(0.8)和60m(0.5)之间
            },
        },
    },

    # L2 产业链×周期覆盖 — 按产业链分组调优
    "per_chain": {},

    # L1 品种×周期覆盖 — 最精确，自优化最终写入层
    "per_symbol": {},
}


# ═══════════════════════════════════════════════════════════
# 信号范式 ↔ 验证器 声明式映射（架构原则见 technical_debt.md §5）
# 每个 signal_type 显式声明它该跑哪些验证器；"__global__" 对所有活跃信号跑一次。
# 调用约定（由注册位置决定）：
#   - 普通 key 下的验证器 → 单记录验证器 fn(r, ctx)（按记录逐条调用）
#   - "__global__" 下的验证器 → 列表级验证器 fn(all_ranked, ctx)（跑一次）
# 验证器实现见 signals/validators/（全用公开主流因子，无黑盒）。
# 加新验证器 = 在 validators/ 写模块并 register_validator + 在此登记一行。
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════
# G30 趋势跟踪指标衍生子策略 — 参数集中配置（单一真相源）
# 镜像 futures_data_core.indicators.tdx_compat 中 calculate_* 的默认值，
# 供调参/复盘时统一查阅；当前实现以 FDC 默认值为准，本字典为权威登记。
# ═══════════════════════════════════════════════
TREND_G30_CONFIG = {
    "keltner":        {"period": 20, "atr_mult": 2.25},   # EMA±ATR 通道（Linda Raschke）
    "chandelier":     {"period": 22, "mult": 3.0},        # 吊灯退出（Chuck LeBeau）
    "sar":            {"acceleration": 0.02, "maximum": 0.20},  # 抛物线转向
    "supertrend":     {"period": 10, "multiplier": 3.0},  # 趋势状态（legacy_numpy 同参）
    "macd":           {"fast": 12, "slow": 26, "signal": 9},  # MACD 系统
    # 子信号置信度（与 trend_following_strategy 评分助手一致）
    "sub_conviction": {
        "keltner": "distance_scaled(0-1)",
        "supertrend": 0.5,
        "sar": 0.4,
        "chandelier": "0.3 + distance_scaled(0-1)",
        "macd": "distance_scaled(0-1, 0.5%价格=满强度)",
    },
}


# ═══════════════════════════════════════════════════════════
# G31 时间序列动量 TSMOM — 参数集中配置（单一真相源）
# Moskowitz-Ooi-Pedersen(2012) 多窗口（1/3/6/12 月）收益合成。
# 镜像 futures_data_core.indicators.tdx_compat.calculate_tsmom 默认值；
# 本字典为权威登记，trend_following_strategy._score_tsmom 的硬编码置信尺度
# 与此处 conviction_scale_pct 一致（10% 平均收益 → 满强 1.0）。
# ═══════════════════════════════════════════════════════════
TREND_G31_CONFIG = {
    # 回看窗口（交易日）：1月≈21 / 3月≈63 / 6月≈126 / 12月≈252
    "windows": {"m1": 21, "m3": 63, "m6": 126, "m12": 252},
    # 合成强度缩放：平均收益达此比例（10%）即满强（1.0）；按 abs(avg)/scale 截断
    "conviction_scale_pct": 10.0,
    # 合成方式：平均符号定方向、平均绝对值定强度（多窗口合成即降噪）
    "synthesis": "mean_sign",
    # 子信号置信度（与 _score_tsmom 一致）：满强=1.0（abs(avg)>=10%）
    "sub_conviction": "min(1.0, abs(avg_ret)/0.10)",
}


# ═══════════════════════════════════════════════════════════
# G32 波动率目标化 Vol Targeting — 参数集中配置（单一真相源）
# 现代 CTA 趋势跟踪第二基石（与 TSMOM 并列）。目标使持仓对组合
# 波动率贡献恒定 = target_ann_vol（默认 10%/年）。
# scale = target / realized_vol，截断 [floor, cap]。
# 镜像 futures_data_core.indicators.tdx_compat.calculate_* 默认值；
# legacy_numpy 单点注入 REALIZED_VOL / VOL_SCALE 与之一致。
# ═══════════════════════════════════════════════════════════
TREND_G32_CONFIG = {
    "window": 63,            # 已实现波动率回看（交易日）≈ 3 月，与 TSMOM 3m 对齐
    "target_ann_vol": 0.10,  # 目标年化波动率 10%
    "floor": 0.2,            # 高波动最多降仓到 0.2x
    "cap": 3.0,              # 低波动最多加仓到 3.0x
    # 落点：执行/风险 overlay 层（非信号评分层）；依赖 G31 收益序列做波动估计
    "layer": "execution_risk_overlay",
}


SIGNAL_VALIDATOR_MAP = {
    # P1 通道突破 — 全装伪突破防护
    "channel_breakout":       ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing", "trend_direction"],
    "trend_confirmation":     ["p0_4_raw_kline", "trend_direction", "stability"],
    "bb_squeeze_prebreakout": ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing"],
    "near_breakout":          ["volume_confirm", "atr_vol_timing"],   # 未实质突破，轻量确认
    # P3 均值回归
    "minor_signal":           ["entity_quality", "atr_vol_timing", "stability"],
    # 全局闸门（稳定性/拥挤度，列表级）
    "__global__":             ["crowding"],
}

# ═══════════════════════════════════════════════════════════
# B1 角色化 LLM 档案（约定层 + 部分可控）
# ───────────────────────────────────────────────────────────
# 单一真相源。每个辩论角色的 model/temperature/max_tokens 建议值。
# FDT 的 run_debate.py 不自己调 LLM（只产出 spawn 计划，由平台 spawn 子 Agent），
# 故本表作为「约定层」注入 spawn prompt，供团队主管 spawn 时参考；
# 若平台支持 per-spawn 覆盖则生效，否则仅为建议、不报错（详见 docs/design/ 评估整改方案）。
LLM_PROFILE_MAP = {
    "technical":  {"model": "deepseek-v4-flash", "temperature": 0.1, "top_p": 0.9,  "max_tokens": 4000, "cache_ttl": 86400},  # 观澜·技术
    "zhengzhen":  {"model": "deepseek-v4-flash", "temperature": 0.4, "top_p": 0.95, "max_tokens": 3000, "cache_ttl": 86400},  # 证真
    "zhensi":     {"model": "deepseek-v4-flash", "temperature": 0.4, "top_p": 0.95, "max_tokens": 3000, "cache_ttl": 86400},  # 慎思
    "judge":      {"model": "deepseek-v4-flash", "temperature": 0.0, "top_p": 0.8,  "max_tokens": 2000, "cache_ttl": 86400},  # 闫判官·裁决
    "trading_plan":{"model": "deepseek-v4-flash", "temperature": 0.5, "top_p": 0.95, "max_tokens": 3000, "cache_ttl": 86400},  # 策执远·策略
    "risk":       {"model": "deepseek-v4-flash", "temperature": 0.2, "top_p": 0.85, "max_tokens": 2000, "cache_ttl": 86400},  # 风控明
    "coherence":  {"model": "deepseek-v4-flash", "temperature": 0.0, "top_p": 0.8,  "max_tokens": 1500, "cache_ttl": 86400},  # 一致性裁判
}

# B2 Token 预算（FDT 可控：plan 期预估护栏）
LLM_TOKEN_BUDGET = {
    "per_round": 120000,    # 单 spawn prompt 超此预警
    "daily": 1500000,       # 日级累计超此中止 plan
}


# ═══════════════════════════════════════════════════════════
# 制度感知参数预设 — 市场制度变化时切换的整组参数
# 优先级: 主结构 P0(PARAM_OVERRIDES) → P1~P4 不变
#         制度预设作为 P4(default) 的替换基底
# 用法: apply_regime("trend") 将预设注入 P0
# ═══════════════════════════════════════════════════════════
REGIME_PARAMS = {
    # ── 趋势市 ── 放大通道突破信号, 给足趋势加分
    "trend": {
        "dc20": {
            "break_base_score": 40.0,
            "break_strong_bonus": 15.0,
        },
        "dc55": {
            "trend_base_score": 20.0,
            "trend_alignment_bonus": 10.0,
        },
        "volume": {
            "explosive_ratio": 2.0,
            "explosive_score": 12.0,
            "weak_penalty": -2.0,
        },
        "bb": {
            "squeeze_bonus": 1.0,
            "dc_consistency_bonus": 3.0,
        },
    },
    # ── 震荡市 ── 压低突破分, 加重缩量惩罚, 加强布林挤压识别
    "range": {
        "dc20": {
            "break_base_score": 20.0,
            "break_strong_bonus": 5.0,
        },
        "dc55": {
            "trend_base_score": 5.0,
            "trend_alignment_bonus": 2.0,
        },
        "volume": {
            "explosive_ratio": 1.3,
            "explosive_score": 8.0,
            "weak_penalty": -5.0,
        },
        "bb": {
            "squeeze_bonus": 5.0,
            "width_high_score": 10.0,
        },
    },
    # ── 高波动市 ── 适度保守, 阈值适当放宽但不激进
    "volatile": {
        "dc20": {
            "break_base_score": 25.0,
            "break_strong_bonus": 8.0,
        },
        "dc55": {
            "trend_base_score": 10.0,
            "trend_alignment_bonus": 3.0,
        },
        "volume": {
            "explosive_ratio": 1.8,
            "explosive_score": 10.0,
            "weak_penalty": -3.0,
        },
        "bb": {
            "squeeze_bonus": 3.0,
            "width_high_score": 8.0,
        },
    },
}

# 未识别/混合制度 — 用全局 default（无覆盖，相当于清除）
MIXED_REGIME_KEY = "default"


# ============================================================
# 品种→产业链映射（按 symbols.py 分类定义）
# ============================================================
SYMBOL_CHAIN_MAP = {
    # 黑色系 (7)
    "rb": "黑色系", "hc": "黑色系", "i": "黑色系",
    "j": "黑色系", "jm": "黑色系", "SF": "黑色系", "SM": "黑色系",
    # 能源链 (6)
    "sc": "能源链", "lu": "能源链", "fu": "能源链",
    "bu": "能源链", "pg": "能源链", "PX": "能源链",
    # 聚酯链 (5)
    "TA": "聚酯链", "PF": "聚酯链", "PR": "聚酯链",
    "eg": "聚酯链", "eb": "聚酯链",
    # 塑化链 (4)
    "v": "塑化链", "pp": "塑化链", "l": "塑化链", "MA": "塑化链",
    # 化工 (3)
    "SH": "化工", "SA": "化工", "UR": "化工",
    # 有色金属 (8)
    "cu": "有色金属", "al": "有色金属", "zn": "有色金属",
    "pb": "有色金属", "ni": "有色金属", "sn": "有色金属",
    "ao": "有色金属", "SS": "有色金属",
    # 贵金属 (2)
    "au": "贵金属", "ag": "贵金属",
    # 油脂油料 (8)
    "a": "油脂油料", "b": "油脂油料", "m": "油脂油料",
    "y": "油脂油料", "p": "油脂油料", "OI": "油脂油料",
    "RM": "油脂油料", "PK": "油脂油料",
    # 农产品 (6)
    "c": "农产品", "cs": "农产品", "SR": "农产品",
    "CF": "农产品", "jd": "农产品", "lh": "农产品",
    # 果蔬 (2)
    "AP": "果蔬", "CJ": "果蔬",
    # 建材化工 (6)
    "FG": "建材化工", "ru": "建材化工", "nr": "建材化工",
    "br": "建材化工", "sp": "建材化工", "op": "建材化工",
    # 新能源 (3)
    "lc": "新能源", "si": "新能源", "ps": "新能源",
    # 航运 (1)
    "ec": "航运",
    # 其他 (1)
    "rr": "其他",
}


# ============================================================
# 品种最小变动价位（tick size）— 用于DC20边界接近判定
# ============================================================
SYMBOL_TICK_SIZES = {
    # 黑色系
    "rb": 1, "hc": 1, "i": 1, "j": 1, "jm": 1, "SF": 2, "SM": 2,
    # 能源链
    "sc": 0.1, "lu": 1, "fu": 1, "bu": 1, "pg": 1, "PX": 2,
    # 聚酯链
    "TA": 2, "PF": 2, "PR": 2, "eg": 1, "eb": 1,
    # 塑化链
    "v": 1, "pp": 1, "l": 1, "MA": 1,
    # 化工
    "SH": 1, "SA": 1, "UR": 1,
    # 有色金属
    "cu": 10, "al": 5, "zn": 5, "pb": 5, "ni": 10, "sn": 10, "ao": 1, "SS": 5,
    # 贵金属
    "au": 0.02, "ag": 1,
    # 油脂油料
    "a": 1, "b": 1, "m": 1, "y": 2, "p": 2, "OI": 1, "RM": 1, "PK": 2,
    # 农产品
    "c": 1, "cs": 1, "SR": 1, "CF": 5, "jd": 1, "lh": 1,
    # 果蔬
    "AP": 1, "CJ": 5,
    # 建材化工
    "FG": 1, "ru": 5, "nr": 5, "br": 5, "sp": 2, "op": 1,
    # 新能源
    "lc": 50, "si": 5, "ps": 5,
    # 航运
    "ec": 0.1,
    # 其他
    "rr": 1,
}

def get_tick_size(symbol: str) -> float:
    """获取品种最小变动价位。支持大小写不敏感查找。"""
    s = symbol.lower()
    if s in SYMBOL_TICK_SIZES:
        return SYMBOL_TICK_SIZES[s]
    if symbol in SYMBOL_TICK_SIZES:
        return SYMBOL_TICK_SIZES[symbol]
    return 1.0  # 兜底

# ── 启动时加载优化参数（来自历史回测的品种级覆盖） ──
_OPT_PARAMS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "optimizer", "optimized_params.json"
)
if os.path.exists(_OPT_PARAMS_PATH):
    try:
        with open(_OPT_PARAMS_PATH, "r", encoding="utf-8") as _f:
            _loaded = json.load(_f)
        if "per_symbol" in _loaded:
            for _sym, _sym_cfg in _loaded["per_symbol"].items():
                if _sym not in CHANNEL_BREAKOUT_CONFIG["per_symbol"]:
                    CHANNEL_BREAKOUT_CONFIG["per_symbol"][_sym] = {}
                for _period, _period_cfg in _sym_cfg.items():
                    CHANNEL_BREAKOUT_CONFIG["per_symbol"][_sym][_period] = _period_cfg
    except Exception:
        pass  # 加载失败不影响核心功能

# P0 覆盖层（优化器注入，优先级最高）
_PARAM_OVERRIDES: dict = {}

def set_param_overrides(overrides: dict):
    """设置参数覆盖（优化器回测用）。调用后 resolve_param 优先返回覆盖值。"""
    global _PARAM_OVERRIDES
    _PARAM_OVERRIDES = overrides

def clear_param_overrides():
    """清除参数覆盖"""
    global _PARAM_OVERRIDES
    _PARAM_OVERRIDES = {}


# ═══ 制度感知参数切换 ═══
_CURRENT_REGIME: str = ""

def apply_regime(regime: str):
    """注入制度预设到 P0 覆盖层（替换全局默认参数基底）

    制度预设仅覆盖少数关键参数（dc20/dc55/volume/bb），其余保持 default。
    调用 set_param_overrides 注入，resolve_param 自动回落。
    制度为 "default"/"mixed"/"unknown" 时相当于清空覆盖。
    """
    global _CURRENT_REGIME
    _CURRENT_REGIME = regime
    if regime in ("default", "mixed", "unknown", ""):
        clear_param_overrides()
        return
    preset = REGIME_PARAMS.get(regime)
    if preset:
        set_param_overrides(preset)
    else:
        clear_param_overrides()


def current_regime() -> str:
    """返回当前生效的市场制度"""
    return _CURRENT_REGIME


def resolve_param(section: str, key: str, symbol: str = "",
                  chain: str = "", period: str = "daily") -> object:
    """四层回落解析通道突破策略参数（制度感知 v2.0）。

    优先级（从高到低）:
      P0: _PARAM_OVERRIDES（优化器注入 / 制度预设 apply_regime）
      P1: per_symbol[symbol][period][section][key]
      P2: per_chain[chain][period][section][key]
      P3: per_period[period][section][key]
      P4: default[section][key]（兜底，必须存在）
    """
    # P0 — 优化器覆盖（最高优先级）
    if _PARAM_OVERRIDES and section in _PARAM_OVERRIDES and key in _PARAM_OVERRIDES[section]:
        return _PARAM_OVERRIDES[section][key]

    cfg = CHANNEL_BREAKOUT_CONFIG
    # P1 — 大小写不敏感查找（runtime symbol 可能是 "SC"，优化器 key 可能是 "sc"）
    per_sym = cfg.get("per_symbol", {})
    sym_cfg = None
    if symbol and symbol in per_sym:
        sym_cfg = per_sym[symbol]
    elif symbol and (symbol_lower := symbol.lower()) in per_sym:
        sym_cfg = per_sym[symbol_lower]
    elif symbol and (symbol_upper := symbol.upper()) in per_sym:
        sym_cfg = per_sym[symbol_upper]

    if sym_cfg is not None and period in sym_cfg:
        section_cfg = sym_cfg[period].get(section)
        if section_cfg is not None and key in section_cfg:
            return section_cfg[key]
    # P2
    if chain and chain in cfg.get("per_chain", {}):
        chain_cfg = cfg["per_chain"][chain]
        if period in chain_cfg:
            section_cfg = chain_cfg[period].get(section)
            if section_cfg is not None and key in section_cfg:
                return section_cfg[key]
    # P3
    if period in cfg.get("per_period", {}):
        section_cfg = cfg["per_period"][period].get(section)
        if section_cfg is not None and key in section_cfg:
            return section_cfg[key]
    # P4 — 兜底
    default = cfg.get("default", {})
    return default[section][key]


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


# ============================================================
# 周期能力注册表（v5.11.0 FDT 周期发现层 — 单一真相源）
# ============================================================
# 【铁律】任何"有哪些周期 / 周期衍生属性"一律读本表，禁止在别处硬编码周期清单。
# 新增/停用周期 = 改本表一行 enabled，全链路（扫描/评分/发现/决策）自动跟随。
#   wf_key : 指向 knowledge_bridge.get_symbol_knowledge() 的 WF 测试准确率字段；
#            None 表示该周期暂无 WF 数据 → 发现层自动退化（wf 维权重归零，靠 signal/gap 维）。
#   gap_sensitive : 该周期是否对跳空敏感（决定默认执行风格）。
#   exec_default : 默认执行风格键（见 EXEC_STYLE_MAP）。
PERIOD_REGISTRY = {
    "daily": {"enabled": True,  "minutes": 1440, "min_bars": 60,  "wf_key": "daily_test_accuracy", "gap_sensitive": True,  "exec_default": "limit_order"},
    "240m":  {"enabled": True,  "minutes": 240,  "min_bars": 90,  "wf_key": None,                  "gap_sensitive": False, "exec_default": "next_bar_market"},
    "120m":  {"enabled": True,  "minutes": 120,  "min_bars": 120, "wf_key": None,                  "gap_sensitive": False, "exec_default": "next_bar_market"},
    "60m":   {"enabled": True,  "minutes": 60,   "min_bars": 120, "wf_key": "h_test_accuracy",     "gap_sensitive": False, "exec_default": "next_bar_market"},
    "30m":   {"enabled": True,  "minutes": 30,   "min_bars": 200, "wf_key": None,                  "gap_sensitive": False, "exec_default": "next_bar_market"},
}

# 辩论主周期 / 60m 副周期（语义化常量，单一来源，禁止在编排脚本写死字面量）
PRIMARY_PERIOD = "daily"
HOURLY_PERIOD = "60m"

# 周期发现适配分权重（可配置，不写死在引擎里）
PERIOD_FITNESS_WEIGHTS = {
    "wf_acc": 0.35,           # WF 测试准确率（有数据周期才生效）
    "signal_strength": 0.45,  # 通道突破信号强度 |total|
    "gap_risk": 0.20,         # 跳空/缺口风险（越低越好，1-gap 计入）
}

# 缺口风险 → 执行风格映射
EXEC_STYLE_MAP = {
    "limit_order": "限价单（避免跳空滑点）",
    "next_bar_market": "次根市价（缺口不敏感）",
}


def enabled_periods() -> list:
    """返回启用周期列表，按分钟数从大到小（大周期优先遍历，语义清晰）。"""
    return sorted(
        [p for p, c in PERIOD_REGISTRY.items() if c.get("enabled")],
        key=lambda p: -PERIOD_REGISTRY[p]["minutes"],
    )


def period_meta(period: str) -> dict:
    """取周期配置；未知周期安全回退 daily。"""
    return PERIOD_REGISTRY.get(period, PERIOD_REGISTRY["daily"])


# ═══════════════════════════════════════════════════════════
# V2/V3 增强验证器阈值（集中管理，替代散落在验证器py中的硬编码）
# ═══════════════════════════════════════════════════════════

ENHANCED_VALIDATOR_THRESHOLDS = {
    # volume_confirm.py (V2)
    "OI_SURGE_THRESHOLD": 15.0,      # OI 暴增 % → 主力建仓判定
    "OI_SHRINK_THRESHOLD": -10.0,    # OI 萎缩 % → 主力出货判定
    # atr_vol_timing.py (V3)
    "ATR_PCT_LOW": 0.5,              # 低波动阈值 (%)，低于则降级
    "ATR_PCT_HIGH": 4.0,             # 高波动阈值 (%)，高于仅标记
    "BASIS_WIDEN_THRESHOLD": 2.0,    # 基差走阔 % → 弹簧压缩覆写
    "BASIS_SHRINK_THRESHOLD": -2.0,  # 基差收缩 % → 过热降级
    # p0_4_raw_kline.py (V1 增强)
    "BASIS_CONFLICT_THRESHOLD": 2.0, # 基差与突破方向冲突阈值 %
}
