"""持仓排名数据 [INDEPENDENT]。

数据来源：各交易所官网直连（无 AKShare 依赖）。
  - SHFE: pm{date}.dat JSON GET
  - CFFEX: {VAR}_1.csv CSV GET
  - CZCE: FutureDataHolding.xlsx GET（openpyxl 解析）
  - DCE: 官方 API（dce_api.py，需 DCE_API_KEY/DCE_API_SECRET）优先；
         未配置凭证或 API 异常时回退 portal.dce.com.cn 网页抓取（POST 合约列表 → GET xlsx）
  - GFEX: POST 获取合约列表 → POST 逐合约 3 页合并

A2A 输出：``type=fdc.position_ranking``。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES, _default_meta
from futures_data_core.core import get_symbol
from futures_data_core.f10 import dce_api
from futures_data_core.f10.exchange_scraper import (
    fetch_exchange_page,
    get_position_rank_url,
    parse_position_rank,
    rank_fmt_of,
    rank_headers_of,
    today_yyyymmdd,
)


async def get_position_ranking(
    symbol: str,
    days: int = 30,
    trade_date: Optional[str] = None,
    *,
    transport=None,
) -> A2APayload:
    """获取单个品种的期货会员持仓排名。

    直连交易所官网（无 AKShare 依赖）。

    Args:
        symbol: 品种代码（如 'rb', 'CU', 'M', 'SI'）
        days: 保留参数（向下兼容，直连模式未使用）
        trade_date: 交易日 YYYYMMDD；缺省取最近交易日
        transport: 注入的抓取器（单步 GET 用，DCE/GFEX 多步取合约列表用 httpx）

    Returns:
        A2APayload，data 结构：
        {
            "symbol": "rb",
            "exchange": "SHFE",
            "contract": "rb2410",
            "total_oi": null,
            "long_volume": 123456,
            "short_volume": 123456,
            "net_long": 0,           # 前N会员净持仓
            "top5_long": 60000,
            "top5_short": 58000,
            "long": [{"rank":1,"member":"某期货","lots":20000}, ...],
            "short": [...],
            "trade_date": "20260714",
            "data_source": "SHFE官网直连",
        }
    """
    meta = _default_meta()
    trade_date = trade_date or today_yyyymmdd()
    sym_meta = get_symbol(symbol)
    exchange = (sym_meta or {}).get("exchange")
    meta["sources"] = []
    if not exchange:
        meta["warnings"].append(f"未知品种交易所: {symbol}")
        return _unavailable(symbol, meta)

    try:
        if exchange in ("SHFE", "CFFEX", "CZCE"):
            parsed = await _fetch_single_rank(exchange, symbol, trade_date, transport=transport)
        elif exchange == "DCE":
            # 官方 API 优先（需 DCE_API_KEY/DCE_API_SECRET）；失败或返回空时回退 portal 抓取。
            if dce_api.dce_api_configured():
                try:
                    parsed = await _fetch_dce_rank_api(symbol, trade_date)
                except Exception as e:
                    meta["warnings"].append(
                        f"DCE官方API异常转回portal抓取: {type(e).__name__}: {str(e)[:80]}"
                    )
                    parsed = {}
                # API 返回空（无数据）时也尝试 portal 兜底
                if not parsed:
                    try:
                        parsed = await _fetch_dce_rank(symbol, trade_date)
                    except Exception as e:
                        meta["warnings"].append(
                            f"DCE portal 抓取也失败: {type(e).__name__}: {str(e)[:80]}"
                        )
            else:
                parsed = await _fetch_dce_rank(symbol, trade_date)
        elif exchange == "GFEX":
            parsed = await _fetch_gfex_rank(symbol, trade_date)
        else:
            meta["warnings"].append(f"不支持的交易所: {exchange}")
            return _unavailable(symbol, meta)

        if parsed and (parsed.get("long") or parsed.get("short")):
            meta["data_grade"] = "DAILY"
            meta["data_grade_label"] = 2
            meta["sources"].append(f"{exchange}官网直连")
            return _build_payload(
                symbol, exchange, parsed, trade_date, meta,
                source=f"{exchange}官网直连",
            )
    except Exception as e:
        meta["warnings"].append(f"直连{exchange}失败: {type(e).__name__}: {str(e)[:80]}")

    return _unavailable(symbol, meta)


# ── 单步直连（SHFE/CFFEX/CZCE） ──────────────────────────────────────────────

async def _fetch_single_rank(
    exchange: str, symbol: str, trade_date: str, *, transport=None
) -> dict:
    """SHFE/CFFEX/CZCE 单步直连接口。"""
    url = get_position_rank_url(exchange, trade_date, symbol)
    fmt = rank_fmt_of(exchange)
    if not url or not fmt:
        return {}
    as_bytes = exchange in ("CZCE", "CFFEX")  # CFFEX=GBK, CZCE=xlsx
    text = await fetch_exchange_page(
        url, transport=transport,
        headers=rank_headers_of(exchange),
        as_bytes=as_bytes,
    )
    return parse_position_rank(text, fmt, exchange, symbol)


# ── DCE（POST 取合约列表 → 取首合约 xlsx） ────────────────────────────────────

async def _fetch_dce_rank(symbol: str, trade_date: str) -> dict:
    """大商所：POST 获取合约列表，取首个合约 xlsx。"""
    import httpx

    s = symbol.lower()
    y = int(trade_date[:4])
    m = int(trade_date[4:6]) - 1  # DCE month 0-based
    d = int(trade_date[6:])

    # Step 1: 获取合约列表
    contract_list_url = "http://portal.dce.com.cn/publicweb/quotesdata/memberDealPosiQuotes.html"
    payload = {
        "memberDealPosiQuotes.variety": s,
        "memberDealPosiQuotes.trade_type": "0",
        "year": str(y),
        "month": str(m),
        "day": str(d),
        "contract.contract_id": "all",
        "contract.variety_id": s,
        "contract": "",
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.post(contract_list_url, data=payload)
        resp.raise_for_status()
        html = resp.text

    # 从 onclick 提取合约号
    nums = re.findall(r"setContract_id\('(\d+)'\)", html)
    if not nums:
        return {}
    contracts = [s + num for num in nums]
    # 取首个合约
    contract_id = contracts[0]

    # Step 2: 取该合约 xlsx
    xlsx_url = (
        f"http://portal.dce.com.cn/publicweb/quotesdata/exportMemberDealPosiQuotesData.html"
        f"?memberDealPosiQuotes.variety={s}&memberDealPosiQuotes.trade_type=0"
        f"&contract.contract_id={contract_id}&contract.variety_id={s}"
        f"&year={y}&month={m}&day={d}&exportFlag=excel"
    )
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp2 = await client.get(xlsx_url)
        resp2.raise_for_status()
        raw = resp2.content

    parsed = parse_position_rank(raw, "txt", "DCE", symbol)
    if parsed and not parsed.get("contract") and contracts:
        parsed["contract"] = contract_id.upper()
    return parsed


# ── DCE 官方 API（需 DCE_API_KEY/DCE_API_SECRET） ───────────────────────────

async def _fetch_dce_rank_api(symbol: str, trade_date: str) -> dict:
    """大商所官方 API 路径（dce_api.py）。失败抛异常交由上层回退 portal。"""
    return await dce_api.fetch_dce_api_position_ranking(symbol, trade_date)


# ── GFEX（POST 取合约列表 → POST 逐合约 3 页合并） ──────────────────────────

async def _fetch_gfex_rank(symbol: str, trade_date: str) -> dict:
    """广期所：POST 获取合约列表，逐合约 POST 3 页(data_type=1/2/3)合并。"""
    import httpx

    s = symbol.lower()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # Step 1: 获取合约列表
    contract_list_url = (
        "http://www.gfex.com.cn/u/interfacesWebTiMemberDealPosiQuotes/loadListContract_id"
    )
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.post(
            contract_list_url,
            data={"variety": s, "trade_date": trade_date},
            headers=headers,
        )
        resp.raise_for_status()
        js = resp.json()
        raw_data = js.get("data") or []
        if raw_data and isinstance(raw_data[0], str):
            contracts = raw_data  # GFEX 返回字符串列表 ["si2609", ...]
        elif raw_data and isinstance(raw_data[0], (list, tuple)):
            contracts = [item[0] for item in raw_data if len(item) > 0]
        elif raw_data and isinstance(raw_data[0], dict):
            contracts = [list(item.values())[0] for item in raw_data]
        else:
            contracts = []
        if not contracts:
            return {}

    contract_id = contracts[0]

    # Step 2: POST 3 页合并
    data_url = "http://www.gfex.com.cn/u/interfacesWebTiMemberDealPosiQuotes/loadList"
    pages = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for data_type in range(1, 4):
            resp = await client.post(
                data_url,
                data={
                    "trade_date": trade_date,
                    "trade_type": "0",
                    "variety": s,
                    "contract_id": contract_id,
                    "data_type": str(data_type),
                },
                headers=headers,
            )
            resp.raise_for_status()
            pages.append(resp.text)

    # 合并 3 页：data_type=1(成交量), data_type=2(持买), data_type=3(持卖)
    merged = _merge_gfex_pages(pages)
    parsed = parse_position_rank(merged, "json", "GFEX", symbol)
    if parsed and not parsed.get("contract") and contracts:
        parsed["contract"] = contract_id.upper()
    return parsed


def _merge_gfex_pages(pages: list[str]) -> str:
    """合并 GFEX 3 页 JSON API 返回为单 JSON。

    Page 1 (data_type=1): 成交量, Page 2 (data_type=2): 持买单量, Page 3 (data_type=3): 持卖单量。
    各页会员顺序可能不同，按 memberId 合并。
    """
    merged: dict[str, dict] = {}
    labels = ["vol", "long", "short"]
    for page_idx, text in enumerate(pages):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            continue
        rows = (data or {}).get("data") or []
        for r in rows:
            mid = str(r.get("memberId", "") or "")
            if not mid:
                continue
            if mid not in merged:
                merged[mid] = {
                    "memberId": mid,
                    "abbr": str(r.get("abbr", "") or ""),
                    "vol": 0, "long": 0, "short": 0,
                }
            try:
                qty = int(float(r.get("todayQty", 0) or 0))
            except (ValueError, TypeError):
                qty = 0
            merged[mid][labels[page_idx]] = qty

    # 按 long 量排序
    sorted_members = sorted(merged.values(), key=lambda x: -x["long"])
    result = []
    for i, m in enumerate(sorted_members):
        result.append({
            "rank": i + 1,
            "abbr": m["abbr"],
            "long_open_interest": m["long"],
            "short_open_interest": m["short"],
        })
    return json.dumps({"data": result}, ensure_ascii=False)


# ── 构造 Payload ──────────────────────────────────────────────────────────────

def _build_payload(
    symbol: str,
    exchange: str,
    parsed: dict,
    trade_date: str,
    meta: dict,
    source: str,
) -> A2APayload:
    """由解析结果组装 A2APayload，修正 net_long 语义并补 top5。"""
    long_list = parsed.get("long", [])
    short_list = parsed.get("short", [])
    long_vol = sum(x["lots"] for x in long_list)
    short_vol = sum(x["lots"] for x in short_list)
    return A2APayload(
        type=DATA_TYPES.get("POSITION_RANKING", "fdc.position_ranking"),
        runtime_mode="independent",
        data={
            "symbol": symbol.lower(),
            "exchange": exchange,
            "contract": parsed.get("contract", ""),
            "total_oi": None,
            "long_volume": long_vol,
            "short_volume": short_vol,
            "net_long": parsed.get("net_position", long_vol - short_vol),
            "top5_long": sum(x["lots"] for x in long_list[:5]),
            "top5_short": sum(x["lots"] for x in short_list[:5]),
            "long": long_list,
            "short": short_list,
            "trade_date": trade_date,
            "data_source": source,
        },
        meta=meta,
        summary=f"{symbol} 持仓排名（{source}）",
    )


def _unavailable(symbol: str, meta: dict) -> A2APayload:
    """返回不可用 payload。"""
    meta["data_grade"] = "UNAVAILABLE"
    meta["data_grade_label"] = 5
    return A2APayload(
        type=DATA_TYPES.get("POSITION_RANKING", "fdc.position_ranking"),
        runtime_mode="independent",
        data={"symbol": symbol.lower()},
        meta=meta,
        summary=f"{symbol} 持仓排名不可用",
    )
