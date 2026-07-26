"""Phase 2b: Prompt 权重自调整 — 代码控制的参数微调。

MASE 中环（经验反馈）的权重调整组件：
基于偏差检测结果自动调整 Agent Prompt 内部权重参数。
所有权重调整由代码硬约束边界，LLM 无权触碰。

安全门禁（Endure）：
1. 每个参数有 [min, max] 代码硬边界
2. 单次调整 ≤ adjustment_step
3. 累计调整 ±0.1 后自动冻结
4. 调整后需 Pass^3 验证（连续 3 次测试通过）
5. 完整调整历史支持精确回滚
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Agent 权重参数 Schema ─────────────────────────────
# 每个 Agent 的可调权重参数定义
# key: agent_name → {param_name: {"value": float, "min": float, "max": float, "step": float}}

_AGENT_WEIGHT_SCHEMA: dict[str, dict[str, dict[str, float]]] = {
    "technical_researcher": {
        "trend_weight": {"value": 0.30, "min": 0.20, "max": 0.40, "step": 0.02},
        "volume_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "structure_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "momentum_weight": {"value": 0.20, "min": 0.10, "max": 0.30, "step": 0.02},
    },
    "fundamental_researcher": {
        "supply_demand_weight": {"value": 0.35, "min": 0.25, "max": 0.45, "step": 0.02},
        "inventory_weight": {"value": 0.30, "min": 0.20, "max": 0.40, "step": 0.02},
        "macro_weight": {"value": 0.20, "min": 0.10, "max": 0.30, "step": 0.02},
        "sentiment_weight": {"value": 0.15, "min": 0.05, "max": 0.25, "step": 0.02},
    },
    "judge": {
        "technical_evidence_weight": {"value": 0.35, "min": 0.25, "max": 0.45, "step": 0.02},
        "fundamental_evidence_weight": {"value": 0.35, "min": 0.25, "max": 0.45, "step": 0.02},
        "debate_quality_weight": {"value": 0.30, "min": 0.20, "max": 0.40, "step": 0.02},
    },
    "bullish_analyst": {
        "trend_argument_weight": {"value": 0.30, "min": 0.20, "max": 0.40, "step": 0.02},
        "valuation_argument_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "catalyst_argument_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "risk_awareness_weight": {"value": 0.20, "min": 0.10, "max": 0.30, "step": 0.02},
    },
    "bearish_analyst": {
        "trend_argument_weight": {"value": 0.30, "min": 0.20, "max": 0.40, "step": 0.02},
        "valuation_argument_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "catalyst_argument_weight": {"value": 0.25, "min": 0.15, "max": 0.35, "step": 0.02},
        "risk_awareness_weight": {"value": 0.20, "min": 0.10, "max": 0.30, "step": 0.02},
    },
}

# ── 冻结阈值 ──
MAX_CUMULATIVE_ADJUSTMENT = 0.10  # 任一参数累计调整超此值后冻结
FROZEN_WEIGHTS_FILE = "memory/evolution/frozen_weights.json"
HISTORY_FILE = "memory/evolution/weight_adjustment_history.jsonl"


class WeightAdjuster:
    """权重自调整器 — 代码控制的 Agent Prompt 权重参数微调。

    Usage:
        wa = WeightAdjuster()
        wa.adjust("technical_researcher", "trend_weight", -0.02,
                  reason="过度依赖趋势判断导致多次偏差")
        wa.adjust("judge", "debate_quality_weight", +0.02,
                  reason="辩论质量权重偏低导致裁决偏差")
        wa.save()

        for adjustment in wa.get_history(agent="technical_researcher"):
            print(adjustment)
    """

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.weights: dict[str, dict[str, dict[str, float]]] = deepcopy(_AGENT_WEIGHT_SCHEMA)
        self.history: list[dict[str, Any]] = []
        self.frozen_params: dict[str, list[str]] = {}  # agent → [param_name, ...]

        self._load_history()
        self._load_frozen()

    # ═══════════════════════════════════════════════════
    # 核心 API
    # ═══════════════════════════════════════════════════

    def adjust(
        self,
        agent_name: str,
        param_name: str,
        delta: float,
        reason: str = "",
    ) -> dict[str, Any]:
        """调整指定 Agent 的权重参数。

        Args:
            agent_name: Agent 名称（如 "technical_researcher"）
            param_name: 参数名称（如 "trend_weight"）
            delta: 调整量（如 -0.02）
            reason: 调整理由

        Returns:
            {"success": bool, "message": str, "new_value": float}

        约束（由代码硬执行）:
            - 冻结的参数不可调整
            - delta 不得超过 param.step
            - 新值不得超出 [min, max]
            - 累计调整超过 MAX_CUMULATIVE_ADJUSTMENT 后冻结
        """
        # ── 校验 Agent 存在 ──
        if agent_name not in self.weights:
            return {"success": False, "message": f"未知 Agent: {agent_name}", "new_value": None}

        # ── 校验参数存在 ──
        params = self.weights[agent_name]
        if param_name not in params:
            return {"success": False, "message": f"未知参数 {agent_name}.{param_name}", "new_value": None}

        param = params[param_name]
        current = param["value"]

        # ── 检查冻结状态 ──
        frozen_list = self.frozen_params.get(agent_name, [])
        if param_name in frozen_list:
            logger.warning("[WeightAdj] %s.%s 已冻结，拒绝调整", agent_name, param_name)
            return {
                "success": False,
                "message": f"{agent_name}.{param_name} 已冻结（累计调整超{MAX_CUMULATIVE_ADJUSTMENT}）",
                "new_value": current,
            }

        # ── 检查单步步长 ──
        max_step = param["step"]
        if abs(delta) > max_step:
            logger.warning("[WeightAdj] %s.%s delta=%.3f 超步长 %.3f",
                           agent_name, param_name, delta, max_step)
            return {"success": False, "message": f"调整量 {delta} 超步长 {max_step}", "new_value": current}

        # ── 计算新值并钳制 ──
        new_value = round(current + delta, 4)
        new_value = max(param["min"], min(param["max"], new_value))

        # ── 记录调整历史 ──
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent_name,
            "param": param_name,
            "prev_value": current,
            "new_value": new_value,
            "delta": round(new_value - current, 4),
            "reason": reason,
        }
        self.history.append(entry)

        # ── 应用 ──
        self.weights[agent_name][param_name]["value"] = new_value
        logger.info("[WeightAdj] %s.%s: %.4f → %.4f (%s)", agent_name, param_name, current, new_value, reason)

        # ── 检查累计调整是否超阈值 → 冻结 ──
        if self._check_freeze(agent_name, param_name):
            logger.warning("[WeightAdj] %s.%s 累计调整超%.2f，已自动冻结",
                           agent_name, param_name, MAX_CUMULATIVE_ADJUSTMENT)

        return {"success": True, "message": f"{agent_name}.{param_name}: {current} → {new_value}", "new_value": new_value}

    def batch_adjust(
        self,
        deviations: list[dict],
        deviation_to_adjustments: dict[str, list[tuple[str, float, str]]] | None = None,
    ) -> list[dict[str, Any]]:
        """基于偏差列表批量调整权重。

        Args:
            deviations: 偏差检测结果（含 category 字段）
            deviation_to_adjustments: 可选，偏差分类→调整列表的映射。
                默认映射:
                  - "weight_misallocation" → judge.debate_quality_weight +0.02
                  - "logical_flaw" → technical_researcher.trend_weight +0.02
                  - "sentiment_miss" → fundamental_researcher.sentiment_weight +0.02

        Returns:
            每次 adjust() 的结果列表。
        """
        mapping = deviation_to_adjustments or {
            "weight_misallocation": [
                ("judge", "debate_quality_weight", +0.02, "裁决权重偏差→增加辩论质量权重"),
            ],
            "logical_flaw": [
                ("technical_researcher", "trend_weight", +0.02,
                 "逻辑缺陷偏差→增加趋势分析权重"),
                ("fundamental_researcher", "supply_demand_weight", +0.02,
                 "逻辑缺陷偏差→增加供需分析权重"),
            ],
            "sentiment_miss": [
                ("fundamental_researcher", "sentiment_weight", +0.02,
                 "情绪偏差→增加情绪分析权重"),
            ],
            "data_error": [
                ("technical_researcher", "volume_weight", +0.02,
                 "数据误差偏差→增加量能验证权重"),
            ],
        }

        results: list[dict[str, Any]] = []
        for dev in deviations:
            cat = dev.get("category", "")
            adjustments = mapping.get(cat, [])
            for agent, param, delta, reason in adjustments:
                result = self.adjust(agent, param, delta, reason)
                results.append(result)

        return results

    def save(self) -> bool:
        """持久化权重和调整历史到文件。"""
        try:
            # 保存权重
            weights_file = self.project_root / "memory" / "evolution" / "weights.json"
            weights_file.parent.mkdir(parents=True, exist_ok=True)
            with open(weights_file, "w", encoding="utf-8") as f:
                json.dump(self.weights, f, ensure_ascii=False, indent=2)

            # 追加历史
            if self.history:
                hist_file = self.project_root / HISTORY_FILE
                hist_file.parent.mkdir(parents=True, exist_ok=True)
                with open(hist_file, "a", encoding="utf-8") as f:
                    for entry in self.history:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # 保存冻结状态
            frozen_file = self.project_root / FROZEN_WEIGHTS_FILE
            with open(frozen_file, "w", encoding="utf-8") as f:
                json.dump(self.frozen_params, f, ensure_ascii=False, indent=2)

            logger.info("[WeightAdj] 已保存 weights + history + frozen")
            return True
        except Exception as e:
            logger.warning("[WeightAdj] 保存失败: %s", e)
            return False

    def get_history(
        self,
        agent: str = "",
        param: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询调整历史。"""
        result = list(self.history)
        if agent:
            result = [e for e in result if e.get("agent") == agent]
        if param:
            result = [e for e in result if e.get("param") == param]
        return result[-limit:]

    def get_weights_prompt_block(self, agent_name: str) -> str:
        """生成注入到 Agent Prompt 中的权重配置块。

        返回格式：
        【权重配置（代码控制）】
        - trend_weight: 0.30 [边界: 0.20-0.40]
        - volume_weight: 0.25 [边界: 0.15-0.35]
        ...
        """
        params = self.weights.get(agent_name)
        if not params:
            return ""

        lines = ["\n【权重配置（代码控制）】"]
        for pname, pconf in params.items():
            lines.append(
                f"- {pname}: {pconf['value']:.2f} [边界: {pconf['min']:.2f}-{pconf['max']:.2f}]"
            )
        return "\n".join(lines)

    def rollback(self, entry_index: int) -> bool:
        """回滚到指定历史版本（根据 entry 在 history 中的索引）。

        Args:
            entry_index: history 列表中的索引（0 = 最早）

        Returns:
            是否成功回滚
        """
        if entry_index < 0 or entry_index >= len(self.history):
            return False

        entry = self.history[entry_index]
        agent = entry["agent"]
        param_name = entry["param"]
        prev_value = entry["prev_value"]

        if agent not in self.weights or param_name not in self.weights[agent]:
            return False

        # 直接设回旧值（跳过 step 检查 — 回滚不受步长限制）
        self.weights[agent][param_name]["value"] = prev_value

        rollback_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "param": param_name,
            "prev_value": entry["new_value"],
            "new_value": prev_value,
            "delta": round(prev_value - entry["new_value"], 4),
            "reason": f"回滚到调整#{entry_index}之前的值: {entry.get('reason', '')}",
            "rollback_of_index": entry_index,
        }
        self.history.append(rollback_entry)
        logger.info("[WeightAdj] 回滚 %s.%s → %.4f (调整#%d)", agent, param_name, prev_value, entry_index)
        return True

    def get_status(self) -> dict[str, Any]:
        """获取当前权重调整系统的状态摘要。"""
        total_adjustments = len(self.history)
        frozen_count = sum(len(v) for v in self.frozen_params.values())
        return {
            "agents": list(self.weights.keys()),
            "total_adjustments": total_adjustments,
            "frozen_params_count": frozen_count,
            "frozen_params": dict(self.frozen_params),
            "last_adjustment": self.history[-1] if self.history else None,
        }

    # ═══════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════

    def _check_freeze(self, agent: str, param_name: str) -> bool:
        """检查累计调整是否超阈值，是则冻结。"""
        adjustments = [
            e for e in self.history
            if e.get("agent") == agent and e.get("param") == param_name
               and "rollback_of_index" not in e  # 排除回滚记录
        ]
        cumulative = sum(abs(e.get("delta", 0)) for e in adjustments)
        if cumulative >= MAX_CUMULATIVE_ADJUSTMENT:
            if agent not in self.frozen_params:
                self.frozen_params[agent] = []
            if param_name not in self.frozen_params[agent]:
                self.frozen_params[agent].append(param_name)
            return True
        return False

    def _load_history(self) -> None:
        """从文件加载历史记录。"""
        hist_file = self.project_root / HISTORY_FILE
        if hist_file.exists():
            try:
                with open(hist_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.history.append(json.loads(line))
            except Exception as e:
                logger.debug("[WeightAdj] 历史加载失败: %s", e)

    def _load_frozen(self) -> None:
        """从文件加载已冻结参数。"""
        frozen_file = self.project_root / FROZEN_WEIGHTS_FILE
        if frozen_file.exists():
            try:
                with open(frozen_file, "r", encoding="utf-8") as f:
                    self.frozen_params = json.load(f)
            except Exception as e:
                logger.debug("[WeightAdj] 冻结状态加载失败: %s", e)
