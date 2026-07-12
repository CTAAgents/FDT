"""
Memory Writer 集成测试 — G8
===========================

覆盖: Journal/Index/Record 三类写入、并发安全、必需字段校验。
"""

import sys, json, threading
from pathlib import Path
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


class TestMemoryWriter:
    """MemoryWriter 核心功能测试"""

    @pytest.fixture
    def writer(self, tmp_path):
        from scripts.memory_writer import MemoryWriter
        return MemoryWriter(round_id="TEST_001", base_dir=str(tmp_path))

    def test_write_creates_file(self, writer):
        """写入后文件存在"""
        writer.write("test_agent", {"key": "value"})
        files = list(writer.round_dir.glob("*.json"))
        assert len(files) == 1

    def test_write_preserves_data(self, writer):
        """写入内容可正确读取——数据在 record.data 中"""
        data = {"signal": "breakout", "score": 85}
        writer.write("test_agent", data)

        files = list(writer.round_dir.glob("*.json"))
        with open(files[0], encoding="utf-8") as f:
            record = json.load(f)

        assert record["data"]["signal"] == "breakout"
        assert record["data"]["score"] == 85

    def test_merge_all_combines(self, writer):
        """merge_all 合并多个 Agent 产出"""
        writer.write("agent_a", {"x": 1})
        writer.write("agent_b", {"y": 2})
        writer.write("agent_c", {"z": 3})

        merged = writer.merge_all()
        assert merged is not None
        assert isinstance(merged, dict)

    def test_validate_no_errors_on_good_data(self, writer):
        """完整数据 validate 通过——使用标准 Agent ID"""
        expected = [
            "futures-datatech",
            "futures-technical-researcher",
            "futures-fundamental-researcher",
            "futures-chain-analyst",
            "futures-affirmative-debater",
            "futures-opposition-debater",
            "futures-trading-strategist",
            "futures-risk-manager",
            "futures-judge",
        ]
        for agent in expected:
            writer.write(agent, {"type": "research_output", "subject": "RB"})
        result = writer.validate()
        assert result["is_valid"] is True, f"missing: {result.get('missing')}"

    def test_concurrent_writes_no_crash(self, writer):
        """并发写入不崩溃"""
        errors = []
        barrier = threading.Barrier(5, timeout=10)

        def worker(i):
            try:
                barrier.wait()
                for j in range(10):
                    writer.write(f"agent_{i}", {"round": j, "value": i * j})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert errors == [], f"并发写入出错: {errors}"

    def test_sqlite_backup_exists(self, writer):
        """SQLite 备份文件存在"""
        writer.write("test", {"a": 1})
        assert writer.db_path.exists()


class TestMemoryWriterEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def writer(self, tmp_path):
        from scripts.memory_writer import MemoryWriter
        return MemoryWriter(round_id="EDGE_001", base_dir=str(tmp_path))

    def test_write_empty_data_ok(self, writer):
        """空 dict 写入不崩溃"""
        writer.write("test", {})
        assert len(list(writer.round_dir.glob("*.json"))) == 1

    def test_write_large_data_ok(self, writer):
        """大数据量写入不崩溃"""
        data = {"key": "x" * 10000, "items": list(range(1000))}
        writer.write("test", data)
        assert len(list(writer.round_dir.glob("*.json"))) == 1

    def test_multi_round_isolation(self, tmp_path):
        """不同 round_id 文件互不干扰"""
        from scripts.memory_writer import MemoryWriter
        w1 = MemoryWriter(round_id="R1", base_dir=str(tmp_path))
        w2 = MemoryWriter(round_id="R2", base_dir=str(tmp_path))

        w1.write("a", {"round": 1})
        w2.write("a", {"round": 2})

        r1_files = list(w1.round_dir.glob("*.json"))
        r2_files = list(w2.round_dir.glob("*.json"))
        assert len(r1_files) == 1
        assert len(r2_files) == 1
