"""辩论结果缓存 [INDEPENDENT]。

- key = (symbol, date)，值 = 该品种已组装的裁决摘要。
- 持久化到 ``data/debate_cache_{date}.json``，带 timestamp。
- TTL 由调用方传入（默认读 settings.LLM_PROFILE_MAP 各角色 cache_ttl，统一 86400）。
- ``plan`` 阶段命中且未过期 → 跳过该品种 spawn，直接复用（同品种同日期不重辩）。
- 提供 ``--no-cache`` 强制重辩（调用方直接不查 / 清缓存）。

FDT 可控范围：缓存的是"已落盘的辩论产物"，平台 spawn 行为不受 FDT 控制，
故缓存是"跳过重辩"的优化而非"复用 LLM 响应"。
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

__all__ = ["DebateCache"]


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


class DebateCache:
    def __init__(self, ttl: int = 86400, data_dir: str | None = None) -> None:
        self.ttl = ttl
        self._date = date.today().strftime("%Y-%m-%d")
        self._data_dir = Path(data_dir) if data_dir else (_root() / "data")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / f"debate_cache_{self._date}.json"
        self._store = self._load()

    def _load(self) -> dict:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._store, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, symbol: str) -> dict | None:
        entry = self._store.get(symbol)
        if not entry:
            return None
        ts = entry.get("cached_at", 0)
        if time.time() - ts > self.ttl:
            # 过期：删除并返回 None
            self._store.pop(symbol, None)
            self._save()
            return None
        return entry.get("verdict")

    def put(self, symbol: str, verdict: dict) -> None:
        self._store[symbol] = {"cached_at": time.time(), "verdict": verdict}
        self._save()

    def cached_symbols(self) -> list[str]:
        """返回当前未过期的已缓存品种列表。"""
        out = []
        for sym, entry in list(self._store.items()):
            ts = entry.get("cached_at", 0)
            if time.time() - ts > self.ttl:
                self._store.pop(sym, None)
            else:
                out.append(sym)
        self._save()
        return out

    def clear(self) -> None:
        self._store = {}
        self._save()
