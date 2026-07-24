"""运行报告 [INDEPENDENT]。

跨阶段累加指标，``flush`` 写 ``reports/run_report_{date}.json``（同一天多次运行合并）。

字段（取数失败一律置 null，不抛错）：
    run_id / start_ts / end_ts / phase / n_symbols_scanned / n_signals
    n_triggered_debates / per_validator_demotions / source_health / errors[]
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

__all__ = ["RunReporter"]


def _root() -> Path:
    return Path(__file__).resolve().parents[1]  # scripts -> root


class RunReporter:
    def __init__(self, run_id: str | None = None, reports_dir: str | None = None) -> None:
        self._date = date.today().strftime("%Y-%m-%d")
        self._reports_dir = Path(reports_dir) if reports_dir else (_root() / "reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._reports_dir / f"run_report_{self._date}.json"
        self._run_id = run_id or f"FDT_{self._date}"
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {
            "run_id": self._run_id,
            "date": self._date,
            "start_ts": datetime.now().isoformat(timespec="seconds"),
            "end_ts": None,
            "phases": {},
            "n_symbols_scanned": None,
            "n_signals": None,
            "n_triggered_debates": None,
            "per_validator_demotions": None,
            "source_health": None,
            "errors": [],
        }

    def mark_phase(self, phase: str, duration_s: float | None = None) -> None:
        self._data.setdefault("phases", {})[phase] = {
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "duration_s": duration_s,
        }

    def set(self, **kwargs) -> None:
        for k, v in kwargs.items():
            self._data[k] = v

    def add_error(self, stage: str, msg: str) -> None:
        self._data.setdefault("errors", []).append({
            "stage": stage,
            "msg": str(msg),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })

    def flush(self) -> None:
        self._data["end_ts"] = datetime.now().isoformat(timespec="seconds")
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass  # 报告写入失败绝不阻断主流程

    @property
    def path(self) -> Path:
        return self._path
