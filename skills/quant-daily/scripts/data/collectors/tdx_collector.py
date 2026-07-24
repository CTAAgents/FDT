#!/usr/bin/env python3
"""
通达信Tdx量化本地数据采集器 v2.0

通过通达信本地HTTP服务（JSON-RPC协议）获取期货行情数据。
数据源：本机通达信客户端 TdxW.exe → HTTP 127.0.0.1:17709

功能：
- 行情查询（主力/任意合约/连续）
- 全部合约发现与K线批量获取
- 期限结构计算（Back/Contango + 斜率）
- 跨期价差计算（近月-远月价差 + Z分数）

代码格式：
- 具体合约：CU2607.SHF（品种+年月+交易所）
- 连续合约：CUL8.SHF（主连） CUL7.SHF（次连） CUL9.SHF（加权）

数据源优先级：已配置为最高（不论盘中盘后均为 priority=0）
"""

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

# ==================== 交易所后缀映射 ====================
EXCHANGE_SUFFIX = {
    "SHFE": "SHF",
    "DCE": "DCE",
    "CZCE": "CZC",
    "CFFEX": "CFF",
    "INE": "INE",
    "GFEX": "GFE",
}

# ==================== 品种与交易所映射 ====================
VARIETY_EXCHANGE = {
    "CU": "SHFE",
    "AL": "SHFE",
    "ZN": "SHFE",
    "PB": "SHFE",
    "NI": "SHFE",
    "SN": "SHFE",
    "AU": "SHFE",
    "AG": "SHFE",
    "RB": "SHFE",
    "HC": "SHFE",
    "RU": "SHFE",
    "BR": "SHFE",
    "FU": "SHFE",
    "BU": "SHFE",
    "SP": "SHFE",
    "SS": "SHFE",
    "AO": "SHFE",
    "WR": "SHFE",
    "OP": "SHFE",
    "A": "DCE",
    "B": "DCE",
    "M": "DCE",
    "Y": "DCE",
    "P": "DCE",
    "C": "DCE",
    "CS": "DCE",
    "I": "DCE",
    "J": "DCE",
    "JM": "DCE",
    "L": "DCE",
    "V": "DCE",
    "PP": "DCE",
    "EG": "DCE",
    "EB": "DCE",
    "PG": "DCE",
    "JD": "DCE",
    "LH": "DCE",
    "RR": "DCE",
    "FB": "DCE",
    "AP": "CZCE",
    "CF": "CZCE",
    "CJ": "CZCE",
    "FG": "CZCE",
    "SA": "CZCE",
    "MA": "CZCE",
    "TA": "CZCE",
    "UR": "CZCE",
    "PF": "CZCE",
    "PR": "CZCE",
    "PX": "CZCE",
    "PK": "CZCE",
    "OI": "CZCE",
    "RM": "CZCE",
    "SR": "CZCE",
    "SF": "CZCE",
    "SM": "CZCE",
    "SH": "CZCE",
    "ZC": "CZCE",
    "SC": "INE",
    "LU": "INE",
    "NR": "INE",
    "BC": "INE",
    "EC": "INE",
    "SI": "GFEX",
    "LC": "GFEX",
    "PS": "GFEX",
    "IF": "CFFEX",
    "IH": "CFFEX",
    "IC": "CFFEX",
    "IM": "CFFEX",
    "T": "CFFEX",
    "TF": "CFFEX",
    "TS": "CFFEX",
    "TL": "CFFEX",
}

# 连续合约后缀
CONTINUOUS_SUFFIX = {
    "main": "L8",  # 主力连续
    "sub": "L7",  # 次主力连续
    "index": "L9",  # 加权指数
}


def _get_tdx_codes(variety: str) -> List[str]:
    """根据品种代码和当前日期生成候选通达信代码（优先主力连续L8）"""
    variety = variety.upper()
    exchange = VARIETY_EXCHANGE.get(variety)
    if not exchange:
        return []
    suffix = EXCHANGE_SUFFIX.get(exchange)
    if not suffix:
        return []
    now = datetime.now()
    year = now.year % 100
    month = now.month
    offsets = {
        "SHFE": [1, 2, 3, 0],
        "DCE": [3, 4, 5, 2],
        "CZCE": [2, 3, 4, 1],
        "CFFEX": [0, 1, 2, 3],
        "INE": [1, 2, 3, 0],
        "GFEX": [3, 4, 5, 2],
    }.get(exchange, [1, 2, 3])
    codes = []
    # L8 是主力连续（合成合约），price/volume准确但holding=0
    # 将L8放在第一位用于获取准确价格，后面月合约提供持仓量
    codes.append(f"{variety}L8.{suffix}")
    for offset in offsets:
        m = month + offset
        y = year
        if m > 12:
            m -= 12
            y += 1
        if exchange == "CZCE":
            ym = f"{y}{m:02d}"[-3:]
        else:
            ym = f"{y:02d}{m:02d}"
        codes.append(f"{variety}{ym}.{suffix}")
    return codes


import re

_PERIOD_BAR_MINUTES = {
    "1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
    "60m": 60, "120m": 120, "240m": 240,
    "1d": 1440, "1w": 10080, "1M": 43200,
}
_CUSTOM_PERIOD_RE = re.compile(r"^(\d+)m$")

def _period_to_count(days: int, period: str) -> int:
    """根据天数和K线周期估算需要的数据量（K线条数）"""
    p = period.lower()
    if p in _PERIOD_BAR_MINUTES:
        bar_min = _PERIOD_BAR_MINUTES[p]
    else:
        m = _CUSTOM_PERIOD_RE.match(p)
        bar_min = int(m.group(1)) if m else 1440  # 默认日线
    # 日线及以上：day/bar_min即可
    if bar_min >= 1440:
        rate = 1440 / bar_min
        return int(days * rate) + 50
    # 分钟线：按每天345分钟交易时间估算
    trading_min_per_day = 345
    count = days * trading_min_per_day // max(bar_min, 1) + 100
    return min(count, 2000)  # 上限2000


class TdxCollector:
    """通达信本地数据采集器 v2.0"""

    HTTP_URL = "http://127.0.0.1:17709/"
    TIMEOUT = 10

    def __init__(self):
        self._http_available = None

    # ==================== 基础服务 ====================

    @property
    def is_available(self) -> bool:
        if self._http_available is None:
            self._http_available = self._check_http_service()
        return self._http_available

    def reset_availability(self):
        self._http_available = None

    def _check_http_service(self) -> bool:
        try:
            req = urllib.request.Request(
                self.HTTP_URL,
                data=json.dumps({"id": 1, "method": "get_match_stkinfo", "params": {"key_word": "铜"}}).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                return "result" in json.loads(resp.read().decode("utf-8"))
        except Exception:
            return False

    def _call(self, method: str, params: dict) -> Optional[dict]:
        """发送JSON-RPC请求"""
        try:
            req = urllib.request.Request(
                self.HTTP_URL,
                data=json.dumps({"id": 1, "method": method, "params": params}).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("error"):
                    return None
                r = result.get("result")
                # 通用返回处理：ErrorId="0"为成功
                if isinstance(r, dict) and r.get("ErrorId") == "0":
                    return r
                return r
        except Exception:
            return None

    def _extract_kline(self, code: str, raw: dict) -> Optional[List[Dict]]:
        """从原始返回中提取K线数据"""
        data = raw.get("Value", {}).get(code, {})
        if not data or "Close" not in data:
            return None
        n = len(data["Date"])
        records = []
        for i in range(n):
            try:
                records.append(
                    {
                        "date": str(data["Date"][i]),
                        "open": float(data.get("Open", ["0"] * n)[i] or 0),
                        "high": float(data.get("High", ["0"] * n)[i] or 0),
                        "low": float(data.get("Low", ["0"] * n)[i] or 0),
                        "close": float(data.get("Close", ["0"] * n)[i] or 0),
                        "volume": int(float(data.get("Volume", ["0"] * n)[i] or 0)),
                        "oi": int(float(data.get("Hold", ["0"] * n)[i] or 0)),
                    }
                )
            except (ValueError, IndexError):
                continue
        return records if len(records) > 5 else None

    # ==================== 合约发现 ====================

    # 中文名称映射（用于搜索）
    CN_NAME_MAP = {
        "CU": "沪铜",
        "AL": "沪铝",
        "ZN": "沪锌",
        "PB": "沪铅",
        "NI": "沪镍",
        "SN": "沪锡",
        "AU": "沪金",
        "AG": "沪银",
        "RB": "螺纹",
        "HC": "热卷",
        "RU": "橡胶",
        "BR": "丁二烯橡胶",
        "FU": "燃油",
        "BU": "沥青",
        "SP": "纸浆",
        "SS": "不锈钢",
        "AO": "氧化铝",
        "WR": "线材",
        "OP": "双胶纸",
        "A": "豆一",
        "B": "豆二",
        "M": "豆粕",
        "Y": "豆油",
        "P": "棕榈",
        "C": "玉米",
        "CS": "淀粉",
        "I": "铁矿",
        "J": "焦炭",
        "JM": "焦煤",
        "L": "塑料",
        "V": "PVC",
        "PP": "聚丙烯",
        "EG": "乙二醇",
        "EB": "苯乙烯",
        "PG": "液化气",
        "JD": "鸡蛋",
        "LH": "生猪",
        "RR": "粳米",
        "FB": "纤维板",
        "AP": "苹果",
        "CF": "棉花",
        "CJ": "红枣",
        "FG": "玻璃",
        "SA": "纯碱",
        "MA": "甲醇",
        "TA": "PTA",
        "UR": "尿素",
        "PF": "短纤",
        "PR": "瓶片",
        "PX": "对二甲苯",
        "PK": "花生",
        "OI": "菜油",
        "RM": "菜粕",
        "SR": "白糖",
        "SF": "硅铁",
        "SM": "锰硅",
        "SH": "烧碱",
        "ZC": "动力煤",
        "SC": "原油",
        "LU": "低硫燃油",
        "NR": "20号胶",
        "BC": "国际铜",
        "EC": "欧线",
        "SI": "工业硅",
        "LC": "碳酸锂",
        "PS": "多晶硅",
        "IF": "沪深300",
        "IH": "上证50",
        "IC": "中证500",
        "IM": "中证1000",
        "T": "国债",
        "TF": "五年国债",
        "TS": "两年国债",
        "TL": "三十年国债",
    }

    def get_contract_list(self, variety: str) -> Optional[List[Dict]]:
        """
        搜索品种下所有可查合约（含连续合约）。

        通过 get_match_stkinfo 搜索返回全部合约月份，
        包括具体合约(CU2607.SHF)和连续合约(CUL7/CUL8/CUL9)。

        Returns:
            [{"code": "CU2607.SHF", "name": "沪铜2607", "type": "contract"},
             {"code": "CUL8.SHF", "name": "沪铜主连", "type": "continuous"}, ...]
        """
        if not self.is_available:
            return None

        keyword = self.CN_NAME_MAP.get(variety.upper(), variety)
        exchange = VARIETY_EXCHANGE.get(variety.upper(), "")
        result = self._call("get_match_stkinfo", {"key_word": keyword})
        if not result:
            return None

        items = result.get("Value", [])
        if isinstance(items, dict):
            items = [items]
        if not items or not isinstance(items, list):
            return None

        # 过滤出属于该品种的合约（code以品种标记开头）
        variety_up = variety.upper()
        contracts = []
        for item in items:
            code = item.get("Code", "")
            if not code.upper().startswith(variety_up):
                continue
            name = item.get("Name", "")
            # 判断类型：连续合约代码如 CUL8, CUL7, CUL9（品种+L+数字）
            base = code.split(".")[0]  # CUL8
            if len(base) > 2 and base[-2] == "L" and base[-1].isdigit():
                ctype = "continuous"
            else:
                ctype = "contract"
            contracts.append(
                {
                    "code": code,
                    "name": name,
                    "type": ctype,
                    "exchange": exchange,
                }
            )
        return contracts if contracts else None

    def get_continuous_code(self, variety: str, ctype: str = "main") -> Optional[str]:
        """获取连续合约代码"""
        suffix = CONTINUOUS_SUFFIX.get(ctype)
        if not suffix:
            return None
        exchange = VARIETY_EXCHANGE.get(variety.upper())
        ex_suffix = EXCHANGE_SUFFIX.get(exchange)
        if not ex_suffix:
            return None
        return f"{variety.upper()}{suffix}.{ex_suffix}"

    # ==================== 行情查询 ====================

    def get_quote(self, variety: str) -> Optional[List[Dict]]:
        """获取品种实时行情快照（自动选最优合约，L8优先获取价格）"""
        if not self.is_available:
            return None
        codes = _get_tdx_codes(variety)
        if not codes:
            return None
        for code in codes:
            result = self._call("get_market_snapshot", {"stock_code": code})
            if result and result.get("Now"):
                v = result
                return [
                    {
                        "code": code,
                        "variety": variety.upper(),
                        "price": float(v.get("Now", 0) or 0),
                        "open": float(v.get("Open", 0) or 0),
                        "high": float(v.get("Max", 0) or 0),
                        "low": float(v.get("Min", 0) or 0),
                        "close": float(v.get("LastClose", 0) or 0),
                        "volume": int(v.get("Volume", 0) or 0),
                        "holding": int(v.get("Holding", 0) or 0),
                        "data_source": "tdx_local",
                        "confidence": 1.0,
                    }
                ]
        return None

    def get_contract_quote(self, code: str) -> Optional[Dict]:
        """获取指定合约的实时行情快照"""
        result = self._call("get_market_snapshot", {"stock_code": code})
        if not result or not result.get("Now"):
            return None
        v = result
        return {
            "code": code,
            "price": float(v.get("Now", 0) or 0),
            "open": float(v.get("Open", 0) or 0),
            "high": float(v.get("Max", 0) or 0),
            "low": float(v.get("Min", 0) or 0),
            "close": float(v.get("LastClose", 0) or 0),
            "volume": int(v.get("Volume", 0) or 0),
            "holding": int(v.get("Holding", 0) or 0),
            "data_source": "tdx_local",
        }

    def get_all_contracts(self, variety: str) -> Optional[List[Dict]]:
        """
        获取品种下所有可查合约的行情快照。
        先通过 get_contract_list 发现全部合约，再逐一遍历获取行情。
        """
        contracts = self.get_contract_list(variety)
        if not contracts:
            return None

        records = []
        for c in contracts:
            q = self.get_contract_quote(c["code"])
            if q:
                records.append(
                    {
                        "code": c["code"].split(".")[0],
                        "full_code": c["code"],
                        "name": c["name"],
                        "type": c["type"],
                        "price": q["price"],
                        "open": q["open"],
                        "high": q["high"],
                        "low": q["low"],
                        "close": q["close"],
                        "volume": q["volume"],
                        "holding": q["holding"],
                    }
                )
        if not records:
            return None
        records.sort(key=lambda x: x["volume"], reverse=True)
        return records

    # ==================== K线查询 ====================

    def get_kline(self, variety: str, days: int = 365, period: str = "1d") -> Optional[List[Dict]]:
        """
        获取品种K线历史数据。

        Args:
            variety: 品种代码
            days: 获取天数（用于估算数据量）
            period: K线周期 "1d"(日) / "1w"(周) / "1m"(月) / "60m"(60分) / "240m"(4小时)
        """
        if not self.is_available:
            return None
        codes = _get_tdx_codes(variety)
        if not codes:
            return None

        count = _period_to_count(days, period)
        best, best_n = None, 0
        for code in codes:
            try:
                r = self._call(
                    "get_market_data",
                    {
                        "stock_list": [code],
                        "period": period,
                        "count": min(count, 2000),
                        "dividend_type": "none",
                    },
                )
                if r:
                    recs = self._extract_kline(code, r)
                    if recs and len(recs) > best_n:
                        best, best_n = recs, len(recs)
            except Exception:
                continue
        return best

    def get_contract_kline(self, code: str, days: int = 365, period: str = "1d") -> Optional[List[Dict]]:
        """
        获取指定合约的K线历史数据。

        Args:
            code: 完全代码，如 CU2607.SHF, CUL8.SHF
            days: 获取天数（用于估算数据量）
            period: K线周期 "1d"(日) / "1w"(周) / "1m"(月) / "60m"(60分) / "240m"(4小时)
        """
        if not self.is_available:
            return None
        count = _period_to_count(days, period)
        r = self._call(
            "get_market_data",
            {
                "stock_list": [code],
                "period": period,
                "count": min(count, 2000),
                "dividend_type": "none",
            },
        )
        if r:
            return self._extract_kline(code, r)
        return None

    def get_all_contracts_kline(self, variety: str, days: int = 250) -> Dict[str, List[Dict]]:
        """
        获取品种下所有合约的完整K线历史。

        自动发现全部合约后，批量获取K线数据。

        Returns:
            {"CU2607.SHF": [K-line], "CU2608.SHF": [K-line], ...,
             "CUL8.SHF": [K-line], ...}
        """
        contracts = self.get_contract_list(variety)
        if not contracts:
            return {}

        result = {}
        print(f"[TDX] 开始获取 {variety} 全部合约K线 ({len(contracts)}个合约)...")
        for i, c in enumerate(contracts):
            code = c["code"]
            klines = self.get_contract_kline(code, days=days)
            if klines:
                result[code] = klines
                print(f"  [{i + 1}/{len(contracts)}] [OK] {code}: {len(klines)}条K线")
            else:
                print(f"  [{i + 1}/{len(contracts)}] [x] {code}: 无数据")
        return result

    # ==================== 期限结构 ====================

    def get_term_structure(self, variety: str) -> Optional[Dict]:
        """
        计算品种的期限结构。

        通过 get_all_contracts 获取全部合约的实时价格，
        按月排序后计算近月-远月价差和斜率。

        Returns:
            {
                "variety": "CU",
                "time": "2026-06-29 20:00",
                "type": "Contango",        # Back / Contango / Flat
                "slope": 0.16,             # 斜率（%）
                "near_month": "2611",      # 近月合约
                "near_price": 102690,
                "far_month": "2706",       # 远月合约
                "far_price": 102850,
                "contracts": [
                    {"month": "2611", "code": "CU2611.SHF", "price": 102690, "volume": 100},
                    ...
                ],
                "data_source": "tdx_local",
            }
        """
        contracts = self.get_all_contracts(variety)
        if not contracts:
            return None

        # 过滤出具体合约（排除连续合约 + 价格无效合约）
        specific = [c for c in contracts if c["type"] == "contract" and c.get("price") and c["price"] > 0]
        if len(specific) < 2:
            # v2.0.1: 价格=0合约自动过滤，避免hc等品种远月无成交返回0
            return None

        # 按月排序（code格式如 HC2607.SHF）
        specific.sort(key=lambda x: x["code"])

        near = specific[0]
        far = specific[-1]
        near_price = near["price"]
        far_price = far["price"]

        if near_price > 0:
            slope = round((far_price - near_price) / near_price * 100, 2)
        else:
            slope = 0

        if slope < -0.1:
            ts_type = "Back"
        elif slope > 0.1:
            ts_type = "Contango"
        else:
            ts_type = "Flat"

        return {
            "variety": variety.upper(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": ts_type,
            "slope": slope,
            "near_month": near["code"][-4:],
            "near_price": near_price,
            "far_month": far["code"][-4:],
            "far_price": far_price,
            "contract_count": len(specific),
            "contracts": [
                {
                    "month": c["code"][-4:],
                    "code": c["full_code"],
                    "price": c["price"],
                    "volume": c["volume"],
                    "holding": c["holding"],
                }
                for c in specific
            ],
            "continuous": [
                {
                    "code": c["full_code"],
                    "name": c["name"],
                    "price": c["price"],
                    "volume": c["volume"],
                }
                for c in contracts
                if c["type"] == "continuous"
            ],
            "data_source": "tdx_local",
        }

    # ==================== 跨期价差 ====================

    def get_spread(
        self, variety: str, near_month: Optional[str] = None, far_month: Optional[str] = None
    ) -> Optional[Dict]:
        """
        计算跨期价差。

        默认近月为最近合约、远月为第二近合约。
        可指定合约月份（如 "2607", "2612"）。

        Returns:
            {
                "variety": "CU",
                "near_code": "CU2611.SHF", "near_price": 102690,
                "far_code": "CU2612.SHF", "far_price": 102750,
                "spread": -60,           # 价差 = 近 - 远
                "spread_pct": -0.058,   # 百分比
                "type": "Back",          # 近高远低=Back
                "data_source": "tdx_local",
            }
        """
        contracts = self.get_all_contracts(variety)
        if not contracts:
            return None

        specific = [c for c in contracts if c["type"] == "contract"]
        if len(specific) < 2:
            return None
        specific.sort(key=lambda x: x["code"])

        if near_month:
            near = next((c for c in specific if near_month in c["code"]), None)
        else:
            near = specific[0]

        if far_month:
            far = next((c for c in specific if far_month in c["code"]), None)
        else:
            far = specific[1] if len(specific) > 1 else specific[-1]

        if not near or not far:
            return None

        spread = near["price"] - far["price"]
        spread_pct = round(spread / far["price"] * 100, 3) if far["price"] else 0
        spread_type = "Back" if spread > 0 else ("Contango" if spread < 0 else "Flat")

        return {
            "variety": variety.upper(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "near_code": near["full_code"],
            "near_price": near["price"],
            "near_volume": near["volume"],
            "far_code": far["full_code"],
            "far_price": far["price"],
            "far_volume": far["volume"],
            "spread": round(spread, 2),
            "spread_pct": spread_pct,
            "type": spread_type,
            "data_source": "tdx_local",
        }

    def get_spread_history(self, variety: str, near_month: str, far_month: str, days: int = 60) -> Optional[Dict]:
        """
        获取跨期价差历史数据。

        获取近月和远月合约的历史K线，计算每日价差序列。

        Returns:
            {
                "variety": "CU",
                "near_code": "CU2611.SHF",
                "far_code": "CU2612.SHF",
                "history": [
                    {"date": "2026-06-01", "near_price": x, "far_price": y, "spread": z},
                    ...
                ],
                "current_spread": -60,
                "mean": -45.2,
                "std": 12.3,
                "z_score": -1.2,
                "data_source": "tdx_local",
            }
        """
        variety_up = variety.upper()
        exchange = VARIETY_EXCHANGE.get(variety_up)
        ex_suffix = EXCHANGE_SUFFIX.get(exchange) if exchange else "SHF"
        near_code = f"{variety_up}{near_month}.{ex_suffix}"
        far_code = f"{variety_up}{far_month}.{ex_suffix}"

        near_k = self.get_contract_kline(near_code, days=days)
        far_k = self.get_contract_kline(far_code, days=days)
        if not near_k or not far_k:
            return None

        # 构建日期字典
        near_map = {r["date"]: r for r in near_k}
        far_map = {r["date"]: r for r in far_k}
        dates = sorted(set(near_map.keys()) & set(far_map.keys()))

        history = []
        spreads = []
        for d in dates:
            np_ = near_map[d]["close"]
            fp_ = far_map[d]["close"]
            sp = np_ - fp_
            history.append(
                {
                    "date": d,
                    "near_price": np_,
                    "far_price": fp_,
                    "spread": round(sp, 2),
                }
            )
            spreads.append(sp)

        if not spreads:
            return None

        mean_ = sum(spreads) / len(spreads)
        std_ = (sum((s - mean_) ** 2 for s in spreads) / len(spreads)) ** 0.5 if len(spreads) > 1 else 0
        current = spreads[-1]
        z_ = round((current - mean_) / std_, 2) if std_ > 0 else 0

        return {
            "variety": variety_up,
            "near_code": near_code,
            "far_code": far_code,
            "near_month": near_month,
            "far_month": far_month,
            "history": history,
            "current_spread": round(current, 2),
            "mean": round(mean_, 2),
            "std": round(std_, 2),
            "z_score": z_,
            "min": min(spreads),
            "max": max(spreads),
            "data_source": "tdx_local",
        }

    # ==================== 技术指标计算 ====================

    def get_indicators(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        获取品种的技术指标（全部通过通达信 formula_zb 实盘公式直接获取）。

        覆盖指标（18组公式，通达信客户端100%一致）：
          趋势类: DMI(ADX/PDI/MDI)、MACD(DIF/DEA/柱)、MA(5/10/20/40/60)、BOLL(UB/中轨/LB)、TRIX、BBI
          震荡类: RSI、CCI、KDJ(K/D/J)、MFI、BIAS(6/12/24)、WR(W%R)
          量能类: OBV/MAOBV、VOL(量/5均/10均)、VR/MAVR
          波动类: ATR
          动量类: MTM/MTMMA
          其他:   PSY/PSYMA、ROC/MAROC、SAR、UOS

        不支持 formula_zb 直取的指标（需通过 TDX K线数据 numpy 计算）：
          SuperTrend、Vortex(VI±)、HMA、KAMA、Donchian

        Args:
            symbol: 品种代码（如 rb, cu, SA）

        Returns:
            {"adx": 59.3, "pdi": 8.5, "mdi": 38.3, "rsi": 31.6,
             "cci": -93.8, "macd_dif": -60.7, "macd_dea": -55.2, "macd_hist": -5.5,
             "ma1": 5740, "ma2": 5780, "ma3": 5850, "ma4": 5920, "ma5": 5980,
             "boll_upper": 6100, "boll_mid": 5921, "boll_lower": 5742,
             "obv": -591967, "obv_ma": -580000,
             "atr": 85.3, "kdj_k": 35.2, "kdj_d": 38.1, "kdj_j": 29.4,
             "mfi": 42.5, "roc": -1.23, "roc_ma": -0.45,
             "bias1": 0.32, "bias2": -0.15, "bias3": -0.08,
             "psy": 41.67, "psy_ma": 45.14,
             "vr": 65.32, "vr_ma": 72.18,
             "sar": 3125.0, "volume": 513567, "vol_ma5": 482300, "vol_ma10": 510200,
             "trix": 0.015, "trix_ma": 0.012,
             "wr1": 95.56, "wr2": 92.86,
             "bbi": 3150.5,
             "uos": 45.2, "uos_ma": 43.8,
             "mtm": -15.3, "mtm_ma": -8.7}
        """
        if not self.is_available:
            return None

        # 获取主力合约代码（通过 get_stock_list 实时映射，与通达信官方一致）
        try:
            r = self._call("get_stock_list", {"market": "92", "list_type": 1})
            if not r:
                return None
            futures = r.get("Value", [])
            tdx_code = None
            alpha = symbol.upper()
            for f in futures:
                code = f.get("Code", "")
                code_alpha = "".join(c for c in code.split(".")[0] if c.isalpha())
                if code_alpha.upper() == alpha:
                    tdx_code = code
                    break
            if not tdx_code:
                return None
        except Exception:
            return None

        # 设置公式数据上下文
        try:
            r = self._call(
                "formula_set_data_info",
                {
                    "stock_code": tdx_code,
                    "stock_period": "1d",
                    "count": 250,
                    "dividend_type": 0,
                },
            )
            if not r or r.get("ErrorId", "") != "0":
                return None
        except Exception:
            return None

        def _last_float(v):
            if v is None:
                return None
            if isinstance(v, (list, tuple)):
                # 从尾部查找第一个非空值（通达信公式返回数组尾部可能为None）
                for item in reversed(v):
                    if item is not None:
                        try:
                            return float(item)
                        except (ValueError, TypeError):
                            continue
                return None
            if isinstance(v, str):
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None
            return float(v)

        result = {}

        # ── 以下全部通过 TDX formula_zb 实盘公式直接获取 ──

        # DMI (14,6): ADX, PDI, MDI
        try:
            dmi = self._call("formula_zb", {"formula_name": "DMI", "formula_arg": "14,6", "xsflag": 2})
            if dmi:
                dmi_val = dmi.get("Value", {})
                result["adx"] = _last_float(dmi_val.get("ADX"))
                result["pdi"] = _last_float(dmi_val.get("PDI"))
                result["mdi"] = _last_float(dmi_val.get("MDI"))
        except Exception:
            pass

        # RSI (14)
        try:
            rsi = self._call("formula_zb", {"formula_name": "RSI", "formula_arg": "14,14", "xsflag": 2})
            if rsi:
                rsi_val = rsi.get("Value", {})
                result["rsi"] = _last_float(rsi_val.get("RSI1"))
        except Exception:
            pass

        # CCI
        try:
            cci = self._call("formula_zb", {"formula_name": "CCI", "formula_arg": "", "xsflag": 2})
            if cci:
                cci_val = cci.get("Value", {})
                result["cci"] = _last_float(cci_val.get("CCI"))
        except Exception:
            pass

        # MACD (12,26,9)
        try:
            macd = self._call("formula_zb", {"formula_name": "MACD", "formula_arg": "", "xsflag": 2})
            if macd:
                macd_val = macd.get("Value", {})
                result["macd_dif"] = _last_float(macd_val.get("DIF"))
                result["macd_dea"] = _last_float(macd_val.get("DEA"))
                result["macd_hist"] = _last_float(macd_val.get("MACD"))
        except Exception:
            pass

        # MA (5/10/20/40/60)
        try:
            ma = self._call("formula_zb", {"formula_name": "MA", "formula_arg": "", "xsflag": 2})
            if ma:
                ma_val = ma.get("Value", {})
                for i in range(1, 6):
                    v = _last_float(ma_val.get(f"MA{i}"))
                    if v is not None:
                        result[f"ma{i}"] = v
        except Exception:
            pass

        # BOLL (20,2)
        try:
            boll = self._call("formula_zb", {"formula_name": "BOLL", "formula_arg": "", "xsflag": 2})
            if boll:
                boll_val = boll.get("Value", {})
                result["boll_upper"] = _last_float(boll_val.get("UB"))
                result["boll_mid"] = _last_float(boll_val.get("BOLL"))
                result["boll_lower"] = _last_float(boll_val.get("LB"))
        except Exception:
            pass

        # OBV + MAOBV
        try:
            obv = self._call("formula_zb", {"formula_name": "OBV", "formula_arg": "", "xsflag": 2})
            if obv:
                obv_val = obv.get("Value", {})
                result["obv"] = _last_float(obv_val.get("OBV"))
                result["obv_ma"] = _last_float(obv_val.get("MAOBV"))
        except Exception:
            pass

        # ── 新增直接可取的指标 ──

        # ATR (14): 平均真实波幅
        try:
            atr = self._call("formula_zb", {"formula_name": "ATR", "formula_arg": "14", "xsflag": 2})
            if atr:
                atr_val = atr.get("Value", {})
                result["atr"] = _last_float(atr_val.get("ATR"))
        except Exception:
            pass

        # KDJ (9,3,3): 随机指标
        try:
            kdj = self._call("formula_zb", {"formula_name": "KDJ", "formula_arg": "9,3,3", "xsflag": 2})
            if kdj:
                kdj_val = kdj.get("Value", {})
                result["kdj_k"] = _last_float(kdj_val.get("K"))
                result["kdj_d"] = _last_float(kdj_val.get("D"))
                result["kdj_j"] = _last_float(kdj_val.get("J"))
        except Exception:
            pass

        # MFI (14): 资金流量指标
        try:
            mfi = self._call("formula_zb", {"formula_name": "MFI", "formula_arg": "14", "xsflag": 2})
            if mfi:
                mfi_val = mfi.get("Value", {})
                result["mfi"] = _last_float(mfi_val.get("MFI"))
        except Exception:
            pass

        # ROC (12): 变动率指标
        try:
            roc = self._call("formula_zb", {"formula_name": "ROC", "formula_arg": "12", "xsflag": 2})
            if roc:
                roc_val = roc.get("Value", {})
                result["roc"] = _last_float(roc_val.get("ROC"))
                result["roc_ma"] = _last_float(roc_val.get("MAROC"))
        except Exception:
            pass

        # BIAS (6,12,24): 乖离率
        try:
            bias = self._call("formula_zb", {"formula_name": "BIAS", "formula_arg": "6,12,24", "xsflag": 2})
            if bias:
                bias_val = bias.get("Value", {})
                result["bias1"] = _last_float(bias_val.get("BIAS1"))
                result["bias2"] = _last_float(bias_val.get("BIAS2"))
                result["bias3"] = _last_float(bias_val.get("BIAS3"))
        except Exception:
            pass

        # PSY (12): 心理线指标
        try:
            psy = self._call("formula_zb", {"formula_name": "PSY", "formula_arg": "12", "xsflag": 2})
            if psy:
                psy_val = psy.get("Value", {})
                result["psy"] = _last_float(psy_val.get("PSY"))
                result["psy_ma"] = _last_float(psy_val.get("PSYMA"))
        except Exception:
            pass

        # VR (26): 成交量变异率
        try:
            vr = self._call("formula_zb", {"formula_name": "VR", "formula_arg": "26", "xsflag": 2})
            if vr:
                vr_val = vr.get("Value", {})
                result["vr"] = _last_float(vr_val.get("VR"))
                result["vr_ma"] = _last_float(vr_val.get("MAVR"))
        except Exception:
            pass

        # SAR (4,2,20): 抛物线转向
        try:
            sar = self._call("formula_zb", {"formula_name": "SAR", "formula_arg": "4,2,20", "xsflag": 2})
            if sar:
                sar_val = sar.get("Value", {})
                result["sar"] = _last_float(sar_val.get("SAR"))
        except Exception:
            pass

        # VOL(5,10): 成交量 + 均量
        try:
            vol = self._call("formula_zb", {"formula_name": "VOL", "formula_arg": "5,10", "xsflag": 2})
            if vol:
                vol_val = vol.get("Value", {})
                result["volume"] = _last_float(vol_val.get("VOLUME"))
                result["vol_ma5"] = _last_float(vol_val.get("MAVOL1"))
                result["vol_ma10"] = _last_float(vol_val.get("MAVOL2"))
        except Exception:
            pass

        # TRIX (12,9): 三重指数平滑平均线
        try:
            trix = self._call("formula_zb", {"formula_name": "TRIX", "formula_arg": "12,9", "xsflag": 2})
            if trix:
                trix_val = trix.get("Value", {})
                result["trix"] = _last_float(trix_val.get("TRIX"))
                result["trix_ma"] = _last_float(trix_val.get("MATRIX"))
        except Exception:
            pass

        # WR (14): 威廉指标 W%R（通达信公式名 WR）
        try:
            wr = self._call("formula_zb", {"formula_name": "WR", "formula_arg": "14", "xsflag": 2})
            if wr:
                wr_val = wr.get("Value", {})
                result["wr1"] = _last_float(wr_val.get("WR1"))
                result["wr2"] = _last_float(wr_val.get("WR2"))
        except Exception:
            pass

        # BBI: 多空指标
        try:
            bbi = self._call("formula_zb", {"formula_name": "BBI", "formula_arg": "", "xsflag": 2})
            if bbi:
                bbi_val = bbi.get("Value", {})
                result["bbi"] = _last_float(bbi_val.get("BBI"))
        except Exception:
            pass

        # UOS (7,14,28): 终极指标
        try:
            uos = self._call("formula_zb", {"formula_name": "UOS", "formula_arg": "7,14,28", "xsflag": 2})
            if uos:
                uos_val = uos.get("Value", {})
                result["uos"] = _last_float(uos_val.get("UOS"))
                result["uos_ma"] = _last_float(uos_val.get("MAUOS"))
        except Exception:
            pass

        # MTM (12,6): 动量线
        try:
            mtm = self._call("formula_zb", {"formula_name": "MTM", "formula_arg": "12,6", "xsflag": 2})
            if mtm:
                mtm_val = mtm.get("Value", {})
                result["mtm"] = _last_float(mtm_val.get("MTM"))
                result["mtm_ma"] = _last_float(mtm_val.get("MTMMA"))
        except Exception:
            pass

        return result if result else None


# ==================== 快捷函数 ====================


def get_collector() -> TdxCollector:
    """获取单例采集器"""
    return TdxCollector()


if __name__ == "__main__":

    c = TdxCollector()
    if not c.is_available:
        print("[x] 通达信HTTP服务不可用")
        exit(1)

    print("=== 合约发现 ===")
    contracts = c.get_contract_list("CU")
    if contracts:
        for ct in contracts:
            print(f"  {ct['code']:15s} {ct['name']:10s} [{ct['type']}]")

    print("\n=== 期限结构 ===")
    ts = c.get_term_structure("CU")
    if ts:
        print(f"  类型: {ts['type']}, 斜率: {ts['slope']}%, 合约数: {ts['contract_count']}")
        print(f"  近月: {ts['near_month']}={ts['near_price']}, 远月: {ts['far_month']}={ts['far_price']}")
        for ct in ts["contracts"]:
            print(f"    {ct['code']:15s} price={ct['price']:>8} vol={ct['volume']:>8} oi={ct['holding']:>12}")

    print("\n=== 跨期价差 ===")
    sp = c.get_spread("CU")
    if sp:
        print(f"  {sp['near_code']} - {sp['far_code']} = {sp['spread']} ({sp['type']})")

    print("\n=== 价差历史 ===")
    sh = c.get_spread_history("CU", "2611", "2612", days=30)
    if sh:
        print(f"  当前: {sh['current_spread']}, 均值: {sh['mean']}, 标准差: {sh['std']}, Z分数: {sh['z_score']}")
        print(f"  最小: {sh['min']}, 最大: {sh['max']}")
        print(f"  历史: {len(sh['history'])}个交易日")

    print("\n=== 连续合约 ===")
    for ct in ["main", "sub", "index"]:
        code = c.get_continuous_code("CU", ct)
        if code:
            k = c.get_contract_kline(code, days=5)
            if k:
                print(f"  {code:15s}: {len(k)}条K线, 最新={k[-1]['close']}")
