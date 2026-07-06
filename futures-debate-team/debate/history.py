"""
辩论历史反馈模块 — 轻量JSON档案（append-only）
==============================================

记录每次辩论的品种评分和结果，用于：
  - 提高品种选择的连贯性
  - 为闫判官提供历史参考
  - 为 ML 模型积累训练数据
"""

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 默认档案路径（可被环境变量覆盖）
_DEFAULT_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "debate_history"
)


def _get_history_dir() -> str:
    """动态获取历史目录（支持运行时切换环境变量）"""
    return os.environ.get("DEBATE_HISTORY_DIR", _DEFAULT_HISTORY_DIR)


def _get_history_file() -> str:
    return os.path.join(_get_history_dir(), "debate_feedback.json")


def _get_records_file() -> str:
    return os.path.join(_get_history_dir(), "debate_records.jsonl")


def _ensure_dir():
    """确保档案目录存在"""
    os.makedirs(_get_history_dir(), exist_ok=True)


def load_feedback() -> dict:
    """加载历史反馈汇总。

    Returns:
        { symbol: {
            "debate_count": int,           # 辩论次数
            "high_value_count": int,       # 被评为高价值的次数
            "avg_judge_confidence": float, # 平均闫判官置信度 (0-100)
            "win_rate": float,             # 胜率 (0-1)，无结果时为 None
            "avg_debate_value": float,     # 平均辩论价值评分
        }, ... }
    """
    _ensure_dir()
    if not os.path.exists(_get_history_file()):
        return {}
    try:
        with open(_get_history_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning(f"读取历史反馈失败: {e}")
        return {}


def record_feedback(symbol: str, debate_value: float, judge_confidence: float, outcome: str = None) -> None:
    """记录一次辩论的反馈。

    Args:
        symbol: 品种代码（如 "RB"）
        debate_value: 本次辩论价值评分 (0-100)
        judge_confidence: 闫判官置信度 (0-100)
        outcome: 最终结果 "win" / "loss" / None（待定）
    """
    _ensure_dir()

    # 1. 写入详细记录（JSONL, append-only）
    record = {
        "symbol": symbol.upper(),
        "debate_value": round(debate_value, 2),
        "judge_confidence": round(judge_confidence, 2),
        "outcome": outcome,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(_get_records_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except IOError as e:
        logger.error(f"写入辩论记录失败: {e}")

    # 2. 更新汇总
    feedback = load_feedback()
    sym = symbol.upper()
    if sym not in feedback:
        feedback[sym] = {
            "debate_count": 0,
            "high_value_count": 0,
            "avg_judge_confidence": 0.0,
            "win_rate": None,
            "avg_debate_value": 0.0,
            "wins": 0,
            "losses": 0,
        }

    f = feedback[sym]
    old_count = f["debate_count"]
    new_count = old_count + 1

    # 更新平均值
    f["avg_debate_value"] = round((f["avg_debate_value"] * old_count + debate_value) / new_count, 2)
    f["avg_judge_confidence"] = round((f["avg_judge_confidence"] * old_count + judge_confidence) / new_count, 2)

    if debate_value >= 70:
        f["high_value_count"] += 1

    if outcome == "win":
        f["wins"] += 1
    elif outcome == "loss":
        f["losses"] += 1

    total_decided = f["wins"] + f["losses"]
    if total_decided > 0:
        f["win_rate"] = round(f["wins"] / total_decided, 3)
    else:
        f["win_rate"] = None

    f["debate_count"] = new_count

    try:
        _ensure_dir()
        with open(_get_history_file(), "w", encoding="utf-8") as f_out:
            json.dump(feedback, f_out, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"写入历史反馈汇总失败: {e}")


def get_symbol_value_score(symbol: str, feedback: dict = None) -> float:
    """基于历史反馈计算品种价值调整分 [-10, +10]。

    高价值历史 → 加分；低价值历史 → 减分。

    Args:
        symbol: 品种代码
        feedback: load_feedback() 的返回，为 None 时自动加载

    Returns:
        调整分值 [-10, +10]
    """
    if feedback is None:
        feedback = load_feedback()

    sym = symbol.upper()
    entry = feedback.get(sym)
    if entry is None:
        return 0.0

    score = 0.0
    count = entry.get("debate_count", 0)
    if count == 0:
        return 0.0

    # 高价值比例加分
    hv_ratio = entry.get("high_value_count", 0) / count
    score += hv_ratio * 5.0  # 0~5 分

    # 胜率加分
    wr = entry.get("win_rate")
    if wr is not None:
        score += (wr - 0.5) * 4.0  # -2~+2 分

    # 置信度加分
    avg_conf = entry.get("avg_judge_confidence", 50)
    score += (avg_conf - 50) / 50 * 3.0  # -3~+3 分

    return round(max(-10.0, min(10.0, score)), 2)


def get_recent_records(limit: int = 20) -> list:
    """获取最近的辩论记录。

    Args:
        limit: 返回的最大记录数

    Returns:
        最近 N 条记录（时间降序）
    """
    _ensure_dir()
    if not os.path.exists(_get_records_file()):
        return []
    try:
        records = []
        with open(_get_records_file(), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records[-limit:]
    except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
        logger.warning(f"读取辩论记录失败: {e}")
        return []


def clear_history() -> None:
    """清空历史数据（谨慎使用）"""
    try:
        if os.path.exists(_get_history_file()):
            os.remove(_get_history_file())
        if os.path.exists(_get_records_file()):
            os.remove(_get_records_file())
        logger.info("已清空辩论历史数据")
    except IOError as e:
        logger.error(f"清空历史数据失败: {e}")
