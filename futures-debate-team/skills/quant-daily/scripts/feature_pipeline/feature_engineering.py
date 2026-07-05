# -*- coding: utf-8 -*-
"""特征工程管道 — 从K线+OI+技术指标构建ML训练特征集。

输出：按品种+日期存储的特征向量，供 LightGBM 训练使用。

核心流程:
1. collect_raw_data(): 从 scan_all.py 输出中采集原始数据
2. engineer_features(): 从原始数据计算衍生特征
3. build_label(): 生成未来N根K线方向标签
4. store_features(): 持久化到 feature_store/
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json, os, math
import numpy as np


# ── 特征定义（30+ 维度） ──
# 分类: 价格动量 / OI衍生 / 技术指标 / 期限结构 / 跨品种
FEATURE_META = {
    # --- 价格动量 (10维) ---
    "roc_1": {"type": "momentum", "desc": "1日收益率"},
    "roc_5": {"type": "momentum", "desc": "5日收益率"},
    "roc_10": {"type": "momentum", "desc": "10日收益率"},
    "roc_20": {"type": "momentum", "desc": "20日收益率"},
    "volatility_5": {"type": "momentum", "desc": "5日波动率"},
    "volatility_20": {"type": "momentum", "desc": "20日波动率"},
    "high_low_range_5": {"type": "momentum", "desc": "5日高低振幅均值"},
    "high_low_range_20": {"type": "momentum", "desc": "20日高低振幅均值"},
    "close_position_5": {"type": "momentum", "desc": "收盘价在5日高低区间位置"},
    "close_position_20": {"type": "momentum", "desc": "收盘价在20日高低区间位置"},

    # --- OI衍生 (8维) ---
    "oi_change_1": {"type": "oi", "desc": "1日OI变化率"},
    "oi_change_5": {"type": "oi", "desc": "5日OI变化率"},
    "oi_price_divergence_1": {"type": "oi", "desc": "OI-价背离(1日)"},
    "oi_price_divergence_5": {"type": "oi", "desc": "OI-价背离(5日) 价升OI降=虚涨"},
    "oi_vol_corr_5": {"type": "oi", "desc": "OI-成交量5日相关系数"},
    "oi_ma_ratio": {"type": "oi", "desc": "OI/MA20(OI) 比值"},
    "oi_zscore": {"type": "oi", "desc": "OI的20日z-score"},
    "volume_ratio": {"type": "oi", "desc": "成交量/20日均量"},

    # --- 技术指标 (8维) ---
    "adx": {"type": "technical", "desc": "ADX趋势强度"},
    "rsi_14": {"type": "technical", "desc": "RSI14"},
    "macd_hist": {"type": "technical", "desc": "MACD柱状值"},
    "macd_cross": {"type": "technical", "desc": "MACD金叉/死叉 1/0/-1"},
    "bb_width": {"type": "technical", "desc": "布林带宽"},
    "bb_position": {"type": "technical", "desc": "价格在布林带位置"},
    "ma_short_long": {"type": "technical", "desc": "MA20/MA60 比值"},
    "atr_pct": {"type": "technical", "desc": "ATR/价格 比值"},

    # --- 期限结构 (4维) ---
    "ts_type_encoded": {"type": "term_structure", "desc": "展期结构编码"},
    "ts_slope": {"type": "term_structure", "desc": "展期斜率"},
    "basis_pct": {"type": "term_structure", "desc": "基差/价格"},
    "spread_1_5": {"type": "term_structure", "desc": "1-5月差"},

    # --- 跨品种 (2维, 需外部数据) ---
    "cross_corr_peers": {"type": "cross", "desc": "同板块关联品种平均相关系数"},
    "cross_price_ratio": {"type": "cross", "desc": "品种/板块指数 比值"},
}


def engineer_features(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[float],
    oi_series: Optional[List[float]] = None,
    adx: Optional[float] = None,
    rsi: Optional[float] = None,
    macd_hist: Optional[float] = None,
    atr: Optional[float] = None,
) -> Dict[str, float]:
    """从原始K线数据计算全部衍生特征。

    Args:
        closes: 收盘价序列（最近的在最后）
        highs: 最高价序列
        lows: 最低价序列
        volumes: 成交量序列
        oi_series: 持仓量序列（可选）
        各项技术指标值（可选）

    Returns:
        {特征名: 值, ...}
    """
    features = {}
    n = len(closes)
    if n < 5:
        return features

    # --- 价格动量 ---
    ref_price = closes[-1] if closes[-1] != 0 else 1
    features["roc_1"] = _safe_roc(closes, 1)
    features["roc_5"] = _safe_roc(closes, 5)
    features["roc_10"] = _safe_roc(closes, 10)
    features["roc_20"] = _safe_roc(closes, 20)
    features["volatility_5"] = _safe_volatility(closes, 5)
    features["volatility_20"] = _safe_volatility(closes, 20)
    features["high_low_range_5"] = _safe_range(highs, lows, 5)
    features["high_low_range_20"] = _safe_range(highs, lows, 20)

    # 收盘价在高低区间位置
    if n >= 5:
        h5, l5 = max(highs[-5:]), min(lows[-5:])
        features["close_position_5"] = (closes[-1] - l5) / (h5 - l5) if h5 > l5 else 0.5
    if n >= 20:
        h20, l20 = max(highs[-20:]), min(lows[-20:])
        features["close_position_20"] = (closes[-1] - l20) / (h20 - l20) if h20 > l20 else 0.5

    # --- OI衍生 ---
    if oi_series and len(oi_series) >= 5:
        features["oi_change_1"] = _safe_pct_change(oi_series, 1)
        features["oi_change_5"] = _safe_pct_change(oi_series, 5)
        # OI-价背离: 价升OI降 = 负值
        oi_1 = _safe_pct_change(oi_series, 1)
        p_1 = features.get("roc_1", 0)
        features["oi_price_divergence_1"] = p_1 - oi_1 if abs(oi_1) < 50 else 0
        features["oi_price_divergence_5"] = features.get("roc_5", 0) - _safe_pct_change(oi_series, 5)
        # OI/均价
        oi_ma = sum(oi_series[-20:]) / max(len(oi_series[-20:]), 1) if len(oi_series) >= 20 else sum(oi_series) / len(oi_series)
        features["oi_ma_ratio"] = oi_series[-1] / max(oi_ma, 1)
        # OI z-score
        oi_vals = oi_series[-20:] if len(oi_series) >= 20 else oi_series
        oi_mean = sum(oi_vals) / len(oi_vals)
        oi_std = math.sqrt(sum((v - oi_mean) ** 2 for v in oi_vals) / len(oi_vals)) if len(oi_vals) > 1 else 1
        features["oi_zscore"] = (oi_series[-1] - oi_mean) / max(oi_std, 1)

    # --- 成交量 ---
    if volumes and len(volumes) >= 20:
        vol_ma = sum(volumes[-20:]) / 20
        features["volume_ratio"] = volumes[-1] / max(vol_ma, 1)

    # --- 技术指标 ---
    if adx is not None:
        features["adx"] = adx
    if rsi is not None:
        features["rsi_14"] = rsi
    if macd_hist is not None:
        features["macd_hist"] = macd_hist
    if atr is not None:
        features["atr_pct"] = atr / max(ref_price, 1) * 100

    # MA短长比
    if n >= 60:
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60
        features["ma_short_long"] = ma20 / max(ma60, 1)

    return features


def export_feature_summary(symbol: str, features: Dict[str, float]) -> Dict[str, any]:
    """为品种输出可读的特征摘要，供研究员（探源/观澜）自动注入。

    返回 top-5 最显著的特征（偏离均值最远的）及其解读。

    Args:
        symbol: 品种代码
        features: engineer_features() 输出的特征字典

    Returns:
        {"symbol": str, "top_features": [...], "summary": str}
    """
    if not features:
        return {"symbol": symbol, "top_features": [], "summary": "无特征数据"}

    # 特征解读映射
    FEATURE_MEANING = {
        "roc_1": "1日动量",
        "roc_5": "5日动量",
        "roc_10": "10日动量",
        "roc_20": "20日动量",
        "volatility_5": "5日波动率",
        "volatility_20": "20日波动率",
        "high_low_range_5": "5日振幅",
        "high_low_range_20": "20日振幅",
        "close_position_5": "5日收盘价分位",
        "close_position_20": "20日收盘价分位",
        "oi_change_1": "OI日变化",
        "oi_change_5": "OI 5日变化",
        "oi_price_divergence_1": "OI-价背离(1d)",
        "oi_price_divergence_5": "OI-价背离(5d)",
        "oi_ma_ratio": "OI/均值比",
        "oi_zscore": "OI Z分数",
        "volume_ratio": "成交量/均值比",
        "adx": "ADX趋势强度",
        "rsi_14": "RSI(14)",
        "macd_hist": "MACD柱",
        "atr_pct": "ATR%/价",
        "ma_short_long": "MA短长比",
    }

    # 按偏离中位值排序（以0.5为中性基准）
    scored = []
    for k, v in features.items():
        deviation = abs(v - 0.5) if "position" in k or "ratio" in k else abs(v)
        meaning = FEATURE_MEANING.get(k, k)
        scored.append((deviation, k, v, meaning))

    scored.sort(reverse=True)
    top5 = scored[:5]

    top_features = []
    lines = []
    for _, k, v, meaning in top5:
        entry = {"feature": k, "name": meaning, "value": round(v, 4)}
        top_features.append(entry)
        lines.append(f"{meaning}({k})={v:.4f}")

    summary = f"{symbol} 特征摘要: {' | '.join(lines)}"

    return {
        "symbol": symbol,
        "top_features": top_features,
        "summary": summary,
    }


def build_label(
    closes: List[float],
    forecast_horizon: int = 5,
    threshold_pct: float = 1.0,
) -> int:
    """生成未来 forecast_horizon 根K线的方向标签。

    Args:
        closes: 收盘价序列
        forecast_horizon: 预测未来多少根K线
        threshold_pct: 最小波动阈值（低于此值标为0=横盘）

    Returns:
        1 = 涨, -1 = 跌, 0 = 横盘/无法判断
    """
    if len(closes) < forecast_horizon + 1:
        return 0
    future_return = (closes[-1] - closes[-(forecast_horizon + 1)]) / max(closes[-(forecast_horizon + 1)], 1) * 100
    if future_return > threshold_pct:
        return 1
    elif future_return < -threshold_pct:
        return -1
    return 0


def store_features(
    symbol: str,
    date_str: str,
    features: Dict[str, float],
    label: int,
    store_dir: str,
):
    """持久化特征向量到 feature_store/。"""
    record = {
        "symbol": symbol,
        "date": date_str,
        **features,
        "label": label,
    }
    os.makedirs(store_dir, exist_ok=True)
    fp = os.path.join(store_dir, f"{symbol}_{date_str}.json")
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return fp


def load_dataset(
    store_dir: str,
    symbols: Optional[List[str]] = None,
    max_records: int = 10000,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """从 feature_store/ 加载训练数据集。

    Returns:
        (X, y, feature_names): 特征矩阵、标签、特征名列表
    """
    records = []
    for fname in os.listdir(store_dir):
        if not fname.endswith('.json'):
            continue
        if symbols:
            sym = fname.split('_')[0]
            if sym not in symbols:
                continue
        with open(os.path.join(store_dir, fname), 'r', encoding='utf-8') as f:
            records.append(json.load(f))
        if len(records) >= max_records:
            break

    if not records:
        return np.array([]), np.array([]), []

    feature_names = [k for k in records[0].keys() if k not in ('symbol', 'date', 'label')]
    X = np.array([[r.get(k, 0) for k in feature_names] for r in records])
    y = np.array([r.get('label', 0) for r in records])

    return X, y, feature_names


# ── 辅助函数 ──

def _safe_roc(series: List[float], period: int) -> float:
    if len(series) <= period or series[-(period + 1)] == 0:
        return 0.0
    return (series[-1] - series[-(period + 1)]) / series[-(period + 1)] * 100


def _safe_pct_change(series: List[float], period: int) -> float:
    if len(series) <= period or series[-(period + 1)] == 0:
        return 0.0
    return (series[-1] - series[-(period + 1)]) / series[-(period + 1)] * 100


def _safe_volatility(series: List[float], window: int) -> float:
    if len(series) < window + 1:
        return 0.0
    returns = [(series[i] - series[i - 1]) / max(series[i - 1], 1)
               for i in range(-window, 0)]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance) * 100


def _safe_range(highs: List[float], lows: List[float], window: int) -> float:
    if len(highs) < window or len(lows) < window:
        return 0.0
    ranges = [(highs[-i] - lows[-i]) / max(lows[-i], 1) * 100 for i in range(1, window + 1)]
    return sum(ranges) / len(ranges)
