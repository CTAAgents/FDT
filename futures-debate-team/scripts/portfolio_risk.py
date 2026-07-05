from scripts.unified_logger import get_logger
_logger = get_logger("portfolio_risk")
#!/usr/bin/env python3
"""
组合风险计算器 — L6全局风控（P1-7）
========================================
在原有5层单合约风控基础上新增L6账户级全局风控：
- 行业集中度：单一产业链 ≤ 15% 总资金
- 跨品种相关性：|ρ|>0.7 同时开仓强制减半
- 账户回撤熔断：单日总亏损 > 2.5% 暂停新开仓
- 保证金占比：总保证金 ≤ 40% 账户资金

用法:
    from portfolio_risk import PortfolioRisk, calculate_portfolio_risk
    risk = calculate_portfolio_risk(
        positions=[{"symbol": "RB", "lots": 10, "margin": 5000, "chain": "black"}, ...],
        account_equity=1000000,
        daily_pnl=-5000,
    )
    # → {"concentration_ok": True, "correlation_ok": True, "drawdown_ok": False, ...}
"""

import json, math
from typing import Dict, List, Any
from collections import defaultdict


# ── 产业链映射 ──
CHAIN_MAP = {
    "RB": "black", "HC": "black", "I": "black", "J": "black", "JM": "black", "FG": "black",
    "M": "oilseeds", "Y": "oilseeds", "P": "oilseeds", "OI": "oilseeds", "RM": "oilseeds",
    "SR": "soft", "CF": "soft", "C": "grain", "CS": "grain", "A": "grain", "B": "grain",
    "AU": "precious", "AG": "precious",
    "CU": "nonferrous", "AL": "nonferrous", "ZN": "nonferrous", "NI": "nonferrous", "SN": "nonferrous",
    "SC": "energy", "FU": "energy", "BU": "energy", "L": "chemical", "PP": "chemical", "V": "chemical", "MA": "chemical", "TA": "chemical", "EG": "chemical", "EB": "chemical", "UR": "chemical", "SA": "chemical", "PF": "chemical", "PR": "chemical",
    "IF": "financial", "IC": "financial", "IH": "financial", "IM": "financial",
    "PK": "oilseeds", "LH": "livestock", "AP": "fruit",
}


class PortfolioRisk:
    """L6 组合全局风控计算器。"""
    
    # 风控阈值
    THRESHOLDS = {
        "max_chain_concentration": 0.15,   # 单一产业链 ≤ 15%
        "max_correlation_threshold": 0.70,  # 高相关阈值
        "max_daily_drawdown": 0.025,        # 单日回撤 ≤ 2.5%
        "max_total_margin_ratio": 0.40,     # 保证金占比 ≤ 40%
        "consecutive_loss_sleep": 3,        # 连续亏损3笔休眠
    }
    
    def __init__(self, account_equity: float, thresholds: Dict[str, float] = None):
        self.account_equity = account_equity
        self.thresholds = thresholds or self.THRESHOLDS
    
    def calculate(self, positions: List[Dict[str, Any]], daily_pnl: float = 0, consecutive_losses: int = 0) -> Dict[str, Any]:
        """
        计算组合风险指标。
        
        Args:
            positions: [{"symbol": str, "lots": int, "margin": float, "direction": int, "entry_price": float}, ...]
            daily_pnl: 当日总盈亏
            consecutive_losses: 连续亏损笔数
        
        Returns:
            {
                "concentration_ok": bool,      # 行业集中度检查
                "correlation_ok": bool,         # 相关性检查
                "drawdown_ok": bool,            # 回撤检查
                "margin_ok": bool,              # 保证金检查
                "consecutive_ok": bool,           # 连续亏损检查
                "overall": "green|yellow|red",  # 综合评级
                "veto_debate": bool,             # 是否否决辩论
                "details": {...},               # 详细指标
            }
        """
        results = {}
        
        # 1. 行业集中度检查
        results["concentration_ok"] = self._check_concentration(positions)
        
        # 2. 跨品种相关性检查
        results["correlation_ok"] = self._check_correlation(positions)
        
        # 3. 回撤检查
        results["drawdown_ok"] = self._check_drawdown(daily_pnl)
        
        # 4. 保证金占比检查
        results["margin_ok"] = self._check_margin(positions)
        
        # 5. 连续亏损检查
        results["consecutive_ok"] = consecutive_losses < self.thresholds["consecutive_loss_sleep"]
        
        # 综合评级
        all_ok = all([results["concentration_ok"], results["correlation_ok"], results["drawdown_ok"], results["margin_ok"], results["consecutive_ok"]])
        some_ok = sum([results["concentration_ok"], results["correlation_ok"], results["drawdown_ok"], results["margin_ok"], results["consecutive_ok"]])
        
        if all_ok:
            results["overall"] = "green"
        elif some_ok >= 3:
            results["overall"] = "yellow"
        else:
            results["overall"] = "red"
        
        # 独立否决权：回撤超限或连续亏损超限 → 直接否决
        results["veto_debate"] = not results["drawdown_ok"] or not results["consecutive_ok"]
        
        results["details"] = self._calc_details(positions, daily_pnl)
        
        return results
    
    def _check_concentration(self, positions: List[Dict[str, Any]]) -> bool:
        """检查单一产业链集中度。"""
        chain_values = defaultdict(float)
        for pos in positions:
            symbol = pos.get("symbol", "")
            chain = CHAIN_MAP.get(symbol, "other")
            chain_values[chain] += pos.get("margin", 0)
        
        max_concentration = max(chain_values.values()) / max(self.account_equity, 1) if chain_values else 0
        return max_concentration <= self.thresholds["max_chain_concentration"]
    
    def _check_correlation(self, positions: List[Dict[str, Any]]) -> bool:
        """检查高相关性合约是否同时开仓。"""
        # 简化：同产业链且方向相同 → 视为高相关
        chain_directions = defaultdict(list)
        for pos in positions:
            chain = CHAIN_MAP.get(pos.get("symbol", ""), "other")
            chain_directions[chain].append(pos.get("direction", 0))
        
        for chain, directions in chain_directions.items():
            if len(directions) > 1 and all(d == directions[0] for d in directions):
                # 同产业链同方向多品种 → 高相关风险
                return False
        return True
    
    def _check_drawdown(self, daily_pnl: float) -> bool:
        """检查单日回撤。"""
        drawdown_ratio = abs(daily_pnl) / max(self.account_equity, 1)
        return drawdown_ratio <= self.thresholds["max_daily_drawdown"]
    
    def _check_margin(self, positions: List[Dict[str, Any]]) -> bool:
        """检查保证金占比。"""
        total_margin = sum(pos.get("margin", 0) for pos in positions)
        margin_ratio = total_margin / max(self.account_equity, 1)
        return margin_ratio <= self.thresholds["max_total_margin_ratio"]
    
    def _calc_details(self, positions: List[Dict[str, Any]], daily_pnl: float) -> Dict[str, float]:
        """计算详细指标。"""
        chain_values = defaultdict(float)
        for pos in positions:
            symbol = pos.get("symbol", "")
            chain = CHAIN_MAP.get(symbol, "other")
            chain_values[chain] += pos.get("margin", 0)
        
        total_margin = sum(pos.get("margin", 0) for pos in positions)
        
        return {
            "max_chain_concentration": round(max(chain_values.values()) / max(self.account_equity, 1), 4) if chain_values else 0,
            "total_margin_ratio": round(total_margin / max(self.account_equity, 1), 4),
            "daily_drawdown_ratio": round(abs(daily_pnl) / max(self.account_equity, 1), 4),
            "position_count": len(positions),
        }


def calculate_portfolio_risk(
    positions: List[Dict[str, Any]],
    account_equity: float,
    daily_pnl: float = 0,
    consecutive_losses: int = 0,
    thresholds: Dict[str, float] = None,
) -> Dict[str, Any]:
    """便捷函数：计算组合风险。"""
    pr = PortfolioRisk(account_equity, thresholds)
    return pr.calculate(positions, daily_pnl, consecutive_losses)


if __name__ == "__main__":
    positions = [
        {"symbol": "RB", "lots": 10, "margin": 15000, "direction": 1},
        {"symbol": "HC", "lots": 5, "margin": 8000, "direction": 1},
        {"symbol": "I", "lots": 3, "margin": 12000, "direction": 1},
    ]
    result = calculate_portfolio_risk(positions, account_equity=100000, daily_pnl=-2000)
    print(f"组合风险: {json.dumps(result, ensure_ascii=False, indent=2)}")
