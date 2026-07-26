# 因子看板增强 — 资金流向/北向资金/ETF 溢价注入实施方案

> **版本**: v0.1 (设计草案)
> **日期**: 2026-07-26
> **关联**: G23 全市场因子驱动 / 腾讯自选股 MCP 数据源

---

## 1. 问题陈述

当前因子看板（`dashboard.py`）仅支持 4 个因子源：

| 因子源 | 信号提取函数 | 适用品种 |
|:-------|:------------|:---------|
| `volatility` | `_signal_from_volatility()` | 全品种 |
| `term_structure` | `_signal_from_term_structure()` | 期货 |
| `holding_sentiment` | `_signal_from_holding_sentiment()` | 期货 |
| `cross_spread` | `_signals_from_cross_spreads()` | 期货 |

腾讯自选股 MCP 新增的 **3 个特有因子**（资金流向/北向资金/ETF溢价）虽然已在 P2.5 采集并注入 state，但**未被因子看板消费**，闫判官看不到这些信号。

### 差距

| 因子 | 数据已采集 | state 注入 | Dashboard 消费 | 闫判官可见 |
|:-----|:---------:|:---------:|:-------------:|:---------:|
| 资金流向 (money_flow) | ✅ P2.5 | `factor_money_flow` | ❌ | ❌ |
| 北向资金 (north_flow) | ✅ P2.5 | `factor_north_flow` | ❌ | ❌ |
| ETF 溢价 (etf_premium) | ❌ P2.5 | 未采集 | ❌ | ❌ |

---

## 2. 设计目标

1. **新增 3 个信号提取函数**：`_signal_from_money_flow()` / `_signal_from_north_flow()` / `_signal_from_etf_premium()`
2. **扩展 `build_dashboard()` 签名**：接受 3 个新参数，注入 dashboard
3. **ETF 溢价数据加入 P2.5 采集**：通过 `data_adapter.get_etf_premium()` 采集
4. **类型感知渲染（架构决策）**：统一 `FactorDashboardResult` 存储，`format_dashboard_for_prompt()` 按资产类型分组渲染子表格
5. **更新 `build_matrix()`**：自动继承新因子
6. **全链路验证**：P2.5 → dashboard → 闫判官 prompt

---

## 3. 架构变更

### 3.1 数据模型层 — 统一存储

保持 `FactorDashboardResult` 不变，所有因子信号统一存储在 `signals: dict[str, list[FactorSignal]]` 中。
每种资产类型只采集相关的因子，不相关的因子不产生信号（即期货品种的 `factor_money_flow` 为空 dict）。

```
FactorDashboardResult
  ├── symbols: ["RB", "IF", "600519", "510050"]
  ├── signals: {
  │     "RB":     [vol_sig, ts_sig, hs_sig, cs_sig]       # 4个期货因子
  │     "IF":     [vol_sig, ts_sig, hs_sig]               # 3个股指因子
  │     "600519": [vol_sig, mf_sig, nf_sig]               # 3个权益因子
  │     "510050": [vol_sig, mf_sig, nf_sig, ep_sig]       # 4个ETF因子
  │   }
  ├── consensus: { "RB": 3, "600519": 1 }
  └── divergence: { "RB": 0.25, "600519": 0.15 }
```

### 3.2 渲染层 — 类型感知分组渲染

`format_dashboard_for_prompt()` 接收一个额外的 `market_types: dict[str, MarketType]` 参数，
按市场类型将品种分组，每种类型渲染独立的子表格，只展示该类型相关的因子列。

```
输出格式（闫判官 prompt 中）：
═══════════════════════════════════════════════════════════════

【多因子信号一致性看板】

── 商品期货 ──
品种 | 波动率 | 期限结构 | 多空持仓 | 价差 | 汇总 | 分歧度
RB   | +1     | +1       | 0        | +1   | +3   | 0.25
CU   | 0      | -1       | -1       | 0    | -2   | 0.10

── 股指期货 ──
品种 | 波动率 | 期限结构 | 多空持仓 | 汇总 | 分歧度
IF   | +1     | 0        | +1       | +2   | 0.10

── 股票 ──
品种    | 波动率 | 资金流向 | 北向资金 | 汇总 | 分歧度
600519  | +1     | +1       | 0        | +2   | 0.10

── ETF ──
品种   | 波动率 | 资金流向 | 北向资金 | ETF溢价 | 汇总 | 分歧度
510050 | 0      | +1       | +1       | -1      | +1   | 0.33

分歧度 < 0.2 → 因子共振，高确信度
分歧度 0.2~0.5 → 因子分歧，需辩论揭示关键矛盾
分歧度 > 0.5 → 极度分歧，降低置信度
```

### 3.3 类型-因子映射表

```python
# format_dashboard_for_prompt 内部定义
_TYPE_FACTOR_MAP: dict[MarketType, list[tuple[str, str]]] = {
    MarketType.COMMODITY_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("cross_spread", "价差"),
    ],
    MarketType.INDEX_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.BOND_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.STOCK: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"),
    ],
    MarketType.ETF: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"), ("etf_premium", "ETF溢价"),
    ],
    MarketType.CONVERTIBLE_BOND: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
    MarketType.REIT: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
}
```

### 3.4 因子列自动补全

由于按类型分组渲染，每种类型的子表格列头是固定的。
品种在该因子无数据时显示 "—"（而非 "0"），区分"方向中性"和"数据不可用"。

### 3.5 `build_dashboard()` 签名扩展

```
┌── 已有参数（不变） ──────────────────────────────────────────┐
│  symbols, term_structure, volatility,                        │
│  holding_sentiment, cross_spreads                             │
└──────────────────────────────────────────────────────────────┘

┌── 新增参数（腾讯特有） ─────────────────────────────────────┐
│  money_flow: dict[str, dict]     ← state["factor_money_flow"] │
│  north_flow: dict[str, dict]     ← state["factor_north_flow"] │
│  etf_premium: dict[str, dict]    ← state["factor_etf_premium"]│
└──────────────────────────────────────────────────────────────┘

输出: FactorSignal 中新增 source:
  - "money_flow"
  - "north_flow"  
  - "etf_premium"
```

### 因子信号量化规则

| 因子 | 规则 | 方向 |
|:-----|:-----|:----:|
| 资金流向 | 主力净流入 > 0 → 看多，< 0 → 看空 | ±1 ~ ±2 |
| 北向资金 | 北向净买入 > 0 → 看多（外资加仓） | ±1 |
| ETF 溢价 | 溢价 > 1% → 市场情绪过热 → 看空；折价 > 1% → 看多 | ±1 |

---

## 4. 执行计划

### Task 1: Dashboard 新增 3 个信号提取函数

**文件**: `data_adapter/factors/dashboard.py`

- [ ] **Step 1: 新增 `_signal_from_money_flow()`**

```python
def _signal_from_money_flow(mf: dict | None) -> Optional[FactorSignal]:
    """从资金流向因子提取方向信号。

    主力净流入 > 0 → 看多（机构看好）
    主力净流入 < 0 → 看空（机构撤离）
    强度 = 主力净流入 / max(|中户|+|散户|, 1) 归一化
    """
    if not mf or mf.get("data_grade") != "PRIMARY":
        return None

    main_n = mf.get("main_net_inflow")
    if main_n is None:
        return None

    symbol = mf.get("symbol", "?")
    direction = 0
    if main_n > 0:
        direction = 1 if main_n > 0 else -1
    elif main_n < 0:
        direction = -1

    # 强度：主力净流入相对散户+中户的比例
    retail_n = abs(mf.get("retail_net_inflow", 0) or 0)
    mid_n = abs(mf.get("mid_net_inflow", 0) or 0)
    denominator = retail_n + mid_n
    if denominator > 0 and direction != 0:
        strength = min(abs(main_n) / denominator, 1.0)
    else:
        strength = 0.3 if direction != 0 else 0.0

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="money_flow",
    )
```

- [ ] **Step 2: 新增 `_signal_from_north_flow()`**

```python
def _signal_from_north_flow(nf: dict | None) -> Optional[FactorSignal]:
    """从北向资金因子提取方向信号。

    北向净买入 > 0 → +1（外资加仓，看多）
    北向净买入 < 0 → -1（外资减仓，看空）
    """
    if not nf or nf.get("data_grade") != "PRIMARY":
        return None

    net_buy = nf.get("north_net_buy")
    if net_buy is None:
        return None

    symbol = nf.get("symbol", "?")
    direction = 0
    if net_buy > 0:
        direction = 1
    elif net_buy < 0:
        direction = -1

    # 强度：持股占比越高，信号越强
    pct = nf.get("north_holding_pct")
    strength = min(abs(pct or 0) / 10, 1.0) if pct else 0.3
    if direction == 0:
        strength = 0.0

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="north_flow",
    )
```

- [ ] **Step 3: 新增 `_signal_from_etf_premium()`**

```python
def _signal_from_etf_premium(ep: dict | None) -> Optional[FactorSignal]:
    """从 ETF 溢价因子提取方向信号。

    溢价 > 1% → 市场情绪过热，短期回调风险 → -1（看空）
    折价 > 1% → 市场情绪低迷，短期反弹机会 → +1（看多）
    """
    if not ep or ep.get("data_grade") != "PRIMARY":
        return None

    premium = ep.get("premium_pct")
    if premium is None:
        return None

    symbol = ep.get("symbol", "?")
    direction = 0
    if premium > 1.0:
        direction = -1  # 溢价过高，看空
    elif premium < -1.0:
        direction = 1   # 折价过大，看多

    strength = min(abs(premium) / 5, 1.0) if direction != 0 else 0.0

    return FactorSignal(
        symbol=symbol,
        direction=direction,
        strength=round(strength, 2),
        source="etf_premium",
    )
```

- [ ] **Step 4: 运行测试验证导入**

Run: `python -m pytest tests/data_adapter/factors/test_dashboard.py -v`
Expected: 7 passed (不影响现有测试)

### Task 2: 类型感知 `format_dashboard_for_prompt()` 重构 + 信号集成

**文件**: `data_adapter/factors/dashboard.py`

这是最核心的任务。`format_dashboard_for_prompt()` 从单一大表格改造成按资产类型分组渲染。
需在 `build_dashboard()` 循环中添加新信号，然后重构 format 函数。

- [ ] **Step 1: 修改 `build_dashboard()` 签名和循环体**

```python
def build_dashboard(
    symbols: list[str],
    term_structure: dict[str, TermStructureResult],
    volatility: dict[str, VolatilityResult],
    holding_sentiment: dict[str, HoldingSentimentResult],
    cross_spreads: list[CrossSpreadResult],
    # ── 新增参数（腾讯特有，dict 降级友好） ──
    money_flow: dict[str, dict] | None = None,
    north_flow: dict[str, dict] | None = None,
    etf_premium: dict[str, dict] | None = None,
) -> FactorDashboardResult:
```

在 `for sym in symbols:` 循环中，`signals.extend(spread_signals)` 之后添加：

```python
        # ── 资金流向信号（腾讯特有） ──
        mf_data = (money_flow or {}).get(bare)
        mf_signal = _signal_from_money_flow(mf_data)
        if mf_signal:
            signals.append(mf_signal)

        # ── 北向资金信号（腾讯特有） ──
        nf_data = (north_flow or {}).get(bare)
        nf_signal = _signal_from_north_flow(nf_data)
        if nf_signal:
            signals.append(nf_signal)

        # ── ETF 溢价信号（腾讯特有） ──
        ep_data = (etf_premium or {}).get(bare)
        ep_signal = _signal_from_etf_premium(ep_data)
        if ep_signal:
            signals.append(ep_signal)
```

- [ ] **Step 2: 在文件顶部定义类型-因子映射表**

```python
from data_adapter.instrument_classifier import MarketType

# 类型感知看板：每种市场类型对应的因子列
# key=MarketType, value=[(source_name, 中文标签), ...]
_TYPE_FACTOR_MAP: dict[MarketType, list[tuple[str, str]]] = {
    MarketType.COMMODITY_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"), ("cross_spread", "价差"),
    ],
    MarketType.INDEX_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.BOND_FUTURES: [
        ("volatility", "波动率"), ("term_structure", "期限结构"),
        ("holding_sentiment", "多空持仓"),
    ],
    MarketType.STOCK: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"),
    ],
    MarketType.ETF: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
        ("north_flow", "北向资金"), ("etf_premium", "ETF溢价"),
    ],
    MarketType.CONVERTIBLE_BOND: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
    MarketType.REIT: [
        ("volatility", "波动率"), ("money_flow", "资金流向"),
    ],
}
```

- [ ] **Step 3: 重构 `format_dashboard_for_prompt()` 为类型感知渲染**

```python
def format_dashboard_for_prompt(
    dashboard: FactorDashboardResult,
    market_types: dict[str, MarketType] | None = None,
) -> str:
    """将因子看板格式化为 LLM prompt 可读的文本表格。

    按市场类型分组渲染子表格，每种类型只展示相关因子列。
    可通过 market_types 参数传入 {symbol: MarketType} 映射；
    未传入时使用 classify() 自动判断。

    Args:
        dashboard: 因子看板数据
        market_types: {symbol: MarketType} 映射（可选）

    Returns:
        格式化后的文本表格。
    """
    if dashboard.data_grade == "NO_DATA" or not dashboard.signals:
        return "\n【多因子信号一致性看板】暂无因子数据。\n"

    from data_adapter.instrument_classifier import classify

    lines = ["\n【多因子信号一致性看板】"]
    added_separator = False

    # 按市场类型分组
    type_groups: dict[str, list[str]] = {}
    for bare in dashboard.symbols:
        if market_types and bare in market_types:
            mt = market_types[bare]
        else:
            mt = classify(bare)
        type_name = mt.value
        if type_name not in type_groups:
            type_groups[type_name] = []
        type_groups[type_name].append(bare)

    # 类型中文标签
    type_labels = {
        "commodity_futures": "商品期货", "index_futures": "股指期货",
        "bond_futures": "国债期货", "stock": "股票",
        "etf": "ETF", "convertible_bond": "可转债", "reit": "REITs",
    }

    for type_name, symbols_group in type_groups.items():
        mt_enum = MarketType(type_name) if type_name in {m.value for m in MarketType} else None
        if mt_enum is None or mt_enum not in _TYPE_FACTOR_MAP:
            continue

        factors = _TYPE_FACTOR_MAP[mt_enum]
        label = type_labels.get(type_name, type_name)
        lines.append(f"\n── {label} ──")

        # 表头
        headers = ["品种"] + [f[1] for f in factors] + ["汇总", "分歧度"]
        lines.append(f"| {' | '.join(headers)} |")
        lines.append(f"|:{':' + '-' * 4 + ':' * (len(headers) - 1)}")

        for bare in symbols_group:
            sigs = dashboard.signals.get(bare, [])
            sig_map = {s.source: s.direction for s in sigs}

            row = [bare]
            for source, _ in factors:
                d = sig_map.get(source)
                if d is None:
                    row.append("—")  # 数据不可用
                elif d > 0:
                    row.append(f"+{d}")
                elif d < 0:
                    row.append(str(d))
                else:
                    row.append("0")  # 方向中性

            consensus = dashboard.consensus.get(bare, 0)
            row.append(f"+{consensus}" if consensus > 0 else str(consensus))

            div = dashboard.divergence.get(bare, 1.0)
            row.append(f"{div:.2f}")

            lines.append(f"| {' | '.join(row)} |")

        added_separator = True

    if not added_separator:
        return "\n【多因子信号一致性看板】暂无因子数据。\n"

    lines.append("")
    lines.append("分歧度 < 0.2 → 因子共振，高确信度")
    lines.append("分歧度 0.2~0.5 → 因子分歧，需辩论揭示关键矛盾")
    lines.append("分歧度 > 0.5 → 极度分歧，降低置信度")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: 更新 `build_matrix()` 的 source_labels**

`build_matrix()` 无需改动 — 它从 `dashboard.signals` 自动聚合所有 source。

- [ ] **Step 5: 运行测试验证**

Run: `python -m pytest tests/data_adapter/factors/test_dashboard.py -v`
Expected: 7 passed（向后兼容，现有测试使用无 market_types 参数时的默认行为）

### Task 3: 测试新信号函数

**文件**: `tests/data_adapter/factors/test_dashboard.py`

- [ ] **Step 1: 添加资金流向信号测试**

在文件末尾 `TestDashboard` 类中添加：

```python
    # ── 资金流向信号 ──

    def test_money_flow_bullish(self):
        """主力净流入 > 0 → +1"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        mf = {"symbol": "600519", "main_net_inflow": 5000, "retail_net_inflow": 1000,
              "mid_net_inflow": 500, "data_grade": "PRIMARY"}
        sig = _signal_from_money_flow(mf)
        assert sig is not None
        assert sig.direction == 1
        assert sig.source == "money_flow"

    def test_money_flow_bearish(self):
        """主力净流入 < 0 → -1"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        mf = {"symbol": "600519", "main_net_inflow": -3000, "retail_net_inflow": 500,
              "mid_net_inflow": 200, "data_grade": "PRIMARY"}
        sig = _signal_from_money_flow(mf)
        assert sig is not None
        assert sig.direction == -1

    def test_money_flow_no_data(self):
        """无数据 → None"""
        from data_adapter.factors.dashboard import _signal_from_money_flow
        assert _signal_from_money_flow(None) is None
        assert _signal_from_money_flow({"data_grade": "UNAVAILABLE"}) is None

    # ── 北向资金信号 ──

    def test_north_flow_bullish(self):
        """北向净买入 > 0 → +1"""
        from data_adapter.factors.dashboard import _signal_from_north_flow
        nf = {"symbol": "600519", "north_net_buy": 2000, "north_holding_pct": 5.0,
              "data_grade": "PRIMARY"}
        sig = _signal_from_north_flow(nf)
        assert sig is not None
        assert sig.direction == 1
        assert sig.source == "north_flow"

    def test_north_flow_bearish(self):
        """北向净买入 < 0 → -1"""
        from data_adapter.factors.dashboard import _signal_from_north_flow
        nf = {"symbol": "600519", "north_net_buy": -1000, "north_holding_pct": 3.0,
              "data_grade": "PRIMARY"}
        sig = _signal_from_north_flow(nf)
        assert sig is not None
        assert sig.direction == -1

    # ── ETF 溢价信号 ──

    def test_etf_premium_overheat(self):
        """溢价 > 1% → -1（看空）"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": 2.5, "data_grade": "PRIMARY"}
        sig = _signal_from_etf_premium(ep)
        assert sig is not None
        assert sig.direction == -1
        assert sig.source == "etf_premium"

    def test_etf_premium_discount(self):
        """折价 > 1% → +1（看多）"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": -1.8, "data_grade": "PRIMARY"}
        sig = _signal_from_etf_premium(ep)
        assert sig is not None
        assert sig.direction == 1

    def test_etf_premium_normal(self):
        """溢价在 ±1% 内 → 无信号"""
        from data_adapter.factors.dashboard import _signal_from_etf_premium
        ep = {"symbol": "510050", "premium_pct": 0.3, "data_grade": "PRIMARY"}
        assert _signal_from_etf_premium(ep) is None
```

- [ ] **Step 2: 运行测试验证**

Run: `python -m pytest tests/data_adapter/factors/test_dashboard.py -v`
Expected: 14 passed (7 old + 7 new)

### Task 4: P2.5 采集 ETF 溢价数据

**文件**: `fdt_langgraph/_nodes_prepare.py`

- [ ] **Step 1: 在腾讯特有因子采集块中添加 ETF 溢价**

在 `factor_north_flow` 采集逻辑之后追加：

```python
            nf = await get_north_flow(sym)
            if nf.get("data_grade") == "PRIMARY":
                factor_north_flow[sym] = nf
        # ── ETF 溢价采集（仅 ETF 品种） ──
        factor_etf_premium: dict = {}
        for sym in symbols:
            mt = classify(sym)
            if mt != MarketType.ETF:
                continue
            ep = await get_etf_premium(sym)
            if ep.get("data_grade") == "PRIMARY":
                factor_etf_premium[sym] = ep
```

- [ ] **Step 2: 在 return dict 中添加 `factor_etf_premium`**

```python
        "factor_money_flow": factor_money_flow,
        "factor_north_flow": factor_north_flow,
        "factor_etf_premium": factor_etf_premium,   # ← 新增
```

### Task 5: 更新 `node_prepare_data()` 调用的 `build_dashboard()`

**文件**: `fdt_langgraph/_nodes_prepare.py`

- [ ] **Step 1: 传递新参数给 build_dashboard**

将：

```python
        factor_dashboard = fc.build_dashboard(
            symbols, factor_term_structure, factor_volatility,
            factor_holding_sentiment, factor_cross_spread,
        )
```

改为：

```python
        factor_dashboard = fc.build_dashboard(
            symbols, factor_term_structure, factor_volatility,
            factor_holding_sentiment, factor_cross_spread,
            money_flow=factor_money_flow,
            north_flow=factor_north_flow,
            etf_premium=factor_etf_premium,
        )
```

### Task 6: 更新 `FactorCollector.build_dashboard()`

**文件**: `data_adapter/factors/__init__.py`

- [ ] **Step 1: 转发新参数**

将 `build_dashboard()` 方法签名改为：

```python
    def build_dashboard(
        self,
        symbols: list[str],
        term_structure: dict[str, TermStructureResult],
        volatility: dict[str, VolatilityResult],
        holding_sentiment: dict[str, HoldingSentimentResult],
        cross_spreads: list[CrossSpreadResult],
        money_flow: dict[str, dict] | None = None,
        north_flow: dict[str, dict] | None = None,
        etf_premium: dict[str, dict] | None = None,
    ) -> FactorDashboardResult:
        """构建多因子信号一致性看板。"""
        from .dashboard import build_dashboard
        return build_dashboard(symbols, term_structure, volatility,
                               holding_sentiment, cross_spreads,
                               money_flow=money_flow,
                               north_flow=north_flow,
                               etf_premium=etf_premium)
```

- [ ] **Step 2: 在 import 中新增 dict 类型的 Option**

不需要新增类型导入（dict 是内置类型）。

### Task 7: 更新 `node_verdict()` 传递 `market_types`

**文件**: `fdt_langgraph/_nodes_verdict.py`

- [ ] **Step 1: 传递 market_types 到 format 函数**

将 L128-134：

```python
    # ── P2.5 多因子信号一致性看板注入 ──
    factor_dashboard_text = ""
    try:
        fdb = state.get("factor_dashboard")
        if fdb is not None:
            from data_adapter.factors.dashboard import format_dashboard_for_prompt
            factor_dashboard_text = format_dashboard_for_prompt(fdb)
    except Exception:
        pass
```

改为：

```python
    # ── P2.5 多因子信号一致性看板注入（类型感知渲染） ──
    factor_dashboard_text = ""
    try:
        fdb = state.get("factor_dashboard")
        if fdb is not None:
            from data_adapter.factors.dashboard import format_dashboard_for_prompt
            from data_adapter.instrument_classifier import classify, MarketType
            symbols = state.get("selected_symbols", [])
            market_types = {}
            for sym in symbols:
                try:
                    market_types[sym] = classify(sym)
                except Exception:
                    pass
            factor_dashboard_text = format_dashboard_for_prompt(fdb, market_types=market_types)
    except Exception:
        pass
```

### Task 8: 全链路验证

- [ ] **Step 1: 运行全量 data_adapter 测试**

Run: `python -m pytest tests/data_adapter/ -v --tb=short`
Expected: 125+ passed

- [ ] **Step 2: 验证 format 输出含新因子**

Run: `python -c "
from data_adapter.factors.dashboard import build_dashboard, format_dashboard_for_prompt
from data_adapter.factors.types import *
result = build_dashboard(
    ['600519'], {}, {}, {}, [],
    money_flow={'600519': {'symbol': '600519', 'main_net_inflow': 5000, 'retail_net_inflow': 1000, 'mid_net_inflow': 500, 'data_grade': 'PRIMARY'}},
    north_flow={'600519': {'symbol': '600519', 'north_net_buy': 2000, 'north_holding_pct': 5.0, 'data_grade': 'PRIMARY'}},
)
text = format_dashboard_for_prompt(result)
assert '资金流向' in text
assert '北向资金' in text
print(text)
print('ALL OK')
"`
Expected: 表格中含有"资金流向"和"北向资金"列

---

## 5. 文件变更清单

| 文件 | 操作 | 变更内容 |
|:-----|:-----|:---------|
| `data_adapter/factors/dashboard.py` | 修改 | 新增 3 个信号函数 + `_TYPE_FACTOR_MAP` + `build_dashboard` 签名扩展 + `format_dashboard_for_prompt` 类型感知重构 |
| `tests/data_adapter/factors/test_dashboard.py` | 修改 | 新增 7 个测试用例 |
| `data_adapter/factors/__init__.py` | 修改 | `FactorCollector.build_dashboard()` 传递新参数 |
| `fdt_langgraph/_nodes_prepare.py` | 修改 | ETF 溢价采集 + `build_dashboard` 调用传参 |
| `fdt_langgraph/_nodes_verdict.py` | 修改 | 构建 `market_types` 映射并传入 `format_dashboard_for_prompt` |

## 6. 降级策略

| 场景 | 行为 | 示例 |
|:-----|:-----|:-----|
| 数据源为 AKShare（无 money_flow/north_flow） | dict 为空，dashboard 跳过新因子 | 表格不显示资金流向/北向资金列 |
| 品种为期货（非 ETF/Stock） | `classify()` 排除，不采集 | dashboard 不包含该品种的 ETF 溢价信号 |
| ETF 溢价数据不可用 | `get_etf_premium()` 返回 UNAVAILABLE | dashboard 跳过该信号 |
| 单个品种无资金流向数据 | `_signal_from_money_flow(None)` → None | 该品种表格对应列显示 0 |

## 7. 验收标准（DOD）

- [x] 3 个信号函数有 UT 覆盖 ≥ 7 条
- [x] `build_dashboard()` 兼容新旧签名（默认 None，向后兼容）
- [x] P2.5 采集 ETF 溢价数据并注入 state
- [x] `format_dashboard_for_prompt()` 按 7 种资产类型分组渲染子表格，类型间因子列不同
- [x] "—" 标记数据不可用 vs "0" 标记方向中性，语义明确区分
- [x] `node_verdict()` 传入 `market_types` 映射
- [x] 全量现有测试通过（零回归）— 133/133 passed
- [x] 跨资产类型混合品种（如 RB + IF + 600519 + 510050）渲染出 4 个子表格

---

## 8. 扩展性设计 — 新增资产类型指南

### 8.1 扩展点总览

本设计的核心决策是 **统一数据模型 + 类型感知渲染**，新增资产类型时只需加数据，不需改渲染逻辑。

```
新增资产类型需要改的（3 处）：
  ┌─ instrument_classifier.py ───────────────────────────────┐
  │ ① MarketType.CRYPTO = "crypto"     # 枚举               │
  │ ② classify() 中加识别规则           # 如 "BTC" → CRYPTO  │
  └──────────────────────────────────────────────────────────┘

  ┌─ dashboard.py ───────────────────────────────────────────┐
  │ ③ _TYPE_FACTOR_MAP 中加一行：                            │
  │   MarketType.CRYPTO: [("volatility", "波动率"), ...]      │
  └──────────────────────────────────────────────────────────┘

  可能还需要改的（选做）：
  ┌─ 数据源层 ──────────────────────────────────────────────┐
  │ ④ 实现该类型的数据源方法（如 get_crypto_xxx()）           │
  └──────────────────────────────────────────────────────────┘

  不需要改的（渲染层自动适配）：
  ✓ format_dashboard_for_prompt()    — 循环遍历 type_groups
  ✓ FactorDashboardResult            — 通用信号存储
  ✓ P2.5 注入管线                    — state["factor_*"] 通用
```

### 8.2 新增示例：虚拟货币（Crypto）

以下展示新增虚拟货币类型的完整操作，验证扩展性。

**Step 1: 添加 MarketType 枚举**

文件：`data_adapter/instrument_classifier.py`

```python
class MarketType(str, Enum):
    # ... 现有 7 种
    CRYPTO = "crypto"  # ← 新增
```

**Step 2: 添加分类规则**

```python
# 虚拟货币代码规则
_CRYPTO_SYMBOLS = {"BTC", "ETH", "BNB", "SOL", "XRP"}

def classify(symbol: str) -> MarketType:
    # ... 现有规则之后，return COMMODITY_FUTURES 之前
    if sym_upper in _CRYPTO_SYMBOLS:
        return MarketType.CRYPTO
    # 7. 默认：商品期货
    return MarketType.COMMODITY_FUTURES
```

`get_market_label()` 自动返回 MarketType 的 value，无需修改。

**Step 3: 添加因子映射**

文件：`data_adapter/factors/dashboard.py`

```python
_TYPE_FACTOR_MAP: dict[MarketType, list[tuple[str, str]]] = {
    # ... 现有 7 种
    MarketType.CRYPTO: [
        ("volatility", "波动率"),
        ("money_flow", "资金流向"),
        ("momentum", "动量"),
    ],
}
```

**Step 4（可选）: 数据源实现**

在 TencentStockSource 或新建源中添加 `get_crypto_quote()` 等方法。

### 8.3 渲染器的自动适配机制

```python
# format_dashboard_for_prompt 的核心循环 — 纯数据驱动
for type_name, symbols_group in type_groups.items():
    mt_enum = MarketType(type_name) if type_name in MARKET_TYPE_VALUES else None
    if mt_enum is None or mt_enum not in _TYPE_FACTOR_MAP:
        continue  # ← 新类型无映射时静默跳过，不报错、不阻断
    factors = _TYPE_FACTOR_MAP[mt_enum]
    label = get_market_label(mt_enum)  # ← 从 classifier 自动获取标签

    # 渲染子表格（表头 | 数据行） — 与具体类型无关
    headers = ["品种"] + [f[1] for f in factors] + ["汇总", "分歧度"]
    lines.append(f"\n── {label} ──")
    lines.append(f"| {' | '.join(headers)} |")
    for bare in symbols_group:
        sigs = dashboard.signals.get(bare, [])
        sig_map = {s.source: s.direction for s in sigs}
        row = [bare]
        for source, _ in factors:
            d = sig_map.get(source)
            row.append("—" if d is None else f"+{d}" if d > 0 else str(d))
        # ... consensus / divergence
```

渲染器不感知具体类型，只依赖 `_TYPE_FACTOR_MAP` 中定义的数据。

### 8.4 改进建议（v2）

| 建议 | 效果 | 优先级 |
|:-----|:-----|:-------|
| 用 `get_market_label()` 替代硬编码 `type_labels` | 新增类型自动获得标签 | P0（当前版本做） |
| `_TYPE_FACTOR_MAP` 移到 `docs/harness/_data/factor_map.yaml` | 改配置不改代码 | P2 |
| 新增因子源时只需加 `_signal_from_xxx()` + 映射表一行 | 信号函数即插即用 | 已支持 |

### 8.5 当前改进：移除硬编码 `type_labels`

在 `format_dashboard_for_prompt()` 中，将：

```python
    type_labels = {
        "commodity_futures": "商品期货", "index_futures": "股指期货",
        "bond_futures": "国债期货", "stock": "股票",
        "etf": "ETF", "convertible_bond": "可转债", "reit": "REITs",
    }
    # ...
    label = type_labels.get(type_name, type_name)
```

改为：

```python
    from data_adapter.instrument_classifier import get_market_label
    # ...
    label = get_market_label(mt_enum)
```

`get_market_label()` 已在 `instrument_classifier.py` 中为所有 MarketType 定义了中文标签，
新增类型时只需在 classify 函数末尾的 labels dict 中加一行，两处同步。文档已更新。
