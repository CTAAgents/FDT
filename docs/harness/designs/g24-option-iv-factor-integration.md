# G24: 期权隐含波动率因子集成方案

> **阶段一期范围**：优先覆盖**金融期权**（股指期权 IO/MO/HO + ETF 期权 510050/510300/510500/159915/588000）。商品期货期权推迟到二期实施。
> 数据源使用 AKShare `option_value_analysis_em()` 直接获取 IV，无需 `vollib` 依赖。

## 背景与动机

FDT 现有因子体系中，`volatility.py` 仅基于标的资产历史价格计算**历史波动率**（HV/偏度/峰度/ATR），无法捕捉市场对**未来波动率的定价预期**。期权隐含波动率（Implied Volatility, IV）从期权市场价格反推得出，反映市场参与者对未来波动率的一致预期和风险溢价定价。

在 FDT 覆盖的各市场板块中，**大部分主流期货品种和核心 ETF 均有对应期权**：

| 板块 | 代表性品种 | 对应期权 | 交易所 | 一阶段 |
|------|-----------|---------|--------|:------:|
| 金融 ETF | 510050(50ETF) / 510300(300ETF) / 510500(500ETF) / 159915(创业板) / 588000(科创50) | ETF 期权 | 上交所 / 深交所 | ✅ |
| 股指期货 | IF(沪深300) / IC(中证500) / IM(中证1000) / IH(上证50) | 股指期权 IO/MO/HO | 中金所 | ✅ |
| 商品期货 | 铜/豆粕/白糖/螺纹钢/铁矿石/原油/甲醇/PTA/黄金/白银 等 | 商品期权 | 三大商品交易所 | ⏳ 二期 |

引入期权 IV 因子可以带来以下增量价值：

- **领先性**：IV 反映市场对未来波动率的前瞻预期，领先于历史波动率
- **情绪维度**：波动率偏度（Put-Call IV Skew）直接量化市场避险情绪
- **风险溢价**：波动率风险溢价（VRP = IV - HV）作为独立套利因子，在均值回归策略中有效
- **尾部风险**：深度虚值期权的 IV 变化可预警尾部事件

---

## 可行性评估

### 数据源

| 场景 | 可行性 | 推荐方案 |
|------|--------|---------|
| 金融期权（ETF/股指）IV | 可行，稳定 | AKShare `option_value_analysis_em()` 直接返回 IV，无需反算 |
| 商品期货期权 IV | 可行（二期实施） | AKShare 新浪接口 + `vollib` 反算 IV，二期实施 |
| 全行权价全期限数据 | 可行 | AKShare 逐月拉取 + 新浪期权行情接口 |
| 日频数据 | 可行，稳定 | 盘后定时定量抓取，增量缓存 |

### 技术栈

```
数据获取：AKShare（Python 库，免费开源）
IV 反算：vollib（Python 库，BS/BSM 模型）
存储与复用：FDT fdt_cache/（SQLite 增量缓存，复用现有 CacheManager）
因子计算：numpy / pandas
集成点：FDT FactorCollector + P2.5 节点
```

### 边界

- 本阶段仅覆盖**日频**数据，Tick/分钟级期权数据暂不支持
- 一阶段仅覆盖金融期权，IV 可直接获取（东方财富接口已验证），无需 BS 模型反算
- 商品期权 IV 推迟到二期，届时需通过 BS 模型反算
- 实时期权行情（夜盘）需要后续评估是否接入通达信 TQ-Local

---

## 数据结构设计

### 新增数据类型（`data_adapter/factors/types.py`）

```python
@dataclass
class OptionIVResult:
    """期权隐含波动率因子 — 捕获市场对标的资产未来波动率的预期定价。"""
    symbol: str

    # ── IV 水平 ──
    atm_iv: Optional[float] = None        # 平值期权 IV（%）
    iv_5d: Optional[float] = None         # 5日 IV 均值（%）
    iv_20d: Optional[float] = None        # 20日 IV 均值（%）
    iv_rank_20d: Optional[float] = None   # 20日 IV 历史百分位（0~100）
    iv_percentile_3m: Optional[float] = None  # 90日 IV 历史百分位（0~100）

    # ── IV 偏度（Skew） ──
    skew_25d: Optional[float] = None      # delta=0.25 处 Put - Call IV 差
    skew_10d: Optional[float] = None      # delta=0.10 处 Put - Call IV 差（尾部偏度）
    skew_atm: Optional[float] = None      # 平值附近 Call IV - Put IV 差
    skew_slope: Optional[float] = None    # 偏度曲线斜率（OTM Put vs OTM Call）

    # ── IV 期限结构 ──
    ts_near_month: Optional[float] = None    # 近月合约平值 IV（%）
    ts_next_month: Optional[float] = None    # 次月合约平值 IV（%）
    ts_far_month: Optional[float] = None     # 远月合约平值 IV（%）
    ts_slope: Optional[float] = None         # 期限结构斜率（次月 IV - 近月 IV）
    ts_contango_pct: Optional[float] = None  # Contango 程度（正=远月更高）

    # ── 波动率风险溢价（VRP） ──
    vrp_20d: Optional[float] = None        # IV_20d - HV_20d（%）
    vrp_rank_20d: Optional[float] = None   # VRP 20日历史百分位（0~100）

    # ── 衍生指标 ──
    iv_hv_ratio: Optional[float] = None    # IV / HV 比率（>1=溢价，<1=折价）
    zscore_iv_vs_hv: Optional[float] = None  # IV vs HV 截面 Z-Score

    # ── 期权市场活跃度 ──
    option_volume: Optional[int] = None      # 期权总成交量（张）
    put_call_volume_ratio: Optional[float] = None  # Put/Call 成交量比
    option_open_interest: Optional[int] = None     # 期权总持仓量（张）

    # ── 元数据 ──
    underlying_type: str = "commodity_futures"  # 复用 MarketType 枚举值
    data_grade: str = "PRIMARY"
    extract_time: Optional[str] = None           # 数据提取时间（ISO 格式）
    option_symbol: Optional[str] = None          # 使用的期权合约代码
    freshness_hours: Optional[float] = None      # 数据新鲜度（距现在多少小时）
    is_stale: bool = False                       # 是否过期（>24 小时）
```

### 数据质量等级

沿用现有 `data_grade` 体系，新增两种等级：

| 等级 | 含义 | 赋值条件 |
|------|------|---------|
| `"PRIMARY"` | 正常 | IV 数据完整，至少 `atm_iv` 可用 |
| `"DERIVED"` | 降级（手工/合成） | 仅有少数几个行权价数据，IV 为近似值 |
| `"UNSUPPORTED"` | 品种无对应期权 | 该品种没有对应的活跃期权市场 |
| `"NO_DATA"` | 当日数据缺失 | 期权数据当日未获取到 |
| `"ERROR"` | 计算异常 | IV 反算失败（BS 模型不收敛等） |

---

### 品种-期权映射（复用 `instrument_classifier`）

**不维护独立 YAML 映射表**，而是复用 `data_adapter/instrument_classifier.py` 的 `classify()` 判断市场类型，
再通过二级路由定位对应期权代码：

```python
# data_adapter/factors/option_iv.py — 映射复用逻辑

from data_adapter.instrument_classifier import classify, MarketType

# 股指期货 → 对应股指期权代码
_INDEX_OPTION_MAP: dict[str, str] = {
    "IF": "IO",    # 沪深300 → IO
    "IC": "MO",    # 中证500 → MO
    "IH": "HO",    # 上证50 → HO
    "IM": "MO",    # 中证1000 → MO（部分月份用 MO）
}

# ETF → AKShare 板块名称
_ETF_OPTION_BOARD: dict[str, str] = {
    "510300": "沪深300ETF期权",
    "510050": "上证50ETF期权",
    "510500": "中证500ETF期权",
    "159915": "创业板ETF期权",
    "588000": "科创50ETF期权",
}


def _resolve_option_symbol(symbol: str) -> tuple[str, str] | None:
    """获取品种对应的期权前缀或板块名。

    Returns:
        (option_code_or_board, option_type) 或 None（无对应期权）。
        option_type 为 MarketType 枚举值：INDEX_FUTURES / ETF / COMMODITY_FUTURES。
    """
    mt = classify(symbol)
    if mt == MarketType.INDEX_FUTURES:
        prefix = _INDEX_OPTION_MAP.get(symbol.upper())
        return (prefix, "index_futures") if prefix else None
    if mt == MarketType.ETF:
        board = _ETF_OPTION_BOARD.get(symbol)
        return (board, "etf") if board else None
    # 商品期货 → 二期实施
    return None
```

---

## 实施计划

实施分为四个阶段，每个阶段产出可独立验证的中间成果。

### 第一阶段：数据层搭建（预计 3-5 天）

**目标**：实现期权 IV 数据的稳定获取，建立数据缓存机制。

| 步骤 | 任务 | 产出物 |
|------|------|--------|
| 1.1 | 验证 AKShare `option_value_analysis_em()` 接口，确认返回字段和稳定性 | 测试脚本 + 数据样例 |
| 1.2 | 实现 IV 采集函数 `collect_option_iv(symbols)`，支持股指期权 IO/MO/HO + ETF 期权 510050/510300/510500/159915/588000 | `data_adapter/factors/option_iv.py` |
| 1.3 | 实现 `_map_symbol_to_option(symbol)` — 品种到期权合约的映射查找 | 同上 |
| 1.4 | 实现 `_select_atm_option(options_data)` — 从期权链中自动识别平值合约 | 同上 |
| 1.5 | 实现 `_compute_skew(options_data)` — 从全行权价数据构建波动率微笑、提取偏度 | 同上 |
| 1.6 | 实现 `_compute_term_structure(options_data)` — 从多到期月数据构建期限结构 | 同上 |
| 1.7 | 建立数据缓存机制：当日数据写本地 JSON，IO 时优先读缓存 | 增量数据文件 |

**验证标准**：
- `collect_equity_option_iv(["510300"])` 可返回完整 `OptionIVResult`（atm_iv / skew / ts）
- 品种映射表覆盖一阶段所有品种（股指+ETF，约 10 个）
- 缓存命中策略：同一品种同一日不重复请求 API

**关键代码模式**（参考 `term_structure.py` 的 async 采集模式）：

```python
# data_adapter/factors/option_iv.py — 核心架构（示意）

from data_adapter.instrument_classifier import classify, MarketType
from fdt_cache import CacheManager


async def collect_option_iv(symbols: list[str]) -> dict[str, OptionIVResult]:
    """统一入口：根据品种类型自动路由到金融/商品期权 IV 采集。

    缓存复用 fdt_cache（SQLite，与 FDT 其他数据共享缓存池），
    不另建独立的 JSON 缓存目录。
    """
    cache = CacheManager.get_instance()
    results: dict[str, OptionIVResult] = {}

    for sym in symbols:
        # 1. 检查缓存（避免同一日重复请求 API）
        cached = cache.get_option_iv(sym)  # 需在 CacheManager 新增此方法
        if cached:
            results[sym] = cached
            continue

        # 2. 通过 instrument_classifier 确定期权类型
        opt_info = _resolve_option_symbol(sym)
        if opt_info is None:
            results[sym] = OptionIVResult(symbol=sym, data_grade="UNSUPPORTED")
            continue

        option_code, opt_type = opt_info
        try:
            if opt_type == "etf":
                raw = await _fetch_etf_option_iv(sym, option_code)
            elif opt_type == "index_futures":
                raw = await _fetch_index_option_iv(option_code)
            else:
                results[sym] = OptionIVResult(symbol=sym, data_grade="UNSUPPORTED")
                continue

            result = _parse_to_result(sym, raw, opt_type)

            # 3. 写入缓存
            cache.save_option_iv(sym, result)  # 需在 CacheManager 新增此方法
            results[sym] = result

        except Exception as e:
            logger.warning("[OptionIV] %s 采集失败: %s", sym, e)
            # 降级：尝试 web 保底获取
            try:
                from data_adapter.sources.web_data_fetcher import fetch_option_iv_from_web
                web_result = await fetch_option_iv_from_web(sym)
                if web_result:
                    web_result.data_grade = "DERIVED"
                    results[sym] = web_result
                    continue
            except Exception:
                pass
            results[sym] = OptionIVResult(symbol=sym, data_grade="ERROR")
    return results
```

---

### 第二阶段：因子计算层（预计 2-3 天）

**目标**：在 IV 原始数据基础上，计算衍生因子信号。

| 步骤 | 任务 | 产出物 |
|------|------|--------|
| 2.1 | 实现 `compute_iv_rank()` — IV 历史分位（20日/90日），需要构建和维护历史 IV 数据库 | `data_adapter/factors/option_iv.py` |
| 2.2 | 实现 `compute_vrp()` — 波动率风险溢价（IV - HV），需调用 `volatility.py` 的 HV 数据。当 HV 不可用时（新品种）：① 优先使用标的 20 日收益率标准差作为近似 HV；② 两者均不可用时 VRP 标记为 `None` | 同上 |
| 2.3 | 实现 `compute_skew_slope()` — 偏度曲线斜率（OTM Put IV vs OTM Call IV 之差） | 同上 |
| 2.4 | 实现 `compute_ts_slope()` — 期限结构斜率标准化（次月 IV - 近月 IV） | 同上 |
| 2.5 | 实现 `compute_put_call_ratio()` — Put/Call 成交量和持仓量比 | 同上 |
| 2.6 | 实现 IV 因子的信号量化逻辑 `_signal_from_option_iv()`（direction 使用 -2~+2 满范围） | 后续 `dashboard.py` 使用 |

**验证标准**：
- `compute_iv_rank("510300")` 返回 `0~100` 的有效百分位值
- `compute_vrp("CU")` 返回 IV-HV 差值，正/负符号符合市场直觉
- `compute_skew_slope("M")` 在期权月份切换日可正确识别新旧合约

---

### 第三阶段：FDT 集成（预计 2 天）

**目标**：将 IV 因子无缝接入 FDT 现有因子流水线。

| 步骤 | 任务 | 修改文件 |
|------|------|---------|
| 3.1 | 在 `types.py` 中添加 `OptionIVResult` 数据类型（参考已有 dataclass 模式） | `data_adapter/factors/types.py` |
| 3.2 | 在 `FactorCollector` 中注册 `collect_option_iv()` 方法（参考 `collect_term_structure` 模式） | `data_adapter/factors/__init__.py` |
| 3.3 | 在 `node_prepare_data()` 的 P2.5 因子采集块中调用 `fc.collect_option_iv(symbols)` 并注入 state（注意：**不是** `prepare_one_symbol`） | `fdt_langgraph/_nodes_prepare.py` |
| 3.4 | 在 `build_dashboard()` 中新增 `factor_option_iv` 参数。**注意**：当前 `build_dashboard()` 已有 15 个参数，建议用 `extra_factors: dict[str, dict] | None = None` 统一收口新增因子，避免持续膨胀 | `data_adapter/factors/dashboard.py` |
| 3.5 | 更新 `_TYPE_FACTOR_MAP`：为 `INDEX_FUTURES` 和 `ETF` 添加 `("option_iv", "期权IV")` 因子列 | 同上 |
| 3.6 | 在 `DebateState` 中新增 `factor_option_iv` 字段（`NotRequired[dict[str, Any]]`），按已有因子字段模式处理序列化 | `fdt_langgraph/state.py` |
| 3.7 | 品种-期权映射直接在 `option_iv.py` 中用 Python dict 维护（复用 `instrument_classifier.classify()`），**不创建独立 YAML 文件** | 不新建文件 |

**`build_dashboard()` 的信号量化逻辑**：

```python
def _signal_from_option_iv(iv: Optional[OptionIVResult]) -> Optional[FactorSignal]:
    """期权 IV 综合信号 — 综合 VRP + Skew + IV 分位三个维度。

    FactorSignal.direction 使用 -2~+2 满范围：
        -2 强烈看空（IV 极度折价+恐慌性偏度+极端高 IV 分位）
        -1 看空
         0 中性
        +1 看多（IV 溢价+乐观偏度+极端低 IV 分位）
        +2 强烈看多
    """
    if iv is None or iv.data_grade not in ("PRIMARY", "DERIVED"):
        return None

    # VRP 信号：溢价回归（贡献范围 -1.0 ~ +1.0）
    score = 0.0
    if iv.vrp_20d is not None and abs(iv.vrp_20d) > 0.5:
        score += -1.0 * np.sign(iv.vrp_20d) * min(abs(iv.vrp_20d) / 5.0, 1.0)

    # Skew 信号：偏度反映避险情绪（贡献范围 -0.5 ~ +0.5）
    if iv.skew_25d is not None and abs(iv.skew_25d) > 0.5:
        score += -0.5 * np.sign(iv.skew_25d) * min(abs(iv.skew_25d) / 3.0, 1.0)

    # IV 分位信号：极端位置（贡献范围 -0.5 ~ +0.5）
    if iv.iv_percentile_3m is not None:
        if iv.iv_percentile_3m > 80:
            score -= 0.5  # IV 高位 → 恐慌 → 反转信号
        elif iv.iv_percentile_3m < 20:
            score += 0.5  # IV 低位 → 过度乐观 → 警惕

    # 映射到 -2~+2 范围（总分范围 -2.0 ~ +2.0）
    direction = round(np.clip(score, -2.0, 2.0))
    strength = min(abs(score) / 2.0, 1.0)

    return FactorSignal(
        symbol=iv.symbol,
        direction=direction,
        strength=round(strength, 2),
        source="option_iv",
        zscore=iv.zscore_iv_vs_hv,
        percentile=iv.iv_percentile_3m,
    )
```

**`_TYPE_FACTOR_MAP` 更新**：

```python
_TYPE_FACTOR_MAP = {
    MarketType.COMMODITY_FUTURES: [
        ("option_iv", "期权IV"),
        ("volatility", "波动率"),
        # ... 其他不变（商品期权二期增加）
    ],
    MarketType.INDEX_FUTURES: [
        ("option_iv", "期权IV"),
        ("volatility", "波动率"),
        ("term_structure", "期限结构"),
        # ...
    ],
    MarketType.ETF: [  # 注意：枚举值为 ETF，不是 EQUITY_ETF
        ("option_iv", "期权IV"),
        ("volatility", "波动率"),
        ("money_flow", "资金流向"),
        # ...
    ],
}
```

**验证标准**：
- P2.5 执行后，state 中 `factor_option_iv` 作为 dict 存在
- `factor_dashboard` 的 signal 列表中包含 `option_iv` 信号
- `format_dashboard_for_prompt()` 输出的 Markdown 表格中可见"期权IV"因子列

---

### 第四阶段：测试与验证（预计 2 天）

**目标**：确保 IV 因子功能正确、性能可接受。

| 步骤 | 任务 | 产出物 |
|------|------|--------|
| 4.1 | 编写单元测试：IV 采集函数 mock 测试（覆盖正常/Primary 数据、无数据/UNSUPPORTED、异常/ERROR） | `tests/data_adapter/factors/test_option_iv.py` |
| 4.2 | 编写信号提取测试：`_signal_from_option_iv()` 在各种 IV 场景下的方向判断 | 同上 |
| 4.3 | 编写集成测试：用真实数据（510300 / 510050 / IF）测试端到端采集+计算+signal 流程 | 同上 |
| 4.4 | 编写品种映射覆盖率测试：确认 FDT 关注的各板块品种至少 80% 有对应期权 | `tests/data_adapter/factors/test_option_mapping.py` |
| 4.5 | 性能基准测试：单次 `collect_option_iv(["510300","510050","IF","IC","510500"])` 耗时 | 测试报告 |

**预期性能指标**（一阶段仅金融期权）：

| 场景 | 目标耗时 |
|------|---------|
| 全缓存命中（5 品种） | < 50ms |
| 金融期权 API 采集（5 品种） | < 3s |
| 首次全量采集（全品种） | < 10s |

---

## 里程碑与优先级

| 里程碑 | 阶段 | 优先级 | 预计工期 |
|--------|------|--------|---------|
| M1：金融期权 IV 采集可用（股指+ETF） | 一阶段 | P0 | 2 天 |
| M2：IV Rank / VRP / Skew 衍生因子就绪 | 二阶段 | P1 | 2 天 |
| M3：IV 因子接入 FDT P2.5 + Dashboard | 三阶段 | P0 | 2 天 |
| M4：品种映射表覆盖一阶段品种 | 三阶段 | P1 | 1 天 |
| M6：测试通过，性能达标 | 四阶段 | P1 | 2 天 |

**优先接入品种**（一阶段，按 FDT 实盘关注度排序）：

1. **510300**（沪深300ETF期权）— ETF 期权 IV 最成熟，AKShare 直接返回
2. **IF / IO**（沪深300股指期货/期权）— 金融期权，同数据源
3. **510050**（上证50ETF期权）— 覆盖大盘蓝筹
4. **IM / MO**（中证1000股指期货/期权）— 覆盖中小盘
5. **510500** + **159915**（中证500/创业板ETF期权）— 完整覆盖宽基

---

## 风险与应对

| 风险 | 影响 | 概率 | 应对 |
|------|------|------|------|
| AKShare 东方财富期权接口改版 | 金融期权 IV 断供 | 中 | 降级到新浪期权行情接口或上交所/中金所官网数据 |
| 期权合约月份切换时新旧合约价差 | 期限结构信号跳变 | 低 | 滚动窗口平滑，切换日前后 3 天使用加权重构 |
| 部分 FDT 品种无对应期权 | 无法获取 IV 数据 | 确定 | `data_grade="UNSUPPORTED"`，该品种跳过 IV 因子 |
| 夜盘期权行情数据缺失 | 当日 IV 计算有偏 | 中 | 以日盘收盘数据为准，在 `extract_time` 字段注明采集时间 |

---

## 附录

### A. 实施脚本清单

```
data_adapter/
└── factors/
    ├── types.py                        # [修改] +OptionIVResult（参考已有 dataclass 模式）
    ├── option_iv.py                    # [新建] IV 采集+计算（包含 _resolve_option_symbol 映射）
    ├── __init__.py                     # [修改] FactorCollector +collect_option_iv
    └── dashboard.py                    # [修改] build_dashboard +_signal_from_option_iv
                                        #         +_TYPE_FACTOR_MAP 更新
                                        #         +extra_factors 参数收口（推荐）

fdt_langgraph/
├── state.py                            # [修改] +NotRequired factor_option_iv 字段
└── _nodes_prepare.py                   # [修改] node_prepare_data() 中 P2.5 因子采集块

tests/data_adapter/factors/
├── test_option_iv.py                   # [新建] 单元测试
└── test_option_mapping.py              # [新建] 品种映射覆盖率测试

fdt_cache/
└── cache_manager.py                    # [修改] +get_option_iv() / save_option_iv()
```

### B. 依赖库

```bash
# AKShare 已在 FDT dependencies 中
# 一阶段无需额外依赖
```

### C. 参考文档

- AKShare 期权数据文档: `option_value_analysis_em()` — 一阶段唯一数据接口
- 东方财富期权价值分析页面: https://data.eastmoney.com/other/valueAnal.html
- FDT 现有因子采集架构: `data_adapter/factors/term_structure.py`（async 采集模式参考） / `data_adapter/factors/volatility.py`（纯计算模式参考）
- FDT P2.5 集成点: `fdt_langgraph/_nodes_prepare.py` node_prepare_data()（约第 550-700 行 P2.5 因子采集块）
