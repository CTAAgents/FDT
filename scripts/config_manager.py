"""
统一配置管理器 v1.0（技术债清理）
=====================================
收敛所有散落的配置项到 settings.json。

用法:
    from scripts.config_manager import ConfigManager
    cfg = ConfigManager()
    cfg.get("mode")           # "dry-run" | "paper" | "live"
    cfg.get("seed")           # None 或 int
    cfg.get("fee_rate")       # 交易费率
    cfg.get("webhook.wecom")  # 企微webhook地址
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class ConfigManager:
    """统一配置管理器 — 从 settings.json 读取配置。"""

    def __init__(self, path: str = None) -> None:
        if path is None:
            # 自动定位到项目根目录
            path = Path(__file__).parent.parent / "settings.json"
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        """加载 settings.json。"""
        if not self.path.exists():
            return {"agent": "futures-debate-team-team-lead", "mode": "dry-run"}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套 key）。"""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        """设置配置值并持久化。"""
        keys = key.split(".")
        target = self._data
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self._save()

    def _save(self) -> None:
        """持久化到文件。"""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_all(self) -> Dict[str, Any]:
        """获取全部配置。"""
        return self._data.copy()

    def __repr__(self) -> None:
        return f"ConfigManager({self.path})"


# ── 全局单例 ──
_config = None


def config(key: str | None = None, default: Any = None) -> Any:
    """全局配置访问快捷函数。"""
    global _config
    if _config is None:
        _config = ConfigManager()
    if key is None:
        return _config
    return _config.get(key, default)


if __name__ == "__main__":
    c = ConfigManager()
    print(f"模式: {c.get('mode')}")
    print(f"品种阈值: {c.get('selection_threshold')}")
    print(f"全部配置: {json.dumps(c.get_all(), ensure_ascii=False, indent=2)}")
