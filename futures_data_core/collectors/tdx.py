"""通达信 TQ-Local 采集器 [INDEPENDENT]。

通过本地通达信客户端的 HTTP 服务（默认 ``http://127.0.0.1:17709/``）以
JSON-RPC 方式获取期货 K 线与行情快照，无需任何 LLM 依赖。

协议要点（来自 TQ-Local 接口文档）：
    - 所有请求为 ``POST``，body 形如
      ``{"id":1, "method":<方法名>, "params":{...}}``。
    - ``get_market_data``：K 线/历史行情，返回字段为
      ``Date/Open/High/Low/Close/Volume/Amount`` 等字符串数组。
    - ``get_market_snapshot``：实时行情快照。
    - ``get_stock_list``（``market="92"``）：期货主力合约列表。

测试策略：通过 ``transport`` 注入假 JSON-RPC 传输，完全脱离本地客户端。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorType,
    CollectorUnavailableError,
)
from futures_data_core.core.symbol_registry import get_symbol
from futures_data_core.core.types import KlineBar, KlineData, QuoteData

# TQ-Local 本地服务地址
DEFAULT_BASE_URL = "http://127.0.0.1:17709/"
DEFAULT_TIMEOUT = 3  # G26: TQ-Local 离线时快速失败（原15s导致降级链超时累积）
# 期货市场代码（TQ-Local get_stock_list 的 market 参数）
FUTURES_MARKET = "92"

# FDT 周期 -> TQ-Local period 映射
_PERIOD_MAP = {
    "daily": "1d",
    "1d": "1d",
    "60m": "60m",
    "120m": "120m",
    "240m": "240m",
    "weekly": "1w",
    "1w": "1w",
}


class TDXCollector(BaseCollector):
    """通达信 TQ-Local 采集器（priority=0，第一数据源）。"""

    name = "tdx_tq_local"
    priority = 0
    collector_type = CollectorType.INDEPENDENT
    llm_requirement = ""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        transport: Optional[Callable[[str, dict], Any]] = None,
    ) -> None:
        """初始化。

        Args:
            base_url: TQ-Local 服务地址。
            timeout: HTTP 超时（秒）。
            transport: 可选的异步传输函数 ``async (method, params) -> dict``，
                用于测试注入；为 ``None`` 时使用真实 httpx 客户端。
        """
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport
        self._contract_cache: Optional[dict] = None
        self._contract_lock = asyncio.Lock()

    # ───────────────────────────────────────────────────────────
    # 传输层
    # ───────────────────────────────────────────────────────────
    async def _post(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并返回解析后的 ``result`` 部分。

        Args:
            method: TQ-Local 方法名。
            params: 方法参数。

        Returns:
            响应中的 ``result`` 字典（已剥离外层信封）。
        """
        payload = {"id": 1, "method": method, "params": params}
        if self._transport is not None:
            return await self._transport(method, params)

        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.base_url, json=payload)
            body = resp.json()
        return body.get("result", body)

    # ───────────────────────────────────────────────────────────
    # 可用性探测
    # ───────────────────────────────────────────────────────────
    async def check_available(self) -> bool:
        """探测 TQ-Local 是否可用（轻量 get_stock_list 调用）。
        🐛 2026-07-13: 缺 list_type=1 参数导致 TQ-Local 返回 ErrorId=10（参数缺少:market/list_type）
        """
        try:
            resp = await self._post("get_stock_list", {"market": FUTURES_MARKET, "list_type": 1})
            result = resp.get("Value", resp) if isinstance(resp, dict) else resp
            return isinstance(result, list) and len(result) > 0
        except Exception:
            return False

    # ───────────────────────────────────────────────────────────
    # 合约解析
    # ───────────────────────────────────────────────────────────
    async def _resolve_contract(self, symbol: str) -> str:
        """将品种代码解析为 TQ-Local 合约代码（取该品种首个合约）。

        Args:
            symbol: 品种代码（如 ``"CU"``）。

        Returns:
            TQ-Local 合约代码（如 ``"CU2408"``）。

        Raises:
            CollectorUnavailableError: 品种未知或无法在合约列表中定位。
        """
        meta = get_symbol(symbol)
        if meta is None:
            raise CollectorUnavailableError(self.name, f"未知品种: {symbol}")
        async with self._contract_lock:
            if self._contract_cache is None:
                await self._load_contracts()
        contracts = self._contract_cache or {}
        alpha = symbol.upper()
        if alpha in contracts:
            return contracts[alpha]
        raise CollectorUnavailableError(
            self.name, f"TQ-Local 合约列表中未找到品种 {symbol}"
        )

    async def _load_contracts(self) -> None:
        """加载期货主力合约映射 ``{品种字母: 合约代码}``。
        🐛 2026-07-13: 缺 list_type=1 参数导致 TQ-Local 返回 ErrorId=10（合约列表为空）
        """
        self._contract_cache = {}
        try:
            resp = await self._post("get_stock_list", {"market": FUTURES_MARKET, "list_type": 1})
            result = resp.get("Value", resp) if isinstance(resp, dict) else resp
            if not isinstance(result, list):
                return
            for item in result:
                code = item.get("Code")
                if not code:
                    continue
                alpha = "".join(c for c in code.split(".")[0] if c.isalpha()).upper()
                if alpha and alpha not in self._contract_cache:
                    self._contract_cache[alpha] = code
        except Exception:
            self._contract_cache = {}

    # ───────────────────────────────────────────────────────────
    # K 线
    # ───────────────────────────────────────────────────────────
    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120
    ) -> KlineData:
        """获取 K 线数据。

        Args:
            symbol: 品种代码。
            period: 周期（``daily`` / ``60m`` / ``120m`` / ``240m`` / ``weekly``）。
            days: 回溯交易日数。

        Returns:
            归一化 :class:`KlineData`。

        Raises:
            CollectorUnavailableError: 合约解析失败或拉取异常。
        """
        tdx_period = _PERIOD_MAP.get(period, "1d")
        try:
            contract = await self._resolve_contract(symbol)
            resp = await self._post(
                "get_market_data",
                {
                    "stock_list": [contract],
                    "count": days,
                    "dividend_type": "none",
                    "period": tdx_period,
                },
            )
        except CollectorUnavailableError:
            raise
        except Exception as exc:  # 网络/解析异常统一降级
            raise CollectorUnavailableError(self.name, str(exc)) from exc

        bars = self._parse_kline(resp, contract)
        return KlineData(
            symbol=symbol,
            period=period,
            source=self.name,
            bars=bars,
            contract=contract,
        )

    @staticmethod
    def _parse_kline(resp: dict, contract: str) -> list[KlineBar]:
        """从 get_market_data 响应中解析 K 线列表。"""
        if not isinstance(resp, dict):
            return []
        # 兼容两种返回形态：result[contract] 或 result["Value"][contract]
        value = resp.get("Value", resp)
        series = None
        if isinstance(value, dict) and contract in value:
            series = value[contract]
        elif contract in resp:
            series = resp[contract]
        if not isinstance(series, dict):
            return []

        dates = series.get("Date", []) or []
        opens = series.get("Open", []) or []
        highs = series.get("High", []) or []
        lows = series.get("Low", []) or []
        closes = series.get("Close", []) or []
        volumes = series.get("Volume", []) or []
        amounts = series.get("Amount", []) or []
        holds = series.get("Hold", []) or []

        n = min(len(dates), len(opens), len(closes))
        bars: list[KlineBar] = []
        for i in range(n):
            try:
                bars.append(
                    KlineBar(
                        date=str(dates[i]),
                        open=float(opens[i]),
                        high=float(highs[i]),
                        low=float(lows[i]),
                        close=float(closes[i]),
                        volume=float(volumes[i]) if i < len(volumes) else 0.0,
                        amount=float(amounts[i]) if i < len(amounts) else 0.0,
                        open_interest=float(holds[i]) if i < len(holds) else 0.0,
                    )
                )
            except (TypeError, ValueError):
                continue
        return bars

    # ───────────────────────────────────────────────────────────
    # 行情快照
    # ───────────────────────────────────────────────────────────
    async def get_quote(self, symbol: str) -> QuoteData:
        """获取行情快照。

        Raises:
            CollectorUnavailableError: 合约解析失败或拉取异常。
        """
        try:
            contract = await self._resolve_contract(symbol)
            resp = await self._post(
                "get_market_snapshot", {"stock_code": contract}
            )
        except CollectorUnavailableError:
            raise
        except Exception as exc:
            raise CollectorUnavailableError(self.name, str(exc)) from exc

        snap = resp.get("Value", resp) if isinstance(resp, dict) else resp
        snap = snap if isinstance(snap, dict) else {}

        def _f(key: str) -> Optional[float]:
            v = snap.get(key)
            if v in (None, ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return QuoteData(
            symbol=symbol,
            source=self.name,
            last_price=_f("Now"),
            open=_f("Open"),
            high=_f("Max"),
            low=_f("Min"),
            pre_close=_f("LastClose"),
            volume=_f("Volume"),
        )

    # ───────────────────────────────────────────────────────────
    # 技术指标（formula_zb）
    # ───────────────────────────────────────────────────────────
    async def get_indicators(self, symbol: str) -> Optional[dict]:
        """通过通达信 formula_zb 获取品种技术指标。

        覆盖指标（与通达信实盘100%一致）：
          ADX/PDI/MDI(DMI), RSI, CCI, MACD(DIF/DEA/HIST),
          MA(5/10/20/40/60), BOLL(UB/中轨/LB), OBV

        Args:
            symbol: 品种代码（如 'rb', 'CU', 'M'）。

        Returns:
            指标字典如 {'adx': 59.3, 'rsi': 31.6, ...} 或 None。
        """
        try:
            contract = await self._resolve_contract(symbol)
        except CollectorUnavailableError:
            return None
        if not await self._set_data(contract):
            return None

        result = {}

        dmi = await self._query_formula("DMI", "14,6")
        if dmi:
            result["adx"] = self._last_float(dmi.get("ADX"))
            result["pdi"] = self._last_float(dmi.get("PDI"))
            result["mdi"] = self._last_float(dmi.get("MDI"))

        rsi = await self._query_formula("RSI", "14,14")
        if rsi:
            result["rsi"] = self._last_float(rsi.get("RSI1"))

        cci = await self._query_formula("CCI", "")
        if cci:
            result["cci"] = self._last_float(cci.get("CCI"))

        macd = await self._query_formula("MACD", "")
        if macd:
            result["macd_dif"] = self._last_float(macd.get("DIF"))
            result["macd_dea"] = self._last_float(macd.get("DEA"))
            result["macd_hist"] = self._last_float(macd.get("MACD"))

        ma = await self._query_formula("MA", "")
        if ma:
            for i in range(1, 6):
                v = self._last_float(ma.get(f"MA{i}"))
                if v is not None:
                    result[f"ma{i}"] = v

        boll = await self._query_formula("BOLL", "")
        if boll:
            result["boll_upper"] = self._last_float(boll.get("UB"))
            result["boll_mid"] = self._last_float(boll.get("BOLL"))
            result["boll_lower"] = self._last_float(boll.get("LB"))

        obv = await self._query_formula("OBV", "")
        if obv:
            result["obv"] = self._last_float(obv.get("OBV"))
            result["obv_ma"] = self._last_float(obv.get("MAOBV"))

        return result if result else None

    async def _set_data(self, stock_code: str) -> bool:
        """设置 formula_zb 的数据上下文。"""
        try:
            resp = await self._post(
                "formula_set_data_info",
                {
                    "stock_code": stock_code,
                    "stock_period": "1d",
                    "count": 250,
                    "dividend_type": 0,
                },
            )
            err = resp.get("ErrorId", "") if isinstance(resp, dict) else ""
            return err in ("", "0")
        except Exception:
            return False

    async def _query_formula(self, formula: str, arg: str = "") -> Optional[dict]:
        """查询单个通达信公式。"""
        try:
            resp = await self._post(
                "formula_zb",
                {"formula_name": formula, "formula_arg": arg, "xsflag": 2},
            )
            return resp.get("Value", resp) if isinstance(resp, dict) else resp
        except Exception:
            return None

    @staticmethod
    def _last_float(arr) -> Optional[float]:
        """安全提取数组最后一个有效值。"""
        if not arr:
            return None
        for v in reversed(arr):
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None
