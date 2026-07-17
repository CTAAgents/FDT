#!/usr/bin/env python3
"""
情景分析 — 闫判官(交易参数职责)的Bull/Base/Bear推演工具
===========================================
为辩论输出方案增加三种情景的文字推演，避免"单一方向"的过度自信。
"""

import json


def generate_scenarios(base_plan: dict = None, market_data: dict = None) -> dict:
    """根据辩论判决生成三种情景的文字推演。

    Args:
        base_plan: 辩论最终方案（含品种、方向、仓位）
        market_data: 当前市场数据快照

    Returns:
        {bull_case, base_case, bear_case} 三个情景
    """
    if base_plan is None:
        base_plan = {}
    if market_data is None:
        market_data = {}

    direction = base_plan.get("direction", "做空")
    symbols = base_plan.get("symbols", [])
    position_pct = base_plan.get("total_position_pct", 20)

    # 方向反义
    opposite = "做多" if direction == "做空" else "做空"

    scenarios = {
        "bull_case": {
            "scenario": f"趋势加速，{direction}信号持续强化",
            "condition": f"ADX继续上升+资金持续流入{direction}方向+产业链验证一致",
            "pnl_est": f"{direction}方案按趋势运行，{len(symbols)}品种等权{direction}，目标盈利区间X%",
            "action": "持有至止盈或ADX衰减到30以下",
        },
        "base_case": {
            "scenario": f"基准路径，{direction}逻辑逐步兑现",
            "condition": "无重大宏观冲击，基本面边际变化符合预期",
            "pnl_est": f"{direction}方案分批次建仓，均价略优于市价，目标盈利区间半个X%",
            "action": "按止损止盈计划执行，不做额外调整",
        },
        "bear_case": {
            "scenario": f"逻辑失效，行情反向运行",
            "condition": f"突发宏观事件/政策转向/产业链断裂/{opposite}资金大规模进场",
            "pnl_est": f"单品种触发止损出场，总回撤约{position_pct}%×止损幅度的等效损失",
            "action": "触发止损后停止该品种交易，等待下一次辩论",
        },
    }

    return {
        "scenarios": scenarios,
        "base_plan_summary": f"{direction} {len(symbols)}品种 {position_pct}%仓位",
        "note": "情景分析为文字推演，不构成精确预估。分歧度越高的品种，情景差异应越大。",
    }


if __name__ == "__main__":
    # 测试
    plan = {
        "direction": "做空",
        "symbols": ["PK", "jd", "ec", "sn", "SF"],
        "total_position_pct": 25,
    }
    result = generate_scenarios(plan)
    print(json.dumps(result["scenarios"], indent=2, ensure_ascii=False)[:500])
    print(f"\n[OK] 情景分析通过")
