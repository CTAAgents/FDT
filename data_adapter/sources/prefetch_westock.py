#!/usr/bin/env python3
"""
westock MCP 数据预取脚本 — 由 agent 通过 run_mcp 调用获取国际期货数据。

用法 (agent 执行):
  python prefetch_westock.py --symbol CL            # 预取 WTI 原油 (单品种)
  python prefetch_westock.py --all                  # 预取所有国际期货
  python prefetch_westock.py --status               # 查看缓存状态

注意: 本脚本不能直接调用 MCP，需由 agent 先通过 run_mcp 获取数据，
      再通过 --write 写入缓存。但为简化流程，直接通过 HTTP 访问已知 API。
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path

# ── 缓存目录 (与 WestockSource 共享) ──
_CACHE_DIR = Path(r"d:\Programs\FDT\data_adapter\.westock_cache")

# ── 已知国际期货品种 ──
ALL_SYMBOLS = {
    "CL": "WTI原油",
    "OIL": "布伦特原油",
    "NG": "天然气",
    "RB": "RBOB汽油",
    "HO": "取暖油",
    "GC": "COMEX黄金",
    "SI": "COMEX白银",
    "HG": "COMEX铜",
}


def write_cache(symbol: str, quote: dict | None = None,
                kline: list | None = None) -> str:
    """写入预取数据到缓存（兼容 WestockSource 格式）。"""
    from data_adapter.instrument_classifier import get_international_futures_params
    params = get_international_futures_params(symbol)
    std = params.get("symbol", symbol)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / f"{std}.json"

    existing = {}
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                existing = json.load(f)
        except Exception:
            pass

    data = {
        "symbol": std,
        "westock_code": params.get("westock", ""),
        "timestamp": datetime.now().timestamp(),
        "name": params.get("name", ""),
    }
    if quote is not None:
        data["quote"] = quote
    elif existing.get("quote"):
        data["quote"] = existing["quote"]
    if kline is not None:
        data["kline"] = kline
    elif existing.get("kline"):
        data["kline"] = existing["kline"]

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(cache_file)


def write_from_mcp_result(symbol: str, mcp_result: dict) -> str:
    """将 run_mcp 的 daa_quote 和 data_kline 结果写入缓存。"""
    data = mcp_result.get("data", {})
    quote = data.get("quote", {}) if "quote" in data else data
    kline = data.get("kline", data.get("nodes", [])) if "kline" in data or "nodes" in data else None

    # 如果 data 中包含 kline 批量结果
    if isinstance(kline, list) and kline and isinstance(kline[0], dict) and "symbol" in kline[0]:
        for item in kline:
            if item.get("symbol") == f"fu{symbol}" or item.get("symbol") == f"hf_OIL":
                nodes = item.get("data", {}).get("nodes", [])
                return write_cache(symbol, quote=quote, kline=nodes)
        return write_cache(symbol, quote=quote)
    elif isinstance(kline, list):
        return write_cache(symbol, quote=quote, kline=kline)
    else:
        return write_cache(symbol, quote=quote)


def show_status():
    """显示缓存状态。"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = list(_CACHE_DIR.glob("*.json"))
    if not files:
        print("无缓存数据。请先通过 run_mcp 预取。")
        return

    print(f"{'品种':8s} {'缓存时间':22s} {'有无报价':8s} {'有无K线':8s} {'过期':6s}")
    print("-" * 60)
    now = time.time()
    for f in sorted(files):
        try:
            with open(f) as fh:
                data = json.load(fh)
            sym = data.get("symbol", f.stem)
            ts = data.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "从未"
            has_q = "✅" if data.get("quote") else "❌"
            has_k = "✅" if data.get("kline") else "❌"
            age_h = (now - ts) / 3600 if ts else 999
            expired = "⚠️" if age_h > 1 else "✅"
            print(f"{sym:8s} {dt:22s} {has_q:8s} {has_k:8s} {expired:6s}")
        except Exception as e:
            print(f"{f.stem:8s} 读取失败: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="westock MCP 数据预取桥接")
    parser.add_argument("--symbol", help="品种标准代码，如 CL/NG/GC")
    parser.add_argument("--all", action="store_true", help="预取所有品种 (需 agent 循环)")
    parser.add_argument("--write", help="写入从 run_mcp 获取的 JSON 数据 (文件路径)")
    parser.add_argument("--westock-code", help="指定 westock 代码 (如 fuCL)，配合 --write 使用")
    parser.add_argument("--status", action="store_true", help="查看缓存状态")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    if args.write:
        # 从文件读取 MCP 结果并写入缓存
        with open(args.write, "r", encoding="utf-8") as f:
            mcp_result = json.load(f)

        wc = args.westock_code or ""
        # 从westock代码推断标准代码
        if wc:
            from data_adapter.instrument_classifier import _WESTOCK_TO_STANDARD
            std_code = _WESTOCK_TO_STANDARD.get(wc, wc)
        else:
            std_code = args.symbol or "UNKNOWN"

        path = write_from_mcp_result(std_code, mcp_result)
        print(f"已写入: {path}")
        sys.exit(0)

    if args.symbol:
        # 输出 agent 需要的 run_mcp 指令
        from data_adapter.instrument_classifier import get_westock_code
        wc = get_westock_code(args.symbol)
        print(f"请在 agent 中执行以下命令预取 {args.symbol} ({wc}):")
        print(f"\n  1. 获取行情:")
        print(f'     run_mcp(server="mcp_westock-mcp", tool="data_quote", args={{"codes":"{wc}"}})')
        print(f"\n  2. 获取K线 (保存结果到文件):")
        print(f'     run_mcp(server="mcp_westock-mcp", tool="data_kline", args={{"codes":"{wc}","limit":60}})')
        print(f"\n  3. 写入到 {_CACHE_DIR}:")
        print(f'     python prefetch_westock.py --write <结果文件> --westock-code {wc}')
        print(f"\n  或直接运行全量预取:")
        print(f'     python prefetch_westock.py --all')
        sys.exit(0)

    if args.all:
        print("全量预取模式 — 请在 agent 中依次执行:")
        for sym, name in ALL_SYMBOLS.items():
            from data_adapter.instrument_classifier import get_westock_code
            wc = get_westock_code(sym)
            print(f"\n[{sym}] {name} (westock: {wc})")
            print(f'  run_mcp(server="mcp_westock-mcp", tool="data_quote", args={{"codes":"{wc}"}})')
            print(f'  run_mcp(server="mcp_westock-mcp", tool="data_kline", args={{"codes":"{wc}","limit":60}})')
        print(f"\n然后使用 --write 逐品种写入。")
        sys.exit(0)

    parser.print_help()
