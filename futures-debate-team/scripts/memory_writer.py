"""
专家团内存写入工具 — 所有 Agent 通过此模块自动记录工作过程到 memory/ 目录

用法:
    from scripts.memory_writer import append_debate_journal, append_md_section

    # 记录到 debate_journal.json
    append_debate_journal("futures-datatech", "dual_scan", {
        "symbols": ["LH", "RB", "M"],
        "l1l4": {"bull": 1, "bear": 2},
        "factor": {"bull": 1, "bear": 1}
    })

    # 追加到 .md 文件
    append_md_section("argument_patterns.md", "证真", "2026-07-05", "发现有效的多头论证模式：...")
"""

import json, os, sys
from datetime import datetime

# ── memory 目录 ──
_MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")
_DEBATE_JOURNAL = os.path.join(_MEMORY_DIR, "debate_journal.json")
_DEBATES_INDEX = os.path.join(_MEMORY_DIR, "debates", "INDEX.md")


def _ensure_dir():
    os.makedirs(_MEMORY_DIR, exist_ok=True)


def append_debate_journal(agent: str, action: str, data: dict):
    """
    写入 debate_journal.json——所有 Agent 的通用操作日志。

    Args:
        agent: Agent 名称（如 "futures-datatech"）
        action: 操作类型（如 "dual_scan" / "research_snapshot" / "debate_thesis" 等）
        data: 操作详情 dict
    """
    _ensure_dir()
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "agent": agent,
        "action": action,
        **data,
    }
    journal = []
    if os.path.exists(_DEBATE_JOURNAL):
        try:
            with open(_DEBATE_JOURNAL, 'r', encoding='utf-8') as f:
                journal = json.load(f)
                if isinstance(journal, dict):
                    journal = journal.get("entries", [])
        except Exception:
            journal = []
    journal.append(entry)
    with open(_DEBATE_JOURNAL, 'w', encoding='utf-8') as f:
        json.dump({"entries": journal}, f, ensure_ascii=False, indent=2)
    print(f"[memory] {agent} → debate_journal.json: {action}")


def append_md_section(filename: str, author: str, date_str: str, content: str):
    """
    向 memory/ 下的 .md 文件追加一条带时间戳的记录。

    Args:
        filename: 文件名（如 "argument_patterns.md"）
        author: 作者（如 "证真"）
        date_str: 日期字符串（如 "2026-07-05"）
        content: 要追加的内容
    """
    _ensure_dir()
    filepath = os.path.join(_MEMORY_DIR, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    lines = []
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    # 添加一条记录
    record = f"\n## {date_str} by {author}\n{content}\n"
    lines.append(record)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"[memory] {author} → {filename}: 已追加")


def append_debate_index(round_id: str, symbols: list, winner: str = None):
    """更新 debates/INDEX.md"""
    _ensure_dir()
    os.makedirs(os.path.dirname(_DEBATES_INDEX), exist_ok=True)
    line = f"| {round_id} | {','.join(symbols)} | {winner or 'pending'} | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
    header = "| Round ID | Symbols | Winner | Date |\n|----------|---------|--------|------|\n"
    if os.path.exists(_DEBATES_INDEX):
        with open(_DEBATES_INDEX, 'r') as f:
            existing = f.read()
        if header not in existing:
            existing = header + existing
        existing = existing.rstrip() + "\n" + line
        with open(_DEBATES_INDEX, 'w') as f:
            f.write(existing)
    else:
        with open(_DEBATES_INDEX, 'w') as f:
            f.write(header + line)
    print(f"[memory] debate_index 已更新: {round_id}")
