#!/usr/bin/env python3
"""
registry.py — 工具注册中心 (D2 Tool Phase 1)
===============================================
功能:
  1. 所有 FDT 工具统一注册
  2. 版本管理
  3. 工具发现与描述
  4. 工具调用统计

用法:
  from fdt_langgraph.tools.registry import ToolRegistry
  registry = ToolRegistry()
  registry.register("data_scan", module_path="scripts.data_scan", description="多策略扫描")
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_FILE = PROJECT_ROOT / "config" / "tools" / "tool_registry.json"


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._call_stats: dict[str, dict] = {}
        self._load()

    def _load(self):
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._tools = data.get("tools", {})
                    self._call_stats = data.get("call_stats", {})
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")

    def _save(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "tools": self._tools,
                "call_stats": self._call_stats,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def register(self, name: str, module_path: str, description: str, version: str = "1.0.0",
                 category: str = "data", tags: Optional[list[str]] = None,
                 dependencies: Optional[list[str]] = None):
        """注册一个工具"""
        self._tools[name] = {
            "name": name,
            "module_path": module_path,
            "description": description,
            "version": version,
            "category": category,
            "tags": tags or [],
            "dependencies": dependencies or [],
            "registered_at": datetime.now().isoformat(),
        }
        if name not in self._call_stats:
            self._call_stats[name] = {"calls": 0, "success": 0, "failures": 0, "last_call": None}
        self._save()

    def get_tool(self, name: str) -> Optional[dict]:
        """获取工具信息"""
        return self._tools.get(name)

    def list_tools(self, category: str = "") -> list[dict]:
        """列出所有工具"""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.get("category") == category]
        return sorted(tools, key=lambda x: x["name"])

    def record_call(self, name: str, success: bool):
        """记录工具调用"""
        if name not in self._call_stats:
            self._call_stats[name] = {"calls": 0, "success": 0, "failures": 0, "last_call": None}
        self._call_stats[name]["calls"] += 1
        if success:
            self._call_stats[name]["success"] += 1
        else:
            self._call_stats[name]["failures"] += 1
        self._call_stats[name]["last_call"] = datetime.now().isoformat()
        self._save()

    def get_stats(self) -> dict:
        """获取调用统计"""
        return {
            "total_tools": len(self._tools),
            "total_calls": sum(s["calls"] for s in self._call_stats.values()),
            "overall_success_rate": round(
                sum(s["success"] for s in self._call_stats.values()) /
                max(sum(s["calls"] for s in self._call_stats.values()), 1) * 100, 1
            ),
            "tools": self._call_stats,
        }

    def get_summary(self) -> dict:
        """获取注册汇总"""
        categories = {}
        for t in self._tools.values():
            cat = t.get("category", "other")
            if cat not in categories:
                categories[cat] = 0
            categories[cat] += 1
        return {
            "total": len(self._tools),
            "categories": categories,
            "stats": self.get_stats(),
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="工具注册中心")
    parser.add_argument("action", choices=["list", "stats", "register"])
    parser.add_argument("--name", "-n", help="工具名 (register)")
    parser.add_argument("--module", "-m", help="模块路径 (register)")
    parser.add_argument("--desc", "-d", help="描述 (register)")
    parser.add_argument("--category", "-c", help="分类 (register)")
    args = parser.parse_args()

    registry = ToolRegistry()

    if args.action == "register":
        registry.register(
            name=args.name or "unnamed",
            module_path=args.module or "unknown",
            description=args.desc or "",
            category=args.category or "other",
        )
        print(f"Registered: {args.name}")
    elif args.action == "list":
        for t in registry.list_tools():
            print(f"  {t['name']:<25} {t['category']:<10} v{t['version']}  {t['description']}")
    elif args.action == "stats":
        print(json.dumps(registry.get_stats(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
