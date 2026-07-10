#!/usr/bin/env python3
"""
预计算缓存模块 v1.0.0 — 盘中时延优化 Step 4
==============================================
盘前运行 scan_all 并缓存结果；盘中触发辩论时跳过全量扫描，仅做增量价格更新。

使用流程:
  1. 盘前（08:00）：build_cache() → 跑全品种 scan_all，缓存 JSON
  2. 盘中触发辩论：load_cache() → 若命中 → load_cache() + 仅刷新辩论品种最新价格
  3. 缓存失效：TTL=4h 或 重大事件触发 → 回退全量扫描

适用范围: FDT 辩论专家团（futures-debate-team）
"""

import json, os, sys, time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple

# ── 路径 ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
FDT_DIR = os.path.dirname(SKILL_DIR)  # plugins/futures-debate-team/
CACHE_DIR = os.path.join(FDT_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# scan_all.py 路径
COMMODITY_SKILL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ))),
    "skills", "commodity-trend-signal"
)
SCAN_ALL_PATH = os.path.join(COMMODITY_SKILL_DIR, "scripts", "scan_all.py")


# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════

# 缓存有效期（秒）
CACHE_TTL_SECONDS = 4 * 3600  # 4 小时

# 重大事件关键词（用于缓存失效检测）
MAJOR_EVENT_KEYWORDS = [
    "FOMC", "非农", "CPI", "PPI", "美联储", "OPEC", "USDA",
    "地缘冲突", "战争", "制裁", "关税", "利率决议",
]

# 当日缓存文件名
def _cache_file_path(dt: date = None) -> str:
    dt = dt or date.today()
    return os.path.join(CACHE_DIR, f"precompute_{dt.strftime('%Y%m%d')}.json")


# ═══════════════════════════════════════════════
# 核心 API
# ═══════════════════════════════════════════════

def build_cache(output_dir: str = None) -> dict:
    """盘前预计算：跑全品种 scan_all + 缓存结果。

    Args:
        output_dir: scan_all 的输出目录（HTML/JSON 写入路径）

    Returns:
        scan_all 的完整输出 dict（含 _meta、all_ranked 等）
    """
    print(f"[precompute_cache] 开始构建缓存 ({date.today()})...")
    start = time.time()

    # ── 加载 scan_all ──
    sys.path.insert(0, os.path.join(COMMODITY_SKILL_DIR, "scripts"))
    from scan_all import run_scan

    result = run_scan(output_dir=output_dir)

    # ── 存入缓存 ──
    cache_path = _cache_file_path()
    cache_entry = {
        "version": "1.0.0",
        "built_at": datetime.now().isoformat(),
        "cache_date": date.today().isoformat(),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "expires_at": (datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS)).isoformat(),
        "data": result,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_entry, f, ensure_ascii=False, indent=2, default=str)

    elapsed = time.time() - start
    total = result.get("_meta", {}).get("total", 0)
    print(f"[precompute_cache] 缓存构建完成: {total} 品种, {elapsed:.0f}s")
    print(f"  → {cache_path}")
    print(f"  → 有效期至 {cache_entry['expires_at']}")

    return result


def load_cache() -> Tuple[Optional[dict], bool]:
    """尝试加载当日缓存。

    Returns:
        (data, is_fresh)
        - data: scan_all 结果 dict（None = 无缓存）
        - is_fresh: True = 缓存有效可直接用；False = 缓存过期或不存在
    """
    cache_path = _cache_file_path()
    if not os.path.exists(cache_path):
        return None, False

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_entry = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return None, False

    # 检查有效期
    expires_str = cache_entry.get("expires_at")
    if expires_str:
        expires = datetime.fromisoformat(expires_str)
        if datetime.now() > expires:
            print(f"[precompute_cache] ⚠️ 缓存已过期（{expires_str}）")
            return cache_entry.get("data"), False

    data = cache_entry.get("data")
    if not data:
        return None, False

    total = data.get("_meta", {}).get("total", 0)
    print(f"[precompute_cache] ✅ 缓存命中: {total} 品种, 构建于 {cache_entry['built_at']}")
    return data, True


def refresh_prices_for_symbols(cached_data: dict, symbols: List[str]) -> dict:
    """盘中增量更新：只获取指定品种的最新 K 线，更新缓存中的价格数据。

    不重新跑 scan_all 全流程，只拉最近几根 K 线做价格修正。

    Args:
        cached_data: 从 load_cache() 拿到的 scan_all 结果
        symbols: 需要刷新价格的品种列表

    Returns:
        更新后的 scan_all 结果（原地修改 + 返回）
    """
    if not symbols or not cached_data:
        return cached_data

    print(f"[precompute_cache] 增量更新 {len(symbols)} 个品种价格...")
    start = time.time()

    try:
        sys.path.insert(0, os.path.join(COMMODITY_SKILL_DIR, "scripts"))
        from tdx_bridge import get_bridge
        from scan_all import collect_kline_for_all
        from symbols import ALL_SYMBOLS

        bridge = get_bridge()
        if not bridge.available:
            print("[precompute_cache] ⚠️ TQ-Local 不可用，跳过价格刷新")
            return cached_data

        # 构造 target symbols
        sym_map = {s: n for s, n in ALL_SYMBOLS}
        targets = [(s, sym_map.get(s, s)) for s in symbols if s in sym_map]

        # 只拉最近 10 根 K 线（快速）
        from adapters import MultiSourceAdapter
        adapter = MultiSourceAdapter()
        fresh_kline = collect_kline_for_all(adapter, targets, days=5, min_bars=2)

        # 更新缓存中的价格
        updated = 0
        for sym, name in targets:
            if sym not in fresh_kline:
                continue
            _, dlist = fresh_kline[sym]
            if not dlist:
                continue
            latest = dlist[-1]
            new_price = float(latest.get("close", 0))
            if new_price <= 0:
                continue

            # 找到 all_ranked 中对应品种并更新价格
            for r in cached_data.get("all_ranked", []):
                if r.get("symbol") == sym:
                    old_price = r.get("price", 0)
                    r["price"] = new_price
                    r["_price_updated_at"] = datetime.now().isoformat()
                    if old_price > 0:
                        r["change_pct"] = round((new_price / old_price - 1) * 100, 2)
                    updated += 1
                    break

        elapsed = time.time() - start
        print(f"[precompute_cache] 价格刷新完成: {updated}/{len(targets)} 更新, {elapsed:.1f}s")

    except Exception as e:
        print(f"[precompute_cache] ⚠️ 价格刷新异常: {e}")

    return cached_data


def check_event_invalidation() -> bool:
    """检查当前是否有重大事件应导致缓存失效。

    通过 WebSearch 或事件日历检查 FOMC/USDA 等关键事件。

    Returns:
        True = 应失效缓存（触发全量扫描）
    """
    # 简化实现：检查是否在重大事件日
    # 期货市场的重要发布日通常是固定的
    today = date.today()
    weekday = today.weekday()

    # 美国非农就业数据：每月第一个周五
    if weekday == 4:  # Friday
        first_friday = date(today.year, today.month, 1)
        while first_friday.weekday() != 4:
            first_friday += timedelta(days=1)
        if today == first_friday:
            print("[precompute_cache] ⚠️ 非农日，缓存过期")
            return True

    # FOMC 决议：每年 8 次会议，季度末月
    # 此处简化：每月第三个周三附近
    if today.month in [3, 6, 9, 12] and 15 <= today.day <= 22:
        if weekday == 2 or weekday == 3:  # Wed/Thu
            print("[precompute_cache] ⚠️ FOMC 窗口期，缓存过期")
            return True

    return False


def get_cache_info() -> dict:
    """获取当前缓存状态信息。"""
    cache_path = _cache_file_path()
    if not os.path.exists(cache_path):
        return {"status": "no_cache", "path": cache_path}

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        now = datetime.now()
        expires = datetime.fromisoformat(entry["expires_at"]) if entry.get("expires_at") else now
        remaining = max(0, (expires - now).total_seconds() / 3600)
        return {
            "status": "fresh" if remaining > 0 else "expired",
            "path": cache_path,
            "built_at": entry.get("built_at"),
            "expires_at": entry.get("expires_at"),
            "remaining_hours": round(remaining, 1),
            "total_symbols": entry.get("data", {}).get("_meta", {}).get("total", 0),
            "version": entry.get("version", "unknown"),
        }
    except Exception as e:
        return {"status": "corrupted", "path": cache_path, "error": str(e)}


def invalidate_cache(dt: date = None) -> bool:
    """主动使缓存失效（删除缓存文件）。

    Returns:
        True = 成功删除
    """
    cache_path = _cache_file_path(dt)
    if os.path.exists(cache_path):
        os.remove(cache_path)
        print(f"[precompute_cache] 🗑️ 缓存已清除: {cache_path}")
        return True
    return False


# ═══════════════════════════════════════════════
# CLI / 盘前自动化入口
# ═══════════════════════════════════════════════

def main():
    """CLI入口：python precompute_cache.py [--build] [--info] [--clear]"""
    import argparse

    parser = argparse.ArgumentParser(description="FDT 预计算缓存管理")
    parser.add_argument("--build", action="store_true", help="构建/重建缓存（盘前）")
    parser.add_argument("--info", action="store_true", help="查看缓存状态")
    parser.add_argument("--clear", action="store_true", help="清除当日缓存")

    args = parser.parse_args()

    if args.info:
        info = get_cache_info()
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.clear:
        invalidate_cache()
    else:
        # 默认：如果缓存不存在或过期 → 重建
        data, is_fresh = load_cache()
        if is_fresh:
            print("[precompute_cache] 缓存有效，无需重建")
            cache_info = get_cache_info()
            print(json.dumps(cache_info, ensure_ascii=False, indent=2))
        else:
            build_cache()


if __name__ == "__main__":
    main()
