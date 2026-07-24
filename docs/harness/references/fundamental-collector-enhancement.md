# fundamental-data-collector 增强方向

> **关联**: Phase 3 基本面清洗（`data_adapter/cleaning/fundamental.py`）已完成结构化快照清洗。
> 本文件标注 **探源 Agent 自有工具集**（fundamental-data-collector Skill）的下一步增强方向，
> 实现从"静态快照"到"时序对齐+口径追踪+修订可溯"的升级。

## 1. 现状评估

### 1.1 数据源框架

| 文件 | 功能 | 数据模式 | 时间序列 | 动态性 | 清洗 |
|:-----|:-----|:---------|:--------:|:------:|:----:|
| `supply.py` | 供给端（产量/开工率/进口） | 硬编码字典 | ❌ 单期 | ❌ 2026-07-04快照 | ❌ |
| `demand.py` | 需求端（下游开工/订单） | 硬编码字典 | ❌ 单期 | ❌ 2026-07-04快照 | ❌ |
| `inventory.py` | 库存（社库/厂库/分位数） | 硬编码字典 | ❌ 单期 | ❌ 2026-07-04快照 | ❌ |
| `margin.py` | 利润/加工费 | 硬编码字典 | ❌ 单期 | ❌ 2026-07-04快照 | ❌ |
| `term_basis.py` | 基差/期限结构 | JSON + 字典 | ❌ 单期 | ⚠️ JSON可更新 | ❌ |
| `macro_link.py` | 宏观/外盘联动 | WebSearch | ❌ 单期 | ⚠️ 运行时搜索 | ❌ |
| `chain_balance.py` | 供需平衡表 | 调用 supply+demand | ❌ 单期 | ❌ 依赖上游 | ❌ |
| `data_interface.py` | 徽商智汇 DuckDB | 数据库查询 | ✅ 多期 | ✅ 实时查询 | ❌ |

### 1.2 核心问题

1. **硬编码静态数据** — 6/8 的模块数据来自 2026-07-04 的 WebSearch 快照，至今未刷新
2. **无时间序列** — 所有函数返回单期快照，无法做趋势分析（库存变化率、利润边际变动）
3. **缺失值未标注** — 数据为空时返回 `{"info": "无XX数据"}` 字符串，无统一缺失标记
4. **口径变更不可见** — 交易所规则调整（如 SA 保证金率 9%→12%→15%）在数据中无标记
5. **修订版本不追踪** — 同一数据多次查询无法识别是否已更新
6. **无清洗层对接** — 已完成的 `fundamental.py` 清洗层未被任何 query_* 函数调用

## 2. 增强方向

### 2.1 P1 — 数据结构化升级（高优先级）

将硬编码字典升级为 **带元数据的结构化记录**，对接 `fundamental.py` 清洗层：

```python
# 当前（硬编码字符串）
{"RB": {"利润": "80元/吨", "趋势": "低位"}}

# 目标（结构化 + 可清洗）
{
    "RB": {
        "value": 80,            # 数值（可校验）
        "unit": "元/吨",         # 单位
        "direction": "下降",     # 趋势方向
        "data_date": "2026-07-04",  # 数据日期（可新鲜度评分）
        "source": "Mysteel",     # 来源
        "revision": "v1",        # 版本（可追踪）
        "_raw": "长流程毛利80元/吨（来源：Mysteel）"  # 原始文本
    }
}
```

**涉及文件**: `supply.py` / `demand.py` / `inventory.py` / `margin.py`

### 2.2 P1 — DuckDB 优先策略（高优先级）

`data_interface.py` 已有 DuckDB 多期数据能力，将其提升为**首选数据源**：

- 硬编码字典降级为 DuckDB 查不到的 fallback
- DuckDB 查询结果自动过 `clean_fundamental_snapshot()` 管线
- 返回带时间序列的 DataFrame 而非单值

```python
def query_inventory(symbol: str) -> dict:
    # 1. 先查 DuckDB（多期时序）
    result = data_interface.query_inventory_timeseries(symbol, days=90)
    if result is not None:
        return apply_cleaning(result, "inventory", symbol)
    # 2. DuckDB 无数据 → 硬编码 fallback
    return _HARDCODED_FALLBACK.get(symbol, {"info": "无数据"})
```

### 2.3 P2 — 对接清洗管线

每个 `query_*` 函数返回前调用 `clean_fundamental_snapshot()`：

```python
from data_adapter.cleaning.fundamental import clean_fundamental_snapshot

data = {"data": {...}, "data_grade": "PRIMARY"}
cleaned, report = clean_fundamental_snapshot(data, data_type="inventory", symbol=symbol)
```

这带来：
- **值校验**：负库存、异常利润率的自动捕获
- **新鲜度评分**：`freshness_level` / `freshness_days` 自动附加
- **口径变更警告**：规则调整事件自动标注
- **修订追踪**：每次查询版本自动递增

### 2.4 P2 — 时间对齐层

基本面数据是周/月频率，K 线是日频率。需要时间对齐层：

```python
def align_to_timeline(
    fundamental_data: dict,    # 多期基本面数据
    kline_dates: list[str],    # K 线日期序列
    method: str = "ffill",     # 前向填充 / 线性插值
) -> dict:
    """将低频率基本面数据对齐到日 K 线时间轴。"""
```

对齐方法：
| 数据类型 | 推荐方法 | 说明 |
|:---------|:---------|:-----|
| 库存（周频） | 前向填充 | 新数据发布前沿用上次值 |
| 开工率（周频） | 前向填充 | 同上 |
| 利润（日频） | 当日值 | 已有日频数据可直接对齐 |
| 仓单（日频） | 当日值 | 已有日频数据 |
| 宏观数据（月频） | 前向填充 | 月底发布，沿用至下月底 |

### 2.5 P2 — 口径变更事件库扩充

当前 `fundamental.py` 的 `_KNOWN_CALIBER_CHANGES` 只含 5 条已知事件。
需要建立一个**可维护的事件库**，支持运行时追加：

```yaml
# docs/harness/_data/caliber_changes.yaml
- date: "2023-08-04"
  symbol: "SA"
  field: "margin_rate"
  description: "纯碱保证金率从 9% 调至 12%"
  exchange: "ZCE"
- date: "2024-06-01"
  symbol: "SI"
  field: "tick_size"
  description: "工业硅最小变动价位调整"
  exchange: "GFEX"
```

`detect_caliber_change()` 从 YAML 文件动态加载，而非硬编码。

### 2.6 P3 — 修订版追踪持久化

当前 `track_revision()` 每次返回 `v1`，无法跨 session 追踪。
需要持久化修订版本到 SQLite：

```python
# memory/fdt_cache/fundamental_revisions.db
# 表: revision_tracker
# symbol, data_type, version, tracked_at, checksum
```

每次查询时比对 checksum，变化时 version++，实现跨 session 修订可溯。

### 2.7 P3 — Agent Prompt 注入钩子

探源 Agent 的 context 中应包含当前品种的**口径变更警告**和**数据新鲜度等级**，
让 LLM 在推理时感知数据质量风险：

```
【数据质量提示】
- 基差新鲜度: STALE_WARNING（数据距今 7 天）
- 仓单口径变更: SA 保证金率在 2023-09-08 从 12%→15%
- 库存字段: 缺失 50%，数据等级已降级至 DEGRADED
```

这些提示由 `clean_fundamental_data()` 产出的 `_cleaning` 信息自动生成。

## 3. 实施路线

| 阶段 | 优先级 | 内容 | 预计工作量 |
|:----:|:------:|:-----|:----------:|
| **3.1** | P1 | 数据结构化升级（硬编码→结构化） | 4 文件 × 0.5h = 2h |
| **3.2** | P1 | DuckDB 优先 + fallback 降级链 | 1 文件（data_interface.py 增强）= 1.5h |
| **3.3** | P2 | 对接清洗管线（每个 query 函数调用 cleaning） | 8 文件 × 0.25h = 2h |
| **3.4** | P2 | 时间对齐层（`align_to_timeline`） | 新建 1 文件 = 1h |
| **3.5** | P2 | 口径变更 YAML 事件库 | 新建 1 YAML + 修改 fundamental.py = 0.5h |
| **3.6** | P3 | 修订版追踪持久化（SQLite） | 新建 1 模块 = 1.5h |
| **3.7** | P3 | Agent Prompt 注入钩子 | 修改 `_build_fdc_fundamental_context()` = 0.5h |

**总计**: 约 9h 工作量，可分 2-3 个会话完成。

## 4. 对接点总览

```
探源 Agent
  │
  ├─ P2.5 预采集（data_adapter）── 已对接 Phase 3 清洗 ✅
  │   ├─ basis → clean_fundamental("basis") ✅
  │   ├─ warrant → clean_fundamental("warrant") ✅
  │   ├─ position_ranking → clean_fundamental("position_ranking") ✅
  │   └─ fund_flow → clean_fundamental("fund_flow") ✅
  │
  └─ fundamental-data-collector Skill ── 待增强 ⏳
      ├─ query_supply()     → 结构化 + clean_fundamental("inventory") ⏳
      ├─ query_demand()     → 结构化 + clean_fundamental("inventory") ⏳
      ├─ query_inventory()  → 结构化 + clean_fundamental("inventory") ⏳
      ├─ query_margin()     → 结构化 + fresh_rating ⏳
      ├─ query_basis()      → DuckDB 优先 + clean_fundamental("basis") ⏳
      ├─ query_macro()      → 结构化 + WebSearch 增强 ⏳
      └─ query_chain_balance() → 自动调用各子函数 ⏳
```
