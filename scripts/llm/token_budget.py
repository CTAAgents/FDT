"""LLM Token 预算追踪 [INDEPENDENT]。

- 日级用量持久化到 ``data/.llm_budget_{date}.json``。
- ``plan`` 阶段对每个 spawn prompt 计费：超 ``per_round`` 预警，超 ``daily`` 中止 plan 并报错。
- 估算用 ``len(chars)/2.5`` 粗估（中文+英文混合文本的 token 经验值），仅作预算护栏，
  非精确计数。

FDT 可控范围：run_debate 在产出 spawn 计划时对 prompt 计费；平台实际 token 消耗
取决于 spawn 时的模型，FDT 无法逐 token 计量，故为"计划期预估预算"。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

__all__ = ["TokenBudget", "BudgetExceeded"]


class BudgetExceeded(Exception):
    """日级 token 预算超限。"""


def _root() -> Path:
    return Path(__file__).resolve().parents[2]  # scripts/llm -> parents[2] = FDT 根


class TokenBudget:
    def __init__(
        self,
        per_round: int = 120000,
        daily: int = 1500000,
        data_dir: str | None = None,
    ) -> None:
        self.per_round = per_round
        self.daily = daily
        self._date = date.today().strftime("%Y-%m-%d")
        self._data_dir = Path(data_dir) if data_dir else (_root() / "data")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / f".llm_budget_{self._date}.json"
        self._used = self._load()

    def _load(self) -> int:
        try:
            if self._path.exists():
                d = json.loads(self._path.read_text(encoding="utf-8"))
                return int(d.get("used", 0))
        except Exception:
            pass
        return 0

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps({"date": self._date, "used": self._used,
                            "daily": self.daily}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def estimate(text: str) -> int:
        """粗估 token 数（字符数 / 2.5）。"""
        if not text:
            return 0
        return max(1, int(len(text) / 2.5))

    def consume(self, role: str, prompt: str) -> tuple[int, bool, bool]:
        """计费一次。返回 (预估token, 超per_round预警, 超daily中止)。

        超 daily 时抛 ``BudgetExceeded``（由调用方捕获并中止 plan）。
        """
        est = self.estimate(prompt)
        over_round = est > self.per_round
        if self._used + est > self.daily:
            self._used += est
            self._save()
            raise BudgetExceeded(
                f"[{role}] 日级 token 预算超限：已用 {self._used} + 本轮 {est} > 上限 {self.daily}"
            )
        self._used += est
        self._save()
        return est, over_round, False

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.daily - self._used)
