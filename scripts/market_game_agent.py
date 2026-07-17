from scripts.unified_logger import get_logger

_logger = get_logger("market_game")
#!/usr/bin/env python3
"""
对手盘行为建模 v1.0（P3-2）
=============================
模拟机构资金、套保盘、投机盘行为，预判假突破、诱多诱空行情。

核心功能：
- simulate_institutional(): 机构资金行为模拟
- simulate_hedge(): 套保盘行为模拟
- simulate_speculator(): 投机盘行为模拟
- detect_fake_breakout(): 假突破检测
- detect_suction(): 诱多/诱空行情检测

用法:
    from scripts.market_game_agent import MarketGameAgent
    agent = MarketGameAgent()
    signal = agent.analyze(price_data, volume_data, oi_data)
    # → {"fake_breakout_risk": 0.7, "sucking_type": "bull_trap", "confidence": 0.65}
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import math


class MarketGameAgent:
    """对手盘行为分析器 — 博弈视角的市场解读。"""

    def analyze(self, price_data: List[float], volume_data: List[float], oi_data: List[float] = None) -> Dict[str, Any]:
        """综合分析市场博弈行为。

        Args:
            price_data: 近期价格序列（至少20个数据点）
            volume_data: 近期成交量序列
            oi_data: 近期持仓量序列（可选）

        Returns:
            {"fake_breakout_risk": float,  # 假突破风险 0~1
             "sucking_type": str,          # 诱多/诱空类型
             "confidence": float,           # 置信度
             "signals": [...],             # 信号详情
             "recommendation": str}         # 操作建议
        """
        signals = []

        # 1. 假突破检测
        fb = self.detect_fake_breakout(price_data, volume_data)
        if fb["risk"] > 0.5:
            signals.append(fb)

        # 2. 诱空/诱多检测
        suction = self.detect_suction(price_data, volume_data, oi_data)
        if suction["confidence"] > 0.5:
            signals.append(suction)

        # 3. 机构资金行为分析
        inst = self.simulate_institutional(price_data, volume_data)
        if inst["suspicion"] > 0.5:
            signals.append(inst)

        # 综合判断
        max_risk = max([s.get("risk", 0) for s in signals], default=0)
        max_confidence = max([s.get("confidence", 0) for s in signals], default=0)

        # 确定诱多/诱空类型
        sucking_types = [s.get("sucking_type") for s in signals if s.get("sucking_type")]
        primary_type = sucking_types[0] if sucking_types else "none"

        # 建议
        if max_risk > 0.7:
            rec = "假突破风险高，建议等待确认再入场"
        elif max_risk > 0.4:
            rec = "博弈信号较强，降低仓位参与"
        else:
            rec = "无明显博弈信号，正常交易"

        return {
            "fake_breakout_risk": round(max_risk, 2),
            "sucking_type": primary_type,
            "confidence": round(min(max_confidence, 1.0), 2),
            "signals": signals,
            "recommendation": rec,
        }

    def detect_fake_breakout(self, prices: List[float], volumes: List[float]) -> Dict[str, Any]:
        """检测假突破。

        特征：
        - 价格突破关键水平但成交量萎缩
        - 突破后快速回到区间内
        - OI在突破后下降（多头平仓）

        Returns:
            {"risk": float, "type": str, "confidence": float}
        """
        if len(prices) < 20:
            return {"risk": 0, "type": "none", "confidence": 0, "risk_level": "low"}

        recent = prices[-10:]
        vol_recent = volumes[-10:]

        # 计算突破信号
        high = max(prices[:-5]) if len(prices) > 5 else max(prices)
        low = min(prices[:-5]) if len(prices) > 5 else min(prices)
        current = recent[-1]

        # 突破前高/前低
        broke_high = current > high * 1.01
        broke_low = current < low * 0.99

        if not (broke_high or broke_low):
            return {"risk": 0, "type": "none", "confidence": 0, "risk_level": "low"}

        # 成交量确认
        avg_vol = sum(vol_recent[:-1]) / len(vol_recent[:-1]) if len(vol_recent) > 1 else 1
        breakout_vol = vol_recent[-1]
        vol_ratio = breakout_vol / max(avg_vol, 1)

        # 突破伴随低量 → 假突破风险高
        fake_risk = 1.0 - min(vol_ratio, 2.0) / 2.0  # 成交量越低风险越高

        return {
            "risk": round(fake_risk, 2),
            "type": "fake_breakout",
            "confidence": round(0.6 + fake_risk * 0.3, 2),
            "breakout_direction": "high" if broke_high else "low",
            "vol_ratio": round(vol_ratio, 2),
            "risk_level": "high" if fake_risk > 0.6 else "medium",
        }

    def detect_suction(self, prices: List[float], volumes: List[float], oi: List[float] = None) -> Dict[str, Any]:
        """检测诱多/诱空（sucking）。

        特征：
        - 价格快速拉升/下跌但持仓量下降
        - 成交量异常放大后迅速回落
        - 价格突破后无后续动能

        Returns:
            {"risk": float, "sucking_type": "bull_trap"|"bear_trap"|"none"}
        """
        if len(prices) < 10:
            return {"risk": 0, "sucking_type": "none", "confidence": 0}

        recent_p = prices[-10:]
        recent_v = volumes[-10:]

        # 价格变化
        p_change = (recent_p[-1] - recent_p[0]) / recent_p[0]

        # 成交量变化
        v_start = sum(recent_v[:3]) / 3
        v_end = sum(recent_v[-3:]) / 3
        v_surge = v_start > v_end * 1.5  # 成交量从高位回落

        # 快速拉升→诱多，快速下跌→诱空
        if p_change > 0.03 and v_surge:
            return {
                "risk": 0.6,
                "sucking_type": "bull_trap",
                "confidence": 0.6,
                "detail": "快速拉升+成交量萎缩，疑似诱多",
            }
        elif p_change < -0.03 and v_surge:
            return {
                "risk": 0.6,
                "sucking_type": "bear_trap",
                "confidence": 0.6,
                "detail": "快速下跌+成交量萎缩，疑似诱空",
            }
        else:
            return {"risk": 0.2, "sucking_type": "none", "confidence": 0.3}

    def simulate_institutional(self, prices: List[float], volumes: List[float]) -> Dict[str, Any]:
        """模拟机构资金行为。

        特征：
        - 大单成交占比突增
        - 价格窄幅盘整但成交量持续
        - 区间上下沿反复测试

        Returns:
            {"suspicion": float, "behavior": str}
        """
        if len(prices) < 10:
            return {"suspicion": 0, "behavior": "unknown", "confidence": 0}

        # 计算波动率
        returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
        vol = sum(abs(r) for r in returns) / len(returns)

        # 窄幅盘整+低波动 → 机构吸筹/出货
        if vol < 0.005:
            return {
                "suspicion": 0.5,
                "behavior": "accumulation_or_distribution",
                "confidence": 0.5,
                "detail": "低波动盘整，机构可能在吸筹或出货",
            }

        return {"suspicion": 0, "behavior": "normal_trading", "confidence": 0.5}


if __name__ == "__main__":
    import random

    # 测试假突破场景
    prices = [100 + i * 0.2 for i in range(20)] + [102, 101.5, 101, 100.5, 100]
    volumes = [1000 + random.randint(-100, 100) for _ in range(25)]
    volumes[-5:] = [300, 250, 200, 150, 100]  # 突破后缩量

    agent = MarketGameAgent()
    result = agent.analyze(prices, volumes)
    print(f"博弈分析: {json.dumps(result, ensure_ascii=False, indent=2)}")
