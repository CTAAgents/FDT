"""基差分析（现货 - 期货）[INDEPENDENT]。

数据来源：
  1. 现货价：生意社 (100ppi.com) 公开页面直接爬取，零鉴权
  2. 期货价：QMT/xtquant ``get_main_contract`` + ``get_market_data_ex``
     或可选的 TDX 等注入 fetcher

实现采用**可注入 fetcher** 设计：``get_basis`` 接受 ``fetch_spot`` /
``fetch_futures`` 可调用对象；计算内核 ``compute_basis`` 为纯函数。

A2A 输出：``type=fdc.basis``。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional, Union

from futures_data_core._a2a import A2APayload, DATA_TYPES


def compute_basis(
    spot_price: float,
    futures_price: float,
    unit: str = "元/吨",
    currency: str = "CNY",
) -> Optional[dict]:
    """计算基差（纯函数）。

    ``basis = spot - futures``；``basis_pct = basis / futures * 100``。

    Returns:
        含 ``basis`` / ``basis_pct`` / ``unit`` / ``currency`` 的 dict；
        期货价非正时返回 ``None``。
    """
    if futures_price is None or futures_price <= 0:
        return None
    basis = spot_price - futures_price
    basis_pct = basis / futures_price * 100.0
    return {
        "basis": round(basis, 2),
        "basis_pct": round(basis_pct, 4),
        "unit": unit,
        "currency": currency,
    }


class PpiSpotFetcher:
    """生意社 (100ppi.com) 现货价抓取器 [INDEPENDENT, 可选]。

    生意社现货价 API 需要 token；未配置 ``token`` 时静默降级（返回 ``None``），
    调用方应回退到 AKShare 等可用源。本类仅负责 HTTP + JSON 解析，
    不假定任何未经验证的端点必然可用（避免幻觉）。
    """

    def __init__(
        self,
        token: Optional[str] = None,
        endpoint: Optional[str] = None,
        transport: Optional[Callable[[str], Awaitable[tuple[int, str]]]] = None,
    ) -> None:
        self.token = token
        self.endpoint = endpoint or "https://www.100ppi.com/api/json/{token}/price/{name}.html"
        self._transport = transport

    async def fetch(self, symbol: str, name: Optional[str] = None) -> Optional[float]:
        """抓取现货价；不可用时返回 ``None``。"""
        if self.token is None:
            return None
        url = self.endpoint.format(token=self.token, name=name or symbol.lower())
        try:
            raw = self._transport(url) if self._transport is not None else await _httpx_get(url)
            if hasattr(raw, "__await__"):
                raw = await raw
            status, body = raw
        except Exception:
            return None
        if status != 200:
            return None
        return self._parse(body)

    @staticmethod
    def _parse(body: str) -> Optional[float]:
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return None
        price = data.get("price") if isinstance(data, dict) else None
        if price is None:
            return None
        try:
            return float(price)
        except (TypeError, ValueError):
            return None


async def _maybe(inj, default_fn, symbol):
    """若注入 fetcher 则用之，否则走默认函数。"""
    if inj is not None:
        out = inj(symbol)
        if hasattr(out, "__await__"):
            out = await out
        return out
    return await default_fn(symbol)


# ════════════════════════════════════════════════════════════
# 默认 fetcher：现货价 ← 生意社直爬
# ════════════════════════════════════════════════════════════

_PPI_BASE_URL = "https://www.100ppi.com/spec/"


async def _ppi_spot_page(symbol: str) -> Optional[float]:
    """从生意社 (100ppi.com) 公开页面爬取现货价，零鉴权。

    尝试直接爬取品种现货页面，提取最新现货价格。
    源不可用时静默返回 ``None``（触发基差不可用降级）。
    """
    url = f"{_PPI_BASE_URL}{symbol.lower()}.html"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "lxml")
        # 尝试多个常见选择器提取现货价
        price_text = (
            soup.select_one(".price-today .num")
            or soup.select_one(".sprice .num")
            or soup.select_one(".price")
            or soup.select_one("[class*='price']")
        )
        if price_text is None:
            return None
        raw = price_text.text.strip().replace(",", "").replace(" ", "")
        return float(raw) if raw else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 默认 fetcher：期货价 ← QMT/xtquant
# ════════════════════════════════════════════════════════════


async def _qmt_futures_pair(symbol: str) -> Optional[tuple[float, Optional[str]]]:
    """通过 QMT/xtquant 获取主力合约价与合约代码。

    Returns:
        ``(price, contract_code)`` 或失败时 ``None``。
    """
    try:
        from xtquant import xtdata
    except ImportError:
        return None
    try:
        sym = symbol.upper()
        con_code = f"{sym}00.SF"  # 主力连续后缀（跨交易所兼容用默认 SF）
        main_con = xtdata.get_main_contract(con_code)
        if not main_con:
            return None

        import pandas as pd

        klines = xtdata.get_market_data_ex(
            [], [main_con], period="1d", count=1, dividend_type="none"
        )
        if not isinstance(klines, dict) or main_con not in klines:
            return None
        df = klines[main_con]
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        price = float(df["close"].iloc[-1])
        return price, main_con
    except Exception:
        return None


async def _httpx_get(url: str) -> tuple[int, str]:
    """真实 httpx 抓取（抽离为模块级函数，便于测试桩替换）。"""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        return resp.status_code, resp.text


async def get_basis(
    symbol: str,
    *,
    fetch_spot: Optional[Callable[[str], Union[float, Awaitable[Optional[float]]]]] = None,
    fetch_futures: Optional[
        Callable[[str], Union[tuple, float, Awaitable]]
    ] = None,
) -> A2APayload:
    """获取品种基差（现货 - 期货）。无 LLM 依赖。

    Args:
        symbol: 品种代码。
        fetch_spot: 可注入现货价 fetcher（返回 ``float``）。
        fetch_futures: 可注入期货价 fetcher（返回 ``(price, contract)`` 或 ``float``）。

    Returns:
        :class:`A2APayload`，``data`` 含 ``spot_price`` / ``futures_price`` /
        ``futures_contract`` / ``basis`` / ``basis_pct`` 等。
    """
    spot = await _maybe(fetch_spot, _ppi_spot_page, symbol)

    raw_fut = await _maybe(fetch_futures, _qmt_futures_pair, symbol)
    if isinstance(raw_fut, tuple):
        futures, contract = raw_fut[0], (raw_fut[1] if len(raw_fut) > 1 else None)
    else:
        futures, contract = raw_fut, None

    if spot is None or futures is None:
        payload = A2APayload(
            type=DATA_TYPES["BASIS"],
            runtime_mode="independent",
            data={"symbol": symbol, "basis": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("现货或期货价格缺失，基差不可用")
        return payload

    b = compute_basis(spot, futures)
    if b is None:
        payload = A2APayload(
            type=DATA_TYPES["BASIS"],
            runtime_mode="independent",
            data={"symbol": symbol, "basis": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("期货价格非正，基差不可用")
        return payload

    data: dict[str, Any] = {
        "symbol": symbol,
        "spot_price": round(spot, 2),
        "futures_price": round(futures, 2),
        "futures_contract": contract,
        **b,
    }
    payload = A2APayload(type=DATA_TYPES["BASIS"], runtime_mode="independent", data=data)
    payload.set_grade("PRIMARY")
    spot_label = "injected" if fetch_spot is not None else "ppi_100ppi"
    fut_label = "injected" if fetch_futures is not None else "qmt_xtquant"
    payload.meta["sources"] = [spot_label, fut_label]
    payload.summary = (
        f"{symbol} 基差 {data['basis']:.2f}（{data['basis_pct']:.2f}%），"
        f"现货 {data['spot_price']} vs 期货 {data['futures_price']}"
    )
    return payload


# ════════════════════════════════════════════════════════════
# 100ppi 现期表聚合抓取（一次HTTP获取60+品种现货+基差）
# ════════════════════════════════════════════════════════════

_PPI_SF_URL = "https://www.100ppi.com/sf/"
# 品种 → 100ppi sf_id 映射（精简版，核心活跃品种）
_PPI_SF_MAP: dict[str, int] = {
    "cu": 792, "al": 827, "zn": 826, "pb": 825, "ni": 1182, "sn": 1181,
    "rb": 927, "hc": 195, "ss": 1300, "fu": 387, "bu": 1022, "ru": 586,
    "sp": 1053, "TA": 356, "PF": 976, "eg": 252, "MA": 308, "SA": 1287,
    "FG": 279, "UR": 1288, "v": 839, "pp": 850, "l": 793,
    "CF": 162, "SR": 688, "OI": 373, "RM": 431, "PK": 1319,
    "m": 416, "y": 780, "p": 446, "c": 155, "jd": 1408, "lh": 1295,
    "sc": 543, "lu": 1330, "pg": 1286, "bu": 1022,
    "i": 723, "j": 357, "jm": 355, "SF": 1098, "SM": 1102,
    "si": 1406, "lc": 1407,
}


def _parse_100ppi_sf_page(html: str) -> tuple[Optional[str], dict[str, dict]]:
    """解析100ppi现期表HTML页面（纯函数）。

    Returns:
        (data_date, {symbol_lower: {"spot_raw": float, "main_price": float, ...}})
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    data_date = None

    # 日期行: <span class="s_time">2026-07-13</span>
    time_span = soup.select_one("span.s_time")
    if time_span:
        data_date = time_span.text.strip()

    raw_items: dict[str, dict] = {}
    table = soup.find("table", class_="sf-table") or soup.find("table", id="sf-table")
    if not table:
        table = soup.find("table")
    if not table:
        return data_date, raw_items

    rows = table.find_all("tr")
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        # 第0列: 品种名称+代码，如 "螺纹钢" / "RB"
        name_text = cells[0].get_text(strip=True)
        if not name_text:
            continue
        # 查找匹配的品种：从映射表中匹配
        matched_sym = None
        for sym, sf_id in _PPI_SF_MAP.items():
            if sym.upper() in name_text.upper() or name_text.upper() in sym.upper():
                matched_sym = sym
                break
        if not matched_sym:
            # 尝试从文本提取符号
            for sym in _PPI_SF_MAP:
                if sym.lower() in name_text.lower():
                    matched_sym = sym
                    break
        if not matched_sym:
            continue

        try:
            spot_raw = float(cells[2].get_text(strip=True).replace(",", ""))
        except (ValueError, IndexError):
            continue
        try:
            main_price = float(cells[3].get_text(strip=True).replace(",", ""))
        except (ValueError, IndexError):
            main_price = 0.0

        raw_items[matched_sym.lower()] = {
            "name": name_text,
            "sf_id": _PPI_SF_MAP[matched_sym],
            "spot_raw": spot_raw,
            "main_price": main_price,
        }

    return data_date, raw_items


async def get_basis_batch(
    symbols: Optional[list[str]] = None,
    timeout: int = 15,
) -> A2APayload:
    """批量获取基差数据（100ppi现期表聚合页，一次HTTP获取所有品种）。

    Args:
        symbols: 品种列表；None → 全部覆盖品种。
        timeout: HTTP超时秒数。

    Returns:
        A2APayload，data 含 items / data_date / covered_count。
    """
    import httpx

    meta = _default_meta()
    meta["sources"] = ["100ppi_sf"]

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                _PPI_SF_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    ),
                },
            )
        if resp.status_code != 200:
            meta["data_grade"] = "UNAVAILABLE"
            meta["data_grade_label"] = 5
            return A2APayload(
                type=DATA_TYPES.get("BASIS", "fdc.basis"),
                data={"items": {}, "error": f"HTTP {resp.status_code}"},
                meta=meta,
            )

        data_date, raw_items = _parse_100ppi_sf_page(resp.text)
        if not raw_items:
            meta["data_grade"] = "UNAVAILABLE"
            meta["data_grade_label"] = 5
            return A2APayload(
                type=DATA_TYPES.get("BASIS", "fdc.basis"),
                data={"items": {}, "error": "100ppi页面解析为空"},
                meta=meta,
            )

        # 新鲜度校验
        freshness_ok = False
        if data_date:
            try:
                page_dt = datetime.strptime(data_date, "%Y-%m-%d").date()
                delta = (date.today() - page_dt).days
                freshness_ok = delta <= 1
            except (ValueError, TypeError):
                pass

        # 构建输出
        items = {}
        target_syms = set(s.lower() for s in symbols) if symbols else set(raw_items.keys())
        for sym_lower in target_syms:
            if sym_lower not in raw_items:
                continue
            raw = raw_items[sym_lower]
            spot = raw["spot_raw"]
            fut = raw["main_price"]
            if spot <= 0:
                continue

            b = compute_basis(spot, fut) if fut and fut > 0 else None
            items[sym_lower] = {
                "spot_price": spot,
                "futures_price": fut if fut > 0 else None,
                "basis": b["basis"] if b else None,
                "basis_pct": b["basis_pct"] if b else None,
                "data_source": "100ppi_sf",
            }

        meta["data_grade"] = "PRIMARY" if freshness_ok else "DAILY"
        meta["data_grade_label"] = 0 if freshness_ok else 2
        return A2APayload(
            type=DATA_TYPES.get("BASIS", "fdc.basis"),
            data={
                "items": items,
                "data_date": data_date,
                "covered_count": len(items),
                "freshness_ok": freshness_ok,
            },
            meta=meta,
            summary=f"100ppi现期表: {len(items)}品种 (日期:{data_date})",
        )

    except Exception as e:
        meta["data_grade"] = "UNAVAILABLE"
        meta["data_grade_label"] = 5
        meta["warnings"] = [str(e)[:80]]
        return A2APayload(
            type=DATA_TYPES.get("BASIS", "fdc.basis"),
            data={"items": {}, "error": str(e)[:80]},
            meta=meta,
        )
