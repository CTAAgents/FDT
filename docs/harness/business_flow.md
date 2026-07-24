# 期货辩论专家团 — 业务逻辑流程（v2.1 · 单辩论通道 + 六阶段流水线）

> 本文档为专家团完整业务流程的**规范参考**，所有 Agent MD 和 pipeline 执行逻辑以此为准。
> **v2.0 变更 (2026-07-23)**：移除双通道架构（通道A直接推荐已废除），所有通道突破品种必须辩论。P2 闫判官不做方向预判，只负责品种筛选与协调调度。
> **v2.1 变更 (2026-07-24)**：P6 报告输出执行者更正为品藻（非明鉴秋）。FDC 退役 → data_adapter。P2 品种筛选移至 P1。

---

## 总览

六阶段串行流水线，每个品种逐个走完整辩论流程：

```
P1 数技源扫描（通道突破信号）
    ↓
P2 闫判官协调调度 + 四源并行（链证源/观澜/探源/读心）
    ↓
P3 六阶段辩论（多空攻防）
    ↓
P4 闫判官终裁（含完整交易参数）
    ↓
P5 风控明审核
    ↓
P6 报告输出（品藻）
```

**核心原则**：
- **无直接推荐通道**：所有通道突破品种必须经过辩论，无例外
- **P2 不做方向预判**：闫判官只做品种筛选和调度协调，多空方向由辩论决定
- **四源平级并行**：链证源/观澜/探源/读心为平级分析师，无调度与被调度关系

---

## 阶段一：P1 数技源通道突破扫描

### 执行者

数技源 Agent（`futures-datatech`），由明鉴秋 spawn 执行 `scan_all.py`。

### 步骤

```
① 数据采集（data_adapter.get_kline，AKShare 唯一数据源）

② 通道突破策略打分（仅 channel_breakout，其余10策略已退役）
   ├── 唐奇安通道 DC20/DC55 突破信号
   ├── trend_confirmation 趋势确认
   ├── bb_squeeze_prebreakout 布林带挤压预警
   └── 产出 stats 纯统计特征（MA/ATR/RSI/ADX/量能比/通道位置/20日区间位置）

③ P0-4 伪信号过滤（可配置开关，默认开启）

④ 相关系数去重（v10.0.0）
   ├── 60日收盘价 Pearson r > 0.80 且信号强度差异 ≤ 20%
   ├── → 只保留信号最强的品种 → primary_symbols
   └── 去重映射 → associated_groups（被去重品种列表）

⑤ 传递 primary_symbols 给 P2 闫判官（闫判官不再做品种筛选）
```

### 产出物

| 文件 | 说明 | 用途 |
|:-----|:-----|:-----|
| `full_scan_summary_{date}.json` | 通道突破信号 + stats 统计特征 | 闫判官 + 四源 |
| `all_ranked[].stats` | 纯统计特征（MA/ATR/RSI/ADX/量能比） | 闫判官品种筛选依据 |
| `primary_symbols` | 相关系数去重后的主辩论品种列表 | 闫判官直接接收（不再筛选） |
| `associated_groups` | 被去重品种的映射关系 | 辩论报告关联展示 |

### 约束

- **不下多空结论**：数技源只输出统计事实，不做方向预判
- **仅通道突破**：多策略管线已全部退役（v10.0.0），只留 channel_breakout
- **相关系数去重**：由 scan_all.py 执行，P2 闫判官不做二次筛选

---

## 阶段二：P2 闫判官协调调度 + 四源并行

### 2.1 闫判官调度决策

#### 执行者

闫判官 Agent（`futures-judge`），由明鉴秋 spawn。

#### 调度权归属

**闫判官拥有辩论调度权**：决定辩论哪些品种，并 dispatch 四分析师（链证源/观澜/探源/读心）。四源只做各自分析、**无调度权**；明鉴秋负责按闫判官指令执行 spawn 与资源管控。

**闫判官在 P2 不做品种筛选和方向预判**——品种列表由 P1 相关系数去重后直接传递，闫判官只决定 dispatch_sources。多空方向由后续辩论阶段自然决定。

#### 输入

| 来源 | 数据 |
|:-----|:-----|
| 数技源 | `full_scan_summary_{date}.json`（含 stats 统计特征） |
| 链证源 | 产业链快照 + `redundant_pairs`（产业链分析已在 scan 后并行） |
| 外部 | `get_upcoming_events()` / `get_liquidity_risk()` / `query_history()` |

#### 流程

```
① 接收 P1 的 primary_symbols（相关系数去重后品种列表）
② 加载事件日历、流动性、历史反馈
③ 决定调度哪些数据源：["chain", "technical", "fundamental", "sentiment"] 的子集
④ 传递筛选结果给四源，进入并行分析
```

#### 品种筛选规则

> ⚠️ **v10.0.0 变更**：品种筛选已移至 P1 scan_all.py 执行（相关系数去重），P2 闫判官不再做品种筛选。
> 
> P1 执行的筛选规则：
> 1. **所有通道突破品种必须辩论**（channel_breakout/trend_confirmation/bb_squeeze_prebreakout）
> 2. **相关系数去重**：60日收盘价 Pearson r > 0.80 且信号强度差异 ≤ 20% → 只保留信号最强的品种
> 3. **伪信号过滤**（P0-4 验证器管道，可配置开关）
> 
> 闫判官仅接收筛选后的 `primary_symbols`，职责限于数据源调度。

---

### 2.2 四源并行分析

四源由闫判官调度后**并行执行**，互不依赖、互不等待。

| 分析师 | Agent | 职责 | 超时 | 降级 |
|:-------|:------|:-----|:----|:-----|
| **链证源** | `futures-chain-analyst` | 产业链分析（不下多空结论） | 300s | 跳过 |
| **观澜** | `futures-technical-researcher` | 技术面分析 | 420s | 跳过 |
| **探源** | `futures-fundamental-researcher` | 基本面分析 | 420s | 跳过 |
| **读心** | `futures-news-sentiment-analyst` | 新闻情绪分析 | 420s | 跳过 |

#### 链证源 — 产业链分析

- 基于数技源的通道突破品种，做对应产业链分析
- 产业链景气度判断：繁荣/正常/萧条/分化
- 产出 `redundant_pairs`：同链品种 60 日滚动 Pearson 相关系数

#### 观澜 — 技术面分析

- 通过 `data_interface` 按需加载技术数据
- 自行计算补充技术指标
- 识别技术图形（支撑阻力/形态突破/量价关系等）

#### 探源 — 基本面分析

- 通过 `data_interface` 按需拉取因子数据
- 供需/库存/利润/期限结构分析
- 政策/天气/地缘等定性信息

#### 读心 — 新闻情绪分析

- 通过金十 MCP（快讯/资讯）获取新闻情绪事件流
- 网页爬虫补充定性信息
- 输出情绪评分 + 事件摘要

---

### 2.3 merge_research（合并节点）

四源完成后，由 `node_merge_research` 将四份独立分析合并为统一的 `research_data`，供辩论阶段使用。

合并产出：
```python
{
    "chain_analysis": {...},       # 链证源
    "technical_data": {...},        # 观澜（含 per_symbol）
    "fundamental_data": {...},      # 探源（含 per_symbol）
    "sentiment_data": {...},        # 读心
    "dispatch_sources": [...],      # 已调度的源列表
}
```

---

## 阶段三：P3 六阶段辩论

### 执行者

| 角色 | Agent | 动作 |
|:-----|:------|:-----|
| 多头分析员 | `futures-bullish-analyst` | 列举做多论据，反驳空头质疑 |
| 空头分析员 | `futures-bearish-analyst` | 列举做空论据，反驳多头质疑 |

**分析师中立供弹**：四源提供的数据作为辩论素材，辩手只能使用分析师提供的资料，不能自行搜集数据。

### 多空头多轮攻防机制

- **多头分析员**：代表多头利益，从研究员资料中独立寻找做多理由，反驳空头质疑
- **空头分析员**：代表空头利益，从研究员资料中独立寻找做空理由，反驳多头质疑
- **无预设正方方向**：P2 不做方向预判，多空双方平等辩论

### 六阶段辩论流程

```
merge_research（研究员合并供弹）
    ↓
① bullish_v1 — 多头立论（多头分析员独立做多论据）
    ↓
② bearish_v1 — 空头立论（空头分析员独立做空论据）
    ↓
③ bearish_rebuttal — 空头反驳（针对多头立论逐条反驳）
    ↓
④ bullish_rebuttal — 多头反驳（针对空头立论+空头反驳再反驳）
    ↓
⑤ bear_final — 空头最终陈述（整合空头全部论据，含风险提示）
    ↓
⑥ bull_final — 多头最终陈述（整合多头全部论据，含风险提示）
    ↓
verdict — 闫判官终裁（基于全部六轮辩论）
```

### 判决评分模型

| 维度 | 权重 |
|:-----|:----:|
| 逻辑严谨度 | 25% |
| 证据充分性 | 20% |
| 量化一致性 | 15% |
| 反驳有效性 | 20% |
| 风险意识 | 10% |
| 表达与结构 | 10% |

---

## 阶段四：P4 闫判官终裁（含交易参数）

### 执行者

闫判官 Agent（`futures-judge`），基于六轮辩论论据做出最终裁决。

### 裁决输出

| 字段 | 说明 | 示例 |
|:-----|:-----|:-----|
| `direction` | 裁决方向 | `bear` / `bull` / `neutral` |
| `confidence` | 置信度 | `HIGH` / `MEDIUM` / `LOW` |
| `entry_price` | 入场价（=当前市价） | `3077` |
| `target_price` | 目标价（RR≥2.0） | `2892` |
| `stop_loss_price` | 止损价 | `3154` |
| `position_pct` | 建议仓位 % | `3.5` |
| `risk_reward_ratio` | 盈亏比 | `2.4` |
| `reason` | 裁决理由 | 引用辩论论据 |

### 🔴 交易建议以当前市价为基准

**任何交易建议必须锚定当前市价**，禁止给出挂单价操作建议。当前价无法操作时必须选"观望"。

### 参数设定参考

| ATR 特征 | 建议止损距 | 说明 |
|:---------|:-----------|:-----|
| ATR ≥ 历史90分位 | 2.0×ATR | 高波动放宽 |
| ATR 正常范围 | 1.5×ATR | 标准 |
| ATR < 历史10分位 | 1.0×ATR | 低波动收紧 |

---

## 阶段五：P5 风控明审核

### 执行者

风控明 Agent（`futures-risk-manager`），独立审查闫判官裁决。

### 审核红线

| 红线 | 等级 |
|:-----|:----:|
| 杠杆 > 3倍 | 🔴 red |
| 保证金占用 > 60% | 🔴 red |
| 单笔止损 > 5%权益 | 🔴 red |
| 尾部当基准（<10%概率） | 🔴 red |
| 合约月份未明确 | 🟡 yellow |
| 左侧信号仓位超50% | 🟡 yellow |
| 净盈亏比 < 1.5 | 🟡 yellow |

### 入场价可行性审核（v9.11+）

| 偏差范围 | 判定 | 动作 |
|:---------|:-----|:------|
| < 0.5% | ✅ 可进场 | 通过 |
| 0.5% ~ 2% | ⚠️ 接近入场区 | 标注 yellow_flag |
| > 2% | ⏳ 等待 | 标注 red_flag，退回修订 |

**审核结果**：
- `green` → 通过
- `yellow` → 通过但标注关注项
- `red` → 退回闫判官修订（最多1轮），仍为 red 则暂停

---

## 阶段六：P6 报告输出与归档（品藻 + 明鉴秋）

### 执行者

| 角色 | Agent | 职责 |
|:-----|:------|:-----|
| **品藻** | `futures-quality-inspector` | 报告排版、数据合并、HTML 生成、完整性校验 |
| **明鉴秋** | `futures-debate-team-team-lead` | 调度协调、辩论结束后触发记忆写入与进化闭环 |

### 合并输出结构

```json
{
  "round_id": "debate_20260723",
  "trace_id": "fdt-xxx",
  "verdicts": {
    "rb": {
      "direction": "bear",
      "confidence": "HIGH",
      "entry": 3077,
      "target": 2892,
      "stop_loss": 3154,
      "position_pct": 3.5,
      "risk_reward": 2.4,
      "chain": "黑色系",
      "bull_args": ["RSI未超卖", "阶段trending无反转信号"],
      "bear_args": ["通道突破确认", "ADX>25趋势延续"]
    }
  },
  "risk_check": {
    "rb": {"approved": true, "risk_level": "medium", "risk_color": "yellow"}
  },
  "total_exposure_pct": 3.5,
  "summary": "本日辩论品种: RB 空头通过风控审核..."
}
```

### 报告完整性核验

品藻在输出前逐条核验以下四项铁律：

1. **全品种覆盖**：所有通道突破品种在报告中可见，无一沉默
2. **交易参数完备**：方向/入场/止损/目标/仓位/盈亏比 6 字段缺一不可
3. **数据源穿透**：数据来源必须到采集器名称（如"通达信TQ-Local"），禁止使用程序名
4. **时间精确到分钟**：所有时间字段必须是 `YYYY-MM-DD HH:MM` 格式

### 归档

1. `debate_report_{trace_id}.html` — 最终辩论报告
2. 各 Agent 按规范写入 `memory/`（辩论索引 + 分数 + 论证模式）

---

## 执行顺序（单品种辩论模式）

```
P1: scan_all.py 扫描 → 产出 all_ranked（含 stats 统计特征）
    ↓
P2: node_judge_direction（闫判官接收 primary_symbols + 调度四源）
    ↓
    node_prepare_data（data_adapter 数据预采集）
    ↓
    链证源 | 观澜 | 探源 | 读心（四源并行）
    ↓
    node_merge_research（合并分析）
    ↓
P3: 六阶段辩论（bullish_v1 → bearish_v1 → bearish_rebuttal → bullish_rebuttal → bear_final → bull_final）
    ↓
P4: node_verdict（闫判官终裁 + 交易参数）
    ↓
P5: node_risk_check（风控明审核）
    ↓
P6: node_generate_report（品藻报告输出）
    ↓
    node_signal_output（品藻 CTP 信号输出）
    ↓
    （明鉴秋：记忆写入 + 进化闭环触发）
```

> 对 P1 给出的**每个品种逐个走辩论流程**。多品种模式下，每个品种独立经历 P2→P3→P4→P5→P6，合并输出为一份多品种辩论报告。

---

## LangGraph 节点映射

| 阶段 | LangGraph 节点 | 执行者 | 职责 |
|:-----|:---------------|:-------|:-----|
| P1 | `node_scan` | 数技源 | 通道突破信号扫描 |
| P2 | `node_judge_direction` | 闫判官 | 直接接收 P1 primary_symbols + 数据源调度决策（**不筛选品种，不做方向预判**） |
| P2 | `node_prepare_data` | 系统 | data_adapter 数据预采集 |
| P2 | `node_chain` | 链证源 | 产业链分析 |
| P2 | `node_technical` | 观澜 | 技术面分析 |
| P2 | `node_fundamental` | 探源 | 基本面分析 |
| P2 | `node_sentiment` | 读心 | 新闻情绪分析 |
| P2 | `node_merge_research` | 系统 | 四源合并 |
| P3 | `bullish_v1`→`bearish_v1`→...→`bull_final` | 多空分析员 | 六阶段攻防辩论 |
| P4 | `node_verdict` | 闫判官 | 终裁 + 交易参数 |
| P5 | `node_risk_check` | 风控明 | 风险审核 |
| P6 | `node_generate_report` | 品藻 | 报告排版/HTML 生成/完整性校验 |
| P6a | `node_signal_output` | 品藻 | CTP 信号输出（风控 red 阻断） |

---

## 版本变更说明

| 版本 | 日期 | 变更内容 |
|:-----|:-----|:---------|
| v1.2 | 2026-07-xx | 双通道架构（通道A直接推荐+通道B辩论） |
| **v2.0** | **2026-07-23** | **移除双通道架构**：废除通道A直接推荐，所有品种必须辩论。P2 闫判官不再做方向预判，仅负责品种筛选与调度协调。新增"读心"第四源。|
| **v2.1** | **2026-07-24** | **P6 归属更正**：报告输出执行者更正为品藻（非明鉴秋）。FDC 退役 → data_adapter 数据适配层。P2 品种筛选职责移至 P1 scan_all.py。|
