from scripts.unified_logger import get_logger
_logger = get_logger("memory_writer")
#!/usr/bin/env python3
"""
记忆写入器 — 竞态安全的Agent日志管理（P0-4）
================================================
解决DAG并行调度下10个Agent共用 debate_journal.json 的读写竞态问题。

设计原则：
1. 每个Agent写入独立文件：memory/{agent_id}_{round}.json
2. 明鉴秋汇总阶段统一 merge 到 debate_results.json
3. 过渡期使用 SQLite 本地时序库，支持并发写入
4. 每日自动校验日志完整性

用法:
    from memory_writer import MemoryWriter
    writer = MemoryWriter(round_id="RB_20260705")
    writer.write(agent_id="futures-technical-researcher", data={...})
    
    # 汇总
    merged = writer.merge_all()
    writer.validate()
"""

import os, json, sqlite3, time
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path


class MemoryWriter:
    """竞态安全的记忆写入器，每个Agent独立文件 + SQLite 备份。"""
    
    def __init__(self, round_id: str, base_dir: str = None):
        """
        Args:
            round_id: 本轮辩论唯一ID（如 "RB_20260705"）
            base_dir: 记忆根目录（默认 ~/.workbuddy/plugins/.../memory/）
        """
        self.round_id = round_id
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            # 自动定位到项目 memory/ 目录
            self.base_dir = Path(__file__).parent.parent / "memory"
        
        self.round_dir = self.base_dir / round_id
        self.round_dir.mkdir(parents=True, exist_ok=True)
        
        # SQLite 数据库路径
        self.db_path = self.round_dir / "debate_journal.db"
        self._init_sqlite()
    
    def _init_sqlite(self):
        """初始化SQLite表结构。"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(round_id, agent_id, data_type)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_round_agent 
                ON agent_logs(round_id, agent_id)
            """)
            conn.commit()
    
    def write(self, agent_id: str, data: Dict[str, Any], data_type: str = "output") -> str:
        """
        写入Agent日志（文件 + SQLite双写）。
        
        Args:
            agent_id: Agent标识（如 "futures-technical-researcher"）
            data: 结构化数据字典
            data_type: 数据类型（output/analysis/decision）
        
        Returns:
            写入的文件路径
        """
        timestamp = datetime.now().isoformat()
        
        # 1. 写入独立JSON文件（每个Agent一个文件）
        file_name = f"{agent_id}_{data_type}.json"
        file_path = self.round_dir / file_name
        
        record = {
            "round_id": self.round_id,
            "agent_id": agent_id,
            "data_type": data_type,
            "timestamp": timestamp,
            "data": data,
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        
        # 2. 写入SQLite（支持并发写入）
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO agent_logs (round_id, agent_id, timestamp, data_type, data_json)
                VALUES (?, ?, ?, ?, ?)
            """, (self.round_id, agent_id, timestamp, data_type, json.dumps(data, ensure_ascii=False)))
            conn.commit()
        
        return str(file_path)
    
    def read(self, agent_id: str, data_type: str = "output") -> Optional[Dict[str, Any]]:
        """读取指定Agent的日志。"""
        file_path = self.round_dir / f"{agent_id}_{data_type}.json"
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def merge_all(self) -> Dict[str, Any]:
        """
        汇总所有Agent日志，合并为 debate_results.json 格式。
        
        Returns:
            {"round_id": str, "agents": {agent_id: data}, "metadata": {...}}
        """
        result = {
            "round_id": self.round_id,
            "agents": {},
            "metadata": {
                "merged_at": datetime.now().isoformat(),
                "agent_count": 0,
            }
        }
        
        # 从SQLite读取（更可靠，支持并发）
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT agent_id, data_type, data_json FROM agent_logs WHERE round_id = ?",
                (self.round_id,)
            )
            for row in cursor.fetchall():
                agent_id, data_type, data_json = row
                if agent_id not in result["agents"]:
                    result["agents"][agent_id] = {}
                result["agents"][agent_id][data_type] = json.loads(data_json)
        
        # 补充从文件读取（SQLite可能缺失的）
        for json_file in self.round_dir.glob("*_*.json"):
            if json_file.name == "debate_results.json":
                continue
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    record = json.load(f)
                agent_id = record.get("agent_id", "")
                data_type = record.get("data_type", "output")
                if agent_id and agent_id not in result["agents"]:
                    result["agents"][agent_id] = {}
                if agent_id:
                    result["agents"][agent_id][data_type] = record.get("data", {})
            except (json.JSONDecodeError, KeyError):
                pass
        
        result["metadata"]["agent_count"] = len(result["agents"])
        
        # 保存汇总结果
        result_path = self.round_dir / "debate_results.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        return result
    
    def validate(self) -> Dict[str, Any]:
        """
        校验日志完整性：检查缺失、重复、损坏。
        
        Returns:
            {"is_valid": bool, "missing": [str], "duplicates": [str], "corrupted": [str]}
        """
        expected_agents = [
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
        
        missing = []
        duplicates = []
        corrupted = []
        
        for agent_id in expected_agents:
            file_path = self.round_dir / f"{agent_id}_output.json"
            if not file_path.exists():
                missing.append(agent_id)
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 检查重复（同一Agent多个文件）
                matching = list(self.round_dir.glob(f"{agent_id}_*.json"))
                if len(matching) > 2:  # 正常只有 _output.json + 可能的手动文件
                    duplicates.append(f"{agent_id} ({len(matching)} files)")
            except json.JSONDecodeError:
                corrupted.append(agent_id)
        
        is_valid = len(missing) == 0 and len(corrupted) == 0
        
        result = {
            "is_valid": is_valid,
            "missing": missing,
            "duplicates": duplicates,
            "corrupted": corrupted,
            "checked_at": datetime.now().isoformat(),
        }
        
        # 保存校验报告
        report_path = self.round_dir / "validation_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        return result


# ── 兼容旧API ──
def append_debate_journal(agent_id: str, data_type: str, data: Dict[str, Any], round_id: str = None):
    """兼容旧版 debate_journal 写入接口。"""
    if round_id is None:
        round_id = datetime.now().strftime("%Y%m%d")
    writer = MemoryWriter(round_id=round_id)
    return writer.write(agent_id, data, data_type)


def append_debate_index(round_id: str, symbols: List[str], direction: str):
    """兼容旧版 debate_index 写入接口。"""
    writer = MemoryWriter(round_id=round_id)
    return writer.write("team-lead", {"symbols": symbols, "direction": direction}, "index")


if __name__ == "__main__":
    # 测试
    writer = MemoryWriter(round_id="TEST_20260705")
    writer.write("futures-technical-researcher", {"adx": 25, "trend": "bull"})
    writer.write("futures-risk-manager", {"verdict": "green"})
    merged = writer.merge_all()
    print(f"Merged: {json.dumps(merged, ensure_ascii=False, indent=2)}")
    validation = writer.validate()
    print(f"Validation: {json.dumps(validation, ensure_ascii=False, indent=2)}")
