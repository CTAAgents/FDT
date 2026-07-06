#!/usr/bin/env python3
"""
辩论后复盘分析 — 明鉴秋自动调用
====================================
每次辩论结束后自动执行：追加辩论记录到 INDEX.md、更新Agent表现统计。

依赖数据：从 debate_results.json + p_judge_final.json 提取
"""

import json, os, datetime


def _load_json(filepath: str) -> dict:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def _get_expert_root() -> str:
    """获取专家包根目录。优先用环境变量，fallback到硬编码路径。"""
    env = os.environ.get("FDT_EXPERT_ROOT", "")
    if env and os.path.isdir(env):
        return env
    # 基于脚本位置推算
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # futures-trading-analysis/scripts/ → 向上4层到skills/ → 再向上到futures-debate-team/
    candidate = os.path.normpath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir, os.pardir))
    if os.path.isdir(os.path.join(candidate, "agents")):
        return candidate
    # hardcoded fallback
    return os.path.join(
        os.path.expanduser("~"), ".workbuddy", "plugins", "marketplaces", "my-experts", "plugins", "futures-debate-team"
    )


def update_debate_index(round_id: str, judge_verdict: dict, results: dict) -> str:
    index_dir = os.path.join(_get_expert_root(), "memory", "debates")
    index_path = os.path.join(index_dir, "INDEX.md")
    os.makedirs(index_dir, exist_ok=True)

    winner = judge_verdict.get("winner", "?")
    score = judge_verdict.get("score_summary", {})
    short_candidates = results.get("quant_signals_summary", {}).get("short_top5", {})
    symbols = ", ".join(list(short_candidates.keys())[:5])

    entry = f"""| {round_id} | {symbols} | {score.get("long", 0):.1f} vs {score.get("short", 0):.1f} | {winner} | {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} |
"""
    header = f"""# 辩论索引库

| 辩论ID | 品种 | 评分 | 胜方 | 日期 |
|--------|------|------|------|------|{chr(10)}"""

    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            existing = f.read()
        if "| 辩论ID |" not in existing:
            existing = header + existing
    else:
        existing = header

    # 去重：如果round_id已存在则跳过
    if round_id in existing:
        return f"跳过：{round_id} 已存在"

    # 插入第一条数据后
    lines = existing.split("\n")
    insert_pos = 0
    for i, line in enumerate(lines):
        if line.startswith("| --") or line.startswith("|---"):
            insert_pos = i + 1
            break
    if insert_pos == 0:
        insert_pos = len(lines)

    lines.insert(insert_pos, entry.rstrip())

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return f"INDEX.md 已更新: {round_id}"


def update_agent_performance(round_id: str, judge_verdict: dict) -> str:
    analysis_dir = os.path.join(_get_expert_root(), "memory", "debates", "analysis")
    perf_path = os.path.join(analysis_dir, "agent_performance.md")
    os.makedirs(analysis_dir, exist_ok=True)

    winner = judge_verdict.get("winner", "?")
    scores = judge_verdict.get("scores", {})

    entry_lines = [f"\n### {round_id}"]
    for dim, data in scores.items():
        if isinstance(data, dict) and "long" in data and "short" in data:
            entry_lines.append(f"- {dim}: 正{data['long']} vs 反{data['short']} (weight={data.get('weight', '?')})")

    if not os.path.exists(perf_path):
        header = f"# Agent 表现跟踪\n\n## 辩论记录\n记录格式：辩论ID → 各维度评分\n"
        with open(perf_path, "w", encoding="utf-8") as f:
            f.write(header)
    else:
        with open(perf_path, "r", encoding="utf-8") as f:
            existing = f.read()
        if round_id in existing:
            return f"跳过：{round_id} 已存在"

    with open(perf_path, "a", encoding="utf-8") as f:
        f.write("\n".join(entry_lines) + "\n")

    return f"Agent表现已记录: {round_id}"


def run_post_debate(round_id: str, reports_dir: str) -> dict:
    """主入口：辩论结束后自动调用。"""
    judge = _load_json(os.path.join(reports_dir, f"p_judge_final_{round_id}.json"))
    results = _load_json(os.path.join(reports_dir, f"debate_results_{round_id}.json"))

    index_result = update_debate_index(round_id, judge, results)
    perf_result = update_agent_performance(round_id, judge)

    return {
        "round_id": round_id,
        "index_entry": index_result,
        "perf_entry": perf_result,
        "status": "ok",
    }


if __name__ == "__main__":
    import sys

    round_id = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    report_dir = (
        sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.expanduser("~"), "Documents", "Signal", "reports")
    )
    result = run_post_debate(round_id, report_dir)
