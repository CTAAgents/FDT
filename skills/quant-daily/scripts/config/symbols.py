# -*- coding: utf-8 -*-
"""
商品期货品种列表 — 单一来源（symbols.py）
========================================
所有入口脚本必须从此文件导入品种列表，禁止各自定义。

更新品种时：只改此文件，所有入口（scan_all / full_scan_debate / collect_data）自动同步。
"""

from typing import Dict, List, Tuple

# ── 主力非僵尸品种列表 (pid, name) ──
# 覆盖：黑色、能化、有色、贵金属、油脂油料、农产品、建材化工、新能源、航运
ALL_SYMBOLS: List[Tuple[str, str]] = [
    # 黑色系 (7)
    ("rb", "螺纹钢"),
    ("hc", "热卷"),
    ("i", "铁矿石"),
    ("j", "焦炭"),
    ("jm", "焦煤"),
    ("SF", "硅铁"),
    ("SM", "锰硅"),
    # 能源链 (6)
    ("sc", "原油"),
    ("lu", "低硫燃油"),
    ("fu", "燃油"),
    ("bu", "沥青"),
    ("pg", "LPG"),
    ("PX", "对二甲苯"),
    # 聚酯链 (5)
    ("TA", "PTA"),
    ("PF", "短纤"),
    ("PR", "瓶片"),
    ("eg", "乙二醇"),
    ("eb", "苯乙烯"),
    # 塑化链 (4)
    ("v", "PVC"),
    ("pp", "聚丙烯"),
    ("l", "塑料"),
    ("MA", "甲醇"),
    # 化工 (3)
    ("SH", "烧碱"),
    ("SA", "纯碱"),
    ("UR", "尿素"),
    # 有色金属 (8)
    ("cu", "沪铜"),
    ("al", "沪铝"),
    ("zn", "沪锌"),
    ("pb", "沪铅"),
    ("ni", "沪镍"),
    ("sn", "沪锡"),
    ("ao", "氧化铝"),
    ("SS", "不锈钢"),
    # 贵金属 (2)
    ("au", "沪金"),
    ("ag", "沪银"),
    # 油脂油料 (8)
    ("a", "豆一"),
    ("b", "豆二"),
    ("m", "豆粕"),
    ("y", "豆油"),
    ("p", "棕榈油"),
    ("OI", "菜籽油"),
    ("RM", "菜粕"),
    ("PK", "花生"),
    # 农产品 (6)
    ("c", "玉米"),
    ("cs", "玉米淀粉"),
    ("SR", "白糖"),
    ("CF", "棉花"),
    ("jd", "鸡蛋"),
    ("lh", "生猪"),
    # 果蔬 (2)
    ("AP", "苹果"),
    ("CJ", "红枣"),
    # 建材化工 (6)
    ("FG", "玻璃"),
    ("ru", "橡胶"),
    ("nr", "20号胶"),
    ("br", "丁二烯橡胶"),
    ("sp", "纸浆"),
    ("op", "双胶纸"),
    # 新能源 (3)
    ("lc", "碳酸锂"),
    ("si", "工业硅"),
    ("ps", "多晶硅"),
    # 航运 (1)
    ("ec", "集运指数"),
    # 有色金属补充 (1)
    ("bc", "国际铜"),
    # 其他 (1)
    ("rr", "粳米"),
]

# 交易所代码 + 通达信代码映射（单一来源，供 collect_data.py 使用）
# exchange: SHFE/DCE/CZCE/GFEX/INE/CFFEX
# tdx_code: 通达信品种代码（主力连续）
SYMBOL_DETAILS: Dict[str, dict] = {
    # 黑色系 (7)
    "rb": {"exchange": "SHFE", "tdx_code": "rb0"},
    "hc": {"exchange": "SHFE", "tdx_code": "hc0"},
    "i": {"exchange": "DCE", "tdx_code": "i0"},
    "j": {"exchange": "DCE", "tdx_code": "j0"},
    "jm": {"exchange": "DCE", "tdx_code": "jm0"},
    "SF": {"exchange": "CZCE", "tdx_code": "SF0"},
    "SM": {"exchange": "CZCE", "tdx_code": "SM0"},
    # 能源链 (6)
    "sc": {"exchange": "INE", "tdx_code": "sc0"},
    "lu": {"exchange": "INE", "tdx_code": "lu0"},
    "fu": {"exchange": "SHFE", "tdx_code": "fu0"},
    "bu": {"exchange": "SHFE", "tdx_code": "bu0"},
    "pg": {"exchange": "DCE", "tdx_code": "pg0"},
    "PX": {"exchange": "CZCE", "tdx_code": "PX0"},
    # 聚酯链 (5)
    "TA": {"exchange": "CZCE", "tdx_code": "TA0"},
    "PF": {"exchange": "CZCE", "tdx_code": "PF0"},
    "PR": {"exchange": "CZCE", "tdx_code": "PR0"},
    "eg": {"exchange": "DCE", "tdx_code": "eg0"},
    "eb": {"exchange": "DCE", "tdx_code": "eb0"},
    # 塑化链 (4)
    "v": {"exchange": "DCE", "tdx_code": "v0"},
    "pp": {"exchange": "DCE", "tdx_code": "pp0"},
    "l": {"exchange": "DCE", "tdx_code": "l0"},
    "MA": {"exchange": "CZCE", "tdx_code": "MA0"},
    # 化工 (3)
    "SH": {"exchange": "CZCE", "tdx_code": "SH0"},
    "SA": {"exchange": "CZCE", "tdx_code": "SA0"},
    "UR": {"exchange": "CZCE", "tdx_code": "UR0"},
    # 有色金属 (8)
    "cu": {"exchange": "SHFE", "tdx_code": "cu0"},
    "al": {"exchange": "SHFE", "tdx_code": "al0"},
    "zn": {"exchange": "SHFE", "tdx_code": "zn0"},
    "pb": {"exchange": "SHFE", "tdx_code": "pb0"},
    "ni": {"exchange": "SHFE", "tdx_code": "ni0"},
    "sn": {"exchange": "SHFE", "tdx_code": "sn0"},
    "ao": {"exchange": "SHFE", "tdx_code": "ao0"},
    "SS": {"exchange": "SHFE", "tdx_code": "SS0"},
    # 贵金属 (2)
    "au": {"exchange": "SHFE", "tdx_code": "au0"},
    "ag": {"exchange": "SHFE", "tdx_code": "ag0"},
    # 油脂油料 (8)
    "a": {"exchange": "DCE", "tdx_code": "a0"},
    "b": {"exchange": "DCE", "tdx_code": "b0"},
    "m": {"exchange": "DCE", "tdx_code": "m0"},
    "y": {"exchange": "DCE", "tdx_code": "y0"},
    "p": {"exchange": "DCE", "tdx_code": "p0"},
    "OI": {"exchange": "CZCE", "tdx_code": "OI0"},
    "RM": {"exchange": "CZCE", "tdx_code": "RM0"},
    "PK": {"exchange": "CZCE", "tdx_code": "PK0"},
    # 农产品 (6)
    "c": {"exchange": "DCE", "tdx_code": "c0"},
    "cs": {"exchange": "DCE", "tdx_code": "cs0"},
    "SR": {"exchange": "CZCE", "tdx_code": "SR0"},
    "CF": {"exchange": "CZCE", "tdx_code": "CF0"},
    "jd": {"exchange": "DCE", "tdx_code": "jd0"},
    "lh": {"exchange": "DCE", "tdx_code": "lh0"},
    # 果蔬 (2)
    "AP": {"exchange": "CZCE", "tdx_code": "AP0"},
    "CJ": {"exchange": "CZCE", "tdx_code": "CJ0"},
    # 建材化工 (6)
    "FG": {"exchange": "CZCE", "tdx_code": "FG0"},
    "ru": {"exchange": "SHFE", "tdx_code": "ru0"},
    "nr": {"exchange": "INE", "tdx_code": "nr0"},
    "br": {"exchange": "SHFE", "tdx_code": "br0"},
    "sp": {"exchange": "SHFE", "tdx_code": "sp0"},
    "op": {"exchange": "SHFE", "tdx_code": "op0"},
    # 新能源 (3)
    "lc": {"exchange": "GFEX", "tdx_code": "lc0"},
    "si": {"exchange": "GFEX", "tdx_code": "si0"},
    "ps": {"exchange": "GFEX", "tdx_code": "ps0"},
    # 航运 (1)
    "ec": {"exchange": "INE", "tdx_code": "ec0"},
    # 有色金属补充 (1)
    "bc": {"exchange": "INE", "tdx_code": "bc0"},
    # 其他 (1)
    "rr": {"exchange": "DCE", "tdx_code": "rr0"},
}

# 提取 pid 集合，用于快速查询
ALL_PIDS = {sym[0] for sym in ALL_SYMBOLS}

# 62 主力品种 + 1 补充 = 63 品种
assert len(ALL_SYMBOLS) == 63, f"品种列表长度应为63，实际为{len(ALL_SYMBOLS)}"
assert len(SYMBOL_DETAILS) == 63, f"品种详情长度应为63，实际为{len(SYMBOL_DETAILS)}"
