# -*- coding: utf-8 -*-
"""
期限结构与基差分析模块 v1.0
数据源：
  - 期限结构：futures-data-search DuckDB（futures-data-search内置，原exchange-futures-data）
  - 现货价格：AKShare（降级源，置信度-20%）

输出：per-symbol dict，含 term_structure / basis_rate / basis_signal
供 run_pipeline.py 调用，注入到品种信号中参与置信度计算。
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ============================================================
# 现货价格映射：品种代码 → AKShare symbol + 现货名称
# 覆盖主流能化、黑色、有色、农产品品种
# ============================================================
SPOT_PRICE_MAP: Dict[str, dict] = {
    # 黑色系
    "rb": {"ak_symbol": "rb0", "spot_name": "螺纹钢"},
    "hc": {"ak_symbol": "hc0", "spot_name": "热轧板卷"},
    "i": {"ak_symbol": "i0", "spot_name": "铁矿石"},
    "j": {"ak_symbol": "j0", "spot_name": "焦炭"},
    "jm": {"ak_symbol": "jm0", "spot_name": "焦煤"},
    "SF": {"ak_symbol": "SF0", "spot_name": "硅铁"},
    "SM": {"ak_symbol": "SM0", "spot_name": "锰硅"},
    # 能源链
    "sc": {"ak_symbol": "sc0", "spot_name": "原油"},
    "lu": {"ak_symbol": "lu0", "spot_name": "低硫燃油"},
    "fu": {"ak_symbol": "fu0", "spot_name": "燃料油"},
    "bu": {"ak_symbol": "bu0", "spot_name": "沥青"},
    "pg": {"ak_symbol": "pg0", "spot_name": "液化气"},
    # 聚酯链
    "TA": {"ak_symbol": "TA0", "spot_name": "PTA"},
    "PF": {"ak_symbol": "PF0", "spot_name": "短纤"},
    "PX": {"ak_symbol": "PX0", "spot_name": "对二甲苯"},
    "PR": {"ak_symbol": "PR0", "spot_name": "瓶片"},
    # 油化工
    "eg": {"ak_symbol": "eg0", "spot_name": "乙二醇"},
    "eb": {"ak_symbol": "eb0", "spot_name": "苯乙烯"},
    "v": {"ak_symbol": "v0", "spot_name": "PVC"},
    "pp": {"ak_symbol": "pp0", "spot_name": "聚丙烯"},
    "l": {"ak_symbol": "l0", "spot_name": "塑料"},
    # 煤化工
    "MA": {"ak_symbol": "MA0", "spot_name": "甲醇"},
    "SH": {"ak_symbol": "SH0", "spot_name": "烧碱"},
    # 有色
    "cu": {"ak_symbol": "cu0", "spot_name": "铜"},
    "al": {"ak_symbol": "al0", "spot_name": "铝"},
    "zn": {"ak_symbol": "zn0", "spot_name": "锌"},
    "pb": {"ak_symbol": "pb0", "spot_name": "铅"},
    "ni": {"ak_symbol": "ni0", "spot_name": "镍"},
    "sn": {"ak_symbol": "sn0", "spot_name": "锡"},
    "ao": {"ak_symbol": "ao0", "spot_name": "氧化铝"},
    "SS": {"ak_symbol": "SS0", "spot_name": "不锈钢"},
    # 贵金属
    "au": {"ak_symbol": "au0", "spot_name": "黄金"},
    "ag": {"ak_symbol": "ag0", "spot_name": "白银"},
    # 油脂油料
    "a": {"ak_symbol": "a0", "spot_name": "豆一"},
    "b": {"ak_symbol": "b0", "spot_name": "豆二"},
    "m": {"ak_symbol": "m0", "spot_name": "豆粕"},
    "y": {"ak_symbol": "y0", "spot_name": "豆油"},
    "p": {"ak_symbol": "p0", "spot_name": "棕榈油"},
    "OI": {"ak_symbol": "OI0", "spot_name": "菜油"},
    "RM": {"ak_symbol": "RM0", "spot_name": "菜粕"},
    "PK": {"ak_symbol": "PK0", "spot_name": "花生"},
    # 谷物软商品
    "c": {"ak_symbol": "c0", "spot_name": "玉米"},
    "cs": {"ak_symbol": "cs0", "spot_name": "淀粉"},
    "SR": {"ak_symbol": "SR0", "spot_name": "白糖"},
    "CF": {"ak_symbol": "CF0", "spot_name": "棉花"},
    "jd": {"ak_symbol": "jd0", "spot_name": "鸡蛋"},
    "lh": {"ak_symbol": "lh0", "spot_name": "生猪"},
    "AP": {"ak_symbol": "AP0", "spot_name": "苹果"},
    "CJ": {"ak_symbol": "CJ0", "spot_name": "红枣"},
    # 建材
    "FG": {"ak_symbol": "FG0", "spot_name": "玻璃"},
    "SA": {"ak_symbol": "SA0", "spot_name": "纯碱"},
    "UR": {"ak_symbol": "UR0", "spot_name": "尿素"},
    # 橡胶
    "ru": {"ak_symbol": "ru0", "spot_name": "橡胶"},
    "nr": {"ak_symbol": "nr0", "spot_name": "20号胶"},
    "br": {"ak_symbol": "br0", "spot_name": "丁二烯橡胶"},
    # 纸浆
    "sp": {"ak_symbol": "sp0", "spot_name": "纸浆"},
    # 新品种
    "lc": {"ak_symbol": "lc0", "spot_name": "碳酸锂"},
    "si": {"ak_symbol": "si0", "spot_name": "工业硅"},
    "ps": {"ak_symbol": "ps0", "spot_name": "多晶硅"},
    "ec": {"ak_symbol": "ec0", "spot_name": "集运指数"},
}


def _fetch_spot_prices_akshare(trade_date: str = None) -> Dict[str, float]:
    """
    通过AKShare获取现货价格。
    API: futures_spot_price(date='YYYYMMDD', vars_list=['AL','CU',...])
    返回 {symbol_lower: spot_price}，如 {'rb': 3520, 'i': 780, ...}
    注意：AKShare是降级数据源，调用失败返回空dict。
    """
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        print("[term_basis] AKShare未安装，跳过现货价格获取")
        return {}

    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    spot_prices = {}

    try:
        print(f"[term_basis] 正在通过AKShare获取现货价格({trade_date})...")

        # 构建vars_list：从SPOT_PRICE_MAP提取ak_symbol并转换为大写品种代码
        vars_list = []
        pid_to_spot_symbol = {}
        for pid, info in SPOT_PRICE_MAP.items():
            # futures_spot_price的vars_list使用大写品种代码如 AL, CU, RB
            spot_symbol = pid.upper()
            vars_list.append(spot_symbol)
            pid_to_spot_symbol[pid.lower()] = spot_symbol

        # AKShare批量接口: futures_spot_price(date, vars_list)
        df = ak.futures_spot_price(date=trade_date, vars_list=vars_list)

        if df is not None and not df.empty:
            print(f"  AKShare现货返回 {len(df)} 行, columns={df.columns.tolist()[:8]}")

            # 列结构: date, symbol, spot_price, near_contract, near_contract_price, ...
            for _, row in df.iterrows():
                spot_symbol = str(row.get("symbol", "")).strip().upper()
                spot_price = row.get("spot_price", None)

                if spot_price is None or pd.isna(spot_price):
                    # 尝试其他列名
                    for col in ["现货价", "价格", "price", "value"]:
                        if col in df.columns:
                            spot_price = row.get(col)
                            if spot_price is not None and not pd.isna(spot_price):
                                break

                if spot_price is not None and not pd.isna(spot_price) and float(spot_price) > 0:
                    # 反向映射：spot_symbol (如 'AL') → pid_lower (如 'al')
                    for pid_lower, ss in pid_to_spot_symbol.items():
                        if ss == spot_symbol:
                            spot_prices[pid_lower] = float(spot_price)
                            break
        else:
            print("  AKShare现货返回空数据")

    except Exception as e:
        print(f"  [WARN] AKShare批量现货获取失败: {str(e)[:100]}")
        # 降级：逐品种查询
        print("  尝试逐品种查询...")
        for pid, info in SPOT_PRICE_MAP.items():
            try:
                spot_symbol = pid.upper()
                df_spot = ak.futures_spot_price(date=trade_date, vars_list=[spot_symbol])
                if df_spot is not None and not df_spot.empty:
                    spot_price = df_spot.iloc[0].get("spot_price")
                    if spot_price is not None and not pd.isna(spot_price) and float(spot_price) > 0:
                        spot_prices[pid.lower()] = float(spot_price)
                        print(f"    [OK] {pid} ({info['spot_name']}) 现货价: {spot_price}")
            except Exception as e2:
                print(f"    [WARN] {pid} 现货价获取失败: {str(e2)[:60]}")
                continue

    print(f"[term_basis] 现货价获取完成: {len(spot_prices)}/{len(SPOT_PRICE_MAP)} 品种")
    return spot_prices


def _get_term_structure_from_akshare(symbols: List[dict], trade_date: str) -> Dict[str, dict]:
    """
    AKShare降级方案：通过 futures_spot_price 批量获取现货+近月+主力合约价格。

    futures_spot_price(date, vars_list) 返回:
      spot_price, near_contract, near_contract_price,
      dominant_contract, dominant_contract_price, near_basis_rate, dom_basis_rate

    期限结构 = (dom_price - near_price) / near_price
    - contango: dom > near (远月升水)
    - backwardation: dom < near (远月贴水)

    仅在DuckDB不可用时使用（降级源，置信度-20%）。
    """
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        print("[term_basis] AKShare未安装，跳过期限结构(AKShare降级)")
        return {}

    print("[term_basis] DuckDB不可用，使用AKShare降级方案(futures_spot_price)...")
    term_data = {}

    # 构建 vars_list: 从symbols提取大写品种代码
    pid_to_spot_symbol = {}
    for sym in symbols:
        pid = sym["pid"]
        spot_sym = pid.upper()
        pid_to_spot_symbol[spot_sym] = pid.lower()

    vars_list = list(set(pid_to_spot_symbol.keys()))  # 去重
    print(f"  查询 {len(vars_list)} 个品种...")

    try:
        df = ak.futures_spot_price(date=trade_date, vars_list=vars_list)

        if df is not None and not df.empty:
            for _, row in df.iterrows():
                spot_sym = str(row.get("symbol", "")).strip().upper()
                pid_lower = pid_to_spot_symbol.get(spot_sym)
                if not pid_lower:
                    continue

                near_price = row.get("near_contract_price")
                dom_price = row.get("dominant_contract_price")

                if near_price is None or dom_price is None:
                    continue
                if pd.isna(near_price) or pd.isna(dom_price):
                    continue

                near_price = float(near_price)
                dom_price = float(dom_price)

                if near_price <= 0 or dom_price <= 0:
                    continue

                # 期限结构: (主力 - 近月) / 近月
                slope = (dom_price - near_price) / near_price

                if slope > 0.02:
                    term_type = "contango"
                elif slope < -0.02:
                    term_type = "backwardation"
                else:
                    term_type = "flat"

                term_data[pid_lower] = {
                    "near_month": str(row.get("near_contract", "")),
                    "far_month": str(row.get("dominant_contract", "")),
                    "near_price": near_price,
                    "far_price": dom_price,
                    "slope": round(slope, 4),
                    "term_type": term_type,
                    "contracts_count": 2,
                    "data_source": "AKShare(降级,-20%)",
                }

                # 同时提取基差数据
                spot_price = row.get("spot_price")
                if spot_price is not None and not pd.isna(spot_price):
                    spot_price = float(spot_price)
                    if spot_price > 0:
                        basis_rate = (spot_price - near_price) / near_price
                        term_data[pid_lower]["spot_price"] = round(spot_price, 2)
                        term_data[pid_lower]["basis_rate"] = round(basis_rate, 4)
                        term_data[pid_lower]["data_source_spot"] = "AKShare(降级,-20%)"
                        term_data[pid_lower]["dom_basis_rate"] = row.get("dom_basis_rate")

                term_type_cn = (
                    "升水" if term_type == "contango" else ("贴水" if term_type == "backwardation" else "平水")
                )
                sig = "+" if slope > 0 else ""
                print(f"  [OK] {pid_lower}: {term_type_cn} 近{near_price}→主{dom_price} ({sig}{slope:.2%})")
    except Exception as e:
        print(f"  [ERROR] AKShare futures_spot_price失败: {str(e)[:100]}")
        return {}

    print(f"[term_basis] AKShare期限结构提取完成: {len(term_data)}/{len(symbols)} 品种")
    return term_data


def _get_term_structure_from_duckdb(symbols: List[dict], trade_date: str) -> Dict[str, dict]:
    """
    从 futures-data-search 的 exchange-collector DuckDB 提取期限结构。
    返回 {symbol_lower: {near_month, far_month, near_price, far_price, slope, type}}

    数据源由 futures-data-search 统一调度，不硬编码数据库路径。
    如 DuckDB 不可用或为空，自动降级到 AKShare。
    """
    import duckdb

    # 通过 futures-data-search 的 MultiSourceAdapter 获取 DuckDB 路径
    db_path = None
    try:
        fds_dir = os.path.expanduser("~/.workbuddy/skills/futures-data-search")
        if fds_dir not in sys.path:
            sys.path.insert(0, fds_dir)
        from scripts.multi_source_adapter import MultiSourceAdapter

        adapter = MultiSourceAdapter()
        if adapter.collector_available and hasattr(adapter, "exchange_collector"):
            db_path = adapter.exchange_collector.db_path
            if os.path.exists(db_path):
                print(f"[term_basis] 通过MultiSourceAdapter获取DuckDB路径: {db_path}")
    except Exception as e:
        print(f"[term_basis] 通过MultiSourceAdapter获取DuckDB失败: {e}")

    if db_path is None:
        print("[term_basis] 未找到futures-data-search DuckDB，降级到AKShare")
        return _get_term_structure_from_akshare(symbols, trade_date)

    try:
        conn = duckdb.connect(db_path, read_only=True)
    except Exception as e:
        print(f"[term_basis] DuckDB连接失败: {e}，降级到AKShare")
        return _get_term_structure_from_akshare(symbols, trade_date)

    # 检查DuckDB是否有当天数据
    try:
        count = conn.execute("SELECT count(*) FROM daily_data WHERE trade_date = ?", [trade_date]).fetchone()[0]
        if count == 0:
            print(f"[term_basis] DuckDB中无{trade_date}数据(0条)，降级到AKShare")
            conn.close()
            return _get_term_structure_from_akshare(symbols, trade_date)
    except Exception:
        print("[term_basis] DuckDB查询失败，降级到AKShare")
        try:
            conn.close()
        except Exception:
            pass  # 连接关闭失败不影响降级
        return _get_term_structure_from_akshare(symbols, trade_date)

    term_data = {}

    for sym in symbols:
        pid = sym["pid"]
        exchange = sym["exchange"]

        try:
            # 查找该品种当天所有合约
            df = conn.execute(
                """
                SELECT symbol, close, volume, open_interest
                FROM daily_data
                WHERE trade_date = ?
                  AND exchange = ?
                  AND symbol SIMILAR TO ?
                  AND close > 0
                  AND volume > 0
                ORDER BY symbol
            """,
                [trade_date, exchange, f"{pid}[0-9]+"],
            ).fetchdf()

            if df is None or len(df) < 2:
                # 尝试忽略交易所过滤
                df = conn.execute(
                    """
                    SELECT symbol, close, volume, open_interest
                    FROM daily_data
                    WHERE trade_date = ?
                      AND symbol SIMILAR TO ?
                      AND close > 0
                      AND volume > 0
                    ORDER BY symbol
                """,
                    [trade_date, f"%{pid}%"],
                ).fetchdf()

            if df is None or len(df) < 2:
                continue

            # 自然排序：symbol字段天然按字母排序
            near = df.iloc[0]
            far = df.iloc[-1]

            near_price = float(near["close"])
            far_price = float(far["close"])

            if near_price <= 0 or far_price <= 0:
                continue

            slope = (far_price - near_price) / near_price

            # 判断期限结构类型
            if slope > 0.02:
                term_type = "contango"
            elif slope < -0.02:
                term_type = "backwardation"
            else:
                term_type = "flat"

            term_data[pid.lower()] = {
                "near_month": str(near["symbol"]),
                "far_month": str(far["symbol"]),
                "near_price": near_price,
                "far_price": far_price,
                "slope": round(slope, 4),
                "term_type": term_type,
                "contracts_count": len(df),
                "data_source": "交易所官方API(DuckDB)",
            }

        except Exception as e:
            print(f"  [WARN] {pid} 期限结构提取失败: {e}")
            continue

    conn.close()
    print(f"[term_basis] 期限结构提取完成(DuckDB): {len(term_data)}/{len(symbols)} 品种")
    return term_data


def compute_term_basis(
    symbols: List[dict],
    trade_date: str = None,
    spot_prices: Dict[str, float] = None,
) -> Dict[str, dict]:
    """
    主入口：计算所有品种的期限结构和基差信号。

    Args:
        symbols: 品种列表 [{'pid': 'rb', 'exchange': 'SHFE', ...}, ...]
        trade_date: 交易日期 YYYYMMDD，默认今天
        spot_prices: 预获取的现货价 {pid: price}，跳过AKShare调用

    Returns:
        {
            'rb': {
                'pid': 'rb',
                'term_type': 'contango'/'flat'/'backwardation',
                'term_slope': -0.023,
                'term_signal': -0.5,         # -1(利空) ~ +1(利多)
                'term_score': -5,            # term得分(±10内)
                'near_month': 'rb2507',
                'far_month': 'rb2601',
                'near_price': 3450,
                'far_price': 3370,
                'spot_price': 3520,
                'basis_rate': 0.0203,        # (现货-期货)/期货
                'basis_signal': 0.5,          # -1(高估利空) ~ +1(低估利多)
                'basis_score': 5,             # basis得分(±10内)
                'data_source_term': '交易所官方API(DuckDB)',
                'data_source_spot': 'AKShare(降级,-20%)',  # 或 None
            },
        }
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    # Step 1: 获取期限结构（交易所数据，主力源）
    term_data = _get_term_structure_from_duckdb(symbols, trade_date)

    # Step 2: 获取现货价格（AKShare，降级源）
    # 优先从 term_data 中提取（AKShare降级方案已自带现货价）
    if spot_prices is None:
        # 先从 term_data 提取已获取的现货价
        extracted_spot = {}
        for pid_lower, td in term_data.items():
            if "spot_price" in td and td["spot_price"] is not None:
                extracted_spot[pid_lower] = td["spot_price"]

        if extracted_spot:
            print(f"[term_basis] 从期限结构数据中提取现货价: {len(extracted_spot)}品种")
            spot_prices = extracted_spot
        else:
            spot_prices = _fetch_spot_prices_akshare(trade_date)

    # Step 3: 组装输出
    result = {}

    for sym in symbols:
        pid = sym["pid"]
        pid_lower = pid.lower()

        entry = {
            "pid": pid,
            "term_type": "unknown",
            "term_slope": None,
            "term_signal": 0,
            "term_score": 0,
            "near_month": None,
            "far_month": None,
            "near_price": None,
            "far_price": None,
            "spot_price": None,
            "basis_rate": None,
            "basis_signal": 0,
            "basis_score": 0,
            "data_source_term": None,
            "data_source_spot": None,
        }

        # 填期限结构
        if pid_lower in term_data:
            td = term_data[pid_lower]
            entry.update(
                {
                    "term_type": td["term_type"],
                    "term_slope": td["slope"],
                    "near_month": td["near_month"],
                    "far_month": td["far_month"],
                    "near_price": td["near_price"],
                    "far_price": td["far_price"],
                    "data_source_term": td.get("data_source", "交易所官方API(DuckDB)"),
                }
            )

            # 期限结构信号：backwardation=利多(现货紧), contango=利空(供应宽松)
            if td["term_type"] == "backwardation":
                entry["term_signal"] = 0.5
                entry["term_score"] = 5
            elif td["term_type"] == "contango":
                entry["term_signal"] = -0.5
                entry["term_score"] = -5
            else:
                entry["term_signal"] = 0
                entry["term_score"] = 0

        # 填基差
        near_price = entry.get("near_price")
        if pid_lower in spot_prices and near_price and near_price > 0:
            spot = spot_prices[pid_lower]
            entry["spot_price"] = spot
            entry["data_source_spot"] = "AKShare(降级,-20%)"

            basis_rate = (spot - near_price) / near_price
            entry["basis_rate"] = round(basis_rate, 4)

            # 基差信号：现货>期货=低估利多, 现货<期货=高估利空
            if basis_rate > 0.03:
                entry["basis_signal"] = 0.6  # 期货低估，利多
                entry["basis_score"] = 6
            elif basis_rate > 0.01:
                entry["basis_signal"] = 0.3
                entry["basis_score"] = 3
            elif basis_rate < -0.03:
                entry["basis_signal"] = -0.6  # 期货高估，利空
                entry["basis_score"] = -6
            elif basis_rate < -0.01:
                entry["basis_signal"] = -0.3
                entry["basis_score"] = -3
            else:
                entry["basis_signal"] = 0
                entry["basis_score"] = 0

        result[pid_lower] = entry

    available_term = sum(1 for v in result.values() if v["term_type"] != "unknown")
    available_basis = sum(1 for v in result.values() if v["spot_price"] is not None)
    print(f"[term_basis] 汇总: 期限结构{available_term}品种, 基差{available_basis}品种")
    return result


# ============================================================
# CLI 入口
# ============================================================
def main():
    """独立运行：打印期限结构和基差概览。"""
    print(f"\n{'=' * 60}")
    print("期限结构与基差分析")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    # 导入品种定义
    from collect_data import FUTURES_SYMBOLS

    result = compute_term_basis(FUTURES_SYMBOLS)

    print(f"\n--- 期限结构 ---")
    for pid_lower, entry in sorted(result.items()):
        if entry["term_type"] != "unknown":
            sig = "📈" if entry["term_signal"] > 0 else ("📉" if entry["term_signal"] < 0 else "➡️")
            print(
                f"  {sig} {pid_lower}: {entry['term_type']} "
                f"(近{entry['near_price']}→远{entry['far_price']}, "
                f"斜率{entry['term_slope']:.2%})"
            )

    print(f"\n--- 基差（正=期货低估,负=期货高估）---")
    for pid_lower, entry in sorted(result.items()):
        if entry["spot_price"] is not None:
            sig = "🟢" if entry["basis_signal"] > 0 else ("🔴" if entry["basis_signal"] < 0 else "⚪")
            print(
                f"  {sig} {pid_lower}: 现货{entry['spot_price']} vs 期货{entry['near_price']}, "
                f"基差率{entry['basis_rate']:.2%} [{entry['data_source_spot']}]"
            )


if __name__ == "__main__":
    main()
