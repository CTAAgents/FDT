#!/usr/bin/env python3
"""
知识库按产业链重构迁移脚本 v1.0
==================================
将 knowledge/ 下的品种目录按产业链（chain）分组移动到产业链目录下。

执行前:
    python scripts/migrate_knowledge_by_chain.py --dry-run

执行:
    python scripts/migrate_knowledge_by_chain.py

验证:
    python scripts/migrate_knowledge_by_chain.py --verify
"""
import json
import os
import shutil
import sys
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent.parent / "memory" / "knowledge"
INDEX_PATH = KNOWLEDGE_DIR / "variety_index.json"

# 需要补充 chain 的品种
CHAIN_OVERRIDES = {
    "ec": "航运",  # 欧线集运期货 — 上海国际能源交易中心航运指数期货
}

# 产业链中文名 → 英文标识映射（用于目录名）
CHAIN_DIR_MAP = {
    "贵金属": "precious_metals",
    "有色金属": "nonferrous_metals",
    "黑色系": "ferrous_metals",
    "能源化工": "energy_chemical",
    "聚酯链": "polyester_chain",
    "农产品": "agricultural",
    "建材": "building_materials",
    "新能源": "new_energy",
    "金融期货": "financial_futures",
    "ETF-指数": "etf_index",
    "航运": "shipping",
}


def load_index() -> dict:
    with open(INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_index(index: dict) -> None:
    tmp = INDEX_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    tmp.replace(INDEX_PATH)


def dry_run() -> None:
    """预览将要移动的品种。"""
    index = load_index()
    varieties = index.get("varieties", {})

    # 按产业链分组
    chains = {}
    for code, info in varieties.items():
        chain = info.get("chain", "") or CHAIN_OVERRIDES.get(code, "")
        if not chain:
            print(f"  ⚠️  {code}: chain 为空，跳过")
            continue
        chains.setdefault(chain, []).append(code)

    print(f"共 {len(chains)} 个产业链，{len(varieties)} 个品种：")
    for chain, codes in sorted(chains.items()):
        dir_name = CHAIN_DIR_MAP.get(chain, chain)
        print(f"\n  📁 {chain} ({dir_name}/) — {len(codes)} 品种:")
        for code in codes:
            src = KNOWLEDGE_DIR / code
            exists = src.is_dir()
            print(f"    {'✅' if exists else '❌'} {code} ({info.get('name', '')})")

    # 检查是否有品种目录不在索引中
    all_indexed = set(varieties.keys())
    all_dirs = set(d.name for d in KNOWLEDGE_DIR.iterdir() if d.is_dir() and d.name != "strategies")
    not_indexed = all_dirs - all_indexed - {"strategies"}
    if not_indexed:
        print(f"\n  ⚠️  以下目录在索引中不存在：{not_indexed}")


def migrate() -> None:
    """执行迁移。"""
    index = load_index()
    varieties = index.get("varieties", {})

    moved = 0
    no_dir = 0
    skipped = 0
    errors = []

    # 先为所有品种设置 chain_dir，即使是目录不存在的（仅索引记录）
    for code, info in list(varieties.items()):
        chain = info.get("chain", "") or CHAIN_OVERRIDES.get(code, "")
        if not chain:
            continue
        chain_dir_name = CHAIN_DIR_MAP.get(chain, chain)

        src = KNOWLEDGE_DIR / code
        if not src.is_dir():
            # 目录不存在 → 只标记 chain_dir，不移动
            varieties[code]["chain_dir"] = chain_dir_name
            no_dir += 1
            continue

        dst_dir = KNOWLEDGE_DIR / chain_dir_name
        dst = dst_dir / code

        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"  ⚠️  {code}: 目标目录已存在 ({dst})，跳过")
                skipped += 1
                continue
            shutil.move(str(src), str(dst))
            varieties[code]["chain_dir"] = chain_dir_name
            moved += 1
            print(f"  ✅ {code} → {chain_dir_name}/{code}")
        except Exception as e:
            errors.append(f"{code}: {e}")
            print(f"  ❌ {code}: {e}")

    # 更新 ec 品种的 chain
    if "ec" in varieties:
        varieties["ec"]["chain"] = "航运"

    # 更新索引元数据
    index["meta"]["version"] = "1.1"
    index["meta"]["description"] = "品种分析逻辑知识库索引。品种按产业链分组存放。"
    index["meta"]["chain_dirs"] = {v: k for k, v in CHAIN_DIR_MAP.items()}

    save_index(index)
    print(f"\n📊 迁移完成：移动 {moved} / 无目录(仅标记) {no_dir} / 跳过 {skipped} / 错误 {len(errors)}")
    if errors:
        print(f"  错误详情：{errors}")


def verify() -> None:
    """验证迁移后的目录结构。"""
    index = load_index()
    varieties = index.get("varieties", {})

    ok = 0
    fail = 0

    for code, info in varieties.items():
        chain_dir = info.get("chain_dir", "")
        if not chain_dir:
            continue
        expected = KNOWLEDGE_DIR / chain_dir / code
        if expected.is_dir():
            ok += 1
        else:
            print(f"  ❌ {code}: 期望在 {chain_dir}/{code}，但不存在")
            fail += 1

    # 检查每个产业链目录下的期望文件
    chain_dirs = set()
    for code, info in varieties.items():
        chain_dir = info.get("chain_dir", "")
        if chain_dir:
            chain_dirs.add(chain_dir)

    for chain_dir in sorted(chain_dirs):
        p = KNOWLEDGE_DIR / chain_dir
        if not p.is_dir():
            print(f"  ❌ 产业链目录不存在: {chain_dir}")
            continue
        has_overview = (p / "overview.md").exists()
        child_dirs = [d.name for d in p.iterdir() if d.is_dir()]
        print(f"  📁 {chain_dir}/ — {len(child_dirs)} 品种{' ✅ overview.md' if has_overview else ' ❌ 无overview.md'}")

    # 检查是否有品种还在根目录下（排除产业链目录和 strategies）
    chain_dir_names = set(CHAIN_DIR_MAP.values())
    all_dirs = set(d.name for d in KNOWLEDGE_DIR.iterdir() if d.is_dir())
    leftover = all_dirs - chain_dir_names - {"strategies"}
    if leftover:
        print(f"\n  ⚠️  根目录下仍有未迁移的品种目录：{leftover}")

    print(f"\n📊 验证：{ok} 通过 / {fail} 失败")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        dry_run()
    elif "--verify" in sys.argv:
        verify()
    else:
        migrate()
