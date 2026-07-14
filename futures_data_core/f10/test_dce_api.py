"""DCE 官方 API 适配器单测（httpx MockTransport 桩，不真发网络）。

运行:
    cd <FDT_ROOT> && python -m pytest futures_data_core/f10/test_dce_api.py -v
"""

import asyncio
import os

import httpx
import pytest

from futures_data_core.f10 import dce_api


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """每个用例前清空进程内 token 缓存，保证登录桩必被触发。"""
    dce_api._TOKEN_CACHE["token"] = None
    dce_api._TOKEN_CACHE["expires_at"] = 0.0
    yield


@pytest.fixture
def dce_creds():
    """注入桩凭证（MockTransport 不校验真实值，仅用于通过 env 检查与构造 Header）。"""
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("DCE_API_KEY", "TEST_KEY")
        mp.setenv("DCE_API_SECRET", "TEST_SECRET")
        yield


# ── 桩响应 ──────────────────────────────────────────────────────────────────

def _login_resp():
    return httpx.Response(200, json={
        "success": True, "code": 200, "msg": "安全Token签发成功",
        "requestId": "x", "data": {"tokenType": "Bearer", "token": "FAKE.JWT.TOKEN"},
    })


def _contract_resp():
    return httpx.Response(200, json={
        "success": True, "code": 200, "msg": "操作成功", "requestId": "x",
        "data": [
            {"contractId": "m2608", "variety": "豆粕", "varietyOrder": "m"},
            {"contractId": "m2609", "variety": "豆粕", "varietyOrder": "m"},
        ],
    })


def _member_resp():
    return httpx.Response(200, json={
        "success": True, "code": 200, "msg": "操作成功", "requestId": "x",
        "data": {
            "contractId": "期货公司会员",
            "buyFutureList": [
                {"rank": "1", "buyAbbr": "招商期货（代客）", "todayBuyQty": 35713, "buySub": 100},
                {"rank": "2", "buyAbbr": "国泰君安（代客）", "todayBuyQty": 34581, "buySub": 50},
            ],
            "sellFutureList": [
                {"rank": "1", "sellAbbr": "招商期货（代客）", "todaySellQty": 34679, "sellSub": 20},
                {"rank": "2", "sellAbbr": "国泰君安（代客）", "todaySellQty": 31575, "sellSub": 10},
            ],
        },
    })


def _mock_handler(request):
    url = str(request.url)
    if "accessToken" in url:
        return _login_resp()
    if "contractInfo" in url:
        return _contract_resp()
    if "memberDealPosi" in url:
        return _member_resp()
    return httpx.Response(404)


def _transport():
    return httpx.MockTransport(_mock_handler)


# ── 单元：符号拆分 / 配置标志 ────────────────────────────────────────────────

def test_split_symbol():
    assert dce_api._split_symbol("m") == ("m", None)
    assert dce_api._split_symbol("M2609") == ("m", "m2609")
    assert dce_api._split_symbol("m2609") == ("m", "m2609")
    assert dce_api._split_symbol("rb") == ("rb", None)


def test_configured_flag():
    with pytest.MonkeyPatch().context() as mp:
        mp.delenv("DCE_API_KEY", raising=False)
        mp.delenv("DCE_API_SECRET", raising=False)
        assert dce_api.dce_api_configured() is False
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("DCE_API_KEY", "k")
        mp.setenv("DCE_API_SECRET", "s")
        assert dce_api.dce_api_configured() is True


# ── 集成：品种解析 + 合约直取 ────────────────────────────────────────────────

def test_fetch_via_variety_resolves_contract(dce_creds):
    async def _run():
        return await dce_api.fetch_dce_api_position_ranking("m", "20260714", transport=_transport())
    r = asyncio.run(_run())
    assert r["contract"] == "M2608"            # 经 contractInfo 解析到首合约
    assert len(r["long"]) == 2 and len(r["short"]) == 2
    assert r["long"][0]["member"] == "招商期货（代客）"
    assert r["long"][0]["lots"] == 35713
    assert r["long"][0]["rank"] == 1
    assert r["short"][0]["member"] == "招商期货（代客）"
    assert r["short"][0]["lots"] == 34679


def test_fetch_via_contract_skips_resolution(dce_creds):
    async def _run():
        return await dce_api.fetch_dce_api_position_ranking("m2609", "20260714", transport=_transport())
    r = asyncio.run(_run())
    assert r["contract"] == "M2609"
    assert r["long"][0]["lots"] == 35713


# ── 异常路径 ────────────────────────────────────────────────────────────────

def test_login_failure_raises(dce_creds):
    def _handler(request):
        if "accessToken" in str(request.url):
            return httpx.Response(200, json={"success": False, "code": 401,
                                             "msg": "无权限", "data": None})
        return httpx.Response(404)
    async def _run():
        return await dce_api.fetch_dce_api_position_ranking(
            "m2609", "20260714", transport=httpx.MockTransport(_handler))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(_run())
    assert "登录失败" in str(ei.value)


def test_member_failure_raises(dce_creds):
    def _handler(request):
        url = str(request.url)
        if "accessToken" in url:
            return _login_resp()
        if "memberDealPosi" in url:
            return httpx.Response(200, json={"success": False, "code": 500,
                                             "msg": "内部错误", "data": None})
        return httpx.Response(404)
    async def _run():
        return await dce_api.fetch_dce_api_position_ranking(
            "m2609", "20260714", transport=httpx.MockTransport(_handler))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(_run())
    assert "memberDealPosi 失败" in str(ei.value)


def test_missing_credentials_raises():
    with pytest.MonkeyPatch().context() as mp:
        mp.delenv("DCE_API_KEY", raising=False)
        mp.delenv("DCE_API_SECRET", raising=False)
        async def _run():
            return await dce_api.fetch_dce_api_position_ranking("m2609", "20260714", transport=_transport())
        with pytest.raises(RuntimeError) as ei:
            asyncio.run(_run())
        assert "未设置" in str(ei.value)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
