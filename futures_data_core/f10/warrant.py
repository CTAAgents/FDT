"""仓单日报 [INDEPENDENT]。

数据来源：交易所仓单日报官方端点（经 :mod:`exchange_scraper` 的路由转发）。
  - SHFE: JSON (stocks dat file)
  - DCE: TSV (日行情数据中提取仓单列)
  - CZCE: XLSX (仓单日报Excel)
  - GFEX: HTML (日行情数据中提取)

实现采用**可注入 transport** 设计：``get_warrant`` 接受 ``transport`` 可调用对象，
缺省走交易所官方端点。解析与汇总逻辑为纯函数。

A2A 输出：``type=fdc.warrant``。
"""

from __future__ import annotations

import io
import re
from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.f10.exchange_scraper import (
    fetch_exchange_page,
    get_warrant_url,
    warrant_fmt_of,
    today_yyyymmdd,
)

_WARRANT_KEYS = {"warrant", "receipt", "仓单", "仓单量", "仓单数量"}
_CHANGE_KEYS = {"change", "delta", "日变动", "增减", "仓单变动"}


def _match_key(headers: list[str], candidates: set[str]) -> Optional[str]:
    for h in headers:
        key = str(h).strip()
        if key.lower() in candidates or key in candidates:
            return h
    return None


def summarize_warrant(rows: list[dict]) -> dict:
    """从解析行汇总仓单总量与日变动（纯函数）。"""
    if not rows:
        return {"total": None, "daily_change": None, "rows": 0}

    headers = list(rows[0].keys())
    warrant_col = _match_key(headers, _WARRANT_KEYS)
    change_col = _match_key(headers, _CHANGE_KEYS)

    total = None
    if warrant_col:
        vals: list[float] = []
        for r in rows:
            try:
                vals.append(float(str(r.get(warrant_col, "")).replace(",", "")))
            except (TypeError, ValueError):
                pass
        if vals:
            total = sum(vals)

    daily_change = None
    if change_col:
        changes: list[float] = []
        for r in rows:
            try:
                changes.append(float(str(r.get(change_col, "")).replace(",", "")))
            except (TypeError, ValueError):
                pass
        if changes:
            daily_change = sum(changes)

    return {"total": total, "daily_change": daily_change, "rows": len(rows)}


def _parse_czce_xlsx(content: bytes) -> dict[str, dict]:
    """解析 CZCE 仓单日报 Excel（纯函数）。

    Excel 格式：每个品种一个区域，以 "品种：XX" 行开头，
    区域内包含仓库明细行，"总计" 行为该品种合计数。

    Returns:
        {symbol_lower: {"total": int, "daily_change": int}}
    """
    try:
        import pandas as pd

        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception:
        return {}

    result: dict[str, dict] = {}

    # 找品种区域 (header格式: "品种：白糖SR     单位：张")
    variety_idx = df[df.iloc[:, 0].astype(str).str.contains(r"品种：", na=False)].index.tolist()
    if not variety_idx:
        return result

    for i, idx in enumerate(variety_idx):
        header = str(df.iloc[idx, 0])
        vm = re.search(r"品种：(\w+)", header)
        if not vm:
            continue
        variety_code = vm.group(1)
        # CZCE格式: "菜粕RM" → 提取大写符号 "RM"
        sym_match = re.search(r"([A-Z]{1,3})$", variety_code)
        sym_raw = sym_match.group(1) if sym_match else variety_code

        end_idx = variety_idx[i + 1] if i + 1 < len(variety_idx) else len(df)
        section = df.iloc[idx:end_idx]
        total_row = section[section.iloc[:, 0].astype(str).str.strip().eq("总计")]
        if total_row.empty:
            # 尝试 "合计" 行
            total_row = section[section.iloc[:, 0].astype(str).str.strip().eq("合计")]
        if total_row.empty:
            continue

        # 列名匹配: CZCE 仓单Excel包含"仓单数量"和"当日增减"列
        header_row = section.iloc[1]
        qty_cols = []
        chg_col = None
        for c in range(min(9, len(header_row))):
            h = str(header_row.iloc[c]).strip()
            if "仓单数量" in h:
                qty_cols.append(c)
            elif "当日增减" in h and chg_col is None:
                chg_col = c

        if not qty_cols:
            continue

        try:
            qty = sum(
                int(total_row.iloc[0, c])
                for c in qty_cols
                if c < len(total_row.columns) and pd.notna(total_row.iloc[0, c])
            )
            chg = (
                int(total_row.iloc[0, chg_col])
                if chg_col is not None
                and chg_col < len(total_row.columns)
                and pd.notna(total_row.iloc[0, chg_col])
                else 0
            )
        except (ValueError, IndexError, TypeError):
            continue

        if qty == 0:
            continue

        result[sym_raw.lower()] = {"total": qty, "daily_change": chg}

    return result


async def get_warrant(
    symbol: str,
    exchange: str = "SHFE",
    trade_date: Optional[str] = None,
    *,
    transport=None,
) -> A2APayload:
    """获取品种仓单日报。无 LLM 依赖。

    Args:
        symbol: 品种代码。
        exchange: 交易所（SHFE/DCE/CZCE/CFFEX/GFEX）。
        trade_date: ``YYYYMMDD``；缺省今天。
        transport: 可注入抓取器（返回页面文本/bytes）；缺省走交易所官方端点。

    Returns:
        :class:`A2APayload`，``data`` 含 ``total`` / ``daily_change`` / ``data_source``。
    """
    if trade_date is None:
        trade_date = today_yyyymmdd()

    url = get_warrant_url(exchange, trade_date)
    if not url:
        return _unavailable(symbol, exchange, f"未知交易所 {exchange}")

    fmt = warrant_fmt_of(exchange) or "html"

    # ── xlsx 格式（CZCE）特殊处理 ──
    if fmt == "xlsx":
        return await _get_warrant_czce(symbol, url, trade_date, transport=transport)

    # ── json / tsv / html 通用处理 ──
    text = None
    try:
        text = await fetch_exchange_page(url, transport=transport)
    except Exception:
        pass

    if not text:
        return _unavailable(symbol, exchange, f"{exchange} 仓单页面获取失败")

    from futures_data_core.f10.exchange_scraper import parse_daily_rows

    rows = parse_daily_rows(text, fmt) if text else []
    summary = summarize_warrant(rows)

    if summary["total"] is None and not rows:
        return _unavailable(symbol, exchange, f"{exchange} 仓单数据解析为空")

    data: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "trade_date": trade_date,
        "total": summary["total"],
        "daily_change": summary["daily_change"],
        "source_rows": summary["rows"],
    }
    payload = A2APayload(type=DATA_TYPES["WARRANT"], runtime_mode="independent", data=data)
    payload.set_grade("DAILY")
    payload.meta["sources"] = [exchange.lower()]
    payload.summary = (
        f"{symbol} ({exchange}) 仓单 {data['total']}"
        + (f"，日变动 {data['daily_change']}" if data["daily_change"] is not None else "")
    )
    return payload


async def _get_warrant_czce(
    symbol: str,
    url: str,
    trade_date: str,
    transport=None,
) -> A2APayload:
    """CZCE 仓单 Excel 下载 + 解析。盘中回退前一日数据。"""
    content = None
    try:
        if transport is not None:
            raw = transport(url)
            if hasattr(raw, "__await__"):
                raw = await raw
            content = raw.encode() if isinstance(raw, str) else raw
        else:
            import httpx

            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200 and len(resp.content) > 1000:
                    content = resp.content
    except Exception:
        pass

    # CZCE 盘后才发布，如果当天数据不可用，回退前一日
    if not content:
        from datetime import datetime, timedelta

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        y_url = get_warrant_url("CZCE", yesterday)
        if y_url:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=15, verify=False) as client:
                    resp = await client.get(
                        y_url,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        content = resp.content
                        trade_date = yesterday
            except Exception:
                pass

    if not content:
        return _unavailable(symbol, "CZCE", "CZCE 仓单Excel获取失败")

    # 解析 Excel
    parsed = _parse_czce_xlsx(content)
    sym_lower = symbol.lower()
    matched = None
    # 精确匹配
    if sym_lower in parsed:
        matched = parsed[sym_lower]
    # 模糊匹配（如 symbol=TA, parsed.key=ta）
    for k, v in parsed.items():
        if k.strip("0123456789").lower() == sym_lower.strip("0123456789"):
            matched = v
            break

    if matched is None:
        return _unavailable(symbol, "CZCE", f"CZCE {symbol} 仓单数据缺失")

    data: dict[str, Any] = {
        "symbol": symbol,
        "exchange": "CZCE",
        "trade_date": trade_date,
        "total": matched["total"],
        "daily_change": matched.get("daily_change", 0),
        "source_rows": 1,
    }
    payload = A2APayload(type=DATA_TYPES["WARRANT"], runtime_mode="independent", data=data)
    payload.set_grade("DAILY")
    payload.meta["sources"] = ["czce"]
    payload.summary = f"{symbol} (CZCE) 仓单 {data['total']}"
    return payload


def _unavailable(symbol: str, exchange: str, reason: str) -> A2APayload:
    payload = A2APayload(
        type=DATA_TYPES["WARRANT"],
        runtime_mode="independent",
        data={"symbol": symbol, "total": None},
    )
    payload.set_grade("UNAVAILABLE")
    payload.add_warning(reason)
    return payload
