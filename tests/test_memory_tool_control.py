#!/usr/bin/env python3
"""
测试: D5 Memory 记忆治理层 + D2 Tool 工具治理层
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_knowledge_graph import KnowledgeGraph
from scripts.memory_retriever import MemoryRetriever
from scripts.memory_cleaner import MemoryCleaner
from fdt_langgraph.tools.registry import ToolRegistry
from scripts.tool_metrics import ToolMetrics
from scripts.tool_circuit_breaker import CircuitBreaker


# ============================================================
# D5 Memory Phase 2: 知识图谱
# ============================================================

class TestKnowledgeGraph:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.kg = KnowledgeGraph(storage_dir=self.temp_dir)

    def test_add_entity(self):
        self.kg.add_entity("RB", "commodity")
        summary = self.kg.get_summary()
        assert summary["entities"] == 1

    def test_add_relation(self):
        self.kg.add_entity("RB", "commodity")
        self.kg.add_entity("HC", "commodity")
        self.kg.add_relation("RB", "HC", "上下游")
        rels = self.kg.get_relations("RB")
        assert len(rels) == 1
        assert rels[0]["type"] == "上下游"

    def test_search(self):
        self.kg.add_entity("RB", "commodity", {"name": "螺纹钢"})
        results = self.kg.search("rb")
        assert len(results) == 1

    def test_get_neighbors(self):
        self.kg.add_entity("RB", "commodity")
        self.kg.add_entity("HC", "commodity")
        self.kg.add_entity("I", "commodity")
        self.kg.add_relation("RB", "HC", "上下游")
        self.kg.add_relation("HC", "I", "原料")
        neighbors = self.kg.get_neighbors("RB", max_depth=2)
        assert "HC" in neighbors
        assert "I" in neighbors

    def test_add_debate_relation(self):
        self.kg.add_debate_relation("RB", "trace_001", {"direction": "long", "confidence": 0.8})
        rels = self.kg.get_relations("RB")
        assert len(rels) == 1


# ============================================================
# D5 Memory Phase 3: 记忆召回
# ============================================================

class TestMemoryRetriever:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.retriever = MemoryRetriever(storage_dir=self.temp_dir)

    def test_store_debate_result(self):
        self.retriever.store_debate_result("RB", "long", 0.8, True)
        stats = self.retriever.get_stats()
        assert stats["total"] == 1
        assert stats["positive"] == 1

    def test_retrieve_empty(self):
        results = self.retriever.retrieve("RB")
        assert len(results) == 0  # 暂无本地数据


# ============================================================
# D5 Memory Phase 4: 记忆清理
# ============================================================

class TestMemoryCleaner:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cleaner = MemoryCleaner(memory_dir=self.temp_dir)

    def test_dry_run(self):
        report = self.cleaner.clean(dry_run=True)
        assert report["dry_run"] is True


# ============================================================
# D2 Tool Phase 1: 工具注册中心
# ============================================================

class TestToolRegistry:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        # 覆写 REGISTRY_FILE 路径
        import fdt_langgraph.tools.registry as reg_module
        reg_module.REGISTRY_FILE = self.temp_dir / "tool_registry.json"
        self.registry = ToolRegistry()

    def test_register_tool(self):
        self.registry.register("data_scan", "scripts.data_scan", "多策略扫描", category="data")
        tool = self.registry.get_tool("data_scan")
        assert tool is not None
        assert tool["name"] == "data_scan"

    def test_list_tools(self):
        self.registry.register("a", "m.a", "desc a", category="data")
        self.registry.register("b", "m.b", "desc b", category="risk")
        tools = self.registry.list_tools(category="data")
        assert len(tools) == 1

    def test_record_call(self):
        self.registry.register("test", "m.test", "test")
        self.registry.record_call("test", success=True)
        self.registry.record_call("test", success=True)
        self.registry.record_call("test", success=False)
        stats = self.registry.get_stats()
        assert stats["tools"]["test"]["calls"] == 3
        assert stats["tools"]["test"]["success"] == 2


# ============================================================
# D2 Tool Phase 3: 工具效能追踪
# ============================================================

class TestToolMetrics:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.tm = ToolMetrics(storage_dir=self.temp_dir)

    def test_record_and_stats(self):
        self.tm.record_call("scan", success=True, latency_ms=1200)
        self.tm.record_call("scan", success=False, latency_ms=3000)
        stats = self.tm.get_tool_stats("scan")
        assert stats["scan"]["calls"] == 2
        assert stats["scan"]["success_rate"] == 50.0

    def test_latency_tracking(self):
        self.tm.record_call("scan", success=True, latency_ms=1000)
        self.tm.record_call("scan", success=True, latency_ms=2000)
        stats = self.tm.get_tool_stats("scan")
        assert stats["scan"]["avg_latency_ms"] == 1500.0
        assert stats["scan"]["max_latency_ms"] == 2000.0

    def test_detect_high_latency(self):
        for _ in range(5):
            self.tm.record_call("slow_tool", success=True, latency_ms=6000)
        anomalies = self.tm.detect_anomalies(days=7)
        slow = [a for a in anomalies if a["tool"] == "slow_tool"]
        assert len(slow) > 0

    def test_detect_low_success(self):
        for _ in range(10):
            self.tm.record_call("flaky_tool", success=False, latency_ms=500)
        anomalies = self.tm.detect_anomalies(days=7)
        flaky = [a for a in anomalies if a["tool"] == "flaky_tool"]
        assert len(flaky) > 0


# ============================================================
# D2 Tool Phase 4: 工具熔断器
# ============================================================

class TestCircuitBreaker:
    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cb = CircuitBreaker(
            storage_dir=self.temp_dir,
            failure_threshold=3,
            recovery_timeout=1,
            window_seconds=60,
        )

    def test_closed_by_default(self):
        assert self.cb.is_allowed("test_tool") is True

    def test_opens_after_threshold(self):
        for _ in range(4):
            self.cb.record_failure("failing_tool")
        assert self.cb.is_allowed("failing_tool") is False

    def test_recovers_after_timeout(self):
        self.cb = CircuitBreaker(
            storage_dir=self.temp_dir,
            failure_threshold=2,
            recovery_timeout=0,  # immediate recovery
            window_seconds=60,
        )
        for _ in range(3):
            self.cb.record_failure("temp_fail")
        assert self.cb.is_allowed("temp_fail") is True  # immediate recovery

    def test_fallback(self):
        self.cb.register_fallback("primary", ["secondary"])
        for _ in range(4):
            self.cb.record_failure("primary")
        fallback = self.cb.get_fallback("primary")
        assert fallback == "secondary"

    def test_half_open_recovery(self):
        self.cb = CircuitBreaker(
            storage_dir=self.temp_dir,
            failure_threshold=3,
            recovery_timeout=0,  # immediate half-open
            window_seconds=60,
        )
        for _ in range(4):
            self.cb.record_failure("recovering")
        self.cb.record_success("recovering")
        assert self.cb.is_allowed("recovering") is True

    def test_events_logged(self):
        for _ in range(4):
            self.cb.record_failure("event_test")
        events = self.cb.get_recent_events()
        assert len(events) >= 1
        assert events[0]["event"] == "opened"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
