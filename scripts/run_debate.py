# -*- coding: utf-8 -*-
"""
FDT 辩论主动驱动层 (B 项优化 · 2026-07-11)
==========================================

设计意图：
- 把每轮手工的多步易碎操作（识别触发品种 / 手写 spawn 提示 / 手写内联 Python 组装
  debate_results.json / 逐品种 extract_knowledge / 误用手写 HTML）收敛进**一个脚本**，
  消除"零胶水代码"红线被踩的问题。
- **不 spawn Agent**（spawn 是团队主管 WorkBuddy Agent 的固有职责，Python 也 spawn 不了
  子 Agent）。本脚本产出**标准化 spawn 计划 JSON**，主管按此计划 spawn。
- 提供 assemble / extract / report 子命令，复用既有 CLI（extract_knowledge.py、
  phase3_generate_report.py），不重复造轮子。

用法：
  # 1) 产出 spawn 计划（主管据此 spawn 各辩论 Agent）
  python scripts/run_debate.py plan \
      --scan 2026-07-11/scan_daily_1824_20260711.json \
      --workspace 2026-07-11

  # 2) 主管 spawn 完毕、各 p4/p5 文件就绪后，收口组装+萃取+报告
  python scripts/run_debate.py finalize \
      --scan 2026-07-11/scan_daily_1824_20260711.json \
      --workspace 2026-07-11

依赖：
  - 阈值单一真相源：skills/quant-daily/scripts/config/settings.py:DEBATE_ENTRY_MIN_ABS
    （经 importlib 按路径加载，不写死；FDT 根 config/settings.py 不存在，故走量化子技能配置）
  - 萃取：skills/futures-trading-analysis/scripts/extract_knowledge.py ingest --from
  - 报告：skills/futures-trading-analysis/scripts/phase3_generate_report.py --debate
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PureWindowsPath
import re

_WIN_DRIVE_RE = re.compile(r"^/([a-zA-Z])/")  # 匹配 /d/foo/bar → d:\foo\bar

_FDT_ROOT = Path(__file__).resolve().parent.parent
_AGENT_PROFILES_PATH = _FDT_ROOT / "memory" / "agent_profiles.json"


def _load_strategist_profile() -> dict:
    """加载策执远进化参数（rr_target / position_coefficient / 统计）。"""
    try:
        if _AGENT_PROFILES_PATH.exists():
            ap = json.loads(_AGENT_PROFILES_PATH.read_text(encoding="utf-8"))
            return ap.get("策执远", {})
    except Exception:
        pass
    return {}


def _strategist_experience_inject(profile: dict) -> str:
    """从进化参数生成经验注入文本，追加到策执远 spawn prompt。"""
    if not profile:
        return ""
    rr = profile.get("rr_target", 2.0)
    pos = profile.get("position_coefficient", 1.0)
    stats = profile.get("_stats", {})
    total = stats.get("total_validated", 0)
    hit_rate = stats.get("real_target_hit_rate", 0)
    avg_pnl = stats.get("avg_realized_pnl_pct", 0)
    log = profile.get("_evolution_log", [])
    last_adj = log[-1]["reason"] if log else "尚无调整记录"
    avg_pnl_str = f"{avg_pnl:+.1f}%" if isinstance(avg_pnl, (int, float)) else str(avg_pnl)
    return (
        f"\n【历史经验注入 — 累计{total}条已验证裁决】\n"
        f"建议RR目标: {rr:.1f}:1（{last_adj}）\n"
        f"仓位系数: {pos:.2f}（基于历史实现盈亏{avg_pnl_str}校准）\n"
        f"T1达标率: {hit_rate:.0f}%\n"
        f"注意：上述参数为历史统计参考，请结合当前品种特征做判断，不要生搬硬套。"
    )


def _to_win_path(p: str) -> str:
    """将 Git Bash 风格绝对路径 /d/foo/bar 转为 Windows 风格 D:\foo\bar。

    - 仅 Windows 上生效，非 Windows 直接返回原值。
    - 匹配不上的原值返回（如已含 : 或相对路径）。
    """
    if sys.platform != "win32":
        return p
    m = _WIN_DRIVE_RE.match(p)
    if m:
        return m.group(1).upper() + ":\\" + p[3:].replace("/", "\\")
    # 也处理反过来的: d:\foo → 归一化大小写和分隔符
    if ":" in p:
        return str(PureWindowsPath(p))
    return p

# ── FDT 根目录（本文件在 scripts/ 下）──
ROOT = Path(__file__).resolve().parent.parent
QUANT_DAILY = ROOT / "skills" / "quant-daily" / "scripts"
# extract_knowledge.py 在 scripts/ 下，不在 futures-trading-analysis/ 下
SCRIPTS = ROOT / "scripts"


# ─────────────────────────────────────────────
# 阈值单一真相源（按路径加载，禁止写死 20）
# ─────────────────────────────────────────────
def load_debate_threshold() -> int:
    """从量化子技能 config/settings.py 读取 DEBATE_ENTRY_MIN_ABS（唯一真相源）。"""
    cand = QUANT_DAILY / "config" / "settings.py"
    if cand.exists():
        try:
            spec = importlib.util.spec_from_file_location("qd_settings", str(cand))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return int(getattr(mod, "DEBATE_ENTRY_MIN_ABS", 20))
        except Exception:
            pass
    return 20  # 仅文件缺失时兜底；正常路径不应命中


# ─────────────────────────────────────────────
# 数据基准（G 项：写入 debate_results.json 顶层）
# ─────────────────────────────────────────────
def derive_data_benchmark(scan: dict) -> str:
    """从扫描 JSON 派生的'数据基准'时间戳。

    优先取 _meta.klines_latest_date；无则取 generated_at；均无则用扫描文件 mtime。
    标注 收盘/盘中：16:00 后或 09:00-15:00 之间按时刻语义，简化处理为'收盘'若时刻≥15:00 否则'盘中'。
    """
    meta = scan.get("_meta", {}) or {}
    kl = meta.get("klines_latest_date") or scan.get("klines_latest_date")
    gen = scan.get("generated_at") or scan.get("scan_generated_at")
    base = kl or gen
    if not base:
        try:
            mtime = datetime.fromtimestamp((ROOT / "pyproject.toml").stat().st_mtime)
            base = mtime.strftime("%Y-%m-%d %H:%M")
        except Exception:
            base = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 标注收盘/盘中
    try:
        hh = int(str(base).split(" ")[-1].split(":")[0])
        suffix = "收盘" if hh >= 15 else "盘中"
    except Exception:
        suffix = "收盘"
    return f"{base} {suffix}"


# ─────────────────────────────────────────────
# 触发品种识别（信号检查闸门）
# ─────────────────────────────────────────────
def select_triggers(scan: dict, threshold: int) -> list:
    """|total| >= DEBATE_ENTRY_MIN_ABS 即进候选（grade 仅作优先级标签）。"""
    ranked = scan.get("all_ranked", [])
    cands = [s for s in ranked if abs(s.get("total", 0)) >= threshold]
    # 优先级：STRONG > WATCH > 其余
    order = {"STRONG": 0, "WATCH": 1, "WEAK": 2, "NOISE": 3}
    cands.sort(key=lambda s: (order.get(s.get("grade", "NOISE"), 9), -abs(s.get("total", 0))))
    return cands


# ─────────────────────────────────────────────
# 固定注入规则（ADX 角色反转 / WATCH 语义 / 置信度归一）
# 与 fdt-spawn-debate SKILL.md 铁律一致，集中于此单一来源
# ─────────────────────────────────────────────
def _adx_reversal_rule() -> str:
    return ("ADX角色反转：ADX低位(<20)视为趋势启动早期而非'无趋势不交易'；"
            "ADX高位(≥60)为过热警示；ADX不得作为致命伤，提及占比≤1/3。")


def build_spawn_plan(symbols: list, workspace: str, data_benchmark: str) -> dict:
    """产出标准化 spawn 计划 JSON（主管据此 spawn，spawn 本身仍是主管职责）。"""
    ws = Path(workspace)
    plan = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "data_benchmark": data_benchmark,
             "injected_rules": {
                 "adx_reversal": _adx_reversal_rule(),
                 "watch_semantics": "WATCH等级=监控观察信号，非直接触发；需结合辩论强度决定是否进候选。",
                 "confidence": "confidence由confidence_utils归一化，输出0-1数值或高/中/低标签均可，禁止任意裸字符串。",
             },
             # ─── 资源管理：分批执行指引 ───
             "execution_phases": {
                 "phase1": {"agents": ["technical"],
                            "label": "P3 技术分析(观澜) + 研究员供弹",
                            "max_concurrent": 5,
                            "depends_on": []},
                 "phase2": {"agents": ["zhengzhen","zhensi"],
                            "label": "P4 多空辩论(证真+慎思)",
                            "max_concurrent": 6,
                            "depends_on": []},
                 "phase3": {"agents": ["judge"],
                            "label": "P5a 闫判官裁决",
                            "max_concurrent": 5,
                            "depends_on": ["phase2"]},
                 "phase4": {"agents": ["coherence"],
                            "label": "P5b 一致性裁判审计",
                            "max_concurrent": 5,
                            "depends_on": ["phase3"]},
                 "phase5": {"agents": ["trading_plan"],
                            "label": "P5c 策执远出方案(需读p3_technical+p5_judge)",
                            "max_concurrent": 5,
                            "depends_on": ["phase1","phase3"]},
                 "phase6": {"agents": ["risk"],
                            "label": "P5d 风控明审核",
                            "max_concurrent": 5,
                            "depends_on": ["phase5"]},
             },
             "symbols": []}

    for s in symbols:
        sym = s.get("symbol")
        direction = s.get("direction", "neutral")      # bull / bear
        grade = s.get("grade", "")
        pro_side = "多头" if direction == "bull" else ("空头" if direction == "bear" else "中性")
        p4_z = ws / f"p4_zhengzhen_{sym}.json"
        p4_s = ws / f"p4_zhensi_{sym}.json"
        p5_j = ws / f"p5_judge_{sym}.json"
        p5_t = ws / f"p5_trading_plan_{sym}.json"
        p5_c = ws / f"p5_coherence_{sym}.json"
        p5_r = ws / f"p5_risk_review_{sym}.json"
        # P3 研究员产出（先于 P4/P5 spawn）
        p3_tech = ws / f"p3_technical_{sym}.json"      # 观澜 · 支撑阻力
        p3_fund = ws / f"p3_fundamental_{sym}.json"    # 探源 · 基本面状态向量

        # 证真（正方 = 信号方向）—— 输出格式必须严格匹配以下Schema
        _p4_schema_zhengzhen = ('{"symbol":"str","direction":"str","agent":"zhengzhen","generated_at":"YYYY-MM-DD HH:MM",'
                                '"key_arguments":[{"id":"str","claim":"str","evidence":"str","reasoning":"str",'
                                '"family":"technical_general","confidence":"高/中/低","source":"str"}]}')
        _p4_schema_zhensi = ('{"symbol":"str","direction":"str","agent":"zhensi","generated_at":"YYYY-MM-DD HH:MM",'
                             '"key_arguments":[{"id":"str","claim":"str","evidence":"str","reasoning":"str",'
                             '"family":"technical_general","confidence":"高/中/低","source":"str"}]}')
        zhengzhen_prompt = (
            f"你是证真(正方)辩手，论证品种 {sym} 的{direction}信号({grade})有效性。\n"
            f"{_adx_reversal_rule()}\n"
            f"数据基准: {data_benchmark}。\n"
            f"从研究员/链证源资料中提炼≥3条{direction}论据，每条附来源标注。\n"
            f"【重要】输出JSON必须严格匹配以下Schema（字段名/类型/结构完全一致），否则校验失败将导致重spawn：\n{_p4_schema_zhengzhen}\n"
            f"写完用 SendMessage(recipient='main') 通知，并把论据写入 {p4_z}"
        )
        # 慎思（反方）
        zhensi_prompt = (
            f"你是慎思(反方)辩手，质疑品种 {sym} 的{direction}信号({grade})可靠性。\n"
            f"{_adx_reversal_rule()}\n"
            f"数据基准: {data_benchmark}。\n"
            f"从研究员/链证源资料中提炼≥3条反向论据，每条附来源标注。\n"
            f"【重要】输出JSON必须严格匹配以下Schema（字段名/类型/结构完全一致），否则校验失败将导致重spawn：\n{_p4_schema_zhensi}\n"
            f"写完用 SendMessage(recipient='main') 通知，并把论据写入 {p4_s}"
        )
        # 闫判官输出Schema
        _p5j_schema = ('{"agent":"judge","symbol":"str","generated_at":"YYYY-MM-DD HH:MM",'
                       '"verdict":"bull/bear/neutral","confidence":"高/中/低",'
                       '"bull_score":0-100,"bear_score":0-100,"winner":"zhengzhen/zhensi",'
                       '"reasoning":"str",'
                       '"score_breakdown":{"technical":{"bull":0,"bear":0},"fundamental":{...},"sentiment":{...},'
                       '"risk_reward":{...},"timing":{...},"chain_resonance":{...}}}')
        judge_prompt = (
            f"你是闫判官，裁决品种 {sym}（方向信号 {direction}/{grade}）。\n"
            f"{_adx_reversal_rule()}\n"
            f"读取 {p4_z} 与 {p4_s}，主持交叉质询后输出裁决到 {p5_j}。\n"
            f"【重要】输出JSON必须严格匹配以下Schema：\n{_p5j_schema}\n"
            f"禁止向其他 Agent 发消息，仅读文件。"
        )
        # 观澜（技术面研究员）— P3 支撑阻力计算，先于 P4/P5 执行
        technical_prompt = (
            f"你是观澜(技术面研究员)，为品种 {sym} 计算支撑阻力位，写入 {p3_tech}。\n"
            f"数据基准: {data_benchmark}。\n"
            f"使用 technical_analysis.scripts.support_resistance 模块：\n"
            f"  - find_swing_points(): ZigZag找前高前低\n"
            f"  - identify_key_levels(): 硬/软分类 + ATR容差 + 失效条件\n"
            f"  - calculate_poc(): 成交量分布图(POC/VAH/VAL)\n"
            f"  - cross_validate_timeframes(): 多周期共振验证\n"
            f"输出JSON Schema：\n"
            f'{{"symbol":"str","agent":"technical_researcher","generated_at":"YYYY-MM-DD HH:MM",'
            f'"support_levels":[{{"price":0.0,"hardness":"hard/medium/soft","atr_tolerance":0.0,'
            f'"failure_condition":"str","tf_resonance":["daily/60min/15min"],"oi_confirm":true}}],'
            f'"resistance_levels":[{{"price":0.0,"hardness":"hard/medium/soft","atr_tolerance":0.0,'
            f'"failure_condition":"str","tf_resonance":["daily/60min/15min"],"oi_confirm":true}}],'
            f'"poc":{{"price":0.0,"vah":0.0,"val":0.0}}}}\n'
            f"注意：不下多空结论，不参与辩论，只提供技术位事实。\n"
            f"写完用 SendMessage(recipient='main') 通知。"
        )
        # 策执远输出Schema
        _p5t_schema = ('{"agent":"trading_planner","symbol":"str","generated_at":"YYYY-MM-DD HH:MM",'
                       '"direction":"bull/bear","action":"buy_long/sell_short","timeframe":"str",'
                       '"contract":"str",'
                       '"entry":{"type":"limit/market","price":0.0,"condition":"str"},'
                       '"stop_loss":{"price":0.0,"type":"fixed/trailing/atr","atr_multiple":0},'
                       '"targets":[{"level":1,"price":0.0,"position_reduce_pct":50}],'
                       '"position_pct":0.0,"risk_reward_ratio":0.0}')
        strategist_profile = _load_strategist_profile()
        exp_inject = _strategist_experience_inject(strategist_profile)
        plan_prompt = (
            f"你是策执远，基于 {p5_j} 裁决为 {sym} 制定可执行方案，写入 {p5_t}。\n"
            f"【支撑阻力参考】观澜技术分析已输出到 {p3_tech}，内含：\n"
            f"  - support_levels: 支撑位（hardness硬/软分类 + ATR容差 + 失效条件）\n"
            f"  - resistance_levels: 阻力位（同上）\n"
            f"  - poc: 成交量分布图（POC/VAH/VAL）\n"
            f"止损应设在关键阻力/支撑位外延，目标应基于关键位之间的空间，参考上述数据。\n"
            f"【重要】输出JSON必须严格匹配以下Schema（entry和stop_loss是dict类型，不是纯数字）：\n{_p5t_schema}\n"
            f"监控条件不以ADX为首要触发，价格突破+量确认排第一。"
            f"{exp_inject}"
        )
        # 一致性裁判
        coherence_prompt = (
            f"你是一致性裁判，审计 {sym} 裁决是否真正源于辩论论据（不重写论据）。\n"
            f"读取 {p4_z}/{p4_s}/{p5_j}，输出 coherence_score(0-100)+rationale 到 {p5_c}。"
        )
        # 风控明输出Schema
        _p5r_schema = ('{"agent":"risk_manager","symbol":"str","generated_at":"YYYY-MM-DD HH:MM",'
                       '"risk_level":"高/中/低","veto":false,'
                       '"risk_items":[{"category":"str","description":"str","mitigation":"str"}],'
                       '"recommendation":"str"}')
        risk_prompt = (
            f"你是风控明，审核 {sym} 方案 {p5_t}。\n"
            f"ADX风险标记降级为辅助参考，不独立构成否决理由。\n"
            f"【重要】输出JSON必须严格匹配以下Schema：\n{_p5r_schema}"
        )

        plan["symbols"].append({
            "symbol": sym, "direction": direction, "grade": grade,
            "files": {
                "p3_technical": str(p3_tech),    # 观澜 · 支撑阻力
                "p3_fundamental": str(p3_fund),  # 探源 · 基本面
                "p4_zhengzhen": str(p4_z), "p4_zhensi": str(p4_s),
                "p5_judge": str(p5_j), "p5_trading_plan": str(p5_t),
                "p5_coherence": str(p5_c), "p5_risk_review": str(p5_r),
            },
            "spawn_prompts": {
                "technical": technical_prompt,   # 观澜（P3 先执行）
                "zhengzhen": zhengzhen_prompt, "zhensi": zhensi_prompt,
                "judge": judge_prompt, "trading_plan": plan_prompt,
                "coherence": coherence_prompt, "risk": risk_prompt,
            },
        })
    return plan


# ─────────────────────────────────────────────
# 文件就绪轮询（S04 标准实现）
# ─────────────────────────────────────────────
def poll_file_ready(path: str, timeout: int = 900, stable_seconds: int = 5) -> bool:
    import time
    deadline = time.time() + timeout
    last_size = -1
    stable_since = None
    while time.time() < deadline:
        if os.path.exists(path):
            sz = os.path.getsize(path)
            if sz > 0:
                if sz == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stable_seconds:
                        return True
                else:
                    last_size = sz
                    stable_since = None
        time.sleep(15)
    return False


# ─────────────────────────────────────────────
# 组装 debate_results.json（per_pid，含 data_benchmark）
# ─────────────────────────────────────────────
def _extract_price(val, default=0):
    """从 p5_trading_plan 提取数值价格。entry/stop_loss 可能是 dict 或纯数字。"""
    if isinstance(val, dict):
        return val.get("price", val.get("entry", default))
    if isinstance(val, (int, float)):
        return val
    return default


# ── 裁决→动作 消歧（信号与策略不一致的根因修复）──
def _derive_action(verdict: str, grade: str, score_breakdown: dict, scan_direction: str) -> str:
    """从判官裁决推导最终可操作动作。

    规则：
    1. NEUTRAL → wait（中立裁决，不可执行）
    2. 总分差≤15 → wait（辩论太接近，信噪比不足）
    3. 裁决方向 ≠ 扫描信号方向 → wait（辩论反转了信号方向）
    4. grade=WEAK → hold（监控观察，非直接执行）
    5. grade=STRONG/WATCH 且全部通过 → execute

    返回: 'execute' | 'hold' | 'wait'
    """
    v = verdict.upper()
    s = scan_direction.upper() if scan_direction else ""

    if v == "NEUTRAL":
        return "wait"

    margin = 999
    if score_breakdown and isinstance(score_breakdown, dict):
        bull_t = sum(d.get("bull", 0) for d in score_breakdown.values() if isinstance(d, dict))
        bear_t = sum(d.get("bear", 0) for d in score_breakdown.values() if isinstance(d, dict))
        margin = abs(bull_t - bear_t)

    if margin <= 15:
        return "wait"
    if v != s:
        return "wait"
    if grade in ("WEAK",):
        return "hold"
    if grade in ("STRONG", "WATCH"):
        return "execute"
    return "wait"


def assemble(scan: dict, workspace: str, data_benchmark: str) -> dict:
    ws = Path(workspace)
    verdicts = {}
    plan = build_spawn_plan(select_triggers(scan, load_debate_threshold()), workspace, data_benchmark)
    for item in plan["symbols"]:
        sym = item["symbol"]
        f = item["files"]
        p4z = p4s = p5j = p5t = p5r = None
        try:
            if os.path.exists(f["p4_zhengzhen"]):
                p4z = json.load(open(f["p4_zhengzhen"], encoding="utf-8"))
            if os.path.exists(f["p4_zhensi"]):
                p4s = json.load(open(f["p4_zhensi"], encoding="utf-8"))
            if os.path.exists(f["p5_judge"]):
                p5j = json.load(open(f["p5_judge"], encoding="utf-8"))
            if os.path.exists(f["p5_trading_plan"]):
                p5t = json.load(open(f["p5_trading_plan"], encoding="utf-8"))
            if os.path.exists(f["p5_risk_review"]):
                p5r = json.load(open(f["p5_risk_review"], encoding="utf-8"))
        except json.JSONDecodeError:
            pass

        if not p5j:
            print(f"  ⚠️ {sym} 缺 p5_judge，跳过")
            continue

        jv = p5j.get("judge_verdict", p5j)
        direction = str(jv.get("final_direction", jv.get("verdict", jv.get("direction", "")))).upper() or "NEUTRAL"
        score_breakdown = jv.get("score_breakdown", p5j.get("score_breakdown", {}))

        # ── 动作消歧：裁决→可执行动作 ──
        scan_direction = next((s.get("direction", "") for s in scan.get("all_ranked", []) if s.get("symbol") == sym), "")
        action = _derive_action(direction, item["grade"], score_breakdown, scan_direction)

        # ── 仅 action=execute 才保留交易参数；wait/hold 清空 ──
        entry = _extract_price(p5t.get("entry")) if p5t else 0
        sl = _extract_price(p5t.get("stop_loss")) if p5t else 0
        target = _extract_price(p5t.get("targets", [{}])[0]) if p5t and p5t.get("targets") else 0
        # 安全兜底：action=execute 但 entry=0 → 降级为 wait（参数未填充）
        if action == "execute" and (entry is None or entry <= 0):
            print(f"  ⚠️ {sym} action=execute 但 entry={entry}，降级为 wait")
            action = "wait"
        entry_price = entry if action == "execute" else None
        stop_loss_price = sl if action == "execute" else None
        target_price = target if action == "execute" else None
        position_size = p5t.get("position_pct") if p5t and action == "execute" else None
        contract = p5t.get("contract") if p5t and action == "execute" else None

        verdicts[sym] = {
            "symbol": sym,
            "name": sym,
            "direction": direction,
            "action": action,
            "verdict": direction,
            "confidence": jv.get("confidence", p5j.get("confidence")),
            "reasoning": jv.get("reasoning", p5j.get("reasoning")),
            "signal_type": scan_signal_type(scan, sym),
            "grade": item["grade"],
            "total_score": next((s.get("total") for s in scan.get("all_ranked", []) if s.get("symbol") == sym), None),
            "winner": jv.get("winner", p5j.get("winner", "")),
            "price": entry,
            "atr": scan_atr(scan, sym),
            "adx": scan_adx(scan, sym),
            "rsi": scan_rsi(scan, sym),
            "cci": scan_cci(scan, sym),
            "chain": (p5t.get("chain") if p5t else None) or scan_chain(scan, sym),
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss_price": stop_loss_price,
            "position_size": position_size,
            "contract": contract,
            "judge_verdict": {
                "final_direction": jv.get("final_direction"),
                "confidence": jv.get("confidence"),
                "reasoning": jv.get("reasoning"),
                "key_observation": jv.get("key_observation"),
                "score_breakdown": jv.get("score_breakdown"),
            },
            "bull_args": [f"{sym}-pro{i+1}: {a.get('claim', a.get('point', ''))}"
                         for i, a in enumerate((p4z or {}).get("key_arguments", []))],
            "bear_args": [f"{sym}-con{i+1}: {a.get('claim', a.get('point', ''))}"
                         for i, a in enumerate((p4s or {}).get("key_arguments", []))],
            "trading_plan": p5t or {},
            "risk_review": p5r or {},
        }
        has_plan = "完整" if (p5t and p5r) else "仅裁决"
        print(f"  ✅ {sym} {direction}（{has_plan}）")

    out = {
        "round_id": f"FDT_{datetime.now().strftime('%Y%m%d')}_auto",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_benchmark": data_benchmark,
        "signal_source": scan.get("signal_source", ""),
        "scan_generated_at": scan.get("generated_at", scan.get("scan_generated_at", "")),
        "verdicts": verdicts,
    }
    out_path = ws / "debate_results.json"
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2, default=str)
    print(f"✅ 组装 debate_results.json: {out_path}（{len(verdicts)} 品种）")
    return out


def _scan_row(scan, sym):
    return next((s for s in scan.get("all_ranked", []) if s.get("symbol") == sym), {})


def scan_signal_type(scan, sym):
    return _scan_row(scan, sym).get("signal_type", "channel_breakout")


def scan_atr(scan, sym):
    return _scan_row(scan, sym).get("atr")


def scan_adx(scan, sym):
    return _scan_row(scan, sym).get("adx")


def scan_rsi(scan, sym):
    return _scan_row(scan, sym).get("rsi")


def scan_cci(scan, sym):
    return _scan_row(scan, sym).get("cci")


def scan_chain(scan, sym):
    return _scan_row(scan, sym).get("chain")


# ─────────────────────────────────────────────
# 中间数据生成（给 phase3_generate_report.py 喂 all_actionable / chain_results / symbols_summary）
# ─────────────────────────────────────────────
def generate_intermediate_data(scan: dict, workspace: str, data_benchmark: str):
    """从 scan 数据生成 phase3 报告器依赖的 intermediate_data.json"""
    ws = Path(workspace)
    ranked = scan.get("all_ranked", [])

    # 品种→产业链映射（scan没有chain字段时兜底）
    # 覆盖国内商品期货76+品种的核心产业链归属
    SYMBOL_CHAIN_MAP = {
        # 黑色系（钢铁产业链）
        "rb": "螺纹钢", "hc": "热卷", "i": "铁矿石", "jm": "焦煤", "j": "焦炭",
        "SF": "铁合金", "SM": "铁合金", "si": "工业硅",
        # 有色金属
        "cu": "有色金属", "al": "有色金属", "zn": "有色金属", "pb": "有色金属",
        "ni": "有色金属", "sn": "有色金属", "ao": "有色金属",
        # 贵金属
        "au": "贵金属", "ag": "贵金属",
        # 能源化工
        "sc": "原油", "bu": "沥青", "fu": "燃料油", "lu": "低硫燃料油", "pg": "液化气",
        "ru": "橡胶", "nr": "20号胶", "br": "丁二烯橡胶",
        "SH": "化工", "v": "化工", "pp": "化工", "l": "化工", "eb": "化工", "eg": "化工",
        "MA": "化工", "UR": "化工", "SA": "化工", "FG": "化工",
        "PX": "聚酯链", "TA": "聚酯链", "PF": "聚酯链", "PR": "聚酯链", "ec": "聚酯链",
        # 农产品
        "a": "豆类", "b": "豆类", "m": "豆类", "y": "豆类",
        "RM": "菜籽", "OI": "菜籽",
        "c": "玉米", "cs": "玉米",
        "p": "油脂", "PK": "油脂",
        "SR": "软商品", "CF": "软商品",
        "ap": "苹果", "CJ": "红枣", "lc": "碳酸锂",
        "rr": "畜牧", "lh": "畜牧", "jd": "畜牧",
        # 其他
        "sp": "纸浆", "ps": "聚苯乙烯",
    }

    def _get_chain(sym: str) -> str:
        """获取品种所属产业链"""
        # 先试 scan 内置 chain 字段
        for s in ranked:
            c = s.get("chain", "")
            if c and s.get("symbol") == sym:
                return c
        # 再试映射表
        return SYMBOL_CHAIN_MAP.get(sym, "")

    # symbols_summary = 全量品种数据
    symbols_summary = []
    for s in ranked:
        symbols_summary.append({
            "symbol": s.get("symbol", ""),
            "pid": s.get("symbol", ""),
            "product_name": s.get("name", s.get("symbol", "")),
            "price": s.get("price", 0),
            "change_pct": s.get("change_pct", 0),
            "volume": s.get("volume", 0),
            "total": s.get("total", 0),
            "abs": s.get("abs", 0),
            "direction": s.get("direction", ""),
            "grade": s.get("grade", "NOISE"),
            "adx": s.get("adx", 0),
            "rsi": s.get("rsi", 50),
            "cci": s.get("cci", 0),
            "ma_slope": s.get("ma_slope", 0),
            "macd_cross": s.get("macd_cross", "none"),
            "dc20_break": s.get("dc20_break", "none"),
            "ma_align": s.get("ma_align", "mixed"),
            "z_score": s.get("z_score", 0),
            "stage": s.get("stage", ""),
            "atr": s.get("atr", 0),
            "dc20": s.get("dc20", 0),
            "dc55": s.get("dc55", 0),
            "bb": s.get("bb", 0),
            "vol_score": s.get("vol_score", 0),
            "signal_type": s.get("signal_type", ""),
            "dc55_trend": s.get("dc55_trend", ""),
            "ma60": s.get("ma60", 0),
            "channel_detail": s.get("channel_detail", {}),
            "bb_detail": s.get("bb_detail", {}),
            "vol_detail": s.get("vol_detail", {}),
            "chain": _get_chain(s.get("symbol", "")),
        })

    # all_actionable = 有信号的品种（STRONG/WATCH/WEAK），转换为 phase3 格式
    # 每项需 pid / confidence / decision / product_name / price / stage / adx / signal_type 等
    all_actionable = []
    # 已有辩论结果的，从 debate_results.json 中取裁决
    debate_path = ws / "debate_results.json"
    debate_data = {}
    if debate_path.exists():
        try:
            debate_data_raw = json.load(open(debate_path, encoding="utf-8"))
            debate_data = debate_data_raw.get("verdicts", {})
        except (json.JSONDecodeError, Exception):
            debate_data = {}

    for s in ranked:
        sym = s.get("symbol", "")
        grade = s.get("grade", "NOISE")
        if grade == "NOISE":
            continue  # 噪声品种跳过

        direction = s.get("direction", "")
        total = s.get("total", 0)
        abs_score = s.get("abs", 0)

        # 若有辩论结果，用辩论中的action/direction覆盖，不用原始扫描信号
        verdict_entry = debate_data.get(sym, {})
        chain_name = verdict_entry.get("chain", "") or _get_chain(sym)

        # 裁决→action 映射：用辩论action决定交易系统决策（根因修复）
        debate_action = verdict_entry.get("action", "")
        debate_direction = verdict_entry.get("direction", "")
        if debate_action == "execute":
            decision = "BUY" if debate_direction in ("BULL", "bull") else "SELL"
        elif debate_action == "hold":
            decision = "WATCH"
        else:  # wait 或无裁决
            decision = "HOLD"

        # 置信度：有裁决时直接用裁决confidence
        confidence = verdict_entry.get("confidence", "")
        if not confidence:
            confidence = min(1.0, max(0.1, abs_score / 80.0))

        entry = s.get("price", 0)
        adx_val = s.get("adx", 0)

        entry_price = verdict_entry.get("entry_price", entry) or entry
        target_price = verdict_entry.get("target_price", s.get("target_price", 0))
        stop_loss = verdict_entry.get("stop_loss_price", s.get("stop_loss_price", 0))
        pos_size = verdict_entry.get("position_size", s.get("position_size", 0))
        rr = verdict_entry.get("risk_reward_ratio", s.get("risk_reward_ratio", 0))

        all_actionable.append({
            "pid": sym,
            "product_name": s.get("name", sym),
            "confidence": confidence,
            "decision": decision,
            "direction": debate_direction or direction,
            "price": entry,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss_price": stop_loss,
            "position_size": pos_size,
            "risk_reward_ratio": rr,
            "stage": s.get("stage", ""),
            "adx": adx_val,
            "signal_type": s.get("signal_type", ""),
            "grade": grade,
            "total": total,
            "abs": abs_score,
            "chain": chain_name,
            "last_price": entry,
        })

    # chain_results — 从品种映射表构建产业链
    chain_results = {}
    # 先收集每个品种的链
    for s in ranked:
        sym = s.get("symbol", "")
        chain = _get_chain(sym)
        if chain:
            if chain not in chain_results:
                chain_results[chain] = {
                    "chain": chain,
                    "chain_name": chain,
                    "chain_members": [],
                    "members": [],
                    "term_structure": "flat",
                }
            chain_results[chain]["chain_members"].append(sym)
            chain_results[chain]["members"].append(sym)
    # 如果链条数为0，至少把所有品种归到"未分类"
    if not chain_results:
        chain_results["未分类"] = {
            "chain": "未分类",
            "chain_name": "未分类",
            "chain_members": [s.get("symbol", "") for s in ranked if s.get("symbol")],
            "members": [s.get("symbol", "") for s in ranked if s.get("symbol")],
            "term_structure": "flat",
        }

    # 组装中间数据
    meta = scan.get("_meta", {})
    intermediate = {
        "data_benchmark": data_benchmark,
        "data_source": meta.get("data_source", scan.get("data_source", "unknown")),
        "_meta": meta,
        "all_actionable": all_actionable,
        "chain_results": chain_results,
        "symbols_summary": symbols_summary,
    }

    out_path = ws / "intermediate_data.json"
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(intermediate, fp, ensure_ascii=False, indent=2, default=str)
    print(f"✅ 中间数据 intermediate_data.json: {out_path}（{len(all_actionable)} 信号，{len(chain_results)} 链）")
    return intermediate


# ─────────────────────────────────────────────
# 萃取（D 项：批量 --from）
# ─────────────────────────────────────────────
def run_extract(workspace: str) -> int:
    dr = Path(workspace) / "debate_results.json"
    if not dr.exists():
        print(f"✗ 未找到 {dr}")
        return 1
    cmd = [sys.executable,
            str(SCRIPTS / "extract_knowledge.py"), "ingest_from",
            "--from", str(dr)]
    print(f"🔍 知识萃取（批量，conf<0.6 自动跳过）: {' '.join(cmd)}")
    return subprocess.call(cmd)


# ─────────────────────────────────────────────
# 信号复查（终检：推送给交易系统前的最后一道门）
# ─────────────────────────────────────────────
def run_validate(workspace: str, scan_path: str | None = None) -> int:
    """确定性复查 debate_results.json，确保无矛盾。
    
    退出码 0=通过，1=失败。失败时打印所有错误并静默返回 1（供 pipelining 用）。
    """
    ws = Path(workspace)
    dr = ws / "debate_results.json"
    if not dr.exists():
        print(f"✗ 未找到 {dr}，跳过信号复查")
        return 0

    cmd = [sys.executable, str(SCRIPTS / "validate_final_signals.py"),
           "--input", str(dr)]
    if scan_path:
        cmd += ["--scan", str(Path(scan_path).resolve())]
    print(f"🔴 信号复查: {' '.join(cmd)}")
    ret = subprocess.call(cmd)
    if ret != 0:
        print(f"⛔ 信号复查失败，中止管道 — 修复后重新 assemble")
    return ret


# ─────────────────────────────────────────────
# 报告（G 项：phase3 --debate，数据基准走 debate_results.data_benchmark）
# ─────────────────────────────────────────────
def run_report(workspace: str) -> int:
    ws = Path(workspace)
    cmd = [sys.executable,
            str(ROOT / "skills" / "futures-trading-analysis" / "scripts" / "phase3_generate_report.py"),
            "--debate", str(ws / "debate_results.json"),
            "--intermediate", str(ws / "intermediate_data.json"),
            "--workspace", str(ws)]
    print(f"📊 生成辩论报告: {' '.join(cmd)}")
    return subprocess.call(cmd)


def run_a2a(workspace: str) -> int:
    """调用 export_a2a.py 导出 A2A 兼容格式。"""
    cmd = [sys.executable,
            str(SCRIPTS / "export_a2a.py"),
            "--workspace", str(workspace)]
    print(f"🔗 A2A 导出: {' '.join(cmd)}")
    return subprocess.call(cmd)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="FDT 辩论主动驱动层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="产出标准化 spawn 计划 JSON")
    p_plan.add_argument("--scan", required=True)
    p_plan.add_argument("--workspace", required=True)
    p_plan.add_argument("--check-resources", action="store_true",
                        help="spawn前调用 resource_watchdog 动态算并发数，不写死")

    p_fin = sub.add_parser("finalize", help="组装+萃取+报告（spawn 后收口）")
    p_fin.add_argument("--scan", required=True)
    p_fin.add_argument("--workspace", required=True)

    p_asm = sub.add_parser("assemble", help="仅组装 debate_results.json")
    p_asm.add_argument("--scan", required=True)
    p_asm.add_argument("--workspace", required=True)

    p_ext = sub.add_parser("extract", help="仅批量萃取")
    p_ext.add_argument("--workspace", required=True)

    p_rep = sub.add_parser("report", help="仅生成报告")
    p_rep.add_argument("--workspace", required=True)

    p_a2a = sub.add_parser("a2a", help="导出 A2A 兼容格式（Agent-to-Agent Protocol）")
    p_a2a.add_argument("--workspace", required=True)

    p_val = sub.add_parser("validate", help="仅信号复查")
    p_val.add_argument("--workspace", required=True)
    p_val.add_argument("--scan", help="scan JSON（可选，用于品种数交叉校验）")

    args = ap.parse_args()
    # 归一化路径（Git Bash /d/… → D:\…）
    if getattr(args, 'workspace', None):
        args.workspace = _to_win_path(args.workspace)
    if getattr(args, 'scan', None):
        args.scan = _to_win_path(args.scan)
    ws = Path(args.workspace)

    # extract/report/validate/a2a 不需要 scan 文件
    if args.cmd in ("extract", "report", "validate", "a2a"):
        if args.cmd == "extract":
            run_extract(str(ws))
        elif args.cmd == "report":
            run_report(str(ws))
        elif args.cmd == "validate":
            run_validate(str(ws), getattr(args, 'scan', None))
        elif args.cmd == "a2a":
            run_a2a(str(ws))
        return

    # plan/assemble/finalize 需要 scan 文件
    scan = json.load(open(args.scan, encoding="utf-8"))
    threshold = load_debate_threshold()
    data_benchmark = derive_data_benchmark(scan)

    if args.cmd == "plan":
        triggers = select_triggers(scan, threshold)
        print(f"🔔 触发品种（|total|≥{threshold}）: {[t['symbol'] for t in triggers]}")
        plan = build_spawn_plan(triggers, str(ws), data_benchmark)
        # ── 资源感知：动态调整并发数 ──
        if getattr(args, 'check_resources', False):
            try:
                import subprocess as _sp, json as _json
                watchdog = _FDT_ROOT / "scripts" / "resource_watchdog.py"
                for ph_name, ph_info in plan.get("execution_phases", {}).items():
                    r = _sp.run(
                        [sys.executable, str(watchdog), "--phase", ph_name],
                        capture_output=True, text=True, timeout=15,
                    )
                    if r.returncode == 0:
                        rc = _json.loads(r.stdout)
                        new_max = rc.get("safe_concurrent", ph_info["max_concurrent"])
                        old_max = ph_info["max_concurrent"]
                        ph_info["max_concurrent"] = new_max
                        ph_info["resource_note"] = rc.get("reason", "")
                        print(f"  📊 {ph_name}: 基础{old_max}→动态{new_max}（{rc.get('reason','')}）")
            except Exception as e:
                print(f"  ⚠️ 资源检查失败（{e}），使用基础并发值")
        out = ws / f"spawn_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"📋 spawn 计划: {out}")

    elif args.cmd == "assemble":
        out = assemble(scan, str(ws), data_benchmark)
        generate_intermediate_data(scan, str(ws), data_benchmark)
        if run_validate(str(ws), args.scan) != 0:
            sys.exit(1)

    elif args.cmd == "finalize":
        out = assemble(scan, str(ws), data_benchmark)
        generate_intermediate_data(scan, str(ws), data_benchmark)
        if run_validate(str(ws), args.scan) != 0:
            sys.exit(1)
        run_extract(str(ws))
        run_report(str(ws))
        run_a2a(str(ws))


if __name__ == "__main__":
    main()
