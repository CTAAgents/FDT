#!/usr/bin/env python3
"""
bootstrap.py — 专家团一键启动入口

用法:
  python bootstrap.py               # 单次检查模式（集成到自循环前置）
  python bootstrap.py daemon        # 后台守护模式（持续运行）
  python bootstrap.py once          # 单次运行后退出
  python bootstrap.py interactive   # 交互模式（当前）
"""

import sys
import os
from pathlib import Path

# 确保路径正确
_ROOT = Path(__file__).resolve().parent
os.chdir(str(_ROOT))
sys.path.insert(0, str(_ROOT))


def load_memory():
    """加载记忆系统"""
    memory_files = sorted(_ROOT.glob("memory/*.md"))
    json_files = sorted(_ROOT.glob("memory/*.json"))
    print(f"📚 记忆系统: {len(memory_files)}个文档 + {len(json_files)}个数据文件")

    # 关键文件检查
    critical = [
        "memory/judgment_revisions.md",
        "memory/incidents.md",
        "memory/agent_profiles.json",
        "memory/execution_followup.json",
    ]
    for f in critical:
        fp = _ROOT / f
        status = "✅" if fp.exists() else "❌"
        print(f"  {status} {f}")

    # 读取R规则数量
    revisions = _ROOT / "memory/judgment_revisions.md"
    if revisions.exists():
        r_count = sum(1 for line in revisions.read_text().splitlines() if line.startswith("| R"))
        print(f"  📋 裁决修正规则: {r_count}条生效")

    # 读取Agent数量
    agents = list(_ROOT.glob("agents/*.md"))
    print(f"  🤖 Agent定义: {len(agents)}个")

    # 读取技能数量
    skills_dir = _ROOT / "skills"
    skills = [d for d in skills_dir.iterdir() if d.is_dir() and d.name != "__pycache__"]
    print(f"  🛠️  技能: {len(skills)}个")


def print_banner():
    print()
    print("╔══════════════════════════════════════════╗")
    print("║    期货交易辩论专家团 v5.1               ║")
    print("║    Futures Trading Debate Team           ║")
    print("╚══════════════════════════════════════════╝")
    print()


def main():
    print_banner()
    load_memory()

    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "daemon":
        print(f"\n🚀 守护模式启动")
        # 写入PID文件给看门狗使用
        pid_file = _ROOT / "memory" / "daemon.pid"
        pid_file.write_text(str(os.getpid()))
        from scheduler.engine import SchedulerEngine
        engine = SchedulerEngine()
        engine.run_forever()

    elif mode == "once":
        print(f"\n⚡ 单次调度检查")
        from scheduler.engine import run_once
        triggered = run_once()
        print(f"\n触发: {len(triggered)} 个任务")
        for t in triggered:
            icon = "✅" if t["success"] else "❌"
            print(f"  {icon} {t['trigger']}: {t['reason']}")
        print(f"\n📋 注册任务 ({len(_get_tasks())}):")
        for name in _get_tasks():
            print(f"  • {name}")

    elif mode == "interactive":
        print(f"\n💬 交互模式 — 使用专家团对话界面")
        print("（当前已在此模式中运行）")
        print(f"\n可用命令:")
        print(f"  python bootstrap.py once      — 单次调度检查")
        print(f"  python bootstrap.py daemon    — 后台守护模式")

    else:
        print(f"用法:")
        print(f"  python bootstrap.py            — 单次调度检查")
        print(f"  python bootstrap.py daemon     — 后台守护模式")
        print(f"  python bootstrap.py interactive— 交互模式")


def _get_tasks() -> list:
    from scheduler.tasks import list_tasks
    return list_tasks()


if __name__ == "__main__":
    main()
