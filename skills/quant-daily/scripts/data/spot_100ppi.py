# -*- coding: utf-8 -*-
"""
100ppi 生意社现货基准价采集与单位对齐模块 v1.0

数据源: https://www.100ppi.com/sf/ (现期表, 日频, 16:30发布)
覆盖: 60+品种, 免费Web版, URL可预测

核心功能:
  1. 品种→sf_id映射表
  2. 单位自动换算 (FG玻璃/鸡蛋/生猪)
  3. 基差计算 (basis = spot - futures_main)
  4. 新鲜度校验

集成方式:
  在 term_basis.py 的 compute_term_basis() 中作为现货数据源之一,
  优先级: 100ppi > AKShare.
"""

import json
import urllib.request
import urllib.error
import re
from datetime import datetime, date
from typing import Dict, Optional, Tuple

# ============================================================
# 品种 → 100ppi sf_id 映射表
# ============================================================
PPI_SYMBOL_MAP: Dict[str, int] = {
    # 上海期货交易所
    "cu": 792,       # 铜
    "al": 827,       # 铝
    "zn": 826,       # 锌
    "pb": 825,       # 铅
    "ni": 1182,      # 镍
    "sn": 1181,      # 锡
    "au": 551,       # 黄金 (元/克)
    "ag": 544,       # 白银 (元/千克)
    "rb": 927,       # 螺纹钢
    "hc": 195,       # 热轧卷板
    "ss": 1300,      # 不锈钢
    "fu": 387,       # 燃料油 (规格不同, 基差仅供参考)
    "bu": 1022,      # 沥青
    "ru": 586,       # 天然橡胶
    "sp": 1053,      # 纸浆
    "br": 358,       # 丁二烯橡胶
    "ao": None,      # 氧化铝 — 100ppi未覆盖
    # 郑州商品交易所
    "TA": 356,       # PTA
    "PF": 976,       # 短纤
    "PX": 968,       # 对二甲苯
    "PR": 173,       # 瓶片
    "MA": 817,       # 甲醇
    "SA": 737,       # 纯碱
    "FG": 959,       # 玻璃 (现货元/㎡→需换算×80)
    "UR": 89,        # 尿素
    "CF": 344,       # 棉花
    "SR": 564,       # 白糖
    "OI": 810,       # 菜籽油
    "RM": 1014,      # 菜籽粕
    "PK": None,      # 花生 — 100ppi未覆盖
    "AP": None,      # 苹果 — 100ppi未覆盖
    "CJ": None,      # 红枣 — 100ppi未覆盖
    "SH": 368,       # 烧碱 (规格不同: 现货32%液碱, 期货干吨折百)
    "SM": 1155,      # 锰硅
    "SF": 1154,      # 硅铁
    # 大连商品交易所
    "m": 312,        # 豆粕
    "y": 403,        # 豆油
    "a": 1080,       # 豆一
    "b": None,       # 豆二 — 100ppi未覆盖
    "p": 1084,       # 棕榈油
    "c": 274,        # 玉米
    "jd": 1049,      # 鸡蛋 (现货元/公斤, 期货元/500kg→需换算)
    "lh": 936,       # 生猪 (现货元/公斤, 期货元/吨→需换算)
    "l": 435,        # 塑料(PE)
    "pp": 718,       # 聚丙烯(PP)
    "v": 107,        # PVC
    "eg": 222,       # 乙二醇
    "eb": 168,       # 苯乙烯
    "pg": 158,       # LPG
    "i": 961,        # 铁矿石 (现货湿吨, 期货干吨, 仅供参考)
    "j": 346,        # 焦炭 (现货一级, 期货介于一二之间, 仅供参考)
    "jm": 1121,      # 焦煤
    # 广州期货交易所
    "si": 238,       # 工业硅
    "lc": 1162,      # 碳酸锂
    "ps": 463,       # 多晶硅
    # 上海国际能源交易中心
    "sc": None,      # 原油 — 100ppi未覆盖
    "lu": None,      # 低硫燃油 — 100ppi未覆盖
    "ec": None,      # 集运指数 — 100ppi未覆盖
    "nr": None,      # 20号胶 — 100ppi未覆盖
}


# ============================================================
# 单位换算配置
# ============================================================
# 换算后所有品种统一为: 元/吨 (黄金白银除外)
# 换算公式: processed_spot = raw_spot × factor

UNIT_CONVERSIONS: Dict[str, dict] = {
    "FG": {
        "raw_unit": "元/平方米",
        "target_unit": "元/吨",
        "factor": 80,
        "formula": "spot_ton = spot_m2 × 80",
        "rationale": "5mm浮法玻璃: 密度2500kg/m³, 5mm×1㎡=12.5kg, 1吨=80㎡. "
                     "郑商所仓单标准: 1张=20吨=1600㎡, 1600/20=80㎡/吨 ✓",
    },
    "jd": {
        "raw_unit": "元/公斤",
        "target_unit": "元/公斤(统一)",
        "factor": 1,  # 现货已是元/公斤
        "futures_conversion": {
            "raw_unit": "元/500千克",
            "target_unit": "元/公斤",
            "factor": 1/500,  # 除以500
            "formula": "futures_kg = futures_raw / 500",
        },
        "formula": "basis = spot - futures/500",
        "rationale": "鸡蛋期货报价单位为元/500千克, 除以500得元/公斤",
    },
    "lh": {
        "raw_unit": "元/公斤",
        "target_unit": "元/公斤(统一)",
        "factor": 1,  # 现货已是元/公斤
        "futures_conversion": {
            "raw_unit": "元/吨",
            "target_unit": "元/公斤",
            "factor": 1/1000,  # 除以1000
            "formula": "futures_kg = futures_raw / 1000",
        },
        "formula": "basis = spot - futures/1000",
        "rationale": "生猪期货报价单位为元/吨, 除以1000得元/公斤",
    },
    "au": {
        "raw_unit": "元/克",
        "target_unit": "元/克(不转换)",
        "factor": 1,
        "rationale": "黄金单位元/克, 与期货一致, 无需转换",
    },
    "ag": {
        "raw_unit": "元/千克",
        "target_unit": "元/千克(不转换)",
        "factor": 1,
        "rationale": "白银单位元/千克, 与期货一致, 无需转换",
    },
    "fu": {
        "raw_unit": "元/吨",
        "target_unit": "元/吨(不转换)",
        "factor": 1,
        "warning": "现货180CST vs 期货RMG380, 规格不同, 基差不可比",
    },
    "SH": {
        "raw_unit": "元/吨",
        "target_unit": "元/吨(不转换)",
        "factor": 1,
        "warning": "现货32%液碱 vs 期货100%干吨折百, 规格不同, 基差仅供参考",
    },
    "i": {
        "raw_unit": "元/吨",
        "target_unit": "元/吨(不转换)",
        "factor": 1,
        "warning": "现货湿吨 vs 期货干吨, 基差仅供参考",
    },
    "j": {
        "raw_unit": "元/吨",
        "target_unit": "元/吨(不转换)",
        "factor": 1,
        "warning": "现货一级冶金焦 vs 期货介于一二之间, 基差仅供参考",
    },
}


# ============================================================
# URL 构建
# ============================================================
PPI_SF_URL = "https://www.100ppi.com/sf/"
PPI_SF_ITEM_URL = "https://www.100ppi.com/sf/{sf_id}.html"


def _normalize_symbol(symbol: str) -> str:
    """品种代码规范化: 转为映射表中存在的key (大小写不敏感)."""
    # 直接匹配
    if symbol in PPI_SYMBOL_MAP:
        return symbol
    # 尝试原始大小写
    for key in PPI_SYMBOL_MAP:
        if key.lower() == symbol.lower():
            return key
    return symbol


def get_ppi_url(symbol: str) -> Optional[str]:
    """根据品种代码获取100ppi现期表页面URL。"""
    key = _normalize_symbol(symbol)
    sf_id = PPI_SYMBOL_MAP.get(key)
    if sf_id is None:
        return None
    return PPI_SF_ITEM_URL.format(sf_id=sf_id)


def is_covered(symbol: str) -> bool:
    """检查品种是否被100ppi覆盖(大小写不敏感)。"""
    key = _normalize_symbol(symbol)
    return PPI_SYMBOL_MAP.get(key) is not None


def get_uncovered_symbols(symbols: list) -> list:
    """从品种列表中筛选未被100ppi覆盖的品种(大小写不敏感)。"""
    return [s for s in symbols if not is_covered(s)]


# ============================================================
# 单位换算
# ============================================================
def convert_spot(symbol: str, raw_spot: float) -> Tuple[float, str]:
    """
    将100ppi原始现货价换算为统一单位(大小写不敏感)。

    Args:
        symbol: 品种代码 (如 'FG', 'sp', 'jd')
        raw_spot: 100ppi页面上的原始现货价格

    Returns:
        (converted_price, unit_note)
        如 FG: (1014.4, '元/吨 (换算自12.68元/㎡×80)')
    """
    key = _normalize_symbol(symbol)
    conv = UNIT_CONVERSIONS.get(key, {})
    if not conv:
        return raw_spot, "元/吨"

    factor = conv.get("factor", 1)
    target_unit = conv.get("target_unit", "元/吨")

    if factor == 1:
        return raw_spot, target_unit

    converted = round(raw_spot * factor, 2)
    note = f"{target_unit} (换算自{raw_spot}{conv['raw_unit']}×{factor})"
    return converted, note


def convert_futures_for_basis(symbol: str, futures_price: float) -> Tuple[float, str]:
    """
    将期货主力价换算为与现货一致的单位，用于基差计算。

    Args:
        symbol: 品种代码
        futures_price: 100ppi页面上的主力合约原始价格

    Returns:
        (converted_price, unit_note)
    """
    conv = UNIT_CONVERSIONS.get(_normalize_symbol(symbol), {})
    fc = conv.get("futures_conversion")
    if fc is None:
        return futures_price, "元/吨"

    converted = futures_price * fc["factor"]
    note = f"{fc['target_unit']} (换算: {futures_price}{fc['raw_unit']}×{fc['factor']:.4f})"
    return converted, note


# ============================================================
# 基差计算
# ============================================================
def calculate_basis(symbol: str, spot_raw: float, futures_main: float) -> dict:
    """
    计算基差, 自动处理单位换算。

    Args:
        symbol: 品种代码
        spot_raw: 100ppi原始现货价
        futures_main: 100ppi页面上的主力合约价

    Returns:
        {
            'spot_raw': float,          # 原始现货价
            'spot_unit': str,           # 原始单位
            'spot_converted': float,    # 换算后现货价
            'spot_conv_note': str,      # 换算说明
            'futures_converted': float, # 换算后期货价
            'futures_conv_note': str,   # 期货换算说明
            'basis': float,             # 基差
            'basis_rate': float,        # 基差率 (basis/spot_converted)
            'basis_direction': str,     # '期货贴水' / '期货升水' / '不能计算'
            'warning': str,             # 警告信息(如有)
        }
    """
    result = {
        "spot_raw": spot_raw,
        "spot_unit": "元/吨",
        "spot_converted": spot_raw,
        "spot_conv_note": "",
        "futures_converted": futures_main,
        "futures_conv_note": "",
        "basis": None,
        "basis_rate": None,
        "basis_direction": "unknown",
        "warning": "",
    }

    conv = UNIT_CONVERSIONS.get(_normalize_symbol(symbol), {})

    # 检查是否不可比
    warning = conv.get("warning", "")
    if warning:
        result["warning"] = warning
        result["basis_direction"] = "单位/规格不可比"
        return result

    # 现货换算
    spot_converted, spot_note = convert_spot(symbol, spot_raw)
    result["spot_converted"] = spot_converted
    result["spot_conv_note"] = spot_note

    # 期货换算
    futures_converted, futures_note = convert_futures_for_basis(symbol, futures_main)
    result["futures_converted"] = futures_converted
    result["futures_conv_note"] = futures_note

    # 基差计算
    if spot_converted > 0 and futures_converted > 0:
        basis = round(spot_converted - futures_converted, 2)
        basis_rate = round(basis / spot_converted * 100, 2)
        result["basis"] = basis
        result["basis_rate"] = basis_rate
        result["basis_direction"] = "期货贴水(现货偏强)" if basis > 0 else ("期货升水(期货溢价)" if basis < 0 else "期现持平")
    else:
        result["warning"] = "现货或期货价格无效, 无法计算基差"

    return result


# ============================================================
# 网页数据解析
# ============================================================
def parse_ppi_sf_page(html: str) -> Tuple[str, Dict[str, dict]]:
    """
    解析100ppi现期表页面HTML, 提取现货+期货价格。

    支持的页面:
      - 总表: https://www.100ppi.com/sf/
      - 单品: https://www.100ppi.com/sf/{sf_id}.html

    Returns:
        (data_date_iso, {symbol_lower: {spot, main_price, main_contract, basis_text}})

    解析逻辑:
      从现期表HTML中正则匹配: 商品名 → 现货价 → 主力合约代码 → 主力合约价
      格式示例: <a href="...">纸浆</a>4816.67 ... 2609 4740 76
    """
    # 提取日期
    date_match = re.search(r"(\d{4})年(\d{2})月(\d{2})日", html)
    if date_match:
        data_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
    else:
        data_date = datetime.now().strftime("%Y-%m-%d")

    # 尝试匹配 "商品名</a>数字" 模式 (总表格式)
    # 例: <a href="/sf/1053.html">纸浆</a>4816.67 ... 2609 4740 76
    pattern = re.compile(
        r'<a[^>]*href="[^"]*sf/(\d+)\.html"[^>]*>([^<]+)</a>'
        r'\s*([\d,.]+(?:\.\d+)?)'  # 现货价
        r'(?:.*?)'                   # 跳过中间列
        r'(\d{4})\s+'               # 主力合约代码
        r'([\d,.]+(?:\.\d+)?)'      # 主力合约价
    )
    
    # 简化版: 只匹配现期表中的现货-主力对
    # 格式: 商品链接 → 现货 → ... → 主力代码 主力价 现期差
    items = {}
    matches = pattern.findall(html)

    if matches:
        for sf_id_str, name, spot_str, main_code, main_price_str in matches:
            try:
                sf_id = int(sf_id_str)
                spot = float(spot_str.replace(",", ""))
                main_price = float(main_price_str.replace(",", ""))
                
                # 反向映射: sf_id → symbol
                symbol = None
                for sym, sid in PPI_SYMBOL_MAP.items():
                    if sid == sf_id:
                        symbol = sym.lower()
                        break

                if symbol:
                    items[symbol] = {
                        "name": name.strip(),
                        "spot_raw": spot,
                        "main_contract": main_code,
                        "main_price": main_price,
                        "sf_id": sf_id,
                    }
            except (ValueError, AttributeError):
                continue

    return data_date, items


# ============================================================
# 数据获取
# ============================================================
def fetch_ppi_data(symbols: list = None, timeout: int = 15) -> Dict[str, dict]:
    """
    从100ppi现期表获取现货基准价和基差。

    Args:
        symbols: 品种代码列表, None=全部已覆盖品种
        timeout: HTTP超时(秒)

    Returns:
        {
            'data_date': '2026-07-09',
            'source': '100ppi现期表',
            'freshness_ok': bool,
            'items': {
                'sp': {spot_converted, basis, basis_rate, ...},
                ...
            },
            'uncovered': [...],   # 未被覆盖的品种
            'errors': [...],      # 获取失败的品种
        }
    """
    if symbols is None:
        symbols = list(PPI_SYMBOL_MAP.keys())

    result = {
        "data_date": None,
        "source": "生意社100ppi现期表",
        "source_url": PPI_SF_URL,
        "freshness_ok": False,
        "items": {},
        "uncovered": get_uncovered_symbols(symbols),
        "errors": [],
    }

    # 只处理被覆盖的品种
    covered = [s for s in symbols if is_covered(s)]
    if not covered:
        return result

    # 尝试获取总表页面 (一次性获取所有品种)
    html = None
    try:
        req = urllib.request.Request(PPI_SF_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("gb2312", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        result["errors"].append(f"总表获取失败: {e}")
        return result
    except Exception as e:
        result["errors"].append(f"总表解析异常: {e}")
        return result

    if not html:
        return result

    # 解析
    data_date, raw_items = parse_ppi_sf_page(html)
    result["data_date"] = data_date

    # 新鲜度校验
    try:
        page_date = date.fromisoformat(data_date)
        today = date.today()
        delta = (today - page_date).days
        result["freshness_ok"] = delta <= 1  # T-1或Today可接受
        result["freshness_delta_days"] = delta
    except (ValueError, TypeError):
        result["freshness_ok"] = False

    # 处理每个品种: 单位换算 + 基差计算
    for symbol in covered:
        sym_lower = symbol.lower()
        raw = raw_items.get(sym_lower)
        if raw is None:
            continue

        basis_info = calculate_basis(symbol, raw["spot_raw"], raw["main_price"])

        result["items"][sym_lower] = {
            "name": raw["name"],
            "sf_id": raw["sf_id"],
            "spot_raw": basis_info["spot_raw"],
            "spot_converted": basis_info["spot_converted"],
            "spot_conv_note": basis_info["spot_conv_note"],
            "main_contract": raw["main_contract"],
            "main_price_raw": raw["main_price"],
            "main_price_converted": basis_info["futures_converted"],
            "basis": basis_info["basis"],
            "basis_rate_pct": basis_info["basis_rate"],
            "basis_direction": basis_info["basis_direction"],
            "warning": basis_info["warning"],
        }

    result["covered_count"] = len(result["items"])
    return result


# ============================================================
# CLI 入口
# ============================================================
def main():
    """CLI: 获取并打印现货基准价概览。"""
    import sys

    print(f"\n{'='*60}")
    print(f"100ppi 现货基准价采集 v1.0")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 读取参数
    symbols = None
    output_file = None
    args = sys.argv[1:]
    if args:
        if not args[0].startswith("-"):
            symbols = [s.strip() for s in args[0].split(",")]
    if "-o" in args:
        idx = args.index("-o")
        if idx + 1 < len(args):
            output_file = args[idx + 1]

    if symbols:
        print(f"指定品种: {symbols}")
    else:
        print("全品种扫描 (所有已覆盖品种)")

    result = fetch_ppi_data(symbols)

    # 打印结果
    print(f"\n数据日期: {result['data_date']}")
    print(f"新鲜度: {'✅ OK (T-0/T-1)' if result['freshness_ok'] else '⚠️ 过期 (>1天)'}")
    print(f"覆盖品种: {result['covered_count']}")
    if result["uncovered"]:
        print(f"未覆盖: {result['uncovered']}")
    if result["errors"]:
        print(f"错误: {result['errors']}")

    print(f"\n{'品种':<6} {'现货(原)':>10} {'现货(换算)':>10} {'主力合约':>8} {'期货价':>10} {'基差':>10} {'基差率':>8} {'方向'}")
    print("-" * 85)
    for sym, item in sorted(result["items"].items()):
        basis_str = f"{item['basis']:+.2f}" if item['basis'] is not None else "N/A"
        rate_str = f"{item['basis_rate_pct']:+.2f}%" if item['basis_rate_pct'] is not None else "N/A"
        print(
            f"{sym:<6} {item['spot_raw']:>10.2f} {item['spot_converted']:>10.2f} "
            f"{item['main_contract']:>8} {item['main_price_converted']:>10.2f} "
            f"{basis_str:>10} {rate_str:>8} {item['basis_direction']}"
        )
        if item["warning"]:
            print(f"  ⚠️  {item['warning']}")

    # 输出JSON
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            # 简化输出(移除不可序列化对象)
            clean = {
                "data_date": result["data_date"],
                "source": result["source"],
                "freshness_ok": result["freshness_ok"],
                "items": result["items"],
                "uncovered": result["uncovered"],
            }
            json.dump(clean, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 输出: {output_file}")


if __name__ == "__main__":
    main()
