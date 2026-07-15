"""宏观数据（利率 / 制造业PMI）[INDEPENDENT]。

数据来源（免费公开，零鉴权，httpx 直连）：
  - PMI ：东方财富数据中心 ``RPT_ECONOMY_PMI``（制造业 PMI，月度）
  - 利率：东方财富 ``RPTA_WEB_RATE``（LPR 1Y/5Y，月度，作为融资利率代理）

端点经 WebSearch 核实（2026-07-15，参考 akshare/qstock 公开实现），
使用东方财富公开 Web token，无需鉴权。沙箱 Python 网络受限时返回
UNAVAILABLE → 上层因子惰性 0（不造假信号）。

本地状态持久化（临时目录 ``fdt_macro_state.json``）：记录上次抓取的水平值，
用于计算**环比动量**（``pmi_mom`` / ``rate_mom``），使利率/景气度因子即便
无长历史也能产出有意义的动量信号。源不可用时因子保持惰性 0。

实现采用**可注入 transport** 设计（同 warrant/basis），缺省走 httpx 直连。
A2A 输出：``type=fdc.macro``。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES


# ── 配置（部署环境如需换源，仅改此处常量即可，无需动架构） ──
_MACRO_STATE_FILE = os.path.join(tempfile.gettempdir(), "fdt_macro_state.json")

_EMACRO_PMI_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EMACRO_RATE_URL = "https://datacenter.eastmoney.com/api/data/get"
_EMACRO_RATE_TOKEN = "894050c76af8597a853f5b408b759f5d"  # 东方财富公开 Web token
_EMACRO_RATE_VAR = "WPuRCBoA"  # LPR 接口 JSONP 包裹变量名


def _pmi_params() -> dict:
    return {
        "reportName": "RPT_ECONOMY_PMI",
        "columns": "REPORT_DATE,TIME,MAKE_INDEX,MAKE_SAME,NMAKE_INDEX,NMAKE_SAME",
        "pageSize": "2000",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
        "p": "1",
        "pageNo": "1",
        "pageNum": "1",
    }


def _rate_params() -> dict:
    return {
        "type": "RPTA_WEB_RATE",
        "sty": "ALL",
        "token": _EMACRO_RATE_TOKEN,
        "p": "1",
        "ps": "2000",
        "st": "TRADE_DATE",
        "sr": "-1",
        "var": _EMACRO_RATE_VAR,
        "rt": "52826782",
    }


# ── 本地状态（环比动量计算） ──
def _load_state() -> dict:
    try:
        if os.path.exists(_MACRO_STATE_FILE):
            with open(_MACRO_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        with open(_MACRO_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None:
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


# ── 可注入 transport（缺省 httpx） ──
async def _httpx_get(url: str, params: dict) -> tuple[int, str]:
    """真实 httpx 抓取（抽离为模块级函数，便于测试桩替换）。"""
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        return resp.status_code, resp.text


def _parse_jsonp(text: str) -> Optional[dict]:
    """解析东方财富 LPR 接口的 JSONP 包裹（``var WPuRCBoA={...};``）。

    非 JSONP 文本或非 JSON 时返回 ``None``。
    """
    t = text.strip()
    if t.startswith("var "):
        eq = t.find("=")
        if eq != -1:
            body = t[eq + 1:]
            if body.endswith(";"):
                body = body[:-1]
            try:
                return json.loads(body)
            except Exception:
                return None
    try:
        return json.loads(t)
    except Exception:
        return None


# ── 公共 API ──
async def get_macro_pmi(*, transport=None) -> A2APayload:
    """获取制造业 PMI 最新值（含环比动量）。无 LLM 依赖。

    Args:
        transport: 可注入 ``(url, params) -> (status, body)`` 抓取器；
            缺省走东方财富宏观数据中心 httpx 直连。``body`` 可为 dict（已解析）
            或 str（原始响应，自动 JSON/JSONP 解析）。

    Returns:
        :class:`A2APayload`，``data`` 含 ``pmi`` / ``pmi_date`` / ``pmi_mom`` /
        ``source``；获取失败返回 UNAVAILABLE 信封（``pmi=None``）。
    """
    try:
        fetch = transport or _httpx_get
        raw = await fetch(_EMACRO_PMI_URL, _pmi_params())
        if hasattr(raw, "__await__"):
            raw = await raw
        status, body = raw
        if status != 200 or not body:
            return _unavailable("pmi", "HTTP 获取失败")
        data = body if isinstance(body, dict) else _parse_jsonp(body)
        rows = (data or {}).get("result", {}).get("data") if isinstance(data, dict) else None
        if not rows:
            return _unavailable("pmi", "PMI 数据解析为空")
        latest = rows[0]  # 已按 REPORT_DATE 降序
        pmi = _safe_float(latest.get("MAKE_INDEX"))
        date = str(latest.get("REPORT_DATE", ""))
        if pmi is None:
            return _unavailable("pmi", "PMI 值缺失")
        # 环比动量（相对上次抓取）
        state = _load_state()
        prev = state.get("pmi")
        pmi_mom = round(pmi - prev, 2) if prev is not None else None
        state["pmi"] = pmi
        state["pmi_date"] = date
        _save_state(state)
        payload = A2APayload(
            type=DATA_TYPES["MACRO"],
            runtime_mode="independent",
            data={"pmi": pmi, "pmi_date": date, "pmi_mom": pmi_mom, "source": "eastmoney"},
        )
        payload.set_grade("DAILY")
        payload.summary = (
            f"制造业PMI {pmi}（{date}）"
            + (f"，环比 {pmi_mom:+.2f}" if pmi_mom is not None else "")
        )
        return payload
    except Exception as e:
        return _unavailable("pmi", str(e)[:80])


async def get_macro_rate(*, transport=None) -> A2APayload:
    """获取 LPR 1Y（作为融资利率代理，含环比动量）。无 LLM 依赖。

    利率上行 → 融资收紧（偏空）；下行 → 宽松（偏多）。LPR 为官方贷款市场报价
    利率，月度更新，是商品融资成本的直接代理。

    Args:
        transport: 同 :func:`get_macro_pmi`。

    Returns:
        :class:`A2APayload`，``data`` 含 ``rate``（LPR1Y %）/ ``rate_date`` /
        ``rate_mom``（百分点）/ ``source``；失败返回 UNAVAILABLE 信封。
    """
    try:
        fetch = transport or _httpx_get
        raw = await fetch(_EMACRO_RATE_URL, _rate_params())
        if hasattr(raw, "__await__"):
            raw = await raw
        status, body = raw
        if status != 200 or not body:
            return _unavailable("rate", "HTTP 获取失败")
        data = body if isinstance(body, dict) else _parse_jsonp(body)
        rows = (data or {}).get("result", {}).get("data") if isinstance(data, dict) else None
        if not rows:
            return _unavailable("rate", "LPR 数据解析为空")
        latest = rows[0]  # 按 TRADE_DATE 降序
        rate = _safe_float(latest.get("LPR1Y"))
        date = str(latest.get("TRADE_DATE", ""))
        if rate is None:
            return _unavailable("rate", "LPR1Y 值缺失")
        # 环比动量（相对上次抓取，单位：百分点）
        state = _load_state()
        prev = state.get("rate")
        rate_mom = round(rate - prev, 4) if prev is not None else None
        state["rate"] = rate
        state["rate_date"] = date
        _save_state(state)
        payload = A2APayload(
            type=DATA_TYPES["MACRO"],
            runtime_mode="independent",
            data={"rate": rate, "rate_date": date, "rate_mom": rate_mom, "source": "eastmoney"},
        )
        payload.set_grade("DAILY")
        payload.summary = (
            f"LPR1Y {rate}%（{date}）"
            + (f"，环比 {rate_mom:+.2f}pp" if rate_mom is not None else "")
        )
        return payload
    except Exception as e:
        return _unavailable("rate", str(e)[:80])


def _unavailable(kind: str, reason: str) -> A2APayload:
    payload = A2APayload(
        type=DATA_TYPES["MACRO"],
        runtime_mode="independent",
        data={"pmi": None, "rate": None, kind: None},
    )
    payload.set_grade("UNAVAILABLE")
    payload.add_warning(reason)
    return payload
