from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseSkillOutput


class DimensionItem(BaseModel):
    dim: str  # 供给 / 需求 / 库存 / 基差 / 宏观
    claim: str  # 核心观点
    evidence: str  # 数据支撑（必须包含可核验数字）
    confidence: float = Field(ge=0, le=1)  # 该维度置信度
    source: str = ""  # 数据来源，可选


class EvidenceItem(BaseModel):
    """结构化证据项 — 便于闫判官回溯"""

    claim_id: str = ""  # 论点ID（如 "证真-D1"），反驳时引用
    point: str  # 论点
    source: str  # "观澜" / "探源" / "链证源"
    weight: float = Field(default=1.0, ge=0, le=1)  # 该证据权重
    # ── 结构化证据要素（辩论质量v2） ──
    evidence_value: str = ""  # 具体数值（如 "35.2万吨"）
    evidence_source: str = ""  # 数据来源机构（如 "Mysteel" / "交易所" / "统计局"）
    evidence_date: str = ""  # 数据截至日期
    impact_level: str = "MEDIUM"  # HIGH / MEDIUM / LOW
    logical_fallacy: str = ""  # 反驳时标注的逻辑漏洞类型
    rebuttal_to: str = ""  # 反驳目标论点ID（空=立论，非空=反驳）


class CounterRisk(BaseModel):
    """主动列出的己方弱点 — 不列则扣分"""

    risk: str  # 弱点描述
    mitigation: str  # 防守理由
    severity: str = "medium"  # low / medium / high


class EntryPlan(BaseModel):
    """交易方案 — 直接供闫判官裁决"""

    price_zone: str  # "6860-6880"
    stop: str  # "6763（观澜锚6850-0.4ATR）"
    target: str  # "7020（观澜hard压力）"
    risk_reward: str  # "1:1.2"


class StructuredDebate(BaseSkillOutput):
    """结构化辩词 v3.0 — 替换平铺的 ArgumentOutput

    核心变化：
    1. thesis: 一句话论点（不是复述数据，是建构叙事）
    2. evidence: 分技术/基本面，标注source（观澜/探源/链证源）
    3. counter_risks: 主动列弱点（不列=闫判官扣分）
    4. entry_plan: 直供给闫判官裁决
    5. rebuttal_strategy: 预判对方主攻方向+防守方案
    """

    role: Literal["证真", "慎思"]
    variant: Literal["bull", "bear"] = "bull"
    symbol: str = ""

    # 一句话论点（核心叙事）
    thesis: str

    # 结构化证据
    evidence: dict = Field(
        default_factory=lambda: {
            "technical": [],
            "fundamental": [],
            "chain": [],
        }
    )  # { "technical": [EvidenceItem], "fundamental": [...], "chain": [...] }

    # 主动承认的己方弱点（不列则扣分）
    counter_risks: List[CounterRisk] = Field(default_factory=list)

    # 交易方案（直接供闫判官裁决）
    entry_plan: Optional[EntryPlan] = None

    # 预判对方攻击方向+己方防守方案
    rebuttal_strategy: List[dict] = Field(default_factory=list)  # [{"attack": "...", "defense": "..."}]

    # 6类交锋适用套路
    engagement_patterns: List[str] = Field(default_factory=list)

    # 整体置信度
    confidence: float = Field(default=0.5, ge=0, le=1)

    # 向后兼容字段
    summary_4_risk: str = ""
    full_text: str = ""


class ArgumentOutput(BaseSkillOutput):
    """原始辩手输出（向后兼容，新代码用 StructuredDebate）"""

    role: Literal["证真", "慎思"]
    variant: Literal["bull", "bear"] = "bull"
    dimensions: list[DimensionItem] = Field(default_factory=list, min_length=5, max_length=10)
    summary_4_risk: str = ""
    full_text: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    rebuttal_targets: list[str] = Field(default_factory=list)


class BullOutput(ArgumentOutput):
    """证真输出 — 向后兼容"""

    role: Literal["证真"] = "证真"
    variant: Literal["bull"] = "bull"


class BearOutput(ArgumentOutput):
    """慎思输出 — 向后兼容"""

    role: Literal["慎思"] = "慎思"
    variant: Literal["bear"] = "bear"


class DebateFeedbackItem(BaseModel):
    """辩论反馈 — 回流给观澜/探源/链证源"""

    target: str  # "观澜" / "探源" / "链证源"
    item: str  # 被挑战的具体项
    challenge: str  # 挑战内容
    winner: str  # "证真" / "慎思"
    action: str  # 改进动作


class DebateResult(BaseModel):
    """完整辩论结果（含反馈链路）"""

    symbol: str
    date: str
    proposition_side: str  # "long" / "short"
    bull_debate: StructuredDebate
    bear_debate: StructuredDebate
    judge_verdict: dict  # 闫判官裁决
    feedback: List[DebateFeedbackItem] = Field(default_factory=list)
    verdict: dict = Field(default_factory=dict)  # 兼容旧格式
    overall: str = ""
