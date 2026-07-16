#!/usr/bin/env python3
"""
期货辩论专家团 — 全自动零人工干预流水线
=========================================

用途: 每日收盘后全自动运行，无人值守。
流程: 三生产者扫描(数技源 channel_breakout + 观澜 L1-L4 + 探源 factor_timing) → chain_analysis → debate_brief(增强版)
      → assemble_intermediate → phase3_generate_report
      → debate_history自动记录 → TrainingOrchestrator检查

输出目录: ~/Documents/WorkBuddy/Commodities/Reports/商品期货深度分析/{YYYY-MM-DD}/
"""

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone

# ── 统一日志 + 链路追踪 ──────────────────────────────────
_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_PIPELINE_DIR)
sys.path.insert(0, _PROJECT_DIR)

from scripts.unified_logger import get_logger
from scripts.trace_id import new_trace, current_trace, inject_trace_to_env

# ── 路径常量 ────────────────────────────────────────────
HOME = os.path.expanduser("~")
PROJECT_DIR = _PROJECT_DIR
SKILLS_DIR = os.path.join(PROJECT_DIR, "skills")
QDAILY_DIR = os.path.join(SKILLS_DIR, "quant-daily", "scripts")
COMMODITY_DIR = os.path.join(SKILLS_DIR, "commodity-chain-analysis", "scripts")
FT_ANALYSIS_DIR = os.path.join(SKILLS_DIR, "futures-trading-analysis", "scripts")
SIGNALS_DIR = os.path.join(QDAILY_DIR, "signals")
TECHA_DIR = os.path.join(SKILLS_DIR, "technical-analysis", "scripts")
FDC_DIR = os.path.join(SKILLS_DIR, "fundamental-data-collector", "scripts")

# 品种列表（从 config/symbols.py 导入，与 scan_all 保持一致）
try:
    sys.path.insert(0, QDAILY_DIR)
    from config.symbols import ALL_SYMBOLS
    ALL_SYMBOL_CODES = [s[0] for s in ALL_SYMBOLS]
except Exception:
    ALL_SYMBOLS = []
    ALL_SYMBOL_CODES = []

TODAY = datetime.now()
DATE_STR = TODAY.strftime("%Y-%m-%d")
DATE_COMPACT = TODAY.strftime("%Y%m%d")
REPORT_DIR = os.path.join(
    HOME,
    "Documents",
    "WorkBuddy",
    "Commodities",
    "Reports",
    "商品期货深度分析",
    DATE_STR,
)

# ── 流水线日志（统一使用 unified_logger） ──────────────
_log_dir = os.path.join(
    os.path.dirname(REPORT_DIR),  # .../Reports/商品期货深度分析/../
)
logger = get_logger("pipeline", log_dir=_log_dir)


def python_exe() -> str:
    """获取 Python 可执行路径"""
    # 优先使用当前运行的 Python
    return sys.executable


def log_path() -> str:
    """日志文件路径"""
    lp = os.path.join(REPORT_DIR, "..", f"pipeline_{DATE_COMPACT}.log")
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    return os.path.abspath(lp)


def run_cmd(cmd: list, desc: str, check: bool = True) -> subprocess.CompletedProcess:
    """通用命令执行包装器"""
    logger.info(f"▶ [{desc}] {cmd}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
            timeout=600,
            check=check,
            env=inject_trace_to_env({"PYTHONIOENCODING": "utf-8"}),
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                logger.info(f"  {line}")
        if result.returncode != 0:
            for line in result.stderr.strip().split("\n")[-10:]:
                logger.warning(f"  ⚠ {line}")
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"✗ [{desc}] 超时 (600s)")
        if check:
            raise
        return subprocess.CompletedProcess(cmd, -1, "", "TIMEOUT")
    except Exception as e:
        logger.error(f"✗ [{desc}] {e}")
        if check:
            raise
        return subprocess.CompletedProcess(cmd, -1, "", str(e))


def step_scan() -> bool:
    """Step 1: 三生产者信号生成（辩论流水线 P1）

    数技源 scan_all.py (channel_breakout，默认) → full_scan_summary_{date}.json
    观澜 run_l1l4_scan.py                  → full_scan_l1l4_{date}.json
    探源 run_factor_timing_scan.py         → full_scan_factor_timing_{date}.json
    三者均落地到 REPORT_DIR，供 step_debate_brief 读取。

    环境变量控制：
    - FDT_SCAN_MODE: no-filter 禁用伪信号过滤
    - FDT_STRATEGIES: 指定策略列表，逗号分隔（如 trend_following,mean_reversion）
    """
    logger.info("=" * 60)
    logger.info("Step 1/6: 三生产者扫描 (数技源 + 观澜 + 探源)")
    logger.info("=" * 60)

    sym_arg = ",".join(ALL_SYMBOL_CODES) if ALL_SYMBOL_CODES else None

    # 环境变量读取
    scan_mode = os.environ.get("FDT_SCAN_MODE", "")
    strategies = os.environ.get("FDT_STRATEGIES", "")

    # 1) 数技源: 通道突破（默认 channel_breakout）
    cmd_cb = [
        python_exe(),
        os.path.join(QDAILY_DIR, "scan_all.py"),
        "-o", REPORT_DIR,
        "-p", "full_scan_summary",
    ]
    if scan_mode == "no-filter":
        cmd_cb.append("--disable-filter")
    if strategies:
        cmd_cb.append("--strategies")
        cmd_cb.append(strategies)
    run_cmd(cmd_cb, "通道突破扫描", check=False)

    # 2) 观澜: L1-L4 分层指标
    cmd_l1l4 = [python_exe(), os.path.join(TECHA_DIR, "run_l1l4_scan.py"), "--output-dir", REPORT_DIR]
    cmd_l1l4 += ["--symbols", sym_arg] if sym_arg else ["--all"]
    run_cmd(cmd_l1l4, "L1-L4 扫描", check=False)

    # 3) 探源: 因子择时（五因子）
    cmd_ft = [python_exe(), os.path.join(FDC_DIR, "run_factor_timing_scan.py"), "--output-dir", REPORT_DIR]
    cmd_ft += ["--symbols", sym_arg] if sym_arg else ["--all"]
    run_cmd(cmd_ft, "因子择时扫描", check=False)

    files = [
        os.path.join(REPORT_DIR, f"full_scan_summary_{DATE_COMPACT}.json"),
        os.path.join(REPORT_DIR, f"full_scan_l1l4_{DATE_COMPACT}.json"),
        os.path.join(REPORT_DIR, f"full_scan_factor_timing_{DATE_COMPACT}.json"),
    ]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        logger.warning(f"以下扫描产物缺失，下游可能降级: {[os.path.basename(m) for m in missing]}")
    return len(missing) == 0


def step_chain_analysis() -> bool:
    """Step 2: 产业链分析"""
    logger.info("=" * 60)
    logger.info("Step 2/6: 产业链分析")
    logger.info("=" * 60)

    # 确认分析脚本存在
    analysis_script = os.path.join(COMMODITY_DIR, "analyze_chain.py")
    if not os.path.exists(analysis_script):
        logger.warning(f"analyze_chain.py 不存在 {analysis_script}，跳过链分析")
        return False

    symbols_arg = ",".join(ALL_SYMBOL_CODES) if ALL_SYMBOL_CODES else ""
    if not symbols_arg:
        logger.warning("无法获取品种列表，跳过链分析")
        return False
    cmd = [python_exe(), analysis_script, "--symbols", symbols_arg]
    r = run_cmd(cmd, "产业链分析", check=False)
    return r.returncode == 0


def step_debate_brief() -> bool:
    """Step 3: debate_brief.py 辩论品种精选 (增强版, 含历史反馈)"""
    logger.info("=" * 60)
    logger.info("Step 3/6: debate_brief.py 辩论品种精选")
    logger.info("=" * 60)

    summary_path = os.path.join(REPORT_DIR, f"full_scan_summary_{DATE_COMPACT}.json")
    l1l4_path = os.path.join(REPORT_DIR, f"full_scan_l1l4_{DATE_COMPACT}.json")
    factor_path = os.path.join(REPORT_DIR, f"full_scan_factor_timing_{DATE_COMPACT}.json")

    if not all(os.path.exists(p) for p in [summary_path, l1l4_path, factor_path]):
        logger.error("scan_all 输出文件不完整，跳过分歧品种评选")
        return False

    # 查找最近的 chain_analysis JSON
    chain_analysis_dir = os.path.join(COMMODITY_DIR, "Reports")
    chain_file = None
    if os.path.exists(chain_analysis_dir):
        candidates = sorted(
            [f for f in os.listdir(chain_analysis_dir) if f.startswith("chain_analysis_") and f.endswith(".json")],
            reverse=True,
        )
        if candidates:
            chain_file = os.path.join(chain_analysis_dir, candidates[0])

    if not chain_file or not os.path.exists(chain_file):
        # 尝试从报告目录找
        report_chain = os.path.join(REPORT_DIR, "chain_analysis_report.json")
        if os.path.exists(report_chain):
            chain_file = report_chain

    if not chain_file:
        logger.warning("未找到 chain_analysis 文件，跳过辩论品种精选")
        return False

    # 历史反馈路径
    history_dir = os.path.join(os.path.dirname(os.path.dirname(QDAILY_DIR)), "data", "debate_history")
    history_file = os.path.join(history_dir, "debate_feedback.json")

    cmd = [
        python_exe(),
        os.path.join(SIGNALS_DIR, "debate_brief.py"),
        l1l4_path,
        factor_path,
        "-o",
        REPORT_DIR,
        "--select-debate",
        chain_file,
        "--min-count",
        "20",
        "--min-chains",
        "12",
    ]
    if os.path.exists(history_file):
        cmd += ["--history-path", history_file]

    r = run_cmd(cmd, "辩论品种精选", check=False)
    return r.returncode == 0


def step_assemble_intermediate() -> bool:
    """Step 4: assemble_intermediate_data.py 数据适配"""
    logger.info("=" * 60)
    logger.info("Step 4/6: assemble_intermediate_data.py 数据适配")
    logger.info("=" * 60)

    summary_path = os.path.join(REPORT_DIR, f"full_scan_summary_{DATE_COMPACT}.json")
    chain_strategy_path = os.path.join(REPORT_DIR, "chain_strategy_report.json")
    chain_analysis_dir = os.path.join(COMMODITY_DIR, "Reports")

    # 找chain_analysis json
    chain_analysis_file = None
    if os.path.exists(chain_analysis_dir):
        candidates = sorted(
            [f for f in os.listdir(chain_analysis_dir) if f.startswith("chain_analysis_") and f.endswith(".json")],
            reverse=True,
        )
        if candidates:
            chain_analysis_file = os.path.join(chain_analysis_dir, candidates[0])

    if not chain_analysis_file or not os.path.exists(chain_analysis_file):
        # fallback: 用chain_analysis_report
        alt = os.path.join(REPORT_DIR, "chain_analysis_report.json")
        if os.path.exists(alt):
            chain_analysis_file = alt

    if not chain_analysis_file or not os.path.exists(chain_analysis_file):
        logger.warning("未找到 chain_analysis 文件，跳过 assemble_intermediate_data")
        return False

    cmd = [
        python_exe(),
        os.path.join(QDAILY_DIR, "assemble_intermediate_data.py"),
        "--summary",
        summary_path,
        "--chain-analysis",
        chain_analysis_file,
        "--output-dir",
        REPORT_DIR,
    ]
    if os.path.exists(chain_strategy_path):
        cmd += ["--chain-strategy", chain_strategy_path]

    r = run_cmd(cmd, "数据适配", check=False)
    return r.returncode == 0


def step_generate_report() -> bool:
    """Step 5: phase3_generate_report.py 深度分析报告"""
    logger.info("=" * 60)
    logger.info("Step 5/6: phase3_generate_report.py 报告生成")
    logger.info("=" * 60)

    report_script = os.path.join(FT_ANALYSIS_DIR, "phase3_generate_report.py")
    if not os.path.exists(report_script):
        logger.error(f"报告生成脚本不存在 {report_script}")
        return False

    cmd = [python_exe(), report_script]
    r = run_cmd(cmd, "报告生成", check=False)
    return r.returncode == 0


def step_record_history() -> bool:
    """Step 6: 自动记录辩论历史到 debate_history + 同步裁决到 execution_followup"""
    logger.info("=" * 60)
    logger.info("Step 6/6: 辩论历史记录 + 裁决同步 + ML训练检查")
    logger.info("=" * 60)

    try:
        # 检查候选文件是否存在
        candidates_file = os.path.join(REPORT_DIR, f"signal_summary_candidates.json")
        # 尝试不同前缀
        if not os.path.exists(candidates_file):
            candidates_file = os.path.join(REPORT_DIR, f"full_scan_summary_candidates.json")
        if not os.path.exists(candidates_file):
            # 找最近的文件
            import glob

            matches = glob.glob(os.path.join(REPORT_DIR, "*candidates*.json"))
            if matches:
                candidates_file = matches[0]
            else:
                logger.warning("未找到候选文件，跳过历史记录")
                return False

        logger.info(f"候选文件: {candidates_file}")

        # 记录到 debate_history（debate/history.py 在项目根目录）
        sys.path.insert(0, PROJECT_DIR)
        from debate.history import record_feedback, load_feedback

        with open(candidates_file, "r", encoding="utf-8") as f:
            selection = json.load(f)

        candidates = selection.get("debate_candidates", [])
        logger.info(f"共 {len(candidates)} 个候选品种")

        high_value = [c for c in candidates if c.get("debate_value", 0) >= 70]
        logger.info(f"  高价值(≥70): {len(high_value)} 个")

        # 记录辩论价值
        for c in candidates[:5]:  # 按辩论价值排名的前5个
            sym = c.get("symbol", "")
            dv = c.get("debate_value", 0)
            tag = " | ".join(c.get("tags", []))
            logger.info(f"  {sym}: debate_value={dv}, tags=[{tag}]")
            record_feedback(sym, dv, judge_confidence=50)

        logger.info("辩论历史记录完成")

    except Exception as e:
        logger.warning(f"记录历史失败: {e}")
        return False

    # ── 裁决同步：将 debate_results.json 同步到 execution_followup.json ──
    try:
        # 查找 debate_results.json（可能在 REPORT_DIR 或显式路径）
        debate_results_files = [
            os.path.join(REPORT_DIR, "debate_results.json"),
            os.path.join(REPORT_DIR, f"debate_results_{DATE_COMPACT}.json"),
        ]
        debate_results_path = None
        for p in debate_results_files:
            if os.path.exists(p):
                debate_results_path = p
                break

        if debate_results_path:
            record_script = os.path.join(PROJECT_DIR, "scripts", "record_verdicts.py")
            if os.path.exists(record_script):
                r = subprocess.run(
                    [sys.executable, record_script, "--input", debate_results_path],
                    capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace",
                )
                if r.returncode == 0:
                    logger.info(f"✅ 裁决已同步至 execution_followup.json")
                else:
                    logger.warning(f"裁决同步返回非零: {r.stderr.strip()[-200:]}")
            else:
                logger.warning(f"record_verdicts.py 不存在: {record_script}")
        else:
            logger.info("未找到 debate_results.json, 跳过裁决同步")
    except Exception as e:
        logger.warning(f"裁决同步失败: {e}")

    # ML训练检查
    try:
        logger.info("检查 ML 训练条件...")
        from ml.trainer import TrainingOrchestrator

        orch = TrainingOrchestrator()
        status = orch.get_status()
        logger.info(f"  ML状态: 已训练{status['total_trained']}次, 已部署{status['total_deployed']}次")

        result = orch.run_daily_check(new_samples_count=len(candidates))
        logger.info(f"  ML检查结果: {result.get('final_decision', '无')}")
        if result.get("final_decision") == "deployed":
            logger.info("  ✅ 新模型已自动部署")
        elif result.get("final_decision") == "flagged_need_review":
            logger.warning("  ⚠ 候选模型需要审查")
    except Exception as e:
        logger.warning(f"ML训练检查失败: {e}")

    return True


def clean_xgboost_warning():
    """静默 XGBoost 警告（如果未安装）"""
    import warnings

    warnings.filterwarnings("ignore", message="XGBoost is not installed")


def run_langgraph_pipeline(trace_id: str) -> int:
    """LangGraph 模式流水线 — 使用 fdt_langgraph 图编排替代 subprocess 步骤。

    当 FDT_USE_LANGGRAPH=true 时由 main() 调用。
    保持与旧 pipeline 相同的 6 步骤语义，但通过 LangGraph 节点函数执行。
    """
    logger.info("=" * 60)
    logger.info("🤖 期货辩论专家团 — LangGraph 模式")
    logger.info(f"   Trace: {trace_id}")
    logger.info(f"   日期: {DATE_STR}")
    logger.info("=" * 60)

    try:
        import asyncio
        from fdt_langgraph.state import create_initial_state
        from fdt_langgraph.graph import build_debate_graph_no_checkpoint
        from fdt_langgraph.health import run_health_check
    except ImportError as e:
        logger.error(f"LangGraph 模块不可用: {e}，回退到 subprocess 模式")
        return -1

    async def _run():
        mode = os.environ.get("FDT_LANGGRAPH_MODE", "default")
        state = create_initial_state(trace_id, mode=mode)
        state["selected_symbols"] = ALL_SYMBOL_CODES[:10] if ALL_SYMBOL_CODES else ["RB"]

        graph = build_debate_graph_no_checkpoint(mode=mode)
        config = {"configurable": {"thread_id": trace_id}}

        logger.info(f"▶ LangGraph 图执行开始 (mode={mode})")
        final_state = await graph.ainvoke(state, config=config)

        # 健康检查
        health = run_health_check(state=final_state)
        logger.info(f"  健康状态: {health.get('overall_status', 'unknown')}")

        # 报告路径
        report_path = final_state.get("report_path", "")
        if report_path:
            logger.info(f"📄 报告已生成: {report_path}")

        return final_state

    try:
        result = asyncio.run(_run())
        logger.info("✅ LangGraph 流水线完成")
        return 0
    except Exception as e:
        logger.error(f"LangGraph 流水线失败: {e}")
        traceback.print_exc()
        return 1


def main():
    """全自动管道主流程"""
    clean_xgboost_warning()

    # 生成 trace_id（贯穿全链路，注入子进程环境变量）
    trace_id = new_trace("daily")

    # ── A/B 切换：FDT_USE_LANGGRAPH=true 走 LangGraph 图编排 ──
    use_langgraph = os.environ.get("FDT_USE_LANGGRAPH", "").lower() in ("true", "1", "yes")
    if use_langgraph:
        logger.info("🔧 FDT_USE_LANGGRAPH=true → LangGraph 模式")
        ret = run_langgraph_pipeline(trace_id)
        if ret >= 0:
            return ret
        logger.warning("LangGraph 模式不可用，回退到 subprocess 模式")

    # 确保报告目录存在
    os.makedirs(REPORT_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"🤖 期货辩论专家团 — 全自动流水线 (subprocess 模式)")
    logger.info(f"   Trace: {trace_id}")
    logger.info(f"   日期: {DATE_STR}")
    logger.info(f"   项目: {PROJECT_DIR}")
    logger.info(f"   报告: {REPORT_DIR}")
    logger.info("=" * 60)

    # 步骤执行（每一步失败不阻断后续）
    results = {}

    # Step 1: 三生产者扫描
    results["scan"] = step_scan()
    if not results["scan"]:
        logger.warning("Step 1 (三生产者扫描) 未全部产出，但尝试继续")

    # Step 2: 产业链分析
    results["chain"] = step_chain_analysis()

    # Step 3: 辩论品种精选
    results["debate_brief"] = step_debate_brief()

    # Step 4: 数据适配
    results["assemble"] = step_assemble_intermediate()

    # Step 5: 报告生成
    results["report"] = step_generate_report()

    # Step 6: 历史记录 + ML检查
    results["history"] = step_record_history()

    # 汇总
    logger.info("=" * 60)
    logger.info("📊 流水线执行汇总")
    logger.info("=" * 60)
    all_ok = True
    for step_name, ok in results.items():
        status = "✅" if ok else "⚠️"
        logger.info(f"  {status} {step_name}")
        if not ok:
            all_ok = False

    html_path = os.path.join(REPORT_DIR, f"daily_analysis_{DATE_COMPACT}.html")
    if os.path.exists(html_path):
        logger.info(f"\n📄 报告已生成: {html_path}")
    else:
        logger.warning(f"\n⚠️ HTML报告未生成")
        all_ok = False

    logger.info(f"\n{'✅ 流水线完成' if all_ok else '⚠️ 部分步骤有警告'}")
    logger.info(f"   Trace: {current_trace()}")
    logger.info(f"   日志: {_log_dir}")
    logger.info(f"   报告: {REPORT_DIR}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.critical(f"流水线崩溃: {e}")
        traceback.print_exc()
        sys.exit(2)
