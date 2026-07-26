"""session_memory → 补丁记忆迁移脚本

为现有 session_memory JSONL 条目补充 EvoMem 补丁字段
（patch_id / domain / pre_state / post_state / rationale / evidence / conditions），
并将规则变更类条目写入 patches.jsonl。

用法:
    python scripts/migrate_session_memory_patches.py
    python scripts/migrate_session_memory_patches.py --dry-run  # 仅预览不写入
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── 领域推断规则 ──────────────────────────────────
# 从 learned / intent 文本匹配到 domain 标签
_DOMAIN_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"P0铁律|硬规则|不可违反", re.IGNORECASE), "规则|P0铁律"),
    (re.compile(r"止损|stop_loss|止损价", re.IGNORECASE), "规则|止损"),
    (re.compile(r"仓位|position_pct|仓位上限", re.IGNORECASE), "规则|仓位"),
    (re.compile(r"入场|entry_price|市价", re.IGNORECASE), "规则|入场"),
    (re.compile(r"右侧交易|反趋势|趋势结构", re.IGNORECASE), "规则|右侧交易"),
    (re.compile(r"生猪|lh|猪周期", re.IGNORECASE), "品种|生猪"),
    (re.compile(r"螺纹|rb|螺纹钢", re.IGNORECASE), "品种|螺纹钢"),
    (re.compile(r"PTA|ta|聚酯", re.IGNORECASE), "品种|PTA"),
    (re.compile(r"知识库|knowledge|产业链", re.IGNORECASE), "知识库|产业链"),
    (re.compile(r"数据源|akshare|数据清洗", re.IGNORECASE), "数据源|AKShare"),
    (re.compile(r"架构|重构|迁移", re.IGNORECASE), "架构"),
    (re.compile(r"质检|quality|品藻", re.IGNORECASE), "规则|质检"),
    (re.compile(r"风控|risk|风险", re.IGNORECASE), "规则|风控"),
    (re.compile(r"版本号|bump|version", re.IGNORECASE), "运维|版本"),
    (re.compile(r"LLM|prompt|agent", re.IGNORECASE), "架构|Agent"),
]


def infer_domain(entry: dict) -> str:
    """从 entry 文本推断 domain 标签。"""
    text = " ".join(filter(None, [
        entry.get("learned", ""),
        entry.get("intent", ""),
        entry.get("outcome", ""),
    ]))
    for pattern, domain in _DOMAIN_RULES:
        if pattern.search(text):
            return domain
    return "未分类"


def build_patch(entry: dict, patch_id: str) -> dict:
    """将 session_memory 条目转换为补丁格式。"""
    learned = entry.get("learned", "")
    intent = entry.get("intent", "")
    outcome = entry.get("outcome", "")
    timestamp = entry.get("message_summary_time", "")

    # 从 learned 提取 pre_state/post_state
    if "→" in learned:
        parts = learned.split("→", 1)
        pre = parts[0].strip()
        post = parts[1].strip()
    elif "改为" in learned or "替换" in learned:
        pre = learned  # 保留原文作为 pre
        post = learned
    else:
        # 尝试从 outcome 提取
        if "改为" in outcome or "→" in outcome:
            pre = outcome
            post = outcome
        else:
            pre = f"之前: {learned[:60]}" if learned else "未知"
            post = learned[:120] if learned else "未知"

    domain = infer_domain(entry)
    date_str = timestamp[:10] if len(timestamp) >= 10 else datetime.now().strftime("%Y-%m-%d")

    return {
        "patch_id": patch_id,
        "domain": domain,
        "pre_state": pre[:200],
        "post_state": post[:200],
        "rationale": intent[:200] or entry.get("message_summary_time", ""),
        "evidence": [f"来自 session_memory: {entry.get('message_id', 'unknown')}"],
        "conditions": {
            "applicable_regime": ["all"],
            "inapplicable_regime": [],
            "valid_from": date_str,
            "valid_until": None,
        },
        "intent": intent,
        "actions": entry.get("actions", []),
        "outcome": outcome,
        "learned": learned,
        "message_summary_time": timestamp,
        "message_id": entry.get("message_id", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="session_memory → 补丁记忆迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.parent
    memory_dir = script_dir / "memory"
    session_dir = memory_dir / "session"
    patch_dir = memory_dir / "_session_memory"

    # 扫描所有 session_memory JSONL
    entries: list[dict] = []
    for f in sorted(session_dir.rglob("session_memory_*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    logger.info("发现 %d 条 session_memory 条目", len(entries))

    # 转换
    patches: list[dict] = []
    for i, entry in enumerate(entries):
        # 检查是否已有 patch_id
        if entry.get("patch_id"):
            continue
        patch_id = f"patch-{datetime.now().strftime('%Y%m%d')}-migrate-{i + 1:03d}"
        patch = build_patch(entry, patch_id)
        patches.append(patch)

    # 过滤：只保留规则变更类（跳过纯信息查询）
    rule_patches = [p for p in patches if p["domain"] != "未分类"]
    skipped = len(patches) - len(rule_patches)

    logger.info("可迁移规则补丁: %d 条（跳过 %d 条未分类）", len(rule_patches), skipped)

    if args.dry_run:
        logger.info("=== DRY RUN ===")
        for p in rule_patches[:5]:
            logger.info("  %s | %s | %s", p["patch_id"], p["domain"], p["post_state"][:60])
        if len(rule_patches) > 5:
            logger.info("  ... 及 %d 条更多", len(rule_patches) - 5)
        logger.info("DRY RUN 结束，未写入任何文件")
        return

    # 写入
    today = datetime.now().strftime("%Y%m%d")
    today_patch_dir = patch_dir / today
    today_patch_dir.mkdir(parents=True, exist_ok=True)

    patch_file = today_patch_dir / "patches.jsonl"
    written = 0
    with open(patch_file, "a", encoding="utf-8") as fh:
        for p in rule_patches:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
            written += 1

    logger.info("已写入 %d 条补丁至 %s", written, patch_file)

    # 写入索引（简化版 — 批处理全部插入后再重建索引）
    from memory.store.patch_store import PatchStore
    store = PatchStore(memory_dir)
    for p in rule_patches:
        store._update_index(p)
    logger.info("倒排索引已重建")


if __name__ == "__main__":
    main()
