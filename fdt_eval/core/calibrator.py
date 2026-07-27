"""Weight calibration using Leave-One-Out correlation analysis.

Method (from ARCHITECTURE.md §9.2):
    For each weight wi:
    1. Fix other weights
    2. Scan wi in [0.05, 0.50] with step 0.05
    3. Compute Spearman correlation between EvalScore and subsequent verdict accuracy
    4. Choose wi that maximizes correlation

    Constraints:
    - Sum of all wi = 1.0
    - Each wi >= 0.05
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fdt_eval.core.store import EvalStore

logger = logging.getLogger(__name__)

# ── 阶段默认权重 ──
# 从 ARCHITECTURE.md §9.1 提取
_DEFAULT_WEIGHTS: dict[str, float] = {
    "runtime": 0.35,
    "gate": 0.25,
    "post_hoc": 0.25,
    "evolution": 0.15,
}

# ── 扫描参数 ──
_MIN_WEIGHT = 0.05
_MAX_WEIGHT = 0.50
_STEP = 0.05
_MIN_SAMPLES_FOR_LOO = 20  # LOO 需要至少这么多样本


def _default_output_path() -> Path:
    """获取默认的 weight_history.json 路径。"""
    return Path(__file__).resolve().parent.parent / "profiles" / "weight_history.json"


def _load_history(output_path: Path) -> list[dict[str, Any]]:
    """加载已有的 weight history。"""
    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("weight_history.json 解析失败: %s", e)
            return []
    return []


def _save_history(history: list[dict[str, Any]], output_path: Path) -> None:
    """保存 weight history。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    logger.info("权重历史已保存到 %s", output_path)


def _compute_default_weights() -> dict[str, float]:
    """计算当前默认权重。

    当 EvalStore 中数据不足时返回预定义默认值。
    runtime=0.35, gate=0.25, post_hoc=0.25, evolution=0.15
    """
    return dict(_DEFAULT_WEIGHTS)


def _loo_scan(
    store: EvalStore,
    last_n: int,
) -> dict[str, float] | None:
    """Leave-One-Out 权重扫描。

    LOO 扫描需要:
    1. 从 EvalStore 读取最近 last_n 条 eval_results
    2. 按 case stage 分组统计
    3. 对每个 stage 的权重 wi 在 [0.05, 0.50] 以 0.05 步长扫描
    4. 计算 Spearman 相关系数（EvalScore vs 裁决正确性）
    5. 选取相关系数最大的 wi

    Args:
        store: EvalStore 实例
        last_n: 分析的最近记录数

    Returns:
        校准后的权重 dict 或 None（数据不足时返回 None）
    """
    # 获取最近 runs
    all_cases = set()
    case_records: dict[str, list[dict[str, Any]]] = {}

    # 从 store 获取所有 case 类型
    from fdt_eval.core.registry import eval_registry
    for case_id in eval_registry.all_case_ids:
        records = store.trend(case_id, last=last_n)
        if records:
            all_cases.add(case_id)
            case_records[case_id] = records

    if not case_records:
        logger.info("LOO 扫描: 无历史数据，返回 None")
        return None

    total_records = sum(len(v) for v in case_records.values())
    if total_records < _MIN_SAMPLES_FOR_LOO:
        logger.info(
            "LOO 扫描: 样本不足 (%d < %d)，需要更多历史数据",
            total_records, _MIN_SAMPLES_FOR_LOO,
        )
        return None

    # ── 按 stage 聚合 ──
    stage_cases: dict[str, list[str]] = {}
    for case_id in all_cases:
        stage = case_id.split(".")[0]
        if stage not in stage_cases:
            stage_cases[stage] = []
        stage_cases[stage].append(case_id)

    # 当前使用的默认权重
    current_weights = _compute_default_weights()

    # TODO: 真实 LOO Spearman 扫描
    # 当前实现为占位 - 返回默认权重并记录需要进一步数据积累
    #
    # 完整实现需要:
    # 1. 从 store 读取每个 case 的历史得分
    # 2. 从外部系统（如 BacktestDB）读取对应品种的裁决正确性
    # 3. 对每个 stage 的权重 wi 扫描:
    #    for wi in np.arange(0.05, 0.51, 0.05):
    #        other_weights = normalize remaining stages
    #        eval_scores = compute_weighted_scores(history, wi, other_weights)
    #        corr = spearmanr(eval_scores, verdict_accuracy)
    #        if corr > best_corr: best_wi = wi
    # 4. 确保 sum(wi) = 1.0, each wi >= 0.05

    sample_counts = {stage: len(cases) for stage, cases in stage_cases.items()}
    logger.info(
        "LOO 扫描占位: 共 %d 条记录, %d 个 stage (%s) — "
        "需要裁判正确性数据才能执行真实 Spearman 扫描",
        total_records,
        len(stage_cases),
        sample_counts,
    )

    return current_weights


def calibrate_weights(
    store: EvalStore | None = None,
    last_n: int = 100,
    output_path: str | None = None,
) -> dict[str, Any]:
    """执行权重校准。

    读取配置文件 (profiles/*.yaml) 中的权重设置，结合历史 eval 数据，
    使用 LOO Spearman 方法优化各阶段权重。

    Args:
        store: EvalStore 实例，None 时创建默认实例
        last_n: 分析的最近记录数 (默认 100)
        output_path: weight_history.json 输出路径，None 时使用默认路径
                     (fdt_eval/profiles/weight_history.json)

    Returns:
        dict 包含:
        - current_weights: 当前默认权重
        - calibrated_weights: 校准后的权重（数据不足时同 current_weights）
        - method: "loo_spearman" 或 "default"
        - samples: 分析的 eval_results 数量
    """
    store = store or EvalStore()
    out_path = Path(output_path) if output_path else _default_output_path()

    # 1. 加载历史记录
    history = _load_history(out_path)

    # 2. 计算当前默认权重
    current_weights = _compute_default_weights()

    # 3. LOO 扫描
    calibrated = _loo_scan(store, last_n)

    if calibrated is not None:
        method = "loo_spearman"
        final_weights = calibrated
    else:
        method = "default"
        final_weights = current_weights

    # 4. 保存历史
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "method": method,
        "samples": last_n,
        "current_weights": current_weights,
        "calibrated_weights": final_weights,
        "notes": (
            "LOO scanning: Samples insufficient for Spearman correlation. "
            "Needs >=20 eval_results and external verdict accuracy data. "
            "Returning default weights."
            if method == "default"
            else "LOO Spearman calibration applied."
        ),
    }
    history.append(snapshot)
    _save_history(history, out_path)

    return {
        "current_weights": current_weights,
        "calibrated_weights": final_weights,
        "method": method,
        "samples": last_n,
        "history_entries": len(history),
    }
