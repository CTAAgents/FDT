# -*- coding: utf-8 -*-
"""
统一基本面数据采集器 v1.0

整合 AKShare 全部期货基本面数据接口，为辩论探源/辩手/闫判官提供结构化数据。

数据源优先级:
  P0 仓单日报: AKShare futures_*_warehouse_receipt (4交易所全覆盖)
  P1 库存数据: AKShare futures_inventory_* + 生意社 spot_sys
  P2 持仓排名: AKShare get_rank_sum_daily + 各交易所排名API
  P3 交割数据: AKShare futures_delivery_*
  P4 基差数据: 100ppi现期表(优先) + AKShare futures_spot_price(降级)

输出格式: 每个品种一个 FundamentalSnapshot dict，包含:
  - warehouse: 仓单快照 (总量/日变化/月趋势/分位/信号)
  - inventory: 库存快照 (交易所库存/社会库存)
  - position: 持仓分析 (总持仓/OI变化/主力净多空)
  - basis: 基差快照 (现货价/基差率/方向)
  - delivery: 交割参考 (历史交割量/交割率)
"""

import sys
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

import pandas as pd
import numpy as np

# 确保可以导入本地模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.warehouse_receipt import (
    WarehouseReceipt, EXCHANGE_MAP, generate_debate_brief as warehouse_brief
)
from data.spot_100ppi import (
    fetch_ppi_data, calculate_basis, PPI_SYMBOL_MAP as PPI_MAP
)


# ============================================================
# P0: 仓单日报采集
# ============================================================
def fetch_warehouse_all(date_str: str = None) -> Dict[str, WarehouseReceipt]:
    """
    通过AKShare获取4个交易所仓单日报，返回统一格式。

    Args:
        date_str: 交易日期 YYYYMMDD, 默认今天

    Returns:
        {symbol_lower: WarehouseReceipt}
    """
    import akshare as ak

    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    print(f"[fundamental] 采集仓单日报 ({date_str})...")
    results: Dict[str, WarehouseReceipt] = {}

    def _try_fetch(exchange: str, fn, **kwargs):
        try:
            return fn(**kwargs)
        except Exception as e:
            print(f"  [{exchange}] 仓单获取失败: {str(e)[:80]}")
            return None

    # 上期所 — 尝试新版API
    shfe_date = date_str
    # 回退检测: 今日仓单可能在15:30后才能获取
    try:
        import requests as req
        test_url = f"https://tsite.shfe.com.cn/data/tradedata/future/dailydata/{date_str}dailystock.dat"
        r = req.get(test_url, timeout=5, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://tsite.shfe.com.cn/"})
        if r.status_code != 200 or len(r.text) < 100:
            yesterday = date.today() - timedelta(days=1)
            shfe_date = yesterday.strftime("%Y%m%d")
            print(f"  今日SHFE仓单未发布，尝试 {shfe_date}")
        else:
            print(f"  SHFE raw: {r.text[:60]}...")
    except Exception:
        yesterday = date.today() - timedelta(days=1)
        shfe_date = yesterday.strftime("%Y%m%d")

    shfe_data = _try_fetch("SHFE", ak.futures_shfe_warehouse_receipt, date=shfe_date)
    if shfe_data:
        for variety_name, df in shfe_data.items():
            sym = _variety_to_symbol(variety_name)
            if not sym:
                continue
            wr = WarehouseReceipt(sym, date_str)
            # 总计行
            total_row = df[df.iloc[:, 0].astype(str).str.contains("总计", na=False)]
            if not total_row.empty:
                try:
                    wr.total_registered = int(total_row.iloc[0, -2]) if len(total_row.columns) >= 2 else 0
                    wr.daily_change = int(total_row.iloc[0, -1]) if len(total_row.columns) >= 1 else 0
                except (ValueError, IndexError):
                    pass
            wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
            results[sym] = wr

    # 郑商所 — 使用 engine='openpyxl' 避免Excel格式错误
    czce_data = None
    try:
        import requests as req
        from io import BytesIO
        # 直接下载Excel, 绕过AKShare的引擎问题
        xlsx_url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{date_str[:4]}/{date_str}/FutureDataWhsheet.xlsx"
        r = req.get(xlsx_url, verify=False, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200 and len(r.content) > 1000:
            czce_df = pd.read_excel(BytesIO(r.content), engine='openpyxl')
            # 解析: 找到各品种区域
            variety_idx = czce_df[czce_df.iloc[:, 0].astype(str).str.contains(r'品种：', na=False)].index
            for i, idx in enumerate(variety_idx):
                header = czce_df.iloc[idx, 0]
                variety_match = __import__('re').search(r'品种：(\w+)', str(header))
                if not variety_match:
                    continue
                variety_code = variety_match.group(1)
                sym = _variety_to_symbol(variety_code, exchange="CZCE")
                if not sym:
                    continue
                # 找该品种的合计行
                end_idx = variety_idx[i+1] if i+1 < len(variety_idx) else len(czce_df)
                section = czce_df.iloc[idx:end_idx]
                total_row = section[section.iloc[:, 0].astype(str).str.contains('合计', na=False)]
                if total_row.empty:
                    continue
                wr = WarehouseReceipt(sym, date_str)
                try:
                    # 合计行: 仓单数量在"仓单数量"列, 当日增减在"当日增减"列
                    wr.total_registered = int(total_row.iloc[0, 5])  # 仓单数量
                    wr.daily_change = int(total_row.iloc[0, 6])      # 当日增减
                except (ValueError, IndexError):
                    continue
                wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
                results[sym] = wr
            print(f"  [CZCE] 仓单解析: {len([s for s in results if s in [r for r in results]])}品种")
    except Exception as e:
        print(f"  [CZCE] 仓单获取失败: {str(e)[:80]}")

    # 大商所
    dce_data = _try_fetch("DCE", ak.futures_warehouse_receipt_dce, date=date_str)
    if dce_data is not None and not dce_data.empty:
        # DCE格式: DataFrame含品种代码列
        for variety_code in dce_data["品种代码"].unique():
            sym = _variety_to_symbol(variety_code, exchange="DCE")
            if not sym:
                continue
            wr = WarehouseReceipt(sym, date_str)
            variety_df = dce_data[dce_data["品种代码"] == variety_code]
            wr.total_registered = int(variety_df["今日仓单量（手）"].sum())
            wr.daily_change = int(variety_df["增减（手）"].sum())
            wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
            results[sym] = wr

    # 广期所
    gfex_data = _try_fetch("GFEX", ak.futures_gfex_warehouse_receipt, date=date_str)
    if gfex_data:
        for symbol, df in gfex_data.items():
            sym = symbol.lower()
            wr = WarehouseReceipt(sym, date_str)
            if not df.empty:
                wr.total_registered = int(df["今日仓单量"].sum())
                wr.daily_change = int(df["增减"].sum())
                wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
            results[sym] = wr

    print(f"  仓单采集完成: {len(results)}品种")
    return results


# ============================================================
# P1: 库存数据采集
# ============================================================
def fetch_inventory(symbols: List[str], days: int = 60) -> Dict[str, dict]:
    """
    获取期货库存数据（交易所库存+社会库存）。

    Returns:
        {symbol: {latest_stock, stock_change, trend_30d, data_source}}
    """
    import akshare as ak

    print(f"[fundamental] 采集库存数据...")
    results = {}

    # 东方财富库存 (逐品种)
    try:
        for sym in symbols:
            try:
                # futures_inventory_em 使用小写字母品种代码
                em_df = ak.futures_inventory_em(symbol=sym.lower())
                if em_df is not None and not em_df.empty:
                    results[sym.lower()] = {
                        "latest_stock": float(em_df.iloc[0].get("库存", 0)),
                        "stock_change": float(em_df.iloc[0].get("增减", 0)),
                        "data_source": "东方财富(期货库存)",
                        "unit": "吨",
                    }
            except Exception:
                continue
    except Exception as e:
        print(f"  [库存] 东方财富失败: {str(e)[:60]}")

    # 99期货库存(补充)
    try:
        for sym in symbols[:5]:  # 限制频率，只补前5个
            try:
                df_99 = ak.futures_inventory_99(symbol=sym.upper())
                if df_99 is not None and not df_99.empty and sym.lower() not in results:
                    latest = df_99.iloc[-1]
                    results[sym.lower()] = {
                        "latest_stock": float(latest.get("库存量", 0)),
                        "stock_change": None,
                        "data_source": "99期货(大宗商品库存)",
                        "unit": "吨",
                    }
            except Exception:
                continue
    except Exception as e:
        print(f"  [库存] 99期货失败: {str(e)[:60]}")

    print(f"  库存采集完成: {len(results)}品种")
    return results


# ============================================================
# P2: 持仓排名采集
# ============================================================
def fetch_position_ranking(symbols: List[str]) -> Dict[str, dict]:
    """
    获取期货持仓排名数据，分析主力资金方向。

    Returns:
        {symbol: {total_oi, oi_change, top5_long, top5_short, net_position, signal}}
    """
    import akshare as ak

    print(f"[fundamental] 采集持仓排名...")
    results = {}

    try:
        # 获取全品种汇总排名 (API使用 start_day/end_day)
        rank_df = ak.get_rank_sum_daily(
            start_day=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
            end_day=datetime.now().strftime("%Y%m%d"),
            vars_list=[s.upper() for s in symbols]
        )
        if rank_df is not None and not rank_df.empty:
            for sym in symbols:
                sym_upper = sym.upper()
                sym_rows = rank_df[rank_df["variety"].str.upper() == sym_upper]
                if sym_rows.empty:
                    continue
                latest = sym_rows.iloc[-1]
                long_vol = float(latest.get("long_position", latest.get("vol", 0)))
                short_vol = float(latest.get("short_position", 0))
                results[sym.lower()] = {
                    "total_oi": float(latest.get("open_interest", 0)),
                    "long_volume": long_vol,
                    "short_volume": short_vol,
                    "net_long": long_vol - short_vol if long_vol and short_vol else None,
                    "data_source": "AKShare(会员持仓排名)",
                }
    except Exception as e:
        print(f"  [持仓] get_rank_sum_daily失败: {str(e)[:80]}")
        # 降级: 逐品种从交易所API获取
        print("  尝试逐品种获取...")
        try:
            shfe_rank = ak.get_shfe_rank_table(date=datetime.now().strftime("%Y%m%d"))
            if shfe_rank is not None:
                for sym in symbols:
                    sym_upper = sym.upper()
                    for key in shfe_rank:
                        if sym_upper in str(key).upper():
                            df = shfe_rank[key]
                            if isinstance(df, pd.DataFrame) and not df.empty:
                                results[sym.lower()] = {
                                    "total_oi": len(df),
                                    "data_source": "SHFE(持仓排名)",
                                }
        except Exception:
            pass

    print(f"  持仓采集完成: {len(results)}品种")
    return results


# ============================================================
# P3: 交割数据采集
# ============================================================
def fetch_delivery_stats(symbols: List[str]) -> Dict[str, dict]:
    """获取历史交割数据作为参考。"""
    import akshare as ak

    print(f"[fundamental] 采集交割统计...")
    results = {}

    for exchange_name, fn in [
        ("SHFE", ak.futures_delivery_shfe),
        ("CZCE", ak.futures_delivery_czce),
        ("DCE", ak.futures_delivery_dce),
    ]:
        try:
            data = fn()
            if data is None:
                continue
            for sym in symbols:
                sym_upper = sym.upper()
                if isinstance(data, pd.DataFrame) and not data.empty:
                    sym_rows = data[data.iloc[:, 0].astype(str).str.upper() == sym_upper]
                    if not sym_rows.empty:
                        latest = sym_rows.iloc[-1]
                        results[sym.lower()] = {
                            "delivery_volume": float(latest.iloc[1]) if len(latest) > 1 else None,
                            "data_source": f"{exchange_name}(交割统计)",
                        }
        except Exception as e:
            print(f"  [交割] {exchange_name}失败: {str(e)[:60]}")

    print(f"  交割采集完成: {len(results)}品种")
    return results


# ============================================================
# 统一入口: 基本面全景快照
# ============================================================
def fetch_all_fundamentals(
    symbols: List[str],
    trade_date: str = None,
    include_ppi: bool = True,
) -> Dict[str, dict]:
    """
    统一基本面数据采集入口。一次调用获取所有基本面维度。

    Args:
        symbols: 品种代码列表
        trade_date: 交易日期 YYYYMMDD
        include_ppi: 是否包含100ppi现货基准价

    Returns:
        {symbol_lower: FundamentalSnapshot}
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"统一基本面数据采集 v1.0 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"品种: {len(symbols)} | 日期: {trade_date}")
    print(f"{'='*60}\n")

    # P0: 仓单
    warehouse = fetch_warehouse_all(trade_date)

    # P1: 库存
    inventory = fetch_inventory(symbols)

    # P2: 持仓排名
    position = fetch_position_ranking(symbols)

    # P3: 交割
    delivery = fetch_delivery_stats(symbols)

    # P4: 100ppi现货基准价
    ppi_data = {}
    if include_ppi:
        try:
            ppi_result = fetch_ppi_data(symbols)
            ppi_data = ppi_result.get("items", {}) if ppi_result else {}
        except Exception as e:
            print(f"  [现货] 100ppi获取失败: {str(e)[:60]}")

    # 组装
    snapshots = {}
    for sym in symbols:
        sym_key = sym.lower() if isinstance(sym, str) else sym
        snap = {
            "symbol": sym_key,
            "trade_date": trade_date,
            "warehouse": _wr_to_friendly(warehouse.get(sym_key)),
            "inventory": inventory.get(sym_key),
            "position": position.get(sym_key),
            "delivery": delivery.get(sym_key),
            "spot_ppi": ppi_data.get(sym_key),
        }
        snapshots[sym_key] = snap

    # 统计
    wr_count = sum(1 for s in snapshots.values() if s["warehouse"] is not None)
    inv_count = sum(1 for s in snapshots.values() if s["inventory"] is not None)
    pos_count = sum(1 for s in snapshots.values() if s["position"] is not None)
    ppi_count = sum(1 for s in snapshots.values() if s["spot_ppi"] is not None)

    print(f"\n{'='*60}")
    print(f"采集完成: 仓单{wr_count} | 库存{inv_count} | 持仓{pos_count} | 现货{ppi_count}")
    print(f"{'='*60}\n")

    return snapshots


def generate_fundamental_brief(snapshots: Dict[str, dict], for_debate: bool = True) -> str:
    """
    生成基本面分析素材摘要(Markdown)，可直接注入辩手/闫判官上下文。

    Args:
        snapshots: fetch_all_fundamentals() 的返回
        for_debate: 是否使用辩论友好格式(含信号解读)

    Returns:
        Markdown文本
    """
    lines = ["## 基本面数据全景", ""]

    for sym, snap in sorted(snapshots.items()):
        lines.append(f"### {sym.upper()}")
        lines.append("")

        # 仓单
        wr = snap.get("warehouse")
        if wr:
            tr = wr.get('total_registered', 0)
            dc = wr.get('daily_change', 0)
            mcp = wr.get('month_change_pct')
            un = wr.get('unit', '吨')
            lines.append(f"**仓单**: 注册{tr:,}{un} | 日{dc:+,} | ")
            if mcp:
                lines.append(f"月{mcp:+.1f}% | ")
            if wr.get("signal"):
                sig = wr["signal"]
                icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(sig["direction"], "")
                lines.append(f"信号: {icon} **{sig['direction']}** ({sig['strength']})")
            lines.append("")
            if wr.get("risk_flags"):
                for flag in wr["risk_flags"]:
                    lines.append(f"  - {flag}")
            lines.append("")

        # 现货/基差
        spot = snap.get("spot_ppi")
        if spot:
            lines.append(f"**现货**(100ppi): {spot.get('spot_converted', '?')} | "
                        f"基差: {spot.get('basis', '?')} ({spot.get('basis_rate_pct', '?')}%) | "
                        f"{spot.get('basis_direction', '')}")
            lines.append("")

        # 库存
        inv = snap.get("inventory")
        if inv:
            lines.append(f"**库存**({inv.get('data_source','')}): "
                        f"{inv.get('latest_stock','?')} {inv.get('unit','吨')}")
            if inv.get("stock_change"):
                lines.append(f" (日{inv['stock_change']:+,})")
            lines.append("")

        # 持仓
        pos = snap.get("position")
        if pos:
            net = pos.get("net_long")
            if net is not None:
                direction = "净多" if net > 0 else "净空" if net < 0 else "均衡"
                lines.append(f"**持仓**: 总OI {pos.get('total_oi','?')} | "
                            f"主力{direction} {abs(net):,.0f}手")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append(f"*数据来源: AKShare + 100ppi生意社 | 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(lines)


# ============================================================
# 工具函数
# ============================================================
def _variety_to_symbol(name: str, exchange: str = "") -> Optional[str]:
    """品种名称→代码映射。如 '纸浆'→'sp', 'PTA'→'TA'"""
    # 直接匹配
    name_upper = name.strip().upper()
    for sym, (ex, vname, _) in EXCHANGE_MAP.items():
        if vname.upper() == name_upper:
            return sym
        if sym.upper() == name_upper:
            return sym
    # 模糊匹配
    name_map = {
        "纸浆": "sp", "铜": "cu", "铝": "al", "锌": "zn", "铅": "pb",
        "镍": "ni", "锡": "sn", "黄金": "au", "白银": "ag",
        "螺纹钢": "rb", "热轧卷板": "hc", "不锈钢": "ss",
        "燃料油": "fu", "沥青": "bu", "天然橡胶": "ru",
        "PTA": "TA", "甲醇": "MA", "纯碱": "SA", "玻璃": "FG",
        "尿素": "UR", "棉花": "CF", "白糖": "SR",
        "菜油": "OI", "菜粕": "RM", "短纤": "PF",
        "对二甲苯": "PX", "瓶片": "PR",
        "豆粕": "m", "豆油": "y", "豆一": "a", "豆二": "b",
        "棕榈油": "p", "玉米": "c", "鸡蛋": "jd", "生猪": "lh",
        "塑料": "l", "聚丙烯": "pp", "PVC": "v",
        "乙二醇": "eg", "苯乙烯": "eb", "液化气": "pg",
        "铁矿石": "i", "焦炭": "j", "焦煤": "jm",
        "工业硅": "si", "碳酸锂": "lc", "多晶硅": "ps",
        "原油": "sc", "低硫燃油": "lu", "集运指数": "ec",
        "丁二烯橡胶": "br", "氧化铝": "ao",
        "硅铁": "SF", "锰硅": "SM", "烧碱": "SH",
        "花生": "PK", "苹果": "AP", "红枣": "CJ",
    }
    return name_map.get(name.strip())


def _safe_pct(change, base) -> Optional[float]:
    """安全计算百分比"""
    if change is None or base is None or base == 0:
        return None
    return round(change / base * 100, 2)


def _wr_to_friendly(wr) -> Optional[dict]:
    """将 WarehouseReceipt 转为辩论友好格式"""
    if wr is None:
        return None
    signal = wr.get_signal() if hasattr(wr, 'get_signal') else {}
    return {
        "total_registered": wr.total_registered,
        "daily_change": wr.daily_change,
        "daily_change_pct": wr.daily_change_pct,
        "month_change_pct": wr.month_change_pct,
        "percentile_1y": wr.percentile_1y,
        "unit": wr.unit,
        "signal": signal,
        "risk_flags": signal.get("risk_flags", []),
    }


# ============================================================
# CLI
# ============================================================
def main():
    import sys

    symbols = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        symbols = [s.strip() for s in sys.argv[1].split(",")]

    if symbols is None:
        # 默认: 扫描品种
        symbols = ["SP", "RM", "SN", "FG", "NI", "AL", "TA", "MA", "SA", "CF", "M", "Y"]

    snapshots = fetch_all_fundamentals(symbols)

    # 输出辩论素材
    brief = generate_fundamental_brief(snapshots)
    print(brief)

    # 可选: 输出JSON
    if "-o" in sys.argv:
        import json
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            output = {}
            for sym, snap in snapshots.items():
                # 清理不可序列化对象
                clean = {}
                for k, v in snap.items():
                    if isinstance(v, dict):
                        clean[k] = {kk: vv for kk, vv in v.items() if not callable(vv)}
                    else:
                        clean[k] = v
                output[sym] = clean
            with open(sys.argv[idx + 1], "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n[OK] JSON输出: {sys.argv[idx + 1]}")


if __name__ == "__main__":
    main()
