"""独立调试单个采集器。

逐个测试 DataCore / TDX / WebFallback / QMT / TqSDK，
打印每个采集器的 check_available 和 get_kline 返回值。
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
# 降低第三方库日志噪音
for name in ("urllib3", "httpcore", "asyncio", "numexpr.utils"):
    logging.getLogger(name).setLevel(logging.INFO)


async def test_one(name: str, factory):
    print(f"\n=== 测试 {name} ===")
    try:
        c = factory()
    except Exception as e:
        print(f"  构造失败: {type(e).__name__}: {e}")
        return

    try:
        avail = await c.check_available()
        print(f"  check_available: {avail}")
        if not avail:
            return
    except Exception as e:
        print(f"  check_available 异常: {type(e).__name__}: {e}")
        return

    # 测试多个 symbol 变体：品种 / 主力合约 / 实际合约
    for sym in ("RB", "RB00", "RB2505", "RB2601"):
        try:
            data = await c.get_kline(sym, "daily", 30)
            if data is None:
                print(f"  get_kline({sym}) 返回 None")
                continue
            bars = getattr(data, "bars", None)
            print(f"  get_kline({sym}): bars={len(bars) if bars else 0}")
            if bars:
                print(f"    首条: {bars[0]}")
                print(f"    末条: {bars[-1]}")
        except Exception as e:
            print(f"  get_kline({sym}) 异常: {type(e).__name__}: {e}")


async def main():
    from futures_data_core.collectors.datacore import DataCoreCollector
    from futures_data_core.collectors.qmt import QMTCollector
    from futures_data_core.collectors.tdx import TDXCollector
    from futures_data_core.collectors.tqsdk import TqSdkCollector
    from futures_data_core.collectors.web_fallback import WebFallbackCollector

    await test_one("WebFallback", WebFallbackCollector)
    await test_one("QMT", QMTCollector)
    await test_one("TqSdk", TqSdkCollector)
    await test_one("TDX", TDXCollector)
    await test_one("DataCore", DataCoreCollector)


if __name__ == "__main__":
    asyncio.run(main())
