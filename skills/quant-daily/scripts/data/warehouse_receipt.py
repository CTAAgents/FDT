# -*- coding: utf-8 -*-
"""
期货仓单数据模块 v1.0

为基本面分析(探源)、辩手、闫判官提供标准化仓单数据。
数据来源: 各交易所仓单日报（上期所/郑商所/大商所/广期所）

仓单分析维度:
  1. 绝对量 — 注册仓单总量(吨/张)
  2. 环比变化 — 单日增减 → 短期入库/出库压力
  3. 月度趋势 — 近30日累计变化 → 中期方向
  4. 同比分位 — vs 历史同期分位数 → 是否异常
  5. 仓单/持仓比 — 仓单占期货持仓比例 → 交割压力

解读原则:
  - 仓单增加 → 现货商在期货上交割意愿增强 → 利空(供给压力)
  - 仓单减少 → 现货被提取/注销 → 利多(现货偏紧)
  - 仓单高位且持续增加 → 强利空
  - 仓单低位且持续减少 → 强利多

品种映射: symbol → (exchange, variety_code, unit)
"""

from typing import Dict, List, Optional, Tuple

# ============================================================
# 品种 → 交易所映射
# ============================================================
EXCHANGE_MAP: Dict[str, Tuple[str, str, str]] = {
    # symbol → (exchange, variety_code, unit)
    # 上海期货交易所
    "cu": ("SHFE", "铜", "吨"),
    "al": ("SHFE", "铝", "吨"),
    "zn": ("SHFE", "锌", "吨"),
    "pb": ("SHFE", "铅", "吨"),
    "ni": ("SHFE", "镍", "吨"),
    "sn": ("SHFE", "锡", "吨"),
    "au": ("SHFE", "黄金", "千克"),
    "ag": ("SHFE", "白银", "千克"),
    "rb": ("SHFE", "螺纹钢", "吨"),
    "hc": ("SHFE", "热轧卷板", "吨"),
    "ss": ("SHFE", "不锈钢", "吨"),
    "fu": ("SHFE", "燃料油", "吨"),
    "bu": ("SHFE", "沥青", "吨"),
    "ru": ("SHFE", "天然橡胶", "吨"),
    "sp": ("SHFE", "纸浆", "吨"),
    "br": ("SHFE", "丁二烯橡胶", "吨"),
    "ao": ("SHFE", "氧化铝", "吨"),
    # 上海国际能源交易中心
    "sc": ("INE", "原油", "桶"),
    "lu": ("INE", "低硫燃油", "吨"),
    "nr": ("INE", "20号胶", "吨"),
    "ec": ("INE", "集运指数", "手"),
    # 郑州商品交易所
    "TA": ("CZCE", "PTA", "张"),
    "PF": ("CZCE", "短纤", "张"),
    "PX": ("CZCE", "对二甲苯", "张"),
    "PR": ("CZCE", "瓶片", "张"),
    "MA": ("CZCE", "甲醇", "张"),
    "SA": ("CZCE", "纯碱", "张"),
    "FG": ("CZCE", "玻璃", "张"),
    "UR": ("CZCE", "尿素", "张"),
    "CF": ("CZCE", "棉花", "张"),
    "SR": ("CZCE", "白糖", "张"),
    "OI": ("CZCE", "菜籽油", "张"),
    "RM": ("CZCE", "菜籽粕", "张"),
    "PK": ("CZCE", "花生", "张"),
    "AP": ("CZCE", "苹果", "张"),
    "CJ": ("CZCE", "红枣", "张"),
    "SH": ("CZCE", "烧碱", "张"),
    "SM": ("CZCE", "锰硅", "张"),
    "SF": ("CZCE", "硅铁", "张"),
    # 大连商品交易所
    "m": ("DCE", "豆粕", "手"),
    "y": ("DCE", "豆油", "手"),
    "a": ("DCE", "豆一", "手"),
    "b": ("DCE", "豆二", "手"),
    "p": ("DCE", "棕榈油", "手"),
    "c": ("DCE", "玉米", "手"),
    "jd": ("DCE", "鸡蛋", "手"),
    "lh": ("DCE", "生猪", "手"),
    "l": ("DCE", "塑料", "手"),
    "pp": ("DCE", "聚丙烯", "手"),
    "v": ("DCE", "PVC", "手"),
    "eg": ("DCE", "乙二醇", "手"),
    "eb": ("DCE", "苯乙烯", "手"),
    "pg": ("DCE", "液化气", "手"),
    "i": ("DCE", "铁矿石", "手"),
    "j": ("DCE", "焦炭", "手"),
    "jm": ("DCE", "焦煤", "手"),
    # 广州期货交易所
    "si": ("GFEX", "工业硅", "手"),
    "lc": ("GFEX", "碳酸锂", "手"),
    "ps": ("GFEX", "多晶硅", "手"),
}


# ============================================================
# 仓单数据源URL（交易所官方+第三方聚合）
# ============================================================
WAREHOUSE_SOURCES = {
    "shfe_daily": "https://www.shfe.com.cn/data/dailydata/kx/kx{date}.dat",
    "czce_daily": "http://www.czce.com.cn/cn/ExchangeNotice/DataWarehouseNotice/",
    "dce_daily": "http://www.dce.com.cn/dalianshangpin/xqsj/tjsj26/",
    "smm": "https://news.smm.cn/live/",  # 上海有色网(聚合)
    "99qh": "https://www.99qh.com/article/",  # 99期货(聚合)
    "eastmoney": "https://data.eastmoney.com/",  # 东方财富(聚合)
}


# ============================================================
# 仓单分析引擎
# ============================================================
class WarehouseReceipt:
    """单品种仓单数据点"""

    def __init__(self, symbol: str, data_date: str):
        self.symbol = symbol
        self.data_date = data_date
        exchange_info = EXCHANGE_MAP.get(symbol, ("未知", symbol, "吨"))
        self.exchange = exchange_info[0]
        self.variety_name = exchange_info[1]
        self.unit = exchange_info[2]

        # 当日数据
        self.total_registered: Optional[int] = None    # 总注册仓单
        self.daily_change: Optional[int] = None         # 日增减
        self.daily_change_pct: Optional[float] = None   # 日增减%

        # 趋势数据
        self.week_change: Optional[int] = None           # 近7日变化
        self.week_change_pct: Optional[float] = None
        self.month_change: Optional[int] = None          # 近30日变化
        self.month_change_pct: Optional[float] = None

        # 分位数据
        self.percentile_1y: Optional[float] = None       # 近1年分位数(%)
        self.percentile_3y: Optional[float] = None       # 近3年分位数(%)

        # 交割压力
        self.total_oi: Optional[int] = None              # 总持仓
        self.warrant_oi_ratio: Optional[float] = None    # 仓单/持仓比

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "variety": self.variety_name,
            "data_date": self.data_date,
            "unit": self.unit,
            "total_registered": self.total_registered,
            "daily_change": self.daily_change,
            "daily_change_pct": self.daily_change_pct,
            "week_change": self.week_change,
            "week_change_pct": self.week_change_pct,
            "month_change": self.month_change,
            "month_change_pct": self.month_change_pct,
            "percentile_1y": self.percentile_1y,
            "warrant_oi_ratio": self.warrant_oi_ratio,
        }

    def get_signal(self) -> dict:
        """
        生成仓单信号摘要，供辩论使用。
        
        Returns:
            {
                'direction': 'bearish'/'bullish'/'neutral',
                'strength': 'strong'/'moderate'/'weak',
                'summary': str,  # 一句话总结
                'risk_flags': [str],  # 风险标注
            }
        """
        flags = []
        bearish_score = 0
        bullish_score = 0

        # 日变化方向
        if self.daily_change is not None:
            if self.daily_change > 0:
                bearish_score += 1
                pct_str = f"+{self.daily_change_pct:.1f}%" if self.daily_change_pct else ""
                flags.append(f"日增{self.daily_change}{self.unit}({pct_str}) → 入库压力增加")
            elif self.daily_change < 0:
                bullish_score += 1
                flags.append(f"日减{abs(self.daily_change)}{self.unit} → 仓单注销/提货")

        # 月度趋势
        if self.month_change_pct is not None:
            if self.month_change_pct > 20:
                bearish_score += 3
                flags.append(f"月增{self.month_change_pct:.1f}% → 大量入库，强利空")
            elif self.month_change_pct > 10:
                bearish_score += 2
                flags.append(f"月增{self.month_change_pct:.1f}% → 持续入库，偏空")
            elif self.month_change_pct > 5:
                bearish_score += 1
                flags.append(f"月增{self.month_change_pct:.1f}% → 温和入库")
            elif self.month_change_pct < -20:
                bullish_score += 3
                flags.append(f"月减{abs(self.month_change_pct):.1f}% → 大量出库，强利多")
            elif self.month_change_pct < -10:
                bullish_score += 2
                flags.append(f"月减{abs(self.month_change_pct):.1f}% → 持续出库，偏多")
            elif self.month_change_pct < -5:
                bullish_score += 1
                flags.append(f"月减{abs(self.month_change_pct):.1f}% → 温和出库")

        # 分位数
        if self.percentile_1y is not None:
            if self.percentile_1y > 90:
                bearish_score += 2
                flags.append(f"仓单处于近1年{self.percentile_1y:.0f}%分位 → 历史高位，交割压力大")
            elif self.percentile_1y > 75:
                bearish_score += 1
                flags.append(f"仓单处于近1年{self.percentile_1y:.0f}%分位 → 偏高")
            elif self.percentile_1y < 10:
                bullish_score += 2
                flags.append(f"仓单处于近1年{self.percentile_1y:.0f}%分位 → 历史低位，现货偏紧")
            elif self.percentile_1y < 25:
                bullish_score += 1
                flags.append(f"仓单处于近1年{self.percentile_1y:.0f}%分位 → 偏低")

        # 综合判断
        net = bullish_score - bearish_score
        if net >= 3:
            direction, strength = "bullish", "strong"
        elif net >= 1:
            direction, strength = "bullish", "moderate"
        elif net <= -3:
            direction, strength = "bearish", "strong"
        elif net <= -1:
            direction, strength = "bearish", "moderate"
        else:
            direction, strength = "neutral", "weak"

        # 一句话总结
        parts = [f"{self.variety_name}仓单"]
        if self.total_registered:
            parts.append(f"{self.total_registered}{self.unit}")
        if self.daily_change and self.daily_change != 0:
            sign = "+" if self.daily_change > 0 else ""
            parts.append(f"日{sign}{self.daily_change}")
        if self.month_change_pct:
            sign = "+" if self.month_change_pct > 0 else ""
            parts.append(f"月{sign}{self.month_change_pct:.1f}%")
        summary = "，".join(parts)

        return {
            "direction": direction,
            "strength": strength,
            "summary": summary,
            "risk_flags": flags,
            "bearish_score": bearish_score,
            "bullish_score": bullish_score,
        }


def parse_smm_line(line: str) -> Optional[dict]:
    """
    解析上海有色网仓单日报格式:
    【锡仓单日报】7月7日上期所锡减少49吨至4907吨
    """
    import re
    # 匹配: 【XX仓单日报】date exchange variety change to total unit
    m = re.search(r'【(.+?)仓单日报】\S+?上期所(\S+?)(增加|减少)([\d,]+)吨至([\d,]+)吨', line)
    if m:
        variety = m.group(2)
        direction = m.group(3)
        change = int(m.group(4).replace(",", ""))
        total = int(m.group(5).replace(",", ""))
        return {
            "variety_name": variety,
            "total": total,
            "change": -change if direction == "减少" else change,
        }
    return None


def parse_99qh_html(html: str, symbol: str) -> Optional[dict]:
    """
    解析99期货仓单日报HTML (上期所格式).
    提取总计行的数据.
    """
    import re
    # 匹配 "总计" 行后的数字: 总计 XXXXX  ±YYY
    total_m = re.search(r'总计\s+([\d,]+)\s*([+-]?\d*)', html)
    if total_m:
        total = int(total_m.group(1).replace(",", ""))
        change_str = total_m.group(2)
        change = int(change_str) if change_str else 0
        return {"total": total, "change": change}
    return None


# ============================================================
# 辩论素材生成
# ============================================================
def generate_debate_brief(symbols: List[str], warehouse_data: dict) -> str:
    """
    为辩论生成仓单素材摘要文本，可直接注入辩手/闫判官上下文。
    
    Args:
        symbols: 品种列表
        warehouse_data: {symbol: WarehouseReceipt dict or WarehouseReceipt.to_dict()}
    
    Returns:
        Markdown格式的仓单素材摘要
    """
    lines = ["## 仓单数据（基本面）", ""]

    for sym in symbols:
        key = sym.lower()
        wr = warehouse_data.get(key)
        if wr is None:
            continue

        if isinstance(wr, dict):
            signal = wr.get("signal", {})
            total = wr.get("total_registered")
            unit = wr.get("unit", "吨")
            daily = wr.get("daily_change")
            month = wr.get("month_change_pct")
            pct1y = wr.get("percentile_1y")
        else:
            signal = wr.get_signal()
            total = wr.total_registered
            unit = wr.unit
            daily = wr.daily_change
            month = wr.month_change_pct
            pct1y = wr.percentile_1y

        lines.append(f"### {sym.upper()}")

        # 基础数据
        if total:
            data_str = f"注册仓单: {total:,}{unit}"
            if daily:
                sign = "+" if daily > 0 else ""
                data_str += f" (日{sign}{daily:,})"
            if month:
                sign = "+" if month > 0 else ""
                data_str += f" (月{sign}{month:.1f}%)"
            if pct1y:
                data_str += f" [近1年{pct1y:.0f}%分位]"
            lines.append(f"- {data_str}")

        # 信号
        lines.append(f"- 仓单信号: **{signal['direction']}** ({signal['strength']})")
        lines.append(f"- 总结: {signal['summary']}")

        # 风险标注
        if signal["risk_flags"]:
            for flag in signal["risk_flags"]:
                lines.append(f"  - ⚠️ {flag}")

        lines.append("")

    lines.append("---")
    lines.append("*数据来源: 各交易所仓单日报 (上期所/郑商所/大商所)*")
    return "\n".join(lines)


# ============================================================
# 测试数据（2026-07-09 实际采集）
# 用于验证模块功能，实际使用时应从数据源获取
# ============================================================
def get_sample_data() -> Dict[str, WarehouseReceipt]:
    """获取示例仓单数据（2026-07-09，实际WebSearch采集）"""
    samples = {}

    # SP 纸浆 — 数据源: 99qh + 同花顺
    sp = WarehouseReceipt("sp", "2026-07-09")
    sp.total_registered = 293788
    sp.daily_change = 3416
    sp.daily_change_pct = 1.18
    sp.month_change = 57355
    sp.month_change_pct = 23.05
    sp.percentile_1y = 92  # 近1年高位 (仓单年初仅15万吨级别)
    samples["sp"] = sp

    # SN 锡 — 数据源: SMM 7月7日
    sn = WarehouseReceipt("sn", "2026-07-07")
    sn.total_registered = 4907
    sn.daily_change = -49
    sn.daily_change_pct = -0.99
    sn.month_change = -800  # 估算: 锡仓单近期持续下降
    sn.month_change_pct = -14.0
    sn.percentile_1y = 35  # 偏低
    samples["sn"] = sn

    # NI 镍 — 数据源: SMM 7月7日
    ni = WarehouseReceipt("ni", "2026-07-07")
    ni.total_registered = 98094
    ni.daily_change = 42
    ni.daily_change_pct = 0.04
    ni.month_change = 5000
    ni.month_change_pct = 5.4
    ni.percentile_1y = 55
    samples["ni"] = ni

    # AL 铝 — 数据源: SMM 7月7日
    al = WarehouseReceipt("al", "2026-07-07")
    al.total_registered = 397145
    al.daily_change = -1913
    al.daily_change_pct = -0.48
    al.month_change = -15000
    al.month_change_pct = -3.6
    al.percentile_1y = 75
    samples["al"] = al

    return samples


# ============================================================
# CLI
# ============================================================
def main():
    import sys

    print(f"\n{'='*50}")
    print("期货仓单数据分析 v1.0")
    print(f"{'='*50}\n")

    samples = get_sample_data()

    if len(sys.argv) > 1:
        symbols = [s.lower() for s in sys.argv[1].split(",")]
    else:
        symbols = list(samples.keys())

    for sym in symbols:
        wr = samples.get(sym)
        if wr is None:
            print(f"  {sym}: 无仓单数据")
            continue

        signal = wr.get_signal()
        print(f"\n  {sym.upper()} {wr.variety_name}")
        print(f"    注册仓单: {wr.total_registered:,}{wr.unit} (日{wr.daily_change:+,})")
        if wr.month_change_pct:
            print(f"    月度趋势: {wr.month_change_pct:+.1f}%")
        if wr.percentile_1y:
            print(f"    分位: 近1年{wr.percentile_1y:.0f}%")
        print(f"    信号: {signal['direction']} ({signal['strength']})")
        for flag in signal['risk_flags']:
            print(f"      ⚠️ {flag}")

    # 输出辩论素材
    print("\n" + "="*50)
    brief = generate_debate_brief(symbols, {s: samples[s] for s in symbols if s in samples})
    print(brief)


if __name__ == "__main__":
    main()
