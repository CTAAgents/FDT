"""交易所官方数据爬取助手 [INDEPENDENT]。

为仓单 / 行情等模块提供通用的「HTTP 抓取 + 表格解析」能力。交易所端点与数据格式
取自 futures-data-search 已验证的 ``exchange_api_config.json``（SHFE=json, DCE=tsv,
CZCE/GFEX=html, CFFEX=csv），内嵌为常量以避免对外部文件的不确定依赖。

所有网络访问通过**可注入 transport** 完成；解析函数为纯函数便于单元测试。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Awaitable, Callable, Optional, Union

try:
    from bs4 import BeautifulSoup

    _HAS_BS4 = True
except ImportError:  # pragma: no cover - bs4 为声明依赖，正常环境必有
    BeautifulSoup = None
    _HAS_BS4 = False


# 端点与格式（源自已验证的 exchange_api_config.json）
EXCHANGE_ENDPOINTS: dict[str, dict] = {
    "SHFE": {
        "base_url": "http://www.shfe.com.cn",
        "fmt": "json",
        "endpoint": "/data/dailydata/kx/kx{date}.dat",
    },
    "DCE": {
        "base_url": "http://www.dce.com.cn",
        "fmt": "tsv",
        "endpoint": "/publicweb/quotesdata/exportDayQuotesChData.html",
    },
    "CZCE": {
        "base_url": "http://www.czce.com.cn",
        "fmt": "html",
        "endpoint": "/cn/DFSStaticFiles/Future/{year}/{date}/FutureDataDaily.htm",
    },
    "CFFEX": {
        "base_url": "http://www.cffex.com.cn",
        "fmt": "csv",
        "endpoint": "/sj/hqsj/rtj/{year_month}/{day}/{date}_1.csv",
    },
    "GFEX": {
        "base_url": "http://www.gfex.com.cn",
        "fmt": "html",
        "endpoint": "/gfex/rihq/{date}.js",
    },
}


def get_exchange_url(exchange: str, trade_date: str) -> Optional[str]:
    """根据交易所与交易日构造数据 URL；未知交易所返回 ``None``。"""
    ex = EXCHANGE_ENDPOINTS.get(exchange.upper())
    if ex is None:
        return None
    y = trade_date[:4]
    ym = trade_date[:6]
    day = trade_date[6:]
    ep = (
        ex["endpoint"]
        .replace("{year}", y)
        .replace("{year_month}", ym)
        .replace("{date}", trade_date)
        .replace("{day}", day)
    )
    return ex["base_url"] + ep


def fmt_of(exchange: str) -> Optional[str]:
    """返回交易所数据格式（json/csv/tsv/html）。"""
    ex = EXCHANGE_ENDPOINTS.get(exchange.upper())
    return ex["fmt"] if ex else None


async def fetch_exchange_page(
    url: str,
    *,
    transport: Optional[Callable[[str], Union[str, Awaitable[str]]]] = None,
) -> str:
    """抓取交易所页面文本（可注入 transport）。

    Args:
        url: 目标 URL。
        transport: 注入的抓取器（同步或异步，返回页面文本）；缺省使用 httpx。

    Raises:
        Exception: 真实 httpx 请求失败时上抛（调用方自行降级）。
    """
    if transport is not None:
        out = transport(url)
        if hasattr(out, "__await__"):
            out = await out
        return out  # type: ignore[return-value]
    return await _httpx_get(url)


async def _httpx_get(url: str) -> str:
    """真实 httpx 抓取（抽离为模块级函数，便于测试桩替换）。"""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def parse_daily_rows(text: str, fmt: str) -> list[dict]:
    """将交易所日线文本解析为行字典列表（纯函数）。"""
    if not text:
        return []
    fmt = (fmt or "").lower()
    if fmt == "json":
        return _parse_json(text)
    if fmt == "csv":
        return _parse_csv(text, ",")
    if fmt == "tsv":
        return _parse_csv(text, "\t")
    if fmt == "html":
        return _parse_html(text)
    return []


def _parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # SHFE kx 格式常为 {"o_curinstrument": [...]} 等单一列表值
        lists = [v for v in data.values() if isinstance(v, list)]
        rows = lists[0] if lists else []
    else:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _parse_csv(text: str, delimiter: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [dict(row) for row in reader]


def _parse_html(text: str) -> list[dict]:
    if not _HAS_BS4:
        return []
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(strip=True) for c in header_cells]
    result: list[dict] = []
    for tr in rows[1:]:
        cells = tr.find_all("td")
        if len(cells) != len(headers):
            continue
        result.append({headers[i]: cells[i].get_text(strip=True) for i in range(len(headers))})
    return result


def today_yyyymmdd() -> str:
    """返回 ``YYYYMMDD`` 格式当前交易日。"""
    return datetime.now().strftime("%Y%m%d")
