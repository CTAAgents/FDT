#!/usr/bin/env python3
"""
自动发布脚本 — 版本号自增 + 文档更新 + GitHub推送

在每日辩论流水线完成后自动执行，无需人工介入。
"""
import json, os, re, subprocess, sys
from datetime import datetime

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(PROJECT, "pyproject.toml")
VERSION_FILE = os.path.join(PROJECT, ".version_history.json")
SYNC_SCRIPT = r"C:\Users\yangd\quant-bare\sync_experts_to_github.py"
TODAY = datetime.now().strftime("%Y-%m-%d")

logger = print


def read_version() -> str:
    """读取当前版本号"""
    with open(PYPROJECT, encoding="utf-8") as f:
        for line in f:
            m = re.search(r'version\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    return "4.4.0"


def bump_version(current: str, change_type: str = "patch") -> str:
    """自增版本号"""
    parts = [int(x) for x in current.split(".")]
    if change_type == "major":
        parts = [parts[0] + 1, 0, 0]
    elif change_type == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    else:  # patch
        parts = [parts[0], parts[1], parts[2] + 1]
    return ".".join(str(p) for p in parts)


def update_pyproject_version(new_version: str) -> bool:
    """更新 pyproject.toml 版本号"""
    with open(PYPROJECT, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', content)
    with open(PYPROJECT, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def append_changelog(current_version: str, new_version: str):
    """在 README.md 版本历史中追加新条目"""
    readme = os.path.join(PROJECT, "README.md")
    with open(readme, encoding="utf-8") as f:
        content = f.read()

    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"| **v{new_version}** | **{today}** | **自动发布**：流水线完成后自动版本号自增、文档同步、GitHub推送 |"

    # 在版本历史表头部插入新行
    marker = "|:----|:----|:------|"
    insert_pos = content.find(marker)
    if insert_pos >= 0:
        eol = content.find("\n", insert_pos)
        content = content[:eol+1] + entry + "\n" + content[eol+1:]
        with open(readme, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def record_change(change_desc: str):
    """记录本次变更到 .version_history.json"""
    history = {}
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, encoding="utf-8") as f:
            try: history = json.load(f)
            except: pass
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history[today] = change_desc
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def run_sync() -> bool:
    """执行 GitHub 同步"""
    if not os.path.exists(SYNC_SCRIPT):
        logger(f"⚠ 同步脚本不存在: {SYNC_SCRIPT}")
        return False
    try:
        r = subprocess.run(
            [sys.executable, SYNC_SCRIPT],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.dirname(SYNC_SCRIPT),
        )
        for line in r.stdout.split("\n"):
            if "Push" in line or "Commit" in line or "Error" in line:
                logger(f"  {line.strip()}")
        return r.returncode == 0
    except Exception as e:
        logger(f"⚠ 同步失败: {e}")
        return False


def main():
    change_desc = os.environ.get("CHANGE_DESC", sys.argv[1] if len(sys.argv) > 1 else "自动发布：代码变更")
    change_type = os.environ.get("CHANGE_TYPE", "patch")

    logger(f"{'='*50}")
    logger(f"自动发布 — {TODAY}")
    logger(f"{'='*50}")

    # 1. 版本号自增
    current = read_version()
    new_version = bump_version(current, change_type)
    logger(f"  版本: {current} → {new_version}")
    update_pyproject_version(new_version)

    # 2. 更新 changelog
    append_changelog(current, new_version)
    logger(f"  ✅ README changelog 已更新")

    # 3. 记录变更
    record_change(f"{change_desc} (v{current}→v{new_version})")
    logger(f"  ✅ 变更记录已保存")

    # 4. GitHub 推送
    logger(f"  开始 GitHub 同步...")
    ok = run_sync()
    logger(f"  {'✅ 推送成功' if ok else '⚠️ 推送失败'}")

    logger(f"{'='*50}")
    logger(f"v{current} → v{new_version} | 推送{'成功' if ok else '失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
