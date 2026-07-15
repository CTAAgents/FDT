"""宏观连接器（f10/macro.py）测试 — G29。

覆盖：
  - get_macro_pmi：解析 MAKE_INDEX + 环比动量（本地状态）
  - get_macro_rate：解析 LPR1Y（含 JSONP 包裹 var WPuRCBoA=） + 动量
  - 失败/空数据 → UNAVAILABLE 信封（因子惰性0，不造假）
  - 可注入 transport（不触网，沙箱安全）
"""
import asyncio
import json

import pytest

from futures_data_core.f10 import macro


def _transport(payload: dict):
    """构造可注入 transport：返回 (200, payload)。"""
    async def _t(url, params):
        return 200, payload
    return _t


def _transport_text(text: str):
    async def _t(url, params):
        return 200, text
    return _t


def _transport_fail(status: int = 500):
    async def _t(url, params):
        return status, ""
    return _t


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """隔离本地动量状态文件，避免跨测试污染。"""
    state_file = tmp_path / "macro_state.json"
    monkeypatch.setattr(macro, "_MACRO_STATE_FILE", str(state_file))
    return state_file


class TestMacroPmi:
    def test_parse_latest(self, clean_state):
        payload = {
            "result": {
                "data": [
                    {"REPORT_DATE": "2026-05-31", "MAKE_INDEX": 50.5, "MAKE_SAME": "1.0%"},
                    {"REPORT_DATE": "2026-04-30", "MAKE_INDEX": 49.8, "MAKE_SAME": "0.5%"},
                ]
            }
        }
        p = asyncio.run(macro.get_macro_pmi(transport=_transport(payload)))
        assert p.meta["data_grade"] == "DAILY"
        assert p.data["pmi"] == 50.5
        assert p.data["pmi_date"] == "2026-05-31"
        # 首次抓取无前值 → 动量 None
        assert p.data["pmi_mom"] is None

    def test_momentum_across_calls(self, clean_state):
        p1 = asyncio.run(macro.get_macro_pmi(transport=_transport({
            "result": {"data": [{"REPORT_DATE": "2026-04-30", "MAKE_INDEX": 49.8}]}
        })))
        assert p1.data["pmi_mom"] is None
        # 第二次抓取 PMI 上升 0.7 → 动量 +0.7
        p2 = asyncio.run(macro.get_macro_pmi(transport=_transport({
            "result": {"data": [{"REPORT_DATE": "2026-05-31", "MAKE_INDEX": 50.5}]}
        })))
        assert p2.data["pmi_mom"] == pytest.approx(0.7)

    def test_state_persisted(self, clean_state):
        asyncio.run(macro.get_macro_pmi(transport=_transport({
            "result": {"data": [{"REPORT_DATE": "2026-05-31", "MAKE_INDEX": 50.5}]}
        })))
        saved = json.loads(clean_state.read_text(encoding="utf-8"))
        assert saved["pmi"] == 50.5

    def test_empty_data_unavailable(self, clean_state):
        p = asyncio.run(macro.get_macro_pmi(transport=_transport({"result": {"data": []}})))
        assert p.meta["data_grade"] == "UNAVAILABLE"
        assert p.data["pmi"] is None

    def test_http_fail_unavailable(self, clean_state):
        p = asyncio.run(macro.get_macro_pmi(transport=_transport_fail(500)))
        assert p.meta["data_grade"] == "UNAVAILABLE"


class TestMacroRate:
    def test_parse_jsonp(self, clean_state):
        """LPR 接口返回 JSONP 包裹 var WPuRCBoA={...};"""
        text = (
            'var WPuRCBoA={"result":{"data":['
            '{"TRADE_DATE":"2026-05-20","LPR1Y":3.0,"LPR5Y":3.5,"RATE_1":3.0}'
            ']}};'
        )
        p = asyncio.run(macro.get_macro_rate(transport=_transport_text(text)))
        assert p.meta["data_grade"] == "DAILY"
        assert p.data["rate"] == 3.0
        assert p.data["rate_date"] == "2026-05-20"
        assert p.data["rate_mom"] is None

    def test_momentum_negative_when_rate_cut(self, clean_state):
        asyncio.run(macro.get_macro_rate(transport=_transport_text(
            'var WPuRCBoA={"result":{"data":[{"TRADE_DATE":"2026-04-20","LPR1Y":3.45}]}};'
        )))
        p2 = asyncio.run(macro.get_macro_rate(transport=_transport_text(
            'var WPuRCBoA={"result":{"data":[{"TRADE_DATE":"2026-05-20","LPR1Y":3.0}]}};'
        )))
        # 利率下调 0.45pp → 动量 -0.45
        assert p2.data["rate_mom"] == pytest.approx(-0.45)

    def test_empty_data_unavailable(self, clean_state):
        p = asyncio.run(macro.get_macro_rate(transport=_transport({"result": {"data": []}})))
        assert p.meta["data_grade"] == "UNAVAILABLE"

    def test_missing_lpr1y_unavailable(self, clean_state):
        text = 'var WPuRCBoA={"result":{"data":[{"TRADE_DATE":"2026-05-20","LPR5Y":3.5}]}};'
        p = asyncio.run(macro.get_macro_rate(transport=_transport_text(text)))
        assert p.meta["data_grade"] == "UNAVAILABLE"
