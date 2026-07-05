# 期货交易辩论专家团 — 用户使用手册 (v4.3)

## 1. 概述

期货交易辩论专家团是一个 **多Agent深度辩论型期货分析系统**，通过 **10个专业角色Agent** 在 **DAG并行化7级管道** 中协作，对商品期货品种进行结构化多空辩论分析。

**核心理念**：quant-daily 只输出原始信号数值不做判断→链证源先于闫判官做产业链分析→闫判官自主决定辩论品种与方向→多方和空方从研究员资料中提取证据进行辩论→策执远出方案→风控明5层引擎审核（含交易摩擦+流动性风险）→闫判官裁决。

**版本**：v4.3 | **Agent数**：10（1协调员 + 9角色）| **双策略**：L1-L4 + factor_timing（含情感第6因子）

**v4.3 亮点**：
- **情感因子（第6因子）**：sentiment_score 注入 factor_timing 投票系统
- **流动性风险检测**：liquidity_trap 自动阻止流动性枯竭品种开仓
- **交易摩擦精细化**：手续费+滑点+保证金利息+移仓成本，净盈亏比约束
- **Agent通信协议 v3.0**：10角色结构化契约，schema校验+版本迁移
- **DAG并行化引擎**：辩论流程从串行改为7级拓扑并行
- **记忆反思注入**：query_history() 注入闫判官/策执远同品种历史决策
- **事件日历时间窗**：get_upcoming_events() 自动降杠杆避让宏观事件
- **特征工程注入**：export_feature_summary() top-5特征送研究员
- **ML+规则集成**：export_ensemble_votes() 第三路信号进证据简报

## 2. 系统架构

```
┌── 用户 ───────────────────────────────────────┐
│  "分析螺纹钢期货的多空博弈情况"                  │
└────────────────────┬───────────────────────────┘
                     ↓
┌────────────────────▼───────────────────────────┐
│   明鉴秋（独立协调员）                           │
│   选题→触发scan_all.py --dual→收束→拍板          │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│   数技源 → scan_all.py --dual                    │
│   ├── full_scan_l1l4_{date}.json                 │
│   ├── full_scan_factor_timing_{date}.json         │
│   └── full_scan_summary_{date}.json              │
│      └── 每个品种含 risk_input 字段               │
│           (confidence/ATR/ADX/pattern_risk)       │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  S1.5: 链证源 → 产业链分析（先于闫判官决策）      │
│  输出产业链景气度快照，不下多空结论               │
│  风控明同步做辩论前预审(换月/交割/事件检查)       │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  S2: 闫判官综合双策略信号 + 产业链信息             │
│  → 决定辩论品种和正方方向                          │
└────┬───────────────────────────┬────────────────┘
     │                           │
     ▼                           ▼
   观澜(技术分析·v2.1)         探源(基本面分析)
   L1-L4+支撑阻力+量价+         factor_timing+供需库存+
   多周期共振+事件日历          互联网+数据源评级
     │          │          │
     └──────────┼──────────┘
                ▼
     ┌──────────┴──────────┐
     ▼                     ▼
  证真(多方)            慎思(空方)
  从研究员资料中         从研究员资料中
  提取多头论据           提取空头论据
     │                     │
     └──────────┬──────────┘
                ▼
        ┌───────────────┐
        │  策执远出方案  │
        │  (含初始止损)  │
        └───────┬───────┘
                ▼
        ┌───────────────┐
        │ 风控明5层引擎  │  ← risk_engine.py
        │ L1:选锚        │     0.8~2.5ATR+整数关口避开
        │ L2:仓位        │     confidence+pattern折减
        │ L3:动态        │     逻辑止损/ATR扩张/trailing
        │ L4:覆写        │     换月/交割/夜盘/宏观事件
        │ L5:反馈        │     build_feedback_entry()
        └───────┬───────┘
                ▼
        ┌───────────────┐
        │ 闫判官最终裁决 │
        └───────┬───────┘
                ▼
        ┌───────────────┐
        │ 明鉴秋汇总输出 │
        │ + 记忆自动写入 │
        │ + PnL反馈闭环  │
        └───────────────┘
```

## 3. 双策略信号解读

### L1-L4 技术信号

40+技术指标累加打分（ADX/RSI/CCI/MACD/MA排列等）：

| 等级 | 总分范围 | 含义 |
|:----|:--------:|:-----|
| STRONG | ≥ 75 | 最强信号，多层共振 |
| WATCH | 60-74 | 重点信号，方向一致 |
| WEAK | 40-59 | 信号一般，需验证 |
| NOISE | < 40 | 噪音，忽略 |

### factor_timing 因子信号

6因子投票合成（展期收益率/动量/反向仓单/偏度/量价相关性/**情感评分**）：

| 字段 | 含义 |
|:-----|:-----|
| total | 总分（正=多头，负=空头） |
| vote_net | 投票净票（-6~+6，因子一致程度） |
| ts_type | 期限结构类型（Back/Contango/Flat） |
| g_group | 分组（g1_bull/g1_bear=动手组，g10=观望组） |
| sentiment_score | 第6因子，情感评分（期货论坛/新闻，-100~+100） |

> 情感因子通过 `data/sentiment/sentiment_collector.py` 采集，可作为独立定时任务刷新 `sentiment_cache.json`。因子不可用时自动回退到5因子。`seed_sentiment(symbol, score)`支持手动标注。

### risk_input 字段（风控专用）

`full_scan_summary.json` 中每个品种新增 `risk_input` 字段：

```json
{
  "confidence": 72,
  "ATR": {"value": 42, "period": 14},
  "adx": 69.2,
  "direction_conflict": true,
  "pattern_risk": "双顶雏形_未确认",
  "invalid_condition": "日线收盘跌破6830且OI增>5%"
}
```

## 4. 辩论流程详解

### 阶段一：数据准备 — 数技源

```bash
python skills/quant-daily/scripts/scan_all.py --dual --symbols RB,PK,M
```

产出三份文件：L1-L4信号、factor_timing信号、双策略汇总（含risk_input）。

### 阶段一·五：产业链分析 — 链证源

链证源先于闫判官决策，分析产业链景气度、上下游结构关系、品种间相关性。只做事实描述，不下多空结论。风控明同步做品种预审（换月周/交割月/宏观事件检查）。

### 阶段二：闫判官定辩论标的

综合双策略信号 + 产业链信息，自行决定：
- 哪些品种值得辩论（方向冲突大 + 产业链信号交汇的优先）
- 正方方向（选择论据更充分的方向）
- 风控明预审 flag 辅助判断

### 阶段三：辩论

1. **观澜（技术分析·v2.1）**— 技术分析，输出包含：
   - ZigZag拐点+Volume Profile支撑阻力（hard/soft分类）
   - ATR动态容差带（hard=0.3×, medium=0.5×, soft=1.0×）
   - 失效条件标记（"日线收盘破6830且OI增>5%"）
   - 多周期共振验证（日线+1H+15min交叉打标签）
   - OI/量能确认（涨到压力位OI大增→真压力，OI减→假突破风险）
   - 换月跳空屏蔽（消除伪拐点）
   - 事件日历影响判定（FOMC/NFP日自动降置信度）

2. **探源（基本面分析）**— 基本面分析，包括：
   - factor_timing因子数据
   - 供需/库存/利润数据
   - 互联网资料（政策/天气/地缘）

3. **链证源**— 产业链分析结果供置信度修正（adjust_confidence_with_chain）

| 辩论时段 | 内容 |
|:---------|:------|
| 0-8min | 多方立论（从研究员资料中提取多头论据） |
| 8-16min | 空方立论（从研究员资料中提取空头论据） |
| 16-24min | 多方rebuttal |
| 24-32min | 空方rebuttal |
| 32-42min | 自由交锋 |
| 42-48min | 最终陈述 |

### 阶段四：方案→风控→裁决→汇总

1. **策执远出方案**：合约选型 + 入场价 + 初始止损 + 手数建议
2. **风控明5层引擎审核**：
   - **L1 选锚**：从观澜hard支撑中选0.8~2.5ATR最优锚，避开整数关口
   - **L2 仓位**：confidence折减（≥80全仓/65-79八折/50-64五折/<50不开） + pattern_risk额外七折
   - **L3 动态调整**：支撑破位→逻辑止损先行；假突破→收紧止损；ATR扩张→重算；新支撑→trailing
   - **L4 特殊覆写**：换月周降级hard→soft+降仓50%；交割月强制30%以下；夜盘放宽止损；事件日置信度打折50%
   - **L5 反馈回流**：平仓后记录→假破率统计→同类型支撑置信度校准
3. **闫判官最终裁决** → 明鉴秋汇总输出 + memory写入 + PnL反馈闭环

## 5. 风控明 — 观澜耦合详解

### 选锚算法

```
风控明从观澜 hard 支撑中选锚：
  ① 过滤：只留 hardness=hard + price < 当前价
  ② 排序：距当前价从近到远
  ③ 择优：选"距离在 0.8~2.5 倍 ATR 之间"的支撑
     - 太近(<0.8ATR)：扫损概率过高 → 降级到下一根
     - 太远(>2.5ATR)：止损太大，仓位起不来 → 向前取
  ④ 避开整数关口：6850→6842，防程序化扫单
  ⑤ 最终止损 = anchor_price - 0.4×ATR（容差）
```

### 置信度仓位折减

| confidence | 仓位比例 | 逻辑 |
|:-----------|:--------|:-----|
| ≥80 | 100% | 技术位硬+多周期共振 |
| 65-79 | 80% | 标准仓 |
| 50-64 | 50% | 降仓等二次确认 |
| <50 | 不开仓 | 技术Agent自己都不确信 |

### 动态监控场景

| 观澜推送事件 | 风控明动作 |
|:-------------|:-----------|
| 支撑失效(日线收盘破+OI增) | 逻辑止损先行→不等价格到位 |
| 假突破识别(插针收+OI未增) | 止损上移收紧 |
| ATR扩张(ATR从42跳到68) | 放宽止损+同步减仓 |
| 新hard支撑出现 | trailing止损锁定浮盈 |
| 宏观事件| 事件前一日降仓70%，事件当日置信度打折50% |

## 6. 技术分析 v2.1 支撑阻力识别

| 方法 | 算法 | 输出 |
|:-----|:-----|:-----|
| 静态位 | ZigZag拐点(可屏蔽换月跳空) + 前高前低 + 整数关口 | `price`, `hardness`, `source` |
| 动态位 | MA20/MA60/布林带/VWAP + 趋势线拟合 | `price`, `tolerance`, `fail_condition` |
| 量价密集 | Volume Profile(POC/VAH/VAL) | `tfs`, `resonance`, `oi_check` |
| 多周期共振 | cross_validate_timeframes(日线+1H+15min) | `confirmed`/`single` |

每个关键位输出：
```json
{"price": 146.0, "hardness": "hard", "tolerance": 1.3, "source": "VP-VAH",
 "fail_condition": "日线实体收盘价<146.0且下根K线不收回",
 "resonance": "confirmed", "tfs": ["daily", "m15"]}
```

## 7. P3 模块使用

### 事件日历 + 时间窗

```python
from technical-analysis.scripts.event_calendar import check_event_impact, get_upcoming_events
# 单日检查
impact = check_event_impact('2026-07-29', 'SC')
# → {"has_event": true, "confidence_discount": 0.5, ...}

# 前瞻时间窗（闫判官/风控明自动调用）
events = get_upcoming_events('M', days=7)
# → [{"event_type": "USDA_WASDE", "days_until": 3, "confidence_discount": 0.5}]
```

### 跨品种联动

```python
from technical-analysis.scripts.cross_correlation import get_correlation_peers
peers = get_correlation_peers('RB', price_dict)
# → [{"symbol": "HC", "correlation": 0.95}, {"symbol": "I", "correlation": 0.82}]
```

### ML方向预测 + 批量导出（第3路信号）

```python
from quant-daily.scripts.ml_models.direction_classifier import EnsemblePredictor
ensemble = EnsemblePredictor(rule_weight=0.6, ml_weight=0.4)
result = ensemble.predict(rule_output, ml_output)
# → {"prob": 0.68, "direction": 1, "confidence": 73}

# 批量导出（供闫判官证据简报）
votes = ensemble.export_ensemble_votes(['RB', 'PK', 'M'], rule_outputs, ml_outputs)
# → {"RB": {"rule_dir": "bear", "ml_dir": "bear", "ensemble_dir": "bear", "consensus": true, ...}}
```

### 特征工程摘要（研究员注入）

```python
from quant-daily.scripts.feature_pipeline.feature_engineering import engineer_features, export_feature_summary
features = engineer_features(closes, highs, lows, volumes, oi_series, adx=72, rsi=35)
summary = export_feature_summary('RB', features)
# → {"symbol": "RB", "top_features": [{"feature": "oi_zscore", "name": "OI Z分数", "value": -2.1}, ...],
#     "summary": "RB 特征摘要: OI Z分数(oi_zscore)=-2.1 | ..."}
```

### 交易摩擦计算

```python
from debate-risk-manager.scripts.risk_engine import calc_transaction_cost
friction = calc_transaction_cost('RB', entry_price=3600, lots=4, multiplier=10, holding_days=10)
# → {"fee_total": 28.8, "slippage_total": 144.0, "interest_total": 24.7, "roll_total": 0,
#     "total_cost": 197.5, "cost_per_lot": 49.38, ...}
```

### 流动性风险

```python
from debate-risk-manager.scripts.risk_engine import get_liquidity_risk, set_liquidity_params

set_liquidity_params('RB', volumes=[12000, 11000, 4500, 4200, 3900])
risk = get_liquidity_risk('RB')
# → {"liquidity_risk": 0.56, "vol_ratio": 0.33, "liquidity_trap": true, "risk_level": "red"}
# liquidity_trap=true → 风控明直接 red_flag 阻止开仓
```

### DAG并行辩论引擎

```python
from quant-daily.scripts.signals.debate_engine import DebateEngine, run_pipeline

# 一键运行完整辩论流
report = run_pipeline({"scan": scan_func, "chain": chain_func, ...})
# → {"total_duration": 45.2, "sequential_est": 120.0, "parallel_gain": 2.65, ...}
```

### PnL反馈 + 记忆注入

```python
from quant-daily.scripts.feedback.trade_journal import record_trade, close_trade, query_history
trade = record_trade('RB', 'long', 6880, 6763, 7200, 6, '2026-07-05', tech_prediction={...})
close = close_trade(trade['trade_id'], 7020, '2026-07-10', multiplier=10)
perf = get_performance_summary()

# 同品种历史查询（闫判官/策执远自动调用）
history = query_history('RB', lookback_days=30)
# → [{"direction": "long", "pnl_pct": 4.5, "entry_price": 6880, ...}, ...]
```

## 8. 启动方式

```bash
# 双策略扫描（数据辅助决策）
python skills/quant-daily/scripts/scan_all.py --dual --symbols RB,PK

# 直接向专家团发出指令
"分析螺纹钢期货的多空博弈情况"
```

## 9. 记忆系统

所有Agent运行后自动写入 `memory/` 目录：

| 文件 | 内容 | 由谁写入 |
|:----|:-----|:---------|
| `debate_journal.json` | 全部操作日志（含时间戳+Agent+动作） | 全员 |
| `argument_patterns.md` | 有效论证模式库 | 证真/慎思/闫判官 |
| `debater_profiles.md` | 各角色辩论表现记录 | 闫判官 |
| `data_sources.md` | 数据源可靠性评级 | 探源/风控明 |
| `execution_followup.json` | 实盘执行回溯 | 策执远 |
| `debates/INDEX.md` | 辩论轮次索引 | 明鉴秋/闫判官 |
| `policies/veto_policies.md` | 否决规则库 | 风控明/明鉴秋 |
| `policies/weighting_history.md` | 评分权重调整记录 | 闫判官/明鉴秋 |

## 10. 效率提示

- **数据先行**：辩论前先跑 `--dual` 获得信号概览，节省辩论时间
- **关注分歧**：L1-L4和factor_timing方向冲突的品种辩论价值最高
- **硬支撑为王**：风控明仅挂单 hard 级支撑（VP-POC/多周期共振/整数关口），soft 支撑只预警不设止损
- **换月警惕**：换月周内前高前低可能失真，hard 支撑自动降级为 soft
- **事件避让**：FOMC/NFP/EIA日前降仓70%，事件当日技术置信度打折50%。`get_upcoming_events()` 可查未来7天事件窗
- **流动性检查**：成交量萎缩至30日均40%以下时 `liquidity_trap=true`，此时不应开仓
- **摩擦前/后对比**：全品种摩擦成本不同（螺纹钢万0.1 vs 铁矿石万1），净盈亏比 < 1.5 的方案标记为 yellow_flag
- **记忆会累积**：多次运行后 `argument_patterns.md` 积累有效论证模式，`trade_journal` 积累假破率统计，`query_history()` 查询同品种历史决策可避免重复踩坑

## 11. 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v4.3** | **2026-07-05** | **P0+P1全面实施**：情感因子(第6因子)+sentiment_collector; 流动性风险liquidity_trap检测; 交易摩擦精细化(利息+移仓+净盈亏比); Agent通信协议v3.0(contracts包+10角色schema); DAG并行化引擎(debate_engine.py); 记忆反思 query_history 注入; 事件日历时间窗 get_upcoming_events; 特征工程 export_feature_summary 注入研究员; ML export_ensemble_votes 第3路信号; 优化计划P0 8/8 + P1 7/7全部完成 |
| **v4.2** | **2026-07-05** | **P3全量实现**：Phase1 事件日历+跨品种联动 / Phase2 ML特征管道(30+维) / Phase3 DirectionClassifier+EnsemblePredictor / Phase4 PnL反馈闭环；风控明5层引擎(risk_engine.py)；观澜技术分析v2.1支撑阻力(hardness/容差/失效/共振)；换月跳空屏蔽+OI/量能确认；risk_input字段注入；全审计8项修复 |
| v4.1 | 2026-07-05 | 方案C仲裁者裁决：量析师移除(10角色)；数技源改为--dual双策略输出；链证源前置(S1.5)；所有Agent自动写memory；`memory/rules/` → `memory/policies/` |
| v4.0 | 2026-07-04 | 策略可插拔架构 |
| v3.3 | 2026-07-04 | quant-daily真分层打分集成 |
