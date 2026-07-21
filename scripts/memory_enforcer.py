#!/usr/bin/env python3
"""
FDT 记忆执行器 — 辩论完成后自动归档。

FDT系统底层基础设施。路径由 fdt_paths 模块自动解析，不依赖外部传参。

用法:
    python memory_enforcer.py [--workspace-log PATH] [--auto-trim]

设计原则:
  - FDT是自包含系统，所有产出在FDT根目录下
  - 路径解析是系统内部行为，调用者不需要知道FDT的内部结构
  - 本脚本是FDT自循环的硬性机制，辩论完成后必须运行
"""

from typing import Any
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_FDT_SCRIPTS = str(Path(__file__).resolve().parent)
_FDT_ROOT = str(Path(_FDT_SCRIPTS).parent)
if _FDT_ROOT not in sys.path:
    sys.path.insert(0, _FDT_ROOT)

from scripts.fdt_paths import FDTFiles, FDTDirs, mirror_report_to_workspace


# ─── 工具函数 ───

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 步骤1: 辩论记录 → debate_journal.json ───

def build_debate_record(debate_data: dict) -> dict:
    varieties = debate_data.get("debate_varieties", {})
    verdicts = {}
    for sym, v in varieties.items():
        judge = v.get("judge_verdict", {}).get("overall", {})
        verdicts[sym] = (
            f"{judge.get('tendency', '?')} "
            f"({v.get('grade', '?')} {v.get('total_score', 0)}, "
            f"{judge.get('confidence', '?')}conf)"
        )
    
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "agent": "futures-debate-team-team-lead",
        "action": "debate_round_daily",
        "round_id": f"debate_{debate_data.get('report_date', 'unknown')}",
        "symbols": list(varieties.keys()),
        "period": "daily",
        "verdicts": verdicts,
        "degraded": debate_data.get("_execution", {}).get("degraded", False),
        "degraded_reason": debate_data.get("_execution", {}).get("degraded_reason"),
        "output_files": debate_data.get("_execution", {}).get("output_files", []),
    }


def archive_to_journal(record: dict) -> bool:
    path = FDTFiles.DEBATE_JOURNAL
    journal = load_json(path) if os.path.exists(path) else {"entries": []}
    
    existing = {e.get("round_id", "") for e in journal.get("entries", [])}
    if record["round_id"] in existing:
        print(f"  [skip] debate_journal: {record['round_id']} exists")
        return False
    
    journal["entries"].append(record)
    save_json(path, journal)
    print(f"  [ok] debate_journal: +{record['round_id']} ({len(journal['entries'])} total)")
    return True


# ─── 步骤2: 辩论索引 → INDEX.md ───

def archive_to_index(debate_data: dict):
    path = FDTFiles.DEBATE_INDEX
    varieties = debate_data.get("debate_varieties", {})
    date = debate_data.get("report_date", datetime.now().strftime("%Y-%m-%d"))
    
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = open(path, "r", encoding="utf-8").readlines() if os.path.exists(path) else []
    
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    for sym, v in varieties.items():
        judge = v.get("judge_verdict", {}).get("overall", {})
        d = judge.get("tendency", "neutral")
        c = judge.get("confidence", "?")
        entry = f"| {date} | {sym} | {d}({c}) | bearish | {ts} |\n"
        if not any(sym in l and date in l for l in lines):
            lines.append(entry)
    
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"  [ok] INDEX.md: {sum(1 for l in lines if date in l)} entries for {date}")


# ─── 步骤3: 工作空间日志校验 ───

FORBIDDEN = [
    "证真", "慎思", "闫判官", "风控明", "链证源", "观澜", "探源",
    "claim", "evidence", "论据", "rebuttal", "置信度",
    "铁水", "盈利率", "Mysteel", "产能利用率", "检修计划",
    "提涨", "焦化利润", "吨焦", "库存拐点", "负反馈闭环",
    "入场价", "分批建仓", "分批入场",
]


def validate_workspace_log(log_path: str, auto_trim: bool = False) -> dict:
    if not os.path.exists(log_path):
        return {"status": "no_log", "violations": 0}
    
    content = open(log_path, "r", encoding="utf-8").read()
    lines = content.split("\n")
    
    # 定位辩论段
    debate_start = -1
    for i, line in enumerate(lines):
        if any(kw in line for kw in ["日线盘后辩论", "辩论自动化", "盘后扫盘"]):
            debate_start = i
            break
    
    if debate_start < 0:
        return {"status": "no_debate_section", "violations": 0}
    
    # 提取辩论段到下一个section
    section_lines = []
    for i in range(debate_start + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if lines[i].strip():
            section_lines.append(lines[i])
    
    # 检查违禁词
    violations = []
    for line in section_lines:
        for kw in FORBIDDEN:
            if kw in line:
                violations.append(line.strip()[:80])
                break
    
    result = {
        "status": "clean" if not violations else "violation",
        "debate_lines": len(section_lines),
        "violations": len(violations),
        "details": violations[:5],
    }
    
    if violations:
        print(f"  [warn] workspace log: {len(section_lines)} lines, {len(violations)} violations")
        for v in violations[:3]:
            print(f"         {v}")
        
        if auto_trim:
            print("  [fix] auto-trimming...")
            trimmed = lines[:debate_start + 1]
            trimmed.append("- 辩论已完成，详细记录在FDT memory/")
            trimmed.append("- 报告在 FDT reports/ 目录")
            i = debate_start + 1
            while i < len(lines) and not lines[i].startswith("## "):
                i += 1
            trimmed.extend(lines[i:])
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(trimmed))
            result["trimmed"] = True
            print("  [ok] trimmed")
    
    return result


# ─── 步骤4: 报告镜像到工作空间 ───

def mirror_to_workspace():
    """将FDT reports/下最新的HTML报告复制到工作空间Commodities/"""
    report_dir = FDTDirs.REPORTS
    if not os.path.isdir(report_dir):
        return None
    
    htmls = sorted(
        [f for f in os.listdir(report_dir) if f.endswith(".html")],
        key=lambda f: os.path.getmtime(os.path.join(report_dir, f)),
        reverse=True
    )
    if not htmls:
        return None
    
    src = os.path.join(report_dir, htmls[0])
    dest = mirror_report_to_workspace(src)
    if dest:
        print(f"  [ok] workspace mirror: {dest}")
    return dest


# ─── 主入口 ───

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="FDT 记忆执行器")
    parser.add_argument("--workspace-log", help="工作空间日志路径")
    parser.add_argument("--auto-trim", action="store_true", help="自动裁减工作空间日志")
    args = parser.parse_args()
    
    # 辩论数据从FDT内部路径读取
    debate_path = FDTFiles.DEBATE_RESULTS
    if not os.path.exists(debate_path):
        print(f"FDT Memory Enforcer: no debate_results at {debate_path}")
        sys.exit(0)
    
    debate_data = load_json(debate_path)
    
    print(f"\n{'='*50}")
    print(f"  FDT Memory Enforcer")
    print(f"  root: {FDTDirs.ROOT}")
    print(f"  time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
    
    # ① 辩论记录
    record = build_debate_record(debate_data)
    archive_to_journal(record)
    
    # ② 索引
    archive_to_index(debate_data)
    
    # ③ 工作空间校验
    if args.workspace_log:
        validate_workspace_log(args.workspace_log, args.auto_trim)
    
    # ④ 镜像报告
    mirror_to_workspace()
    
    print(f"\n  All memory archives complete.\n")


if __name__ == "__main__":
    main()
