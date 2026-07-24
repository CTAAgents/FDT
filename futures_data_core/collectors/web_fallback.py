"""Web 兜底采集器（东方财富 + 新浪）[INDEPENDENT]。

当 FDC 主链路（QMT → TDX → TqSDK）全部不可用时，
通过标准库 urllib 直接调用东方财富和新浪的免费 K 线 API。

置信度：0.85（标记为 WebSearch 降级源）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from futures_data_core.collectors.base import BaseCollector, CollectorType
from futures_data_core.core.types import KlineBar, KlineData

# FDT 品种 -> 东方财富 exchange 代码 (SHFE=113, DCE=114, CZCE=115, GFEX=116)
_EXCHANGE_CODE_MAP: dict[str, int] = {
    "SHFE": 113, "DCE": 114, "CZCE": 115, "CFFEX": 116, "GFEX": 117, "INE": 113,
}


from futures_data_core.core.symbol_registry import strip_contract_suffix as _strip_suffix

def _get_exchange_code(variety: str, known: dict) -> Optional[int]:
    """品种代码 → 东方财富交易所数字代码。
    自动剥离合约月份后缀（``SM2609`` -> ``SM``）。
    """
    # 品种->交易所映射
    ex_map: dict[str, str] = {
        "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "PB": "SHFE", "NI": "SHFE",
        "SN": "SHFE", "AU": "SHFE", "AG": "SHFE", "RB": "SHFE", "HC": "SHFE",
        "SS": "SHFE", "RU": "SHFE", "BR": "SHFE", "FU": "SHFE", "BU": "SHFE",
        "SP": "SHFE", "WR": "SHFE", "AO": "SHFE",
        "A": "DCE", "B": "DCE", "M": "DCE", "Y": "DCE", "C": "DCE", "P": "DCE",
        "J": "DCE", "JM": "DCE", "I": "DCE", "L": "DCE", "PP": "DCE", "V": "DCE",
        "JD": "DCE", "RR": "DCE", "LH": "DCE", "EB": "DCE", "EG": "DCE",
        "PG": "DCE", "FB": "DCE", "BB": "DCE",
        "SR": "CZCE", "CF": "CZCE", "TA": "CZCE", "OI": "CZCE", "RM": "CZCE",
        "MA": "CZCE", "FG": "CZCE", "ZC": "CZCE", "SF": "CZCE", "SM": "CZCE",
        "CY": "CZCE", "AP": "CZCE", "CJ": "CZCE", "UR": "CZCE", "SA": "CZCE",
        "PF": "CZCE", "PK": "CZCE", "PX": "CZCE", "SH": "CZCE", "PR": "CZCE",
        "PS": "CZCE",
        "SC": "INE", "LU": "INE", "NR": "INE", "BC": "INE",
        "SI": "GFEX", "LC": "GFEX",
    }
    bare, _ = _strip_suffix(variety)
    ex = ex_map.get(bare.upper())
    return known.get(ex) if ex else None


class WebFallbackCollector(BaseCollector):
    """Web 兜底采集器（priority=2，第三数据源）。"""

    name = "web_fallback"
    priority = 2  # 第三数据源
    collector_type = CollectorType.INDEPENDENT
    llm_requirement = ""

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    async def check_available(self) -> bool:
        """始终可用（作为最后兜底层）。"""
        return True

    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120
    ) -> KlineData:
        """兜底 K 线：新浪为主（稳定），东方财富为辅（当前环境断连）。"""
        bars = self._try_sina(symbol, days=days)
        if not bars:
            bars = self._try_eastmoney(symbol)
        return KlineData(
            symbol=symbol,
            period=period,
            source=self.name,
            bars=[KlineBar(**b) for b in (bars or [])],
            contract="",
        )

    def _try_eastmoney(self, symbol: str) -> Optional[list]:
        """东方财富 push2his K 线 API。"""
        bare, _ = _strip_suffix(symbol)
        variety = bare.upper()
        ex_code = _get_exchange_code(variety, _EXCHANGE_CODE_MAP)
        if not ex_code:
            return None
        secid = f"{ex_code}.{variety}0"
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}"
            "&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            "&klt=101&fqt=1&beg=20250101"
            f"&end={datetime.now().strftime('%Y%m%d')}"
        )
        try:
            req = Request(url, headers={"User-Agent": self._UA, "Referer": "https://quote.eastmoney.com/"})
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
            klines = data.get("data", {}).get("klines", [])
            if klines:
                records = []
                for kline_str in klines:
                    parts = kline_str.split(",")
                    if len(parts) >= 6:
                        records.append({
                            "date": parts[0], "open": float(parts[1]),
                            "close": float(parts[2]), "high": float(parts[3]),
                            "low": float(parts[4]), "volume": int(float(parts[5])),
                        })
                if records:
                    return records[-days:]
        except Exception:
            pass
        return None

    def _try_sina(self, symbol: str, days: int = 120) -> Optional[list]:
        """新浪财经 InnerFuturesNewService K 线 API（主力连续 = {variety}0）。

        注意：新浪返回短键 d/o/h/l/c/v（非 date/open/...），且日期为
        YYYY-MM-DD；早期版本误用长键名 + 未归一，导致解析出空日期与 0 价格。
        """
        bare, _ = _strip_suffix(symbol)
        variety = bare.upper()
        sina_sym = f"{variety}0"
        url = (
            "https://stock2.finance.sina.com.cn/futures/api/jsonp.php"
            f"/var%20_{sina_sym}=/InnerFuturesNewService.getDailyKLine"
            f"?symbol={sina_sym}"
        )
        try:
            req = Request(url, headers={"User-Agent": self._UA, "Referer": "https://finance.sina.com.cn/"})
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")
            match = re.search(r"=\((\[.+?\])\)", raw, re.DOTALL)
            if not match:
                return None
            klines = json.loads(match.group(1))
            if klines and isinstance(klines, list):
                records = []
                for k in klines:
                    # 新浪短键: d=日期 o=开 h=高 l=低 c=收 v=量 p=持仓 s=结算价
                    records.append({
                        "date": str(k.get("d", "")).replace("-", ""),
                        "open": float(k.get("o", 0)),
                        "high": float(k.get("h", 0)),
                        "low": float(k.get("l", 0)),
                        "close": float(k.get("c", 0)),
                        "volume": int(float(k.get("v", 0))),
                        "open_interest": float(k.get("p", 0)),
                        "settlement": float(k.get("s", 0)),
                    })
                if records:
                    return records[-days:]
        except Exception:
            pass
        return None
