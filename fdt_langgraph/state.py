import operator
from datetime import datetime
from typing import Annotated, Literal, Optional, TypedDict


def _debate_args_reducer(current: list, update: list) -> list:
    """辩论论据的 reducer：空列表表示跨品种重置，非空表示追加。

    prepare_one_symbol 在切换品种时清空论据（传入 []），
    此 reducer 检测到空列表时直接返回 [] 实现重置；
    辩论节点正常追加时使用 operator.add（list + list）。
    """
    if not update:
        return []  # 品种切换：清空上一品种的论据
    return current + update  # 辩论节点追加新数据


class FdcSymbolData(TypedDict, total=False):
    kline: dict
    indicators: dict
    term_structure: dict
    spread: dict
    basis: dict
    warrant: dict
    fundamental: dict
    position_ranking: dict
    f10_summary: dict
    data_grades: dict


class FdcDataStatus(TypedDict, total=False):
    enabled: bool
    collected: bool
    total_symbols: int
    success_symbols: int
    errors: dict
    elapsed_seconds: float
    kline_days: int
    f10_enabled: bool
    position_ranking_enabled: bool


class DebateState(TypedDict, total=False):
    trace_id: str
    timestamp: datetime
    mode: Literal["default", "fast", "deep_research", "tournament"]

    scan_results: dict
    scan_summary: Optional[dict]

    judge_direction: Optional[dict]
    selected_symbols: list
    dispatch_sources: list

    fdc_data: dict
    fdc_data_status: Optional[FdcDataStatus]

    chain_analysis: Optional[dict]
    technical_data: dict
    fundamental_data: dict
    sentiment_data: Optional[dict]          # P3 新闻情绪分析（读心）
    research_data: Optional[dict]
    wind_data: Optional[dict]               # GAP-015: Wind 补充数据（可转债估值/ETF持仓/宏观EDB/公告）

    # v9.0 多空头攻防模式 — 六阶段辩论
    # GAP-006: 使用 _debate_args_reducer 而非 operator.add，
    # 使 prepare_one_symbol 传入 [] 时正确重置论据（而非累积）。
    bullish_arguments: Annotated[list, _debate_args_reducer]              # P4_1 多头立论
    bearish_arguments: Annotated[list, _debate_args_reducer]              # P4_2 空头立论
    bearish_rebuttal_arguments: Annotated[list, _debate_args_reducer]     # P4_3 空头反驳多头
    bullish_rebuttal_arguments: Annotated[list, _debate_args_reducer]     # P4_4 多头反驳空头
    bear_final_arguments: Annotated[list, _debate_args_reducer]           # P4_5 空头最终陈述
    bull_final_arguments: Annotated[list, _debate_args_reducer]           # P4_6 多头最终陈述
    data_sources: list                                            # 数据溯源清单
    debate_round: int

    verdict: Optional[dict]
    risk_check: Optional[dict]
    signal_output: Optional[dict]

    # v8.8.0 阶段报告路径（明鉴秋报告层调度）
    scan_report_path: Optional[str]      # P1 信号扫描报告
    research_report_path: Optional[str]   # P3 研究报告
    verdict_report_path: Optional[str]    # P5 裁决报告
    report_path: Optional[str]            # P6 辩论报告（最终裁决+交易建议）
    signal_report_path: Optional[str]     # P6a CTP信号扫描报告

    current_phase: str
    error: Optional[str]
    completed_phases: list
    phase_start_time: Optional[float]

    # v9.13.0: 逐品种循环处理
    symbol_index: int                       # 当前处理品种在 selected_symbols 中的索引，-1=未开始
    per_symbol_results: dict                # {symbol: {research, debate, verdict, risk}}
    _original_symbols: list                 # 保存完整品种列表，循环中用
    associated_symbols: dict                # {primary_symbol: [associated_symbols]} 关联品种

    # v9.22.3: P0b 数据新鲜度闸门
    freshness_report: Optional[dict]        # 数据新鲜度报告（R24闸门结果）

    # v10.6.0: 全市场扩展 — 品种市场类型
    market_type: Optional[str]              # commodity_futures/index_futures/bond_futures/etf

    # v0.10.6: G97 连续合约复权价差校准
    price_adjustments: dict[str, float]     # {symbol: adjustment}

    # v9.14.0: Phase 3 辩论输出质量治理
    quality_report: Optional[dict]          # 当前质检结果 QualityReport
    rework_counters: dict                   # {symbol: retry_count} 品种级重试计数
    rework_pending_symbols: list            # 待退回重修的品种列表
    phase_timings: list                     # [PhaseTiming] 各阶段耗时记录
    quality_metrics: Optional[dict]         # 自优化指标 QualityMetrics


def create_initial_state(trace_id: str, mode: str = "fast") -> DebateState:
    return DebateState(
        trace_id=trace_id,
        timestamp=datetime.now(),
        mode=mode,
        scan_results={},
        scan_summary=None,
        judge_direction=None,
        selected_symbols=[],
        dispatch_sources=[],
        fdc_data={},
        fdc_data_status=None,
        chain_analysis=None,
        technical_data={},
        fundamental_data={},
        sentiment_data={},
        research_data=None,
        bullish_arguments=[],
        bearish_arguments=[],
        bearish_rebuttal_arguments=[],
        bullish_rebuttal_arguments=[],
        bear_final_arguments=[],
        bull_final_arguments=[],
        data_sources=[],
        debate_round=0,
        verdict=None,
        risk_check=None,
        signal_output=None,
        scan_report_path=None,
        research_report_path=None,
        verdict_report_path=None,
        report_path=None,
        signal_report_path=None,
        current_phase="P0",
        error=None,
        completed_phases=[],
        phase_start_time=None,
        symbol_index=-1,
        per_symbol_results={},
        _original_symbols=[],
        associated_symbols={},
        market_type=None,
        price_adjustments={},
        quality_report=None,
        rework_counters={},
        rework_pending_symbols=[],
        phase_timings=[],
        freshness_report=None,
        quality_metrics=None,
    )
