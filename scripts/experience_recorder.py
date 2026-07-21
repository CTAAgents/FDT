"""
经验记录器 — Phase A2
====================
从辩论 journal + 验证结果中提取 Et 字段，写入 memory/experience/records/。

用法:
    from scripts.experience_recorder import (
        write_record, update_index, extract_task_conditions,
        build_execution_record,
    )
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from contracts.experience_schema import validate_execution_record


# ── 常量 ──

INDEX_VERSION = "1.0"

ADX_THRESHOLDS = {"low": 20, "medium": 40}  # <20=low, 20-40=medium, >40=high
ATR_THRESHOLDS = {"low": 0.5, "normal": 1.5}  # <0.5%=low, 0.5-1.5%=normal, >1.5%=high


# ── 核心函数 ──

def classify_adx(adx: float) -> str:
    """将 ADX 值分类为 low / medium / high"""
    if adx < ADX_THRESHOLDS["low"]:
        return "low"
    elif adx < ADX_THRESHOLDS["medium"]:
        return "medium"
    return "high"


def classify_volatility(atr_pct: float) -> str:
    """将 ATR 百分比分类为 low / normal / high"""
    if atr_pct < ATR_THRESHOLDS["low"]:
        return "low"
    elif atr_pct < ATR_THRESHOLDS["normal"]:
        return "normal"
    return "high"


def extract_task_conditions(scan_data: dict) -> dict:
    """从扫描数据中提取任务条件"""
    conditions = {}

    conditions["symbol"] = scan_data.get("symbol", "UNKNOWN")

    # ADX 分类
    adx = scan_data.get("adx", 0)
    conditions["adx_range"] = classify_adx(float(adx) if adx else 0)

    # 波动率分类
    atr_pct = scan_data.get("atr_pct", 1.0)
    conditions["volatility_regime"] = classify_volatility(float(atr_pct) if atr_pct else 1.0)

    # 数据源
    conditions["data_sources_available"] = scan_data.get("sources", [])

    # 新鲜度
    conditions["data_freshness_level"] = scan_data.get("freshness_level", "stale")

    # 分歧度
    divergence = scan_data.get("divergence", 0.0)
    conditions["debate_divergence"] = float(divergence) if divergence else 0.0

    return conditions


def build_execution_record(
    trace_id: str,
    scan_data: dict,
    harness_config: dict,
    result: dict,
    loop_id: str = "daily-debate",
    diagnosis: Optional[dict] = None,
) -> dict:
    """构建完整的 ExecutionRecord"""
    from datetime import datetime

    record = {
        "trace_id": trace_id,
        "loop_id": loop_id,
        "timestamp": datetime.now().isoformat(),
        "task_conditions": extract_task_conditions(scan_data),
        "harness_config": harness_config,
        "result": result,
    }
    if diagnosis:
        record["diagnosis"] = diagnosis
    return record


def _record_filename(record: dict) -> str:
    """生成记录文件名: {symbol}_{date}_{trace_short}.json"""
    symbol = record.get("task_conditions", {}).get("symbol", "UNKNOWN")
    date_str = datetime.now().strftime("%Y%m%d")
    trace_short = record.get("trace_id", "unknown")[:4]
    return f"{symbol}_{date_str}_{trace_short}.json"


def write_record(record: dict, records_dir: Path) -> Path:
    """写入单条 Et 记录到 JSON 文件。

    Args:
        record: ExecutionRecord 字典
        records_dir: 记录存储目录

    Returns:
        写入的文件路径

    Raises:
        FileExistsError: trace_id 已存在时拒绝写入（幂等保护）
    """
    # 验证
    errors = validate_execution_record(record)
    if errors:
        raise ValueError(f"ExecutionRecord 验证失败: {errors}")

    filename = _record_filename(record)
    filepath = records_dir / filename

    # 幂等检查：同 trace_id 不重复写入
    if filepath.exists():
        raise FileExistsError(f"重复 trace_id: {record['trace_id']}")

    filepath.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return filepath


def update_index(
    index_path: Path,
    record: dict,
    filename: str,
) -> None:
    """更新 INDEX.json，新增一条记录索引。

    Args:
        index_path: INDEX.json 文件路径
        record: ExecutionRecord 字典
        filename: 写入的记录文件名
    """
    if not index_path.exists():
        # 初始化空索引
        index = {
            "version": INDEX_VERSION,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "records_count": 0,
            "patterns_count": 0,
            "records": {},
            "patterns": {},
        }
    else:
        index = json.loads(index_path.read_text(encoding="utf-8"))

    trace_id = record.get("trace_id", "")
    index["records"][trace_id] = {
        "filename": filename,
        "symbol": record.get("task_conditions", {}).get("symbol", ""),
        "timestamp": record.get("timestamp", ""),
        "signal_quality": record.get("result", {}).get("signal_quality", ""),
    }
    index["records_count"] = len(index["records"])
    index["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_execution(
    trace_id: str,
    scan_data: dict,
    harness_config: dict,
    result: dict,
    records_dir: Path,
    index_path: Path,
    loop_id: str = "daily-debate",
    diagnosis: Optional[dict] = None,
) -> Path:
    """一次性完成：构建记录 → 验证 → 写入文件 → 更新索引。

    这是 post_loop 集成的推荐入口函数。

    Returns:
        写入的文件路径
    """
    record = build_execution_record(
        trace_id=trace_id,
        scan_data=scan_data,
        harness_config=harness_config,
        result=result,
        loop_id=loop_id,
        diagnosis=diagnosis,
    )
    filepath = write_record(record, records_dir)
    update_index(index_path, record, filepath.name)
    return filepath
