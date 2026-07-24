# FDC 迁移 + AKShare 全量数据集成实施计划

> 计划版本: v2.0 | 2026-07-24
> 项目: FDT v9.26.0 → v10.0.0

---

## 0. 目标

1. **废除 FDC 多源降级链**：移除全部 5 个 legacy 采集器（TqSDK/TDX/QMT/DataCore/WebFallback）及其基础设施（熔断器、降级链路由、DataCore 桥接）
2. **AKShare 全面替代**：K 线、行情快照、仓单、持仓排名、宏观数据全部改用 AKShare
3. **新增 AKShare 数据源**：引入 FDT 目前未使用的 20+ 个 AKShare 期货数据函数（库存、资金流向、外盘、合约信息、分钟K线等）
4. **保持下游消费层不变**：`data_source_adapter.py` 所有函数签名和 A2APayload 格式不变

---

## 1. AKShare 全量数据映射矩阵

### 1.1 已集成（2个）

| AKShare 函数 | FDT 位置 | 下一步 |
|:-------------|:---------|:------|
| `futures_hist_em` | `collectors/akshare.py` | ✅ 保留 |
| `futures_spot_price_daily` | `f10/basis.py` | ✅ 保留 |

### 1.2 替换现有 FDC（4个函数 → 3个模块）

| AKShare 函数 | 替换 FDC 模块 | 原实现 |
|:-------------|:--------------|:-------|
| `macro_china_pmi` | `f10/macro.py` | httpx 东方财富 JSONP |
| `macro_china_lpr` | `f10/macro.py` | httpx 东方财富 JSONP |
| `futures_shfe_warehouse_receipt` | `f10/warrant.py` | SHFE JSON 直爬 |
| `futures_warehouse_receipt_czce` | `f10/warrant.py` | CZCE XLSX 解析 |
| `futures_warehouse_receipt_dce` | `f10/warrant.py` | DCE TSV 解析 |
| `futures_gfex_warehouse_receipt` | `f10/warrant.py` | GFEX HTML 解析 |
| `futures_dce_position_rank` | `f10/position.py` | DCE 官网 POST + API |
| `futures_gfex_position_rank` | `f10/position.py` | GFEX POST 3页合并 |
| `futures_stock_shfe_js` | `f10/position.py` | SHFE JSON 直爬 |
| `futures_zh_realtime` | K线提供者 | TDX TQ-Local 快照 |
| `futures_contract_detail_em` | K线提供者 | TDX/QMT 合约列表 |

### 1.3 新增 AKShare 数据源（新模块，FDT 未消费）

| 类别 | AKShare 函数 | 数据内容 | 新模块 | 优先级 |
|:----|:-------------|:---------|:-------|:------:|
| **库存** | `futures_inventory_em` | 东方财富大宗商品库存 | `f10/inventory.py` | P1 |
| **库存** | `futures_comex_inventory` | COMEX 铜/金/银库存 | `f10/inventory.py` | P2 |
| **资金流向** | `futures_hold_pos_sina` | 持仓量/多空持仓/资金流向 | `f10/fund_flow.py` | P1 |
| **外盘** | `futures_foreign_hist` | 外盘（美棉/美豆/伦铜等）历史K线 | `f10/foreign.py` | P1 |
| **外盘** | `futures_foreign_commodity_realtime` | 外盘实时行情 | `f10/foreign.py` | P2 |
| **全球** | `futures_global_hist_em` | 全球期货历史K线 | `f10/foreign.py` | P2 |
| **全球** | `futures_global_spot_em` | 全球现货价格 | `f10/foreign.py` | P2 |
| **合约信息** | `futures_comm_info` | 品种交易信息（保证金/涨跌停等） | `f10/contract_info.py` | P1 |
| **合约信息** | `futures_contract_detail_em` | 合约详情（上市日/交割日等） | `f10/contract_info.py` | P1 |
| **合约信息** | `futures_fees_info` | 手续费信息 | `f10/contract_info.py` | P2 |
| **合约信息** | `futures_rule` | 交易规则 | `f10/contract_info.py` | P2 |
| **分钟K线** | `futures_zh_minute_sina` | 1分钟/5分钟K线 | `collectors/akshare.py` | P2 |
| **分钟K线** | `futures_zh_daily_sina` | 新浪日K线（东方财富后备） | `collectors/akshare.py` | P2 |
| **现货** | `futures_spot_price` | 详细现货价格 | `f10/basis.py` | P3 |
| **现货** | `futures_spot_price_previous` | 前日现货价 | `f10/basis.py` | P3 |
| **期转现** | `futures_to_spot_czce/dce/shfe` | 期转现数据 | `f10/basis.py` | P3 |
| **生猪** | `futures_hog_core/cost/supply` | 生猪产业链 | `f10/hog.py` | P3 |
| **指数** | `futures_index_ccidx` | 中证商品指数 | `f10/macro.py` | P3 |
| **新闻** | `futures_news_shmet` | 上海有色网新闻 | `f10/news.py` | P3 |
| **衍生品** | `futures_derivative` | 衍生品数据 | `f10/derivative.py` | P3 |

### 1.4 不移除的模块（无 AKShare 等效）

- `f10/jin10_mcp.py` — 金十快讯/日历
- `f10/sentiment.py` — 新闻情绪打分（纯计算）
- `f10/fundamentals.py` — 静态缓存 + LLM WebSearch
- `f10/web_collector.py` / `f10/web_collector_llm.py` — 通用网页采集

---

## 2. 实施计划（6 个 Phase）

### Phase P0: 简化 K 线采集（预估 2h）

**目标**：K 线数据源从 6 级降级链简化为 AKShare 单源，保留已实现的 `collectors/akshare.py`。

#### P0.1 创建 `AKShareKlineProvider`

- **新文件**: `futures_data_core/core/akshare_provider.py`
- **内容**：
  - `get_kline()`：直接调 `akshare.futures_hist_em()` + 数据归一化
  - `get_contract_kline()`：同上
  - `get_quote()`：直接调 `akshare.futures_zh_realtime()` 或 `akshare.futures_main_sina()`
  - `get_all_active_contracts()`：调 `akshare.futures_contract_detail_em()`
  - 保留缓存回退（`CacheStore`）和数据包装（`field_normalizer` + A2APayload）
  - 移除：熔断器、降级链、`check_available`、`source_health`

#### P0.2 修改 `futures_data_core/__init__.py`

- 替换 `MultiSourceAdapter` → `AKShareKlineProvider`
- `get_adapter()` 返回新单例
- `get_kline()` / `get_quote()` / `batch_get_quotes()` 签名不变

#### P0.3 删除 10 个 legacy 文件

```
futures_data_core/collectors/tqsdk.py
futures_data_core/collectors/tdx.py
futures_data_core/collectors/qmt.py
futures_data_core/collectors/datacore.py
futures_data_core/collectors/web_fallback.py
futures_data_core/collectors/base.py
futures_data_core/core/multi_source_adapter.py
futures_data_core/core/circuit_breaker.py
futures_data_core/core/_datacore_bridge.py
futures_data_core/collectors/__init__.py (重写)
```

#### P0.4 分钟K线扩展（可选）

在 `collectors/akshare.py` 的 `get_kline()` 中，当 `period=1m/5m/15m/30m/60m` 时路由到 `akshare.futures_zh_minute_sina()`。

---

### Phase P1: F10 模块换源（预估 4.5h）

**目标**：macro/warrant/position 三个模块的底层从交易所爬虫改为 AKShare。

#### P1.1 `f10/macro.py` — AKShare 替换（0.5h）

- `get_macro_pmi()` → `akshare.macro_china_pmi()`
- `get_macro_rate()` → `akshare.macro_china_lpr()`
- 保留：环比动量计算（`_load_state`/`_save_state`）、A2APayload 包装

#### P1.2 `f10/warrant.py` — AKShare 仓单替换（2h）

- 移除 `exchange_scraper` 导入和 CZCE XLSX 解析
- 新增 `_akshare_warrant()` 按交易所路由：
  ```python
  SHFE → akshare.futures_shfe_warehouse_receipt()
  CZCE → akshare.futures_warehouse_receipt_czce()
  DCE  → akshare.futures_warehouse_receipt_dce()
  GFEX → akshare.futures_gfex_warehouse_receipt()
  ```
- 保留 `summarize_warrant()` 纯函数和 `get_warrant()` 签名

#### P1.3 `f10/position.py` — AKShare 持仓排名替换（2h）

- 移除 `exchange_scraper` / `dce_api` 导入和所有交易所特定抓取
- 新增 `_akshare_position_ranking()`：
  ```python
  DCE  → akshare.futures_dce_position_rank()
  GFEX → akshare.futures_gfex_position_rank()
  SHFE → akshare.futures_stock_shfe_js()
  ```
- 移除 Data-Core first 检查
- 保留 `get_position_ranking()` 签名

---

### Phase P2: 新增 AKShare 数据源（预估 6h）

**目标**：创建 5 个新 F10 模块，集成 AKShare 尚未使用的期货数据。

#### P2.1 新增 `futures_data_core/f10/inventory.py` — 库存数据（1.5h）

- 数据类型: `fdc.inventory`（在 `_a2a.py` 新增 `INVENTORY: "fdc.inventory"`）
- 核心函数: `get_inventory(symbol) → A2APayload`
- 数据源:
  - 主力: `akshare.futures_inventory_em()` — 东方财富库存
  - 后备: `akshare.futures_comex_inventory()` — COMEX 库存（有色品种）
- 数据格式:
  ```json
  {
    "symbol": "CU",
    "inventory": 123456,
    "unit": "吨",
    "change": -500,
    "data_date": "2026-07-24",
    "source": "eastmoney"
  }
  ```

#### P2.2 新增 `futures_data_core/f10/fund_flow.py` — 资金流向（1.5h）

- 数据类型: `fdc.fund_flow`（在 `_a2a.py` 新增）
- 核心函数: `get_fund_flow(symbol) → A2APayload`
- 数据源: `akshare.futures_hold_pos_sina()`
- 数据格式:
  ```json
  {
    "symbol": "CF",
    "total_oi": 500000,
    "long_volume": 280000,
    "short_volume": 220000,
    "long_short_ratio": 1.27,
    "data_date": "2026-07-24"
  }
  ```

#### P2.3 新增 `futures_data_core/f10/foreign.py` — 外盘数据（1.5h）

- 数据类型: `fdc.foreign`（在 `_a2a.py` 新增）
- 核心函数: `get_foreign_hist(symbol) → A2APayload`
- 品种映射（FDT 品种 → 外盘代码）:
  ```python
  _FOREIGN_MAP = {
      "CF": "ICE.CF",     # 美棉
      "M":  "CBOT.M",     # 美豆
      "Y":  "CBOT.BO",    # 美豆油
      "CU": "LME.CU",     # 伦铜
      "AL": "LME.AL",     # 伦铝
      "ZN": "LME.ZN",     # 伦锌
      "SC": "NYMEX.CL",   # 美原油
      "AU": "COMEX.AU",   # 美黄金
      "AG": "COMEX.AG",   # 美白银
      "RU": "TOCOM.RU",   # 日胶
  }
  ```
- 数据源: `akshare.futures_foreign_hist(symbol, period)`

#### P2.4 新增 `futures_data_core/f10/contract_info.py` — 合约信息（1h）

- 数据类型: `fdc.contract_info`（在 `_a2a.py` 新增）
- 核心函数: `get_contract_info(symbol) → A2APayload`
- 数据源:
  - `akshare.futures_comm_info()` — 品种交易信息
  - `akshare.futures_contract_detail_em()` — 合约详情

#### P2.5 注册新数据源到 `data_source_adapter.py`

- 新增导出函数:
  ```python
  async def get_inventory(symbol) → A2APayload
  async def get_fund_flow(symbol) → A2APayload
  async def get_foreign_hist(symbol, period="daily") → A2APayload
  async def get_contract_info(symbol) → A2APayload
  ```

#### P2.6 新数据源注入 P2.5 辩论流程

- 修改 `fdt_langgraph/nodes.py` 的 `collect_symbol_data()` 函数
- 新增数据采集开关（环境变量或 state flag）:
  - `FDT_FDC_INVENTORY_ENABLED`（默认 true）
  - `FDT_FDC_FUND_FLOW_ENABLED`（默认 true）
  - `FDT_FDC_FOREIGN_ENABLED`（默认 true）
- 新增数据采集调用:
  ```python
  if inventory_enabled:
      payload = await get_inventory(symbol)
      symbol_data["inventory"] = {"data": payload.data, "summary": payload.summary}
  if fund_flow_enabled:
      payload = await get_fund_flow(symbol)
      symbol_data["fund_flow"] = {"data": payload.data, "summary": payload.summary}
  if foreign_enabled:
      payload = await get_foreign_hist(symbol)
      symbol_data["foreign"] = {"data": payload.data, "summary": payload.summary}
  ```

---

### Phase P3: 清理遗留（预估 1h）

#### P3.1 删除已替代的文件

```
futures_data_core/f10/exchange_scraper.py
futures_data_core/f10/dce_api.py
futures_data_core/f10/huishang.py
futures_data_core/f10/test_macro.py
futures_data_core/f10/test_dce_api.py
futures_data_core/f10/test_position.py
futures_data_core/config/data_sources.yaml
futures_data_core/config/settings.py
futures_data_core/cli.py
futures_data_core/mcp_client.py
```

#### P3.2 清理 `f10/__init__.py`

移除 exchange_scraper / huishang 相关导出。

#### P3.3 清理 `data_source_adapter.py`

移除 `get_warrant_fdc()`、`_import_fdc_sub()` 中已删除模块的分支。

#### P3.4 更新 `requirements.lock`

标记 `tqsdk` / `xtquant` 为可选依赖或移除。

---

### Phase P4: 测试验证（预估 4h）

#### P4.1 替换验证

| 测试 | 预期 |
|:-----|:------|
| `get_kline("CF", days=60)` | 返回 60 根 bars |
| `get_quote("CF")` | 返回行情快照 |
| `get_macro_pmi()` | 返回 PMI 值 |
| `get_macro_rate()` | 返回 LPR 值 |
| `get_warrant("CF")` | 返回仓单数据 |
| `get_warrant("RB")` | 返回仓单数据 |
| `get_position_ranking("RB")` | 返回持仓排名 |
| `get_position_ranking("SI")` | 返回持仓排名 |

#### P4.2 新增验证

| 测试 | 预期 |
|:-----|:------|
| `get_inventory("CU")` | 返回库存数据 |
| `get_fund_flow("CF")` | 返回资金流向 |
| `get_foreign_hist("CF")` | 返回外盘K线 |
| `get_contract_info("CF")` | 返回合约信息 |

#### P4.3 集成验证

- `node_prepare_data()` 执行后 `fdc_data` 包含新字段
- `data_source_adapter.get_f10()` 正常聚合
- 确认无遗留 import 指向已删除模块

---

### Phase P5: 文档 + 版本（预估 1h）

#### P5.1 版本号

`pyproject.toml`: 9.26.0 → 10.0.0（重大架构变更）

#### P5.2 文档更新

- `docs/harness/01-architecture.md`：移除 TqSDK/QMT/TDX/DataCore，更新数据流图
- `docs/harness/07-operations.md`：v10.0.0 版本历史
- `docs/harness/03-configuration.md`：移除旧数据源配置
- `README.md`：更新技术栈和数据架构

---

## 3. A2A 新增类型

`_a2a.py` 的 `DATA_TYPES` 新增：

```python
DATA_TYPES = {
    # ...已有类型...
    "INVENTORY": "fdc.inventory",       # 库存数据
    "FUND_FLOW": "fdc.fund_flow",       # 资金流向
    "FOREIGN": "fdc.foreign",           # 外盘数据
    "CONTRACT_INFO": "fdc.contract_info", # 合约信息
}
```

---

## 4. 文件变更总清单

### 新建文件（6个）

| 文件 | 行数预估 | 用途 |
|:-----|:--------:|:-----|
| `futures_data_core/core/akshare_provider.py` | ~250 | AKShare 单源K线/行情提供者 |
| `futures_data_core/f10/inventory.py` | ~120 | 库存数据 |
| `futures_data_core/f10/fund_flow.py` | ~100 | 资金流向 |
| `futures_data_core/f10/foreign.py` | ~150 | 外盘数据 |
| `futures_data_core/f10/contract_info.py` | ~100 | 合约信息 |

### 修改文件（10个）

| 文件 | 变更 |
|:-----|:------|
| `futures_data_core/_a2a.py` | 新增 4 个 DATA_TYPES |
| `futures_data_core/__init__.py` | 替换 `MultiSourceAdapter` → `AKShareKlineProvider` |
| `futures_data_core/f10/macro.py` | httpx → AKShare |
| `futures_data_core/f10/warrant.py` | 交易所爬虫 → AKShare |
| `futures_data_core/f10/position.py` | 交易所爬虫 → AKShare |
| `futures_data_core/f10/__init__.py` | 移除旧导出，新增新模块导出 |
| `futures_data_core/collectors/__init__.py` | 仅保留 AKShareCollector |
| `futures_data_core/collectors/akshare.py` | 可选：分钟K线扩展 |
| `data_source_adapter.py` | 新增 4 个导出函数 + 清理旧桥接 |
| `fdt_langgraph/nodes.py` | P2.5 新增 inventory/fund_flow/foreign 采集 |

### 删除文件（16个）

见 Phase P0.3 和 P3.1 清单。

---

## 5. 工作量汇总

```
Phase P0: 简化K线采集       ████████░░░░  2.0h
Phase P1: F10模块换源        ██████████████████░░  4.5h
  ├── P1.1 macro.py         ██░░  0.5h
  ├── P1.2 warrant.py       ████████  2.0h
  └── P1.3 position.py      ████████  2.0h
Phase P2: 新增AKShare数据源  ████████████████████████  6.0h
  ├── P2.1 inventory.py     ██████  1.5h
  ├── P2.2 fund_flow.py     ██████  1.5h
  ├── P2.3 foreign.py       ██████  1.5h
  ├── P2.4 contract_info.py ████  1.0h
  ├── P2.5 data_source_adapter ██  0.3h
  └── P2.6 nodes.py注入     ██  0.2h
Phase P3: 清理遗留           ████  1.0h
Phase P4: 测试验证           ████████████████  4.0h
Phase P5: 文档+版本          ████  1.0h
──────────────────────────────────────
总计                       18.5h
```

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|:-----|:----|:------|
| AKShare 高频更新导致函数变动 | **高** | 锁定版本 `<2.0.0`，pre-commit 加 akshare 回归测试 |
| 外盘数据 `futures_foreign_hist` 参数复杂 | **中** | 先做 5 个核心品种映射，逐步扩展 |
| 库存数据字段不稳定 | **中** | 每个函数套 try/except，失败返回 UNAVAILABLE |
| P2.5 新增 3 维数据 → 45s 超时压力 | **中** | 设独立超时（每个新源 10s），避免阻塞主流程 |

---

*本计划由掌柜确认后方可