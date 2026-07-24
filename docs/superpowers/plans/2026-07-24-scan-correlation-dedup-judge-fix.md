# FDT 辩论链路重构 + 数据适配层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构辩论品种选择链路 + 构建数据适配层，FDC 彻底退役，仅保留通道突破策略

**Architecture:** 四层架构：① Data Adapter Layer（数据适配层，统一接口，可插拔数据源）→ ② scan_all 通道突破+相关系数去重 → ③ judge_direction 只调度不选品种 → ④ 下游辩论闭环

**最终状态：** FDC 模块删除、多策略代码删除、只剩 `data_adapter/` + `channel_breakout` 策略 + AKShare 唯一数据源

**Tech Stack:** Python, numpy, LangGraph, AKShare

**关联 Harness 文档：** `docs/harness/08-gap-analysis.md`, `docs/harness/business_flow.md`, `docs/harness/01-architecture.md`

---

## 状态总览

| 模块 | 状态 | 说明 |
|:-----|:----:|:-----|
| scan_all: 移除多策略只留通道突破 | ✅ 已完成 | 管线代码已被替换为单策略调用 |
| scan_all: 相关系数去重 | ✅ 已完成 | `_compute_correlation_groups()` 已添加，替换前缀分组 |
| nodes.py: judge_direction 不选品种 | ✅ 已完成 | 直接读 primary_symbols |
| 技术面 FDC 数据修复 | ✅ 已完成 | fdc_data 保留 + tech_sym 渲染 |
| **Data Adapter Layer 构建** | 📝 待实施 | 含 K线/行情/F10 全部接口 |
| **scan_all/ nodes.py 接入适配层** | ⏳ 待实施 | 替换所有 FDC 引用 |
| **删除 FDC 模块** | 🗑️ 最终步骤 | 确认无引用后物理删除 |
| **删除多策略代码** | 🗑️ 最终步骤 | 仅保留 channel_breakout |
| **全流程验证** | ⏳ 最后 | 跑通完整辩论链 |

---

## 重构后架构图

### 分层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       下游消费者（不变）                          │
│                                                                  │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────┐  ┌─────────┐  │
│  │scan_all  │  │P2.5 data_prep    │  │观澜/探源 │  │报告层   │  │
│  │(P1扫描)  │  │(FDC数据注入)      │  │(技术/基本面)│  │(P6输出) │  │
│  └─────┬────┘  └────────┬─────────┘  └─────┬────┘  └────┬────┘  │
│        │                │                   │            │       │
└────────┼────────────────┼───────────────────┼────────────┼───────┘
         │                │                   │            │
         │     统一接口调用（不关心底层数据源）              │
         ▼                ▼                   ▼            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  数据适配层（Data Adapter Layer）                  │
│                        = 数据源插座                               │
│                                                                  │
│  data_adapter/__init__.py  ← 环境变量 FDT_DATA_SOURCE 控制路由   │
│                                                                  │
│  统一接口: get_kline / get_quote / batch_get_quotes              │
│            compute_indicators / get_basis / get_inventory        │
│            get_warrant / get_position_ranking / get_fund_flow    │
│            get_foreign_hist / get_contract_info                  │
│            get_macro_pmi / get_macro_rate                        │
│                                                                  │
│  此层对下游屏蔽数据源差异：                                        │
│  - 下游传 "RB" 即可，不关心底层用 AKShare 还是新浪还是未来新源      │
│  - 切换数据源仅改环境变量，下游零修改                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
┌─────────────────┐  ┌──────────┐  ┌──────────────────┐
│  AKShareSource   │  │ Source B  │  │    Source C      │
│  (本版唯一实现)   │  │(未来接入) │  │   (未来接入)      │
│                  │  │          │  │                  │
│ futures_hist_em  │  │ 实现同   │  │ 实现同一套        │
│ futures_zh_realtime│  │一接口   │  │ DataSource 接口   │
│ futures_hold_pos │  │          │  │                  │
│ ...共12个接口    │  │          │  │                  │
└────────┬─────────┘  └──────────┘  └──────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                      底层数据源                                    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │AKShare   │  │新浪财经  │  │东方财富  │  │未来数据源 │         │
│  │(主)      │  │(K线降级) │  │(行情)    │  │          │         │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘         │
└──────────────────────────────────────────────────────────────────┘
```

### 数据源插座机制

数据适配层的核心设计理念是 **"数据源插座"**——Data Source Socket：

> 如同电源插座统一了电器接口，数据适配层统一了数据源接口。
> 任何数据源只要实现 `DataSource` 抽象基类，就能"插"到 FDT 系统上，
> 下游消费者不需要知道插进来的是 AKShare 还是未来的 TDX/QMT/自建数据库。

```python
# 接入一个新数据源只需要 3 步：
# 1. 新建 class MySource(DataSource): 实现全部抽象方法
# 2. 在 data_adapter/__init__.py 注册路由：
#      if source_name == "mysource":
#          _DATA_SOURCE = MySource()
# 3. 设置环境变量：export FDT_DATA_SOURCE=mysource
# 下游 0 修改，直接生效！
```

切换示例：
```bash
# 当前：AKShare
export FDT_DATA_SOURCE=akshare    # 默认值，可省略

# 未来切换到新数据源：
export FDT_DATA_SOURCE=tdx        # 仅改此处，全局生效
```

---

## 数据适配层接口清单（定稿）

```
data_adapter/
├── __init__.py            # 路由入口 + 环境变量 FDT_DATA_SOURCE
├── base.py                # DataSource 抽象基类
├── indicators.py          # 技术指标计算（从 FDC legacy_numpy 迁移）
│
├── sources/
│   ├── __init__.py
│   └── akshare_source.py  # AKShare 实现（全部接口）
│
└── types.py               # 统一数据格式定义（KlineBar, QuoteData 等）
```

### 接口完整清单

| 方法 | 输入 | 输出 | AKShare 接口 |
|:-----|:-----|:-----|:-------------|
| `get_kline(symbol, period, days)` | str, str, int | `{symbol, bars[], meta}` | `futures_hist_em` + 新浪降级 |
| `get_quote(symbol)` | str | `{symbol, last_price, ...}` | `futures_zh_realtime` |
| `batch_get_quotes(symbols)` | list[str] | `{symbol: quote, ...}` | 同上，批量封装 |
| `compute_indicators(bars, names)` | list[dict], str | `{RSI14, ADX, ...}` | 纯 numpy |
| `get_contract_info(symbol)` | str | `{multiplier, margin_rate, ...}` | `futures_comm_info` + `futures_contract_detail_em` |
| `get_warrant(symbol, exchange)` | str, str | `{total, daily_change, ...}` | 4交易所全覆盖 |
| `get_inventory(symbol)` | str | `{inventory, change, ...}` | `futures_inventory_em` + COMEX |
| `get_position_ranking(symbol)` | str | `{net_long, top5_long, ...}` | DCE/GFEX/SHFE |
| `get_fund_flow(symbol)` | str | `{total_oi, long_short_ratio, ...}` | `futures_hold_pos_sina` |
| `get_foreign_hist(symbol)` | str | `{foreign_symbol, close, bars[]}` | `futures_foreign_hist` |
| `get_basis(symbol)` | str | `{spot_price, basis, basis_pct}` | `futures_spot_price_daily` |
| `get_macro_pmi()` | — | `{pmi, pmi_mom}` | `macro_china_pmi` |
| `get_macro_rate()` | — | `{rate, rate_mom}` | `macro_china_lpr` |

### 随 FDC 退役（标记 UNAVAILABLE，不迁移）

| 原接口 | 原因 | 替代方案 |
|:-------|:-----|:---------|
| `get_term_structure()` | 依赖 QMT/TqSDK 合约链 | 直接从 K 线主力/次主力价差估算 |
| `get_spread()` | 依赖 QMT/TqSDK 合约链 | 同上 |
| `get_fundamental()` | FDC 静态缓存 + 爬虫 | LLM WebSearch 动态获取 |

### 统一数据格式

```python
# types.py

@dataclass
class KlineBar:
    date: str       # "20260701"
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0

@dataclass
class KlineResult:
    symbol: str
    bars: list[KlineBar]
    meta: dict  # {"data_grade": "PRIMARY"|"UNAVAILABLE", "source": "akshare"}

@dataclass
class QuoteResult:
    symbol: str
    last_price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    open_interest: float = 0.0
    change_pct: float = 0.0
```

---

## 任务分解

### Task 0: 更新 Harness 架构文档

**文件:** `docs/harness/01-architecture.md`

- 新增数据适配层架构框图
- 标注 data_adapter / AKShare / channel_breakout 为唯一存活组件
- 标注 FDC / 多策略 为已退役

**文件:** `docs/harness/business_flow.md`

- P1 数据采集: FDC → data_adapter
- P1 策略: 多策略 → 仅通道突破
- P1→P2 品种筛选: 前缀分组 → 相关系数去重
- P2 闫判官: 选品种 → 不选品种仅调度

**文件:** `docs/harness/08-gap-analysis.md`

- 关闭 G108/G109（已修复）
- 新增 G111: FDC 退役后数据适配层迁移

---

### Task 1: 创建数据适配层

#### 1.1 创建 `data_adapter/types.py`

数据格式定义（KlineBar, KlineResult, QuoteResult）。

#### 1.2 创建 `data_adapter/base.py`

```python
class DataSource(ABC):
    @abstractmethod
    async def get_kline(self, symbol, period, days) -> KlineResult: ...
    @abstractmethod
    async def get_quote(self, symbol) -> QuoteResult: ...
    @abstractmethod
    async def batch_get_quotes(self, symbols) -> dict: ...
    @abstractmethod
    async def get_contract_info(self, symbol) -> dict: ...
    @abstractmethod
    async def get_warrant(self, symbol, exchange) -> dict: ...
    @abstractmethod
    async def get_inventory(self, symbol) -> dict: ...
    @abstractmethod
    async def get_position_ranking(self, symbol) -> dict: ...
    @abstractmethod
    async def get_fund_flow(self, symbol) -> dict: ...
    @abstractmethod
    async def get_foreign_hist(self, symbol) -> dict: ...
    @abstractmethod
    async def get_basis(self, symbol) -> dict: ...
    @abstractmethod
    async def get_macro_pmi(self) -> dict: ...
    @abstractmethod
    async def get_macro_rate(self) -> dict: ...
```

#### 1.3 创建 `data_adapter/indicators.py`

从 `futures_data_core/indicators/legacy_numpy.py` 迁移 `_compute_indicators_numpy` 及其辅助函数。纯 numpy 实现，零外部依赖。

#### 1.4 创建 `data_adapter/sources/akshare_source.py`

AKShareSource 实现全部 12 个接口，代码参考：
- `futures_data_core/core/akshare_provider.py`（K线/行情）
- `futures_data_core/f10/*.py`（F10 数据）

每个方法需包含：
- try/except 保护，异常返回 UNAVAILABLE
- 符号映射（FDT 代码 → AKShare 代码）
- 结果归一化到 `types.py` 定义的数据格式

#### 1.5 创建 `data_adapter/__init__.py`

```python
FDT_DATA_SOURCE = os.environ.get("FDT_DATA_SOURCE", "akshare")

async def get_kline(...): return await _get_source().get_kline(...)
async def get_quote(...): return await _get_source().get_quote(...)
# ... 其余 11 个接口
```

#### 1.6 验证

```bash
python -c "import asyncio; from data_adapter import get_kline; r = asyncio.run(get_kline('RB')); print(len(r.bars), 'bars')"
python -c "from data_adapter.indicators import compute_indicators; print('ok')"
```

---

### Task 2: scan_all.py 接入数据适配层

**文件:** `skills/quant-daily/scripts/scan_all.py`

**修改点：**

| 行号 | 当前代码 | 替换为 |
|:----|:---------|:-------|
| 63-64 | `from data_source_adapter import batch_get_quotes, get_kline` | `from data_adapter import batch_get_quotes, get_kline` |
| 67-91 | `_fdc_get_kline_sync()` 函数 | 删除，改为 `data_adapter.get_kline()` 同步包装 |
| 399 | `from data_source_adapter import get_warrant_fdc` | 删除（无 AKShare 替代） |
| 433 | `from data_source_adapter import load_fundamental` | 删除 |
| 476 | `from data_source_adapter import get_macro_pmi, get_macro_rate` | `from data_adapter import get_macro_pmi, get_macro_rate` |
| 538 | `from futures_data_core.collectors.tqsdk import TqSdkCollector` | 删除（TqSDK fallback） |
| 998 | `from futures_data_core.collectors.tqsdk import TqSdkCollector` | 删除 |
| 1183 | `from futures_data_core.core.data_quality import evaluate_symbol` | 删除 |
| 1228 | `from futures_data_core.core.data_quality import evaluate_symbol` | 删除 |

**删除 `collect_kline_for_all()` 中的 TqSDK fallback 段（约 536-547 行）。**

**删除 R24 闸门中的 FDC fallback 段（约 805-828 行），简化为空检测。**

最终 `collect_kline_for_all()` 变为纯 `data_adapter.get_kline()` 串行采集。

---

### Task 3: nodes.py P2.5 接入数据适配层

**文件:** `fdt_langgraph/nodes.py`

**修改点：**

| 位置 | 当前 | 替换为 |
|:-----|:-----|:-------|
| `node_prepare_data()` 头部 | `from data_source_adapter import get_kline, ...` | `from data_adapter import get_kline, ...` |
| K 线采集 | `get_kline(symbol, period, days)` | 同上（接口名一致） |
| F10 数据采集段 | `get_basis`, `get_spread`, `get_term_structure`, `get_warrant`, `get_fundamental`, `get_position_ranking`, `get_fund_flow`, `get_foreign_hist` | 全部改为 `data_adapter` 对应接口 |
| `get_spread`/`get_term_structure` | 原 FDC 实现 | 返回 `{"data": {}, "summary": "数据源已退役"}` |
| `get_fundamental` | 原 FDC 实现 | 返回 `{"data": {}, "summary": "数据源已退役"}` |

**删除 `from data_source_adapter import ...` 引用。**

---

### Task 4: 清理退役代码

#### 4.1 删除 `futures_data_core/` 目录

```bash
rm -rf D:\Programs\FDT\futures_data_core\
```

#### 4.2 删除 `data_source_adapter.py`

```bash
rm D:\Programs\FDT\data_source_adapter.py
```

#### 4.3 删除退役策略文件

```bash
# 保留 channel_breakout_strategy.py，删除其余
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/trend_following_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/arbitrage_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/mean_reversion_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/pairs_reversion_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/spread_reversion_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/basis_reversion_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/macro_regime_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/event_driven_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/ml_signal_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/multi_factor_strategy.py
rm D:\Programs\FDT\skills\quant-daily\scripts\strategies/registry_v2.py
```

#### 4.4 删除 FDC 相关测试文件

```bash
rm -rf D:\Programs\FDT\tests\futures_data_core\
```

#### 4.5 验证无残留引用

```bash
grep -r "futures_data_core" D:\Programs\FDT --include="*.py" | grep -v "删除\|退役\|废弃\|\.pyc"
grep -r "data_source_adapter" D:\Programs\FDT --include="*.py" | grep -v "删除\|退役\|废弃\|\.pyc"
```

---

### Task 5: 全流程运行验证

#### 5.1 单元测试

```bash
python -m pytest tests/data_adapter/ -v          # 适配层单元测试
python -m pytest tests/scan_all/ -v               # scan_all 测试
python -m pytest tests/fdt_langgraph/ -v          # LangGraph 测试
```

#### 5.2 单步验证

```bash
# 1. 数据适配层 K 线
python -c "import asyncio; from data_adapter import get_kline; r = asyncio.run(get_kline('RB')); print(len(r.bars), 'bars')"

# 2. scan_all 扫描
python skills/quant-daily/scripts/scan_all.py -o D:\FDTWorkspace\20260724

# 3. 辩论全流程
fdt_cli.py run --mode default
```

#### 5.3 验收标准

| 检查项 | 通过标准 |
|:-------|:---------|
| data_adapter.get_kline | 返回 60+ bars，数据等级 PRIMARY |
| data_adapter.get_quote | 返回含有效 last_price |
| data_adapter 全部 12 接口 | 不抛异常，不可用接口返回 UNAVAILABLE |
| scan_all.py 运行 | 62 品种扫描完成，相关系数去重后约 20-30 primary_symbols |
| 辩论全流程 | 报告 HTML 正常生成，技术面/基本面数据展示完整 |
| 无 FDC 引用 | `grep -r "futures_data_core"` 返回空 |
| 无多策略引用 | `grep -r "trend_following\|arbitrage_strategy"` 返回空 |

---

## 执行顺序

```
Task 0: 更新 Harness 文档
  │
  ▼
Task 1: data_adapter 包创建（不含删除）
  │  ├── 1.1 types.py
  │  ├── 1.2 base.py
  │  ├── 1.3 indicators.py（从 FDC 迁移）
  │  ├── 1.4 sources/akshare_source.py
  │  ├── 1.5 __init__.py
  │  └── 1.6 验证
  │
  ▼
Task 2: scan_all.py 接入适配层
  │
  ▼
Task 3: nodes.py P2.5 接入适配层
  │
  ▼
Task 4: 清理退役代码
  │  ├── 删除 futures_data_core/
  │  ├── 删除 data_source_adapter.py
  │  ├── 删除 9 个退役策略
  │  ├── 删除 FDC 测试
  │  └── 验证无残留引用
  │
  ▼
Task 5: 全流程验证
```

每个 Task 完成后需执行完整性检查再进入下一个，不跳步。

---

## Harness 合规检查

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| C01 | 数据流/架构变更 → docs/harness/01-architecture.md | Task 0 |
| C03 | 新配置项 → docs/harness/03-configuration.md | `FDT_DATA_SOURCE` 新增 |
| C05 | 新指标/日志 → docs/harness/05-observability.md | 适配层日志前缀 `[DataAdapter]` |
| C06 | 测试文件 → docs/harness/06-testing.md | 新增 `tests/data_adapter/` |
| C07 | 版本号和版本历史 → docs/harness/07-operations.md | v10.0.0（大版本，FDC 退役） |
| C08 | 差距登记/关闭 → docs/harness/08-gap-analysis.md | G108/G109 关闭，G111 新增 |
| C10 | 流程文档同步 → business_flow.md | Task 0 |
| C12 | README → README.md | 需更新模块清单 |

---

## 版本号

- 当前版本: v9.23.1
- 发布版本: **v10.0.0**（FDC 退役 + 数据适配层上线，重大架构变更）
