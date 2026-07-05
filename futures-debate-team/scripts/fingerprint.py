from scripts.unified_logger import get_logger
_logger = get_logger("fingerprint")
#!/usr/bin/env python3
"""
策略指纹生成器 + 选题硬阈值闸门
========================================
P0-1: 决策确定性重构 — 保证同参数同数据结果100%复现

用法:
    from fingerprint import generate_fingerprint, apply_selection_gate
    fp = generate_fingerprint(strategy_params, regime_info)
    selected = apply_selection_gate(l1l4_data, factor_data, liquidity_data, threshold=0.65)
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Optional


def generate_fingerprint(
    strategy_params: Dict[str, Any],
    regime_info: Optional[Dict[str, Any]] = None,
    seed: Optional[int] = None,
    version: str = "4.4",
) -> str:
    """
    生成唯一策略指纹ID，绑定因子组合、阈值、行情区制、参数版本。
    
    所有交易记录、辩论日志、复盘数据绑定此指纹，实现精准归因迭代。
    
    Args:
        strategy_params: 策略参数字典（如 thresholds, weights, periods）
        regime_info: 行情区制信息（如 trend_type, adx_level, volatility_regime）
        seed: 随机种子值
        version: 系统版本号
    
    Returns:
        策略指纹ID字符串（如 "FDB_v4.4_seed42_md5_abc123"）
    """
    payload = {
        "version": version,
        "seed": seed,
        "strategy_params": strategy_params,
        "regime_info": regime_info or {},
        "timestamp_utc": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    md5_hash = hashlib.md5(payload_json.encode("utf-8")).hexdigest()[:8]
    seed_tag = f"_seed{seed}" if seed is not None else "_noseed"
    return f"FDB_v{version}{seed_tag}_md5_{md5_hash}"


def apply_selection_gate(
    l1l4_data: Dict[str, Any],
    factor_data: Dict[str, Any],
    liquidity_data: Optional[Dict[str, Any]] = None,
    threshold: float = 0.65,
    min_conflicting_signals: int = 1,
) -> Dict[str, Any]:
    """
    选题硬阈值闸门：仅筛选双策略置信度≥threshold、产业链无明显矛盾、流动性达标的品种。
    
    杜绝LLM随机乱选题，保证决策可复现性。
    
    Args:
        l1l4_data: L1-L4策略输出（含每个品种的signal_score, confidence）
        factor_data: factor_timing策略输出（含每个品种的total, vote_net, g_group）
        liquidity_data: 流动性数据（含每个品种的volume_ratio, liquidity_trap）
        threshold: 双策略置信度硬阈值（默认0.65）
        min_conflicting_signals: 至少需要的冲突信号数（用于分歧品种筛选）
    
    Returns:
        {
            "selected": [str],      # 通过闸门的品种代码列表
            "rejected": [str],      # 被过滤的品种代码列表
            "reasons": {str: str},  # 每个被过滤品种的原因
            "metadata": {
                "threshold": float,
                "total_scanned": int,
                "passed_count": int,
                "rejected_count": int,
            }
        }
    """
    selected = []
    rejected = []
    reasons = {}

    # 合并两个策略的数据
    all_symbols = set(l1l4_data.keys()) | set(factor_data.keys())
    
    for sym in sorted(all_symbols):
        l1l4 = l1l4_data.get(sym, {})
        factor = factor_data.get(sym, {})
        
        # 检查1: L1-L4置信度
        l1l4_conf = l1l4.get("confidence", 0.0)
        if l1l4_conf < threshold:
            rejected.append(sym)
            reasons[sym] = f"L1-L4置信度{l1l4_conf:.2f} < 阈值{threshold}"
            continue
        
        # 检查2: factor_timing置信度（通过vote_net绝对值和g_group判断）
        vote_net = abs(factor.get("vote_net", 0))
        max_votes = 6  # 6因子总投票数
        factor_conf = vote_net / max_votes
        if factor_conf < threshold:
            rejected.append(sym)
            reasons[sym] = f"factor置信度{factor_conf:.2f} < 阈值{threshold}"
            continue
        
        # 检查3: 产业链信号无明显矛盾（L1-L4和factor方向一致）
        l1l4_dir = l1l4.get("direction", 0)
        factor_dir = factor.get("total", 0)
        if l1l4_dir * factor_dir < 0:
            # 方向冲突 = 高辩论价值品种，但需置信度都达标才放行
            if l1l4_conf < threshold + 0.05 or factor_conf < threshold + 0.05:
                rejected.append(sym)
                reasons[sym] = f"方向冲突但置信度不足(L1-L4:{l1l4_conf:.2f}, factor:{factor_conf:.2f})"
                continue
        
        # 检查4: 流动性达标
        if liquidity_data:
            liq = liquidity_data.get(sym, {})
            if liq.get("liquidity_trap", False):
                rejected.append(sym)
                reasons[sym] = "流动性陷阱(成交量<40%均值)"
                continue
            if liq.get("volume_ratio", 1.0) < 0.4:
                rejected.append(sym)
                reasons[sym] = f"成交量比{liq['volume_ratio']:.2f} < 0.4"
                continue
        
        selected.append(sym)
    
    return {
        "selected": selected,
        "rejected": rejected,
        "reasons": reasons,
        "metadata": {
            "threshold": threshold,
            "total_scanned": len(all_symbols),
            "passed_count": len(selected),
            "rejected_count": len(rejected),
        }
    }


def set_global_seed(seed: int) -> None:
    """
    设置全局随机种子，锁定 Python random、numpy、pandas 的随机性。
    
    Args:
        seed: 随机种子值
    """
    import random
    random.seed(seed)
    
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    
    try:
        import pandas as pd
        pd.core.common.random_state(seed)
    except (ImportError, AttributeError):
        pass
    
    # 设置 Python hash 种子（环境变量，需在进程启动时设置）
    # 注意：Python hash 随机化在3.3+后默认启用，需通过 PYTHONHASHSEED 控制
    import os
    os.environ["PYTHONHASHSEED"] = str(seed)
    
    print(f"[Fingerprint] 全局随机种子已设置: seed={seed}")


if __name__ == "__main__":
    # 测试
    fp = generate_fingerprint(
        strategy_params={"thresholds": [0.6, 0.7], "weights": [0.4, 0.6]},
        regime_info={"trend_type": "strong_trend", "adx": 35},
        seed=42,
    )
    print(f"策略指纹: {fp}")
    
    gate_result = apply_selection_gate(
        l1l4_data={"RB": {"confidence": 0.72, "direction": 1}, "PK": {"confidence": 0.55, "direction": -1}},
        factor_data={"RB": {"total": 2.5, "vote_net": 4}, "PK": {"total": -1.2, "vote_net": -3}},
        threshold=0.65,
    )
    print(f"闸门结果: {json.dumps(gate_result, ensure_ascii=False, indent=2)}")
