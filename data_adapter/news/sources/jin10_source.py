"""金十 MCP 新闻源 — 包装现有 jin10_adapter，产出统一 NewsItem。"""
from __future__ import annotations

import logging
from typing import Optional

from ..types import NewsItem, NewsQuery, NewsResult, NewsSourceType
from . import NewsSourceBase

logger = logging.getLogger(__name__)

# ── 品种 → 中文关键词映射（归集到此处，与 nodes.py 同步） ──
SYMBOL_TO_KEYWORDS: dict[str, list[str]] = {
    "RB": ["螺纹钢", "螺纹"], "HC": ["热卷", "热轧"], "I": ["铁矿石", "铁矿"],
    "J": ["焦炭"], "JM": ["焦煤"], "SM": ["硅锰", "锰硅"], "SF": ["硅铁"],
    "CU": ["沪铜", "铜"], "AL": ["沪铝", "铝"], "ZN": ["沪锌", "锌"],
    "PB": ["沪铅", "铅"], "NI": ["沪镍", "镍"], "SN": ["沪锡", "锡"],
    "SC": ["原油", "上海原油"], "FU": ["燃料油"], "BU": ["沥青"],
    "RU": ["橡胶"], "TA": ["PTA", "精对苯二甲酸"], "EG": ["乙二醇"],
    "MA": ["甲醇"], "PP": ["聚丙烯", "PP"], "L": ["聚乙烯", "PE", "塑料"],
    "V": ["PVC", "聚氯乙烯"], "UR": ["尿素"], "SA": ["纯碱"],
    "M": ["豆粕"], "RM": ["菜粕"], "Y": ["豆油"], "P": ["棕榈油", "棕榈"],
    "OI": ["菜油"], "A": ["豆一", "大豆"], "B": ["豆二"],
    "C": ["玉米"], "CS": ["淀粉", "玉米淀粉"], "PK": ["花生"],
    "AP": ["苹果"], "CF": ["棉花", "郑棉"], "SR": ["白糖", "白砂糖"],
    "JD": ["鸡蛋"], "LH": ["生猪"],
    "SH": ["烧碱", "液碱"],
    "OP": ["双胶纸", "胶版印刷纸", "胶印纸"],
    "PG": ["液化石油气", "LPG", "液化气"],
    "EC": ["欧线", "集运", "集装箱运价", "欧洲航线"],
    "BU": ["沥青"],
    "LU": ["低硫燃料油"],
    "NR": ["20号胶", "20号橡胶"],
}
_DEFAULT_KEYWORDS = ["期货", "大宗商品", "商品市场"]


def _get_keywords(symbol: str) -> list[str]:
    return SYMBOL_TO_KEYWORDS.get(symbol.upper(), _DEFAULT_KEYWORDS)


class Jin10NewsSource(NewsSourceBase):
    """金十 MCP 新闻源 — 通过 jin10_search_flash 获取快讯。"""

    @property
    def source_name(self) -> str:
        return "jin10"

    @property
    def priority(self) -> int:
        return 10  # 最高优先级

    async def fetch(self, query: NewsQuery) -> NewsResult:
        result = NewsResult()
        try:
            from data_adapter.sources.jin10_adapter import jin10_search_flash, jin10_available
        except ImportError:
            result.errors.append("jin10_adapter 模块未加载")
            return result

        if not jin10_available():
            result.errors.append("金十 MCP 不可用（JIN10_MCP_TOKEN 未配置）")
            return result

        seen_texts: set[str] = set()
        for sym in query.symbols:
            keywords = _get_keywords(sym)
            for kw in keywords:
                try:
                    raw = await jin10_search_flash(kw)
                    items = raw.get("items", []) if isinstance(raw, dict) else []
                except Exception as e:
                    logger.warning("[Jin10News] 搜索 %s 失败: %s", kw, e)
                    continue

                for item in items:
                    text = (item.get("content") or item.get("title") or "").strip()
                    if not text or text in seen_texts:
                        continue
                    seen_texts.add(text)
                    news_item = NewsItem(
                        symbol=sym.upper(),
                        source_type=NewsSourceType.JIN10,
                        source_name="金十快讯",
                        title=text[:80],
                        content=text,
                        time=item.get("time", ""),
                        confidence=0.8,
                        url="",
                        event_type=_classify_event(text),
                    )
                    result.items.append(news_item)

        # fallback: 关键词搜索无结果时，拉取全量快讯后按品种关键词过滤
        if not result.items:
            try:
                from data_adapter.sources.jin10_adapter import jin10_list_flash
                raw = await jin10_list_flash()
                all_items = raw.get("items", []) if isinstance(raw, dict) else []
                for sym in query.symbols:
                    sym_keywords = _get_keywords(sym)
                    for item in all_items:
                        text = (item.get("content") or item.get("title") or "").strip()
                        if not text or text in seen_texts:
                            continue
                        # 检查快讯内容是否包含品种关键词
                        if not any(kw.lower() in text.lower() for kw in sym_keywords):
                            continue
                        seen_texts.add(text)
                        result.items.append(NewsItem(
                            symbol=sym.upper(),
                            source_type=NewsSourceType.JIN10,
                            source_name="金十快讯",
                            title=text[:80],
                            content=text,
                            time=item.get("time", ""),
                            confidence=0.7,
                            url="",
                            event_type=_classify_event(text),
                        ))
            except Exception as e:
                logger.warning("[Jin10News] list_flash fallback 失败: %s", e)

        result.source_stats[self.source_name] = len(result.items)
        result.total_count = len(result.items)
        return result


def _classify_event(text: str) -> str:
    """基于关键词的简单事件分类（与 SentimentStateVector 的 event_type 对齐）"""
    t = text.lower()
    if any(kw in t for kw in ("政策", "监管", "限产", "出口退税", "抛储", "关税", "补贴")):
        return "policy"
    if any(kw in t for kw in ("库存", "供需", "产量", "开工", "港口", "到港", "发货", "供应", "需求")):
        return "supply_demand"
    if any(kw in t for kw in ("利率", "cpi", "ppi", "gdp", "pmi", "宏观", "汇率", "货币")):
        return "macro"
    if any(kw in t for kw in ("制裁", "冲突", "军事", "地缘", "贸易战", "关税")):
        return "geopolitics"
    return "other"
