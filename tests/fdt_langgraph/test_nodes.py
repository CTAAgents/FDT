from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fdt_langgraph.graph import (
    route_after_merge_research,
)
from fdt_langgraph.nodes import (
    _build_fdc_technical_context,
    node_bear_final,
    node_bearish_rebuttal,
    node_bearish_v1,
    node_bull_final,
    node_bullish_rebuttal,
    node_bullish_v1,
    node_chain,
    node_fundamental,
    node_judge_direction,
    node_merge_research,
    node_report,
    node_risk_check,
    node_scan,
    node_signal_output,
    node_technical,
    node_verdict,
)
from fdt_langgraph.state import DebateState, create_initial_state


def create_test_state(mode="default") -> DebateState:
    return create_initial_state("test-trace", mode)


@pytest.mark.asyncio
async def test_node_scan():
    state = create_test_state()
    result = await node_scan(state)
    assert result["scan_results"] is not None
    assert result["current_phase"] == "P1"
    assert "P1" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_judge_direction():
    state = create_test_state()
    state["scan_results"] = {"RB": {"score": 50}}
    result = await node_judge_direction(state)
    assert result["judge_direction"] is not None
    assert result["selected_symbols"] is not None
    assert result["current_phase"] == "P2"
    assert "P2" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_chain():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_chain(state)
    assert result["chain_analysis"] is not None


@pytest.mark.asyncio
async def test_node_technical():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_technical(state)
    assert result["technical_data"] is not None


@pytest.mark.asyncio
async def test_node_fundamental():
    state = create_test_state()
    state["selected_symbols"] = ["RB"]
    result = await node_fundamental(state)
    assert result["fundamental_data"] is not None


@pytest.mark.asyncio
async def test_node_merge_research():
    state = create_test_state()
    state["chain_analysis"] = {"industry": "steel"}
    state["technical_data"] = {"RB": {"adx": 60}}
    state["fundamental_data"] = {"RB": {"inventory": 100}}
    state["completed_phases"] = ["P1", "P2"]
    result = await node_merge_research(state)
    assert result["research_data"] is not None
    assert "P2" in result["completed_phases"]


@pytest.mark.asyncio
async def test_node_bullish_v1():
    """P3 步1: 多头立论 v1"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["completed_phases"] = ["P1", "P2", "P2"]
    result = await node_bullish_v1(state)
    assert result["bullish_arguments"] is not None
    assert len(result["bullish_arguments"]) == 1
    assert result["bullish_arguments"][0]["phase"] == "v1"
    assert result["bullish_arguments"][0]["role"] == "bullish"
    assert result["debate_round"] == 1
    assert result["current_phase"] == "P3_bullish_v1"


@pytest.mark.asyncio
async def test_node_bearish_v1():
    """P3 步2: 空头立论 — 独立做空论据 v1（不再是对多头质疑）"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["debate_round"] = 1
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1"]
    result = await node_bearish_v1(state)
    assert result["bearish_arguments"] is not None
    assert len(result["bearish_arguments"]) == 1
    assert result["bearish_arguments"][0]["phase"] == "v1"
    assert result["bearish_arguments"][0]["role"] == "bearish"
    assert result["debate_round"] == 2
    assert result["current_phase"] == "P3_bearish_v1"


@pytest.mark.asyncio
async def test_node_bullish_rebuttal():
    """P3 步4: 多头反驳 — 针对空头立论和空头反驳进行再反驳"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    # 注入完整历史：多头v1 + 空头v1（独立做空论据）
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["bearish_arguments"] = [
        {"round": 2, "role": "bearish", "phase": "v1", "symbols": {"RB": {"arguments": ["做空论据1"], "confidence": 0.6}}}
    ]
    state["debate_round"] = 2
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1"]
    result = await node_bullish_rebuttal(state)
    # node_bullish_rebuttal 写入 bullish_rebuttal_arguments（非 bullish_arguments）
    assert result["bullish_rebuttal_arguments"] is not None
    assert len(result["bullish_rebuttal_arguments"]) == 1
    assert result["bullish_rebuttal_arguments"][0]["phase"] == "rebuttal"
    assert result["bullish_rebuttal_arguments"][0]["role"] == "bullish"
    assert result["bullish_rebuttal_arguments"][0]["round"] == 4
    assert result["debate_round"] == 3
    assert result["current_phase"] == "P3_bullish_rebuttal"


@pytest.mark.asyncio
async def test_node_bearish_rebuttal():
    """P3 步3: 空头反驳多头立论 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["debate_round"] = 1
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1"]
    # Mock FdtAgentExecutor to return a dict with JSON output
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["反驳看多论据1"], "confidence": 0.65}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bearish_rebuttal(state)
    assert result["bearish_rebuttal_arguments"] is not None
    assert len(result["bearish_rebuttal_arguments"]) == 1
    assert result["bearish_rebuttal_arguments"][0]["phase"] == "rebuttal_v1"
    assert result["bearish_rebuttal_arguments"][0]["role"] == "bearish"
    assert result["debate_round"] == 2
    assert result["current_phase"] == "P3_bearish_rebuttal"


@pytest.mark.asyncio
async def test_node_bear_final():
    """P3 步5: 空头最终陈述 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["selected_symbols"] = ["RB"]
    state["bearish_arguments"] = [
        {"round": 2, "role": "bearish", "phase": "v1", "symbols": {"RB": {"arguments": ["做空论据1"], "confidence": 0.6}}}
    ]
    state["bearish_rebuttal_arguments"] = [
        {"round": 3, "role": "bearish", "phase": "rebuttal", "symbols": {"RB": {"arguments": ["反驳看多"], "confidence": 0.65}}}
    ]
    state["debate_round"] = 3
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1", "P3_bearish_rebuttal", "P3_bullish_rebuttal"]
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["空头最终论据"], "confidence": 0.7, "risk_note": "做空风险"}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bear_final(state)
    assert result["bear_final_arguments"] is not None
    assert len(result["bear_final_arguments"]) == 1
    assert result["bear_final_arguments"][0]["phase"] == "final"
    assert result["bear_final_arguments"][0]["role"] == "bearish"
    assert result["current_phase"] == "P3_bear_final"


@pytest.mark.asyncio
async def test_node_bull_final():
    """P3 步6: 多头最终陈述 (v9.0.0)"""
    state = create_test_state()
    state["research_data"] = {"sources": ["chain", "technical"]}
    state["selected_symbols"] = ["RB"]
    state["bullish_arguments"] = [
        {"round": 1, "role": "bullish", "phase": "v1", "symbols": {"RB": {"arguments": ["看多论据1"], "confidence": 0.7}}}
    ]
    state["bullish_rebuttal_arguments"] = [
        {"round": 4, "role": "bullish", "phase": "rebuttal", "symbols": {"RB": {"arguments": ["反驳做空"], "confidence": 0.75}}}
    ]
    state["debate_round"] = 5
    state["completed_phases"] = ["P1", "P2", "P2", "P3_bullish_v1", "P3_bearish_v1", "P3_bearish_rebuttal", "P3_bullish_rebuttal", "P3_bear_final"]
    with patch("fdt_langgraph.nodes.FdtAgentExecutor") as MockExecutor:
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_output = '{"per_symbol": {"RB": {"arguments": ["多头最终论据"], "confidence": 0.8, "risk_note": "做多风险"}}}'
        mock_instance.run = AsyncMock(return_value={"output": mock_output})
        MockExecutor.return_value = mock_instance
        result = await node_bull_final(state)
    assert result["bull_final_arguments"] is not None
    assert len(result["bull_final_arguments"]) == 1
    assert result["bull_final_arguments"][0]["phase"] == "final"
    assert result["bull_final_arguments"][0]["role"] == "bullish"
    assert result["current_phase"] == "P3_bull_final"



def test_route_after_merge_research_fast():
    """fast 模式跳过辩论"""
    state = create_test_state(mode="fast")
    assert route_after_merge_research(state) == "verdict"


def test_route_after_merge_research_default():
    """default 模式进入辩论"""
    state = create_test_state(mode="default")
    assert route_after_merge_research(state) == "bullish_v1"


@pytest.mark.asyncio
async def test_node_verdict():
    state = create_test_state()
    state["bullish_arguments"] = [{"confidence": 0.8}]
    state["bearish_arguments"] = [{"confidence": 0.3}]
    state["judge_direction"] = {"direction": "bullish"}
    state["selected_symbols"] = ["RB"]
    state["completed_phases"] = ["P1", "P2", "P2", "P3"]
    result = await node_verdict(state)
    assert result["verdict"] is not None
    assert result["current_phase"] == "P4_verdict"


@pytest.mark.asyncio
async def test_node_signal_output():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    # node_signal_output 从 state["signal_output"] 读取（由 node_risk_check 预置）
    state["signal_output"] = {
        "status": "sent",
        "risk_color": "green",
        "risk_check": {"risk_color": "green", "approved": True},
        "signals": [
            {"symbol": "RB", "direction": "BUY", "entry_price": 3100, "score": 80},
        ],
        "signal": {
            "direction": "BUY",
            "symbol": "RB",
            "entry_price": 3100,
            "stop_loss_price": 3007,
            "target_price": 3255,
            "position_pct": 3,
            "contract": "",
            "risk_reward_ratio": 2.0,
            "confidence": 0.8,
        },
    }
    state["scan_results"] = {
        "all_ranked": [
            {"pid": "RB", "symbol": "RB", "direction": "bull", "total": 80, "price": 3100},
        ]
    }
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_risk"]
    result = await node_signal_output(state)
    assert result["signal_output"] is not None
    assert result["signal_output"]["status"] == "sent"
    assert "signal" in result["signal_output"]
    # v9.0 信号方向使用 "BUY"/"SELL"（大写）
    assert result["signal_output"]["signal"]["direction"] == "BUY"


@pytest.mark.asyncio
async def test_node_risk_check():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict"]
    result = await node_risk_check(state)
    assert result.get("signal_output") is not None
    assert result["signal_output"].get("risk_check") is not None


@pytest.mark.asyncio
async def test_node_report():
    state = create_test_state()
    state["verdict"] = {
        "direction": "bullish",
        "entry_price": 3100,
        "stop_loss_price": 3050,
        "target_price": 3250,
        "position_pct": 5,
        "contract": "RB2410",
    }
    state["risk_check"] = {"risk_level": "low", "risk_color": "green"}
    state["completed_phases"] = ["P1", "P2", "P3", "P4", "P5_verdict", "P5_risk"]
    result = await node_report(state)
    assert result["report_path"] is not None
    assert result["current_phase"] == "P6"
    assert "P6" in result["completed_phases"]


# ═══════════════════════════════════════════════════════════════
#  _build_fdc_technical_context — 观澜 context 注入单元测试
# ═══════════════════════════════════════════════════════════════


def _make_fdc_data(symbol: str, **extras) -> dict:
    """构造最小 fdc_data 字典（含 20 根 K 线激活均线计算）。"""
    bars = []
    for i in range(20):
        base_close = 6000 + i * 5
        bars.append({
            "date": f"202607{i+5:02d}",
            "open": base_close - 10, "high": base_close + 50, "low": base_close - 50,
            "close": base_close, "volume": 10000 + i * 100, "amount": 6e7 + i * 1e6, "oi": 50000 + i * 100,
        })
    data = {
        symbol: {
            "kline": {"bars": bars},
            "indicators": {
                "available": ["RSI14", "ADX"],
                "values": {"RSI14": [45, 48, 52], "ADX": [20, 22, 25]},
            },
            "data_grades": {"kline": "PRIMARY", "indicators": "PRIMARY"},
            **extras,
        }
    }
    return data


class TestBuildFdcTechnicalContext:
    """_build_fdc_technical_context 各种输入场景测试。"""

    def test_empty_fdc_data(self):
        """无 FDC 数据时返回占位消息。"""
        result = _build_fdc_technical_context(["RB"], {})
        assert "FDC 数据暂不可用" in result

    def test_no_data_for_symbol(self):
        """品种在 fdc_data 中无数据。"""
        result = _build_fdc_technical_context(["RB"], {"CF": {}})
        assert "无 FDC 数据" in result

    def test_kline_only(self):
        """仅有 K 线数据和指标。"""
        result = _build_fdc_technical_context(["RB"], _make_fdc_data("RB"))
        assert "RB" in result
        assert "FDC 技术数据" in result
        assert "最新价" in result
        assert "MA5" in result
        assert "MA10" in result
        assert "MA20" in result
        assert "RSI14" in result
        assert "ADX" in result

    def test_no_kline_bars(self):
        """K线存在但无 bars。"""
        data = {"RB": {"kline": {}, "indicators": {}, "data_grades": {}}}
        result = _build_fdc_technical_context(["RB"], data)
        assert "K线数据" in result

    def test_no_indicators(self):
        """K线有数据但指标不可用。"""
        data = {"RB": {
            "kline": {"bars": [{"date": "20260724", "close": 6120, "volume": 10000}]},
            "indicators": {},
            "data_grades": {},
        }}
        result = _build_fdc_technical_context(["RB"], data)
        assert "技术指标" in result

    def test_position_ranking_injected(self):
        """持仓排名数据注入。"""
        data = _make_fdc_data("RB", position_ranking={
            "data": {"net_long": 5000, "top5_long": 30000, "top5_short": 25000},
            "summary": "RB 多头占优",
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "持仓排名" in result
        assert "净多:5000" in result
        assert "前5多:30000" in result
        assert "前5空:25000" in result

    def test_position_ranking_empty_data(self):
        """持仓排名 data 为空字典。"""
        data = _make_fdc_data("RB", position_ranking={"data": {}, "summary": ""})
        result = _build_fdc_technical_context(["RB"], data)
        assert "持仓排名" not in result

    def test_position_ranking_with_error(self):
        """持仓排名含 error。"""
        data = _make_fdc_data("RB", position_ranking={"data": {"error": "timeout"}})
        result = _build_fdc_technical_context(["RB"], data)
        assert "持仓排名" not in result

    def test_fund_flow_injected(self):
        """资金流向数据注入（含多空比）。"""
        data = _make_fdc_data("RB", fund_flow={
            "data": {"total_oi": 200000, "long_volume": 105000, "short_volume": 95000, "long_short_ratio": 1.1053},
            "summary": "RB 多头 105000 / 空头 95000，比 1.1053",
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "资金流向" in result
        assert "总持仓:200000" in result
        assert "多头:105000" in result
        assert "空头:95000" in result
        assert "多空比:1.1053" in result

    def test_fund_flow_no_ratio(self):
        """资金流向无多空比。"""
        data = _make_fdc_data("RB", fund_flow={
            "data": {"total_oi": 200000, "long_volume": 105000, "short_volume": 95000, "long_short_ratio": None},
            "summary": "RB 多头 105000 / 空头 95000",
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "资金流向" in result
        assert "总持仓:200000" in result
        assert "多空比" not in result

    def test_fund_flow_all_none(self):
        """资金流向全部字段为 None。"""
        data = _make_fdc_data("RB", fund_flow={
            "data": {"total_oi": None, "long_volume": None, "short_volume": None, "long_short_ratio": None},
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "资金流向" not in result

    def test_fund_flow_with_error(self):
        """资金流向含 error。"""
        data = _make_fdc_data("RB", fund_flow={"data": {"error": "timeout"}})
        result = _build_fdc_technical_context(["RB"], data)
        assert "资金流向" not in result

    def test_foreign_injected(self):
        """外盘数据注入。"""
        data = _make_fdc_data("RB", foreign={
            "data": {"foreign_symbol": "LME.CU", "close": 9850.0, "change_pct": 1.25},
            "summary": "RB(LME.CU) 9850.0 (+1.25%)",
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "外盘" in result
        assert "LME.CU" in result
        assert "9850.0" in result
        assert "+1.25%" in result

    def test_foreign_no_change_pct(self):
        """外盘无涨跌幅。"""
        data = _make_fdc_data("RB", foreign={
            "data": {"foreign_symbol": "LME.CU", "close": 9850.0, "change_pct": None},
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "外盘" in result
        assert "LME.CU" in result
        assert "+" not in result.split("外盘")[-1]

    def test_foreign_empty_symbol(self):
        """外盘无品种代码。"""
        data = _make_fdc_data("RB", foreign={
            "data": {"foreign_symbol": "", "close": None, "change_pct": None},
        })
        result = _build_fdc_technical_context(["RB"], data)
        assert "外盘" not in result

    def test_foreign_with_error(self):
        """外盘含 error。"""
        data = _make_fdc_data("RB", foreign={"data": {"error": "timeout"}})
        result = _build_fdc_technical_context(["RB"], data)
        assert "外盘" not in result

    def test_all_three_injected(self):
        """持仓排名+资金流向+外盘同时注入。"""
        data = _make_fdc_data("RB",
            position_ranking={"data": {"net_long": 5000, "top5_long": 30000, "top5_short": 25000}},
            fund_flow={"data": {"total_oi": 200000, "long_volume": 105000, "short_volume": 95000, "long_short_ratio": 1.1}},
            foreign={"data": {"foreign_symbol": "LME.CU", "close": 9850.0, "change_pct": 1.25}},
        )
        result = _build_fdc_technical_context(["RB"], data)
        assert "持仓排名" in result
        assert "资金流向" in result
        assert "外盘" in result
        assert "净多:5000" in result
        assert "多空比:1.1" in result
        assert "LME.CU" in result

    def test_scan_stats_injected(self):
        """数技源 stats 数据注入。"""
        data = _make_fdc_data("RB")
        scan_results = {
            "all_ranked": [
                {"symbol": "RB", "stats": {
                    "latest_close": 6120, "change_pct": 0.99, "ma_20": 6050, "ma_60": 6000,
                    "ma_align": "多头排列", "atr_14": 50, "rsi_14": 52.5, "adx_14": 25.3,
                    "di_plus": 22.0, "di_minus": 18.0, "volume_ma20_ratio": 1.1, "oi_change": 2000,
                    "price_position_pct": 65.0,
                }},
            ]
        }
        result = _build_fdc_technical_context(["RB"], data, scan_results)
        assert "数技源统计特征" in result
        assert "6120" in result
        assert "RSI" in result
        assert "ADX" in result

    def test_scan_stats_no_symbol_match(self):
        """数技源 stats 中无匹配品种。"""
        data = _make_fdc_data("RB")
        scan_results = {
            "all_ranked": [
                {"symbol": "CF", "stats": {"latest_close": 15000}},
            ]
        }
        result = _build_fdc_technical_context(["RB"], data, scan_results)
        assert "数技源统计特征" not in result

    def test_multiple_symbols(self):
        """多品种同时注入。"""
        data = _make_fdc_data("RB")
        data["CF"] = {
            "kline": {"bars": [
                {"date": "20260724", "close": 15000, "volume": 5000, "high": 15100, "low": 14900},
            ]},
            "indicators": {"available": [], "values": {}},
            "data_grades": {"kline": "PRIMARY", "indicators": "UNAVAILABLE"},
            "fund_flow": {"data": {"total_oi": 100000, "long_short_ratio": 0.95}},
            "foreign": {"data": {"foreign_symbol": "ICE.CF", "close": 82.5, "change_pct": -0.5}},
        }
        result = _build_fdc_technical_context(["RB", "CF"], data)
        assert "RB" in result
        assert "CF" in result
        assert "ICE.CF" in result
        assert "资金流向" in result
        assert result.index("CF") > result.index("RB")

    def test_data_grades_displayed(self):
        """数据质量等级显示。"""
        data = _make_fdc_data("RB")
        result = _build_fdc_technical_context(["RB"], data)
        assert "数据质量" in result
        assert "PRIMARY" in result

    def test_no_data_grades(self):
        """无数据质量等级。"""
        data = {"RB": {"kline": {"bars": []}, "indicators": {}, "data_grades": {}}}
        result = _build_fdc_technical_context(["RB"], data)
        assert "数据质量" not in result
