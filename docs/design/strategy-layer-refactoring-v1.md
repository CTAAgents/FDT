# 策略层插拔化重构设计 v1

> 2026-07-14 | 目标版本 v7.0 | 设计评估阶段

---

## 1. 现状问题

| 问题 | 表现 | 根因 |
|:-----|:-----|:------|
| **单策略执行** | scan_all.run_scan() 只调一个 strategy.score() | 主循环硬编码单策略路径 |
| **策略与验证器解耦** | SIGNAL_VALIDATOR_MAP 全局声明，策略不知道自己的验证器 | 验证器路由是 settings.py 的全局配置，非策略自有属性 |
| **无多策略融合** | 无法同时跑趋势+反转+套利+多因子并融合结果 | 没有跨策略得分融合层 |
| **signal_type 无命名空间** | channel_breakout 和 three_signal 产出的 signal_type 会冲突 | 没有策略-信号类型命名空间隔离 |
| **scan_all 主循环不可插拔** | 数据采集→指标计算→策略打分→验证器→JSON 全在一个函数 | 没有插件式的步骤编排器 |
| **策略间无通信/** **依赖管理** | 宏观策略可能需要等待套利策略结果 | 没有策略执行依赖图 |

---

## 2. 目标架构

```
scan_all.py (瘦壳)
  │
  ▼
StrategyPipeline (核心编排器)
  │
  ├─ 1. 数据采集 (FDC) → kline_data + oi_data + basis_data
  │
  ├─ 2. 指标计算 → tech_list (每品种 ADX/RSI/CCI/MA/ATR/Donchian/BB)
  │
  ├─ 3. 策略并行执行 (无依赖的策略可并行)
  │    ├─ trend_following.compute() → trend_following.filter() → trend_following.score()
  │    ├─ mean_reversion.compute()  → mean_reversion.filter()  → mean_reversion.score()
  │    ├─ arbitrage.compute()       → arbitrage.filter()       → arbitrage.score()
  │    ├─ multi_factor.compute()    → multi_factor.filter()    → multi_factor.score()
  │    ├─ macro_regime.compute()    → macro_regime.filter()    → macro_regime.score()
  │    └─ event_driven.compute()    → event_driven.filter()    → event_driven.score()
  │
  ├─ 4. 策略内验证器 (per-strategy)
  │    ├─ trend_following → [p0_4_raw_kline, volume_confirm, atr_vol_timing]
  │    ├─ mean_reversion → [entity_quality, atr_vol_timing]
  │    └─ arbitrage → [atr_vol_timing, stability]
  │
  ├─ 5. 跨策略融合 (StrategyFusion)
  │    ├─ 同品种多策略信号 → 按权重加权融合
  │    ├─ 方向冲突解决 → 高权重策略优先
  │    └─ 全局闸门 → [crowding]
  │
  └─ 6. 输出 → unified all_ranked + per-strategy 明细
```

---

## 3. 核心接口

### 3.1 Strategy 基类（v2，增强版）

```python
class BaseStrategyV2(ABC):
    """v2 策略基类 — 自包含 compute → filter → score 三阶段。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略标识符，全局唯一。如 'trend_following', 'arbitrage'。"""

    @property
    def signal_type(self) -> str:
        """策略产出的信号类型命名空间。默认 = name。"""
        return self.name

    @property
    def validators(self) -> list[str]:
        """该策略产出的信号需要跑哪些验证器。"""
        return []

    @property
    def weight(self) -> float:
        """跨策略融合权重。默认 1.0。"""
        return 1.0

    @property
    def depends_on(self) -> list[str]:
        """依赖的其他策略 name。空列表 = 无依赖。"""
        return []

    @abstractmethod
    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict) -> list[dict]:
        """从技术指标列表计算原始信号（未过滤未打分）。
        
        Returns:
            [ {symbol, direction, signal_type, raw_score, ...}, ... ]
            每个信号必须带 signal_type = self.signal_type
        """

    def filter(self, raw_signals: list[dict], context) -> list[dict]:
        """策略内过滤（轻量版验证器，不是所有策略都需要 V1-V7）。
        默认返回原样。"""
        return raw_signals

    @abstractmethod
    def score(self, filtered_signals: list[dict], tech_list: list[dict],
              context) -> list[SignalResult]:
        """对过滤后的信号进行打分，返回 SignalResult 列表。
        
        打分规则策略自定（趋势用通道分数、反转用 RSI 极端度、
        套利用 Z-score 绝对值、多因子用复合分）。
        """
```

### 3.2 StrategyPipeline

```python
class StrategyPipeline:
    """多策略编排器 — 执行策略图 + 内验证 + 跨策略融合。"""

    def __init__(self, strategies: list[BaseStrategyV2]):
        self.strategies = strategies  # 按依赖拓扑排序
        self._validate_dag()

    def run(self, tech_list, kline_data, context) -> dict:
        """完整流程。"""
        # Phase 1: 按依赖拓扑逐策略执行
        strategy_signals = {}
        for s in self.strategies:
            raw = s.compute(tech_list, kline_data, context)
            filtered = s.filter(raw, context)
            scored = s.score(filtered, tech_list, context)
            strategy_signals[s.name] = scored

        # Phase 2: 策略内验证器（按 signal_type 路由）
        for s in self.strategies:
            for signal in strategy_signals.get(s.name, []):
                for vid in s.validators:
                    validator = get_validator(vid)
                    if validator:
                        validator(signal, context)

        # Phase 3: 跨策略融合
        fused = self._fuse(strategy_signals, context)

        # Phase 4: 全局闸门
        for vid in GLOBAL_VALIDATORS:  # ["crowding"]
            validator = get_validator(vid)
            if validator:
                validator(fused, context)

        return self._package(fused, strategy_signals)
```

### 3.3 StrategyFusion

```python
class StrategyFusion:
    """跨策略得分融合策略。"""

    def fuse(self, all_strategy_outputs: dict[str, list[SignalResult]],
             context) -> list[SignalResult]:
        """多种融合策略可选。"""
        # 策略 1: 最大权值法 — 同品种取权重最高的策略的分数
        # 策略 2: 加权平均法 — 同品种多策略分数按 weight 加权
        # 策略 3: 信号层叠加 — 保留多策略独立信号，打标 strategy_tag
        # 策略 4: 冲突降级 — 方向冲突时，高权重策略覆盖低权重
        ...

    def _resolve_conflicts(self, symbol_signals: list[SignalResult]) -> SignalResult:
        """方向冲突解决。"""
        # 按 weight 降序 → 取最高权重的方向
        # 同权重 → 取 abs_score 更高的
```

---

## 4. 数据流规范

### 4.1 信号格式（每个策略产出的原始信号）

```python
@dataclass
class RawSignal:
    symbol: str
    direction: str              # "bull" | "bear" | "neutral"
    signal_type: str            # 带策略命名空间, e.g. "trend_following.channel_breakout"
    raw_score: float            # 策略内部原始分（未归一化）
    strategy_name: str          # 来源策略
    meta: dict                  # 策略自定义字段
```

### 4.2 验证器输入的信号格式（与 RawSignal 兼容）

验证器仍然消费 `dict`（当前 all_ranked 中的 dict），扩展 strategy 字段：

```python
{
    "symbol": "RB",
    "direction": "bear",
    "signal_type": "trend_following.channel_breakout",  # 带命名空间
    "total": -38,
    "_raw_total": -38,
    "grade": "WEAK",
    "strategy": "trend_following",   # ← 新增
    "adx": 26.2,
    "price": 3100,
    ...
}
```

### 4.3 融合后的输出格式

```python
{
    "all_ranked": [
        {
            "symbol": "RB",
            "direction": "bear",
            "total": -38,           # 融合后的总分
            "grade": "WEAK",
            "strategy_breakdown": {  # ← 新增
                "trend_following": {"total": -38, "weight": 1.0},
                "arbitrage": {"total": -12, "weight": 0.5},
            },
            "adx": 26.2,
            ...
        },
        ...
    ],
    "per_strategy": {              # ← 新增，各策略独立输出
        "trend_following": {"all_ranked": [...], "_meta": {...}},
        "arbitrage": {"all_ranked": [...], "_meta": {...}},
        ...
    },
    "_meta": {
        "strategies_run": ["trend_following", "arbitrage", ...],
        "fusion_method": "weighted_max",
        ...
    }
}
```

---

## 5. 信号类型命名空间（解除 signal_type 冲突）

当前 `signal_type` 是平铺的，多个策略可能产出一致的 `signal_type` 值。

新规：

```
signal_type = "{strategy_name}.{strategy_defined_signal}"
              │              │
              │              └─ 策略内部定义的信号子类型
              │
              └─ 策略标识符（全局唯一）
```

| 策略 name | signal_type 示例 |
|:----------|:-----------------|
| `trend_following` | `trend_following.dc20_breakout`, `trend_following.bb_squeeze` |
| `mean_reversion` | `mean_reversion.rsi_extreme`, `mean_reversion.bb_reversal` |
| `arbitrage` | `arbitrage.calendar_spread`, `arbitrage.pair_zscore` |
| `multi_factor` | `multi_factor.carry`, `multi_factor.momentum` |
| `macro_regime` | `macro_regime.risk_on`, `macro_regime.sector_rotation` |

验证器用无命名空间版本匹配（只匹配 `signal_type` 后缀部分），或者策略显式声明。

---

## 6. 迁移路径

### Phase A — 接口层（v6.4）

- 新建 `strategies/base_v2.py`（BaseStrategyV2 接口）
- 新建 `strategies/pipeline.py`（StrategyPipeline + StrategyFusion）
- 不改变现有 scan_all.py、channel_breakout_strategy.py 等
- 全部代码是新增，零修改
- 测试：新增 `tests/strategies/test_pipeline.py`

### Phase B — 现有策略适配（v6.5）

- `ChannelBreakoutStrategy` 适配为 BaseStrategyV2 子类
- 验证器路由从 `SIGNAL_VALIDATOR_MAP` 迁移到策略的 `validators` 属性
- `scan_all.py` 新增 `--pipeline` 模式（可选，不破坏现有 `--strategy`）

### Phase C — 新策略填充（v6.6-v6.9）

- `ArbitrageStrategy`（跨期+跨品种）
- `MeanReversionStrategy`（RSI反转+布林带反转）
- `MacroRegimeStrategy`（宏观制度因子）
- `EventDrivenStrategy`（事件日历）
- `MlSignalStrategy`（XGB/LGBM/ONNX）

### Phase D — scan_all 主循环通用化（v7.0）

- `run_scan()` 主循环重写：
  - [1] 数据采集 → [2] 指标计算 → [3] StrategyPipeline.run() → [4] JSON/HTML 输出
  - 移除/废弃单策略 `--strategy` 参数
  - 默认模式 = `--pipeline`（全部已注册策略）
  - 可选模式 = `--pipeline-strategies trend_following,arbitrage`

---

## 7. 向后兼容

| 需要保留 | 弃用时间线 |
|:---------|:-----------|
| `BaseStrategy` (v1) + `registry.py` | Phase D 完成后标记 @deprecated |
| `SIGNAL_VALIDATOR_MAP` | Phase B 完成后标记 @deprecated |
| `scan_all.py --strategy X` 参数 | Phase D 完成后移除 |
| `run_scan()` 现有输出格式 | **永久保留**（兼容下游 debate 管线）— 扩展 fields 不删旧 fields |
