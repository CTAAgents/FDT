#!/usr/bin/env python3
"""
FDT 辩论自动归档器 v1.0
解决: 辩论完成后记忆不自动写入FDT自有memory/系统的问题

用法:
  明鉴秋在每次辩论完成后调用:
  from scripts.debate_archiver import archive_round
  archive_round(round_id, symbols, verdicts, agent_statuses, output_files)

设计原则:
  - 归档到FDT memory/目录，不写工作空间memory
  - 幂等: 相同round_id不会重复写入
  - 容错: 写入失败不阻断辩论流程
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# FDT根目录
FDT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = FDT_ROOT / "memory"
DEBATE_JOURNAL = MEMORY_DIR / "debate_journal.json"
DEBATE_INDEX = MEMORY_DIR / "debates" / "INDEX.md"
JOURNAL_MAX_ENTRIES = 500  # 保留最近500条


def archive_round(
    round_id: str,
    symbols: list[str],
    verdicts: dict[str, str],
    agent_statuses: dict[str, str],
    output_files: list[str] = None,
    degraded: bool = False,
    degraded_reason: str = "",
) -> bool:
    """
    归档一轮辩论到FDT记忆系统。
    
    Args:
        round_id: 辩论轮次ID，如 'debate_20260710_120m'
        symbols: 辩论品种列表
        verdicts: {symbol: verdict_description} 如 {'SP': 'hold'}
        agent_statuses: {agent_name: 'completed'|'timeout'|'error'}
        output_files: 产出文件路径列表
        degraded: 是否降级执行
        degraded_reason: 降级原因
    
    Returns:
        True if archived successfully
    """
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "round_id": round_id,
        "symbols": symbols,
        "verdicts": verdicts,
        "agents": agent_statuses,
        "output_files": output_files or [],
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }

    try:
        # 1. 写 debate_journal.json
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        
        journal = {"entries": []}
        if DEBATE_JOURNAL.exists():
            with open(DEBATE_JOURNAL, encoding="utf-8") as f:
                journal = json.load(f)
        
        # 去重: 相同round_id不重复写
        existing_ids = {e.get("round_id") for e in journal.get("entries", [])}
        if round_id in existing_ids:
            return True
        
        journal.setdefault("entries", []).append(entry)
        # 截断保留最近条目
        if len(journal["entries"]) > JOURNAL_MAX_ENTRIES:
            journal["entries"] = journal["entries"][-JOURNAL_MAX_ENTRIES:]
        
        with open(DEBATE_JOURNAL, "w", encoding="utf-8") as f:
            json.dump(journal, f, ensure_ascii=False, indent=2)
        
        # 2. 更新辩论索引
        debates_dir = MEMORY_DIR / "debates"
        debates_dir.mkdir(parents=True, exist_ok=True)
        
        index_line = f"| {entry['timestamp'][:10]} | {round_id} | {', '.join(symbols)} | {verdicts} | {'⚠️降级' if degraded else '✓'} |\n"
        
        if not DEBATE_INDEX.exists():
            with open(DEBATE_INDEX, "w", encoding="utf-8") as f:
                f.write("# 辩论执行索引\n\n")
                f.write("| 日期 | Round ID | 品种 | 裁决 | 状态 |\n")
                f.write("|------|----------|------|------|------|\n")
                f.write(index_line)
        else:
            with open(DEBATE_INDEX, "a", encoding="utf-8") as f:
                f.write(index_line)
        
        return True
        
    except Exception as e:
        print(f"[archive_round] 归档失败: {e}", file=sys.stderr)
        return False


def archive_incident(
    incident_type: str,
    summary: str,
    root_cause: str,
    fix: str,
    prevention: str,
) -> bool:
    """归档事故到 FDT memory/incidents.md"""
    try:
        incidents_path = MEMORY_DIR / "incidents.md"
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        
        entry = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} | {incident_type}

### 事件
{summary}

### 根因
{root_cause}

### 改正
{fix}

### 预防
{prevention}
"""
        with open(incidents_path, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except Exception as e:
        print(f"[archive_incident] 归档失败: {e}", file=sys.stderr)
        return False
