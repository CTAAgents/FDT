# Futures Data Collector — 独立分发 Skill 完整设计方案

**版本**: v2.0
**日期**: 2026-07-12
**状态**: 设计稿（含 F10 数据扩展方案）

---

## 一、设计目标

| 目标 | 说明 |
|:----|:-----|
| **本地优先** | 要求用户自行安装 TDX TQ-Local / TqSDK / AKShare，不做公开 API 兜底 |
| **可分发** | 作为 WorkBuddy Skill，其他用户可通过 Marketplace 一键安装或手动导入 |
| **环境自检** | 首次使用自动探测本地数据源可用性，清晰指引缺失项的安装方法 |
| **插件化** | 数据源以插件形式注册，运行时自动按优先级选择可用源 |
| **独立于 FDT** | 不依赖 FDT 的辩论管道，可被任何 WorkBuddy 用户/Actor 独立使用 |
| **F10 数据覆盖** | 在行情数据之外，覆盖基差、期限结构、仓单、供需库存等 F10 维度 |

---

## 二、数据能力总览

### 2.1 数据覆盖矩阵

```
数据类型             可靠性    来源管道                      承诺等级
─────────────────────────────────────────────────────────────────────
K 线 (OHLCV)         ★★★★★   TDX → TqSDK → AKShare → Cache   可承诺
行情快照             ★★★★★   TDX → TqSDK → AKShare           可承诺
技术指标 (18 组)     ★★★★★   TDX formula_zb + numpy 兜底     可承诺
品种清单             ★★★★★   TDX + 内置映射表                  可承诺

期限结构             ★★★★★   TDX → 东方财富双源降级           可承诺
跨期价差             ★★★★★   TDX 直取，含历史序列 + Z-score    可承诺

基差                 ★★★☆☆   现货价格采集器 (生意社/交易所)    可承诺，但有条件
仓单日报             ★★★☆☆   交易所官网 HTML 爬取             可承诺，但有条件

现货价格             ★★★☆☆   生意社 100ppi.com + 百川盈孚     可承诺，但有条件
库存数据             ★★★☆☆   WebSearch + 徽商 HS             可承诺，但有条件
供给数据             ★★★☆☆   WebSearch + 缓存兜底             可承诺，但有条件
需求数据             ★★★☆☆   WebSearch + 缓存兜底             可承诺，但有条件
利润/加工费          ★★★☆☆   WebSearch + 徽商 HS             可承诺，但有条件
供需平衡表           ★★☆☆☆   WebSearch 汇总 + 模板           参考级
宏观联动             ★★☆☆☆   静态映射                         参考级
```

**承诺等级说明**：
- **可承诺**：数据源稳定，有自动化管道，可每日更新
- **可承诺，但有条件**：需特定数据源可用（如下文说明），否则降级
- **参考级**：框架级输出，时效性不定

### 2.2 行情数据源优先级（固定顺序，无东方财富）

```
优先级 0: TDX TQ-Local (通达信本地 HTTP 服务)
  依赖: TdxW.exe 运行中, 端口 17709
  备注: 最高优先级, 覆盖 62 品种, 含 K 线/行情/期限结构/技术指标

优先级 1: TqSDK (天勤量化)
  依赖: 环境变量 TQSDK_USERNAME + TQSDK_PASSWORD
  备注: 盘中实时, 需天勤账号

优先级 2: AKShare
  依赖: pip install akshare
  备注: 开源数据, 日线/分钟线

优先级 3: DuckDB 本地缓存
  依赖: pip install duckdb
  备注: 兜底, 4h TTL 自动过期
```

**降级规则**：从优先级 0 开始，依次探测是否可用，第一个可用者返回数据。若所有源都不可用，抛出明确的错误信息，列出缺失项及修复指引。

### 2.3 F10 数据源优先级

F10 数据不同于行情数据，数据源逻辑按数据类型独立设计：

| 数据类型 | 优先级 0 | 优先级 1 | 优先级 2 |
|:---------|:--------|:---------|:---------|
| **期限结构** | TDX TQ-Local | AKShare | DuckDB 缓存 |
| **基差** | 生意社 100ppi.com (WebFetch) | 交易所现货价 | DuckDB 缓存 |
| **仓单** | SHFE/DCE/CZCE 官网 (WebFetch) | 徽商 HS (需登录) | DuckDB 缓存 |
| **供需库存** | WebSearch 行业网站 | 徽商 HS | 内置缓存兜底 |
| **利润/加工费** | WebSearch (隆众/卓创) | 徽商 HS | 内置缓存兜底 |

---

## 三、F10 数据获取方案详解

### 3.1 期限结构 (Term Structure) — 已有成熟管道

**来源**：TDX TQ-Local `get_term_structure()`，东方财富 `get_term_structure()` 降级

**输出字段**：
```
- 结构类型: BACK / CONTANGO / FLAT
- 斜率百分比 (slope_pct)
- 所有可交易合约列表 (contract: price, open_interest, volume)
- 近月合约、远月合约识别
- 跨期价差 + Z-score (来自 get_spread_history)
```

**数据质量**：55/62 品种直接覆盖，其余通过东方财富降级。单次调用 < 200ms。

**CLI 命令**：
```
fdc term-structure <symbol>        # 期限结构快照
fdc term-structure CU --history    # 含历史时间序列
fdc term-structure CU --chart      # 收益率曲线可视化
```

### 3.2 基差 (Basis) — 需新增现货采集器

**核心逻辑**：基差 = 现货价格 − 期货主力合约价格。期货价格已有，欠缺的是现货价格源。

#### 方案：生意社 100ppi.com 公开数据爬取

生意社（100ppi.com）是中国大宗商品现货报价的权威平台，覆盖 100+ 期货相关品种的现货价格，数据公开可访问。

**采集逻辑**：
```
fdc basis CU

  1. 从生意社搜索品种现货价: https://www.100ppi.com/sop/detail-CU.html
     → 获取"铜"现货价格
  2. 从 TDX/降级链 获取主力合约价格
  3. 计算基差 = 现货价 − 期货主力价
  4. 返回 { symbol, spot_price, futures_price, basis, basis_pct, date }
```

**覆盖品种预估**：60+ 品种（生意社覆盖的期货相关大宗商品）

**时效性**：生意社每日更新现货报价（工作日），基差为日频数据

**降级链**：
```
生意社 WebFetch → 交易所官网现货价 → DuckDB 缓存 → 报错提示不可用
```

**CLI 命令**：
```
fdc basis CU                          # 单品种基差
fdc basis CU --history 30             # 30 日基差历史
fdc basis --list                      # 全品种基差列表
```

**输出示例**：
```json
{
  "symbol": "CU",
  "spot_price": 72150,
  "spot_source": "100ppi.com",
  "futures_price": 72300,
  "futures_contract": "CU2408",
  "basis": -150,
  "basis_pct": -0.208,
  "date": "2026-07-12"
}
```

#### 备选：交易所官网现货价

部分交易所（SHFE 的保税铜、DCE 的生猪等）会公布现货参考价，但覆盖品种有限。生意社方案为首选。

---

### 3.3 仓单日报 (Warrant) — 交易所官网爬取

期货交易所每日公布注册仓单数据，信息完全公开。

#### 数据来源

| 交易所 | 页面结构 | 数据内容 |
|:-------|:---------|:---------|
| SHFE (上期所) | HTML 表格 | 各品种各仓库的注册仓单量、增减变化 |
| DCE (大商所) | HTML 表格 | 各品种各仓库的注册仓单量、增减变化 |
| CZCE (郑商所) | HTML 表格 | 各品种各仓库的注册仓单量、增减变化 |

**采集逻辑**：
```
fdc warrant CU

  1. 判断品种所属交易所 (CU → SHFE)
  2. WebFetch 对应交易所仓单日报页面
  3. 解析 HTML 表格，提取该品种的仓单数据
  4. 返回 { symbol, total_warrant, daily_change, warehouses: [...] }
```

**输出示例**：
```json
{
  "symbol": "CU",
  "exchange": "SHFE",
  "date": "2026-07-12",
  "total_warrant": 152847,
  "daily_change": -1250,
  "unit": "吨",
  "warehouses": [
    {"name": "上海期晟", "warrant": 24781, "change": -450},
    {"name": "国储天威", "warrant": 18520, "change": 0},
    {"name": "中储大场", "warrant": 32216, "change": -800},
    ...
  ]
}
```

**时效性**：交易所每日 15:30 后发布仓单日报，日频数据。

**降级链**：
```
交易所官网 WebFetch → 徽商 HS (需登录) → DuckDB 缓存 → 报错提示
```

**覆盖品种**：三大交易所的所有期货品种（约 60+）。

**CLI 命令**：
```
fdc warrant CU                    # 单品种仓单
fdc warrant CU --history 30       # 仓单历史变化趋势
fdc warrant --list                # 全市场仓单一览
```

---

### 3.4 供需/库存/利润数据 — WebSearch 结构化采集

这是覆盖面最广也最具挑战的模块。当前 FDT 已有缓存数据作为兜底，分发版在此基础上增加 WebSearch 自动采集管道。

#### 3.4.1 数据来源分层

```
层 1: WebSearch 实时采集 (主力)
  → Mysteel (螺纹钢/热卷/铁矿石/焦煤焦炭)
  → 隆众资讯 (原油/沥青/燃料油/LPG/PTA/甲醇)
  → 卓创资讯 (塑料/PP/PVC/乙二醇/苯乙烯)
  → MPOB (棕榈油月报)
  → 生意社 (化工品)
  
层 2: 徽商 HS (增强)
  → 结构化基本面主题数据 (需登录，需 Token)
  → 覆盖品种广，但认证门槛高

层 3: 内置静态缓存 (兜底)
  → 来自 FDT fundamental-data-collector 的存量数据
  → 标注采集时间，注明"上次更新"
```

#### 3.2.2 WebSearch 采集流程

```
fdc fundamental CU --type supply

  1. 查找品种 CU 的行业网站映射
     → CU → Mysteel (铜产业链数据)
  2. 生成搜索查询模板
     → "Mysteel 铜 产量 开工率 2026年7月"
  3. WebSearch 获取结果
  4. 解析结构化字段: 产量, 开工率, 进口量, 同比, 环比
  5. 返回结构化 JSON
```

**搜索模板库** (位于 `scripts/references/search_templates.yaml`)：

```yaml
CU:
  site: "Mysteel"
  keywords:
    supply: "Mysteel 铜 产量 开工率 2026"
    demand: "Mysteel 铜 下游 消费 开工率"
    inventory: "Mysteel 铜 库存 社会库存 保税区"
    margin: "Mysteel 铜 加工费 TC/RC"
RB:
  site: "Mysteel"
  keywords:
    supply: "Mysteel 螺纹钢 产量 开工率"
    demand: "Mysteel 螺纹钢 表观消费 成交量"
    inventory: "Mysteel 螺纹钢 社会库存 厂库"
    margin: "Mysteel 螺纹钢 利润 高炉 电炉"
SA:
  site: "隆众资讯"
  ...
```

#### 3.4.3 输出格式

```json
{
  "symbol": "CU",
  "data_type": "supply",
  "source": "Mysteel WebSearch",
  "date": "2026-07-12",
  "fields": {
    "产量": {"value": 95.2, "unit": "万吨", "change_wow": "+2.1%", "change_yoy": "+5.3%"},
    "开工率": {"value": 82.5, "unit": "%", "change_wow": "+1.2%"},
    "进口量": {"value": 45.8, "unit": "万吨", "change_yoy": "-3.2%"}
  },
  "note": "数据来自 WebSearch，准确性取决于搜索结果"
}
```

#### 3.4.4 CLI 命令

```
fdc fundamental <symbol> [options]

  获取品种基本面数据

  参数:
    symbol      品种代码
    --type      数据类型: supply, demand, inventory, margin, all (默认)
    --source    数据源: auto (默认), websearch, cache, huishang

  示例:
    fdc fundamental CU              # 全维度基本面
    fdc fundamental RB --type supply # 仅供给数据
    fdc fundamental SA --type all   # 纯碱全维度
```

#### 3.4.5 静态缓存兜底

来自 FDT 存量数据的文件位于 `scripts/references/fundamental_cache/`，结构如下：

```json
{
  "CU": {
    "supply": {
      "value": "2026年5月铜产量95.2万吨，同比增长5.3%",
      "source": "探源自研供需数据库",
      "cached_at": "2026-07-04"
    },
    "inventory": {
      "social_stock": {"value": 28.5, "unit": "万吨", "percentile": 65},
      "exchange_warrant": {"value": 15.2, "unit": "万吨"},
      "source": "探源自研供需数据库",
      "cached_at": "2026-07-04"
    },
    ...
  }
}
```

**关键设计**：每次输出都附带 `cached_at` 字段，让用户明确知道数据的时效性。

---

### 3.5 利润/加工费数据

部分品种的产业链利润数据（如铜 TC/RC、螺纹钢高炉利润、PTA 加工费）可通过 WebSearch 获取，结构同供需数据。

```
fdc fundamental CU --type margin
```

输出示例：
```json
{
  "symbol": "CU",
  "data_type": "margin",
  "fields": {
    "铜精矿TC": {"value": 12.5, "unit": "美元/吨", "percentile_3y": 15},
    "粗铜加工费": {"value": 1850, "unit": "元/吨"}
  }
}
```

---

### 3.6 F10 综合报告

将所有 F10 数据整合为一份综合报告：

```
fdc f10 <symbol> [options]

  获取品种的 F10 综合数据报告

  参数:
    symbol      品种代码
    --format    输出格式: json (默认), text

  输出内容:
    ├── 品种基本信息: 名称、交易所、合约乘数、最小变动价位
    ├── 行情快照: 最新价、涨跌幅、成交量、持仓量
    ├── 期限结构: Back/Contango、斜率、全部合约
    ├── 基差: 现货价、基差、基差率
    ├── 仓单: 注册仓单总量、日变化、仓库明细
    └── 基本面: 供给、需求、库存、利润 (按品种动态展示)
```

---

## 四、CLI 命令全集

```
行情类:
  fdc kline <symbol>              K 线数据
  fdc indicators <symbol>         技术指标
  fdc quote <symbol>              行情快照

期限/价差类:
  fdc term-structure <symbol>     期限结构 (含全部合约)
  fdc spread <symbol>             跨期价差 (含历史 + Z-score)

F10 类:
  fdc basis <symbol>              基差 (需现货价格源)
  fdc warrant <symbol>            仓单日报 (需交易所爬取)
  fdc fundamental <symbol>        基本面数据 (供需库存利润)
  fdc f10 <symbol>                F10 综合报告

工具类:
  fdc list-symbols                品种清单
  fdc setup verify                环境诊断
  fdc setup status                当前可用数据源
```

**完整示例**：
```bash
# 铜的全景分析
fdc kline CU --period daily --days 120          # K 线
fdc indicators CU --list all                     # 技术指标
fdc term-structure CU                            # 期限结构
fdc basis CU                                     # 基差
fdc warrant CU                                   # 仓单
fdc fundamental CU                               # 基本面
fdc f10 CU                                       # F10 综合报告
```

---

## 五、文件结构

```
futures-data-collector/
├── SKILL.md                                  # WorkBuddy 技能定义
│
├── scripts/
│   ├── __init__.py
│   ├── cli.py                               # argparse 入口，注册所有子命令
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── source_registry.py               # Collector 插件注册表
│   │   ├── multi_source_adapter.py          # 降级链路由（行情类）
│   │   ├── duckdb_store.py                  # DuckDB 缓存引擎
│   │   └── data_freshness.py               # 新鲜度评估
│   │
│   ├── collectors/                          # 行情采集器
│   │   ├── __init__.py
│   │   ├── base_collector.py                # BaseCollector 抽象基类
│   │   ├── tdx_collector.py                 # 通达信 TQ-Local (P0)
│   │   ├── tqsdk_collector.py               # 天勤量化 (P1)
│   │   └── akshare_collector.py             # AKShare (P2)
│   │
│   ├── f10/                                 # F10 数据采集模块 (新增)
│   │   ├── __init__.py
│   │   │
│   │   ├── term_structure.py                # 期限结构
│   │   │   ├── def get_term_structure(symbol) → dict
│   │   │   ├── def get_spread(symbol) → dict
│   │   │   └── def get_spread_history(symbol, days) → list
│   │   │
│   │   ├── basis.py                         # 基差 (新增)
│   │   │   ├── def get_basis(symbol) → dict
│   │   │   ├── def get_spot_price(symbol) → dict
│   │   │   └── def get_basis_history(symbol, days) → list
│   │   │
│   │   ├── warrant.py                       # 仓单日报 (新增)
│   │   │   ├── def get_warrant(symbol) → dict
│   │   │   ├── def get_warrant_history(symbol, days) → list
│   │   │   └── def list_warrant_all() → list
│   │   │
│   │   ├── fundamentals.py                  # 基本面采集路由 (新增)
│   │   │   ├── def get_supply(symbol) → dict
│   │   │   ├── def get_demand(symbol) → dict
│   │   │   ├── def get_inventory(symbol) → dict
│   │   │   ├── def get_margin(symbol) → dict
│   │   │   └── def get_all(symbol) → dict
│   │   │
│   │   ├── web_collector.py                 # WebSearch 采集 (原有升级)
│   │   │   ├── def search_fundamental(symbol, data_type) → dict
│   │   │   └── def search_spot_price(symbol) → dict
│   │   │
│   │   ├── exchange_scraper.py              # 交易所官网爬取 (新增)
│   │   │   ├── def scrape_warrant(symbol) → dict
│   │   │   ├── def scrape_all_warrants() → dict
│   │   │   └── SHFE/DCE/CZCE 页面解析器
│   │   │
│   │   └── cache_store.py                   # F10 缓存存储 (新增)
│   │       ├── class F10Cache
│   │       ├── get(symbol, data_type) → dict | None
│   │       └── set(symbol, data_type, data) → void
│   │
│   ├── indicators/
│   │   ├── __init__.py
│   │   └── core.py                         # numpy 向量化指标计算
│   │
│   └── references/
│       ├── data_sources.yaml               # 数据源配置
│       ├── symbol_map.yaml                 # 品种映射表 (代码→名称→交易所)
│       ├── search_templates.yaml           # WebSearch 模板库 (新增)
│       ├── exchange_urls.yaml              # 交易所页面 URL (新增)
│       └── fundamental_cache/              # 基本面静态缓存 (新增)
│           ├── supply.json
│           ├── demand.json
│           ├── inventory.json
│           ├── margin.json
│           └── README.md                   # 缓存时效说明
│
├── requirements.txt
├── setup.py
└── tests/
    ├── test_collectors/
    ├── test_core/
    ├── test_f10/                           # F10 测试 (新增)
    │   ├── test_term_structure.py
    │   ├── test_basis.py
    │   ├── test_warrant.py
    │   └── test_fundamentals.py
    ├── test_indicators.py
    └── test_cli.py
```

---

## 六、环境诊断扩展

`fdc setup verify` 的输出需扩展至 F10 数据源：

```
$ fdc setup verify

┌─ futures-data-collector 环境诊断 ──────────────────────┐
│                                                         │
│ [行情数据源]                                             │
│   ✓ TDX TQ-Local          (127.0.0.1:17709, 已连接)     │
│   ✗ TqSDK                 (TQSDK_USERNAME 未设置)       │
│   ✓ AKShare               (v1.15.10, 已安装)            │
│   ✓ DuckDB               (缓存引擎就绪)                  │
│                                                         │
│ [F10 数据源]                                             │
│   ✓ 生意社现货价格         (100ppi.com 网页可访问)        │
│   ✗ 交易所仓单日报         (SHFE 首页可访问，DCE 需检查)   │
│   ✗ 徽商 HS              (Token 未配置，登录后可用)       │
│   → 修复指引:                                             │
│     交易所仓单: pip install beautifulsoup4 lxml          │
│     徽商 HS:   fdc setup auth-huishang (交互式登录)      │
│                                                         │
│ [基本面搜索引擎]                                         │
│   ✓ WebSearch            (可用)                          │
│   ○ 静态缓存             (2026-07-04, 建议更新)           │
│                                                         │
│ ─────────────────────────────────────────────────────── │
│ 当前有效数据源: 行情(TDX+AKShare) 基差(生意社) 基本面(缓存)│
│ 建议安装: TqSDK(盘中), HS Token(增强基本面), bsl4(仓单)  │
└─────────────────────────────────────────────────────────┘
```

---

## 七、用户安装流程

```
Step 1: [必需] 安装核心包
         pip install futures-data-collector

Step 2: [强烈推荐] 安装行情源
         安装通达信: https://www.tdx.com.cn/ (启用 TQ-Local 端口 17709)
         pip install akshare          # AKShare 数据源
         pip install duckdb           # 本地缓存

Step 3: [可选] 注册天勤量化
         注册: https://www.shinnytech.com/
         设置环境变量: TQSDK_USERNAME / TQSDK_PASSWORD

Step 4: [推荐, F10 增强] 安装仓单解析依赖
         pip install beautifulsoup4 lxml

Step 5: [可选, 基本面增强] 配置徽商 HS
         fdc setup auth-huishang     # 交互式登录获取 Token

Step 6: 环境诊断
         fdc setup verify
```

### 用户看到的首次使用体验

```bash
$ pip install futures-data-collector
$ fdc setup verify

# 系统自动检测所有数据源，告诉用户当前能力范围
# 用户未装 TDX → 只能用 AKShare 获取 K 线
# 用户未配仓单 → 仓单功能不可用但有清晰指引

$ fdc kline CU    # 即使没有 TDX，也能从 AKShare 获取
$ fdc basis CU    # 如果没有现货源，会明确提示需要什么
```

---

## 八、实施路线

```
Phase 1 (2 天) — 行情骨架
  ├── 目录结构 + base_collector + source_registry
  ├── cli.py (kline + indicators + list-symbols + setup)
  ├── multi_source_adapter + duckdb_store (从 FDT 复制)
  ├── tdx_collector + akshare_collector + tqsdk_collector
  └── 验证: fdc kline/indicators 三种行情数据源

Phase 2 (1 天) — 期限结构 + 价差
  ├── f10/term_structure.py (从 FDT 复制)
  ├── cli 增加 term-structure / spread 子命令
  └── 验证: fdc term-structure CU

Phase 3 (2 天) — 基差 + 仓单管道
  ├── f10/basis.py + 生意社现货采集器
  ├── f10/exchange_scraper.py + 仓单解析
  ├── cli 增加 basis / warrant 子命令
  ├── 创建 references/exchange_urls.yaml
  └── 验证: fdc basis CU + fdc warrant CU

Phase 4 (2 天) — 基本面管道
  ├── f10/fundamentals.py + 数据路由
  ├── f10/web_collector.py (升级版，按搜索模板)
  ├── 创建 references/search_templates.yaml
  ├── 移植 FDT 现有缓存到 references/fundamental_cache/
  ├── cli 增加 fundamental / f10 子命令
  └── 验证: fdc fundamental CU --type all

Phase 5 (1 天) — 环境诊断 + 安装系统
  ├── setup verify 覆盖 F10 数据源
  ├── requirements.txt + setup.py
  ├── SKILL.md 编写（含 F10 能力说明）
  └── 测试: 从未安装过的机器上完整安装流程

Phase 6 (1 天) — 测试 + 分发准备
  ├── 单元测试 (含 F10 模块 mock 测试)
  ├── 降级场景测试 (逐个禁用数据源)
  ├── 端到端验证: fdc f10 CU 完整路径
  └── 打包发布
```

**总工期**: 7-9 天（单人）

---

## 九、依赖清单

### 核心依赖（pip install 自动安装）

| 包 | 用途 | 版本建议 |
|:---|:-----|:---------|
| requests | HTTP 请求 | >=2.28 |
| pandas | 数据处理 | >=1.5 |
| numpy | 指标计算 | >=1.24 |
| pyyaml | 配置解析 | >=6.0 |

### 可选依赖（按需安装）

| 包 | 用途 | 安装条件 |
|:---|:-----|:---------|
| akshare | AKShare 行情数据 | 需要行情降级 |
| duckdb | 本地缓存加速 | 缓存性能敏感 |
| tqsdk | 天勤量化数据 | 有天勤账号 |
| beautifulsoup4 + lxml | 交易所仓单解析 | 需要仓单功能 |
| playwright | 复杂网页 JS 渲染 (交易所) | 仓单页面需要 JS |

---

## 十、与 FDT 的集成关系

```
FDT 生产环境 (不变)                   分发版 Skill
─────────────────────               ─────────────────────
嵌入式 multi_source_adapter         独立 futures-data-collector
TDX → TqSDK → AKShare 作为嵌入      同上，独立安装
scan_all.py (含 P0-P5)              纯数据 CLI，无辩论逻辑
R23/R24 闸门 (辩论特有)              无辩论闸门
FDT 研究员调用数据                    其他用户/终端调用数据
```

**同步策略**：
- 核心算法（指标计算、期限结构计算、缓存的读写逻辑）在两版间以 git submodule 形式共享
- 配置（品种映射表、数据源参数）各自维护
- 分发版新增的 F10 采集器未来可选择性反哺 FDT

---

## 十一、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|:----|:---:|:----:|:-----|
| 生意社网站结构变更导致基差爬取失败 | 中 | 中 | 爬取代码含 CSS 选择器，升级适配；DuckDB 缓存兜底 |
| 交易所仓单页面改版 | 中 | 中 | 同基差策略；缓存 + 提示页面上一步数据 |
| WebSearch 对行业网站返回质量不稳定 | 高 | 中 | 缓存优先，WebSearch 作为增强；用户可见 data source 标注 |
| 仓单页面需要 JavaScript 渲染 | 中 | 高 | 安装 playwright 可选，或降级到静态 HTML 版 |
| 徽商 HS 认证门槛高 | 高 | 低 | HS 不列入核心依赖，作为可选增强，缺失时不影响其他功能 |
| F10 数据量过大拖慢 CLI 响应 | 低 | 中 | f10 子命令在 `--format text` 时可分页输出，JSON 按需请求 |
| 用户浏览器环境限制 WebFetch | 低 | 中 | 在 SKILL.md 中说明需要网络访问能力 |

---

## 十二、数据等级标签系统

每条数据输出附带的元信息，帮助用户判断数据可用性：

```
等级       标签          含义
─────────────────────────────────────────────────
L0         PRIMARY        主数据源直取，T+0 实时
L1         FRESH          当日更新，小时级新鲜度
L2         DAILY          上一个交易日数据
L3         CACHED         缓存数据，标注缓存时间
L4         REFERENCE      参考级非实时数据
L5         UNAVAILABLE     当前不可用，提示原因
```

**输出示例**：
```json
{
  "symbol": "CU",
  "data_type": "basis",
  "data_grade": "L1",
  "data_grade_label": "FRESH",
  "cached_at": "2026-07-12 15:30:00",
  "value": { ... }
}
```

这样用户在消费数据时可以明确知道当前数据的新鲜程度和可信度。
