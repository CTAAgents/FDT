# P2.5 多因子注入扩展方案

## 背景

FDT 当前在 P2.5 阶段通过 `node_prepare_data()` 采集 K 线 + 基本面 + 新闻数据，各 Agent 消费对应因子：

**目标**：不新增 Agent，通过扩展 P2.5 数据注入层，让 FDT 的第二层自然成为多因子整合器。

## 核心设计原则

1. **零新增 Agent** — 所有新因子通过 `node_prepare_data()` 采集，注入 state 供现有 Agent 消费
2. **因子互斥** — 每个因子只注入一个 Agent 的 prompt，不重复
3. **AKShare 优先** — 新因子数据优先使用已有数据源
4. **纯计算优先** — 能从 K 线直接计算的因子零外部依赖
5. **因子看板统一输出** — P5 终裁上下文注入因子信号一致性看板，闫判官做综合裁决

## 因子可行性评估

基于 FDT 当前数据源能力对候选因子逐一评估：

| 因子 | 数据源 | 可行性 | 说明 |
|:-----|:-------|:------:|:------|
| **波动率**（HV/偏度/ATR） | K线自算 | **✅ 可用** | 纯 numpy 计算，已有 K 线数据，零外部依赖 |
| **跨品种价差**（Z-Score） | K线自算 | **✅ 可用** | 纯计算，零外部依赖 |
| **期限结构**（基差/升贴水） | AKShare `futures_zh_realtime()` | **✅ 已集成** | 合约序列已有，已有Agent消费中 |
| **多空持仓**（多空比+前20排名） | AKShare `futures_hold_pos_sina()` + 各交易所持仓排名 | **⚠️ 部分可用** | 可获取持仓多空比（存量）和前20排名。**无法获取日内资金净流入**（期货市场无此 API） |
| **社区情绪**（雪球/股吧） | 无稳定免费API | **❌ 暂不可行** | 需外部采购或爬虫方案，本期搁置 |

**修正**：原方案中的"资金流因子"更名为"多空持仓因子"以准确反映实际数据能力。

## 最终因子分配

| Agent | 当前消费的因子 | 新增注入因子 |
|:------|:--------------|:-------------|
| 观澜（技术面） | K线 + 技术指标 | 波动率 |
| 探源（基本面） | 期限结构 + 基差 + 仓单 + 持仓排名 | 多空持仓排名 |
| 链证源（产业链） | 品种产业链映射 | 跨品种价差 |
| 读心（情绪） | 新闻情绪（多源聚合） | — |
| 闫判官（终裁） | 六维评分 + 辩论论据 | 多因子信号一致性看板 |

## 架构图

```
P2.5 node_prepare_data() 扩展
═══════════════════════════════════════════════════════

┌── 已有采集 ──────────────────────────────────────┐
│  AKShare K线  →  state["kline"]                 │  →  _build_technical_context()   →  观澜
│  AKShare F10  →  state["fdc_data"]              │  →  _build_fundamental_context()  →  探源
│  NewsRouter   →  state["sentiment_data"]         │  →  node_sentiment prompt        →  读心
│  ChainRouter  →  state["chain_data"]             │  →  node_chain prompt             →  链证源
└──────────────────────────────────────────────────┘

┌── 新增采集（data_adapter/factors/） ─────────────┐
│  TermStructure  →  state["factor_term_structure"] │  →  探源沿用 + 因子看板采集信号        │
│  Volatility     →  state["factor_volatility"]     │  →  _build_technical_context()   →  观澜
│  HoldingSentiment → state["factor_holding_sentiment"] │ →  _build_fundamental_context() →  探源
│  CrossSpread    →  state["factor_cross_spread"]   │  →  _build_chain_context()       →  链证源
│  FactorDashboard → state["factor_dashboard"]      │  →  node_verdict prompt           →  闫判官
└──────────────────────────────────────────────────┘
```

## 数据模块设计

### 1. 期限结构因子（→ 探源已有 + 因子看板采集信号）

期限结构因子（基差、升贴水、曲线形态）当前已由 `_build_fundamental_context()` 注入探源。
**不重复注入观澜**。P2.5 独立采集一份 `state["factor_term_structure"]`，用途为：

1. 探源 context builder 沿用已有逻辑，不做变更
2. 因子看板（dashboard）从中读取方向信号，参与一致性评分

数据源：`ak.futures_zh_realtime()` 合约序列 → `get_term_structure()`

```python
@dataclass
class TermStructureResult:
    """期限结构因子"""
    symbol: str
    basis: float | None          # 现货 - 期货
    basis_ratio: float | None    # 基差率
    near_contract: str
    far_contract: str
    spread: float | None         # 远月 - 近月
    spread_ratio: float | None   # 升贴水率
    curve_type: str              # backwardation / contango / flat
    curve_slope: float | None    # 曲线斜率
    delivery_month: str | None
    days_to_delivery: int | None
```

### 2. 波动率因子（→ 观澜）

从已有 K 线数据计算，无需额外 API：

```python
@dataclass
class VolatilityResult:
    """波动率因子"""
    symbol: str
    hv_5: float     # 5日历史波动率
    hv_20: float    # 20日历史波动率
    hv_60: float    # 60日历史波动率
    skewness: float # 收益率偏度（正偏/负偏）
    kurtosis: float # 收益率峰度（肥尾/薄尾）
    max_drawdown: float  # 区间最大回撤
    atr: float      # 平均真实波幅
    atr_pct: float  # ATR占价格百分比
```

注入到观澜的技术分析上下文：

```
【波动率因子】
RB: HV5=18.2%, HV20=22.5%, HV60=25.1%, 偏度=-0.32(负偏), 峰度=3.8(肥尾), ATR=42(1.2%)
含义: 短期波动率低于中长期，市场处于降波阶段；负偏暗示下行风险更大
```

### 3. 多空持仓因子（→ 探源）

数据源：
- `ak.futures_hold_pos_sina()` — 总持仓量、多空持仓、多空比
- `ak.futures_stock_shfe_js()` — 上期所前20会员持仓
- `ak.futures_dce_position_rank()` — 大商所前20会员持仓
- `ak.futures_gfex_position_rank()` — 广期所前20会员持仓

**注意**：此为**持仓存量指标（多空比）**，而非日内资金净流入流量。期货市场无类似股票北向资金的 API 可用。

```python
@dataclass
class HoldingSentimentResult:
    """多空持仓因子"""
    symbol: str
    # 全市场持仓
    total_long: int              # 多头总持仓
    total_short: int             # 空头总持仓
    long_short_ratio: float      # 多空持仓比
    long_change: int             # 多单日变化
    short_change: int            # 空单日变化
    # 前20会员持仓（交易所维度，部分品种可用）
    top20_long: int | None       # 前20多单合计
    top20_short: int | None      # 前20空单合计
    top20_ratio: float | None    # 前20多空比
```

注入到探源的基本面上下文：

```
【多空持仓因子】
RB: 全市场多空比 1.09（多单+12,000 / 空单-5,000）
    前20: 多单 325,000手 / 空单 298,000手, 多空比 1.09
    解读: 多单增空单减, 大户偏多
```

### 4. 跨品种价差（→ 链证源）

从已有 K 线数据计算配对价差：

```python
@dataclass
class CrossSpreadResult:
    """跨品种价差"""
    pair: tuple[str, str]        # 品种对 (如 "RB", "HC")
    current_spread: float        # 当前价差
    historical_mean: float       # N日历史均值
    historical_std: float        # N日历史标准差
    zscore: float                # Z-Score（当前偏离程度）
    percentile: float            # 当前价差在历史中的百分位
    trend: str                   # widening / narrowing / stable
```

**预定义品种对**（在 `FACTOR_PAIRS` 中配置）：

| 品种对 | 关系 |
|:-------|:-----|
| RB - HC | 螺纹-热卷（同材不同型） |
| J - JM | 焦炭-焦煤（上下游） |
| M - RM | 豆粕-菜粕（替代品） |
| Y - P | 豆油-棕榈油（替代品） |
| SC - FU | 原油-燃料油（上下游） |
| TA - EG | PTA-乙二醇（聚酯产业链） |
| MA - PP | 甲醇-PP（MTO 化工链） |

注入到链证源的产业链上下文：

```
【跨品种价差】
RB-HC: 当前价差 185, 历史均值 220, Z-Score = -1.2 (偏低)
       历史百分位 22%, 趋势 narrowing
       含义: 螺纹相对热卷偏弱，卷螺价差回归中
```

### 5. 因子一致性看板（→ 闫判官）

```python
@dataclass
class FactorSignal:
    symbol: str
    direction: int    # -2 强烈看空, -1 看空, 0 中性, +1 看多, +2 强烈看多
    strength: float   # 0.0 ~ 1.0
    source: str       # 因子名称

@dataclass
class FactorDashboardResult:
    """多因子信号一致性看板"""
    symbols: list[str]
    signals: dict[str, list[FactorSignal]]  # {symbol: [signals]}
    consensus: dict[str, int]               # {symbol: 方向汇总}
    divergence: dict[str, float]            # {symbol: 分歧度 0~1}
```

注入到闫判官终裁上下文：

```
【多因子信号一致性看板】
| 品种 | 量价 | 基本面 | 情绪 | 多空持仓 | 期限结构 | 产业链 | 汇总 | 分歧度 |
|:-----|:----:|:------:|:----:|:--------:|:---------:|:------:|:----:|:------:|
| RB   | +2   | +1     | -1   | +1       | +1       | 0      | +4   | 0.28  |
| FU   | -1   | -2     | 0    | -1       | -1       | -1     | -5   | 0.12  |
| TA   | 0    | +1     | +1   | 0        | +1       | +1     | +3   | 0.18  |

分歧度 < 0.2 → 因子共振，高确信度
分歧度 0.2~0.5 → 因子分歧，需辩论揭示关键矛盾
分歧度 > 0.5 → 极度分歧，降低置信度
```

## 数据流

### P2.5 采集阶段（`node_prepare_data` 中扩展）

```python
async def node_prepare_data(state: DebateState) -> dict:
    """P2.5 数据预采集（扩展为多因子聚合器）。"""
    # ── 已有采集 ──
    kline_result = await _collect_klines(selected)
    fdc_result = await _collect_fdc_data(selected)

    # ── 新增因子采集（并行执行） ──
    term_structure = await _collect_term_structure(selected)       # 期限结构
    holding_sentiment = await _collect_holding_sentiment(selected)  # 多空持仓
    volatility = _compute_volatility(kline_result)                  # 波动率（从K线算）
    cross_spread = _compute_cross_spreads(selected, kline_result)  # 跨品种价差
    factor_dashboard = _build_factor_dashboard(state)               # 因子看板

    return {
        "kline": kline_result,
        "fdc_data": fdc_result,
        "factor_term_structure": term_structure,
        "factor_holding_sentiment": holding_sentiment,
        "factor_volatility": volatility,
        "factor_cross_spread": cross_spread,
        "factor_dashboard": factor_dashboard,
    }
```

### P3 各 Agent 消费阶段

各 Agent 的 context builder 从 `state["factor_*"]` 中提取对应因子数据，注入 prompt：

```
观澜   prompt = _build_technical_context()    + 【波动率因子】区块
探源   prompt = _build_fundamental_context()  + 【多空持仓因子】区块（期限结构沿用已有）
链证源 prompt = _build_chain_context()        + 【跨品种价差】区块
闫判官 prompt = 辩论论据 + 【多因子信号一致性看板】
```

## 降级策略

| 因子 | 数据源不可用时 | 超时阈值 |
|:-----|:--------------|:---------|
| 期限结构 | 跳过该因子区块，不阻断流程 | 10s |
| 多空持仓 | 跳过该因子区块，不阻断流程 | 10s |
| 波动率 | 直接从 K 线计算，永不失败 | 0s（纯计算） |
| 跨品种价差 | 直接从 K 线计算，永不失败 | 0s（纯计算） |
| 因子看板 | 部分因子缺失时标注"数据不足" | 0s（聚合操作） |

## 实施阶段

### Phase 1: 数据适配层

| 文件 | 内容 |
|:-----|:-----|
| `data_adapter/factors/__init__.py` | `FactorCollector` 入口，统一调用各因子采集器 |
| `data_adapter/factors/types.py` | `TermStructureResult`, `VolatilityResult`, `HoldingSentimentResult`, `CrossSpreadResult`, `FactorDashboardResult` |
| `data_adapter/factors/term_structure.py` | 从 AKShare 获取多合约数据，计算基差/升贴水/曲线形态 |
| `data_adapter/factors/volatility.py` | 从 K 线计算波动率/偏度/峰度/ATR（纯计算，无外部依赖） |
| `data_adapter/factors/holding_sentiment.py` | 从 AKShare 获取多空持仓比和前20排名 |
| `data_adapter/factors/cross_spread.py` | 从 K 线计算配对价差/Z-Score（纯计算，无外部依赖） |
| `data_adapter/factors/dashboard.py` | 汇总所有因子信号，生成一致性看板 |

### Phase 2: nodes.py 注入改造

| 修改位置 | 内容 |
|:---------|:-----|
| `node_prepare_data()` | 新增 4 个因子采集调用 + state 注入 |
| `_build_technical_context()` | 新增波动率因子区块 |
| `_build_fundamental_context()` | 新增多空持仓因子区块（期限结构沿用已有） |
| `_build_chain_context()` | 新增跨品种价差因子区块 |
| `node_verdict()` | 新增因子一致性看板区块 |

### Phase 3: 测试 + 文档

| 文件 | 内容 |
|:-----|:-----|
| `tests/data_adapter/factors/test_term_structure.py` | 期限结构计算测试 |
| `tests/data_adapter/factors/test_volatility.py` | 波动率计算测试 |
| `tests/data_adapter/factors/test_cross_spread.py` | 跨品种价差测试 |
| `docs/harness/01-architecture.md` | 更新 P2.5 数据流图 |
| `docs/harness/03-configuration.md` | 新增因子配置项 |

## 配置项

```yaml
# config/schema.py / decode_config.yaml 中新增

FACTOR_TERM_STRUCTURE_ENABLED: true     # 期限结构因子开关
FACTOR_HOLDING_SENTIMENT_ENABLED: true  # 多空持仓因子开关
FACTOR_VOLATILITY_ENABLED: true         # 波动率因子开关
FACTOR_CROSS_SPREAD_ENABLED: true       # 跨品种价差开关
FACTOR_DASHBOARD_ENABLED: true          # 因子看板开关

# 跨品种价差预定义配对（可配置）
FACTOR_PAIRS:
  - ["RB", "HC"]
  - ["J", "JM"]
  - ["M", "RM"]
  - ["Y", "P"]
  - ["SC", "FU"]
  - ["TA", "EG"]
  - ["MA", "PP"]

# 波动率计算参数
VOLATILITY_HV_PERIODS: [5, 20, 60]     # 波动率计算周期
VOLATILITY_ATR_PERIOD: 14              # ATR 计算周期
```

## 与已有架构的关系

```
已有                             新增
data_adapter/news/              data_adapter/factors/
  ├── routes/                      ├── types.py
  ├── sources/                     ├── term_structure.py
  ├── types.py                     ├── volatility.py
  └── __init__.py                  ├── holding_sentiment.py
                                   ├── cross_spread.py
data_adapter/cleaning/             ├── dashboard.py
  └── ...                          └── __init__.py
```

两个数据模块互不依赖，`factors/` 的 K 线计算依赖 `state["kline"]`（已在 state 中）。

## 风险与注意事项

1. **Prompt 膨胀**：每个因子区块约 200-400 字符，3 个新因子区块约 1K 字符。需要在 `_build_xxx_context()` 中控制区块长度
2. **数据过期**：AKShare 的持仓排名为日频，当天非交易时段返回的是最近交易日数据
3. **配对价差噪音**：非活跃合约的 K 线可能不连续，需过滤 `< 30` 根 K 线的配对
4. **CZCE 持仓缺失**：郑商所无持仓排名 API，涉及品种的持仓因子跳过
5. **因子看板主观性**：因子信号的方向量化（`-2 ~ +2`）依赖业务规则，初期使用简单阈值规则

## 后续演进

- **Phase 4**: SentiRouter（社区情绪），需要找到稳定数据源后再接入
- **Phase 5**: 因子归因分析（Evolution Graph 中评估各因子对最终裁决的贡献度）
- **Phase 6**: 因子自适应权重（RHI 层面优化因子权重分配）
