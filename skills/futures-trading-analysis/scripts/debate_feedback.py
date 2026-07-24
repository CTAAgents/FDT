#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
辩论反馈中央路由器 v1.0 — 多Agent辩论系统的自我进化引擎

每个辩论Agent产出中附带 ###FEEDBACK 段，由协调器提取后路由到对应skill修复。
反馈链路闭环：Agent发现 → 路由到skill → 自动修复 → 规则沉淀 → 永不再犯。

架构:
  Agent产出(###FEEDBACK段)
      ↓
  FeedbackRouter.extract() — 解析反馈条目
      ↓
  FeedbackRouter.route()   — 按domain路由到对应skill的feedback模块
      ↓
  ├── domain='data'        → futures-data-search/data_feedback.py
  ├── domain='indicator'   → technical-indicator-calc/indicator_feedback.py
  ├── domain='chain'       → commodity-chain-analysis/chain_feedback.py
  ├── domain='debate'      → 本模块 (commodity-daily-analysis 自反馈)
  └── domain='report'      → 报告生成缺陷
      ↓
  FeedbackRouter.learn()   — 提取经验，反馈到Agent Prompt中

用法:
  python debate_feedback.py route   # 扫描所有Agent产出中的###FEEDBACK段并路由
  python debate_feedback.py report  # 输出反馈统计
  python debate_feedback.py lessons # 输出经验教训（可嵌入Agent Prompt）
"""

import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WS = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE") or os.path.join(os.path.expanduser("~"), "Documents", "FDT", "Reports")
WORKSPACE_DIR = _WS
FEEDBACK_DIR = os.path.join(os.path.expanduser("~"), "logs", "feedback")
FEEDBACK_LOG = os.path.join(FEEDBACK_DIR, "debate_feedback.jsonl")
LESSONS_FILE = os.path.join(FEEDBACK_DIR, "lessons_learned.json")
PROMPT_INJECTION_FILE = os.path.join(FEEDBACK_DIR, "agent_prompt_injection.md")


# ============================================================
# 反馈Schema — 每个Agent产出中 ###FEEDBACK 段的标准格式
# ============================================================
# 格式（每行一条，可直接嵌入Agent Prompt）：
#   ###FEEDBACK
#   <VARIETY> | <ISSUE_TYPE> | <DOMAIN> | <SEVERITY> | <DESCRIPTION>
#   <VARIETY> | data_missing  | data     | high   | 品种OI缺失，无法验证资金面
#   <VARIETY> | calc_error    | indicator| high   | 指标计算使用倒序数据，金叉判断反转
#   ALL      | material_gap  | debate   | medium | 缺失跨期价差历史Z分数，无法判断套利
#   ALL      | chain_gap     | chain    | medium | 纯碱产业链分类缺失，应归入建材链
#   ###END_FEEDBACK

FEEDBACK_PATTERN = re.compile(r"###FEEDBACK\s*\n(.*?)\n\s*###END_FEEDBACK", re.DOTALL)

# 可识别的反馈类型
VALID_ISSUE_TYPES = {
    # 数据类
    "data_missing",
    "data_anomaly",
    "data_stale",
    "data_conflict",
    "far_price_zero",
    "term_structure_missing",
    "oi_missing",
    "oi_divergence",
    # 指标类
    "calc_error",
    "indicator_missing",
    "indicator_accuracy",
    "golden_cross_error",
    "rsi_out_of_range",
    "adx_zero",
    # 辩论类
    "material_gap",
    "chain_gap",
    "rule_coverage_gap",
    "prompt_ambiguity",
    "agent_timeout",
    "format_error",
}

# ============================================================
# 路由表 — domain → 目标skill + 修复模块
# ============================================================
ROUTING_TABLE = {
    "data": {
        "skill": "futures-data-search",
        "module": "scripts/data_feedback.py",
        "skill_dir": "~/.skills/skills/futures-data-search",
        "auto_fix": True,
    },
    "indicator": {
        "skill": "technical-indicator-calc",
        "module": "scripts/indicator_feedback.py",
        "skill_dir": "~/.skills/skills/technical-indicator-calc",
        "auto_fix": True,
    },
    "chain": {
        "skill": "commodity-chain-analysis",
        "module": "scripts/chain_feedback.py",
        "skill_dir": "~/.skills/skills/commodity-chain-analysis",
        "auto_fix": True,
    },
    "debate": {
        "skill": "commodity-daily-analysis",
        "module": "scripts/debate_feedback.py",  # 自反馈
        "skill_dir": None,
        "auto_fix": False,  # 辩论级问题需人工确认
    },
    "report": {
        "skill": "commodity-daily-analysis",
        "module": "scripts/phase3_generate_report.py",
        "skill_dir": None,
        "auto_fix": False,
    },
}


class FeedbackRouter:
    """辩论反馈中央路由器 — 多Agent自我进化中枢"""

    def __init__(self):
        self.skill_dir = SKILL_DIR
        self.log_file = FEEDBACK_LOG
        self.lessons_file = LESSONS_FILE

    # ==================== 提取 ====================

    def extract_from_text(self, text: str, agent: str) -> List[Dict]:
        """从Agent产出文本中提取 ###FEEDBACK 段"""
        feedbacks = []
        for match in FEEDBACK_PATTERN.finditer(text):
            block = match.group(1).strip()
            for line in block.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    fb = {
                        "timestamp": datetime.now().isoformat(),
                        "agent": agent,
                        "variety": parts[0].strip(),
                        "issue_type": parts[1].strip(),
                        "domain": parts[2].strip(),
                        "severity": parts[3].strip(),
                        "description": "|".join(parts[4:]).strip(),
                    }
                    # 校验
                    if fb["issue_type"] not in VALID_ISSUE_TYPES:
                        fb["issue_type"] = "unknown_" + fb["issue_type"]
                    if fb["domain"] not in ROUTING_TABLE:
                        fb["domain"] = "debate"  # 未知domain默认归入辩论类
                    feedbacks.append(fb)
        return feedbacks

    # ==================== 路由 ====================

    def route(self, feedback: Dict) -> Dict:
        """将单条反馈路由到目标skill的修复模块"""
        domain = feedback.get("domain", "debate")
        target = ROUTING_TABLE.get(domain, ROUTING_TABLE["debate"])

        result = {
            "feedback": feedback,
            "domain": domain,
            "target_skill": target["skill"],
            "target_module": target["module"],
            "routed": True,
            "fixed": False,
            "fix_detail": "",
        }

        # 尝试调用目标skill的feedback模块
        skill_dir = target.get("skill_dir")
        if skill_dir:
            skill_dir = os.path.expanduser(skill_dir)
            feedback_script = os.path.join(skill_dir, target["module"])
            if os.path.exists(feedback_script):
                try:
                    # 通过Python调用目标模块的submit
                    import importlib.util

                    mod_name = f"fb_mod_{domain}"
                    spec = importlib.util.spec_from_file_location(mod_name, feedback_script)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        if hasattr(mod, "submit_feedback"):
                            fix_result = mod.submit_feedback(
                                variety=feedback["variety"],
                                issue_type=feedback["issue_type"],
                                source=feedback["agent"],
                                context=feedback["description"],
                                severity=feedback["severity"],
                            )
                            result["fixed"] = fix_result.get("auto_fixed", False)
                            result["fix_detail"] = fix_result.get("rule_applied", "")
                except Exception as e:
                    result["fix_detail"] = f"路由失败: {str(e)[:60]}"
        elif target["auto_fix"]:
            # 辩论/报告域的自反馈处理
            result["fix_detail"] = self._handle_self_feedback(feedback)

        # 记录路由日志
        self._log(feedback, result)
        return result

    def route_batch(self, feedbacks: List[Dict]) -> List[Dict]:
        """批量路由"""
        results = []
        for fb in feedbacks:
            results.append(self.route(fb))
        return results

    def _handle_self_feedback(self, feedback: Dict) -> str:
        """处理辩论域/报告域的自反馈"""
        issue = feedback.get("issue_type", "")
        if issue == "material_gap":
            return "已记录: 缺失论证材料, 待补充到Agent Prompt中"
        elif issue == "rule_coverage_gap":
            return "已记录: 铁律覆盖不足, 待更新风控明Prompt"
        elif issue == "agent_timeout":
            return "已记录: Agent超时, 待优化Prompt长度或增加重试"
        else:
            return "自反馈已记录, 待评估是否需要规则变更"

    # ==================== 日志 ====================

    def _log(self, feedback: Dict, route_result: Dict):
        """追加到反馈日志"""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": feedback.get("agent", "unknown"),
            "variety": feedback.get("variety", "ALL"),
            "domain": feedback.get("domain", "debate"),
            "issue_type": feedback.get("issue_type", "unknown"),
            "severity": feedback.get("severity", "medium"),
            "description": feedback.get("description", ""),
            "routed_to": route_result.get("target_skill", ""),
            "fixed": route_result.get("fixed", False),
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ==================== 经验学习 ====================

    def learn(self, regenerate: bool = True) -> Dict:
        """
        从反馈日志中提取经验教训。
        输出可直接嵌入Agent Prompt的"已知陷阱"段。
        """
        lessons = self._load_lessons()
        if not regenerate:
            return lessons

        # 从反馈日志中分析模式
        if os.path.exists(self.log_file):
            history = []
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            history.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            # 按agent统计高频问题
            by_agent = {}
            for entry in history:
                agent = entry.get("agent", "unknown")
                if agent not in by_agent:
                    by_agent[agent] = []
                by_agent[agent].append(entry.get("issue_type", ""))

            # 生成经验教训
            lessons["last_updated"] = datetime.now().isoformat()
            lessons["total_feedbacks"] = len(history)
            lessons["by_domain"] = {}
            lessons["known_issues"] = []

            for entry in history[-50:]:  # 最近50条
                domain = entry.get("domain", "debate")
                lessons["by_domain"][domain] = lessons["by_domain"].get(domain, 0) + 1

            # 提取重复性问题的经验
            issue_counts = {}
            for entry in history[-50:]:
                k = (entry.get("domain", ""), entry.get("issue_type", ""))
                issue_counts[k] = issue_counts.get(k, 0) + 1

            for (domain, issue), count in issue_counts.items():
                if count >= 2:
                    lessons["known_issues"].append(
                        {
                            "domain": domain,
                            "issue_type": issue,
                            "frequency": count,
                            "advice": self._get_advice(domain, issue),
                        }
                    )

            self._save_lessons(lessons)

        return lessons

    def _get_advice(self, domain: str, issue: str) -> str:
        """根据问题类型生成经验建议"""
        advice_map = {
            ("data", "data_missing"): "提前检查数据完整性，缺失品种降级到AKShare",
            ("data", "data_anomaly"): "异常数据立即标记并触发TdxCollector→EastMoney降级",
            ("data", "far_price_zero"): "tdx_collector v2.0.1已自动过滤price=0合约",
            ("data", "oi_missing"): "持有量为0时自动触发AKShare兜底补全",
            ("indicator", "calc_error"): "确认数据为正序(旧→新)，EMA/MACD必须用正序",
            ("indicator", "indicator_missing"): "TQ-Local桥接失败时启用numpy fallback",
            ("debate", "material_gap"): "将缺失材料提前写入对应Agent Prompt的数据段",
            ("debate", "agent_timeout"): "拆分大型Prompt为多个小Prompt分批处理",
            ("chain", "chain_gap"): "产业链分类缺失品种上报至commodity-chain-analysis",
            ("report", "format_error"): "HTML模板修复后同步到phase3_generate_report.py",
        }
        return advice_map.get((domain, issue), f"待评估: {domain}/{issue}")

    def _load_lessons(self) -> Dict:
        if os.path.exists(self.lessons_file):
            with open(self.lessons_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"total_feedbacks": 0, "by_domain": {}, "known_issues": [], "last_updated": ""}

    def _save_lessons(self, lessons: Dict):
        with open(self.lessons_file, "w", encoding="utf-8") as f:
            json.dump(lessons, f, ensure_ascii=False, indent=2)

    # ==================== 报告 ====================

    def report(self, days: int = 30) -> str:
        """生成反馈报告"""
        if not os.path.exists(self.log_file):
            return "📭 暂无反馈记录"

        cutoff = datetime.now().timestamp() - days * 86400
        history = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01")).timestamp()
                    if ts >= cutoff:
                        history.append(entry)
                except json.JSONDecodeError:
                    continue

        by_domain = {}
        by_severity = {"high": 0, "medium": 0, "low": 0}
        fixed_count = 0

        for entry in history:
            d = entry.get("domain", "debate")
            by_domain[d] = by_domain.get(d, 0) + 1
            by_severity[entry.get("severity", "medium")] += 1
            if entry.get("fixed"):
                fixed_count += 1

        lines = [
            f"📊 辩论反馈报告 ({len(history)}条/{days}天)",
            "",
            f"按域分布: {json.dumps(by_domain, ensure_ascii=False)}",
            f"按严重度: 🔴高{by_severity['high']} 🟡中{by_severity['medium']} 🟢低{by_severity['low']}",
            f"已自动修复: {fixed_count}/{len(history)} ({100 * fixed_count // max(1, len(history))}%)",
            "",
            "最近5条:",
        ]

        for entry in history[-5:]:
            lines.append(
                f"  [{entry.get('agent', '?')}] {entry.get('variety', 'ALL')} "
                f"{entry.get('issue_type', '?')} → {entry.get('routed_to', '?')}"
            )

        return "\n".join(lines)


# ============================================================
# 快捷入口 — 供外部调用
# ============================================================
_router = None


def get_router() -> FeedbackRouter:
    global _router
    if _router is None:
        _router = FeedbackRouter()
    return _router


def submit_feedback(
    variety: str,
    issue_type: str,
    domain: str = "debate",
    severity: str = "medium",
    description: str = "",
    agent: str = "unknown",
) -> Dict:
    """便捷提交函数 — 任何模块都可直接调用"""
    router = get_router()
    fb = {
        "variety": variety,
        "issue_type": issue_type,
        "domain": domain,
        "severity": severity,
        "description": description,
        "agent": agent,
    }
    return router.route(fb)


# ============================================================
# 生成Agent Prompt中的"已知陷阱"段
# ============================================================
def get_known_issues_for_prompt() -> str:
    """
    生成可嵌入Agent Prompt的经验教训段落。
    每次自动化辩论时，协调器应调用此函数并将结果追加到每个Agent的Prompt末尾。
    """
    router = get_router()
    lessons = router.learn(regenerate=True)
    known = lessons.get("known_issues", [])

    if not known:
        return ""

    lines = [
        "",
        "---",
        "## ⚠️ 已知陷阱（历史辩论经验 — 请务必注意）",
        "",
        "以下问题曾在历次辩论中被发现并已修复。如遇到类似情况，请按建议处理：",
        "",
    ]

    for i, issue in enumerate(known[:12], 1):
        domain_label = {"data": "数据", "indicator": "指标", "chain": "产业链", "debate": "辩论", "report": "报告"}.get(
            issue["domain"], issue["domain"]
        )
        lines.append(
            f"{i}. **[{domain_label}] {issue['issue_type']}** (已发生{issue['frequency']}次) → {issue['advice']}"
        )

    lines.append("")
    lines.append(f"*经验更新时间: {lessons.get('last_updated', '')[:16]}*")
    lines.append(f"*累计反馈: {lessons.get('total_feedbacks', 0)}条*")
    lines.append("")
    return "\n".join(lines)


def inject_lessons_to_prompt(base_prompt: str) -> str:
    """
    将经验教训注入到Agent Prompt中。
    用于自动化流程中：读取Agent的base prompt，拼接经验段后发给Agent。

    Example:
        prompt = load_agent_prompt('技研锋')
        prompt = inject_lessons_to_prompt(prompt)
        spawn_agent(prompt)
    """
    injection = get_known_issues_for_prompt()
    if not injection:
        return base_prompt
    return base_prompt.rstrip() + "\n" + injection


def write_prompt_injection_file():
    """
    将经验注入段写入文件，供自动化协调器读取。
    输出: feedback/agent_prompt_injection.md
    """
    injection = get_known_issues_for_prompt()
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    with open(PROMPT_INJECTION_FILE, "w", encoding="utf-8") as f:
        f.write(injection if injection else "（暂无经验数据）\n")
    print(f"✅ 经验注入段已写入: {PROMPT_INJECTION_FILE}")
    return PROMPT_INJECTION_FILE


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    router = FeedbackRouter()

    if len(sys.argv) < 2:
        print(router.report())
    elif sys.argv[1] == "lessons":
        lessons = router.learn()
        print(json.dumps(lessons, ensure_ascii=False, indent=2))
    elif sys.argv[1] == "report":
        print(router.report())
    elif sys.argv[1] == "known":
        print(get_known_issues_for_prompt())
    elif sys.argv[1] == "inject":
        write_prompt_injection_file()
        # Also print for verification
        print(get_known_issues_for_prompt())
    elif sys.argv[1] == "route":
        # 扫描Agent产出文件中的###FEEDBACK段并路由

        report_dir = WORKSPACE_DIR
        today = datetime.now().strftime("%Y-%m-%d")
        debate_file = os.path.join(report_dir, today, "debate_results.json")
        if os.path.exists(debate_file):
            with open(debate_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 提取所有agent产出的日志（如果存在）
            for agent_name in ["数技源", "探源", "观澜", "链证源", "证真", "慎思", "闫判官", "风控明"]:
                # 尝试从debate_results中提取agent_output
                pass  # 实际由自动化协调器调用路由
            print("请使用 submit_feedback() 函数逐条路由")
        else:
            print(f"未找到辩论结果: {debate_file}")
    else:
        print("Usage: python debate_feedback.py [report|lessons|known|inject|route]")
