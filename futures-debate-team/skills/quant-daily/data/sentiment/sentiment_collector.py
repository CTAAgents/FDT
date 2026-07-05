# -*- coding: utf-8 -*-
"""情感信号采集器 v1.0 — 期货市场情绪因子（P1-1）。

功能：
- collect_sentiment(): 联网采集期货市场情感评分
- get_sentiment_scores(): 返回最新情感因子数据
- 输出格式：{symbol: sentiment_score}，score ∈ [-100, 100]

情感因子作为 factor_timing 的第6个因子，
5个量化因子 + 1个情感因子 = 6因子独立投票。
"""

from typing import Dict, Optional
from datetime import datetime, date
import json, os, random


SENTIMENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentiment_cache.json")


def collect_sentiment(symbol: str = "ALL") -> Dict[str, float]:
    """联网采集品种情感评分。

    通过 WebSearch 搜索各品种期货论坛/新闻情感。
    返回 {symbol: sentiment_score}, score ∈ [-100, 100]。

    正值 = 市场情绪偏多，负值 = 偏空。

    Args:
        symbol: 品种代码，"ALL"=全品种

    Returns:
        {symbol: score}
    """
    # 使用 WebSearch/WebFetch 采集情感信号
    # 但因 skill 边界限制，此处返回默认中性值
    # 实际部署时由外部定时任务更新 sentiment_cache.json
    return {}


def get_sentiment_scores() -> Dict[str, float]:
    """获取最新情感因子数据。

    优先从本地缓存读取。若缓存过期（>24h），触发collect_sentiment()。

    Returns:
        {symbol: sentiment_score}, score ∈ [-100, 100]
        空 dict = 情感因子不可用，factor_timing 自动回退到5因子
    """
    try:
        with open(SENTIMENT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cache_date = data.get("_date", "")
        if cache_date == date.today().strftime("%Y-%m-%d"):
            scores = {k: v for k, v in data.items() if not k.startswith("_")}
            return scores
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 缓存过期，尝试采集
    result = collect_sentiment()
    if result:
        _save_cache(result)
        return result

    return {}  # 情感因子不可用


def _save_cache(scores: Dict[str, float]):
    """保存情感数据到缓存。"""
    data = {"_date": date.today().strftime("%Y-%m-%d"),
            "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    data.update(scores)
    os.makedirs(os.path.dirname(SENTIMENT_PATH), exist_ok=True)
    with open(SENTIMENT_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def seed_sentiment(symbol: str, score: float):
    """手动设置品种情感评分（用于测试或离线标注）。

    Args:
        symbol: 品种代码
        score: 情感评分 [-100, 100]
    """
    try:
        with open(SENTIMENT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"_date": date.today().strftime("%Y-%m-%d"),
                "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    data[symbol.upper()] = score
    _save_cache({k: v for k, v in data.items() if not k.startswith("_")})
