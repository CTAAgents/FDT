#!/usr/bin/env python3
"""
FDT 路径解析器 — 系统底层基础设施

本模块是FDT所有路径的唯一真相源（Single Source of Truth）。
所有FDT脚本、Agent、自动化都必须通过此模块解析路径，
禁止在代码中硬编码任何路径。

设计原则:
  - FDT是一棵自包含的目录树，所有运行时产出都在FDT根目录下
  - 工作空间仅做镜像：获取报告副本供用户查看
  - 路径计算是纯函数，不依赖环境变量或配置文件
"""

import os
import sys
from datetime import datetime
from pathlib import Path


# ─── 自动检测FDT根目录 ───

def _detect_fdt_root() -> str:
    """自动检测FDT根目录，三级fallback。
    
    优先级:
      1. 从本文件位置向上找（最可靠）
      2. 从当前工作目录找 plugins/.../futures-debate-team
      3. 从 HOME 找 .fdt/plugins/.../futures-debate-team
    """
    # 方法1: 本文件在 FDT_ROOT/scripts/fdt_paths.py
    this_file = Path(__file__).resolve()
    fdt_root = this_file.parent.parent
    if (fdt_root / "memory").exists() and (fdt_root / "agents").exists():
        return str(fdt_root)
    
    # 方法2: 从CWD查找
    cwd = Path.cwd()
    for _ in range(10):
        candidate = cwd / "plugins" / "marketplaces" / "my-experts" / "plugins" / "futures-debate-team"
        if candidate.exists():
            return str(candidate)
        if cwd.parent == cwd:
            break
        cwd = cwd.parent
    
    # 方法3: 从HOME查找
    home = Path.home()
    candidate = home / ".fdt" / "plugins" / "marketplaces" / "my-experts" / "plugins" / "futures-debate-team"
    if candidate.exists():
        return str(candidate)
    
    raise RuntimeError(
        "无法定位FDT根目录。请确认FDT安装在以下路径之一:\n"
        f"  - {(Path(__file__).resolve().parent.parent)}\n"
        f"  - {home / '.fdt' / 'plugins' / 'marketplaces' / 'my-experts' / 'plugins' / 'futures-debate-team'}"
    )


# ─── 单例 ───

FDT_ROOT = _detect_fdt_root()


# ─── 版本号（单一真相源 = pyproject.toml）───

def get_fdt_version() -> str:
    """从 pyproject.toml 读取 FDT 版本号（唯一版本真相源）。

    所有需要展示/写入版本号的地方（bootstrap 横幅、debate_results.json 的
    debate_version 字段、Agent 身份等）都必须调用本函数，禁止写死版本号，
    防止版本漂移（历史事故：team-lead 卡在 5.3.0、debate_results 写死 v5.3）。
    """
    import tomllib
    pyproject = os.path.join(FDT_ROOT, "pyproject.toml")
    try:
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "unknown"


# ─── 目录常量 ───

class FDTDirs:
    """FDT目录结构"""
    ROOT = FDT_ROOT
    DATA = os.path.join(FDT_ROOT, "data")        # 运行时数据 (debate_results.json等)
    REPORTS = os.path.join(FDT_ROOT, "reports")   # 生成的报告 (HTML)
    MEMORY = os.path.join(FDT_ROOT, "memory")     # 系统记忆 (自进化燃料)
    SCRIPTS = os.path.join(FDT_ROOT, "scripts")   # 运行时代码
    SKILLS = os.path.join(FDT_ROOT, "skills")     # Agent技能
    AGENTS = os.path.join(FDT_ROOT, "agents")     # Agent定义
    DEBATES = os.path.join(FDT_ROOT, "memory", "debates")  # 辩论索引


class FDTFiles:
    """FDT关键文件"""
    # 运行时产出
    DEBATE_RESULTS = os.path.join(FDTDirs.DATA, "debate_results.json")
    
    # 系统记忆
    DEBATE_JOURNAL = os.path.join(FDTDirs.MEMORY, "debate_journal.json")
    DEBATE_INDEX = os.path.join(FDTDirs.DEBATES, "INDEX.md")
    INCIDENTS = os.path.join(FDTDirs.MEMORY, "incidents.md")
    
    # 报告
    def debate_report(ts: str | None = None) -> str:
        """生成辩论报告路径"""
        ts = ts or datetime.now().strftime("%Y%m%d_%H%M")
        return os.path.join(FDTDirs.REPORTS, f"debate_report_{ts}.html")


# ─── 工作空间镜像 ───

def workspace_commodities_dir() -> str:
    """推测工作空间的 Commodities/ 目录（用户访问入口）。
    v2.2: 废弃，工作空间由 cwds 参数传入，不再依赖外部仓库。"""
    cwd = os.getcwd()
    return os.path.join(cwd, "Commodities")


def mirror_report_to_workspace(fdt_report_path: str) -> str | None:
    """将FDT报告镜像到工作空间 Commodities/"""
    ws_dir = workspace_commodities_dir()
    if not os.path.exists(ws_dir):
        os.makedirs(ws_dir, exist_ok=True)
    
    fname = os.path.basename(fdt_report_path)
    ws_path = os.path.join(ws_dir, fname)
    
    # 复制
    import shutil
    shutil.copy2(fdt_report_path, ws_path)
    return ws_path


# ─── 验证 ───

def validate_fdt_structure() -> dict:
    """验证FDT目录结构完整性，返回状态报告"""
    required = [
        (FDTDirs.MEMORY, "memory/"),
        (FDTDirs.DATA, "data/"),
        (FDTDirs.REPORTS, "reports/"),
        (FDTDirs.SCRIPTS, "scripts/"),
        (FDTDirs.AGENTS, "agents/"),
        (FDTDirs.SKILLS, "skills/"),
    ]
    
    missing = []
    for path, label in required:
        if not os.path.isdir(path):
            missing.append(label)
    
    return {
        "fdt_root": FDT_ROOT,
        "complete": len(missing) == 0,
        "missing": missing,
    }


# ─── CLI ───

if __name__ == "__main__":
    print(f"FDT根目录: {FDT_ROOT}")
    print(f"  数据目录: {FDTDirs.DATA}")
    print(f"  报告目录: {FDTDirs.REPORTS}")
    print(f"  记忆目录: {FDTDirs.MEMORY}")
    print(f"  脚本目录: {FDTDirs.SCRIPTS}")
    print()
    
    status = validate_fdt_structure()
    if status["complete"]:
        print("✅ FDT目录结构完整")
    else:
        print(f"⚠ 缺失目录: {status['missing']}")
    print()
    print(f"工作空间镜像: {workspace_commodities_dir()}")
