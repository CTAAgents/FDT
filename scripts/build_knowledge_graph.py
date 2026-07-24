#!/usr/bin/env python3
"""
build_knowledge_graph.py — 知识图谱构建 (D5 Memory Phase 2)
=============================================================
功能:
  1. 品种关系图谱 (产业链上下游)
  2. 历史辩论关联图谱
  3. 品种-区制-策略关联
  4. 图谱查询接口

用法:
  from scripts.build_knowledge_graph import KnowledgeGraph
  kg = KnowledgeGraph()
  kg.add_relation("RB", "HC", "上下游")
  rels = kg.get_relations("RB")
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "knowledge_graph"


class KnowledgeGraph:
    """轻量级知识图谱 (JSON-based)"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.graph_file = self.storage_dir / "kg_graph.json"
        self.relations: list[dict] = []
        self.entities: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.graph_file.exists():
            try:
                with open(self.graph_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.relations = data.get("relations", [])
                    self.entities = data.get("entities", {})
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to load KG: {e}")

    def _save(self):
        with open(self.graph_file, "w", encoding="utf-8") as f:
            json.dump({
                "entities": self.entities,
                "relations": self.relations,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def add_entity(self, entity_id: str, entity_type: str, properties: Optional[dict] = None):
        """添加实体"""
        self.entities[entity_id] = {
            "id": entity_id,
            "type": entity_type,
            "properties": properties or {},
            "created_at": datetime.now().isoformat(),
        }
        self._save()

    def add_relation(self, source: str, target: str, relation_type: str, weight: float = 1.0):
        """添加关系"""
        rel = {
            "source": source,
            "target": target,
            "type": relation_type,
            "weight": weight,
            "timestamp": datetime.now().isoformat(),
        }
        self.relations.append(rel)
        self._save()

    def get_relations(self, entity_id: str, relation_type: str = "") -> list[dict]:
        """获取实体的所有关系"""
        results = []
        for rel in self.relations:
            if rel["source"] == entity_id or rel["target"] == entity_id:
                if relation_type and rel["type"] != relation_type:
                    continue
                results.append(rel)
        return results

    def get_neighbors(self, entity_id: str, max_depth: int = 1) -> set[str]:
        """获取邻接实体"""
        visited = {entity_id}
        current = {entity_id}
        for _ in range(max_depth):
            next_set = set()
            for rel in self.relations:
                if rel["source"] in current and rel["target"] not in visited:
                    next_set.add(rel["target"])
                if rel["target"] in current and rel["source"] not in visited:
                    next_set.add(rel["source"])
            visited.update(next_set)
            current = next_set
            if not current:
                break
        visited.discard(entity_id)
        return visited

    def add_debate_relation(self, symbol: str, trace_id: str, verdict: dict):
        """记录辩论与品种的关联"""
        self.add_entity(symbol, "commodity", {"name": symbol})
        self.add_entity(trace_id, "debate", {"direction": verdict.get("direction", "?"),
                                              "confidence": verdict.get("confidence", 0)})
        self.add_relation(symbol, trace_id, "debated")

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """简单实体搜索"""
        query = query.lower()
        results = []
        for eid, entity in self.entities.items():
            if query in eid.lower() or query in str(entity.get("properties", {})).lower():
                results.append(entity)
        return results[:limit]

    def get_summary(self) -> dict:
        """获取图谱汇总"""
        type_counts = defaultdict(int)
        rel_type_counts = defaultdict(int)
        for e in self.entities.values():
            type_counts[e.get("type", "unknown")] += 1
        for r in self.relations:
            rel_type_counts[r.get("type", "unknown")] += 1
        return {
            "entities": len(self.entities),
            "relations": len(self.relations),
            "entity_types": dict(type_counts),
            "relation_types": dict(rel_type_counts),
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="知识图谱构建工具")
    parser.add_argument("action", choices=["status", "search", "neighbors"])
    parser.add_argument("--entity", "-e", help="实体 ID")
    parser.add_argument("--depth", "-d", type=int, default=1, help="遍历深度")
    args = parser.parse_args()

    kg = KnowledgeGraph()
    if args.action == "status":
        summary = kg.get_summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.action == "search" and args.entity:
        results = kg.search(args.entity)
        for r in results:
            print(f"  {r['id']} ({r['type']})")
    elif args.action == "neighbors" and args.entity:
        neighbors = kg.get_neighbors(args.entity, max_depth=args.depth)
        print(f"Neighbors of {args.entity} (depth={args.depth}): {neighbors}")


if __name__ == "__main__":
    main()
