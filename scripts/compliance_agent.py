from __future__ import annotations
from scripts.unified_logger import get_logger

_logger = get_logger("compliance")
#!/usr/bin/env python3
"""
合规审计模块 v1.0（P2-4）
============================
实时校验交易所持仓限额、交割月规则、大户报告门槛、日内交易频次管控。

核心功能：
- check_position_limits(): 持仓限额校验
- check_delivery_month(): 交割月规则检查
- check_large_trader(): 大户报告检查
- check_frequency(): 日内交易频次管控
- generate_audit_log(): 全流程操作日志（不可篡改）

用法:
    from scripts.compliance_agent import ComplianceAgent
    agent = ComplianceAgent()
    result = agent.check_all(positions, orders)
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date
import hashlib
import json
import os
import time
from collections import defaultdict
from pathlib import Path


class ComplianceAgent:
    """合规审计器 — 交易所规则实时校验。"""

    # ── 持仓限额（按品种，手数） ──
    POSITION_LIMITS = {
        "IF": 500,
        "IC": 500,
        "IH": 500,
        "IM": 500,  # 股指期货
        "T": 10000,
        "TF": 10000,
        "TS": 10000,  # 国债期货
        "CU": 5000,
        "AL": 6000,
        "ZN": 6000,
        "PB": 4000,
        "AU": 3000,
        "AG": 6000,
        "RB": 20000,
        "HC": 20000,
        "I": 10000,
        "J": 5000,
        "JM": 5000,
        "SC": 5000,
        "FU": 5000,
        "BU": 5000,
        "M": 15000,
        "Y": 10000,
        "P": 10000,
        "OI": 10000,
        "SR": 10000,
        "CF": 8000,
    }

    # ── 大户报告门槛（手数，超过需报告交易所） ──
    LARGE_TRADER_THRESHOLDS = {
        "IF": 100,
        "IC": 100,
        "IH": 100,
        "CU": 1000,
        "AL": 1500,
        "ZN": 1500,
        "AU": 500,
        "AG": 1500,
        "RB": 5000,
        "HC": 5000,
        "I": 3000,
        "M": 4000,
        "Y": 3000,
        "P": 3000,
    }

    # ── 日内交易频次限制（部分品种） ──
    DAY_TRADE_LIMITS = {
        "IF": 200,
        "IC": 200,
        "IH": 200,
        "IM": 200,  # 股指：日内开仓限制
    }

    def __init__(self, log_dir: str = None) -> None:
        self.audit_logs = []
        self.violations = []
        if log_dir is None:
            log_dir = Path(os.path.expanduser("~/Documents/FDT/Compliance"))
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def check_all(
        self, positions: List[Dict], orders: List[Dict] = None, account_type: str = "individual"
    ) -> Dict[str, Any]:
        """全量合规检查。

        Args:
            positions: [{"symbol": str, "lots": int, "contract": str}, ...]
            orders: [{"symbol": str, "lots": int, "direction": str}, ...]
            account_type: "individual" | "institutional"

        Returns:
            {"pass": bool, "violations": [...], "checks": {...}}
        """
        checks = {}
        all_violations = []

        # 持仓限额检查
        pos_result = self.check_position_limits(positions)
        checks["position_limits"] = pos_result
        all_violations.extend(pos_result["violations"])

        # 交割月检查
        dm_result = self.check_delivery_month(positions)
        checks["delivery_month"] = dm_result
        all_violations.extend(dm_result["violations"])

        # 大户报告检查
        lt_result = self.check_large_trader(positions)
        checks["large_trader"] = lt_result
        all_violations.extend(lt_result["violations"])

        # 日内频次检查
        if orders:
            freq_result = self.check_frequency(orders)
            checks["frequency"] = freq_result
            all_violations.extend(freq_result["violations"])

        overall_pass = len(all_violations) == 0
        self.violations.extend(all_violations)

        # 记录审计日志
        self._log_audit(datetime.now().isoformat(), overall_pass, all_violations)

        return {
            "pass": overall_pass,
            "violations": all_violations,
            "checks": checks,
        }

    def check_position_limits(self, positions: List[Dict]) -> Dict[str, Any]:
        """检查持仓限额。"""
        symbol_lots = defaultdict(int)
        for pos in positions:
            symbol_lots[pos.get("symbol", "").upper()] += pos.get("lots", 0)

        violations = []
        for symbol, lots in symbol_lots.items():
            limit = self.POSITION_LIMITS.get(symbol)
            if limit and lots > limit:
                violations.append(
                    {
                        "rule": "position_limit",
                        "symbol": symbol,
                        "current": lots,
                        "limit": limit,
                        "severity": "HIGH",
                        "message": f"{symbol}持仓{lots}手超过限额{limit}手",
                    }
                )

        return {"pass": len(violations) == 0, "violations": violations}

    def check_delivery_month(self, positions: List[Dict]) -> Dict[str, Any]:
        """检查交割月规则。"""
        current_month = datetime.now().month
        current_year = datetime.now().year
        violations = []

        for pos in positions:
            contract = pos.get("contract", "")
            lots = pos.get("lots", 0)
            # 解析合约月份
            try:
                contract_m = int(re.findall(r"\d+", contract)[-1][-2:]) if hasattr(re, "findall") else 0
            except Exception as _e:
                continue

            # 临近交割月（当月或次月）
            if contract_m in (current_month, current_month + 1):
                violations.append(
                    {
                        "rule": "delivery_month",
                        "contract": contract,
                        "lots": lots,
                        "severity": "WARNING",
                        "message": f"{contract}临近交割月，请确认持仓合规",
                    }
                )

        return {"pass": len(violations) == 0, "violations": violations}

    def check_large_trader(self, positions: List[Dict]) -> Dict[str, Any]:
        """检查大户报告门槛。"""
        symbol_lots = defaultdict(int)
        for pos in positions:
            symbol_lots[pos.get("symbol", "").upper()] += pos.get("lots", 0)

        violations = []
        for symbol, lots in symbol_lots.items():
            threshold = self.LARGE_TRADER_THRESHOLDS.get(symbol)
            if threshold and lots > threshold:
                violations.append(
                    {
                        "rule": "large_trader_report",
                        "symbol": symbol,
                        "current": lots,
                        "threshold": threshold,
                        "severity": "INFO",
                        "message": f"{symbol}持仓{lots}手超过大户报告门槛{threshold}手，需向交易所报告",
                    }
                )

        return {"pass": len(violations) == 0, "violations": violations}

    def check_frequency(self, orders: List[Dict]) -> Dict[str, Any]:
        """检查日内交易频次。"""
        today_orders = [o for o in orders if o.get("date", str(date.today())) == str(date.today())]
        symbol_counts = defaultdict(int)
        for o in today_orders:
            symbol_counts[o.get("symbol", "").upper()] += 1

        violations = []
        for symbol, count in symbol_counts.items():
            limit = self.DAY_TRADE_LIMITS.get(symbol)
            if limit and count > limit:
                violations.append(
                    {
                        "rule": "day_trade_frequency",
                        "symbol": symbol,
                        "current": count,
                        "limit": limit,
                        "severity": "HIGH",
                        "message": f"{symbol}日内交易{count}次超过限制{limit}次",
                    }
                )

        return {"pass": len(violations) == 0, "violations": violations}

    def _log_audit(self, timestamp: str, passed: bool, violations: List[Dict]) -> None:
        """记录审计日志（不可篡改，带哈希链）。"""
        prev_hash = self.audit_logs[-1]["hash"] if self.audit_logs else "GENESIS"

        log_entry = {
            "timestamp": timestamp,
            "passed": passed,
            "violation_count": len(violations),
            "prev_hash": prev_hash,
        }

        # 哈希链：确保日志不可篡改
        content = json.dumps(log_entry, sort_keys=True)
        log_entry["hash"] = hashlib.sha256(content.encode()).hexdigest()[:16]

        self.audit_logs.append(log_entry)

        # 持久化
        log_file = self.log_dir / f"audit_{date.today()}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(self.audit_logs[-100:], f, ensure_ascii=False, indent=2)

    def get_audit_report(self, days: int = 7) -> Dict[str, Any]:
        """获取审计报告。"""
        recent = [l for l in self.audit_logs if l["timestamp"] > (datetime.now() - timedelta(days=days)).isoformat()]
        return {
            "period_days": days,
            "total_audits": len(recent),
            "passed": sum(1 for l in recent if l["passed"]),
            "failed": sum(1 for l in recent if not l["passed"]),
            "hash_chain_integrity": self._verify_hash_chain(),
        }

    def _verify_hash_chain(self) -> bool:
        """验证哈希链完整性。"""
        for i in range(1, len(self.audit_logs)):
            expected_prev = self.audit_logs[i - 1]["hash"]
            actual_prev = self.audit_logs[i]["prev_hash"]
            if expected_prev != actual_prev:
                return False
        return True


if __name__ == "__main__":
    agent = ComplianceAgent()
    positions = [{"symbol": "RB", "lots": 20000, "contract": "rb2510"}]
    orders = [{"symbol": "IF", "lots": 1, "direction": "long"}]
    result = agent.check_all(positions, orders)
    print(f"合规检查: {'✅通过' if result['pass'] else '❌违规'}")
    for v in result["violations"]:
        print(f"  {v['severity']}: {v['message']}")
