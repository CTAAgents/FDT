# -*- coding: utf-8 -*-
"""
统一基本面数据采集器 v1.0

整合 FDC futures_data_core + 100ppi 期货基本面数据接口，为辩论探源/辩手/闫判官提供结构化数据。

数据源优先级:
  P0 仓单日报: FDC futures_data_core get_warrant (4交易所全覆盖)
  P1 库存数据: FDC futures_data_core get_fundamental + 生意社 spot_sys
  P2 持仓排名: AKShare get_rank_sum_daily + 各交易所排名API
  P3 交割数据: FDC futures_data_core get_fundamental
  P4 基差数据: 100ppi现期表(优先) + FDC futures_data_core get_basis(降级)

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

# FDC futures_data_core 替代 AKShare（仓单/库存/交割）
from futures_data_core import get_warrant as fdc_get_warrant

# ============================================================
# P0: 仓单日报采集
# ============================================================
def fetch_warehouse_all(date_str: str = None) -> Dict[str, WarehouseReceipt]:
    """
    通过FDC futures_data_core get_warrant + CZCE爬虫，返回统一格式。

    Args:
        date_str: 交易日期 YYYYMMDD, 默认今天

    Returns:
        {symbol_lower: WarehouseReceipt}
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    print(f"[fundamental] 采集仓单日报 ({date_str})...")
    results: Dict[str, WarehouseReceipt] = {}

    # ── FDC futures_data_core 统一仓单查询（替代原AKShare SHFE/DCE/GFEX） ──
    import asyncio

    async def _fetch_warrants_fdc():
        """逐品种、逐交易所通过FDC获取仓单数据"""
        fdc_out: Dict[str, WarehouseReceipt] = {}
        for exchange in ("SHFE", "DCE", "GFEX"):
            syms = [s for s, (ex, _, _) in EXCHANGE_MAP.items() if ex == exchange]
            if not syms:
                continue
            cnt = 0
            for s in syms:
                try:
                    payload = await fdc_get_warrant(s, exchange=exchange, trade_date=date_str)
                    if not payload or not payload.data:
                        continue
                    d = payload.data
                    total = d.get("total")
                    if total is None:
                        continue
                    wr = WarehouseReceipt(s, date_str)
                    wr.total_registered = int(total)
                    wr.daily_change = int(d.get("daily_change", 0) or 0)
                    wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
                    fdc_out[s.lower()] = wr
                    cnt += 1
                except Exception:
                    continue
            if cnt:
                print(f"  [{exchange}] 仓单解析: {cnt}品种")
        return fdc_out

    try:
        results.update(asyncio.run(_fetch_warrants_fdc()))
    except Exception as e:
        print(f"  [FDC] 仓单获取失败(降级到CZCE爬虫): {str(e)[:80]}")

    # 郑商所 — 盘后才发布当日数据, 盘中回退到前一日
    czce_date = date_str
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        test_url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{date_str[:4]}/{date_str}/FutureDataWhsheet.xlsx"
        r_test = __import__('requests').get(test_url, verify=False, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r_test.status_code != 200:
            czce_date = yesterday
    except Exception:
        czce_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    try:
        import requests as req
        from io import BytesIO
        xlsx_url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{czce_date[:4]}/{czce_date}/FutureDataWhsheet.xlsx"
        r = req.get(xlsx_url, verify=False, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200 and len(r.content) > 1000:
            czce_df = pd.read_excel(BytesIO(r.content), engine='openpyxl')
            # 找品种区域 (header格式: "品种：白糖SR     单位：张")
            variety_idx = czce_df[czce_df.iloc[:, 0].astype(str).str.contains(r'品种：', na=False)].index.tolist()
            czce_count = 0
            for i, idx in enumerate(variety_idx):
                header = str(czce_df.iloc[idx, 0])
                variety_match = __import__('re').search(r'品种：(\w+)', header)
                if not variety_match:
                    continue
                variety_code = variety_match.group(1)
                # CZCE格式: "菜粕RM" → 提取大写符号 "RM"
                sym_match = __import__('re').search(r'([A-Z]{1,3})$', variety_code)
                if sym_match:
                    sym = _variety_to_symbol(sym_match.group(1), exchange="CZCE")
                else:
                    sym = _variety_to_symbol(variety_code, exchange="CZCE")
                if not sym:
                    continue
                # CZCE: 每个品种有一个"总计"行 (col[5]=仓单数量, col[6]=当日增减)  
                # 注意: 棉纱CY等品种列位置不同, 用"总计"行而非"小计"行
                end_idx = variety_idx[i+1] if i+1 < len(variety_idx) else len(czce_df)
                section = czce_df.iloc[idx:end_idx]
                total_row = section[section.iloc[:, 0].astype(str).str.strip().eq('总计')]
                if total_row.empty:
                    continue
                # 列名匹配: 支持PTA(完税+保税双列)等特殊情况
                header_row = section.iloc[1]
                qty_cols = []; chg_col = None
                for c in range(9):
                    h = str(header_row.iloc[c]).strip()
                    if '仓单数量' in h:
                        qty_cols.append(c)
                    elif '当日增减' in h and chg_col is None:
                        chg_col = c
                try:
                    qty = sum(int(total_row.iloc[0, c]) for c in qty_cols if pd.notna(total_row.iloc[0, c]))
                    chg = int(total_row.iloc[0, chg_col]) if chg_col is not None and pd.notna(total_row.iloc[0, chg_col]) else 0
                except (ValueError, IndexError, TypeError):
                    continue
                if qty == 0:
                    continue
                wr = WarehouseReceipt(sym, czce_date)
                wr.total_registered = qty
                wr.daily_change = chg
                wr.daily_change_pct = _safe_pct(wr.daily_change, wr.total_registered)
                results[sym] = wr
                czce_count += 1
            print(f"  [CZCE] 仓单解析: {czce_count}品种")
    except Exception as e:
        print(f"  [CZCE] 仓单获取失败: {str(e)[:80]}")
    
    # ── 第二SHFE/DCE/GFEX回退: 已由上方 FDC 统一替代 ──

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
    print(f"[fundamental] 采集库存数据...")
    results = {}

    # FDC futures_data_core 库存查询（替代原AKShare futures_inventory_em）
    import asyncio
    from futures_data_core import get_fundamental as fdc_get_fundamental

    async def _fetch_inv_one(sym: str) -> dict:
        try:
            payload = await fdc_get_fundamental(sym, data_type="inventory")
            return payload.data if payload else {}
        except Exception:
            return {}

    for sym in symbols:
        inv_data = asyncio.run(_fetch_inv_one(sym))
        if inv_data:
            latest = inv_data.get("latest_stock") or inv_data.get("inventory")
            change = inv_data.get("stock_change") or inv_data.get("change")
            results[sym.lower()] = {
                "latest_stock": float(latest) if latest is not None else 0,
                "stock_change": float(change) if change is not None else 0,
                "data_source": inv_data.get("data_source", "FDC(基本面)"),
                "unit": inv_data.get("unit", "吨"),
            }

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
    """获取历史交割数据作为参考（FDC替代原AKShare futures_delivery_*）。"""
    print(f"[fundamental] 采集交割统计...")
    results = {}

    import asyncio
    from futures_data_core import get_fundamental as fdc_get_fundamental

    async def _fetch_delivery_one(sym: str) -> dict:
        try:
            payload = await fdc_get_fundamental(sym, data_type="delivery")
            return payload.data if payload else {}
        except Exception:
            return {}

    for sym in symbols:
        deliv_data = asyncio.run(_fetch_delivery_one(sym))
        if deliv_data:
            results[sym.lower()] = {
                "delivery_volume": float(deliv_data.get("delivery_volume", 0)),
                "data_source": deliv_data.get("data_source", "FDC(交割)"),
            }

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
        # 大小写不敏感仓库查找
        wr_key = sym_key
        if sym_key not in warehouse:
            # 尝试其他常见大小写变体
            for alt in [sym_key.upper(), sym_key.lower(), sym_key.capitalize()]:
                if alt in warehouse:
                    wr_key = alt
                    break
            else:
                # 遍历查找
                for k in warehouse:
                    if k.lower() == sym_key.lower():
                        wr_key = k
                        break
        wr = warehouse.get(wr_key)
        snap = {
            "symbol": sym_key,
            "trade_date": trade_date,
            "warehouse": _wr_to_friendly(wr),
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

    lines.append(f"*数据来源: FDC futures_data_core + 100ppi生意社 | 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
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
