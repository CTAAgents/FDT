#!/usr/bin/env python3
"""
东方财富期货数据采集器

通过东方财富公开HTTP API获取期货行情数据，作为futures-data-search技能的降级数据源。
优先级：交易所官方API > TqSdk > 东方财富API > AKShare

接口文档：
- 品种列表：GET https://push2.eastmoney.com/api/qt/clist/get
- 历史K线：GET https://push2his.eastmoney.com/api/qt/stock/kline/get
- 实时行情：GET https://push2.eastmoney.com/api/qt/clist/get
"""

import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests


# 东方财富市场分类
EXCHANGE_MAP = {
    8: "中金所",
    113: "上期所",
    114: "大商所",
    115: "郑商所",
    142: "上期能源",
    220: "中金所-股指/国债",
    225: "广期所",
}

# 默认请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
}


class EastMoneyCollector:
    """东方财富期货数据采集器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get_futures_base_info(self) -> Optional[List[Dict]]:
        """
        获取全市场期货品种基本信息

        Returns:
            [{"code": "CU", "name": "沪铜", "exchange": "上期所", "secid": "113.CU"}, ...]
        """
        params = {
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fields": "f1,f2,f3,f4,f12,f13,f14",
            "pn": "1",
            "pz": "500",
            "fid": "f3",
            "po": "1",
            "fs": "m:113,m:114,m:115,m:8,m:142,m:220,m:225",
            "forcect": "1",
        }

        try:
            resp = self.session.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("data") is None or result["data"].get("diff") is None:
                return None

            items = result["data"]["diff"]
            futures_list = []
            for item in items:
                exchange_id = item.get("f13")
                exchange = EXCHANGE_MAP.get(exchange_id, f"其他({exchange_id})")
                futures_list.append(
                    {
                        "code": item.get("f12", ""),
                        "name": item.get("f14", ""),
                        "exchange": exchange,
                        "secid": f"{exchange_id}.{item.get('f12', '')}",
                    }
                )

            return futures_list

        except Exception as e:
            print(f"[EastMoney] 获取品种信息失败: {e}")
            return None

    def get_kline_history(
        self,
        secid: str,
        beg: str = "20100101",
        end: Optional[str] = None,
        klt: int = 101,
        fqt: int = 1,
    ) -> Optional[List[Dict]]:
        """
        获取K线历史数据

        Args:
            secid: 品种secid，如 "113.CU2609"
            beg: 开始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD，默认今天
            klt: K线周期 1=1分钟 5=5分钟 15=15分钟 30=30分钟 60=60分钟 101=日线 102=周线
            fqt: 复权方式 0=不复权 1=前复权 2=后复权

        Returns:
            [{"date": "2026-06-27", "open": 78780, "close": 78850, ...}, ...]
        """
        if end is None:
            end = datetime.now().strftime("%Y%m%d")

        fields_map = {
            "f51": "date",
            "f52": "open",
            "f53": "close",
            "f54": "high",
            "f55": "low",
            "f56": "volume",
            "f57": "amount",
            "f58": "amplitude",
            "f59": "change_pct",
            "f60": "change",
            "f61": "turnover",
        }
        fields2 = ",".join(fields_map.keys())

        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": fields2,
            "beg": beg,
            "end": end,
            "rtntype": "6",
            "secid": secid,
            "klt": str(klt),
            "fqt": str(fqt),
        }

        try:
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urlencode(params)
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            result = resp.json()

            if result.get("data") is None or result["data"].get("klines") is None:
                return None

            klines = result["data"]["klines"]
            records = []
            for raw in klines:
                parts = raw.split(",")
                record = {}
                for i, field in enumerate(fields_map.keys()):
                    key = fields_map[field]
                    val = parts[i] if i < len(parts) else ""
                    # 数字字段转换
                    if key in ("open", "close", "high", "low", "change_pct", "change", "amplitude", "turnover"):
                        try:
                            record[key] = float(val)
                        except (ValueError, TypeError):
                            record[key] = 0.0
                    elif key in ("volume", "amount"):
                        try:
                            record[key] = int(float(val))
                        except (ValueError, TypeError):
                            record[key] = 0
                    else:
                        record[key] = val
                records.append(record)

            return records

        except Exception as e:
            print(f"[EastMoney] 获取K线失败 {secid}: {e}")
            return None

    def get_realtime_quote(
        self,
        variety: Optional[str] = None,
        exchange_code: Optional[int] = None,
    ) -> Optional[List[Dict]]:
        """
        获取实时行情快照

        Args:
            variety: 品种代码过滤（可选），如 "CU"
            exchange_code: 交易所代码过滤（可选），如 113

        Returns:
            [{"code": "cu2608", "name": "沪铜2608", "price": 102740, ...}, ...]
        """
        # 构建市场过滤条件
        markets = ["m:113", "m:114", "m:115", "m:8", "m:142", "m:220", "m:225"]
        if exchange_code:
            markets = [f"m:{exchange_code}"]
        fs = ",".join(markets) + " s:2048"

        params = {
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f24,f25",
            "pn": "1",
            "pz": "500",
            "fid": "f3",
            "po": "1",
            "fs": fs,
            "forcect": "1",
        }

        try:
            resp = self.session.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("data") is None or result["data"].get("diff") is None:
                return None

            items = result["data"]["diff"]
            quotes = []
            for item in items:
                code = item.get("f12", "")
                name = item.get("f14", "")

                # 品种过滤
                if variety and not code.lower().startswith(variety.lower()):
                    continue

                exchange_id = item.get("f13")
                quotes.append(
                    {
                        "code": code,
                        "name": name,
                        "exchange": EXCHANGE_MAP.get(exchange_id, f"其他({exchange_id})"),
                        "price": item.get("f2"),  # 最新价
                        "change_pct": item.get("f3"),  # 涨跌幅
                        "change": item.get("f4"),  # 涨跌额
                        "volume": item.get("f5"),  # 成交量
                        "oi": item.get("f6"),  # 持仓量
                        "open": item.get("f15"),  # 开盘价
                        "high": item.get("f17"),  # 最高价
                        "low": item.get("f16"),  # 最低价
                        "pre_close": item.get("f18"),  # 昨收
                        "amount": item.get("f20"),  # 成交额
                        "amplitude": item.get("f7"),  # 振幅
                    }
                )

            return quotes

        except Exception as e:
            print(f"[EastMoney] 获取实时行情失败: {e}")
            return None

    def get_contract_list(self, variety: str) -> Optional[List[Dict]]:
        """
        获取某一品种的合约列表

        Args:
            variety: 品种代码，如 "CU"

        Returns:
            [{"code": "CU2608", "name": "沪铜2608", "month": "2608", ...}, ...]
        """
        # 通过品种信息过滤
        all_quotes = self.get_realtime_quote(variety=variety)
        if not all_quotes:
            return None

        contracts = []
        for q in all_quotes:
            code = q["code"]
            # 过滤主连/次主连/指数
            if len(code) > 4 and code[-1] in ("m", "s", "i"):
                continue
            contracts.append(
                {
                    "code": code.upper(),
                    "name": q["name"],
                    "month": code[-4:] if len(code) >= 4 else "",
                    "last_price": q["price"],
                    "volume": q["volume"],
                    "oi": q["oi"],
                }
            )

        return contracts

    def get_term_structure(self, variety: str) -> Optional[Dict]:
        """
        从实时行情中提取期限结构（全部合约月份价格 → 期限结构斜率）

        Args:
            variety: 品种代码，如 CU, RB, SC

        Returns:
            {
                "variety": "CU",
                "near_month": "2706", "near_price": 102850,
                "far_month": "2612", "far_price": 102750,
                "slope": -0.10,        # 斜率（%），负=Back，正=Contango
                "type": "Back",         # Back / Contango / Flat
                "contracts": [{"month": "2706", "price": 102850, "oi": 38978250}, ...],
                "data_source": "eastmoney",
            }
        """
        quotes = self.get_realtime_quote(variety=variety)
        if not quotes or len(quotes) < 2:
            return None

        # 过滤出具体合约月份（排除指数/连续合约）
        contracts = []
        for q in quotes:
            code = q.get("code", "")
            # 跳过连续/指数合约（code以 m/s/i 结尾）
            if len(code) > 4 and code[-1] in ("m", "s", "i"):
                continue
            month = code[-4:] if len(code) >= 4 else ""
            if month.isdigit():
                contracts.append(
                    {
                        "month": month,
                        "price": q.get("price", 0),
                        "oi": q.get("oi", 0),
                    }
                )

        if len(contracts) < 2:
            return None

        # 按合约月份排序（近月 → 远月）
        contracts.sort(key=lambda x: x["month"])
        near = contracts[0]
        far = contracts[-1]

        # 计算期限结构斜率
        near_price = near["price"]
        far_price = far["price"]
        if near_price > 0:
            slope = round((far_price - near_price) / near_price * 100, 2)
        else:
            slope = 0

        # 判断类型
        if slope < -0.1:
            ts_type = "Back"
        elif slope > 0.1:
            ts_type = "Contango"
        else:
            ts_type = "Flat"

        return {
            "variety": variety.upper(),
            "near_month": near["month"],
            "near_price": near_price,
            "far_month": far["month"],
            "far_price": far_price,
            "slope": slope,
            "type": ts_type,
            "contract_count": len(contracts),
            "contracts": contracts,
            "data_source": "eastmoney",
        }


if __name__ == "__main__":
    collector = EastMoneyCollector()

    print("=" * 60)
    print("东方财富期货数据采集器测试")
    print("=" * 60)

    # 测试1：获取品种基本信息
    print("\n[测试1] 获取品种基本信息...")
    info = collector.get_futures_base_info()
    if info:
        print(f"  成功获取 {len(info)} 个品种")
        for item in info[:5]:
            print(f"  {item['code']:8s} {item['name']:10s} {item['exchange']}")
    else:
        print("  [x] 失败")

    # 测试2：获取实时行情
    print("\n[测试2] 获取实时行情（沪铜）...")
    quotes = collector.get_realtime_quote(variety="CU")
    if quotes:
        print(f"  成功获取 {len(quotes)} 条数据")
        for q in quotes[:3]:
            print(f"  {q['code']:12s} 最新价={q['price']}  涨幅={q['change_pct']}%  成交量={q['volume']}")
    else:
        print("  [x] 失败")

    # 测试3：获取K线历史
    print("\n[测试3] 获取K线历史（日线，CU2608）...")
    klines = collector.get_kline_history("113.cu2608", beg="20260601", klt=101)
    if klines:
        print(f"  成功获取 {len(klines)} 条K线")
        for k in klines[:3]:
            print(f"  {k['date']}  O={k['open']} H={k['high']} L={k['low']} C={k['close']} V={k['volume']}")
        print(f"  ...")
        for k in klines[-3:]:
            print(f"  {k['date']}  O={k['open']} H={k['high']} L={k['low']} C={k['close']} V={k['volume']}")
    else:
        print("  [x] 失败")

    # 测试4：获取合约列表
    print("\n[测试4] 获取合约列表（CU）...")
    contracts = collector.get_contract_list("CU")
    if contracts:
        print(f"  成功获取 {len(contracts)} 个合约")
        for c in contracts[:5]:
            print(f"  {c['code']:10s} 月={c['month']}  最新价={c['last_price']}")
    else:
        print("  [x] 失败")
