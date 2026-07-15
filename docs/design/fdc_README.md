<p align="center">
  <strong><span style="font-size:28px">fdc · Futures Data Core</span></strong>
</p>

<p align="center">
  独立运行的期货数据采集模块 — K 线 · 技术指标 · 期限结构 · 基差 · 仓单 · 基本面
</p>

<p align="center">
  <code>pip install futures-data-core</code> &nbsp;·&nbsp;
  <code>fdc kline CU</code> &nbsp;·&nbsp;
  <code>from futures_data_core import get_kline</code>
</p>

---

## 概述

**fdc** 是一个独立运行的期货数据采集 Python 包，从 FDT（Futures Debate Team）辩论专家团的采集引擎中解耦提取而来。

核心设计目标：

- **独立运行** — 纯 Python 代码，不依赖 LLM 环境即可获取行情、指标、期限结构化等数据
- **多源降级** — TDX TQ-Local → TqSDK → AKShare → 本地缓存，自动按优先级降级
- **Async 接口** — 全异步 IO，支持 `asyncio.gather` 批量并发采集
- **A2A 兼容** — 输出遵循 Agent-to-Agent 协议，任意 Agent 系统可直接消费
- **显式 LLM 标注** — 每项数据标注运行模式，无隐藏依赖

---

## 数据能力

### 覆盖范围

| 数据类型 | 运行模式 | 工具链 | 可靠性 |
|:---------|:--------|:-------|:------:|
| K 线 (OHLCVI + 持仓量) | [INDEPENDENT] | TDX → TqSDK → AKShare → Cache | ★★★★★ |
| 行情快照 | [INDEPENDENT] | TDX → TqSDK | ★★★★★ |
| 技术指标 (18 组) | [INDEPENDENT] | TDX formula_zb + numpy 兜底 | ★★★★★ |
| 品种清单 | [INDEPENDENT] | 内置品种映射表 | ★★★★★ |
| **期限结构** | [INDEPENDENT] | TDX → AKShare 双源降级 | ★★★★★ |
| **跨期价差** | [INDEPENDENT] | TDX 直取，含历史序列 + Z-score | ★★★★★ |
| **基差** (现货-期货) | [INDEPENDENT] | httpx → 生意社 100ppi.com + bs4 | ★★★☆☆ |
| **仓单日报** | [INDEPENDENT] | httpx → SHFE/DCE/CZCE + bs4 | ★★★☆☆ |
| **持仓排名** (会员持仓) | [INDEPENDENT] | 五家交易所官网直连（SHFE/CFFEX/CZCE/GFEX + DCE 官方 API） | ★★★★★ |
| **基本面** (供需库存利润) | [LLM-ENHANCED] | 静态缓存 + WebSearch 实时 | ★★☆☆☆ |

### 运行模式说明

| 模式 | 标签 | 含义 |
|:----|:----|:------|
| **独立模式** | `[INDEPENDENT]` | 纯 Python，零 LLM 依赖，任环境可运行 |
| **LLM 增强模式** | `[LLM-ENHANCED]` | 基础独立可用，`use_llm=True` 时通过 LLM 获取实时数据 |
| **LLM 驱动模式** | `[LLM-DRIVEN]` | 必须 LLM 环境，当前方案中仅 WebSearch 搜索环节 |

---

## 快速开始

### 安装

```bash
# 核心安装（K线、指标、期限结构、基差、仓单 → 全部独立可用）
pip install futures-data-core

# 可选增强
pip install akshare          # AKShare 行情数据源
pip install duckdb           # 本地缓存加速
pip install tqsdk            # 天勤量化数据源
```

### 环境诊断

```bash
fdc setup verify
```

自动检测 TDX 服务、TqSDK 凭据、AKShare 安装状态，输出每项数据的当前可用性。

### Python 调用

```python
import asyncio
from futures_data_core import get_kline, get_basis, get_warrant, get_term_structure

async def analyze_cu():
    kline = await get_kline("CU", period="daily", days=120)
    basis = await get_basis("CU")
    warrant = await get_warrant("CU")
    ts = await get_term_structure("CU")
    return {"kline": kline, "basis": basis, "warrant": warrant, "term_structure": ts}

result = asyncio.run(analyze_cu())
```

### CLI 使用

```bash
# 行情
fdc kline CU --period daily --days 120
fdc indicators CU --list all

# 期限与价差
fdc term-structure CU
fdc spread CU --history 60

# F10 数据
fdc basis CU
fdc warrant CU
fdc fundamental CU --type all
fdc fundamental CU --type supply --use-llm   # LLM 增强模式

# 综合报告
fdc f10 CU

# 工具
fdc list-symbols --exchange SHFE
fdc setup status --verbose
```

---

## 数据输出格式（A2A 兼容）

所有 API 返回统一的 `A2APayload` 信封，符合 Agent-to-Agent 协议规范。

### 结构

```python
@dataclass
class A2APayload:
    type: str              # 数据类型标识，如 "fdc.basis"
    runtime_mode: str      # "independent" / "llm_enhanced"
    meta: dict             # 元信息（数据等级、来源、时效）
    data: dict             # 纯业务数据
    summary: str           # 自然语言描述
```

### 示例

```json
{
  "type": "fdc.basis",
  "runtime_mode": "independent",
  "meta": {
    "data_grade": "PRIMARY",
    "data_grade_label": 0,
    "sources": ["100ppi.com", "TDX-TQ-Local"],
    "cached_at": null,
    "llm_used": false
  },
  "data": {
    "symbol": "CU",
    "spot_price": 72150,
    "futures_price": 72300,
    "basis": -150,
    "basis_pct": -0.208
  },
  "summary": "铜主力合约CU2408基差-150元/吨(贴水0.21%)"
}
```

### 数据类型标识

| API | type | 说明 |
|:----|:-----|:-----|
| `get_kline` | `fdc.kline` | K 线数据 |
| `get_term_structure` | `fdc.term_structure` | 期限结构 |
| `get_spread` | `fdc.spread` | 跨期价差 |
| `get_basis` | `fdc.basis` | 基差 |
| `get_warrant` | `fdc.warrant` | 仓单日报 |
| `get_fundamental` | `fdc.fundamental` | 基本面 |
| `get_f10` | `fdc.f10` | F10 综合报告 |

---

## 数据源配置

fdc 默认按以下优先级自动降级：

| 优先级 | 数据源 | 依赖 |
|:------:|:-------|:-----|
| 0 | TDX TQ-Local | 本机通达信客户端 + 端口 17709 |
| 1 | TqSDK 天勤量化 | 环境变量 TQSDK_USERNAME + PASSWORD |
| 2 | AKShare | `pip install akshare` |
| 3 | DuckDB 本地缓存 | `pip install duckdb` |

数据源参数可通过 `~/.fdc/config.yaml` 或环境变量覆盖。

---

## 版本

```text
v0.1.0 — 独立模式核心 + A2A 输出格式 (当前)
         K 线 / 指标 / 期限结构 / 基差 / 仓单
v0.2.0 — 基本面 + LLM 增强
         供需库存利润 / LLM WebSearch
v1.0.0 — 生产稳定
         完整测试覆盖 / FDT 上线运行
```

---

## 相关项目

- [FDT / Futures Debate Team](https://github.com/yourname/futures-debate-team) — 期货多空辩论专家团，fdc 的上游消费方
- [quant-skills](https://github.com/yourname/quant-skills) — 量化策略 skills 集合

---

## License

MIT
