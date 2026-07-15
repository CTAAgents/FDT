"""A2A (Agent-to-Agent) 协议兼容常量与类型定义。

所有公开 API 的返回值统一包装为 :class:`A2APayload` / :class:`A2ABatchPayload`，
确保任意 Agent 系统能够无歧义地消费数据。

设计原则：
    - 数据与格式分离：``data`` 为纯业务数据，``meta`` 为元信息。
    - 每块数据自描述：``type`` + ``meta`` 足以让任意 Agent 理解内容。
    - 等级标签驱动行为：``data_grade_label`` 是 Agent 路由决策核心字段。
    - 兼容现有 JSON 消费方：忽略外层信封、直接读 ``data`` 即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ───────────────────────────────────────────────────────────
# 数据等级 (L0-L5)
# ───────────────────────────────────────────────────────────
DATA_GRADE = {
    "PRIMARY": 0,      # 主数据源直取，T+0
    "FRESH": 1,        # 当日更新，小时级
    "DAILY": 2,        # 上一交易日
    "CACHED": 3,       # 缓存数据，标注时间
    "REFERENCE": 4,    # 参考级非实时
    "UNAVAILABLE": 5,  # 当前不可用
}

# 反向映射：label(int) -> 名称
DATA_GRADE_NAME = {v: k for k, v in DATA_GRADE.items()}


# ───────────────────────────────────────────────────────────
# 运行模式
# ───────────────────────────────────────────────────────────
RUNTIME_MODES = {
    "INDEPENDENT": "independent",
    "LLM_ENHANCED": "llm_enhanced",
    "LLM_DRIVEN": "llm_driven",
}


# ───────────────────────────────────────────────────────────
# 数据类型标识 (A2A data.type)
# ───────────────────────────────────────────────────────────
DATA_TYPES = {
    "KLINE": "fdc.kline",
    "QUOTE": "fdc.quote",
    "TERM_STRUCTURE": "fdc.term_structure",
    "SPREAD": "fdc.spread",
    "BASIS": "fdc.basis",
    "WARRANT": "fdc.warrant",
    "MACRO": "fdc.macro",
    "FUNDAMENTAL": "fdc.fundamental",
    "F10": "fdc.f10",
    "SENTIMENT": "fdc.sentiment",
    "INDICATORS": "fdc.indicators",
    "SYMBOLS": "fdc.symbols",
    "BATCH": "fdc.batch",
}


def _default_meta() -> dict:
    """生成默认 meta 字典（每次返回新对象，避免共享可变状态）。"""
    return {
        "data_grade": "PRIMARY",
        "data_grade_label": 0,
        "sources": [],
        "cached_at": None,
        "llm_used": False,
        "warnings": [],
        "a2a_compatible": True,
    }


@dataclass
class A2APayload:
    """A2A 兼容数据信封。

    Attributes:
        type: 数据类型标识，如 ``fdc.basis``，Agent 据此路由。
        runtime_mode: ``independent`` / ``llm_enhanced`` / ``llm_driven``。
        meta: 元信息（数据等级、来源、时效、LLM 标记等）。
        data: 纯业务数据。
        summary: 自然语言摘要（映射到 A2A text.text）。
    """

    type: str
    runtime_mode: str
    data: dict
    summary: str = ""
    meta: dict = field(default_factory=_default_meta)

    def set_grade(self, name: str) -> "A2APayload":
        """按等级名称设置 ``data_grade`` 与 ``data_grade_label``。

        Args:
            name: ``DATA_GRADE`` 中的键（如 ``"PRIMARY"``）。

        Returns:
            自身，便于链式调用。

        Raises:
            ValueError: 未知等级名称。
        """
        if name not in DATA_GRADE:
            raise ValueError(f"未知数据等级: {name!r}, 可选: {list(DATA_GRADE)}")
        self.meta["data_grade"] = name
        self.meta["data_grade_label"] = DATA_GRADE[name]
        return self

    def add_warning(self, message: str) -> "A2APayload":
        """追加一条降级/异常警告。"""
        self.meta["warnings"].append(message)
        return self

    def to_dict(self) -> dict:
        """序列化为 A2A 兼容的 dict。"""
        return {
            "type": self.type,
            "runtime_mode": self.runtime_mode,
            "meta": self.meta,
            "data": self.data,
            "summary": self.summary,
        }


@dataclass
class A2ABatchPayload:
    """批量数据信封，包裹多个 :class:`A2APayload`。"""

    type: str
    runtime_mode: str
    data: list = field(default_factory=list)
    summary: str = ""
    stats: dict = field(default_factory=dict)
    meta: dict = field(default_factory=lambda: {"a2a_compatible": True})

    def add(self, payload: A2APayload) -> "A2ABatchPayload":
        """追加单个 payload。"""
        self.data.append(payload)
        return self

    def to_dict(self) -> dict:
        """序列化为 A2A 兼容的 dict（``data`` 内元素已展开为 dict）。"""
        return {
            "type": self.type,
            "runtime_mode": self.runtime_mode,
            "meta": self.meta,
            "data": [p.to_dict() if isinstance(p, A2APayload) else p for p in self.data],
            "stats": self.stats,
            "summary": self.summary,
        }
