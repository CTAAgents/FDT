from pydantic import BaseModel, Field
from typing import Literal
from .base import BaseSkillOutput


class ContractPrice(BaseModel):
    contract: str       # 合约代码，如 CU2409
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int


class DataCollectionOutput(BaseSkillOutput):
    """数聚石的输出：行情数据采集结果"""
    variant: Literal["futures_data"]
    contracts: list[str]                    # 本次分析的合约列表
    prices: dict[str, ContractPrice]        # 合约代码 → 价格数据
    key_levels: dict[str, float]            # 关键价位，如 {"support": 72000, "resistance": 75000}
    validation_status: Literal["pass", "partial", "fail"]
    raw_df_uri: str = ""                    # 大数据集的 URI，不进 prompt
