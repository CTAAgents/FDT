#!/usr/bin/env python3
"""
品种知识库初始化脚本 v1.0.0
============================
从现有数据源批量初始化品种知识库。

数据源（按优先级）:
1. varieties.yaml — 品种基础信息 → profile.json
2. instrument_strategy_matrix.json — F1-F5适应性权重 → profile.json
3. argument_patterns.md — 通用论证模式 → patterns.json（按品种归类）
4. data_sources.md — 数据源信息 → data_quality.json
5. debate_journal.json — 历史辩论记录 → 批量回填

用法:
    python scripts/init_knowledge_base.py [--force]
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

# ── 路径 ──────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_FDT_ROOT = _SCRIPT_DIR.parent
_MEMORY_DIR = _FDT_ROOT / "memory"
_KNOWLEDGE_DIR = _MEMORY_DIR / "knowledge"
_SKILLS_DIR = _FDT_ROOT / "skills"
_QUANT_DAILY = _SKILLS_DIR / "quant-daily"

# 已知的产业链映射
CHAIN_MAP = {
    "黑色系": ["rb", "hc", "ss", "wr", "i", "j", "jm", "sm", "sf"],
    "有色金属": ["cu", "al", "zn", "pb", "ni", "sn", "ao", "ad", "bc"],
    "贵金属": ["au", "ag", "pt", "pd"],
    "能源化工": ["ru", "br", "fu", "bu", "sp", "op", "l", "v", "pp", "eb", "pg", "sa", "sh", "ma", "ur", "sc", "lu", "nr"],
    "聚酯链": ["ta", "eg", "pf", "pr", "px"],
    "农产品": ["a", "b", "m", "y", "p", "c", "cs", "jd", "lh", "rr", "bb", "fb", "lg", "ap", "cf", "cy", "cj", "pk", "oi", "rm", "rs", "sr", "wh", "pm", "jr", "lr", "ri"],
    "建材": ["fg", "sa"],
    "新能源": ["si", "lc", "ps"],
    "金融期货": ["if", "ic", "im", "ih", "ts", "tf", "t", "tl"],
}


def load_yaml(path: Path) -> Dict:
    """安全加载 YAML。"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"  ⚠️  YAML加载失败 {path.name}: {e}")
        return {}


def load_json(path: Path, default: Any = None) -> Any:
    """安全加载 JSON。"""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️  JSON加载失败 {path.name}: {e}")
        return default if default is not None else {}


def init_profile(variety_code: str, varieties_data: List[Dict], matrix: Dict, force: bool = False) -> bool:
    """写入 variety 的 profile.json。"""
    profile_path = _KNOWLEDGE_DIR / variety_code / "profile.json"
    if profile_path.exists() and not force:
        return False  # 已存在且非强制覆盖

    # 从 varieties.yaml 查找
    v_info = next((v for v in varieties_data if v["code"].lower() == variety_code), {})
    chain = ""
    for c_name, members in CHAIN_MAP.items():
        if variety_code in members:
            chain = c_name
            break

    # 从 instrument_strategy_matrix 获取 F1-F5 权重
    matrix_entry = matrix.get("data", {}).get(variety_code, {})
    families = matrix_entry.get("families", {})

    profile = {
        "code": variety_code,
        "name": v_info.get("name", variety_code.upper()),
        "exchange": v_info.get("exchange", ""),
        "unit": v_info.get("unit", ""),
        "delivery_months": v_info.get("delivery_months", []),
        "chain": chain,
        "aliases": v_info.get("aliases", []),
        "strategy_weights": {
            fam: data.get("w", 0.5) for fam, data in families.items()
        } if families else {},
        "strategy_samples": {
            fam: data.get("v", 0) for fam, data in families.items()
        } if families else {},
        "init_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "varieties.yaml + instrument_strategy_matrix.json",
    }

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ profile.json ({variety_code})")
    return True


def init_drivers(variety_code: str, force: bool = False) -> bool:
    """初始化 drivers.md 模板。"""
    drivers_path = _KNOWLEDGE_DIR / variety_code / "drivers.md"
    if drivers_path.exists() and not force:
        return False

    chain = ""
    for c_name, members in CHAIN_MAP.items():
        if variety_code in members:
            chain = c_name
            break

    content = f"""# {variety_code.upper()} 核心驱动因子

> 自动初始化于 {datetime.now().strftime("%Y-%m-%d %H:%M")}
> 产业链: {chain}
> 本文件由 extract_knowledge.py 在每轮辩论后自动更新

## 初始驱动因子（待辩论积累）

品种 {variety_code.upper()} 暂无辩论记录，驱动因子将在后续辩论中逐步积累。

## 辩论记录

"""
    drivers_path.parent.mkdir(parents=True, exist_ok=True)
    drivers_path.write_text(content, encoding="utf-8")
    print(f"  ✅ drivers.md ({variety_code})")
    return True


def init_data_quality(variety_code: str, data_sources: Dict, force: bool = False) -> bool:
    """初始化 data_quality.json。"""
    dq_path = _KNOWLEDGE_DIR / variety_code / "data_quality.json"
    if dq_path.exists() and not force:
        return False

    dq = {
        "sources": {},
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "variety": variety_code,
    }

    # 从 data_sources.md 解析初始数据源
    for src_name, src_info in data_sources.items():
        priority = 3  # 默认
        src_name_lower = src_name.lower()
        if any(kw in src_name_lower for kw in ["wh6", "文华", "通达信", "tdx", "tq-local"]):
            priority = 1
        elif any(kw in src_name_lower for kw in ["tqsdk", "tq"]):
            priority = 2
        elif any(kw in src_name_lower for kw in ["东方财富", "eastmoney"]):
            priority = 3
        elif any(kw in src_name_lower for kw in ["akshare", "交易所", "shfe", "dce", "czce"]):
            priority = 4

        dq["sources"][src_name.lower().replace(" ", "_")] = {
            "name": src_name,
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
            "last_seen": datetime.now().strftime("%Y-%m-%d"),
            "total_calls": 0,
            "delayed_days": 0,
            "delayed_count": 0,
            "priority": priority,
        }

    dq_path.parent.mkdir(parents=True, exist_ok=True)
    dq_path.write_text(json.dumps(dq, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ data_quality.json ({variety_code})")
    return True


def seed_from_argument_patterns(force: bool = False) -> int:
    """从 argument_patterns.md 中提取通用模式，按品种分类写入。"""
    patterns_path = _MEMORY_DIR / "argument_patterns.md"
    if not patterns_path.exists():
        print("  ⚠️  未找到 argument_patterns.md，跳过模式种子")
        return 0

    content = patterns_path.read_text(encoding="utf-8")
    seeded = 0

    # 解析历史示例表格
    table_pattern = r"\| (\w+)\s+\|.*?(\d+)/\d+.*?\|.*?\|.*?\|.*?\|"
    for match in re.finditer(table_pattern, content):
        variety_code = match.group(1).strip().lower()
        rank = int(match.group(2))

        patterns_file = _KNOWLEDGE_DIR / variety_code / "patterns.json"
        if patterns_file.exists() and not force:
            continue

        # 创建一个种子模式
        seed_pattern = {
            "pattern_id": f"{variety_code}-p000",
            "name": "种子模式（从 argument_patterns.md 导入）",
            "first_observed": "2026-07-04",
            "last_used": "2026-07-04",
            "use_count": 1,
            "win_count": 0,
            "win_rate": 0.5,
            "structure": f"历史排名 {rank}/62 品种，待验证",
            "applicable_conditions": {},
            "key_evidence_sources": ["argument_patterns.md"],
            "derived_from_debates": [],
            "confidence": 0.5,
            "status": "seed",
            "note": "从历史 argument_patterns.md 导入的种子模式，需要后续辩论验证后转为 active",
        }

        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        patterns_file.write_text(json.dumps([seed_pattern], ensure_ascii=False, indent=2), encoding="utf-8")
        seeded += 1

    if seeded > 0:
        print(f"  ✅ 从 argument_patterns.md 导入了 {seeded} 个品种的种子模式")
    return seeded


def update_variety_index() -> None:
    """更新 variety_index.json 索引，同步到文件系统实际状态。"""
    index_path = _KNOWLEDGE_DIR / "variety_index.json"
    if not index_path.exists():
        print("  ⚠️  未找到 variety_index.json")
        return

    index = load_json(index_path)
    existing_dirs = set(os.listdir(_KNOWLEDGE_DIR))

    # 清理已不存在的品种条目
    if "varieties" in index:
        index["varieties"] = {k: v for k, v in index["varieties"].items() if k in existing_dirs or k == "variety_index.json"}

    for variety_code in os.listdir(_KNOWLEDGE_DIR):
        if variety_code == "variety_index.json":
            continue

        variety_dir = _KNOWLEDGE_DIR / variety_code
        if not variety_dir.is_dir():
            continue

        # 检查各文件存在状态
        has_profile = (variety_dir / "profile.json").exists()
        has_drivers = (variety_dir / "drivers.md").exists()
        has_patterns = (variety_dir / "patterns.json").exists()
        has_key_levels = (variety_dir / "key_levels.json").exists()
        has_data_quality = (variety_dir / "data_quality.json").exists()

        # 统计有效模式数
        effective = 0
        if has_patterns:
            try:
                patterns = json.loads((variety_dir / "patterns.json").read_text(encoding="utf-8"))
                effective = len([p for p in patterns if p.get("status", "active") == "active"])
            except (json.JSONDecodeError, OSError):
                pass

        if variety_code not in index.get("varieties", {}):
            if "varieties" not in index:
                index["varieties"] = {}

        idx_entry = index["varieties"].setdefault(variety_code, {})
        idx_entry["profile"] = has_profile
        idx_entry["drivers"] = has_drivers
        idx_entry["patterns"] = has_patterns
        idx_entry["key_levels"] = has_key_levels
        idx_entry["data_quality"] = has_data_quality
        idx_entry["effective_patterns"] = effective

    # 更新时间戳
    index.setdefault("meta", {})
    index["meta"]["last_initialized"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 原子写入
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(index_path)
    print("  ✅ variety_index.json 已更新")


def main() -> None:
    force = "--force" in sys.argv

    print(f"\n{'='*50}")
    print("品种知识库初始化脚本 v1.0.0")
    print(f"运行于: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 1. 加载 varieties.yaml
    print("[1/5] 加载 varieties.yaml...")
    varieties_path = _QUANT_DAILY / "scripts" / "references" / "varieties.yaml"
    varieties_data = load_yaml(varieties_path).get("varieties", [])
    print(f"  → {len(varieties_data)} 品种")

    # 2. 加载 instrument_strategy_matrix.json
    print("[2/5] 加载 instrument_strategy_matrix.json...")
    matrix = load_json(_MEMORY_DIR / "instrument_strategy_matrix.json", {})
    matrix_data = matrix.get("data", {})
    print(f"  → {len(matrix_data)} 品种有策略权重")

    # 3. 加载 data_sources.md
    print("[3/5] 加载 data_sources.md...")
    ds_path = _MEMORY_DIR / "data_sources.md"
    data_sources = {}
    if ds_path.exists():
        for line in ds_path.read_text(encoding="utf-8").split("\n"):
            if line.startswith("|") and "|" in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3 and parts[1]:
                    data_sources[parts[1]] = parts[2] if len(parts) > 2 else ""
    print(f"  → {len(data_sources)} 数据源")

    # 4. 批量初始化各品种
    print("\n[4/5] 初始化品种知识文件...")
    profile_count = 0
    drivers_count = 0
    dq_count = 0

    all_codes = set(v["code"].lower() for v in varieties_data)
    # 补充来自 matrix 的品种
    for code in matrix_data:
        all_codes.add(code.lower())
    # 补充来自 CHAIN_MAP 的品种
    for members in CHAIN_MAP.values():
        for code in members:
            all_codes.add(code)

    for variety_code in sorted(all_codes):
        p = init_profile(variety_code, varieties_data, matrix, force)
        d = init_drivers(variety_code, force)
        q = init_data_quality(variety_code, data_sources, force)
        if p:
            profile_count += 1
        if d:
            drivers_count += 1
        if q:
            dq_count += 1

    print(f"  → profile.json: {profile_count} 新建")
    print(f"  → drivers.md: {drivers_count} 新建")
    print(f"  → data_quality.json: {dq_count} 新建")

    # 5. 从 argument_patterns.md 导入种子模式
    print("\n[5/5] 从 argument_patterns.md 导入种子模式...")
    seeded = seed_from_argument_patterns(force)

    # 6. 更新索引
    print("\n更新 variety_index.json...")
    update_variety_index()

    print(f"\n{'='*50}")
    print("✅ 初始化完成")
    print(f"   品种目录: {len(all_codes)}")
    print(f"   profile.json: {profile_count} 新建")
    print(f"   drivers.md: {drivers_count} 新建")
    print(f"   data_quality.json: {dq_count} 新建")
    print(f"   种子模式: {seeded} 品种")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
