#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDT 鲁棒性 Layer 2: 辩论编排器 v1.0
熔断+重试+降级核心逻辑。不替代团队主管，提供鲁棒性脚手架。

Phase Gate机制:
  P3_guanlan → validate → pass/fail → retry(1)/降级
  P3_tanyuan → validate → pass/fail → retry(1)/降级
  P4_zhengzhen → validate → pass/fail → retry(1)/降级
  P4_zhensi → validate → pass/fail → retry(1)/降级
  P5_judge → validate → pass/fail → retry(2)/D06降级

用法: python debate_orchestrator.py --workspace C:\path\to\Signal [--auto-fallback]
"""

import json, os, sys, time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 导入Layer 1校验器
try:
    from validate_agent_output import validate, SCHEMAS
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from validate_agent_output import validate, SCHEMAS


class DebatePhaseGate:
    """辩论阶段门禁——检查某个阶段的产出是否就绪且合法"""

    def __init__(self, phase: str, output_path: str, max_retries: int = 2, fallback_func=None):
        self.phase = phase
        self.output_path = output_path
        self.max_retries = max_retries
        self.fallback_func = fallback_func
        self.retry_count = 0
        self.history: List[Dict] = []

    def check(self) -> Tuple[bool, str]:
        """检查产出文件是否就绪+合法。返回 (ready, status_msg)"""
        if not os.path.exists(self.output_path):
            return False, f"文件不存在: {self.output_path}"

        result = validate(self.output_path, self.phase)
        self.history.append(result)

        if result["pass"]:
            return True, f"✅ {self.phase} 校验通过"
        elif result["grade"] == "FATAL":
            return False, f"❌ {self.phase} 致命错误: {result['errors'][:3]}"
        else:
            return False, f"⚠️ {self.phase} 需重试: {result['errors'][:3]}"

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def record_retry(self):
        self.retry_count += 1

    def status(self) -> dict:
        return {
            "phase": self.phase,
            "output": self.output_path,
            "retries": self.retry_count,
            "max_retries": self.max_retries,
            "history": self.history[-3:] if self.history else []
        }


class DebateOrchestrator:
    """辩论编排器——管理P3-P5全流程门禁"""

    def __init__(self, workspace: str, signals_file: str = None):
        self.workspace = workspace
        self.commodities_dir = os.path.join(workspace, "Commodities")
        self.signals_file = signals_file or os.path.join(workspace, "Commodities", "debate_trigger.json")
        self.gates: Dict[str, DebatePhaseGate] = {}
        self.log: List[dict] = []
        self.degraded = False

    def _log(self, level: str, msg: str):
        entry = {"time": datetime.now().isoformat(), "level": level, "msg": msg}
        self.log.append(entry)
        if level in ("ERROR", "FATAL", "DEGRADE"):
            print(f"  [{level}] {msg}")

    def load_signals(self) -> Optional[dict]:
        """加载触发信号文件"""
        if not os.path.exists(self.signals_file):
            self._log("WARN", f"信号文件不存在: {self.signals_file}")
            return None
        try:
            with open(self.signals_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._log("INFO", f"加载信号: {data.get('signal_count', 0)}个品种")
            return data
        except Exception as e:
            self._log("ERROR", f"信号文件解析失败: {e}")
            return None

    def register_gate(self, phase: str, output_path: str, max_retries: int = 2, fallback_func=None):
        """注册一个阶段门禁"""
        self.gates[phase] = DebatePhaseGate(phase, output_path, max_retries, fallback_func)

    def setup_standard_gates(self, symbols: List[str]):
        """为给定品种设置标准门禁"""
        base = self.commodities_dir

        # P3 研究员
        self.register_gate("P3_guanlan", os.path.join(base, "p3_guanlan.json"), max_retries=1)
        self.register_gate("P3_tanyuan", os.path.join(base, "p3_tanyuan.json"), max_retries=1)

        # P4 辩手
        self.register_gate("P4_zhengzhen", os.path.join(base, "p4_zhengzhen.json"), max_retries=1)
        self.register_gate("P4_zhensi", os.path.join(base, "p4_zhensi.json"), max_retries=1)

        # P5 闫判官 (最多2次重试)
        self.register_gate("P5_judge", os.path.join(base, "p5_judge.json"), max_retries=2)

    def wait_and_check(self, phase: str, timeout_seconds: int = 120, poll_interval: int = 15) -> Tuple[bool, str]:
        """轮询等待文件就绪+校验。返回 (ready, msg)"""
        gate = self.gates.get(phase)
        if not gate:
            return False, f"未注册的phase: {phase}"

        deadline = time.time() + timeout_seconds
        last_check_msg = ""

        while time.time() < deadline:
            ready, msg = gate.check()
            if ready:
                return True, msg

            if msg != last_check_msg:
                self._log("INFO", f"{phase}: {msg}")
                last_check_msg = msg

            # 如果文件还不存在，等下一轮
            if not os.path.exists(gate.output_path):
                time.sleep(poll_interval)
                continue

            # 文件存在但不合法 → 可以重试就让agent修复
            if gate.can_retry():
                gate.record_retry()
                self._log("WARN", f"{phase} 第{gate.retry_count}次重试...")
                return False, f"REQUIRES_RETRY: {msg}"  # 调用方需重新spawn agent
            else:
                return False, f"RETRIES_EXHAUSTED: {msg}"

        return False, f"TIMEOUT: {timeout_seconds}秒内文件未就绪"

    def degrade_judge(self, symbols: List[str], research_dir: str) -> Optional[str]:
        """
        D06降级: 闫判官不可用 → 明鉴秋基于P3/P4论据独立裁决。
        返回降级裁决文件路径，失败返回None。
        """
        self.degraded = True
        self._log("DEGRADE", "⚡ 触发D06降级——闫判官不可用，明鉴秋基于双方论据独立裁决")

        # 读P3/P4产出
        try:
            from validate_agent_output import validate as vfn
            # 检查前置阶段全部通过
            for ph in ["P3_guanlan", "P3_tanyuan", "P4_zhengzhen", "P4_zhensi"]:
                fp = os.path.join(research_dir, f"{ph.lower()}.json".replace("p3_", "p3_").replace("p4_", "p4_"))
                if not os.path.exists(fp):
                    self._log("FATAL", f"降级失败: 前置文件缺失 {fp}")
                    return None

            # 写入降级标记
            degrade_log = os.path.join(research_dir, "p5_degrade.log")
            with open(degrade_log, 'w', encoding='utf-8') as f:
                f.write(f"P5降级 @ {datetime.now().isoformat()}\n")
                f.write(f"闫判官spawn {self.gates.get('P5_judge', type('',(),{'retry_count':0})()).retry_count}次失败\n")
                f.write("降级裁决需由明鉴秋(团队主管)完成\n")

            self._log("INFO", f"降级日志: {degrade_log}")
            return degrade_log
        except Exception as e:
            self._log("FATAL", f"降级失败: {e}")
            return None

    def run_flow_report(self) -> dict:
        """生成流程执行报告"""
        return {
            "workspace": self.workspace,
            "gates": {ph: g.status() for ph, g in self.gates.items()},
            "degraded": self.degraded,
            "log_count": len(self.log),
            "errors": [l for l in self.log if l["level"] in ("ERROR", "FATAL")]
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FDT辩论编排器")
    parser.add_argument("--workspace", "-w", default=os.getcwd(), help="工作空间路径")
    parser.add_argument("--symbols", "-s", nargs="*", default=[], help="辩论品种")
    parser.add_argument("--check-only", action="store_true", help="仅检查所有阶段状态")
    parser.add_argument("--auto-fallback", action="store_true", help="P5失败自动触发D06降级")
    args = parser.parse_args()

    orch = DebateOrchestrator(args.workspace)
    orch.setup_standard_gates(args.symbols or ["BU", "EC"])

    if args.check_only:
        print("\n=== 阶段状态检查 ===")
        all_ok = True
        for ph, gate in orch.gates.items():
            ready, msg = gate.check()
            icon = "✅" if ready else "❌" if "FATAL" in msg else "⚠️"
            print(f"  {icon} {ph}: {msg}")
            if not ready:
                all_ok = False
        print(f"\n总评: {'全通过' if all_ok else '有未通过阶段'}")
    else:
        # 完整流程
        signals = orch.load_signals()
        if not signals:
            print("无信号文件 → 跳过编排")
            sys.exit(0)

        print(f"\n=== 辩论编排启动 ===")
        print(f"  品种: {[s['symbol'] for s in signals.get('signals', [])]}")
        print(f"  阶段数: {len(orch.gates)}")

        # 各阶段检查
        for ph in ["P3_guanlan", "P3_tanyuan", "P4_zhengzhen", "P4_zhensi", "P5_judge"]:
            gate = orch.gates.get(ph)
            if not gate:
                continue
            if os.path.exists(gate.output_path):
                ready, msg = gate.check()
                print(f"  {'✅' if ready else '⚠️'} {ph}: {msg[:80]}")
            else:
                print(f"  ⏳ {ph}: 文件未生成")

    # 输出摘要
    print(json.dumps(orch.run_flow_report(), ensure_ascii=False, indent=2))
