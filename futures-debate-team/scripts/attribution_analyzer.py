from scripts.unified_logger import get_logger
_logger = get_logger("attribution")
#!/usr/bin/env python3
"""
归因分析器 — Shapley归因 + 判官权重动态 + 论据绩效库（P0-5）
========================================================================
扩展风控L5反馈闭环：从仅校准技术支撑阻力置信度，扩展到校准判官评分和论据有效性。

核心功能：
1. shapley_attribution(): 量化各维度对交易盈亏的贡献占比
2. update_judge_weights(): 根据历史PnL动态调优判官评分权重
3. build_argument_performance_db(): 沉淀论据绩效库

用法:
    from attribution_analyzer import ShapleyAttribution, ArgumentPerformanceDB
    
    attr = ShapleyAttribution()
    result = attr.analyze(trade_record)
    # → {"technical": 0.45, "fundamental": 0.30, "chain": 0.15, "sentiment": 0.10}
    
    db = ArgumentPerformanceDB()
    db.record_argument("RB", "inventory_logic", profit=500, loss=0)
    perf = db.get_performance("RB", "inventory_logic")
    # → {"win_rate": 0.65, "profit_factor": 2.1, "samples": 20}
"""

import os, json, math
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict
from pathlib import Path


class ShapleyAttribution:
    """Shapley值归因分析器，量化各维度对交易盈亏的贡献占比。"""
    
    # 归因维度定义
    DIMENSIONS = ["technical", "fundamental", "chain", "sentiment"]
    
    def __init__(self, history_window: int = 30):
        """
        Args:
            history_window: 历史样本窗口（用于估计各维度贡献）
        """
        self.history_window = history_window
    
    def analyze(self, trade_record: Dict[str, Any]) -> Dict[str, float]:
        """
        对单笔交易进行Shapley归因分析。
        
        简化版Shapley值计算：假设各维度贡献独立可加，根据历史表现加权。
        
        Args:
            trade_record: {
                "symbol": str,
                "pnl": float,              # 盈亏金额
                "technical_score": float,    # 技术面评分(0-100)
                "fundamental_score": float,  # 基本面评分(0-100)
                "chain_score": float,        # 产业链评分(0-100)
                "sentiment_score": float,    # 情感评分(0-100)
                "direction": int,            # 1=多, -1=空
            }
        
        Returns:
            {dimension: shapley_value}，sum ≈ 1.0
        """
        scores = {
            "technical": trade_record.get("technical_score", 50),
            "fundamental": trade_record.get("fundamental_score", 50),
            "chain": trade_record.get("chain_score", 50),
            "sentiment": trade_record.get("sentiment_score", 50),
        }
        
        pnl = trade_record.get("pnl", 0)
        direction = trade_record.get("direction", 1)
        
        # 简化Shapley：按评分比例分配贡献（归一化）
        total = sum(scores.values())
        if total == 0:
            return {dim: 0.25 for dim in self.DIMENSIONS}
        
        # 考虑方向：若实际盈亏与方向一致，则各维度贡献为正；否则为负
        alignment = 1 if (pnl * direction > 0) else -1 if pnl != 0 else 0
        
        attributions = {}
        for dim, score in scores.items():
            base_share = score / total
            # 若盈亏与方向不一致，该维度贡献可能为负（惩罚失效维度）
            attributions[dim] = round(base_share * alignment, 4) if alignment != 0 else round(base_share, 4)
        
        return attributions
    
    def batch_analyze(self, trade_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量归因分析，输出各维度历史平均贡献。
        
        Returns:
            {
                "avg_contribution": {dim: float},
                "winning_contribution": {dim: float},  # 盈利交易中各维度贡献
                "losing_contribution": {dim: float},   # 亏损交易中各维度贡献
                "recommendation": str,                  # 权重调整建议
            }
        """
        if not trade_records:
            return {}
        
        all_attr = {dim: [] for dim in self.DIMENSIONS}
        win_attr = {dim: [] for dim in self.DIMENSIONS}
        loss_attr = {dim: [] for dim in self.DIMENSIONS}
        
        for record in trade_records:
            attr = self.analyze(record)
            pnl = record.get("pnl", 0)
            for dim, val in attr.items():
                all_attr[dim].append(val)
                if pnl > 0:
                    win_attr[dim].append(val)
                elif pnl < 0:
                    loss_attr[dim].append(val)
        
        avg = {dim: round(sum(vals)/max(len(vals),1), 4) for dim, vals in all_attr.items()}
        win_avg = {dim: round(sum(vals)/max(len(vals),1), 4) for dim, vals in win_attr.items()}
        loss_avg = {dim: round(sum(vals)/max(len(vals),1), 4) for dim, vals in loss_attr.items()}
        
        # 生成权重调整建议
        recommendations = []
        for dim in self.DIMENSIONS:
            if win_avg.get(dim, 0) > loss_avg.get(dim, 0) + 0.1:
                recommendations.append(f"{dim}: 盈利贡献高，建议提升权重")
            elif loss_avg.get(dim, 0) > win_avg.get(dim, 0) + 0.1:
                recommendations.append(f"{dim}: 亏损贡献高，建议降低权重")
        
        return {
            "avg_contribution": avg,
            "winning_contribution": win_avg,
            "losing_contribution": loss_avg,
            "recommendation": "; ".join(recommendations) if recommendations else "各维度表现均衡，维持当前权重",
        }


class ArgumentPerformanceDB:
    """论据绩效库：统计不同品种下各类论证模式的胜率、盈亏比。"""
    
    ARGUMENT_TYPES = [
        "inventory_logic",      # 库存逻辑
        "trend_resonance",      # 趋势共振
        "volume_breakout",      # 量价突破
        "support_resistance",   # 支撑阻力
        "fundamental_reversal", # 基本面反转
        "chain_verification",   # 产业链验证
        "macro_shock",          # 宏观冲击
        "sentiment_extreme",    # 情感极端
    ]
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            base = Path(__file__).parent.parent / "memory"
            base.mkdir(exist_ok=True)
            self.db_path = base / "argument_performance.json"
        else:
            self.db_path = Path(db_path)
        
        self._data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        if self.db_path.exists():
            with open(self.db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"records": {}, "stats": {}, "last_updated": ""}
    
    def _save(self):
        self._data["last_updated"] = datetime.now().isoformat()
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
    
    def record_argument(self, symbol: str, argument_type: str, profit: float = 0, loss: float = 0, pnl: float = None):
        """
        记录一次论据的表现。
        
        Args:
            symbol: 品种代码
            argument_type: 论据类型（如 "inventory_logic"）
            profit: 盈利金额（若pnl>0）
            loss: 亏损金额（若pnl<0，取绝对值）
            pnl: 净盈亏（优先使用）
        """
        if pnl is not None:
            profit = pnl if pnl > 0 else 0
            loss = abs(pnl) if pnl < 0 else 0
        
        key = f"{symbol}_{argument_type}"
        if key not in self._data["records"]:
            self._data["records"][key] = {
                "symbol": symbol,
                "argument_type": argument_type,
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "samples": 0,
            }
        
        rec = self._data["records"][key]
        rec["samples"] += 1
        if profit > 0:
            rec["wins"] += 1
            rec["total_profit"] += profit
        elif loss > 0:
            rec["losses"] += 1
            rec["total_loss"] += loss
        
        self._save()
    
    def get_performance(self, symbol: str, argument_type: str) -> Dict[str, Any]:
        """
        获取某品种某论据类型的绩效统计。
        
        Returns:
            {
                "win_rate": float,         # 胜率
                "profit_factor": float,     # 盈亏比
                "avg_profit": float,       # 平均盈利
                "avg_loss": float,         # 平均亏损
                "samples": int,             # 样本数
                "expectancy": float,        # 期望值
            }
        """
        key = f"{symbol}_{argument_type}"
        rec = self._data["records"].get(key, {})
        
        wins = rec.get("wins", 0)
        losses = rec.get("losses", 0)
        samples = rec.get("samples", 0)
        total_profit = rec.get("total_profit", 0)
        total_loss = rec.get("total_loss", 0)
        
        if samples == 0:
            return {"win_rate": 0, "profit_factor": 0, "samples": 0}
        
        win_rate = wins / samples
        avg_profit = total_profit / max(wins, 1)
        avg_loss = total_loss / max(losses, 1)
        profit_factor = total_profit / max(total_loss, 1)
        expectancy = (win_rate * avg_profit) - ((1 - win_rate) * avg_loss)
        
        return {
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 2),
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "samples": samples,
            "expectancy": round(expectancy, 2),
        }
    
    def get_top_arguments(self, symbol: str, min_samples: int = 5, top_n: int = 3) -> List[Dict[str, Any]]:
        """
        获取某品种最有效的论据类型。
        
        Returns:
            [{"argument_type": str, "win_rate": float, "profit_factor": float}, ...]
        """
        results = []
        for arg_type in self.ARGUMENT_TYPES:
            perf = self.get_performance(symbol, arg_type)
            if perf["samples"] >= min_samples:
                results.append({
                    "argument_type": arg_type,
                    **perf,
                })
        
        # 按期望值排序
        results.sort(key=lambda x: x.get("expectancy", 0), reverse=True)
        return results[:top_n]


class JudgeWeightUpdater:
    """判官评分权重动态更新器。"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            base = Path(__file__).parent.parent / "memory"
            base.mkdir(exist_ok=True)
            self.db_path = base / "judge_weights.json"
        else:
            self.db_path = Path(db_path)
        
        self._weights = self._load()
    
    def _load(self) -> Dict[str, float]:
        if self.db_path.exists():
            with open(self.db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        # 默认权重
        return {
            "technical": 0.25,
            "fundamental": 0.25,
            "chain": 0.25,
            "sentiment": 0.25,
            "last_updated": datetime.now().isoformat(),
        }
    
    def _save(self):
        self._weights["last_updated"] = datetime.now().isoformat()
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self._weights, f, ensure_ascii=False, indent=2)
    
    def update_from_attribution(self, attribution_result: Dict[str, float], learning_rate: float = 0.1):
        """
        根据归因结果动态更新权重。
        
        Args:
            attribution_result: {dimension: contribution}，来自ShapleyAttribution
            learning_rate: 学习率（默认0.1，保守更新）
        """
        for dim in ["technical", "fundamental", "chain", "sentiment"]:
            if dim in attribution_result:
                old_w = self._weights.get(dim, 0.25)
                contrib = attribution_result[dim]
                # 贡献为正 → 提升权重；贡献为负 → 降低权重
                new_w = old_w + learning_rate * contrib
                # 限制在合理范围 [0.05, 0.50]
                self._weights[dim] = round(max(0.05, min(0.50, new_w)), 4)
        
        # 归一化
        total = sum(self._weights.get(d, 0) for d in ["technical", "fundamental", "chain", "sentiment"])
        if total > 0:
            for dim in ["technical", "fundamental", "chain", "sentiment"]:
                self._weights[dim] = round(self._weights.get(dim, 0) / total, 4)
        
        self._save()
    
    def get_weights(self) -> Dict[str, float]:
        """获取当前权重。"""
        return {k: v for k, v in self._weights.items() if not k.startswith("_")}


if __name__ == "__main__":
    # 测试Shapley归因
    attr = ShapleyAttribution()
    result = attr.analyze({
        "symbol": "RB",
        "pnl": 500,
        "technical_score": 80,
        "fundamental_score": 60,
        "chain_score": 70,
        "sentiment_score": 40,
        "direction": 1,
    })
    print(f"Shapley归因: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # 测试论据绩效库
    db = ArgumentPerformanceDB()
    db.record_argument("RB", "inventory_logic", pnl=500)
    db.record_argument("RB", "inventory_logic", pnl=-200)
    db.record_argument("RB", "trend_resonance", pnl=300)
    perf = db.get_performance("RB", "inventory_logic")
    print(f"论据绩效: {json.dumps(perf, ensure_ascii=False, indent=2)}")
    
    # 测试权重更新
    updater = JudgeWeightUpdater()
    updater.update_from_attribution(result, learning_rate=0.1)
    print(f"更新后权重: {json.dumps(updater.get_weights(), ensure_ascii=False, indent=2)}")
