"""
模式审查工具 — Phase B3
=======================
将 staging 状态的 Gt 模式经人工确认后提升为 confirmed。
支持交互式 CLI 审查和批量操作。

用法:
    python scripts/pattern_reviewer.py --patterns-dir memory/experience/patterns/
    python scripts/pattern_reviewer.py --list
    python scripts/pattern_reviewer.py --confirm P001
    python scripts/pattern_reviewer.py --deprecate P001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from contracts.experience_schema import validate_distilled_pattern


def _load_pattern(patterns_dir: Path, pattern_id: str) -> dict | None:
    """加载单条模式"""
    filepath = patterns_dir / f"{pattern_id}.json"
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text(encoding="utf-8"))


def _save_pattern(patterns_dir: Path, pattern: dict) -> Path:
    """保存模式"""
    from datetime import datetime
    pattern["last_updated"] = datetime.now().isoformat()
    filepath = patterns_dir / f"{pattern['pattern_id']}.json"
    filepath.write_text(
        json.dumps(pattern, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return filepath


def list_patterns(patterns_dir: Path, status_filter: str | None = None) -> list[dict]:
    """列出模式"""
    if not patterns_dir.exists():
        return []
    patterns = []
    for f in patterns_dir.glob("*.json"):
        pattern = json.loads(f.read_text(encoding="utf-8"))
        if status_filter and pattern.get("status") != status_filter:
            continue
        patterns.append(pattern)
    return sorted(patterns, key=lambda p: p["pattern_id"])


def confirm_pattern(patterns_dir: Path, pattern_id: str) -> bool:
    """将 staging 模式提升为 confirmed"""
    pattern = _load_pattern(patterns_dir, pattern_id)
    if pattern is None:
        print(f"错误: 模式 {pattern_id} 不存在", file=sys.stderr)
        return False
    if pattern.get("status") != "staging":
        print(f"错误: 模式 {pattern_id} 状态为 {pattern['status']}，只能确认 staging 模式", file=sys.stderr)
        return False

    errors = validate_distilled_pattern(pattern)
    if errors:
        print(f"错误: 模式验证失败: {errors}", file=sys.stderr)
        return False

    pattern["status"] = "confirmed"
    _save_pattern(patterns_dir, pattern)
    print(f"已确认: {pattern_id}")
    return True


def deprecate_pattern(patterns_dir: Path, pattern_id: str) -> bool:
    """将模式降级为 deprecated"""
    pattern = _load_pattern(patterns_dir, pattern_id)
    if pattern is None:
        print(f"错误: 模式 {pattern_id} 不存在", file=sys.stderr)
        return False
    if pattern.get("status") == "deprecated":
        print(f"错误: 模式 {pattern_id} 已是 deprecated", file=sys.stderr)
        return False

    pattern["status"] = "deprecated"
    _save_pattern(patterns_dir, pattern)
    print(f"已降级: {pattern_id}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Gt 模式审查工具")
    parser.add_argument("--patterns-dir", type=Path, default=Path("memory/experience/patterns/"),
                        help="模式存储目录")
    parser.add_argument("--list", action="store_true", help="列出所有模式")
    parser.add_argument("--staging", action="store_true", help="仅列出 staging 模式")
    parser.add_argument("--confirm", type=str, help="确认指定模式 (staging → confirmed)")
    parser.add_argument("--deprecate", type=str, help="降级指定模式 (→ deprecated)")

    args = parser.parse_args()

    if args.confirm:
        confirm_pattern(args.patterns_dir, args.confirm)
    elif args.deprecate:
        deprecate_pattern(args.patterns_dir, args.deprecate)
    elif args.list or args.staging:
        status = "staging" if args.staging else None
        patterns = list_patterns(args.patterns_dir, status)
        if not patterns:
            print("无匹配模式")
            return
        for p in patterns:
            print(f"  {p['pattern_id']} [{p['status']}] "
                  f"conf={p['confidence']:.2f} samples={p['sample_count']} "
                  f"success_rate={p['success_rate']:.1%}")
    else:
        # 交互模式
        staging = list_patterns(args.patterns_dir, "staging")
        if not staging:
            print("无 staging 模式需要审查")
            return
        print(f"共有 {len(staging)} 条 staging 模式待审查:\n")
        for p in staging:
            print(f"  {p['pattern_id']}: conf={p['confidence']:.2f}, "
                  f"samples={p['sample_count']}, success_rate={p['success_rate']:.1%}")
            print(f"    条件: {p['conditions']}")
            print(f"    推荐: {p['config_delta']}")
            print()
            choice = input(f"  确认 {p['pattern_id']}? [y/n/skip/deprecate]: ").strip().lower()
            if choice == "y":
                confirm_pattern(args.patterns_dir, p["pattern_id"])
            elif choice == "deprecate":
                deprecate_pattern(args.patterns_dir, p["pattern_id"])
            else:
                print(f"  跳过 {p['pattern_id']}")


if __name__ == "__main__":
    main()
