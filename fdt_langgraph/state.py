from typing import TypedDict, Optional, Literal
from datetime import datetime


class DebateState(TypedDict, total=False):
    trace_id: str
    timestamp: datetime
    mode: Literal["default", "fast", "deep_research", "tournament"]

    scan_results: dict
    scan_summary: Optional[dict]

    judge_direction: Optional[dict]
    selected_symbols: list
    dispatch_sources: list

    chain_analysis: Optional[dict]
    technical_data: dict
    fundamental_data: dict
    research_data: Optional[dict]

    bullish_arguments: list
    bearish_arguments: list

    verdict: Optional[dict]
    trading_plan: Optional[dict]
    risk_check: Optional[dict]

    report_path: Optional[str]

    current_phase: str
    error: Optional[str]
    completed_phases: list
    phase_start_time: Optional[float]


def create_initial_state(trace_id: str, mode: str = "default") -> DebateState:
    return DebateState(
        trace_id=trace_id,
        timestamp=datetime.now(),
        mode=mode,
        scan_results={},
        scan_summary=None,
        judge_direction=None,
        selected_symbols=[],
        dispatch_sources=[],
        chain_analysis=None,
        technical_data={},
        fundamental_data={},
        research_data=None,
        bullish_arguments=[],
        bearish_arguments=[],
        verdict=None,
        trading_plan=None,
        risk_check=None,
        report_path=None,
        current_phase="P0",
        error=None,
        completed_phases=[],
        phase_start_time=None
    )