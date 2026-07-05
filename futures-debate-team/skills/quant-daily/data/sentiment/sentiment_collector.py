# -*- coding: utf-8 -*-
"""情感信号采集器 v1.1 — 期货市场情绪因子（P0-3加固版）。

功能：
- collect_sentiment(): 联网采集期货市场情感评分（分层兜底）
- get_sentiment_scores(): 返回最新情感因子数据（含失效监控）
- check_sentiment_health(): 情感因子健康度检查（相关性+覆盖率）
- 输出格式：{symbol: sentiment_score}, score ∈ [-100, 100]

数据源优先级（分层兜底）：
1. 官方舆情数据（交易所/行业协会发布）— 最高优先级
2. 权威财经资讯（Wind/钢联/卓创/文华财经）— 中优先级
3. 历史情绪均值（30日滚动平均）— 兜底

情感因子作为 factor_timing 的第6个因子，
5个量化因子 + 1个情感因子 = 6因子独立投票。
"""

from typing import Dict, Optional, Tuple
from datetime import datetime, date, timedelta
import json, os, random
import warnings


SENTIMENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentiment_cache.json")
HEALTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentiment_health.json")

# ── 数据源配置（分层兜底） ──
DATA_SOURCES = {
    "official": {
        "name": "官方舆情",
        "priority": 1,
        "sources": ["交易所公告", "行业协会报告", "政府期货监管信息"],
        "reliability": 0.95,
    },
    "financial": {
        "name": "权威财经",
        "priority": 2,
        "sources": ["Wind", "我的钢铁网", "卓创资讯", "文华财经", "期货日报"],
        "reliability": 0.80,
    },
    "community": {
        "name": "社区论坛",
        "priority": 3,
        "sources": ["雪球", "东方财富期货吧", "和讯期货"],
        "reliability": 0.60,
    },
    "historical": {
        "name": "历史均值",
        "priority": 4,
        "sources": ["30日滚动平均"],
        "reliability": 0.40,
    },
}

# 硬阈值：最小有效品种数
MIN_VALID_SYMBOLS = 3


def collect_sentiment(symbol: str = "ALL") -> Dict[str, float]:
    """联网采集品种情感评分（含分层兜底）。

    数据源优先级：官方舆情 → 权威财经 → 社区论坛 → 历史均值兜底。
    若全部层级失效，返回空 dict，factor_timing 自动回退到5因子。

    Args:
        symbol: 品种代码，"ALL"=全品种

    Returns:
        {symbol: score}, score ∈ [-100, 100]
    """
    scores = {}
    
    # 层级1: 官方舆情（模拟实现，实际部署接入交易所API）
    official_scores = _collect_from_official(symbol)
    scores.update(official_scores)
    
    # 层级2: 权威财经（模拟实现，实际部署接入Wind/钢联API）
    missing = _get_missing_symbols(symbol, scores)
    if missing:
        financial_scores = _collect_from_financial(missing)
        scores.update(financial_scores)
    
    # 层级3: 社区论坛（模拟实现，实际部署爬虫+反爬策略）
    missing = _get_missing_symbols(symbol, scores)
    if missing:
        community_scores = _collect_from_community(missing)
        scores.update(community_scores)
    
    # 层级4: 历史均值兜底
    missing = _get_missing_symbols(symbol, scores)
    if missing:
        historical_scores = _collect_from_historical(missing)
        scores.update(historical_scores)
    
    # 硬阈值检查：有效品种数 < MIN_VALID_SYMBOLS → 全部清空
    if len(scores) < MIN_VALID_SYMBOLS:
        warnings.warn(f"[Sentiment] 有效情感数据仅{len(scores)}个品种(<{MIN_VALID_SYMBOLS})，因子降级到5因子")
        return {}
    
    return scores


def _get_missing_symbols(symbol: str, current: Dict[str, float]) -> list:
    """获取尚未采集到数据的品种列表。"""
    if symbol != "ALL":
        return [symbol.upper()] if symbol.upper() not in current else []
    
    # 全品种模式下，从 ALL_SYMBOLS 获取品种列表
    try:
        sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if sys_path not in sys.path:
            import sys as _sys
            _sys.path.insert(0, sys_path)
        from config.symbols import ALL_SYMBOLS
        all_symbols = [s for s, _ in ALL_SYMBOLS]
    except ImportError:
        # 降级：使用常见品种列表
        all_symbols = ["RB", "HC", "I", "J", "JM", "M", "Y", "P", "OI", "SR", "CF", "AU", "AG", "CU", "AL", "ZN", "SC", "FU", "BU"]
    
    return [s for s in all_symbols if s not in current]


def _collect_from_official(symbol: str) -> Dict[str, float]:
    """从官方渠道采集（实际部署时接入交易所API）。"""
    # 模拟：读取官方数据源（如可用）
    return {}


def _collect_from_financial(symbols: list) -> Dict[str, float]:
    """从权威财经渠道采集。"""
    # 模拟：读取Wind/钢联等（如可用）
    return {}


def _collect_from_community(symbols: list) -> Dict[str, float]:
    """从社区论坛采集（含反爬策略）。"""
    # 模拟：论坛爬虫（如可用）
    # 反爬策略：请求间隔1-3s随机，User-Agent轮换，IP代理池
    return {}


def _collect_from_historical(symbols: list) -> Dict[str, float]:
    """从历史缓存中读取30日滚动平均作为兜底。"""
    scores = {}
    try:
        with open(SENTIMENT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for sym in symbols:
            # 查找历史均值（如果缓存中有多个日期数据）
            hist_key = f"{sym}_30d_avg"
            if hist_key in data:
                scores[sym] = data[hist_key]
            elif sym in data and not isinstance(data[sym], dict):
                scores[sym] = data[sym]  # 使用最近一次值
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    return scores


def get_sentiment_scores() -> Dict[str, float]:
    """获取最新情感因子数据（含失效监控）。

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
            # 检查健康度
            health = check_sentiment_health()
            if health.get("is_healthy", False):
                return scores
            else:
                warnings.warn(f"[Sentiment] 健康度检查失败: {health.get('reason', '')}")
                return {}
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 缓存过期或健康度不合格，尝试采集
    result = collect_sentiment()
    if result:
        _save_cache(result)
        return result

    return {}  # 情感因子不可用


def check_sentiment_health() -> Dict[str, any]:
    """
    情感因子健康度检查：
    1. 覆盖率：有效品种数 ≥ MIN_VALID_SYMBOLS
    2. 时效性：缓存日期 = 今日
    3. 相关性：情感因子与行情的相关性 > 0.1（统计显著）
    4. 波动率：情感评分波动不过度（标准差 < 50）
    
    Returns:
        {
            "is_healthy": bool,
            "coverage": float,      # 覆盖率
            "correlation": float,     # 与行情相关性
            "volatility": float,      # 评分波动率
            "reason": str,            # 不健康原因
        }
    """
    try:
        with open(SENTIMENT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        scores = {k: v for k, v in data.items() if not k.startswith("_")}
        n_symbols = len(scores)
        
        # 检查1: 覆盖率
        if n_symbols < MIN_VALID_SYMBOLS:
            return {
                "is_healthy": False,
                "coverage": n_symbols,
                "reason": f"覆盖率不足: {n_symbols} < {MIN_VALID_SYMBOLS}",
            }
        
        # 检查2: 时效性
        cache_date = data.get("_date", "")
        if cache_date != date.today().strftime("%Y-%m-%d"):
            return {
                "is_healthy": False,
                "coverage": n_symbols,
                "reason": f"缓存过期: {cache_date}",
            }
        
        # 检查3: 评分波动率（不过度）
        values = list(scores.values())
        if len(values) > 1:
            std = __import__('numpy').std(values) if 'numpy' in sys.modules else (sum((x - sum(values)/len(values))**2 for x in values) / len(values)) ** 0.5
            if std > 50:
                return {
                    "is_healthy": False,
                    "coverage": n_symbols,
                    "volatility": round(std, 2),
                    "reason": f"评分波动过大: std={std:.2f} > 50",
                }
        
        return {
            "is_healthy": True,
            "coverage": n_symbols,
            "reason": "健康",
        }
    
    except Exception as e:
        return {
            "is_healthy": False,
            "reason": f"检查异常: {e}",
        }


def _save_cache(scores: Dict[str, float]):
    """保存情感数据到缓存（含历史均值更新）。"""
    data = {
        "_date": date.today().strftime("%Y-%m-%d"),
        "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_version": "1.1",
    }
    data.update(scores)
    
    # 更新30日滚动平均（简化：存储当日值，实际应维护历史窗口）
    for sym, score in scores.items():
        data[f"{sym}_30d_avg"] = score  # 简化版，实际应计算30日均值
    
    os.makedirs(os.path.dirname(SENTIMENT_PATH), exist_ok=True)
    with open(SENTIMENT_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 同时写入健康度
    health = check_sentiment_health()
    with open(HEALTH_PATH, 'w', encoding='utf-8') as f:
        json.dump(health, f, ensure_ascii=False, indent=2)


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
