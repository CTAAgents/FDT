"""持仓排名直连路径单测（桩 transport，不真发网络请求）。

运行:
    cd <FDT_ROOT> && python -m pytest futures_data_core/f10/test_position.py -v
"""

import asyncio
import json
import io
from unittest.mock import patch

from futures_data_core.f10 import exchange_scraper as esc
from futures_data_core.f10 import position


# ══════════════════════════════════════════════════════════════════════════
# 公用：创建 DCE/CZCE 风格的 mock xlsx
# ══════════════════════════════════════════════════════════════════════════

def _make_xlsx(sheet_rows: list[list]) -> bytes:
    """用 openpyxl 在内存中生成 xlsx 字节。"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in sheet_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════════════
# SHFE JSON 解析
# ══════════════════════════════════════════════════════════════════════════

SHFE_JSON = json.dumps({"o_cursor": [
    # SHFE 品种合计行（RANK=-1, INSTRUMENTID="rball"），应被过滤
    {"RANK": -1, "INSTRUMENTID": "rball", "PRODUCTNAME": "螺纹钢",
     "PARTICIPANTABBR1": "期货公司会员/境外特殊经纪参与者", "CJ1": 2890000, "CJ1_CHG": 0,
     "PARTICIPANTABBR2": "期货公司会员/境外特殊经纪参与者", "CJ2": 2890000, "CJ2_CHG": 0,
     "PARTICIPANTABBR3": "期货公司会员/境外特殊经纪参与者", "CJ3": 2890000, "CJ3_CHG": 0},
    {"RANK": 1, "INSTRUMENTID": "rb2410", "PRODUCTNAME": "螺纹钢",
     "PARTICIPANTABBR1": "永安期货", "CJ1": 2000, "CJ1_CHG": 100,
     "PARTICIPANTABBR2": "永安期货", "CJ2": 1500, "CJ2_CHG": 50,
     "PARTICIPANTABBR3": "中信期货", "CJ3": 1200, "CJ3_CHG": 30},
    {"RANK": 2, "INSTRUMENTID": "rb2410", "PRODUCTNAME": "螺纹钢",
     "PARTICIPANTABBR1": "中信期货", "CJ1": 1800, "CJ1_CHG": 80,
     "PARTICIPANTABBR2": "中信期货", "CJ2": 1300, "CJ2_CHG": 40,
     "PARTICIPANTABBR3": "国泰期货", "CJ3": 1100, "CJ3_CHG": 20},
]})


def test_parse_shfe_rank():
    r = esc.parse_position_rank(SHFE_JSON, "json", "SHFE", "rb")
    assert r["contract"] == "rb2410"
    assert len(r["long"]) == 2 and len(r["short"]) == 2
    assert r["long"][0]["member"] == "永安期货" and r["long"][0]["lots"] == 1500
    assert r["short"][0]["member"] == "中信期货" and r["short"][0]["lots"] == 1200
    assert r["net_position"] == (1500 + 1300) - (1200 + 1100)


def test_parse_shfe_filters_by_variety():
    mixed = json.dumps({"o_cursor": [
        {"RANK": 1, "INSTRUMENTID": "rb2410", "PARTICIPANTABBR2": "A", "CJ2": 100,
         "PARTICIPANTABBR3": "B", "CJ3": 90},
        {"RANK": 1, "INSTRUMENTID": "cu2408", "PARTICIPANTABBR2": "X", "CJ2": 999,
         "PARTICIPANTABBR3": "Y", "CJ3": 888},
    ]})
    r = esc.parse_position_rank(mixed, "json", "SHFE", "rb")
    assert r["contract"] == "rb2410"
    assert len(r["long"]) == 1 and r["long"][0]["member"] == "A"


# ══════════════════════════════════════════════════════════════════════════
# CFFEX CSV 解析
# ══════════════════════════════════════════════════════════════════════════

def test_parse_cffex_rank():
    raw_csv = ("交易日,合约,排名,成交量排名,,,持买单量排名,,,持卖单量排名,,\n"
               ",,,会员简称,成交量,比上一交易日增减,会员简称,持买单量,比上一交易日增减,会员简称,持卖单量,比上一交易日增减\n"
               "20260713,IF2408,1,中信期货,1000,10,中信期货,800,5,中信期货,700,3\n"
               "20260713,IF2408,2,国泰期货,900,8,国泰期货,750,4,国泰期货,650,2\n")
    # 模拟 GBK 字节输入
    r = esc.parse_position_rank(raw_csv.encode("gbk"), "csv", "CFFEX", "IF")
    assert r["contract"] == "IF2408"
    assert r["long"][0]["lots"] == 800 and r["short"][0]["lots"] == 700
    assert r["net_position"] == (800 + 750) - (700 + 650)


# ══════════════════════════════════════════════════════════════════════════
# CZCE xlsx 解析
# ══════════════════════════════════════════════════════════════════════════

CZCE_XLSX = _make_xlsx([
    # block: TA (PTA)
    ["品种：PTA     日期：2026-", None, None, None, None, None, None, None, None, None],
    ["名次", "会员简称", "交易量（手）", "增减量", "会员简称", "持买仓量", "增减量",
     "会员简称", "持卖仓量", "增减量"],
    ["1", "永安期货", "2,000", "100", "永安期货", "1,500", "50", "中信期货", "1,200", "30"],
    ["2", "中信期货", "1,800", "80", "中信期货", "1,300", "40", "国泰期货", "1,100", "20"],
    ["合计", None, None, None, None, None, None, None, None, None],
])


def test_parse_czce_rank():
    r = esc.parse_position_rank(CZCE_XLSX, "xlsx", "CZCE", "TA")
    assert r["contract"] is not None and "TA" in r["contract"].upper()
    assert len(r["long"]) == 2
    assert r["long"][0]["member"] == "永安期货" and r["long"][0]["lots"] == 1500
    assert r["short"][0]["member"] == "中信期货" and r["short"][0]["lots"] == 1200
    assert r["net_position"] == (1500 + 1300) - (1200 + 1100)


# ══════════════════════════════════════════════════════════════════════════
# DCE xlsx 解析（单合约数据块）
# ══════════════════════════════════════════════════════════════════════════

DCE_XLSX = _make_xlsx([
    ["名次", "会员简称", "成交量", "增减", "会员简称.1", "持买单量", "增减.1",
     "会员简称.2", "持卖单量", "增减.2"],
    ["1", "永安期货", "2000", "100", "永安期货", "1500", "50", "中信期货", "1200", "30"],
    ["2", "中信期货", "1800", "80", "中信期货", "1300", "40", "国泰期货", "1100", "20"],
])


def test_parse_dce_rank():
    r = esc.parse_position_rank(DCE_XLSX, "txt", "DCE", "M")
    assert len(r["long"]) == 2
    assert r["long"][0]["member"] == "永安期货" and r["long"][0]["lots"] == 1500
    assert r["short"][1]["member"] == "国泰期货" and r["short"][1]["lots"] == 1100
    assert r["net_position"] == (1500 + 1300) - (1200 + 1100)


# ══════════════════════════════════════════════════════════════════════════
# GFEX JSON 解析（单合约 3 页合并后）
# ══════════════════════════════════════════════════════════════════════════

GFEX_JSON = json.dumps({"data": [
    {"rank": 1, "abbr": "中信期货", "long_open_interest": 1500, "short_open_interest": 1200},
    {"rank": 2, "abbr": "永安期货", "long_open_interest": 1300, "short_open_interest": 1100},
]})


def test_parse_gfex_rank():
    r = esc.parse_position_rank(GFEX_JSON, "json", "GFEX", "SI")
    assert len(r["long"]) == 2
    assert r["long"][0]["member"] == "中信期货" and r["long"][0]["lots"] == 1500
    assert r["short"][0]["member"] == "中信期货" and r["short"][0]["lots"] == 1200
    assert r["net_position"] == (1500 + 1300) - (1200 + 1100)


# ══════════════════════════════════════════════════════════════════════════
# 直连主路径（SHFE, transport 桩）
# ══════════════════════════════════════════════════════════════════════════

def test_direct_path_shfe():
    with patch.object(position, "get_symbol", return_value={"exchange": "SHFE"}):
        payload = asyncio.run(
            position.get_position_ranking("rb", transport=lambda u: SHFE_JSON)
        )
    d = payload.data
    assert d["exchange"] == "SHFE"
    assert d["long_volume"] == 2800
    assert d["short_volume"] == 2300
    assert d["net_long"] == 500
    assert d["top5_long"] == 2800
    assert d["top5_short"] == 2300
    assert d["data_source"] == "SHFE官网直连"


# ══════════════════════════════════════════════════════════════════════════
# 不可用路径（无退路 fallback → UNAVAILABLE）
# ══════════════════════════════════════════════════════════════════════════

def test_unavailable_when_no_exchange():
    with patch.object(position, "get_symbol", return_value={"exchange": None}):
        payload = asyncio.run(
            position.get_position_ranking("unknown")
        )
    assert payload.meta["data_grade"] == "UNAVAILABLE"


def test_unavailable_when_fetch_fails():
    def _boom(url):
        raise RuntimeError("network down")
    with patch.object(position, "get_symbol", return_value={"exchange": "SHFE"}):
        payload = asyncio.run(
            position.get_position_ranking("rb", transport=_boom)
        )
    assert payload.meta["data_grade"] == "UNAVAILABLE"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
