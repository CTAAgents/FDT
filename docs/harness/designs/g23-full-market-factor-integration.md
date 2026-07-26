# G23: 全市场因子驱动改进计划

> **版本**: v0.1 (设计草案)
> **日期**: 2026-07-26
> **关联**: G22 多循环协作 / G21 Harness 自适应优化

---

## 1. 问题陈述

FDT 当前为纯期货专用系统。两大核心局限阻碍了系统向通用投资决策平台的演进：

**局限一 — 品种覆盖面窄**：品种分类器 `instrument_classifier.py` 仅定义 4 种市场类型，数据管线接口 `DataSource` 包含 5 个期货专有方法，对股票、REITs、可转债零支持。

**局限二 — 辩论缺乏因子锚定**：当前 P3 辩论为"自由辩论"模式，多空论据不强制锚定量化因子信号。因子系统仅在 P2.5 作为辅助看板注入，未成为辩论的第一性原理。裁决不可归因于具体因子。

**两个局限相互强化**：覆盖面越窄，因子截面数据越稀疏，因子投资框架越无法建立；因子系统越弱，品种扩展后分析的"话题漂移"越严重。

---

## 2. 设计目标

1. **全市场品种覆盖**：MarketType 扩展至 7+ 种，DataSource 接口分层
2. **因子投资融入**：从"因子辅助看板"升级为"因子驱动辩论"，P1→P6 全流程因子化
3. **因子归因**：每次裁决可拆解到因子层面，支持 Outer Loop 因子权重进化
4. **代码-推理边界保持**：因子计算由代码精确执行，LLM 仅负责因子解读

---

## 3. 架构变更全景

### 3.1 品种分类器扩展

```python
class MarketType(str, Enum):
    COMMODITY_FUTURES = "commodity_futures"
    INDEX_FUTURES = "index_futures"
    BOND_FUTURES = "bond_futures"
    ETF = "etf"
    STOCK = "stock"               # A股个股 ← 新增
    REIT = "reit"                 # REITs ← 新增
    CONVERTIBLE_BOND = "convertible_bond"  # 可转债 ← 新增
```

**股票代码规则**：`60xxxx`/`68xxxx`(沪) + `00xxxx`/`30xxxx`(深) + `4xxxxx`/`8xxxxx`(北交所)
**REITs 代码规则**：`180xxx`(深) + `508xxx`(沪)
**可转债代码规则**：`11xxxx`(沪) + `12xxxx`(深)

### 3.2 数据管线分层重构

```python
class DataSource(ABC):
    """通用接口——get_kline / get_quote / batch_get_quotes / get_fund_flow / 宏观"""
    async def get_kline(self, ...)       # ✅ 全品种通用
    async def get_quote(self, ...)       # ✅ 全品种通用
    async def batch_get_quotes(self, ...) # ✅ 全品种通用

class FuturesDataSource(DataSource):
    """期货专有——仓单/库存/持仓排名/基差/期限结构"""
    async def get_warrant(self, ...)           # 仓单专用
    async def get_inventory(self, ...)         # 库存专用
    async def get_position_ranking(self, ...)  # 持仓排名专用

class EquityDataSource(DataSource):
    """权益通用——北向/财务/分红"""
    async def get_financials(self, ...)   # 三表核心指标
    async def get_dividend(self, ...)     # 分红记录
    async def get_north_flow(self, ...)   # 北向资金

class ConvertibleBondDataSource(EquityDataSource):
    """可转债——转股价/溢价率/纯债价值"""
    async def get_cb_info(self, ...)
    async def get_cb_premium(self, ...)

class REITDataSource(EquityDataSource):
    """REITs——底层运营/NAV折价"""
    async def get_reit_ops(self, ...)
    async def get_reit_valuation(self, ...)
```

### 3.3 因子模块扩展

**新增 5 个因子模块**：

| 模块 | 因子 | 计算方式 | 优先级 |
|:-----|:-----|:---------|:------:|
| `value.py` | 价值因子 | PE/PB/PS/PCF 历史分位 + EV/EBITDA | P0 |
| `quality.py` | 质量因子 | ROE 杜邦分解 + 毛利率稳定性 + 资产负债率 | P0 |
| `momentum.py` | 动量因子 | 时序动量(12-1M) + 截面动量排序 + 残差动量 | P0 |
| `growth.py` | 成长因子 | 营收/利润增长率 + 分析师预期修正 | P1 |
| `dividend.py` | 红利因子 | 股息率 + 分红支付率 + 分红稳定性 | P1 |

**升级 2 个现有模块**：

| 现模块 | 升级方向 |
|:-------|:---------|
| `volatility.py` → 低波因子 | 增加截面波动率排序 + 风险调整收益 |
| `term_structure.py` → Carry 因子 | 统一 carry = expected return if prices stay same；期货 = 基差收敛，股票 = 股息率-融资成本 |

### 3.4 因子信号矩阵

```python
@dataclass
class FactorSignal:
    symbol: str
    factor_name: str              # value/momentum/quality/...
    direction: int                # -2 ~ +2
    zscore: Optional[float]       # 截面 Z-Score
    percentile: Optional[float]   # 历史百分位 0~100
    ic_value: Optional[float]     # 因子 IC

@dataclass
class FactorMatrixResult:
    symbols: list[str]
    factors: list[str]
    matrix: dict[str, dict[str, FactorSignal]]  # {symbol: {factor: signal}}
    factor_ic: dict[str, float]                 # {factor: IC}
```

### 3.5 辩论流程因子化改造

```
当前流程（因子为辅）:                   改造后流程（因子为主）:

P1 数技源信号扫描                       P1 多因子评分（代码计算 8+ 因子）
  → P2 闫判官选品种                       → P1.5 因子信号矩阵（截面排序+IC）
  → P2 四源并行（自由分析）                → P2 因子驱动选品种（共振最强品种）
  → P2.5 因子看板辅助                      → P2 四源并行（因子注入每个Agent）
  → P3 自由辩论                            → P2.5 因子一致性看板
  → P4 闫判官终裁                          → P3 因子验证辩论（论点锚定因子）
  → P5 风控审核                            → P4 因子加权裁决
  → P6 报告汇编                            → P5 因子视角风控（拥挤度+回撤）
                                           → P6 因子归因报告
```

### 3.6 因子归因引擎

```python
class FactorAttributionEngine:
    """因子归因引擎——将裁决结果拆解到因子层面。

    用法: 每次 P4 结束后运行，结果写入 PG 供 Outer Loop 消费。
    """

    def compute_attribution(self, verdict, factor_matrix) -> FactorAttributionReport:
        """因子权重 = factor_ic × |factor_direction| × 有效性衰减系数
           置信度校准 = min(1.0, Σ|权重| × 分歧度倒数) """

    def detect_factor_decay(self, historical: list) -> dict[str, float]:
        """检测因子衰减——连续 N 次权重下降或方向相反，标记衰减"""
```

### 3.7 裁决 Schema 品种类型化

```python
@dataclass
class VerdictParams:                     # 通用
    direction / confidence / grade / rationale / factor_attribution

class FuturesVerdictParams(VerdictParams):  # 期货
    + entry_price / stop_loss / target / position_pct / risk_reward_ratio

class EquityVerdictParams(VerdictParams):   # 股票/ETF
    + entry_price / stop_loss(可选) / target(可选) / position_pct / holding_days

class REITVerdictParams(VerdictParams):     # REITs
    + dividend_rate / nav_discount / recommended_action

class CBVerdictParams(VerdictParams):       # 可转债
    + pure_bond_value / conversion_premium / ytm / put_status / redemption_risk
```

---

## 4. 执行计划

### Phase 1: 基础设施层改造（预计 3-5 天）

| 任务 | 文件 | 验收标准 |
|:-----|:-----|:---------|
| MarketType 枚举扩展 | `instrument_classifier.py` | 7 种类型可识别，含单元测试 |
| DataSource 接口分层 | `base.py` | Futures/Equity 分拆完成，现有管线不受影响 |
| 新增模块骨架 | `factors/value.py`/`quality.py`/`momentum.py`/`growth.py`/`dividend.py` | 5 个空骨架 + 类型定义 + 测试桩 |
| 现有模块升级 | `factors/volatility.py`/`term_structure.py` | 低波/Carry 标准化 |

### Phase 2: 因子计算实现（预计 5-7 天）

| 任务 | 验收标准 |
|:-----|:---------|
| 价值因子 `value.py` | PE/PB/PS 历史分位计算正确，覆盖 100 只样本 |
| 质量因子 `quality.py` | ROE 杜邦分解 + 5 项质量指标 |
| 动量因子 `momentum.py` | 时序/截面/残差三维度动量 |
| 因子信号矩阵 | FactorMatrixResult 可聚合 8+ 因子 |
| 升级 dashboard.py | 分歧度计算兼容新因子矩阵 |

### Phase 3: 辩论流程改造（预计 3-5 天）

| 任务 | 文件 | 验收标准 |
|:-----|:-----|:---------|
| P1 多因子评分入口 | `fdt_langgraph/nodes.py` | 并行计算全部因子 |
| P1.5 因子信号矩阵 | `_nodes_utils.py` | 截面排序+IC计算 |
| P2 因子驱动选品种 | `nodes.py` | 改为因子共振排序 |
| P3 因子验证辩论 | Agent prompts | 论点必须锚定因子 |
| P4 因子加权裁决 | `node_verdict` prompt | 品种类型化参数输出 |
| P5 因子视角风控 | `node_risk_check` prompt | 因子拥挤度+回撤 |
| P6 因子归因报告 | FactorAttributionEngine | 裁决可拆解到因子 |

### Phase 4: 品种专项实现

**第一波 — A 股个股**（数据源最成熟）
- EquityDataSource 实现 `get_financials()` / `get_dividend()` / `get_north_flow()`
- AKShare 管线对接 `stock_financial_abstract` / `stock_individual_info`
- 裁决 Schema EquityVerdictParams 落地

**第二波 — 可转债**
- ConvertibleBondDataSource 实现 `get_cb_info()` / `get_cb_premium()`
- 分析框架：债底保护 + 转股溢价率 + 条款博弈

**第三波 — REITs**
- REITDataSource 实现 `get_reit_ops()` / `get_reit_valuation()`
- 分析框架：分红率 + 底层资产运营 + NAV 折价

---

## 5. 代码-推理边界清单（新增）

在现有 `10-coding-standards.md` §12 基础上，新增因子投资专属边界：

| 边界 | 负责方 | 不允许 |
|:-----|:-------|:-------|
| 因子值计算（PE 分位/动量 Z-Score/Carry） | 代码 | LLM 估算或调整因子数值 |
| 因子截面排序 | 代码 | LLM 凭记忆排序品种 |
| 因子 IC 计算 | 代码 | LLM 估计因子有效性 |
| 因子权重优化 | Outer Loop | LLM 决定各因子权重 |
| 因子信号解读 | LLM | 代码替 LLM 做基本面推断 |
| 因子信号矛盾识别 | LLM | 代码替 LLM 做逻辑判断 |

---

## 6. 反模式检测规则（新增）

| ID | 反模式 | 严重度 | 检测条件 |
|:--:|:-------|:------:|:---------|
| AP14 | 因子的 LLM 幻觉 | P0 | 裁决中因子数值与代码计算结果不一致 |
| AP15 | 品种分析框架混用 | P1 | 对股票使用 get_warrant() |
| AP16 | 辩论无因子锚定 | P1 | P3 论据未引用任何因子信号 |
| AP17 | 因子归因缺失 | P2 | P6 报告中无因子归因章节 |

---

## 7. 风险与缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:----:|:---------|
| AKShare 股票数据接口不稳定 | 中 | 高 | EquityDataSource 内置多级降级缓存 |
| 因子 IC 对样本量敏感 | 中 | 中 | 设最低品种门限（<20 不计算截面 IC） |
| LLM 偏离因子信号 | 高 | 高 | P3.5 新增"因子锚定检查"质检规则 |
| Schema 继承导致代码膨胀 | 中 | 低 | dataclass 继承压缩重复代码 |

---

## 8. 验收标准（DOD）

- [ ] `instrument_classifier.py` 可识别 7 种市场类型，UT ≥ 14 条
- [ ] FuturesDataSource / EquityDataSource 分拆完成，现有辩论链零回归
- [ ] 5 个新增因子模块全部可实现因子值精确计算
- [ ] FactorMatrixResult 可聚合 8+ 因子全量信号
- [ ] P1→P6 因子化辩论流程跑通（覆盖 ≥1 个股指期货 + ≥1 只个股）
- [ ] 因子归因引擎产出可审计的归因报告
- [ ] P3.5 品藻质检包含"因子锚定检查"
- [ ] 新增反模式 AP14-AP17 可被 pre-commit 检测
- [ ] 文档同步：01/02/03/06/08/09/10
- [ ] 版本号 bump 到 v0.12.0+（Phase 1-2）或 v0.13.0+（Phase 1-4）
