from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


SCHEMA_VERSION = "3.0"  # P1-1: 协议版本号


class PhaseMeta(BaseModel):
    """每个子 skill 输出的元数据，不进入下游 prompt，仅供编排层排障"""
    phase: str                          # P1 / P2 / P3 / P4 / P5
    agent_name: str                     # 探源 / 观澜 / 链证源 / 证真 / 慎思 / 闫判官 / 风控明 / 策执远
    variant: str                        # 品种代码，如 CU.SHF
    trace_id: str                       # 一次完整辩论的唯一 ID
    depends_on: list[str] = []          # 依赖的上游 phase，如 ["P1_data", "P1_tech"]
    confidence: Optional[float] = None  # 整体置信度
    created_at: datetime = Field(default_factory=datetime.now)
    schema_version: str = SCHEMA_VERSION  # P1-1: 版本号

    class Config:
        extra = 'ignore'  # P1-1: 向前兼容，忽略未知字段


class BaseSkillOutput(BaseModel):
    """所有子 skill 输出的基类"""
    version: Literal["3.0"] = "3.0"  # P1-1: 版本升级
    meta: PhaseMeta

    class Config:
        extra = 'ignore'  # P1-1: 向前兼容，忽略未知字段
