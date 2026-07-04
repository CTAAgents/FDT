"""
策略基类 — 所有打分策略必须实现这个接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalResult:
    """单个品种的打分结果，统一格式"""
    symbol: str
    name: str = ""
    total: float = 0.0              # 带方向总分（正=多头, 负=空头）
    abs_score: float = 0.0          # 绝对分
    direction: str = "neutral"      # "bull" | "bear" | "neutral"
    grade: str = "NOISE"            # "STRONG" | "WATCH" | "WEAK" | "NOISE"
    sub_scores: dict = field(default_factory=dict)   # 层/因子明细 {name: score}
    veto: int = 0                   # 否决计数
    consistency: int = 0            # 子层一致性
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    adx: float = 0.0
    rsi: float = 0.0
    cci: float = 0.0
    ma_slope: float = 0.0
    macd_cross: str = "none"
    dc20_break: str = "none"
    ma_align: str = "mixed"
    z_score: float = 0.0
    stage: str = "unknown"
    _tdx_patched: bool = False
    extra: dict = field(default_factory=dict)   # 策略专属额外字段

    def to_dict(self) -> dict:
        """转平铺 dict，兼容 scan_all.py 输出格式"""
        d = {
            "symbol": self.symbol,
            "name": self.name,
            "price": round(self.price, 1),
            "change_pct": round(self.change_pct, 2),
            "volume": self.volume,
            "total": round(self.total) if isinstance(self.total, (int, float)) else self.total,
            "abs": round(self.abs_score),
            "direction": self.direction,
            "grade": self.grade,
            "adx": round(self.adx, 1),
            "rsi": round(self.rsi, 1),
            "cci": round(self.cci, 1),
            "ma_slope": round(self.ma_slope, 2),
            "macd_cross": self.macd_cross,
            "dc20_break": self.dc20_break,
            "ma_align": self.ma_align,
            "z_score": round(self.z_score, 2),
            "stage": self.stage,
            "_tdx_patched": self._tdx_patched,
            "veto": self.veto,
            "cons": self.consistency,
        }
        # 合并子层分数
        for k, v in self.sub_scores.items():
            d[k] = round(v) if isinstance(v, float) else v
        # 合并额外字段
        d.update(self.extra)
        return d


class BaseStrategy(ABC):
    """所有策略的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略标识符，用于 CLI --strategy 参数"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """策略中文名，用于终端打印"""
        ...

    @abstractmethod
    def score(
        self,
        tech_list: list[dict],
        mode: str = "full",
        kline_data: Optional[dict] = None,
        df_map: Optional[dict] = None,
    ) -> dict:
        """
        对全部品种执行打分。

        参数:
            tech_list: 指标引擎产出的每个品种的 tech dict 列表
            mode: "full" | "custom" 控制输出详略
            kline_data: 原始 K 线数据 {sym: (name, [bar_dict, ...])}，可选
            df_map: pandas DataFrame 映射 {sym: DataFrame}，可选

        返回:
            {
                "all_ranked": [dict, ...],     # 按 abs_score 降序
                "bull_signals": [dict, ...],    # direction=="bull"
                "bear_signals": [dict, ...],    # direction=="bear"
                "_meta": { ... },               # 策略元数据
            }
        """
        ...

    def get_meta_extra(self) -> dict:
        """策略额外的元数据字段，子类可覆盖"""
        return {}
