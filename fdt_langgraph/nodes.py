"""LangGraph 辩论节点函数 — 重导出层。

所有函数已按职责拆分至 `_nodes_*.py` 模块。
外部导入继续通过本文件访问，无需修改。
"""

from __future__ import annotations

from fdt_langgraph.agents import FdtAgentExecutor

# ── 代码-推理边界 (L0 硬约束) ──
from fdt_langgraph._nodes_boundary import (
    _clamp_position,
    _compute_stop_target,
)

# ── 共享工具函数 ──
from fdt_langgraph._nodes_utils import (
    ATTACK_DIMENSIONS,
    DEBATE_DIVERGENCE_THRESHOLDS,
    EVIDENCE_WEIGHT_FACTORS,
    _ensure_llm_key,
    _import_from_skill,
    _import_skill_module,
    _inject_memory_rules,
    _normalize_per_symbol,
    _repair_json,
    _resolve_alias,
    _resolve_report_dir,
    _trim_arguments,
    _truncate_arguments_text,
)

# ── 上下文构建函数 ──
from fdt_langgraph._nodes_context import (
    _build_data_sources,
    _build_debate_context,
    _build_fdc_fundamental_context,
    _build_fdc_technical_context,
    _build_market_fundamental_context,
    _build_market_technical_context,
    _build_scan_signal_table,
    _build_signal_summary_html,
)

# ── 准备阶段节点 (P0-P2.5) ──
from fdt_langgraph._nodes_prepare import (
    node_freshness_gate,
    node_judge_direction,
    node_load_cache,
    node_prepare_data,
    node_scan,
    node_update_cache,
)

# ── 研究阶段节点 (P3) ──
from fdt_langgraph._nodes_research import (
    node_chain,
    node_fundamental,
    node_merge_research,
    node_sentiment,
    node_technical,
)

# ── 辩论阶段节点 (P4) ──
from fdt_langgraph._nodes_debate import (
    _parse_per_symbol_debate,
    node_bear_final,
    node_bearish_rebuttal,
    node_bearish_v1,
    node_bull_final,
    node_bullish_rebuttal,
    node_bullish_v1,
    node_prepare_one_symbol,
)

# ── 裁决阶段节点 (P5) ──
from fdt_langgraph._nodes_verdict import (
    node_aggregate_results,
    node_quality_inspect,
    node_risk_check,
    node_route_next_symbol,
    node_store_per_symbol_result,
    node_verdict,
)

# ── 输出阶段节点 (P6-P6a) ──
from fdt_langgraph._nodes_output import (
    _load_template_css,
    _load_template_html,
    _render_html,
    _write_research_report,
    _write_scan_report,
    _write_signal_report,
    _write_verdict_report,
    node_report,
    node_signal_output,
)
