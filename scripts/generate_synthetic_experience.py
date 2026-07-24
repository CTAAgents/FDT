"""
生成模拟 Et 经验数据 — 用于验证蒸馏->适配流程
===================================================
基于 Golden Tasks 的 5 个市场场景生成差异化 Et 记录。
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.experience_recorder import update_index, write_record
from scripts.harness_adapter import adapt_harness, log_adaptation
from scripts.pattern_distiller import distill_patterns, save_pattern
from scripts.pattern_reviewer import confirm_pattern

FDT_ROOT = Path(__file__).resolve().parents[1]
RECORDS_DIR = FDT_ROOT / "memory" / "experience" / "records"
PATTERNS_DIR = FDT_ROOT / "memory" / "experience" / "patterns"
INDEX_PATH = FDT_ROOT / "memory" / "experience" / "INDEX.json"
LOG_DIR = FDT_ROOT / "memory" / "experience" / "adaptation_log"

# 5 个市场场景配置
SCENARIOS = [
    {
        "adx_range": "low", "volatility_regime": "normal", "freshness_level": "fresh",
        "symbol_prefix": "RB", "name": "低ADX+正常波动+新鲜数据",
        # 成功配置倾向
        "success_config": {"d1_context": {"max_evidence_items": 8}, "d3_generation": {"debater_temp": 0.5}},
        "success_rate": 0.75,
        "count": 8,
    },
    {
        "adx_range": "medium", "volatility_regime": "normal", "freshness_level": "fresh",
        "symbol_prefix": "CU", "name": "中ADX+正常波动+新鲜数据",
        "success_config": {"d3_generation": {"debater_temp": 0.4}, "d4_orchestration": {"debate_rounds": 6}},
        "success_rate": 0.70,
        "count": 6,
    },
    {
        "adx_range": "high", "volatility_regime": "high", "freshness_level": "fresh",
        "symbol_prefix": "AU", "name": "高ADX+高波动+新鲜数据",
        "success_config": {"d3_generation": {"debater_temp": 0.3, "judge_temp": 0.15}, "d4_orchestration": {"debate_rounds": 4}},
        "success_rate": 0.80,
        "count": 7,
    },
    {
        "adx_range": "medium", "volatility_regime": "normal", "freshness_level": "stale",
        "symbol_prefix": "SC", "name": "中ADX+正常波动+陈旧数据",
        "success_config": {"d1_context": {"max_evidence_items": 3}, "d5_memory": {"history_turns": 1}},
        "success_rate": 0.50,
        "count": 6,
    },
    {
        "adx_range": "medium", "volatility_regime": "high", "freshness_level": "fresh",
        "symbol_prefix": "IF", "name": "中ADX+高波动+新鲜数据",
        "success_config": {"d3_generation": {"debater_temp": 0.5}, "d5_memory": {"history_turns": 5}},
        "success_rate": 0.65,
        "count": 6,
    },
]

# 默认 Harness 配置（失败案例使用）
DEFAULT_HARNESS = {
    "d1_context": {"max_evidence_items": 5},
    "d3_generation": {"debater_temp": 0.4, "judge_temp": 0.2},
    "d4_orchestration": {"debate_rounds": 6},
    "d5_memory": {"history_turns": 3},
}


def generate_records(scenario: dict, base_date: datetime) -> list[dict]:
    """为单个场景生成多条差异化 Et 记录"""
    records = []
    symbols = [f"{scenario['symbol_prefix']}26{i:02d}" for i in range(1, scenario["count"] + 1)]
    random.seed(hash(scenario["symbol_prefix"]))

    for i, symbol in enumerate(symbols):
        # 70% 成功，30% 失败（按 success_rate 调整）
        is_success = random.random() < scenario["success_rate"]
        quality = "actionable" if is_success else "skip"
        config = scenario["success_config"] if is_success else DEFAULT_HARNESS

        # 添加轻微随机扰动使配置不完全一致
        config = _jitter_config(config, seed=i)

        record = {
            "trace_id": f"syn_{scenario['symbol_prefix']}_{i:03d}",
            "loop_id": "daily-debate",
            "timestamp": (base_date - timedelta(hours=random.randint(1, 72))).isoformat(),
            "task_conditions": {
                "symbol": symbol,
                "adx_range": scenario["adx_range"],
                "volatility_regime": scenario["volatility_regime"],
                "data_freshness_level": scenario["freshness_level"],
                "data_sources_available": ["web_fallback"],
                "debate_divergence": round(random.uniform(0.2, 0.5), 2),
            },
            "harness_config": config,
            "result": {
                "success": is_success,
                "verdict_direction": "bullish" if is_success and random.random() > 0.4 else ("bearish" if is_success else "neutral"),
                "verdict_confidence": round(random.uniform(0.5, 0.85) if is_success else random.uniform(0.4, 0.6), 2),
                "signal_quality": quality,
                "cost_tokens": random.randint(8000, 18000),
                "duration_seconds": round(random.uniform(120, 300), 1),
            },
        }
        records.append(record)
    return records


def _jitter_config(config: dict, seed: int, magnitude: float = 0.05) -> dict:
    """给配置添加轻微随机扰动"""
    import copy
    result = copy.deepcopy(config)
    rng = random.Random(seed + 42)
    for dim, fields in result.items():
        for field, value in fields.items():
            if isinstance(value, (int, float)):
                jitter = value * magnitude * (rng.random() - 0.5) * 2
                new_val = value + jitter
                if isinstance(value, int):
                    new_val = max(1, round(new_val))
                else:
                    new_val = round(max(0.1, min(1.0, new_val)), 4)
                result[dim][field] = new_val
    return result


def main():
    print("=" * 60)
    print("模拟 Et 经验数据生成 + 蒸馏 + 适配验证")
    print("=" * 60)

    # 确保 INDEX.json 存在
    if not INDEX_PATH.exists():
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps({
            "version": "1.0", "created_at": "2026-07-22",
            "last_updated": "2026-07-22", "records_count": 0,
            "patterns_count": 0, "records": {}, "patterns": {},
        }), encoding="utf-8")

    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    PATTERNS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    base_date = datetime(2026, 7, 22)

    # 第一步：生成 Et 记录
    print("\n[1/4] 生成模拟 Et 记录...")
    all_records = []
    for scenario in SCENARIOS:
        records = generate_records(scenario, base_date)
        all_records.extend(records)
        success_count = sum(1 for r in records if r["result"]["signal_quality"] == "actionable")
        print(f"  {scenario['name']}: {len(records)} 条 ({success_count} 成功)")

    print(f"  合计: {len(all_records)} 条")

    # 写入 Et 记录
    print(f"\n[2/4] 写入 Et 记录到 {RECORDS_DIR}...")
    for record in all_records:
        try:
            filepath = write_record(record, RECORDS_DIR)
            update_index(INDEX_PATH, record, filepath.name)
        except FileExistsError:
            # 清理已有合成记录
            existing = RECORDS_DIR / f"{record['task_conditions']['symbol']}_20260722_syn_{record['trace_id'][-4:]}.json"
            if not existing.exists():
                existing = list(RECORDS_DIR.glob(f"syn_{record['task_conditions']['symbol_prefix'][:2]}*"))[0]
            existing.unlink()
            filepath = write_record(record, RECORDS_DIR)
            update_index(INDEX_PATH, record, filepath.name)

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    print(f"  INDEX.json records_count: {index['records_count']}")

    # 第二步：蒸馏 Gt 模式
    print("\n[3/4] 蒸馏 Gt 模式...")
    patterns = distill_patterns(RECORDS_DIR, PATTERNS_DIR, min_sample=5, confidence_threshold=0.1)
    print(f"  蒸馏出 {len(patterns)} 条模式")

    # 修复 pattern_id 重复问题：distill_patterns 内部 _next_pattern_id 在
    # 同一轮中未考虑已保存的文件，导致所有 pattern 都得到 P001。
    # 手动为每条 pattern 分配唯一递增 ID。
    from scripts.pattern_distiller import _next_pattern_id as get_next_id
    for idx, p in enumerate(patterns):
        if idx > 0:
            # 已保存了上一条，重新计算 ID
            p["pattern_id"] = get_next_id(PATTERNS_DIR)
        save_pattern(p, PATTERNS_DIR)
        # 自动确认 staging -> confirmed
        confirm_pattern(PATTERNS_DIR, p["pattern_id"])
        print(f"  {p['pattern_id']} [{p['pattern_type']}] "
              f"conf={p['confidence']:.2f} samples={p['sample_count']} "
              f"rate={p['success_rate']:.0%} conditions={p['conditions']}")
        print(f"    config_delta: {p['config_delta']}")

    # 第三步：验证适配效果
    print("\n[4/4] 验证适配效果...")
    for scenario in SCENARIOS:
        tc = {
            "adx_range": scenario["adx_range"],
            "volatility_regime": scenario["volatility_regime"],
            "data_freshness_level": scenario["freshness_level"],
        }
        result = adapt_harness(tc, PATTERNS_DIR, RECORDS_DIR, shadow_mode=False)
        symbol = scenario["symbol_prefix"] + "2601"
        log_adaptation(result, f"verify_{scenario['symbol_prefix']}", symbol, LOG_DIR)

        print(f"\n  场景: {scenario['name']}")
        print(f"    匹配模式: {result['matched_patterns']}")
        print(f"    匹配案例: {result['matched_cases']}")
        if result['adaptations']:
            for a in result['adaptations']:
                print(f"    适配: {a['dimension']}.{a['field']} = {a.get('value', a.get('from', '?'))} ({a['reason']})")
        else:
            print("    适配: 无变更（使用默认配置）")

    print(f"\n{'='*60}")
    print(f"完成！Et: {index['records_count']} 条, Gt: {len(patterns)} 条")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
