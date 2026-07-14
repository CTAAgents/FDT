# FDT 数据采集模块重构方案

**仓库**: `futures-data-core` (独立仓库)
**版本**: v2.0
**日期**: 2026-07-12
**状态**: 设计稿

---

> ## ⚠️ 硬约束补充（2026-07-13 裁定，优先级高于本文任何相反表述）
>
> `futures-data-core` (FDC) 是**独立抽取实体**，与现有 `FDT` 系统之间设有**不可逾越的隔离边界**：
> 1. FDC 绝不可反向依赖 / import / 引用 FDT 本体或其内嵌模块（`skills/quant-daily` 的 `scan_all` / `data` / `indicators` / `fundamentals`）。
> 2. FDC 绝不可改写、删除、抽空 FDT 任何现有代码——**本文「Phase 5」中的"删除 FDT 内嵌 data/ + indicators/ + fundamentals/"与"scan_all.py import 替换"步骤即日起作废、禁止执行**。
> 3. FDC 绝不可改变 FDT 的运行形态：FDT 必须以自身内嵌代码独立运行。
> 4. **原 FDT 冻结、零修改**：在 FDC 等解耦模块实现完成前，原 FDT 不做任何改动（代码/数据/配置冻结），完整保留。
5. **集成目标是「新 FDT」而非改造原 FDT**：待各解耦模块独立实现后，再基于它们**重建一个新的 FDT**；原 FDT 不被改造、不被抽空。
>
> 机器级强制见 `futures-data-core/tests/test_boundary_isolation.py`（扫描 FDC 源码，断言无 FDT 耦合，CI 阶段即阻断侵入）。

---

## 一、重构目标

### 1.1 核心目标

将 FDT 当前内嵌在 `skills/quant-daily/` 中的数据采集代码，提取为一个**独立的 Python 包**。

### 1.2 关键约束

| 约束 | 取值 | 说明 |
|:----|:----|:-----|
| 仓库形态 | **独立 Git 仓库** | 独立版本、CI、release、changelog |
| 基本面采集 | **包含** | `fundamental-data-collector` 并入 |
| 接口风格 | **Async (asyncio)** | 所有 IO 方法 async，同步包装层兼容 |
| LLM 依赖 | **显式标注** | 每项数据标注运行模式，无隐藏依赖 |
| FDT 集成 | git submodule | FDT 锁定版本引用 |

### 1.3 运行模式定义

整个模块的数据管道分为三种运行模式：

| 模式 | 标签 | 含义 | 适用场景 |
|:----|:----|:-----|:---------|
| **独立模式** | `[INDEPENDENT]` | 纯 Python 代码，零 LLM 依赖 | 任何 Python 环境、CLI、其他 Skill |
| **LLM 增强模式** | `[LLM-ENHANCED]` | 核心逻辑独立，特定场景调用 LLM 提升 | 需要比确定性爬虫更强的情景理解 |
| **LLM 驱动模式** | `[LLM-DRIVEN]` | 必须通过 LLM 执行，无法独立运行 | 非结构化数据、语义搜索、定性分析 |

---

## 二、数据能力矩阵（含 LLM 依赖标注）

### 2.1 完整覆盖矩阵

```
数据类型             运行模式    工具链                                可靠性     LLM 说明
─────────────────────────────────────────────────────────────────────────────────────────────
K 线 (OHLCV)         INDEPENDENT  TDX HTTP → TqSDK → AKShare           ★★★★★    无
行情快照              INDEPENDENT  TDX HTTP → TqSDK                     ★★★★★    无
技术指标 (18 组)      INDEPENDENT  TDX formula_zb + numpy 兜底          ★★★★★    无
品种清单              INDEPENDENT  内置 yaml 映射表                       ★★★★★    无
DuckDB 缓存           INDEPENDENT  本地 SQL                               ★★★★★    无

期限结构              INDEPENDENT  TDX HTTP → AKShare                    ★★★★★    无
跨期价差              INDEPENDENT  TDX HTTP 直取                          ★★★★★    无

基差                  INDEPENDENT  httpx → 生意社 100ppi.com + bs4       ★★★☆☆    无
仓单日报              INDEPENDENT  httpx → 交易所官网 + bs4              ★★★☆☆    无
徽商 HS 基本面        INDEPENDENT  httpx → HS HTTP API                  ★★★☆☆    无

基本面-供需库存        LLM-ENHANCED  静态缓存 + LLM 实时采集              ★★☆☆☆    仅 WebSearch 环节
基本面-利润/加工费    LLM-ENHANCED  静态缓存 + LLM 实时采集              ★★☆☆☆    仅 WebSearch 环节
                                                                                    ↓ 详见第 5 节
F10 综合报告           HYBRID      独立数据 + LLM 增强                   ★★★☆☆    报告润色部分
```

**关键设计原则**：
- **INDEPENDENT 的数据**：pip install 后直接可用，不依赖任何外部 AI 能力
- **LLM-ENHANCED 的数据**：基础版本（静态缓存）独立可用；实时版本需要 LLM 环境
- **LLM-DRIVEN 的数据**：当前方案中没有 —— 所有 LLM 依赖都有 INDEPENDENT 兜底

---

## 三、独立仓库设计

### 3.1 仓库结构

```
futures-data-core/
├── .github/workflows/
│   ├── test.yml
│   └── publish.yml
│
├── src/
│   └── futures_data_core/
│       ├── __init__.py                     # 公开 API 导出
│       ├── _version.py                     # VERSION
│       ├── _runtime.py                     # 运行模式检测 (新增)
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── multi_source_adapter.py     # async 降级链路由 [INDEPENDENT]
│       │   ├── duckdb_store.py             # async 缓存引擎 [INDEPENDENT]
│       │   ├── data_freshness.py           # 通用新鲜度评估 [INDEPENDENT]
│       │   └── symbol_registry.py          # 品种注册与映射 [INDEPENDENT]
│       │
│       ├── collectors/
│       │   ├── __init__.py
│       │   ├── base.py                     # BaseCollector async 基类
│       │   ├── tdx.py                      # [INDEPENDENT] 通达信
│       │   ├── tqsdk.py                    # [INDEPENDENT] 天勤
│       │   ├── akshare.py                  # [INDEPENDENT] AKShare
│       │   └── eastmoney.py               # [INDEPENDENT] 东方财富
│       │
│       ├── indicators/
│       │   ├── __init__.py
│       │   └── core.py                     # [INDEPENDENT] numpy 纯函数
│       │
│       ├── f10/
│       │   ├── __init__.py
│       │   ├── term_structure.py           # [INDEPENDENT] 期限结构
│       │   ├── spread.py                   # [INDEPENDENT] 跨期价差
│       │   ├── basis.py                    # [INDEPENDENT] 基差 httpx→生意社
│       │   ├── warrant.py                  # [INDEPENDENT] 仓单 httpx→交易所
│       │   ├── fundamentals.py             # [LLM-ENHANCED] 基本面路由
│       │   ├── web_collector.py            # [LLM-DRIVEN] WebSearch 采集 (标记)
│       │   ├── exchange_scraper.py         # [INDEPENDENT] 交易所爬取
│       │   └── huishang.py                 # [INDEPENDENT] 徽商 HS
│       │
│       ├── config/
│       │   └── ...
│       │
│       └── cache/
│           └── ...
│
├── tests/
├── examples/
├── pyproject.toml
├── README.md
└── LLM_DEPENDENCY.md                       # LLM 依赖说明文档 (新增)
```

### 3.2 运行模式检测

```python
# src/futures_data_core/_runtime.py

import enum

class RuntimeMode(enum.Enum):
    INDEPENDENT = "独立模式"       # 纯 Python，零 LLM
    LLM_ENHANCED = "LLM增强模式"  # 核心独立，LLM 可选增强
    LLM_DRIVEN = "LLM驱动模式"    # 依赖 LLM 执行
    UNAVAILABLE = "当前不可用"     # 数据源缺失

def detect_llm_capability() -> dict:
    """
    探测当前环境是否具备 LLM 调用能力。
    返回每项功能在当前环境中的运行模式。
    """
    return {
        "kline": RuntimeMode.INDEPENDENT,
        "indicators": RuntimeMode.INDEPENDENT,
        "term_structure": RuntimeMode.INDEPENDENT,
        "spread": RuntimeMode.INDEPENDENT,
        "basis": RuntimeMode.INDEPENDENT,
        "warrant": RuntimeMode.INDEPENDENT,
        "fundamental_supply": RuntimeMode.LLM_ENHANCED
            if _has_websearch() else RuntimeMode.INDEPENDENT,
        "fundamental_demand": RuntimeMode.LLM_ENHANCED
            if _has_websearch() else RuntimeMode.INDEPENDENT,
    }
```

### 3.3 版本策略

```
v0.1.0 — 独立模式核心 (INDEPENDENT 全部)
v0.2.0 — LLM-ENHANCED 基本面增强
v1.0.0 — 稳定发布
```

---

## 四、Async 接口设计

### 4.1 Collector 基类

```python
# src/futures_data_core/collectors/base.py

from abc import ABC, abstractmethod
from enum import Enum

class CollectorType(Enum):
    INDEPENDENT = "independent"    # 不依赖 LLM
    LLM_ENHANCED = "llm_enhanced"  # 可独立运行，LLM 为增强
    LLM_DRIVEN = "llm_driven"      # 必须 LLM 上下文

class BaseCollector(ABC):
    """数据采集器抽象基类"""

    name: str
    priority: int
    collector_type: CollectorType = CollectorType.INDEPENDENT
    llm_requirement: str = ""       # LLM 依赖描述

    @abstractmethod
    async def check_available(self) -> bool:
        ...

    @abstractmethod
    async def get_kline(self, symbol, period="daily", days=120):
        ...
```

### 4.2 公开 API

```python
# src/futures_data_core/__init__.py

"""
futures-data-core — 期货数据采集核心

运行模式说明:
  [INDEPENDENT]    纯 Python 执行，无需 LLM 上下文
  [LLM-ENHANCED]   基础功能独立运行，增强功能需 LLM
  [LLM-DRIVEN]     必须通过 LLM 执行

数据标注格式:
  get_kline        → [INDEPENDENT]
  get_basis        → [INDEPENDENT]
  get_fundamental  → [LLM-ENHANCED] (缓存兜底为 INDEPENDENT)
"""

from futures_data_core.core.multi_source_adapter import MultiSourceAdapter

_adapter = MultiSourceAdapter()

# ══════════════════════════════════════════════════
# [INDEPENDENT] 以下函数可独立运行
# ══════════════════════════════════════════════════

async def get_kline(symbol, period="daily", days=120, source="auto") -> pd.DataFrame:
    """获取 K 线数据，自动降级。无 LLM 依赖。"""
    return await _adapter.get_kline(symbol, period, days, source)

async def get_term_structure(symbol) -> dict:
    """期限结构。无 LLM 依赖。"""
    ...

async def get_basis(symbol) -> dict:
    """基差 (现货-期货)。httpx → 生意社。无 LLM 依赖。"""
    ...

async def get_warrant(symbol) -> dict:
    """交易所仓单日报。httpx → SHFE/DCE/CZCE。无 LLM 依赖。"""
    ...

# ══════════════════════════════════════════════════
# [LLM-ENHANCED] 基础独立，增强需 LLM
# ══════════════════════════════════════════════════

async def get_fundamental(symbol, data_type="all", use_llm=False) -> dict:
    """
    基本面数据 (供需库存利润)。

    运行模式:
      - use_llm=False (默认): [INDEPENDENT] 返回静态缓存 + 采集器数据
      - use_llm=True:         [LLM-ENHANCED] 额外调用 WebSearch 获取实时数据

    LLM 依赖:
      仅在 use_llm=True 时需要 TrustCaller 环境
      不传 use_llm 或 use_llm=False 时完全独立
    """
    ...

async def get_f10(symbol, enhance_with_llm=False) -> dict:
    """
    F10 综合报告。

    enhance_with_llm=False (默认): [INDEPENDENT] 纯数据组装
    enhance_with_llm=True:         [LLM-ENHANCED] LLM 润色报告
    """
    ...

async def search_fundamental_llm(symbol, data_type) -> dict:
    """
    通过 LLM WebSearch 搜索基本面数据。

    运行模式: [LLM-DRIVEN]
    说明: 必须在支持 WebSearch 的 LLM 上下文 (如 WorkBuddy) 中执行。
          独立 Python 环境调用将抛出 LlmContextRequiredError。
    """
    _assert_llm_context("search_fundamental_llm")
    ...

# ══════════════════════════════════════════════════
# 同步函数 (纯计算，全为 INDEPENDENT)
# ══════════════════════════════════════════════════

def compute_indicators(df, indicators) -> dict:
    """技术指标计算。纯 numpy，无 LLM 依赖。"""
    ...

def list_symbols(exchange=None) -> list[dict]:
    """品种清单。纯配置查询。"""
    ...
```

---

## 五、行业网站基本面数据缺口处理方案

### 5.1 问题定义

Mysteel（钢铁/煤焦）、隆众资讯（能化）、卓创资讯（塑料/化工）、MPOB（棕榈油月报）等行业网站的供需数据（产量/开工率/库存/利润），当前**没有公开的确定性 HTTP API**。这些数据源的特点是：

| 特征 | 影响 |
|:----|:-----|
| 无公开 REST API | 无法用 httpx 直接获取结构化数据 |
| 页面结构非固定 | HTML 表格可能因网站改版而变化 |
| 部分需登录/付费 | 非公开数据 |
| 搜索引擎可索引 | WebSearch 可以获取 |

### 5.2 三层数据策略

```
第 1 层: 静态缓存 [INDEPENDENT]
  └─ 发货时附带的预采集数据快照
  └─ 标注 cached_at 时间，用户明确知道时效
  └─ 约 20 个品种，覆盖供给/需求/库存/利润
  └─ 用户可选择手动替换缓存文件更新

第 2 层: 确定性爬虫 [INDEPENDENT] (逐步建设)
  └─ 对数据格式稳定的网站编写专用爬虫
  └─ 如交易所公开数据、生意社现货价
  └─ 爬虫代码 + bs4 解析，无 LLM
  └─ 覆盖度取决于目标网站稳定性

第 3 层: LLM WebSearch [LLM-DRIVEN]
  └─ 最新实时行业数据
  └─ 通过 LLM 的 WebSearch 搜索并提取
  └─ 依赖 WorkBuddy 或支持 WebSearch 的 LLM 环境
  └─ 显式标注，用户知情选择
```

**默认行为**：`get_fundamental()` 不传 `use_llm=True` 时，仅使用第 1 层 + 第 2 层，完全独立运行。

### 5.3 代码示例

```python
async def get_fundamental(symbol, data_type="all", use_llm=False):
    """
    获取品种基本面数据。

    参数:
        symbol:    品种代码
        data_type: supply / demand / inventory / margin / all
        use_llm:   是否启用 LLM 实时搜索 (默认 False)

    返回结构:
        {
            "data": {...},
            "mode": "independent" | "llm_enhanced",
            "llm_used": True/False,
            "cached_at": "2026-07-12" | None,
            "sources": [{"name": "...", "type": "cache" | "collector" | "llm"}]
        }
    """

    # ── 第 1 层: 静态缓存 (INDEPENDENT) ──
    result = await _load_cache(symbol, data_type)

    # ── 第 2 层: 确定性爬虫 (INDEPENDENT) ──
    scraper_result = await _try_scrape(symbol, data_type)
    if scraper_result:
        result = _merge(result, scraper_result)

    result["mode"] = "independent"
    result["llm_used"] = False

    # ── 第 3 层: LLM WebSearch (LLM-DRIVEN) ──
    if use_llm:
        try:
            llm_result = await _llm_search(symbol, data_type)
            result = _merge(result, llm_result)
            result["mode"] = "llm_enhanced"
            result["llm_used"] = True
        except LlmContextNotAvailableError:
            # LLM 环境不可用，静默降级
            result["llm_note"] = "LLM 不可用，已降级为独立模式"

    return result
```

### 5.4 LLM 环境检测

```python
# src/futures_data_core/_llm_bridge.py
"""
LLM 调用桥接层。

设计原则:
  - 所有 LLM 调用集中在此模块，不在业务代码中散落
  - 每个 LLM 调用方法都有清晰的 INDEPENDENT 兜底
  - LLM 调用失败时静默降级，不抛异常
"""

import os
import warnings

class LlmContextNotAvailableError(RuntimeError):
    """LLM 上下文不可用时抛出"""
    pass

def _has_websearch() -> bool:
    """检测当前环境是否有 WebSearch 能力"""
    # WorkBuddy 环境通过 connector 提供
    # 独立 Python 环境返回 False
    if os.environ.get("WORKBUDDY_LLM_CONTEXT"):
        return True
    return False

async def llm_websearch(query: str) -> str | None:
    """
    调用 LLM WebSearch (如果可用)。

    运行模式: [LLM-DRIVEN]
    说明: 仅在 WorkBuddy 或支持 WebSearch 的 LLM 环境中可用。
          独立 Python 环境调用返回 None 并发出警告。

    返回:
        str  — 搜索结果文本
        None — LLM 不可用，调用方应使用缓存降级
    """
    if not _has_websearch():
        warnings.warn(
            "WebSearch 在当前环境中不可用。"
            "请确保在 WorkBuddy 或支持 WebSearch 的 LLM 环境中运行。"
            "已降级为独立模式。",
            RuntimeWarning
        )
        return None
    # 实际的 WebSearch 调用（由 LLM 桥接）
    ...
```

---

## 六、LLM 依赖说明文档

### 6.1 专用文档

仓库中包含 `LLM_DEPENDENCY.md`，内容如下：

```markdown
# LLM 依赖说明

## 概述

`futures-data-core` 的核心功能 (K线、指标、期限结构、基差、仓单) 
完全独立运行，**不需要任何 LLM 环境**。

基本面数据实时采集功能可通过 LLM 增强，但基础版本独立可用。

## 依赖清单

### [INDEPENDENT] 完全独立

| 功能 | 是否依赖 LLM | 说明 |
|:----|:-----------:|:-----|
| get_kline | 否 | 纯 HTTP 或本地服务调用 |
| get_indicators | 否 | numpy 纯函数计算 |
| get_term_structure | 否 | TDX HTTP → AKShare |
| get_spread | 否 | TDX HTTP |
| get_basis | 否 | httpx → 生意社 |
| get_warrant | 否 | httpx → 交易所 |
| get_huishang | 否 | httpx → HS API |
| list_symbols | 否 | 本地 yaml |

### [LLM-ENHANCED] LLM 可选增强

| 功能 | 基础模式 | LLM 增强模式 |
|:----|:--------|:------------|
| get_fundamental | 静态缓存 + 爬虫 | WebSearch 实时采集 |
| get_f10 | 数据组装 | 报告润色 |

### [LLM-DRIVEN] 必须 LLM

| 功能 | 说明 |
|:----|:-----|
| search_fundamental_llm | 显式调用 LLM WebSearch 搜索行业数据 |

## 环境要求

- 独立模式: Python 3.10+, pip install futures-data-core
- LLM 增强模式: 需要 WorkBuddy 或支持 WebSearch 的 LLM 环境
```

### 6.2 运行时标识

每次数据返回中携带运行模式信息：

```python
result = await get_fundamental("CU", use_llm=True)
print(result["_runtime"])

# 输出:
{
    "mode": "llm_enhanced",
    "llm_used": True,
    "llm_capability": "websearch_available",
    "warning": None,
    "fallback_used": False
}
```

---

## 七、CLI 命令全集

```
fdc kline <symbol>              [INDEPENDENT]
fdc indicators <symbol>         [INDEPENDENT]
fdc term-structure <symbol>     [INDEPENDENT]
fdc spread <symbol>             [INDEPENDENT]
fdc basis <symbol>              [INDEPENDENT]
fdc warrant <symbol>            [INDEPENDENT]

fdc fundamental <symbol>        [LLM-ENHANCED]
    --no-llm                    强制独立模式 (默认)
    --use-llm                   启用 LLM WebSearch 增强

fdc f10 <symbol>                [LLM-ENHANCED]
    --no-llm                    强制独立模式 (默认)
    --use-llm                   启用 LLM 增强

fdc setup status                [INDEPENDENT]
    --verbose                   显示 LLM 能力状态
```

### CLI 环境探测输出

```bash
$ fdc setup status --verbose

┌─ futures-data-core 运行模式 ─────────────────────┐
│                                                    │
│ [INDEPENDENT]  纯 Python 执行，零 LLM 依赖         │
│   ✓  K 线/行情              TDX → TqSDK → AKShare │
│   ✓  技术指标               numpy 函数             │
│   ✓  期限结构/价差           TDX → AKShare         │
│   ✓  基差                   生意社 httpx            │
│   ✓  仓单                   交易所 httpx             │
│                                                    │
│ [LLM-ENHANCED]  核心独立，LLM 可选                 │
│   ✓  基本面(缓存)           静态数据, 标注时效      │
│   ✗  基本面(实时)           WebSearch 不可用        │
│       → 需在 WorkBuddy 或 LLM 环境中运行            │
│                                                    │
│ [LLM-DRIVEN]   必须 LLM 环境                       │
│   ✗  search_fundamental_llm  WebSearch 不可用       │
│                                                    │
│ 当前环境: 独立 Python (无 LLM 上下文)              │
│ 建议: 所有 INDEPENDENT 功能可用                     │
└────────────────────────────────────────────────────┘
```

---

## 八、其他模块概要

### 8.1 文件结构

```
src/futures_data_core/
├── __init__.py                     # 公开 API (含运行模式标注)
├── _version.py
├── _runtime.py                     # 运行模式检测
├── _llm_bridge.py                  # LLM 调用桥接 (集中管理)
│
├── core/
│   ├── multi_source_adapter.py     # [INDEPENDENT]
│   ├── duckdb_store.py             # [INDEPENDENT]
│   ├── data_freshness.py           # [INDEPENDENT]
│   └── symbol_registry.py          # [INDEPENDENT]
│
├── collectors/
│   ├── base.py                     # BaseCollector (含 CollectorType)
│   ├── tdx.py                      # [INDEPENDENT]
│   ├── tqsdk.py                    # [INDEPENDENT]
│   ├── akshare.py                  # [INDEPENDENT]
│   └── eastmoney.py                # [INDEPENDENT]
│
├── indicators/
│   └── core.py                     # [INDEPENDENT]
│
├── f10/
│   ├── term_structure.py           # [INDEPENDENT]
│   ├── spread.py                   # [INDEPENDENT]
│   ├── basis.py                    # [INDEPENDENT]
│   ├── warrant.py                  # [INDEPENDENT]
│   ├── fundamentals.py             # [LLM-ENHANCED] 路由
│   ├── web_collector.py            # [LLM-DRIVEN] 显式标注
│   ├── exchange_scraper.py         # [INDEPENDENT]
│   └── huishang.py                 # [INDEPENDENT]
│
├── config/
│   ├── settings.py                 # pydantic-settings
│   ├── data_sources.yaml
│   └── symbol_map.yaml
│
└── cache/
    ├── duckdb.py
    ├── f10_cache.py
    └── fundamental_cache/          # 静态缓存
        ├── supply.json             # [INDEPENDENT 兜底]
        ├── demand.json
        ├── inventory.json
        └── README.md               # 缓存时效说明
```

### 8.2 依赖清单

```toml
# pyproject.toml

[project]
name = "futures-data-core"
version = "0.1.0"

dependencies = [
    "pandas>=1.5",
    "numpy>=1.24",
    "pyyaml>=6.0",
    "httpx>=0.27",              # async HTTP 客户端 (替换 requests)
    "beautifulsoup4>=4.12",     # HTML 解析
    "lxml>=5.0",                # 高性能解析器
]

[project.optional-dependencies]
akshare = ["akshare>=1.15"]
tqsdk = ["tqsdk>=4.0"]
duckdb = ["duckdb>=1.0"]
```

### 8.3 实施路线

```
Phase 1 (2 天) — 独立模式核心
  ├── 创建独立仓库 + pyproject.toml + CI
  ├── collectors/ 全部异步化 (TDX/TqSDK/AKShare/东方财富)
  ├── core/ 降级链 + 缓存 + 新鲜度
  ├── _runtime.py 运行模式检测
  ├── __init__.py 公开 API (含运行模式标注)
  └── 验证: pip install 后所有 INDEPENDENT 功能可用

Phase 2 (1 天) — F10 独立模式
  ├── term_structure / spread (从 FDT 复制，异步化)
  ├── basis (httpx → 生意社)
  ├── warrant (httpx → 交易所)
  ├── exchange_scraper
  └── 验证: fdc basis CU + fdc warrant CU

Phase 3 (1 天) — 静态缓存 + 基本面路由
  ├── fundamental_cache/ 移植 FDT 缓存数据
  ├── _llm_bridge.py + fundamentals.py 路由
  ├── fundamentals.py 三层采集策略
  ├── LLM_DEPENDENCY.md
  └── 验证: get_fundamental("CU", use_llm=False)

Phase 4 (1 天) — LLM WebSearch 桥接
  ├── web_collector.py [LLM-DRIVEN] 显式标注
  ├── _llm_bridge.py WebSearch 调用
  ├── f10 综合报告 [LLM-ENHANCED]
  └── 验证: use_llm=True 在 LLM 环境中工作

Phase 5 (1 天) — 打包 + FDT 适配
  ├── pyproject.toml 完整配置
  ├── FDT git submodule 引用
  ├── scan_all.py import 替换
  ├── 删除 FDT 内嵌 data/ + indicators/ + fundamentals/
  └── 验证: FDT 端到端扫描与重构前一致
```

**总工期**: 6 天

---

## 九、A2A 兼容数据输出格式

### 9.1 设计原则

所有数据输出的格式满足 **A2A (Agent-to-Agent) 协议** 要求，确保不同 Agent 系统能够无歧义地消费数据。

```
A2A 核心规范要求:
  ┌─────────────────────────────────────────┐
  │ Task                                    │
  │ ├── id / sessionId / status             │
  │ ├── artifacts[]                         │
  │ │   ├── parts[]                        │ ← 数据承载层
  │ │   │   ├── type: "text"               │ ← 自然语言描述
  │ │   │   ├── type: "data"               │ ← 结构化数据 (核心)
  │ │   │   └── type: "file"               │ ← 文件引用
  │ │   └── metadata                       │ ← 元信息
  │ └── ...
  └─────────────────────────────────────────┘

futures-data-core 输出:
  不产生完整 A2A Task（那是调用方的工作）
  产生 data part 可用的结构化负载
  产生 text part 可用的自然语言描述
  附带完整 metadata 供 Agent 路由决策
```

### 9.2 标准化数据信封

每个公开 API 的返回值统一包装为 `A2APayload` 结构：

```python
@dataclass
class A2APayload:
    """A2A 兼容数据信封"""

    # ── 类型路由 (映射到 A2A data.type) ──
    type: str                           # "fdc.kline" / "fdc.basis" / "fdc.f10"

    # ── 运行模式 (调用方决定是否信任) ──
    runtime_mode: str                   # "independent" / "llm_enhanced"

    # ── 元信息 (映射到 A2A artifact.metadata) ──
    meta: dict = field(default_factory=lambda: {
        "data_grade": "PRIMARY",        # L0-L5
        "data_grade_label": 0,
        "sources": [],                  # 实际使用的数据源列表
        "cached_at": None,              # 缓存时间
        "llm_used": False,             # 是否使用了 LLM
        "warnings": [],                 # 异常/降级警告
        "a2a_compatible": True,         # A2A 兼容标记
    })

    # ── 结构化数据 (映射到 A2A data.data) ──
    data: dict

    # ── 自然语言描述 (映射到 A2A text.text) ──
    summary: str                        # 一句话摘要
```

### 9.3 各数据类型标识

| API | type 标识 | 说明 |
|:----|:---------|:-----|
| `get_kline` | `fdc.kline` | K 线数据 |
| `get_quote` | `fdc.quote` | 行情快照 |
| `get_term_structure` | `fdc.term_structure` | 期限结构 |
| `get_spread` | `fdc.spread` | 跨期价差 |
| `get_basis` | `fdc.basis` | 基差 |
| `get_warrant` | `fdc.warrant` | 仓单日报 |
| `get_fundamental` | `fdc.fundamental` | 基本面 |
| `get_f10` | `fdc.f10` | F10 综合报告 |
| `compute_indicators` | `fdc.indicators` | 技术指标 |
| `list_symbols` | `fdc.symbols` | 品种清单 |

### 9.4 输出示例

#### get_basis("CU") 的 A2A 兼容输出

```json
{
  "type": "fdc.basis",
  "runtime_mode": "independent",

  "meta": {
    "data_grade": "PRIMARY",
    "data_grade_label": 0,
    "sources": ["100ppi.com", "TDX-TQ-Local"],
    "cached_at": null,
    "llm_used": false,
    "warnings": [],
    "a2a_compatible": true
  },

  "data": {
    "symbol": "CU",
    "symbol_name": "铜",
    "exchange": "SHFE",
    "date": "2026-07-12",
    "spot_price": 72150,
    "spot_source": "100ppi.com",
    "futures_price": 72300,
    "futures_contract": "CU2408",
    "futures_month": "2024-08",
    "basis": -150,
    "basis_pct": -0.208,
    "unit": "元/吨",
    "currency": "CNY"
  },

  "summary": "铜主力合约CU2408基差-150元/吨(贴水0.21%)，现货价72150，期货72300"
}
```

#### get_term_structure("CU") 的 A2A 兼容输出

```json
{
  "type": "fdc.term_structure",
  "runtime_mode": "independent",

  "meta": {
    "data_grade": "PRIMARY",
    "data_grade_label": 0,
    "sources": ["TDX-TQ-Local"],
    "llm_used": false,
    "warnings": []
  },

  "data": {
    "symbol": "CU",
    "structure": "BACK",
    "slope_pct": 2.34,
    "near_contract": {"name": "CU2408", "price": 72300, "oi": 125000},
    "far_contract": {"name": "CU2412", "price": 71820, "oi": 68000},
    "spread": 480,
    "spread_zscore": 1.82,
    "contracts": [
      {"contract": "CU2408", "price": 72300, "oi": 125000, "volume": 35200},
      {"contract": "CU2409", "price": 72150, "oi": 98000, "volume": 28100},
      {"contract": "CU2410", "price": 72000, "oi": 82000, "volume": 19500},
      {"contract": "CU2411", "price": 71900, "oi": 71000, "volume": 14200},
      {"contract": "CU2412", "price": 71820, "oi": 68000, "volume": 12100}
    ]
  },

  "summary": "铜期限结构BACK，斜率2.34%，近月CU2408-远月CU2412价差480点(Z-score 1.82)"
}
```

#### get_f10("CU") 的 A2A 兼容输出

```json
{
  "type": "fdc.f10",
  "runtime_mode": "llm_enhanced",

  "meta": {
    "data_grade": "PRIMARY",
    "data_grade_label": 0,
    "sources": ["TDX-TQ-Local", "100ppi.com", "SHFE"],
    "llm_used": true,
    "llm_sources": ["WebSearch-Mysteel-2026-07-12"],
    "warnings": []
  },

  "data": {
    "profile": {
      "symbol": "CU", "name": "铜", "exchange": "SHFE",
      "multiplier": 5, "tick_size": 10
    },
    "quote": {
      "last_price": 72300, "change_pct": 1.25,
      "volume": 35200, "open_interest": 125000
    },
    "term_structure": {
      "structure": "BACK", "slope_pct": 2.34, "spread_zscore": 1.82
    },
    "basis": {
      "spot_price": 72150, "basis": -150, "basis_pct": -0.208
    },
    "warrant": {
      "total": 152847, "daily_change": -1250
    },
    "fundamental": {
      "supply": {"production": 95.2, "unit": "万吨", "source": "cache", "cached_at": "2026-07-04"},
      "inventory": {"social_stock": 28.5, "unit": "万吨", "percentile": 65}
    }
  },

  "summary": "铜F10报告: 行情72300(+1.25%)，期限结构BACK，基差贴水150，仓单15.3万吨(日减1250吨)"
}
```

### 9.5 A2A 数据等级标签

`data_grade_label` 帮助 Agent 判断数据可信度：

| 等级 | 标识 | 含义 | 建议的 Agent 行为 |
|:----|:----|:-----|:-----------------|
| L0 | `PRIMARY` | 主数据源直取，T+0 | 可直接用于交易决策 |
| L1 | `FRESH` | 当日更新，小时级 | 可用于分析，注意时效 |
| L2 | `DAILY` | 上一交易日 | 适用于回测，慎用于实时决策 |
| L3 | `CACHED` | 缓存数据，标注时间 | 仅作参考 |
| L4 | `REFERENCE` | 参考级非实时 | 辅助判断，不可独立决策 |
| L5 | `UNAVAILABLE` | 当前不可用 | 触发降级或拒绝 |

Agent 的消费逻辑示例：

```python
# 消费方 Agent 收到 A2APayload 后的决策
async def on_basis_data(payload: A2APayload):
    # 检查数据等级
    if payload.meta.data_grade_label <= 1:  # L0 或 L1
        return await execute_trade_decision(payload.data)
    elif payload.meta.data_grade_label == 2:
        return "数据为昨日数据，请确认是否使用"
    else:
        return "数据等级不足，请检查数据源"
```

### 9.6 批量数据输出格式

对于批量请求（如全品种扫描），返回 `A2ABatchPayload`：

```python
@dataclass
class A2ABatchPayload:
    type: str                            # "fdc.batch.kline"
    runtime_mode: str
    meta: dict
    data: list[A2APayload]              # 单品种数据列表
    summary: str
    stats: dict                         # 统计信息
```

```json
{
  "type": "fdc.batch.kline",
  "runtime_mode": "independent",

  "meta": {
    "total_symbols": 62,
    "success_count": 62,
    "failed_count": 0,
    "total_duration_ms": 4800,
    "a2a_compatible": true
  },

  "data": [ /* 62 个 A2APayload */ ],

  "stats": {
    "avg_bars": 170,
    "min_bars": 120,
    "max_bars": 200,
    "oldest_date": "2026-03-14",
    "newest_date": "2026-07-12"
  },

  "summary": "62/62 品种扫描完成，耗时 4.8s，平均 170 条/品种"
}
```

### 9.7 JSON 输出格式常量

```python
# src/futures_data_core/_a2a.py

"""
A2A 协议兼容常量与类型定义。

所有输出遵循此规范，确保 Agent 间互操作性。
"""

# 数据等级
DATA_GRADE = {
    "PRIMARY": 0,     # 主数据源直取
    "FRESH": 1,       # 当日更新
    "DAILY": 2,       # 昨日数据
    "CACHED": 3,      # 缓存
    "REFERENCE": 4,   # 参考
    "UNAVAILABLE": 5, # 不可用
}

# 运行模式
RUNTIME_MODES = {
    "INDEPENDENT": "independent",
    "LLM_ENHANCED": "llm_enhanced",
    "LLM_DRIVEN": "llm_driven",
}

# 数据类型标识
DATA_TYPES = {
    "KLINE": "fdc.kline",
    "QUOTE": "fdc.quote",
    "TERM_STRUCTURE": "fdc.term_structure",
    "SPREAD": "fdc.spread",
    "BASIS": "fdc.basis",
    "WARRANT": "fdc.warrant",
    "FUNDAMENTAL": "fdc.fundamental",
    "F10": "fdc.f10",
    "INDICATORS": "fdc.indicators",
    "SYMBOLS": "fdc.symbols",
    "BATCH": "fdc.batch",
}
```

### 9.8 关键设计原则

```
原则 1: 数据与格式分离
  A2APayload.data 包含纯业务数据，不含格式元信息
  元信息放在 A2APayload.meta 中

原则 2: 每个数据块自描述
  单个 payload 可独立使用，不依赖调用链上下文
  type + meta 足以让任意 Agent 理解数据内容

原则 3: 等级标签驱动 Agent 行为
  data_grade_label 是 Agent 路由决策的核心字段
  而非让 Agent 自行判断数据时效性

原则 4: 兼容现有 JSON 消费方
  不考虑 A2A 的调用方可以忽略外层信封
  直接读取 payload.data 获取业务数据
```

---

## 十、版本里程碑

```
v0.1.0 ─ 独立模式核心 + A2A 输出格式
├── INDEPENDENT: kline / indicators / symbols
├── A2APayload + A2ABatchPayload
├── _runtime.py / _a2a.py
└── 验证: FDT scan_all.py 输出与重构前一致

v0.2.0 ─ F10 数据 + 期限结构
├── INDEPENDENT: term_structure / spread / basis / warrant
├── A2A 标签: data_grade_label, 各数据类型标识
└── 验证: fdc basis CU A2A 格式输出

v0.3.0 ─ 基本面 + LLM 桥接
├── LLM-ENHANCED: fundamentals / f10
├── _llm_bridge.py / LLM_DEPENDENCY.md
└── 验证: 三层采集策略端到端

v1.0.0 ─ FDT 生产上线
├── FDT submodule 引用
├── scan_all.py 重构
└── 验证: 7 天稳定运行
```

---

## 十一、关键设计决策汇总

| 决策 | 结论 | 理由 |
|:----|:----|:-----|
| 仓库形态 | **独立仓库** | 独立版本、CI、多项目复用 |
| 基本面处理 | **三层策略** | 缓存→爬虫→LLM，逐层增强 |
| LLM 依赖 | **显式标注** | 每项数据标注运行模式，用户知情 |
| LLM 桥接 | **集中管理** | 所有 LLM 调用在 `_llm_bridge.py` |
| 兜底机制 | **LLM 失败时静默降级** | 不影响独立功能 |
| 基本面默认行为 | **use_llm=False** | 默认保守，显式开启增强 |
| CLI 行为 | **默认独立模式** | --use-llm 显式开启 LLM |
