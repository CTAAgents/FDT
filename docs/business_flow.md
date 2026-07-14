# 期货辩论专家团 — 业务逻辑流程（v1.0 固化版）

> 本文档为专家团完整业务流程的**规范参考**，所有 Agent MD 和 pipeline 执行逻辑以此为准。

---

## 总览

五阶段串行 + 双通道并行：

```
P1 数据采集与双通道分离
    ↓
P1.5 产业链分析
    ↓
P2 闫判官双通道分流
    ├── 通道A: 直接推荐（跳过辩论）
    └── 通道B: 辩论（完整辩论流程）
    ↓
P3 方案合成与风控审核（双通道在此合并）
    ↓
P4 合并双通道 → 归档输出
```

---

## 阶段一：数据采集与双通道分离（Python 自动化层）

### 执行者

数技源 Agent（`futures-datatech`），由明鉴秋 spawn 执行。

### 步骤

```
① 三生产者扫描（2026-07-14 起 scan_all 仅留 channel_breakout，L1-L4/因子择时已迁独立 skill）
    ├── 数技源 scan_all.py（默认 channel_breakout）→ full_scan_summary_{date}.json（通道突破信号）
    ├── 观澜 run_l1l4_scan.py（technical-analysis）→ full_scan_l1l4_{date}.json（L1-L4 技术指标）
    └── 探源 run_factor_timing_scan.py（fundamental-data-collector）→ full_scan_factor_timing_{date}.json（5因子信号）

② debate_brief.py --select-debate chain_analysis.json
    读取 full_scan_summary.json，对每个品种计算五维辩论价值评分后分离：
    ├── trading_recommendations[]   ← 共识方向+launch阶段+非极端（免辩论）
    ├── watch_list[]                ← 共识方向+部分条件（观察级）
    └── debate_candidates[]         ← 分歧/极端/链补品种（需辩论）
```

### 产出物

| 文件 | 说明 | 用途 |
|:-----|:-----|:-----|
| `full_scan_summary_{date}.json` | 通道突破原始信号（数技源） | 闫判官 + 链证源 |
| `signal_summary_candidates.json` | 双通道分离结果 | 闫判官分流决策 |
| `full_scan_l1l4_{date}.json` | L1-L4 明细（观澜） | 研究员供弹参考 |
| `full_scan_factor_timing_{date}.json` | factor_timing 明细（探源） | 研究员供弹参考 |

### 数据源优先级

K线数据降级链（`MultiSourceAdapter.get_kline()`）：
```
盘中: TDX → TqSdk(新) → 东方财富 → AKShare
盘后: TDX → 东方财富 → AKShare
```

---

## 阶段一.五：产业链分析

### 执行者

链证源 Agent（`futures-chain-analyst`），由闫判官判断调度后 spawn。

### 约束

- **不下多空结论**，只做事实层描述
- **无调度权**：链证源只做产业链分析，不决定辩论范围、不 dispatch 其他 Agent、不替代闫判官裁决；调度权（决定辩论品种/产业链/方向、dispatch 哪些分析师）属于**闫判官**（见 P2）

### 产出

| 产出 | 说明 |
|:-----|:-----|
| 产业链上下游结构 | 供给端/需求端/库存传导 |
| 产业链景气度 | 繁荣/正常/萧条/分化 |
| `redundant_pairs` | 同产业链60日滚动Pearson相关系数（用于同链冗余硬排除） |

---

## 阶段二：闫判官双通道分流

### 执行者

闫判官 Agent（`futures-judge`）。

### 调度权归属（2026-07-14 澄清）

**闫判官拥有辩论调度权**：决定辩论哪些品种/产业链/方向，并 dispatch 三分析师（链证源做产业链分析、观澜做技术面分析、探源做基本面分析）。链证源/观澜/探源只做各自分析、**无调度权**；三者为**平级分析师**（仅分析方向不同），彼此之间**不存在调度与被调度关系**；明鉴秋负责按闫判官指令执行 spawn 与资源管控。

### 输入

| 来源 | 数据 |
|:-----|:-----|
| 数技源 | `full_scan_summary_{date}.json` + `signal_summary_candidates.json` |
| 链证源 | 产业链快照 + `redundant_pairs` |
| 外部 | `get_upcoming_events()` / `get_liquidity_risk()` / `query_history()` |

### 流程

```
① 读取 trading_recommendations / watch_list / debate_candidates
② 加载事件日历、流动性、历史反馈
③ 硬过滤：同链冗余排除（r>0.80且信号差异≤20%只保留最强）
    ↓
┌─── 通道A ──────────────────────────────────────────────┐
│  trading_recommendations 品种                            │
│  逐品种:                                                 │
│  1. 复核方向合理性                                       │
│  2. 基于 price / ATR / ADX / stage 手动设定交易参数      │
│     ├── 入场区间（如当前价±0.3×ATR）                     │
│     ├── 止损距（如1.5×ATR，不超过2.5×ATR）               │
│     └── 目标价（T1/T2/T3分步止盈，最小盈亏比1:2）        │
│  3. 发送 direct_recommend_to_strategist 消息 → 策执远    │
└──────────────────────────────────────────────────────────┘

┌─── 通道B ──────────────────────────────────────────────┐
│  debate_candidates 品种                                   │
│  逐品种:                                                 │
│  1. 选定正方方向（proposition_side）                      │
│     ├── 极端分歧品种 → 逆转方向（左侧反转机会）           │
│     └── 常规分歧品种 → 信号更强的策略方向                 │
│  2. 构建辩论素材包 → 广播给多空双方                       │
│  3. spawn 研究员供弹                                      │
└──────────────────────────────────────────────────────────┘
```

### 通道A 参数设定参考

| ATR 特征 | 建议止损距 | 说明 |
|:---------|:-----------|:-----|
| ATR ≥ 历史90分位 | 2.0×ATR | 高波动放宽 |
| ATR 正常范围 | 1.5×ATR | 标准 |
| ATR < 历史10分位 | 1.0×ATR | 低波动收紧 |

---

## 阶段三：研究员供弹 + 辩论 + 判决（通道B专用）

### 执行者

| 角色 | Agent | 动作 |
|:-----|:------|:-----|
| 观澜 | `futures-technical-researcher` | 技术分析供弹 |
| 探源 | `futures-fundamental-researcher` | 基本面分析供弹 |
| 证真(多方) | `futures-affirmative-debater` | 论证多头方向 |
| 慎思(空方) | `futures-opposition-debater` | 论证空头方向 |
| 闫判官 | `futures-judge` | 主持 + 评分 + 判决 |

### 辩论时序

| 时段 | 内容 |
|:----|:-----|
| 0-8min | 多方立论 |
| 8-16min | 空方立论 |
| 16-24min | 多方 rebuttal |
| 24-32min | 空方 rebuttal |
| 32-42min | 自由交锋 |
| 42-48min | 双方 final statement |

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

## 阶段四：方案合成与风控审核（双通道合并）

### 执行者

策执远 Agent（`futures-trading-strategist`）→ 风控明 Agent（`futures-risk-manager`）。

### 策执远输入来源

| 来源 | 路径 | 输入格式 |
|:-----|:-----|:---------|
| 通道A | `direct_recommend_to_strategist` | symbol, direction, price, atr, 闫判官参数的entry/stop/target |
| 通道B | `judgment_to_strategist` | winner, winning_proposal(entry/target/stop/lots), scores |

### 策执远处理流程（两路径统一）

```
① 合约选型（主力→次主→交割月检查）
② 校验参数合理性（通道A：闫判官参数；通道B：胜方提案）
③ 仓位计算（凯利公式/固定分数模型）
④ 建仓节奏（一次性/分批）
⑤ 对冲检查
⑥ 移仓计划
⑦ 净盈亏比计算（扣手续费+滑点+保证金利息+移仓成本）
⑧ 打包 → 传给风控明
```

### 风控明审核红线

| 红线 | 等级 |
|:-----|:----:|
| 杠杆 > 3倍 | 🔴 red |
| 保证金占用 > 60% | 🔴 red |
| 单笔止损 > 5%权益 | 🔴 red |
| 尾部当基准（<10%概率） | 🔴 red |
| 合约月份未明确 | 🟡 yellow |
| 左侧信号仓位超50% | 🟡 yellow |
| 净盈亏比 < 1.5 | 🟡 yellow |

**审核结果**：
- `green` → 通过，直接进入 P5
- `yellow` → 通过但标注关注项
- `red` → 退回策执远修改（最多1轮），仍为 red 则暂停

---

## 阶段五：合并输出与归档（明鉴秋）

### 执行者

明鉴秋 Agent（`futures-debate-team-team-lead`）。

### 合并输出结构

```json
{
  "round_id": "debate_20260706",
  "decisions": {
    "hc": {
      "source_path": "direct_recommend",
      "decision": "execute",
      "direction": "bear", "entry": 3510,
      "target": 3380, "stop": 3580,
      "lots": 4, "contract": "RB2610",
      "risk_color": "green"
    },
    "rb": {
      "source_path": "debate",
      "decision": "execute",
      "direction": "bear", "entry": 3620,
      "target": 3450, "stop": 3720,
      "lots": 3, "contract": "RB2610",
      "risk_color": "yellow"
    }
  },
  "total_exposure_pct": 14.5,
  "summary_200": "本日推荐HC直接推荐空头+RB辩论空头..."
}
```

### 归档

1. `debate_results.json` — 完整决策记录
2. `phase3_generate_report.py` → HTML 报告
3. 各 Agent 按规范写入 `memory/`（辩论索引 + 分数 + 论证模式）

---

## 双通道对比

| 维度 | 通道A 直接推荐 | 通道B 辩论 |
|:-----|:--------------|:-----------|
| **触发条件** | 共识方向+launch+非极端 | 分歧/极端/链补品种 |
| **耗时** | 短（分钟级） | 长（~60min 辩论+评审） |
| **入场参数来源** | 闫判官手动设定 | 辩手提案→闫判官判决 |
| **研究员供弹** | 无 | 需要 |
| **辩论** | 无 | 48min 多轮陈述+rebuttal |
| **判决** | 无（直接认定方向） | 六维评分判胜负 |
| **策执远介入** | 闫判官给参数后立即 | 辩论判决后 |
| **风控** | 标准审核 | 标准审核 |
| **输出格式** | 同一 `TeamDecisionOutput` | 同一 `TeamDecisionOutput` |

---

## 品种分类决策树

```
输入信号
    │
    ├── L1L4方向 == factor方向 且 非中性
    │   ├── stage=="launch" + RSI 30-70 + |Z|<2.0 + 信号>=30
    │   │   └──→ STRONG_RECOMMEND（直接推荐，免辩论）
    │   ├── (launch或非极端) + 信号>=30
    │   │   └──→ WATCH（观察级）
    │   └── 其他
    │       └──→ debate_candidates（共识品种入辩论池）
    │
    └── L1L4方向 != factor方向 且 均非中性
        ├── RSI>75/<25 或 |Z|>2.5
        │   └──→ 左侧反转机会标记 + 辩论池（proposition_side=逆转方向）
        ├── max(|l1l4_total|,|factor_total|) >= 30
        │   └──→ debate_candidates（常规分歧品种）
        └── 信号弱
            └──→ 跳过（避免为辩论而辩论）
```

---

## 执行顺序（完整 CLI 链路）

```bash
# P1: 三生产者扫描
python skills/quant-daily/scripts/scan_all.py -o reports -p full_scan_summary          # 数技源：通道突破
python skills/technical-analysis/scripts/run_l1l4_scan.py --output-dir reports          # 观澜：L1-L4
python skills/fundamental-data-collector/scripts/run_factor_timing_scan.py --output-dir reports  # 探源：因子择时

# P1: 辩论品种精选 + 双通道分离
python skills/quant-daily/scripts/signals/debate_brief.py \
  reports/full_scan_l1l4_*.json reports/full_scan_factor_timing_*.json \
  --select-debate chain_analysis.json --min-count 22

# P1.5: 数据适配（将 candidates 透传到中间数据）
python skills/quant-daily/scripts/assemble_intermediate_data.py \
  --summary reports/full_scan_summary_*.json \
  --chain-analysis chain_analysis.json \
  --candidates candidates.json

# P3(P5): 报告生成
python skills/futures-trading-analysis/scripts/phase3_generate_report.py
```

P2 / 通道B辩论期 / P3-P4（风控审核）由 LLM Agent 层在 spawn 后自动执行。
