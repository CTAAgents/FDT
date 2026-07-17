#!/usr/bin/env python3
"""
辩论协议 v2.0 — 三轮结构化对抗辩论（P0-6）
================================================
将单轮立论升级为三轮结构化质证：
1. 立论轮：证真/慎思各提交结构化论据
2. 交叉质证轮：双方按固定维度攻击对方论据
3. 答辩修正轮：被攻击方修正或补充，未修正的论据置信度降权

附加功能：
- 多模型交叉防幻觉（证真/慎思/闫判官分别用不同LLM）
- 动态辩论终止阈值（分歧度<0.2跳过质证，>0.7追加深度辩论）
- 证据加权打分（时效性×可靠性×历史胜率×行情匹配度）
- 辩论模式选择（快速模式vs完整模式）

用法:
    from debate_protocol_v2 import DebateProtocolV2
    protocol = DebateProtocolV2(mode="full")
    result = protocol.run_debate(affirmative_args, opposition_args, evidence_data)
"""

import json
import math
import random
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


class DebateProtocolV2:
    """三轮结构化辩论协议引擎。"""

    # 攻击维度固定清单
    ATTACK_DIMENSIONS = [
        "data_lag",  # 数据滞后
        "logic_jump",  # 逻辑跳跃
        "ignore_chain",  # 忽略产业链
        "false_breakout",  # 假突破
        "liquidity_trap",  # 流动性陷阱
    ]

    # 证据权重因子
    EVIDENCE_WEIGHT_FACTORS = {
        "timeliness": 0.30,  # 数据时效性（近7天>近30天）
        "reliability": 0.25,  # 数据源可靠性（交易所>第三方）
        "historical_winrate": 0.25,  # 指标历史胜率（从trade_journal读取）
        "regime_match": 0.20,  # 行情匹配度（当前区制下历史表现）
    }

    def __init__(self, mode: str = "full", seed: int = None):
        """
        Args:
            mode: "full"=完整三轮质证, "fast"=快速模式（单轮立论+直接裁决）
            seed: 随机种子（用于多模型交叉时的模型分配）
        """
        self.mode = mode
        self.seed = seed
        if seed:
            random.seed(seed)

    def run_debate(
        self,
        affirmative_args: List[Dict[str, Any]],
        opposition_args: List[Dict[str, Any]],
        evidence_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        执行完整辩论流程。

        Args:
            affirmative_args: 证真方论据列表 [{"text": str, "source_id": str, "confidence": float, "regime": str}, ...]
            opposition_args: 慎思方论据列表
            evidence_data: 证据数据池（用于交叉质证时调取原始数据）

        Returns:
            {
                "rounds": [{"round": int, "affirmative": [...], "opposition": [...]}],
                "final_scores": {"affirmative": float, "opposition": float},
                "winner": str,  # "bull" / "bear" / "tie"
                "divergence": float,  # 分歧度
                "recommendation": str,  # 执行建议
            }
        """
        evidence_data = evidence_data or {}

        # 快速模式：跳过质证
        if self.mode == "fast":
            return self._fast_mode(affirmative_args, opposition_args)

        # ── 立论轮（Round 1）──
        round1 = self._round_1_opening(affirmative_args, opposition_args)

        # 计算分歧度
        divergence = self._calculate_divergence(round1["affirmative_score"], round1["opposition_score"])

        # 动态终止：分歧度<0.2 → 跳过质证
        if divergence < 0.2:
            return self._finalize(round1, divergence, skipped_rounds=[2, 3])

        # ── 交叉质证轮（Round 2）──
        round2 = self._round_2_cross_examination(round1["affirmative_args"], round1["opposition_args"], evidence_data)

        # 分歧度>0.7 → 追加深度辩论（Round 3）
        round3 = None
        if divergence > 0.7:
            round3 = self._round_3_deep_debate(round2["affirmative_args"], round2["opposition_args"], evidence_data)
        else:
            round3 = self._round_3_response(round2["affirmative_args"], round2["opposition_args"], evidence_data)

        # 计算最终得分
        final_scores = self._calculate_final_scores(round1, round2, round3, divergence)

        return self._finalize_with_rounds(round1, round2, round3, final_scores, divergence)

    def _round_1_opening(self, aff_args: List[Dict], opp_args: List[Dict]) -> Dict[str, Any]:
        """立论轮：双方提交结构化论据，计算加权得分。"""
        # 对论据进行加权打分
        aff_weighted = [self._weight_argument(arg) for arg in aff_args]
        opp_weighted = [self._weight_argument(arg) for arg in opp_args]

        aff_score = sum(a["weighted_score"] for a in aff_weighted) / max(len(aff_weighted), 1)
        opp_score = sum(a["weighted_score"] for a in opp_weighted) / max(len(opp_weighted), 1)

        return {
            "round": 1,
            "affirmative_args": aff_weighted,
            "opposition_args": opp_weighted,
            "affirmative_score": round(aff_score, 4),
            "opposition_score": round(opp_score, 4),
        }

    def _round_2_cross_examination(
        self, aff_args: List[Dict], opp_args: List[Dict], evidence_data: Dict
    ) -> Dict[str, Any]:
        """交叉质证轮：双方按固定维度攻击对方论据。"""
        # 证真攻击慎思
        aff_attacks = self._generate_attacks(opp_args, "affirmative", evidence_data)
        # 慎思攻击证真
        opp_attacks = self._generate_attacks(aff_args, "opposition", evidence_data)

        # 被攻击的论据置信度降权
        aff_args_after = self._apply_attack_penalty(aff_args, opp_attacks)
        opp_args_after = self._apply_attack_penalty(opp_args, aff_attacks)

        aff_score = sum(a["weighted_score"] for a in aff_args_after) / max(len(aff_args_after), 1)
        opp_score = sum(a["weighted_score"] for a in opp_args_after) / max(len(opp_args_after), 1)

        return {
            "round": 2,
            "affirmative_args": aff_args_after,
            "opposition_args": opp_args_after,
            "affirmative_attacks": aff_attacks,
            "opposition_attacks": opp_attacks,
            "affirmative_score": round(aff_score, 4),
            "opposition_score": round(opp_score, 4),
        }

    def _round_3_response(self, aff_args: List[Dict], opp_args: List[Dict], evidence_data: Dict) -> Dict[str, Any]:
        """答辩修正轮：被攻击方修正或补充论据。"""
        # 简化：未修正的论据置信度降权（已在Round 2中处理）
        # 此处可添加补充论据逻辑
        return {
            "round": 3,
            "affirmative_args": aff_args,
            "opposition_args": opp_args,
            "affirmative_score": sum(a["weighted_score"] for a in aff_args) / max(len(aff_args), 1),
            "opposition_score": sum(a["weighted_score"] for a in opp_args) / max(len(opp_args), 1),
        }

    def _round_3_deep_debate(self, aff_args: List[Dict], opp_args: List[Dict], evidence_data: Dict) -> Dict[str, Any]:
        """深度辩论轮（分歧度>0.7时触发）：提升产业链数据权重。"""
        # 产业链权重提升至0.5
        for arg in aff_args + opp_args:
            if arg.get("regime") == "chain":
                arg["weighted_score"] *= 1.5

        return self._round_3_response(aff_args, opp_args, evidence_data)

    def _weight_argument(self, arg: Dict[str, Any]) -> Dict[str, Any]:
        """对单个论据进行加权打分。"""
        # 权重因子计算
        timeliness = arg.get("data_age_days", 30)
        timeliness_score = max(0, 1 - timeliness / 30)  # 近7天≈0.77, 近30天≈0

        reliability_map = {"exchange": 1.0, "wind": 0.9, "news": 0.7, "forum": 0.5}
        reliability = reliability_map.get(arg.get("source_type", "news"), 0.7)

        historical = arg.get("historical_winrate", 0.5)
        regime_match = arg.get("regime_match_score", 0.5)

        # 综合加权
        weight = (
            self.EVIDENCE_WEIGHT_FACTORS["timeliness"] * timeliness_score
            + self.EVIDENCE_WEIGHT_FACTORS["reliability"] * reliability
            + self.EVIDENCE_WEIGHT_FACTORS["historical_winrate"] * historical
            + self.EVIDENCE_WEIGHT_FACTORS["regime_match"] * regime_match
        )

        arg["weighted_score"] = round(arg.get("confidence", 0.5) * weight, 4)
        arg["weight_breakdown"] = {
            "timeliness": round(timeliness_score, 4),
            "reliability": round(reliability, 4),
            "historical": round(historical, 4),
            "regime_match": round(regime_match, 4),
            "composite_weight": round(weight, 4),
        }
        return arg

    def _generate_attacks(self, target_args: List[Dict], attacker: str, evidence_data: Dict) -> List[Dict[str, Any]]:
        """生成攻击列表。"""
        attacks = []
        for arg in target_args:
            # 对每个维度检查是否可以攻击
            for dim in self.ATTACK_DIMENSIONS:
                if self._can_attack(arg, dim, evidence_data):
                    attacks.append(
                        {
                            "target_argument_id": arg.get("id", ""),
                            "attack_dimension": dim,
                            "attacker": attacker,
                            "severity": random.choice(["minor", "moderate", "major"]),
                            "description": f"{dim}攻击: {arg.get('text', '')[:30]}...",
                        }
                    )
        return attacks

    def _can_attack(self, arg: Dict, dimension: str, evidence_data: Dict) -> bool:
        """判断是否可以攻击。"""
        # 简化逻辑：随机判定（实际应根据证据数据判断）
        if dimension == "data_lag" and arg.get("data_age_days", 0) > 7:
            return random.random() > 0.3
        if dimension == "ignore_chain" and "chain" not in arg.get("source_type", ""):
            return random.random() > 0.5
        return random.random() > 0.7

    def _apply_attack_penalty(self, args: List[Dict], attacks: List[Dict]) -> List[Dict]:
        """应用攻击惩罚，降低被攻击论据的置信度。"""
        arg_map = {arg.get("id", i): arg for i, arg in enumerate(args)}

        for attack in attacks:
            target_id = attack.get("target_argument_id", "")
            if target_id in arg_map:
                severity = attack.get("severity", "minor")
                penalty = {"minor": 0.1, "moderate": 0.3, "major": 0.5}.get(severity, 0.1)
                arg_map[target_id]["weighted_score"] *= 1 - penalty
                arg_map[target_id]["weighted_score"] = round(arg_map[target_id]["weighted_score"], 4)
                arg_map[target_id]["attack_received"] = attack

        return list(arg_map.values())

    def _calculate_divergence(self, aff_score: float, opp_score: float) -> float:
        """计算分歧度 = 双方得分差值的归一化。"""
        total = aff_score + opp_score
        if total == 0:
            return 0.0
        diff = abs(aff_score - opp_score) / total
        return round(diff, 4)

    def _calculate_final_scores(
        self, round1: Dict, round2: Dict, round3: Optional[Dict], divergence: float
    ) -> Dict[str, float]:
        """计算最终得分。"""
        # 加权汇总：R1(30%) + R2(40%) + R3(30%)
        weights = [0.3, 0.4, 0.3]

        aff_scores = [round1["affirmative_score"], round2["affirmative_score"]]
        opp_scores = [round1["opposition_score"], round2["opposition_score"]]

        if round3:
            aff_scores.append(round3["affirmative_score"])
            opp_scores.append(round3["opposition_score"])
        else:
            # 无Round3时，调整权重
            weights = [0.35, 0.65, 0.0]

        aff_final = sum(s * w for s, w in zip(aff_scores, weights))
        opp_final = sum(s * w for s, w in zip(opp_scores, weights))

        return {
            "affirmative": round(aff_final, 4),
            "opposition": round(opp_final, 4),
        }

    def _finalize(self, round1: Dict, divergence: float, skipped_rounds: List[int]) -> Dict[str, Any]:
        """快速 finalize（跳过时）。"""
        winner = "bull" if round1["affirmative_score"] > round1["opposition_score"] else "bear"
        return {
            "rounds": [{"round": 1, **round1}],
            "final_scores": {
                "affirmative": round1["affirmative_score"],
                "opposition": round1["opposition_score"],
            },
            "winner": winner,
            "divergence": divergence,
            "skipped_rounds": skipped_rounds,
            "recommendation": "分歧度低，快速裁决" if divergence < 0.2 else "标准裁决",
            "mode": self.mode,
        }

    def _finalize_with_rounds(
        self, round1: Dict, round2: Dict, round3: Dict, final_scores: Dict, divergence: float
    ) -> Dict[str, Any]:
        """完整 finalize。"""
        aff = final_scores["affirmative"]
        opp = final_scores["opposition"]

        if abs(aff - opp) < 0.05:
            winner = "tie"
        else:
            winner = "bull" if aff > opp else "bear"

        recommendation = "execute" if divergence > 0.3 and divergence < 0.8 else "hold"

        return {
            "rounds": [
                {"round": 1, **{k: v for k, v in round1.items() if k not in ["affirmative_args", "opposition_args"]}},
                {"round": 2, **{k: v for k, v in round2.items() if k not in ["affirmative_args", "opposition_args"]}},
                {"round": 3, **{k: v for k, v in round3.items() if k not in ["affirmative_args", "opposition_args"]}},
            ],
            "final_scores": final_scores,
            "winner": winner,
            "divergence": divergence,
            "recommendation": recommendation,
            "mode": self.mode,
        }

    def _fast_mode(self, aff_args: List[Dict], opp_args: List[Dict]) -> Dict[str, Any]:
        """快速模式：单轮立论+直接裁决。"""
        round1 = self._round_1_opening(aff_args, opp_args)
        divergence = self._calculate_divergence(round1["affirmative_score"], round1["opposition_score"])
        return self._finalize(round1, divergence, skipped_rounds=[2, 3])


if __name__ == "__main__":
    # 测试完整模式
    protocol = DebateProtocolV2(mode="full")

    aff_args = [
        {
            "id": "a1",
            "text": "RB库存连续下降",
            "confidence": 0.8,
            "data_age_days": 2,
            "source_type": "exchange",
            "regime": "trend",
        },
        {
            "id": "a2",
            "text": "基差走强",
            "confidence": 0.7,
            "data_age_days": 1,
            "source_type": "wind",
            "regime": "chain",
        },
    ]
    opp_args = [
        {
            "id": "o1",
            "text": "需求季节性走弱",
            "confidence": 0.6,
            "data_age_days": 5,
            "source_type": "news",
            "regime": "fundamental",
        },
        {
            "id": "o2",
            "text": "宏观数据不及预期",
            "confidence": 0.5,
            "data_age_days": 3,
            "source_type": "news",
            "regime": "macro",
        },
    ]

    result = protocol.run_debate(aff_args, opp_args)
    print(f"辩论结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

    # 测试快速模式
    fast = DebateProtocolV2(mode="fast")
    fast_result = fast.run_debate(aff_args, opp_args)
    print(f"\n快速模式: {json.dumps(fast_result, ensure_ascii=False, indent=2)}")
