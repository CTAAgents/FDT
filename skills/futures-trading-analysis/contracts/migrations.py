"""子 skill 输出版本迁移工具，编排层在 parse_fence 后选择性调用"""



def migrate_bull_v20_to_v21(data: dict) -> dict:
    """2.0 → 2.1：增加 rebuttal_quality_score 字段"""
    if data.get("version") != "2.0":
        return data
    data["version"] = "2.1"
    data["rebuttal_quality_score"] = None
    return data


def migrate_risk_v20_to_v21(data: dict) -> dict:
    """2.0 → 2.1：增加 risk_level 字段"""
    if data.get("version") != "2.0":
        return data
    data["version"] = "2.1"
    data["risk_level"] = "medium"
    return data


def migrate_risk_v21_to_v20(data: dict) -> dict:
    """2.1 → 2.0：移除新字段，兼容旧下游"""
    if data.get("version") != "2.1":
        return data
    data.pop("risk_level", None)
    data["version"] = "2.0"
    return data


# ── v2.0 ↔ v3.0 通用迁移（核心变化: BaseSkillOutput 增加 version 字段）──

def _migrate_v20_to_v30(skill_type: str) -> callable:
    """工厂: 生成 skill_type 的 v2.0→v3.0 迁移函数"""
    def _migrate(data: dict) -> dict:
        if data.get("version") not in (None, "2.0"):
            return data
        data["version"] = "3.0"
        return data
    _migrate.__doc__ = f"{skill_type} v2.0 → v3.0: 设置 version='3.0'"
    return _migrate


def _migrate_v30_to_v20(skill_type: str) -> callable:
    """工厂: 生成 skill_type 的 v3.0→v2.0 迁移函数"""
    def _migrate(data: dict) -> dict:
        if data.get("version") != "3.0":
            return data
        data["version"] = "2.0"
        return data
    _migrate.__doc__ = f"{skill_type} v3.0 → v2.0: 设置 version='2.0'"
    return _migrate


# ── debate v2.0→v2.1: 增加 rebuttal_quality_score ──────
def _migrate_debate_v20_to_v21(data: dict) -> dict:
    """debate v2.0 → v2.1: 增加 rebuttal_quality_score 和 rebuttal_targets"""
    if data.get("version") != "2.0":
        return data
    data["version"] = "2.1"
    data.setdefault("rebuttal_quality_score", None)
    data.setdefault("rebuttal_targets", [])
    return data


def _migrate_debate_v21_to_v20(data: dict) -> dict:
    """debate v2.1 → v2.0: 移除 v2.1 新增字段"""
    if data.get("version") != "2.1":
        return data
    data.pop("rebuttal_quality_score", None)
    data["version"] = "2.0"
    return data


# ── judge v2.0→v3.0: 增加结构化 verdict ──────────────────
def _migrate_judge_v20_to_v30(data: dict) -> dict:
    """judge v2.0 → v3.0: 增加结构化 verdict 字段"""
    if data.get("version") not in (None, "2.0"):
        return data
    data["version"] = "3.0"
    data.setdefault("verdict", {})
    data.setdefault("scores", {})
    return data


# ── 通用 v2.1→v3.0 升级 ─────────────────────────────────
def _migrate_bull_v21_to_v30(data: dict) -> dict:
    """bull v2.1 → v3.0"""
    if data.get("version") != "2.1":
        return data
    data["version"] = "3.0"
    return data


def _migrate_risk_v21_to_v30(data: dict) -> dict:
    """risk v2.1 → v3.0"""
    if data.get("version") != "2.1":
        return data
    data["version"] = "3.0"
    return data


# 注册迁移路径，编排层自动调用
MIGRATION_REGISTRY = {
    # ── bull ──
    ("bull", "2.0", "2.1"): migrate_bull_v20_to_v21,
    ("bull", "2.0", "3.0"): _migrate_v20_to_v30("bull"),
    ("bull", "2.1", "3.0"): _migrate_bull_v21_to_v30,
    ("bull", "3.0", "2.0"): _migrate_v30_to_v20("bull"),
    # ── bear ──
    ("bear", "2.0", "3.0"): _migrate_v20_to_v30("bear"),
    ("bear", "3.0", "2.0"): _migrate_v30_to_v20("bear"),
    # ── debate ──
    ("debate", "2.0", "2.1"): _migrate_debate_v20_to_v21,
    ("debate", "2.1", "2.0"): _migrate_debate_v21_to_v20,
    ("debate", "2.0", "3.0"): _migrate_v20_to_v30("debate"),
    ("debate", "2.1", "3.0"): _migrate_v20_to_v30("debate"),
    ("debate", "3.0", "2.0"): _migrate_v30_to_v20("debate"),
    # ── judge ──
    ("judge", "2.0", "3.0"): _migrate_judge_v20_to_v30,
    ("judge", "3.0", "2.0"): _migrate_v30_to_v20("judge"),
    # ── risk ──
    ("risk", "2.0", "2.1"): migrate_risk_v20_to_v21,
    ("risk", "2.1", "2.0"): migrate_risk_v21_to_v20,
    ("risk", "2.0", "3.0"): _migrate_v20_to_v30("risk"),
    ("risk", "2.1", "3.0"): _migrate_risk_v21_to_v30,
    ("risk", "3.0", "2.0"): _migrate_v30_to_v20("risk"),
    # ── trading_plan ──
    ("trading_plan", "2.0", "3.0"): _migrate_v20_to_v30("trading_plan"),
    ("trading_plan", "3.0", "2.0"): _migrate_v30_to_v20("trading_plan"),
    # ── data_collection ──
    ("data_collection", "2.0", "3.0"): _migrate_v20_to_v30("data_collection"),
    ("data_collection", "3.0", "2.0"): _migrate_v30_to_v20("data_collection"),
    # ── technical ──
    ("technical", "2.0", "3.0"): _migrate_v20_to_v30("technical"),
    ("technical", "3.0", "2.0"): _migrate_v30_to_v20("technical"),
    # ── chain_analysis ──
    ("chain_analysis", "2.0", "3.0"): _migrate_v20_to_v30("chain_analysis"),
    ("chain_analysis", "3.0", "2.0"): _migrate_v30_to_v20("chain_analysis"),
}

# v3.0 版本矩阵
VERSION_MATRIX = {
    "data_collection": ["2.0", "3.0"],
    "technical": ["2.0", "3.0"],
    "chain_analysis": ["2.0", "3.0"],
    "fundamental_state": ["1.0"],
    "bull": ["2.0", "3.0"],
    "bear": ["2.0", "3.0"],
    "debate": ["2.0", "2.1", "3.0"],
    "evidence_brief": ["1.0"],
    "judge": ["2.0", "3.0"],
    "risk": ["2.0", "2.1", "3.0"],
    "trading_plan": ["2.0", "3.0"],
    "team_decision": ["1.0"],
}


def apply_migration(skill_type: str, data: dict, target_version: str) -> dict:
    """按需将 data 迁移到 target_version"""
    current = data.get("version", "2.0")
    if current == target_version:
        return data
    key = (skill_type, current, target_version)
    if key in MIGRATION_REGISTRY:
        return MIGRATION_REGISTRY[key](data)
    raise ValueError(f"No migration path from {current} to {target_version} for {skill_type}")
