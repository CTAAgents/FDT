"""FDT 自检脚本 [INDEPENDENT] — Pre-flight 检查 + 故障追溯。

调用方式：
    python scripts/self_check.py                     # 全量检查
    python scripts/self_check.py --scan <json>       # 指定扫描文件
    python scripts/self_check.py --workspace <dir>   # 指定工作空间

退出码：0=全部通过，1=警告，2=错误
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── 工具函数 ──

def _normalize_path(p: str) -> str:
    """归一化 Git Bash 路径"""
    m = re.match(r"^/([a-zA-Z])/(.*)", p.strip())
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else p


def _find_scan(workspace: str) -> str | None:
    """在工作空间中查找最新的 scan JSON"""
    ws = _normalize_path(workspace)
    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    for ptn in [f"scan_*_{today}.json", f"scan_{today}.json"]:
        files = sorted(glob.glob(os.path.join(ws, ptn)), key=os.path.getmtime)
        if files:
            return files[-1]
    return None


# ── 检查项 ──

def check_path_normalization() -> list[dict]:
    """P1: 路径归一化功能验证"""
    issues = []
    tests = [
        ("/d/FDT/FDT", "D:/FDT/FDT"),
        ("/c/Users/foo", "C:/Users/foo"),
        ("D:/FDT/FDT", "D:/FDT/FDT"),
        ("/D/FDT", "D:/FDT"),
    ]
    for raw, expected in tests:
        result = _normalize_path(raw)
        if result != expected:
            issues.append({
                "check": "路径归一化",
                "severity": "error",
                "detail": f"_normalize_path({raw!r}) → {result!r}，期望 {expected!r}",
            })
    return issues


def check_scan_file(workspace: str | None) -> list[dict]:
    """P2: 扫描文件存在性"""
    issues = []
    if not workspace:
        return issues  # 没有workspace就不检查这个

    ws = _normalize_path(workspace)
    if not os.path.isdir(ws):
        issues.append({
            "check": "工作空间",
            "severity": "error",
            "detail": f"目录不存在: {ws}",
        })
        return issues

    scan_json = _find_scan(ws)
    if not scan_json:
        # 列出目录下所有 JSON 帮助诊断
        all_json = glob.glob(os.path.join(ws, "*.json"))
        detail = f"未找到 scan JSON in {ws}"
        if all_json:
            detail += f"\n  目录下 JSON: {', '.join(os.path.basename(p) for p in sorted(all_json)[:10])}"
        issues.append({
            "check": "扫描文件",
            "severity": "error",
            "detail": detail,
        })
        return issues

    # 检查扫描内容
    try:
        with open(scan_json, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        issues.append({
            "check": "扫描文件",
            "severity": "error",
            "detail": f"解析失败 {scan_json}: {e}",
        })
        return issues

    ranked = data.get("all_ranked", data.get("all_ranked_signals", []))
    if not ranked:
        issues.append({
            "check": "信号数据",
            "severity": "error",
            "detail": f"all_ranked 为空（文件 {os.path.basename(scan_json)}）",
        })
    else:
        strong = [s for s in ranked if s.get("grade") in ("STRONG",) or s.get("level") == "STRONG"]
        watch = [s for s in ranked if s.get("grade") == "WATCH"]
        total_abs_ge20 = [s for s in ranked if abs(s.get("total", 0)) >= 20]
        print(f"  [PASS] 扫描文件: {os.path.basename(scan_json)}")
        print(f"         总信号: {len(ranked)}, STRONG: {len(strong)}, WATCH: {len(watch)}, |total|>=20: {len(total_abs_ge20)}")

    # 检查 _meta
    meta = data.get("_meta", {})
    filter_disabled = meta.get("filter_disabled", False)
    print(f"         伪信号过滤: {'禁用' if filter_disabled else '启用'}")
    print(f"         数据源: {meta.get('data_source', '?')}")
    print(f"         生成时间: {meta.get('generated_at', '?')}")

    return issues


def check_spawn_prompts() -> list[dict]:
    """P3: 检查 spawn prompt 模板是否注入 ADX 角色反转规则"""
    issues = []
    adx_keywords = ["ADX角色反转", "ADX反转", "adx_角色", "ADX低位鼓励", "ADX高位警示"]

    # 查找所有 spawn prompt 文件
    prompt_files = []
    for pattern in ["**/spawn_prompts/**/*.md", "**/prompts/**/*.md", "**/*spawn*.md", "**/*prompt*.md"]:
        found = list(ROOT.glob(pattern))
        prompt_files.extend(found)

    if not prompt_files:
        print("  [NOTE] 无 spawn prompt 模板文件（ADX 角色反转已内置于 spawn prompt）")
        return issues

    for pf in sorted(set(prompt_files)):
        try:
            text = pf.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = pf.relative_to(ROOT)
        has_adx = any(kw in text for kw in adx_keywords)
        if not has_adx and ("judge" in str(pf).lower() or "debate" in str(pf).lower()
                           or "agent" in str(pf).lower()):
            issues.append({
                "check": "ADX 角色反转",
                "severity": "warn",
                "detail": f"{rel} 可能缺少 ADX 角色反转规则（分析类 Agent 必须注入）",
            })
        elif has_adx:
            print(f"  [PASS] ADX 角色反转规则: {rel}")

    return issues


def check_fix_coverage() -> list[dict]:
    """追溯已知故障修复是否已代码化"""
    issues = []
    fixes = {
        "F01": ("路径归一化", "scripts/fdt_cli.py", "_normalize_path"),
        "F02": ("Confidence 标签", "scripts/confidence_utils.py", "CONFIDENCE_LABEL_MAP"),
        "F03": ("原策执远 Schema", "scripts/validate_agent_output.py", "variant"),
        "F07": ("评分缩进", "skills/quant-daily/scripts/scan_all.py", "len(target_symbols)"),
        "F08": ("--disable-filter KeyError", "skills/quant-daily/scripts/scan_all.py", "summary.get"),
        "F10": ("glob 不匹配", "scripts/fdt_cli.py", "cmd_finalize_only"),
    }
    applied = []
    missing = []
    for code, (name, rel_path, keyword) in fixes.items():
        target = ROOT / rel_path
        if target.exists():
            try:
                text = target.read_text(encoding="utf-8")
                if keyword in text:
                    applied.append(code)
                else:
                    missing.append(f"{code}({name}): {rel_path} 中未找到 {keyword!r}")
            except Exception:
                missing.append(f"{code}({name}): 读取失败 {rel_path}")
        else:
            missing.append(f"{code}({name}): 文件不存在 {rel_path}")

    print(f"  已代码化修复: {', '.join(applied) if applied else '无'}")
    for m in missing:
        issues.append({"check": "修复追溯", "severity": "warn", "detail": m})
    return issues


# ── 主入口 ──

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="FDT 自检脚本 — Pre-flight 检查 + 故障追溯")
    ap.add_argument("--scan", default=None, help="指定扫描 JSON 路径")
    ap.add_argument("--workspace", default=None, help="工作空间目录")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    return ap.parse_args()


def run_self_check(args: argparse.Namespace) -> int:
    """执行全部自检，返回退出码（0=通过，1=警告，2=错误）"""
    workspace = args.workspace or os.getcwd()

    print(f"{'='*60}")
    print(f"FDT Pre-flight 自检")
    print(f"{'='*60}\n")

    # 1. 路径归一化
    print("[P1] 路径归一化功能验证...")
    p1 = check_path_normalization()

    # 2. 扫描文件
    print("\n[P2] 扫描文件 & 信号合理性...")
    scan_path = args.scan or _find_scan(workspace)
    p2 = check_scan_file(workspace if not scan_path else os.path.dirname(scan_path))

    # 3. spawn prompt 模板
    print("\n[P3] ADX 角色反转规则注入...")
    p3 = check_spawn_prompts()

    # 4. 修复追溯
    print("\n[TRACE] 已知故障代码化追溯...")
    p4 = check_fix_coverage()

    # 汇总
    all_issues = p1 + p2 + p3 + p4
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warn"]

    print(f"\n{'='*60}")
    if errors:
        print(f"❌ {len(errors)} 个错误, {len(warnings)} 个警告")
        for i in errors:
            print(f"  [{i['check']}] {i['detail']}")
        print("\n请修复后重试。")
        return 2
    elif warnings:
        print(f"⚠️  {len(warnings)} 个警告（非致命）")
        for i in warnings:
            print(f"  [{i['check']}] {i['detail']}")
        print("\n建议处理上述警告。")
        return 1
    else:
        print("✅ 全部检查通过")
        return 0


if __name__ == "__main__":
    sys.exit(run_self_check(parse_args()))
