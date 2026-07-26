"""Phase 3: 拓扑自演化 — 条件委派路径 + A/B 测试基础设施。

MASE 慢环（结构演化）的核心组件：
1. 代码规则引擎 decide_path() — 基于信号一致性/波动率/历史准确率选择辩论路径
2. A/B 测试追踪器 — 比较不同拓扑配置的性能

安全门禁（Endure）：
- 拓扑变更必须经过 A/B 测试（各 N=20 轮）
- 每次只变一个维度
- 有回滚预案（代码版本标签）
- 金丝雀先行（1-2 品种 → 全品种）
- Endure 不妥协（止损/仓位/风控在任何拓扑下最后执行）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── 路径定义 ──
DebatePath = Literal["fast_path", "standard_path", "full_debate"]

# ── 路径描述 ──
PATH_DESCRIPTIONS: dict[DebatePath, str] = {
    "fast_path": "快速路径：跳过 P2 部分冗余分析，直接进入 P4 裁决",
    "standard_path": "标准路径：P1→P1.5→P2→P3→P3.5→P4→P5 完整辩论",
    "full_debate": "完整辩论：标准路径 + 强制 P3.5 介入 + 副判官独立裁决",
}

# ── A/B 测试配置 ──
AB_MIN_SAMPLES = 20        # 每臂最少样本数
AB_SIGNIFICANCE = 0.10     # p < 0.10 显著性阈值


# ── 拓扑规则引擎 ──


def decide_path(
    signal_agreement_score: float,
    volatility_regime: str,
    history_accuracy: float,
) -> DebatePath:
    """基于信号一致性、波动率和历史准确率选择辩论路径。

    Args:
        signal_agreement_score: P1 与 P1.5 的结论一致性（0-1）。
            1.0 = 完全一致，0.0 = 完全冲突。
        volatility_regime: 市场波动状态 — "low" / "medium" / "high"。
        history_accuracy: 该品种近期裁决准确率（0-1）。

    Returns:
        DebatePath: "fast_path" / "standard_path" / "full_debate"

    决策逻辑（代码规则，无 LLM 参与）:
        fast_path: 信号一致(>0.8) + 低波动 + 历史准确率>0.65
        full_debate: 信号冲突(<0.4) 或 高波动市场
        standard_path: 其他情况
    """
    # ── 参数门槛校验 ──
    if not 0 <= signal_agreement_score <= 1:
        logger.warning("[Topology] signal_agreement_score=%.2f 越界，钳制到[0,1]", signal_agreement_score)
        signal_agreement_score = max(0.0, min(1.0, signal_agreement_score))

    if not 0 <= history_accuracy <= 1:
        logger.warning("[Topology] history_accuracy=%.2f 越界，钳制到[0,1]", history_accuracy)
        history_accuracy = max(0.0, min(1.0, history_accuracy))

    # ── 决策 ──
    # 信号高度一致 + 低波动 + 历史准确 → 快速路径
    if (signal_agreement_score > 0.8
            and volatility_regime == "low"
            and history_accuracy > 0.65):
        logger.info("[Topology] → fast_path (agreement=%.2f, vol=%s, acc=%.2f)",
                    signal_agreement_score, volatility_regime, history_accuracy)
        return "fast_path"

    # 信号冲突严重 或 高波动 → 完整辩论
    if signal_agreement_score < 0.4 or volatility_regime == "high":
        logger.info("[Topology] → full_debate (agreement=%.2f, vol=%s, acc=%.2f)",
                    signal_agreement_score, volatility_regime, history_accuracy)
        return "full_debate"

    # 其他 → 标准路径
    logger.info("[Topology] → standard_path (agreement=%.2f, vol=%s, acc=%.2f)",
                signal_agreement_score, volatility_regime, history_accuracy)
    return "standard_path"


def get_path_description(path: DebatePath) -> str:
    """获取路径描述文本（用于注入 Agent 上下文）。"""
    return PATH_DESCRIPTIONS.get(path, "未知路径")


# ── A/B 测试追踪 ──


class ABTestTracker:
    """A/B 测试追踪器 — 比较不同拓扑配置的性能。

    存储每次辩论的路径分配 + 结果指标，
    用于在不同配置间做统计比较。

    Usage:
        tracker = ABTestTracker()
        tracker.record_round("config_A", "fast_path", accuracy=0.8, tokens=15000)
        tracker.record_round("config_B", "standard_path", accuracy=0.75, tokens=20000)
        result = tracker.compare("config_A", "config_B")
    """

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self._rounds: list[dict[str, Any]] = []
        self._load()

    def record_round(
        self,
        config_label: str,
        path: DebatePath,
        accuracy: float | None = None,
        tokens: int | None = None,
        latency_ms: float | None = None,
        symbols: list[str] | None = None,
        trace_id: str = "",
    ) -> None:
        """记录一轮辩论的路径分配和结果指标。

        Args:
            config_label: 配置标签（如 "config_A", "config_B"）
            path: 分配的路径
            accuracy: 该轮的准确率（0-1，None 表示尚未验证）
            tokens: 消耗 token 数
            latency_ms: 延迟（毫秒）
            symbols: 品种列表
            trace_id: 追踪 ID
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": config_label,
            "path": path,
            "accuracy": accuracy,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "symbols": symbols or [],
            "trace_id": trace_id,
        }
        self._rounds.append(entry)
        logger.debug("[ABTest] %s | %s recorded (n=%d)", config_label, path, len(self._rounds))

    def compare(self, config_a: str, config_b: str) -> dict[str, Any]:
        """比较两个配置的性能（描述性统计，暂不包含显著性检验）。

        Args:
            config_a: 第一个配置标签
            config_b: 第二个配置标签

        Returns:
            {
                "config_a": {"label": str, "n": int, ...stats},
                "config_b": {"label": str, "n": int, ...stats},
                "winner": "config_a" | "config_b" | "tie" | "insufficient_data",
            }
        """
        rounds_a = [r for r in self._rounds if r.get("config") == config_a]
        rounds_b = [r for r in self._rounds if r.get("config") == config_b]

        # ── 样本量检查 ──
        if len(rounds_a) < AB_MIN_SAMPLES or len(rounds_b) < AB_MIN_SAMPLES:
            return {
                "config_a": self._stats(rounds_a),
                "config_b": self._stats(rounds_b),
                "winner": "insufficient_data",
                "message": f"至少需要 {AB_MIN_SAMPLES} 样本/臂 (A={len(rounds_a)}, B={len(rounds_b)})",
            }

        # ── 统计汇总 ──
        stats_a = self._stats(rounds_a)
        stats_b = self._stats(rounds_b)

        # ── 简单胜出规则 ──
        winner: str = "tie"
        acc_a = stats_a.get("avg_accuracy", 0) or 0
        acc_b = stats_b.get("avg_accuracy", 0) or 0
        cost_a = stats_a.get("avg_tokens", float("inf")) or float("inf")
        cost_b = stats_b.get("avg_tokens", float("inf")) or float("inf")

        # 非劣性 + 成本优势
        if acc_a >= acc_b - 0.05 and cost_a < cost_b * 0.9:
            winner = config_a
        elif acc_b >= acc_a - 0.05 and cost_b < cost_a * 0.9:
            winner = config_b
        elif acc_a > acc_b + 0.03:
            winner = config_a
        elif acc_b > acc_a + 0.03:
            winner = config_b

        logger.info(
            "[ABTest] %s(acc=%.3f,cost=%.0f) vs %s(acc=%.3f,cost=%.0f) → %s",
            config_a, acc_a, cost_a,
            config_b, acc_b, cost_b,
            winner,
        )

        return {
            "config_a": stats_a,
            "config_b": stats_b,
            "winner": winner,
            "message": f"{config_a}: acc={acc_a:.3f}, cost={cost_a:.0f} | "
                       f"{config_b}: acc={acc_b:.3f}, cost={cost_b:.0f} → {winner}",
        }

    def save(self) -> bool:
        """持久化 A/B 测试记录。"""
        try:
            path = self.project_root / "memory" / "evolution" / "ab_test_rounds.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._rounds, f, ensure_ascii=False, indent=2)
            logger.info("[ABTest] 已保存 %d 轮记录", len(self._rounds))
            return True
        except Exception as e:
            logger.warning("[ABTest] 保存失败: %s", e)
            return False

    def get_rounds(
        self,
        config: str = "",
        path: DebatePath | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询 A/B 测试记录。"""
        result = list(self._rounds)
        if config:
            result = [r for r in result if r.get("config") == config]
        if path:
            result = [r for r in result if r.get("path") == path]
        return result[-limit:]

    # ── 内部方法 ──

    @staticmethod
    def _stats(rounds: list[dict]) -> dict[str, Any]:
        """计算一轮记录的描述性统计。"""
        n = len(rounds)
        if n == 0:
            return {"label": "", "n": 0}

        accuracies = [r.get("accuracy") for r in rounds if r.get("accuracy") is not None]
        tokens_list = [r.get("tokens") for r in rounds if r.get("tokens") is not None]
        latencies = [r.get("latency_ms") for r in rounds if r.get("latency_ms") is not None]

        path_counts: dict[str, int] = {}
        for r in rounds:
            p = r.get("path", "unknown")
            path_counts[p] = path_counts.get(p, 0) + 1

        return {
            "n": n,
            "path_distribution": path_counts,
            "avg_accuracy": sum(accuracies) / len(accuracies) if accuracies else None,
            "avg_tokens": int(sum(tokens_list) / len(tokens_list)) if tokens_list else None,
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
            "path_accuracy": {
                p: sum(
                    1 for r in rounds
                    if r.get("path") == p and r.get("accuracy") is not None and r.get("accuracy", 0) > 0.5
                ) / max(sum(1 for r in rounds if r.get("path") == p), 1)
                for p in set(path_counts.keys())
            },
        }

    def _load(self) -> None:
        """从文件加载历史记录。"""
        path = self.project_root / "memory" / "evolution" / "ab_test_rounds.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._rounds = data
            except Exception as e:
                logger.debug("[ABTest] 加载失败: %s", e)
