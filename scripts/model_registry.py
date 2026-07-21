#!/usr/bin/env python3
"""
模型注册表 v1.0（P1-4）
=========================
管理模型版本、训练快照、回退机制。

核心功能：
- register_version(): 注册模型版本
- rollback(): 回退到指定版本
- get_latest(): 获取最新版本
- list_versions(): 查看版本历史
- compare_performance(): 版本间性能比较

用法:
    from scripts.model_registry import ModelRegistry
    reg = ModelRegistry()
    reg.register_version("v4.4.0-20260705", metrics={"sharpe": 1.2, "win_rate": 0.55})
    reg.rollback("v4.4.0-20260704")  # 如果新版本表现不如旧版本
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from scripts.unified_logger import get_logger

logger = get_logger("model_registry")


class ModelRegistry:
    """模型版本注册表。"""

    def __init__(self, path: str = None) -> None:
        if path is None:
            path = Path(__file__).parent.parent / "skills/quant-daily/models/registry.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"versions": [], "active_version": None}

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def register_version(self, version_id: str, parent_version: str = None, metrics: dict = None, notes: str = "") -> None:
        """注册新版本。

        Args:
            version_id: 版本标识（如 "v4.4.0-20260705"）
            parent_version: 父版本（用于回退追踪）
            metrics: 性能指标 {"sharpe": 1.2, "win_rate": 0.55}
            notes: 变更说明
        """
        entry = {
            "version": version_id,
            "parent": parent_version or self._data.get("active_version"),
            "created_at": datetime.now().isoformat(),
            "metrics": metrics or {},
            "notes": notes,
            "status": "active",
        }
        self._data["versions"].append(entry)
        self._data["active_version"] = version_id
        self._save()
        logger.info(f"模型版本注册: {version_id}")

    def rollback(self, target_version: str) -> bool:
        """回退到指定版本。

        Args:
            target_version: 目标版本标识

        Returns:
            是否成功
        """
        versions = [v["version"] for v in self._data["versions"]]
        if target_version not in versions:
            logger.error(f"回退失败: 版本 {target_version} 不存在")
            return False

        current = self._data["active_version"]
        self._data["active_version"] = target_version
        # 标记当前版本为回退
        for v in self._data["versions"]:
            if v["version"] == current:
                v["status"] = "rolled_back"
            elif v["version"] == target_version:
                v["status"] = "active"
        self._save()
        logger.info(f"模型回退: {current} → {target_version}")
        return True

    def get_latest(self) -> Optional[dict]:
        """获取当前活跃版本。"""
        active = self._data.get("active_version")
        if not active:
            return None
        for v in self._data["versions"]:
            if v["version"] == active:
                return v
        return None

    def list_versions(self, top_n: int = 10) -> list:
        """列出最近的版本历史。"""
        versions = sorted(
            self._data["versions"],
            key=lambda x: x["created_at"],
            reverse=True,
        )
        return versions[:top_n]

    def compare_performance(self, v1: str, v2: str) -> dict:
        """比较两个版本的性能指标。"""
        m1 = m2 = {}
        for v in self._data["versions"]:
            if v["version"] == v1:
                m1 = v.get("metrics", {})
            if v["version"] == v2:
                m2 = v.get("metrics", {})

        diff = {}
        for key in set(list(m1.keys()) + list(m2.keys())):
            v1_val = m1.get(key, 0)
            v2_val = m2.get(key, 0)
            diff[key] = round(v2_val - v1_val, 4)

        return {
            "v1": v1,
            "v2": v2,
            "v1_metrics": m1,
            "v2_metrics": m2,
            "diff": diff,
        }


if __name__ == "__main__":
    reg = ModelRegistry()
    reg.register_version("v4.4.0-20260705", metrics={"sharpe": 1.2, "win_rate": 0.55})
    reg.register_version("v4.4.0-20260706", metrics={"sharpe": 0.9, "win_rate": 0.48})
    print(f"活跃版本: {reg.get_latest()}")
    reg.rollback("v4.4.0-20260705")
    print(f"回退后活跃版本: {reg.get_latest()}")
    print(f"对比: {reg.compare_performance('v4.4.0-20260705', 'v4.4.0-20260706')}")
