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

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# 确保可以导入本地模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.spot_100ppi import fetch_ppi_data
from data.warehouse_receipt import EXCHANGE_MAP, WarehouseReceipt

from futures_data_core import get_position_ranking as fdc_get_position_ranking

# FDC futures_data_core 替代 AKShare（仓单/库存/交割/持仓排名）
from futures_data_core import get_warrant as fdc_get_warrant


# ============================================================
# P0: 仓单日报采集
# ============================================================
def fetch_warehouse_all(date_str: str = None) -> Dict[str, WarehouseReceipt]:
    """
    通过FDC futures_data_core get_warrant 统一获取全交易所仓单（SHFE/DCE/CZCE/GFEX）。
    之前 CZCE 的独立 Excel 爬虫已迁移到 FDC f10/warrant.py。

    Args:
        date_str: 交易日期 YYYYMMDD, 默认今天

    Returns:
        {symbol_lower: WarehouseReceipt}
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    print(f"[fundamental] 采集仓单日报(FDC统一) ({date_str})...")
    import asyncio

    async def _fetch_warrants_fdc():
        """逐品种、逐交易所通过FDC获取仓单数据（含CZCE）"""
        fdc_out: Dict[str, WarehouseReceipt] = {}
        # 所有交易所统一走FDC，CZCE Excel解析已内置在FDC warrant.py
        for exchange in ("SHFE", "DCE", "CZCE", "GFEX"):
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
                    wr = WarehouseReceipt(s, d.get("trade_date", date_str))
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
        results = asyncio.run(_fetch_warrants_fdc())
    except Exception as e:
        print(f"  [FDC] 统一仓单获取失败: {str(e)[:80]}")
        results = {}

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
    print("[fundamental] 采集库存数据...")
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
    获取期货持仓排名数据(FDC封装)，分析主力资金方向。

    Returns:
        {symbol: {total_oi, oi_change, top5_long, top5_short, net_position, signal}}
    """
    import asyncio

    print("[fundamental] 采集持仓排名(FDC)...")
    results = {}

    async def _fetch_one(sym: str) -> tuple:
        try:
            payload = await fdc_get_position_ranking(sym, days=30)
            if payload and payload.data:
                d = payload.data
                return (sym.lower(), d)
        except Exception:
            pass
        return (sym.lower(), None)

    try:
        tasks = [_fetch_one(sym) for sym in symbols]
        for future in asyncio.as_completed(tasks):
            sym, data = asyncio.run(future)
            # 简化为同步循环
            pass

        # 同步方式（as_completed 在 sync 环境不好用，用简单循环）
        results = {}
        for sym in symbols:
            try:
                payload = asyncio.run(fdc_get_position_ranking(sym, days=30))
                if payload and payload.data:
                    d = payload.data
                    net = d.get("net_long")
                    results[sym.lower()] = {
                        "total_oi": float(d.get("total_oi", 0)),
                        "long_volume": float(d.get("long_volume", 0)),
                        "short_volume": float(d.get("short_volume", 0)),
                        "net_long": float(net) if net is not None else None,
                        "data_source": d.get("data_source", "FDC(持仓排名)"),
                    }
            except Exception as e:
                print(f"  [WARN] {sym} 持仓排名失败: {str(e)[:60]}")
                continue
    except Exception as e:
        print(f"  [持仓] FDC get_position_ranking 整体失败: {str(e)[:80]}")

    print(f"  持仓采集完成: {len(results)}品种")
    return results


# ============================================================
# P3: 交割数据采集
# ============================================================
def fetch_delivery_stats(symbols: List[str]) -> Dict[str, dict]:
    """获取历史交割数据作为参考（FDC替代原AKShare futures_delivery_*）。"""
    print("[fundamental] 采集交割统计...")
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
