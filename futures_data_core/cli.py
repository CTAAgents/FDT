"""命令行入口 ``fdc`` [INDEPENDENT / LLM-ENHANCED]。

子命令：
    fdc kline <symbol>              [INDEPENDENT]
    fdc indicators <symbol>         [INDEPENDENT]
    fdc term-structure <symbol>     [INDEPENDENT]
    fdc spread <symbol>             [INDEPENDENT]
    fdc basis <symbol>              [INDEPENDENT]
    fdc warrant <symbol>            [INDEPENDENT]
    fdc fundamental <symbol>        [LLM-ENHANCED]
    fdc f10 <symbol>                [LLM-ENHANCED]
    fdc setup status                [INDEPENDENT]

所有数据 API 默认独立运行；``--use-llm`` 显式开启 LLM 增强。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from futures_data_core import (
    compute_indicators,
    detect_llm_capability,
    get_basis,
    get_f10,
    get_fundamental,
    get_kline,
    get_spread,
    get_term_structure,
    get_warrant,
)
from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core._runtime import current_environment


def _print_payload(payload: A2APayload) -> None:
    """将 A2APayload 以 JSON 形式输出到标准输出。"""
    print(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2, default=str))


def _kline_to_indicator_input(kline_data: dict) -> dict:
    """从 K 线 payload 的 ``bars`` 提取技术指标所需 dict-of-arrays。"""
    bars = kline_data.get("bars") or []
    out = {c: [] for c in ("open", "high", "low", "close", "volume")}
    for b in bars:
        for c in out:
            val = b.get(c)
            out[c].append(float(val) if val is not None else 0.0)
    return out


def _print_setup(args) -> None:
    """打印运行模式与 LLM 能力探测结果。"""
    cap = detect_llm_capability()
    print("futures-data-core 运行模式")
    print("=" * 40)
    for name, mode in cap.items():
        label = mode.value if hasattr(mode, "value") else str(mode)
        print(f"  {name:<22} {label}")
    if args.verbose:
        print("-" * 40)
        print(f"  当前环境: {current_environment()}")


async def _dispatch(args) -> int:
    """根据子命令分发到对应数据 API。返回进程退出码。"""
    if args.command == "kline":
        payload = await get_kline(args.symbol, args.period, args.days, args.source)
        _print_payload(payload)
    elif args.command == "indicators":
        k = await get_kline(args.symbol, args.period, args.days)
        indata = _kline_to_indicator_input(k.data)
        result = compute_indicators(indata, "all")
        _print_payload(
            A2APayload(type=DATA_TYPES["INDICATORS"], runtime_mode="independent", data=result)
        )
    elif args.command == "term-structure":
        payload = await get_term_structure(args.symbol)
        _print_payload(payload)
    elif args.command == "spread":
        payload = await get_spread(args.symbol)
        _print_payload(payload)
    elif args.command == "basis":
        payload = await get_basis(args.symbol)
        _print_payload(payload)
    elif args.command == "warrant":
        payload = await get_warrant(args.symbol, exchange=args.exchange)
        _print_payload(payload)
    elif args.command == "fundamental":
        payload = await get_fundamental(args.symbol, use_llm=args.use_llm)
        _print_payload(payload)
    elif args.command == "f10":
        payload = await get_f10(args.symbol, enhance_with_llm=args.use_llm)
        _print_payload(payload)
    elif args.command == "setup":  # pragma: no branch
        # 受 argparse required=True 约束，合法命令必命中前序 elif 或本分支，
        # 故本 elif 的 False 分支（跳转至 return）在运行期不可达。
        _print_setup(args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造 ``fdc`` 命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="fdc", description="futures-data-core 期货数据采集 CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("kline", help="K 线数据 [INDEPENDENT]")
    p.add_argument("symbol")
    p.add_argument("--period", default="daily")
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--source", default="auto")

    p = sub.add_parser("indicators", help="技术指标 [INDEPENDENT]")
    p.add_argument("symbol")
    p.add_argument("--period", default="daily")
    p.add_argument("--days", type=int, default=120)

    p = sub.add_parser("term-structure", help="期限结构 [INDEPENDENT]")
    p.add_argument("symbol")

    p = sub.add_parser("spread", help="跨期价差 [INDEPENDENT]")
    p.add_argument("symbol")

    p = sub.add_parser("basis", help="基差（现货-期货）[INDEPENDENT]")
    p.add_argument("symbol")

    p = sub.add_parser("warrant", help="交易所仓单日报 [INDEPENDENT]")
    p.add_argument("symbol")
    p.add_argument("--exchange", default="SHFE")

    p = sub.add_parser("fundamental", help="基本面 [LLM-ENHANCED]")
    p.add_argument("symbol")
    p.add_argument("--use-llm", dest="use_llm", action="store_true")
    p.add_argument("--no-llm", dest="use_llm", action="store_false")
    p.set_defaults(use_llm=False)

    p = sub.add_parser("f10", help="F10 综合报告 [LLM-ENHANCED]")
    p.add_argument("symbol")
    p.add_argument("--use-llm", dest="use_llm", action="store_true")
    p.add_argument("--no-llm", dest="use_llm", action="store_false")
    p.set_defaults(use_llm=False)

    p = sub.add_parser("setup", help="环境 / 能力探测")
    p.add_argument("action", choices=["status"], nargs="?", default="status")
    p.add_argument("--verbose", action="store_true")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数列表；``None`` 时使用 ``sys.argv[1:]``。

    Returns:
        进程退出码（成功为 ``0``）。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(_dispatch(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
