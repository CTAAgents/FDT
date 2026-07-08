# 辩论质量 × ML 迭代 × 实盘验证 — 实施方案

> **版本**: v1.0 | **日期**: 2026-07-05  
> **定位**: 从"25项架构优化"阶段进入"信号质量提升"阶段  
> **核心原则**: 不新增任何基础设施依赖，在现有 JSON + SQLite 架构上解决问题

---

## 一、辩论质量：从"走过场"到"真拷问"

### 1.1 当前问题

```
证真："RB技术面多头排列，MACD金叉，支撑在3450，建议做多"
慎思："RB库存高位，需求不足，建议做空"
闫判官："双方都有道理，我选... 多头吧"
```

**三刀致命伤**：
1. **立论靠说，不靠数字** — 证据不含具体数值+来源+日期
2. **反驳不抓逻辑漏洞** — 各说各的，不解构对方论证
3. **裁决凭感觉** — 5 维度评分没人监督打分过程

### 1.2 解决思路：结构化辩论协议 v2.0

把辩论从"自由对话"变成**结构化攻防**。

#### 1.2.1 立论格式：每个论点必须 4 字段

```
论证框架 (CLAIM → EVIDENCE → REASONING → IMPACT):
  - CLAIM:   断言（一句话，可证伪）
  - EVIDENCE: 证据（必含：数值+单位+来源+截至日期）
  - REASONING: 推理链（大前提→小前提→结论）
  - IMPACT:  影响程度（HIGH/MEDIUM/LOW） + 影响方向（利多L1~L5 / 利空B1~B5）
```

当前系统有 `ArgumentOutput` schema（`contracts/debate.py`），但 `evidence` 字段是自由文本。需要改为结构化格式。

#### 1.2.2 反驳协议：必须引用对方论点 ID

```
每次反驳格式:
  "反驳论点ID: 证真-D1
   逻辑漏洞类型: 因果倒置 / 数据过时 / 样本偏差 / 推理跳跃
   我方证据: ...
   反例/反证: ..."
```

这样闫判官可以追踪：**"慎思反驳了证真的 D1 论点，但遗漏了 D2 ↑↑↑"**

#### 1.2.3 证据加权打分（取代 5 维度归一化）

当前闫判官的 5 维度评分（逻辑/证据/全面性/反驳/风险）是平权的。改为 **证据加权**：

```python
def score_argument(claims: list) -> dict:
    """按证据质量加权打分，替代凭感觉评分。"""
    weighted = 0
    for claim in claims:
        evidence = claim["evidence"]
        
        # 证据要素检查（每个要素 +1 分）
        has_number = 1 if re.search(r'\d+', evidence["value"]) else 0
        has_source = 1 if evidence["source"] != "" else 0
        has_date = 1 if evidence["date"] != "" else 0
        is_recent = 1 if (today - parse(evidence["date"])).days < 7 else 0
        
        # 来源质量（官方数据 +2，新闻 +1，推测 0）
        source_quality = {
            "交易所": 2, "统计局": 2, "Mysteel": 2,
            "行业网站": 1, "新闻媒体": 1,
            "推测": 0, "我认为": 0,
        }.get(evidence["source"], 0)
        
        evidence_score = (has_number + has_source + has_date + is_recent + source_quality) / 6
        weighted += evidence_score
    
    return {
        "total_score": weighted / max(len(claims), 1),
        "claim_count": len(claims),
        "high_impact_count": sum(1 for c in claims if c["impact"] == "HIGH"),
    }
```

### 1.3 实施步骤

| 步骤 | 内容 | 涉及文件 | 工时 |
|:-----|:-----|:---------|:----|
| 1.3.1 | 修改 `contracts/debate.py` 中 `DimensionItem`，新增 `evidence_schema` 结构化字段 | `contracts/debate.py` | 1h |
| 1.3.2 | 修改 `debate-argument-builder` SKILL.md，定义结构化辩论协议 | `skills/debate-argument-builder/SKILL.md` | 2h |
| 1.3.3 | 在 证真/慎思 prompt 中注入论点格式化模板 + 必须引用对手论点 ID | `agents/futures-affirmative-debater.md`, `agents/futures-opposition-debater.md` | 2h |
| 1.3.4 | 闫判官评分改为证据加权自动计算，human review 只做 ±10% 微调 | `contracts/judge.py` | 1h |
| 1.3.5 | 新增 `EvidentialDebate` schema（替代原有的 `ArgumentOutput`） | `contracts/debate.py` | 1h |
| **合计** | | | **7h** |

---

## 二、ML 模型迭代：从"静态模型"到"自适应进化"

### 2.1 当前问题

```
DirectionClassifier.train(X, y)  # 手动调用，一天一次
EnsemblePredictor.predict(rule_output, ml_output)  # rule_weight=0.6 写死
```

**三刀致命伤**：
1. **训练靠手动** — 没有自动增量训练管道，模型周级老化
2. **权重写死** — `rule_weight=0.6` 不会根据近期表现调整
3. **无特征衰减监控** — 不知道哪些特征已失效

### 2.2 解决思路：全自动 ML 管道

#### 2.2.1 自动增量训练（每日收盘后触发）

```
TradeJournal 收录当日的辩论 → 执行 → PnL
                    ↓
每日收盘后自动运行:
1. 提取今日新增样本 (feature_vector, pnl_direction)
2. DirectionClassifierV2.incremental_train(X_new, y_new)
   → 参数: learning_rate=0.01, num_boost_round=10
3. 记录模型版本到 version_control.json
4. 如果连续3天胜率下降 > 5%，触发全量重训练警
```

#### 2.2.2 动态权重调整（基于滚动 20 笔表现）

```python
class AdaptiveEnsemble:
    """自适应集成 — 规则 vs ML 的权重动态调整。"""
    
    def __init__(self, window=20):
        self.window = window
        self.rule_hits = []    # 规则方向正确的次数
        self.ml_hits = []      # ML方向正确的次数
    
    def record(self, rule_correct: bool, ml_correct: bool, pnl: float):
        self.rule_hits.append(rule_correct)
        self.ml_hits.append(ml_correct)
        # 只保留最近 window 笔
        if len(self.rule_hits) > self.window:
            self.rule_hits.pop(0)
            self.ml_hits.pop(0)
    
    def get_weight(self):
        """动态权重 = 滚动胜率 / 总胜率。"""
        rule_win = sum(self.rule_hits) / max(len(self.rule_hits), 1)
        ml_win = sum(self.ml_hits) / max(len(self.ml_hits), 1)
        total = rule_win + ml_win
        if total == 0:
            return 0.6, 0.4  # 无数据时用默认值
        return rule_win / total, ml_win / total
```

#### 2.2.3 特征衰减监控看板

```python
def analyze_feature_decay(model, recent_importance: dict, history: list):
    """
    输入: 当前模型的特征重要性 + 历史记录
    输出: {
        "stable": [...],      # 重要性稳定
        "decaying": [...],    # 衰减 > 30%
        "dead": [...],        # 重要性 < 1% 阈值
    }
    """
    if len(history) < 2:
        return {"stable": [], "decaying": [], "dead": []}
    
    baseline = history[-2]
    current = recent_importance
    results = {"stable": [], "decaying": [], "dead": []}
    
    for feature, current_imp in current.items():
        base_imp = baseline.get(feature, 0)
        if current_imp < 0.01:
            results["dead"].append(feature)
        elif base_imp > 0 and (base_imp - current_imp) / base_imp > 0.3:
            results["decaying"].append(feature)
        else:
            results["stable"].append(feature)
    
    return results
```

当监测到衰减超过阈值的特征时，自动触发特征工程模块重新生成替代特征。

### 2.3 实施步骤

| 步骤 | 内容 | 涉及文件 | 工时 |
|:-----|:-----|:---------|:----|
| 2.3.1 | 实现 `AdaptiveEnsemble` 类，替换 EnsemblePredictor 的固定权重 | `ml_models/direction_classifier.py` | 1h |
| 2.3.2 | 实现 `analyze_feature_decay` + 自动报告 | `feature_pipeline/feature_engineering.py` | 1h |
| 2.3.3 | 创建每日收盘后自动增量训练的 cron 触发入口 | `scripts/auto_train.py` | 2h |
| 2.3.4 | 实现模型版本控制（训练时间+性能快照+回退机制） | `scripts/model_registry.py` | 1h |
| 2.3.5 | 集成 trade_journal 的 PnL 反馈 → AdaptiveEnsemble.record() | `feedback/trade_journal.py` | 1h |
| **合计** | | | **6h** |

---

## 三、实盘验证：从"模拟"到"真实检验"

### 3.1 当前问题

```
执行引擎已创建（execution_agent.py），但：
- 无实际撮合验证
- 无滑点模型（paper mode 用固定滑点 1 ticks）
- 无实盘交易日志可复盘
- 切到 live mode 的风险不可控
```

**最担心的不是"策略亏钱"，而是"我不知道策略为什么不赚钱"**。

### 3.2 解决思路：三层验证 + 回测/模拟/实盘闭环

#### 3.2.1 第一层：回测验证（已有，需升级）

当前回测的问题：
- 600 天数据，但只有 RB 做了全量回测
- 无样本外验证（walk-forward）
- 摩擦折减只有手续费，缺少冲击成本模型

```python
# 新增 walk-forward 回测模式
python scan_all.py --symbols RB,PK,CU --backtest --walk-forward 180 60
# 用 180 天训练，60 天验证，滚动窗口验证策略稳定性
```

#### 3.2.2 第二层：Paper Trade 验证（核心新增）

**核心规则：Paper=模拟盘≠回测**

| 维度 | 回测 | Paper Trade | Live |
|:-----|:-----|:------------|:-----|
| 数据 | 历史数据回放 | **实时行情驱动** | 实时行情 |
| 滑点 | 固定 1 tick | **动态滑点模型** | 实际成交 |
| 成交 | 假设全部成交 | **50%概率部分成交** | 实际撮合 |
| 心理 | 无 | **有"持仓压力"** | 真实压力 |
| 资金 | 虚拟 | 虚拟（记录净值） | 真实 |

Paper Trade 落地：在 `execution_agent.py` 中

```python
class PaperExecutionEngine:
    """模拟盘引擎 — 动态滑点 + 部分成交。"""
    
    def __init__(self):
        self.positions = {}   # {symbol: lots}
        self.equity = 1_000_000
        self.trades = []      # 所有历史交易
    
    def on_signal(self, signal: dict):
        """收到辩论信号 → 检查 -> 发单 -> 部分成交。"""
        # 1. 合约检查（主力/非主力、涨跌停、开盘前）
        check = self._pre_check(signal["symbol"])
        if not check["pass"]:
            return {"status": "rejected", "reason": check["reason"]}
        
        # 2. 发单
        order = self._place_order(signal)
        
        # 3. 动态成交（50%~100%概率成交，滑点 0~3 ticks）
        filled = self._simulate_fill(order)
        
        # 4. 更新持仓
        self._update_position(filled)
        
        return filled
    
    def _simulate_fill(self, order: dict) -> dict:
        """模拟成交 — 基于实时盘口数据。"""
        import random
        fill_rate = 0.5 + random.random() * 0.5  # 50%~100%
        slippage = random.randint(0, 3)           # 0~3 ticks
        # 实际部署时从 TqSDK 获取实时盘口
        return {
            "filled": order["lots"] * fill_rate,
            "price": order["price"] + slippage * order["tick_size"],
            "slippage_ticks": slippage,
        }
```

#### 3.2.3 第三层：过渡到实盘的安全检查

切换到 `--mode live` 前的**8 道安检**：

```python
LIVE_CHECKLIST = [
    ("Paper 运行 > 20 笔", lambda: len(paper_trades) >= 20),
    ("Paper 胜率 > 40%", lambda: paper_win_rate > 0.4),
    ("Paper 盈亏比 > 1.2", lambda: paper_profit_factor > 1.2),
    ("最大回撤 < 15%", lambda: paper_max_dd < 0.15),
    ("连续亏损不超过 5 笔", lambda: paper_max_losses < 5),
    ("持仓过夜 < 50% 仓位", lambda: paper_overnight_ratio < 0.5),
    ("ML 方向与规则方向一致（双策略同向）", lambda: ml_rule_aligned),
    ("闫判官裁定为 execute（非 hold/rematch）", lambda: verdict == "execute"),
]

def live_readiness_check() -> dict:
    for check in LIVE_CHECKLIST:
        name, fn = check
        if not fn():
            return {"ready": False, "blocked_by": name}
    return {"ready": True}
```

### 3.3 实盘交易日志复盘系统

每次实盘/Paper 交易后记录到 `scripts/trade_journal.py` 的升级版：

```python
TRADE_LOG_SCHEMA = {
    "round_id": str,          # "RB_20260705"
    "mode": str,              # "paper" / "live"
    "signal": {               # 辩论产生的信号
        "direction": str,
        "confidence": float,
        "rule_vote": float,
        "ml_vote": float,
        "sentiment_vote": float,
    },
    "execution": {            # 实际执行
        "contract": str,
        "entry_price": float,
        "lots_filled": int,
        "slippage_ticks": int,
        "commission": float,
    },
    "risk": {                 # 风控记录
        "stop_loss": float,
        "take_profit": float,
        "margin": float,
        "risk_verdict": str,  # "green" / "yellow" / "red"
    },
    "outcome": {              # 平仓结果
        "exit_price": float,
        "pnl": float,
        "exit_reason": str,   # "stop_loss" / "take_profit" / "manual" / "expiry"
        "duration_hours": float,
    },
}
```

每日复盘时自动分析：

```python
def daily_review(trades: list) -> dict:
    return {
        "summary": {
            "total_trades": len(trades),
            "win_rate": wins / total,
            "profit_factor": gross_profit / max(gross_loss, 1),
            "avg_slippage": sum(t["slippage_ticks"] for t in trades) / total,
        },
        "by_symbol": ...,
        "by_weekday": ...,          # 周几表现最好？
        "by_confidence": ...,       # 高置信度 vs 低置信度
        "ml_vs_rule": {             # ML vs 规则，谁今天更准？
            "ml_correct": ml_wins,
            "rule_correct": rule_wins,
        },
    }
```

### 3.4 实施步骤

| 步骤 | 内容 | 涉及文件 | 工时 |
|:-----|:-----|:---------|:----|
| 3.3.1 | `execution_agent.py` 新增 `PaperExecutionEngine` 类 + 动态滑点模型 | `scripts/execution_agent.py` | 3h |
| 3.3.2 | `trade_journal.py` 升级为完整交易日志 schema，含信号/执行/风控/结果 | `feedback/trade_journal.py` | 2h |
| 3.3.3 | 实现 `live_readiness_check()` 8 道安检 | `scripts/execution_agent.py` | 1h |
| 3.3.4 | 实现 `daily_review()` 自动复盘分析 | `scripts/ops_monitor.py` | 2h |
| 3.3.5 | 回测新增 walk-forward 模式 + 多品种批量回测入口 | `scan_all.py` + `backtest_report.py` | 2h |
| **合计** | | | **10h** |

---

## 四、总实施计划

### 4.1 优先级排序

| 优先级 | 模块 | 工时 | 为什么排这里 |
|:------|:-----|:-----|:------------|
| **P0** | 辩论质量 | 7h | **直接决定信号质量**。LLM 辩论质量不提升，ML 和实盘都是无源之水 |
| **P1** | ML 迭代 | 6h | 特征衰减监控可立即止损，自适应权重在辩论质量提升后发挥更大价值 |
| **P2** | 实盘验证 | 10h | 最晚启动，因为"信号质量"→"模拟验证"→"实盘"有先后依赖 |

### 4.2 迭代节奏

```
第 1-2 天（14h）：辩论质量 7h + ML 迭代 6h + 收尾 1h
  → 产出: 结构化辩论协议 + 自动化 ML 管道 + 动态权重
  
第 3-4 天（10h）：实盘验证
  → 产出: Paper 可运行 + 8 道安检 + 每日复盘报告
  
第 5 天（4h）：联调全链路
  → 辩论产生信号 → ML 加上权重 → Paper 执行 → 每日复盘
```

### 4.3 成功标志

| 模块 | 可量化标志 | 验收方式 |
|:-----|:----------|:---------|
| 辩论质量 | 闫判官裁决与证据加权评分的一致性 > 85% | 10 轮辩论人工校验 |
| ML 迭代 | 自动增量训练连续运行 7 天不报错，特征衰减报告每日生成 | `cron` 检查 |
| 实盘验证 | Paper mode 连续运行 20 笔以上，`live_readiness_check` 报告可查看 | `daily_review()` 输出 |

---

## 五、不做的事

| 事项 | 原因 |
|:-----|:-----|
| ❌ 不替换 JSON 为 PG | 当前 10MB 数据量，SQLite WAL 已够用 |
| ❌ 不增加新 Agent 角色 | 10 角色已够多，增加角色带来通信复杂度 > 边际收益 |
| ❌ 不做实时行情接口 | TqSDK 已有 wait_update，改实时意味着重写数据层 |
| ❌ 不做 UI 面板 | 运维面板用 HTML 报告输出，不引入前端框架 |
| ❌ 不接入 CTP 实盘 | `--mode live` 保留入口，但实际实盘需掌柜亲自审核通过后才可启用 |
