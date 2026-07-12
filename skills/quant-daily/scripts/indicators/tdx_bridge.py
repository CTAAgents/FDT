#!/usr/bin/env python3
"""
通达信TQ-Local指标桥接器 v1.1.0
=================================
优先委托 futures-data-search 的 TdxCollector.get_indicators() 获取
指标数据（单源真理原则），降级到本地 formula_zb 直连。

核心指标覆盖（18组公式，全部通达信实盘公式直取）：
  趋势类: DMI(ADX/PDI/MDI)、MACD(DIF/DEA/柱)、MA(5/10/20/40/60)、BOLL(UB/中轨/LB)、TRIX、BBI
  震荡类: RSI、CCI、KDJ(K/D/J)、MFI、BIAS(6/12/24)、WR(W%R)
  量能类: OBV/MAOBV、VOL(量/5均/10均)、VR/MAVR
  波动类: ATR
  动量类: MTM/MTMMA
  其他:   PSY/PSYMA、ROC/MAROC、SAR、UOS

不支持 formula_zb 直取（需通过 TDX K线数据 numpy 计算）：
  SuperTrend、Vortex(VI±)、HMA、KAMA、Donchian

用法:
  bridge = TDXBridge()
  if bridge.available:
      indicators = bridge.batch_get(['rb','hc','i',...])
      # indicators['rb'] = {'ADX':59.3, 'RSI':31.6, ...}
"""

import urllib.request
import json
import os
import sys
import time
from typing import Dict, List, Optional, Set

TQ_URL = "http://127.0.0.1:17709/"
TQ_TIMEOUT = 15  # seconds
CACHE_TTL = 300  # seconds

# ── 品种代码 → 通达信合约代码映射（运行时自动获取主力合约） ──


class TDXBridge:
    """通达信TQ-Local指标桥接器"""

    def __init__(self):
        self._available = None
        self._contract_map: Dict[str, str] = {}
        self._cache: Dict[str, dict] = {}
        self._cache_time: float = 0

    @property
    def available(self) -> bool:
        """检查TQ-Local是否可用（懒加载）"""
        if self._available is None:
            try:
                # 轻量探测：尝试加载合约列表
                self._load_contracts()
                self._available = len(self._contract_map) > 0
            except Exception:
                self._available = False
        return self._available

    def _call(self, method: str, params: dict) -> dict:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    TQ_URL,
                    data=json.dumps({"id": 1, "method": method, "params": params}).encode(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=TQ_TIMEOUT) as resp:
                    return json.loads(resp.read())
            except Exception:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise

    def _load_contracts(self) -> Dict[str, str]:
        """加载主力合约映射 {SM: SM2609.CZC, ...}"""
        if self._contract_map:
            return self._contract_map

        try:
            result = self._call("get_stock_list", {"market": "92", "list_type": 1})
            futures = result["result"]["Value"]
            for f in futures:
                code = f["Code"]  # "SM2609.CZC"
                alpha = "".join(c for c in code.split(".")[0] if c.isalpha())
                if alpha not in self._contract_map:
                    self._contract_map[alpha] = code
        except Exception:
            pass

        return self._contract_map

    def _get_tdx_code(self, symbol: str) -> Optional[str]:
        """symbol → TDX合约代码"""
        contracts = self._load_contracts()
        # 直接匹配大写
        alpha = symbol.upper()
        if alpha in contracts:
            return contracts[alpha]
        # 部分匹配（如sf→SF）
        for k, v in contracts.items():
            if k.upper() == alpha:
                return v
        return None

    def _set_data(self, tdx_code: str, count: int = 250) -> bool:
        """设置公式数据上下文"""
        try:
            r = self._call(
                "formula_set_data_info",
                {"stock_code": tdx_code, "stock_period": "1d", "count": count, "dividend_type": 0},
            )
            return r["result"].get("ErrorId", "") == "0"
        except Exception:
            return False

    def _query_formula(self, formula: str, arg: str = "") -> Optional[dict]:
        """查询单个公式"""
        try:
            r = self._call("formula_zb", {"formula_name": formula, "formula_arg": arg, "xsflag": 2})
            return r["result"]["Value"]
        except Exception:
            return None

    def get_single(self, symbol: str) -> Optional[dict]:
        time.sleep(0.05)  # 避免TQ-Local连接过载
        """获取单个品种的TDX指标

        优先委托 TdxCollector.get_indicators()（futures-data-search 单源），
        降级到本地 formula_zb 直连。

        Returns:
            {'adx':59.3, 'pdi':8.5, 'mdi':38.3, 'rsi':31.6,
             'cci':-93.8, 'macd_dif':-60.7, 'macd_dea':-55.2, 'macd_hist':-5.5,
             'ma5':5740, 'ma10':5780, 'ma20':5850, 'ma40':5920, 'ma60':5980,
             'boll_upper':6100, 'boll_mid':5921, 'boll_lower':5742,
             'obv':-591967, 'obv_ma':-580000}
        """
        # 0. 优先委托 TdxCollector（futures-data-search 单源，与 MSA 统一路由）
        try:
            from data.collectors.tdx_collector import TdxCollector

            tc = TdxCollector()
            if tc.is_available:
                ind = tc.get_indicators(symbol)
                if ind and len(ind) > 0:
                    return ind
        except Exception:
            pass

        # 1. 降级本地 formula_zb 直连
        tdx_code = self._get_tdx_code(symbol)
        if not tdx_code:
            return None

        if not self._set_data(tdx_code):
            return None

        result = {}

        # DMI (14,6)
        dmi = self._query_formula("DMI", "14,6")
        if dmi:
            result["adx"] = self._last_float(dmi.get("ADX"))
            result["pdi"] = self._last_float(dmi.get("PDI"))
            result["mdi"] = self._last_float(dmi.get("MDI"))

        # RSI (14)
        rsi = self._query_formula("RSI", "14,14")
        if rsi:
            result["rsi"] = self._last_float(rsi.get("RSI1"))

        # CCI
        cci = self._query_formula("CCI", "")
        if cci:
            result["cci"] = self._last_float(cci.get("CCI"))

        # MACD
        macd = self._query_formula("MACD", "")
        if macd:
            result["macd_dif"] = self._last_float(macd.get("DIF"))
            result["macd_dea"] = self._last_float(macd.get("DEA"))
            result["macd_hist"] = self._last_float(macd.get("MACD"))

        # MA
        ma = self._query_formula("MA", "")
        if ma:
            for i, key in enumerate(["ma1", "ma2", "ma3", "ma4", "ma5"], 1):
                v = self._last_float(ma.get(f"MA{i}"))
                result[key] = v

        # BOLL
        boll = self._query_formula("BOLL", "")
        if boll:
            result["boll_upper"] = self._last_float(boll.get("UB"))
            result["boll_mid"] = self._last_float(boll.get("BOLL"))
            result["boll_lower"] = self._last_float(boll.get("LB"))

        # OBV
        obv = self._query_formula("OBV", "")
        if obv:
            result["obv"] = self._last_float(obv.get("OBV"))
            result["obv_ma"] = self._last_float(obv.get("MAOBV"))

        return result

    def batch_get(self, symbols: List[str], refresh: bool = False) -> Dict[str, dict]:
        """批量获取品种指标（自动缓存）

        Args:
            symbols: 品种代码列表 ['rb','hc',...]
            refresh: 是否强制刷新缓存

        Returns:
            {symbol: {"adx":..., "rsi":..., ...}}
        """
        # 检查缓存
        if not refresh and self._cache and (time.time() - self._cache_time) < CACHE_TTL:
            # 过滤缓存中已有的
            missing = [s for s in symbols if s not in self._cache]
            if not missing:
                return {s: self._cache[s] for s in symbols if s in self._cache}
            symbols = missing

        if not self.available:
            return {}

        # 批量查询
        self._load_contracts()

        count = 0
        for i, sym in enumerate(symbols):
            try:
                result = self.get_single(sym)
                if result:
                    self._cache[sym] = result
                    count += 1
            except Exception:
                pass

        self._cache_time = time.time()
        return {s: self._cache.get(s) for s in symbols if s in self._cache}

    def patch_indicators(self, tech: dict, symbol: str) -> dict:
        """用TDX指标覆盖tech字典中的对应字段

        Args:
            tech: 现有的技术指标字典
            symbol: 品种代码

        Returns:
            {'patched': bool, 'count': int, 'fields': [...]}  覆盖状态
            tech自身被原地修改
        """
        status = {"patched": False, "count": 0, "fields": []}

        if not self.available:
            return status

        tdx = self.get_single(symbol)
        if not tdx:
            return status

        patched_fields = []

        # ── DMI/ADX 完全覆盖（numpy不可复刻） ──
        if tdx.get("adx") is not None:
            tech["ADX"] = tdx["adx"]
            patched_fields.append("ADX")
        if tdx.get("pdi") is not None:
            tech["DMI_PDI"] = tdx["pdi"]
            patched_fields.append("DMI_PDI")
        if tdx.get("mdi") is not None:
            tech["DMI_MDI"] = tdx["mdi"]
            patched_fields.append("DMI_MDI")

        # ── RSI ──
        if tdx.get("rsi") is not None:
            tech["RSI14"] = tdx["rsi"]
            patched_fields.append("RSI14")

        # ── CCI ──
        if tdx.get("cci") is not None:
            tech["CCI20"] = tdx["cci"]
            patched_fields.append("CCI20")

        # ── MACD ──
        if tdx.get("macd_dif") is not None:
            tech["MACD_DIF"] = tdx["macd_dif"]
            patched_fields.append("MACD_DIF")
        if tdx.get("macd_dea") is not None:
            tech["MACD_DEA"] = tdx["macd_dea"]
            patched_fields.append("MACD_DEA")
        if tdx.get("macd_hist") is not None:
            tech["MACD_HIST"] = tdx["macd_hist"]
            patched_fields.append("MACD_HIST")

        # ── MA ──
        for i, p in enumerate([5, 10, 20, 40, 60], 1):
            k = f"ma{i}"
            if tdx.get(k) is not None:
                tech[f"MA{p}"] = tdx[k]
                patched_fields.append(f"MA{p}")

        # ── BOLL ──
        if tdx.get("boll_upper") is not None:
            tech["BB_UPPER"] = tdx["boll_upper"]
            patched_fields.append("BB_UPPER")
            tech["BB_MIDDLE"] = tdx["boll_mid"]
            patched_fields.append("BB_MIDDLE")
            tech["BB_LOWER"] = tdx["boll_lower"]
            patched_fields.append("BB_LOWER")

        # ── OBV ──
        if tdx.get("obv") is not None:
            tech["OBV"] = tdx["obv"]
            patched_fields.append("OBV")

        # ── ATR ──
        if tdx.get("atr") is not None:
            tech["ATR"] = tdx["atr"]
            patched_fields.append("ATR")
            tech["ATR14"] = tdx["atr"]
            patched_fields.append("ATR14")  # 兼容numpy场名

        # ── KDJ ──
        if tdx.get("kdj_k") is not None:
            tech["KDJ_K"] = tdx["kdj_k"]
            patched_fields.append("KDJ_K")
            tech["KDJ_D"] = tdx["kdj_d"]
            patched_fields.append("KDJ_D")
            tech["KDJ_J"] = tdx["kdj_j"]
            patched_fields.append("KDJ_J")

        # ── MFI ──
        if tdx.get("mfi") is not None:
            tech["MFI"] = tdx["mfi"]
            patched_fields.append("MFI")

        # ── ROC ──
        if tdx.get("roc") is not None:
            tech["ROC"] = tdx["roc"]
            patched_fields.append("ROC")

        # ── BIAS ──
        if tdx.get("bias1") is not None:
            tech["BIAS1"] = tdx["bias1"]
            patched_fields.append("BIAS1")
            tech["BIAS2"] = tdx["bias2"]
            patched_fields.append("BIAS2")
            tech["BIAS3"] = tdx["bias3"]
            patched_fields.append("BIAS3")

        # ── PSY ──
        if tdx.get("psy") is not None:
            tech["PSY"] = tdx["psy"]
            patched_fields.append("PSY")

        # ── VR ──
        if tdx.get("vr") is not None:
            tech["VR"] = tdx["vr"]
            patched_fields.append("VR")

        # ── SAR ──
        if tdx.get("sar") is not None:
            tech["SAR"] = tdx["sar"]
            patched_fields.append("SAR")

        # ── VOL ──
        if tdx.get("volume") is not None:
            tech["VOLUME"] = tdx["volume"]
            patched_fields.append("VOLUME")

        # ── TRIX ──
        if tdx.get("trix") is not None:
            tech["TRIX"] = tdx["trix"]
            patched_fields.append("TRIX")

        # ── WR (Williams %R / W%R) ──
        if tdx.get("wr1") is not None:
            tech["WILLR"] = tdx["wr1"]
            patched_fields.append("WILLR")

        # ── BBI (多空指标) ──
        if tdx.get("bbi") is not None:
            tech["BBI"] = tdx["bbi"]
            patched_fields.append("BBI")

        # ── UOS (终极指标) ──
        if tdx.get("uos") is not None:
            tech["UOS"] = tdx["uos"]
            patched_fields.append("UOS")

        # ── MTM (动量线) ──
        if tdx.get("mtm") is not None:
            tech["MTM"] = tdx["mtm"]
            patched_fields.append("MTM")

        status["patched"] = len(patched_fields) > 0
        status["count"] = len(patched_fields)
        status["fields"] = patched_fields
        return status

    @staticmethod
    def _last_float(arr) -> Optional[float]:
        """安全提取数组最后一个有效值"""
        if not arr:
            return None
        for v in reversed(arr):
            if v is not None:
                return float(v)
        return None


# ── 模块级单例 ──
_bridge_instance = None


def get_bridge() -> TDXBridge:
    """获取全局TDXBridge单例"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = TDXBridge()
    return _bridge_instance


# ── CLI 测试 ──
if __name__ == "__main__":
    bridge = TDXBridge()
    print(f"TQ-Local可用: {bridge.available}")

    if bridge.available:
        # 测试单个
        r = bridge.get_single("SM")
        print(f"\nSM 通达信指标:")
        for k, v in r.items():
            print(f"  {k}: {v}")

        # 批量测试
        results = bridge.batch_get(["rb", "hc", "i", "j", "jm", "SF", "SM"])
        print(f"\n批量: {len(results)}/{7}")
        for sym, ind in results.items():
            print(f"  {sym}: ADX={ind.get('adx', '?'):.1f} RSI={ind.get('rsi', '?'):.1f}")
