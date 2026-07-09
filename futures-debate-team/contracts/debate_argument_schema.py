"""
辩论论点结构化 Schema — 证真/慎思之间的标准化信息交换格式（v1.0）

目的：
  消除自然语言辩论带来的语义歧义和解析成本。
  每条论据按结构化字段组织，闫判官可直接读取无需文本解析。

用法：
  辩手输出的 JSON 块仅需包含 "meta" + "arguments" 两个顶级键。
  所有可选/必选字段由 TypedDict 约束。不合法则下游拒绝接收。
"""

from typing import TypedDict, Optional, Literal

# ----- 策略族枚举 -----
StrategyFamily = Literal[
    "F1",   # 技术面量价：均线/ADX/RSI/BB/成交量等
    "F2",   # 基本面供需：库存/基差/利润/供需平衡表
    "F3",   # 持仓资金：主力持仓/持仓量变化/净多空比
    "F4",   # 宏观政策：利率/贸易/地缘/产业政策
    "F5",   # 套利结构：跨期价差/跨品种价差/展期收益
]

# ----- 反驳类型枚举 -----
RebuttalType = Literal[
    "因果倒置", "数据过时", "样本偏差",
    "推理跳跃", "忽视反证", "直接质疑证据",
]

# ----- 单条论据 -----
class ArgumentItem(TypedDict, total=False):
    """一条完整的论据"""
    id: str                          # 必填：论据唯一ID（如"证真-D3"）
    family: StrategyFamily           # 策略族标签
    claim: str                       # 一句话可证伪断言
    evidence: str                    # 数据支撑（数值+来源+日期）
    reasoning: str                   # 推理链
    impact: Literal["HIGH", "MEDIUM", "LOW"]  # 重要性
    # -- 以下为反驳/被反驳专用字段 --
    rebuts: Optional[list[str]]      # 反驳的目标论点ID列表（可选）
    rebuttal_type: Optional[str]     # 反驳类型（可选，仅反驳时填写）
    rebuttal_detail: Optional[str]   # 反驳的具体拆解（可选）

# ----- 单轮发言 -----
class ArgumentRound(TypedDict, total=False):
    """一轮辩论发言"""
    round: str                       # 轮次标识（如"RB_20260709_r1"）
    speaker: Literal["zhengzhen", "shensi"]  # 发言人
    phase: Literal["opening", "rebuttal", "free_debate", "final"]
    target: Optional[str]            # re阶段引用的对方论点ID（可选）
    arguments: list[ArgumentItem]    # 本轮论点列表（最少2条，最多5条）
    # -- 可选的防御性字段 --
    concedes: Optional[list[str]]    # 承认对方有效的论点ID列表
    family_coverage: Optional[int]   # 本轮论据覆盖的策略族数

# ----- 完整发言 JSON 结构（顶级） -----
class StructuredDebateArgument(TypedDict):
    """辩手输出的顶层 JSON 结构"""
    meta: dict                       # 包含 phase/agent_name/version/target_symbol
    arguments: list[ArgumentItem]    # 论点列表
