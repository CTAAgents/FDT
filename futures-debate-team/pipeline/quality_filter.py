"""
研报质量过滤模块 — B-Minimal + B-Standard
=========================================

基于 Bridgewater 方法论研报质量过滤路径。

B-Minimal: 五层打分逻辑转 Checklist Prompt 过滤
B-Standard: 蒸馏打分逻辑到轻量分类器

依赖: polyester-chain-analysis, energy-chain-analysis 的五层打分输出
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ─── B-Minimal: Checklist Prompt 过滤 ─────────────────────────

QUALITY_CHECKLIST = {
    "has_quantitative_data": {
        "weight": 20,
        "description": "包含量化数据（开工率、库存、利润、基差等）",
    },
    "has_supply_shock": {
        "weight": 20,
        "description": "包含供给冲击信息（检修、停产、进出口变化）",
    },
    "has_demand_change": {
        "weight": 20,
        "description": "包含需求变化信息（政策、季节性、终端需求数据）",
    },
    "has_price_direction": {
        "weight": 25,
        "description": "对价格方向有明确判断（利多/利空）",
    },
    "has_timeliness": {
        "weight": 15,
        "description": "时效性高（过去24小时内的新信息）",
    },
}


def parse_report_quality(report_text: str, prices: dict = None) -> dict:
    """
    基于规则对研报进行质量评分。

    这是 B-Minimal 的核心函数。不需要调用 LLM，
    而是基于报告文本的结构化特征做启发式评分。

    Args:
        report_text: 研报/资讯正文
        prices: 价格数据 dict（可选，用于验证时效性）

    Returns:
        {
            "is_valuable": bool,
            "score": int (0-100),
            "checklist": { "has_quantitative_data": bool, ... },
            "detail_scores": { "has_quantitative_data": int, ... },
        }
    """
    if not report_text or not report_text.strip():
        return {
            "is_valuable": False,
            "score": 0,
            "checklist": {k: False for k in QUALITY_CHECKLIST},
            "detail_scores": {k: 0 for k in QUALITY_CHECKLIST},
            "reason": "空文本",
        }

    text_lower = report_text.lower()
    detail_scores = {}
    checklist = {}

    # 1. 量化数据检测
    quant_patterns = [
        "开工率",
        "库存",
        "利润",
        "基差",
        "升贴水",
        "产能利用率",
        "产量",
        "消费量",
        "出口",
        "进口",
        "供需",
        "%",
        "万吨",
        "吨",
        "桶",
        "亿",
        "万手",
        "百分点",
        "同比",
        "环比",
        "增长率",
        "下降",
        "上升",
    ]
    quant_hit = sum(1 for p in quant_patterns if p in report_text)
    has_quant = quant_hit >= 2
    checklist["has_quantitative_data"] = has_quant
    detail_scores["has_quantitative_data"] = min(
        QUALITY_CHECKLIST["has_quantitative_data"]["weight"],
        QUALITY_CHECKLIST["has_quantitative_data"]["weight"] * quant_hit / 5,
    )

    # 2. 供给冲击检测
    supply_patterns = [
        "检修",
        "停产",
        "减产",
        "限产",
        "停工",
        "爆炸",
        "事故",
        "不可抗力",
        "封航",
        "运输中断",
        "管道",  # 运输中断也归为供给
        "进口减少",
        "出口管制",
        "制裁",
        "OPEC",
        "欧佩克",
    ]
    supply_hit = sum(1 for p in supply_patterns if p in report_text)
    has_supply = supply_hit >= 1
    checklist["has_supply_shock"] = has_supply
    detail_scores["has_supply_shock"] = min(
        QUALITY_CHECKLIST["has_supply_shock"]["weight"],
        QUALITY_CHECKLIST["has_supply_shock"]["weight"] * supply_hit / 2,
    )

    # 3. 需求变化检测
    demand_patterns = [
        "政策",
        "季节性",
        "终端需求",
        "需求",
        "房地产",
        "基建",
        "汽车",
        "家电",
        "出口订单",
        "PMI",
        "社融",
        "货币",
        "财政",
        "刺激",
        "减税",
        "补贴",
        "消费",
        "投资",
    ]
    demand_hit = sum(1 for p in demand_patterns if p in report_text)
    has_demand = demand_hit >= 1
    checklist["has_demand_change"] = has_demand
    detail_scores["has_demand_change"] = min(
        QUALITY_CHECKLIST["has_demand_change"]["weight"],
        QUALITY_CHECKLIST["has_demand_change"]["weight"] * demand_hit / 3,
    )

    # 4. 价格方向判断检测
    direction_patterns = [
        "利多",
        "利空",
        "看涨",
        "看跌",
        "上涨",
        "下跌",
        "反弹",
        "回落",
        "支撑",
        "压力",
        "做多",
        "做空",
        "买入",
        "卖出",
        "偏强",
        "偏弱",
        "震荡上行",
        "震荡下行",
        "牛市",
        "熊市",
        "多头",
        "空头",
    ]
    direction_hit = sum(1 for p in direction_patterns if p in report_text)
    has_direction = direction_hit >= 1
    checklist["has_price_direction"] = has_direction
    detail_scores["has_price_direction"] = min(
        QUALITY_CHECKLIST["has_price_direction"]["weight"],
        QUALITY_CHECKLIST["has_price_direction"]["weight"] * direction_hit / 2,
    )

    # 5. 时效性检测
    date_patterns = [
        "今日",
        "昨日",
        "今天",
        "昨天",
        "凌晨",
        "早间",
        "晚间",
        "刚刚",
        "最新",
        "截至",
        "日内",
        "当前",
    ]
    date_hit = sum(1 for p in date_patterns if p in report_text)
    has_timeliness = date_hit >= 1 or ("日" in report_text[:100] and len(report_text) <= 2000)
    checklist["has_timeliness"] = has_timeliness
    detail_scores["has_timeliness"] = QUALITY_CHECKLIST["has_timeliness"]["weight"] if has_timeliness else 5

    # 总分
    score = sum(detail_scores.values())
    score = min(100, max(0, int(score)))

    # 有价值判断：总分 >= 50 且至少满足 checklist 中的 2 项
    met_count = sum(1 for v in checklist.values() if v)
    is_valuable = score >= 50 and met_count >= 2

    reasons = []
    if not has_quant:
        reasons.append("无量化数据")
    if not has_supply and not has_demand:
        reasons.append("缺少供需驱动信息")
    if not has_direction:
        reasons.append("无价格方向判断")
    if score < 50:
        reasons.append(f"总分{score}<50")

    return {
        "is_valuable": is_valuable,
        "score": score,
        "checklist": checklist,
        "detail_scores": detail_scores,
        "met_count": met_count,
        "reason": " | ".join(reasons) if reasons else "有价值",
    }


def filter_reports(reports: list, min_score: int = 50, min_met_count: int = 2) -> list:
    """
    批量过滤研报列表。

    Args:
        reports: [{"text": str, "source": str, "time": str, ...}, ...]
        min_score: 最低质量分数
        min_met_count: 最少满足的checklist项数

    Returns:
        过滤后的有价值研报列表（每个条目增加 quality 字段）
    """
    filtered = []
    for report in reports:
        text = report.get("text", "") or report.get("content", "")
        if not isinstance(text, str):
            text = str(text)
        quality = parse_report_quality(text)
        report["quality"] = quality
        if quality["is_valuable"] and quality["score"] >= min_score and quality["met_count"] >= min_met_count:
            filtered.append(report)
    return filtered


# ─── B-Standard: 蒸馏模型框架 ──────────────────────────────


def auto_label_reports(reports: list, score_threshold: int = 60, driver_threshold: int = 1) -> list:
    """
    自动标注训练数据：基于现有五层打分逻辑生成弱标签。

    这是 B-Standard 的核心——无需人工标注。

    Args:
        reports: 历史研报列表 [{"text": str, "score_5layer": int, "driver_id": int, ...}, ...]
        score_threshold: 五层打分总评分阈值
        driver_threshold: 主驱动识别标志（>0表示触发了主驱动）

    Returns:
        [{"text": str, "label": 1/0, "score": int, ...}, ...]
    """
    labeled = []
    for report in reports:
        text = report.get("text", "") or report.get("content", "")
        if not isinstance(text, str):
            text = str(text)

        # 使用规则评分作为弱监督信号
        quality = parse_report_quality(text)

        # 高价值：五层打分>阈值 且 触发主驱动 且 规则评分也高
        score_5layer = report.get("score_5layer", report.get("total_score", 0))
        driver_id = report.get("driver_id", report.get("main_driver", 0))

        is_high_value = (
            score_5layer >= score_threshold
            and (driver_id >= driver_threshold if isinstance(driver_id, (int, float)) else True)
            and quality["score"] >= 50
        )

        labeled.append(
            {
                "text": text[:2000],  # 截断过长文本
                "label": 1 if is_high_value else 0,
                "score_5layer": score_5layer,
                "quality_score": quality["score"],
                "driver_id": driver_id,
                "text_length": len(text),
            }
        )

    return labeled


# ─── 部署工具 ──────────────────────────────────────────────


def integrate_filter_into_pipeline(input_path: str, output_path: str = None, min_score: int = 50) -> dict:
    """
    集成过滤器到数据采集流程。

    Args:
        input_path: 研报JSON文件路径
        output_path: 输出路径（None时覆盖输入文件）
        min_score: 最低质量分数

    Returns:
        过滤统计
    """
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reports = data if isinstance(data, list) else data.get("reports", data.get("items", [data]))
    original_count = len(reports)

    filtered = filter_reports(reports, min_score=min_score)
    filtered_count = len(filtered)

    result = {
        "original_count": original_count,
        "filtered_count": filtered_count,
        "removed_count": original_count - filtered_count,
        "removal_rate": round((original_count - filtered_count) / max(1, original_count) * 100, 1),
        "output_path": output_path or input_path,
    }

    out_path = output_path or input_path
    # 只保留过滤后的+quality字段
    output_data = data
    if isinstance(output_data, list):
        output_data = filtered
    else:
        output_data["reports"] = filtered
        output_data["_filter"] = result

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"研报过滤: {original_count} → {filtered_count} ({result['removal_rate']}% 移除)")
    return result
