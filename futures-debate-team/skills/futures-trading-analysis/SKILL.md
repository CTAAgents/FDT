---
name: futures-trading-analysis
version: 2.6.0
description: 期货交易辩论专家团 v2.7 — 明鉴秋协调9Agent。contracts/ Pydantic schema 版本化契约，Shared State按需传参，P3交叉质询（研究员数据驱动、辩手不做独立搜索），混合Supervisor/Handoff模式，PhaseMeta可观测+repair_phase容错+PhaseGuard自动团队恢复+产物双写。
allowed-tools: Read,Bash
agent_created: true
changelog: |
  v2.7.0 (2026-07-03): 流程修正 — 研究员先产出快照（探源WebSearch+观澜量价分析），辩手基于研究员数据提炼论据（不做独立搜索）。Phase 2新增研究员并行产出阶段，Phase 3改为研究员数据驱动模式。修正所有辩手"必须使用WebSearch/WebFetch"的错误指引。
  v2.6.0 (2026-07-01): PhaseGuard自动团队恢复协议 — 每次spawn前自动检测团队连通性+静默恢复；产物双写(SendMessage+文件)；固定团队命名(无随机后缀)；恢复透明性(后续Agent无感知)
  v2.5.1 (2026-07-01): 团队上下文恢复机制 — 新增Team Resilience SOP(会话边界切换导致团队失联的5步恢复流程)；
  v2.5.0 (2026-07-01): 四层架构升级 — ①格式层：Pydantic契约替换###END_XXX哨兵 ②传输层：DebateState typed state按需传参 ③拓扑微调：P3交叉质询1轮+Supervisor/Handoff混合模式 ④可观测：PhaseMeta+confidence+repair_phase回退机制
  v2.4.0 (2026-06-30): 新增裁决权重铁律 + 闫判官Prompt嵌入裁决权重规则 — 价格是唯一客观现实最高原则，期限结构权重上限15%，禁止用左侧信号推翻右侧价格方向
  v2.3.0 (2026-06-30): 新增闫判官裁决者角色 — P3后插入P3b，牛势研+熊谋略辩论后由闫判官综合权衡做出方向裁决，P4风控明基于裁决做风险评估
  v2.2.0 (2026-06-30): 各Agent新增基本面搜索能力 — 牛势研/熊谋略/链证源增加WebSearch/WebFetch工具；辩论不再纯LLM推断；风控明同链冗余升级为相关性驱动排除
  v2.1.0 (2026-06-30): 新增 mode 双模式 — 全市场(full_scan)/指定品种(custom)，Phase 1 内嵌全品种扫描，消除与外部 phase1_collect_signals.py 的重复
  v2.0.0 (2026-07-01): 架构解耦 — 各Agent工作方法剥离至对应skill，主skill只保留角色定义+编排流程+边界能力
  v1.3.5 (2026-07-01): 风控明→策执远交接接口
  v1.3.4 (2026-07-01): 链证源重构
  v1.3.3 (2026-07-01): 技研锋重构
  v1.3.2 (2026-07-01): 数聚石重构
  v1.3.1 (2026-07-01): 组合级风控修复
  v1.3.0 (2026-06-30): 架构重构 — 明鉴秋独立协调员 + 7专家
disable: false
---

# 商品期货交易辩论专家团 — 按需分析

## 依赖
- **编排层输出**：所有 Phase 的 schema 定义在 `contracts/` 目录下（`data_collection.py`, `technical.py`, `chain_analysis.py`, `debate.py`, `risk.py`, `trading_plan.py`）
- **下游子 skill**：`debate-argument-builder`（P3）、`debate-risk-manager`（P4）、`debate-trading-planner`（P5）、`debate-judge`（P3b）、`futures-data-search`（P1）、`commodity-trend-signal`（P1）、`commodity-chain-analysis`（P2）
- **版本**：全部 `2.0`（前端按 version 字段路由）
- **解析方式**：`parse_and_migrate()`（见调度协议章节）
- **通信协议**：正文（HTML 报告）+ 末尾 ```json fence 结构化摘要 → `parse_and_migrate` → state

## 架构

```
用户/定时任务 触发辩论
    ↓ (传参 mode + targets)
WorkBuddy 自动化协调器 → spawn 明鉴秋(独立协调员 Agent)
    ↓
明鉴秋: 根据 mode 选择 Phase 1 扫描范围
    ├─ mode=full_scan → 全67品种（定时任务）
    └─ mode=custom    → 指定品种列表（独立调用）
    ↓
明鉴秋: TeamCreate → 6阶段调度9专家（各Agent的工作方法由对应skill定义）
    ↓
明鉴秋: 汇总 → debate_results.json → phase3_generate_report.py → HTML报告
    ↓
明鉴秋: SendMessage → WorkBuddy → present_files 交付
```

**关键设计**：
- 明鉴秋是独立协调员，不参与分析，只做流程调度
- 7专家为 general-purpose Agent，独立分析，SendMessage 产出给协调员
- WorkBuddy 自动化协调器不参与辩论内容，仅触发和接收报告
- **各Agent的工作方法定义在对应skill中，修改Agent方法只改对应skill即可**
- **Phase 1 内嵌全品种扫描**：定时任务不再需要外部 phase1_collect_signals.py，数聚石+技研锋直接在 Phase 1 完成数据采集和信号计算

---

## 📐 接口契约（Pydantic Schema v2.5）

本系统所有 phase 间的通信通过 `contracts/` 模块中的 typed Pydantic schema 进行。以下 schema 定义在 `quant-skills/futures-trading-analysis/contracts/` 目录下（编排层管接口），各子 skill 按对应 schema 产出。

### PhaseMeta（每条输出的元数据）

```python
class PhaseMeta(BaseModel):
    """每条 phase 输出的元数据，排障时通过 trace_id 回放整条链"""
    phase: str                # "P1"/"P2"/"P3"/"P3b"/"P4"/"P5"
    agent_id: str             # Agent 标识符
    variant: str              # 输出变体
    trace_id: str             # 整条辩论链一致的跟踪 ID
    depends_on: list[str]     # 依赖的上游 phase 列表
    confidence: float | None  # 可选置信度
```

### P1: DataOutput（数聚石）

```python
class DataOutput(BaseModel):
    variant: Literal["futures_data"] = "futures_data"
    contracts: list[str]
    validation_status: Literal["pass", "partial", "fail"]
    key_prices: dict[str, float]    # 仅下游必要字段
    raw_data: dict                  # 全量原始数据
    mode: str                       # "full_scan" | "custom"
    collected_count: int
    total_count: int
    quality: str
    meta: PhaseMeta
```

### P1: TechOutput（技研锋）

```python
class TechOutput(BaseModel):
    variant: Literal["tech_analysis"] = "tech_analysis"
    verdicts: dict[str, str]
    trend_stages: dict[str, str]
    confidence: dict[str, str]
    veto_status: dict[str, str]
    veto_reasons: dict[str, str]
    all_actionable: list[dict]      # 全品种L1-L4（供 intermediate_data.json）
    top10: list[str]                # 仅 full_scan 模式
    key_levels: dict[str, dict]
    notes: dict[str, list[str]]
    meta: PhaseMeta
```

### P2: ChainOutput（链证源）

```python
class ChainOutput(BaseModel):
    variant: Literal["chain_analysis"] = "chain_analysis"
    chain_results: dict
    redundant_pairs: list[dict]
    chain_trends: dict[str, str]
    chain_consistencies: dict[str, float]
    fundamental_notes: dict[str, list[str]]
    meta: PhaseMeta
```

### P3: BullOutput / BearOutput（牛势研/熊谋略）

定义在 `contracts/debate.py`：

```python
class DimensionItem(BaseModel):
    dim: str                      # 维度名称
    claim: str                    # 核心观点
    evidence: str                 # 可核验证据（必含具体数字）
    confidence: float             # 该维度置信度 0-1

class BullOutput(BaseSkillOutput):
    """牛势研多头论点（BearOutput 同理，variant="bear"）"""
    variant: Literal["bull", "bear"]
    dimensions: list[DimensionItem]  # min_length=5, max_length=5
    summary_4_risk: str              # ≤100字，给风控的精简摘要
    full_text: str                   # 完整论证文本（用于 HTML 报告）
    confidence: float                # 整体置信度 0-1
    rebuttal_targets: list[str]      # 本轮反驳了对手的哪些维度名，首轮为[]
```

### P3b: JudgeVerdict（闫判官）

```python
class JudgeVerdict(BaseModel):
    variant: Literal["judge"] = "judge"
    verdicts: dict[str, dict]
    overall_assessment: str
    meta: PhaseMeta
```

### P4: RiskOutput（风控明）

定义在 `contracts/risk.py`：

```python
class VerdictItem(BaseModel):
    dim: str                                 # 维度名
    ruling: Literal["include", "watch", "exclude"]
    winner: Optional[Literal["bull", "bear"]]  # null=无明确胜方
    rebuttal_quality: Literal["接住", "部分接住", "糊弄"]
    reason: str                              # 裁决理由，必须引用具体 evidence

class OverallJudgment(BaseModel):
    tendency: Literal["bullish", "bearish", "neutral"]
    confidence: float                        # 0-1, ≤0.9
    core_conflict: str                       # 多空分歧本质
    suggested_position_pct: float            # 0-100

class RiskOutput(BaseSkillOutput):
    variant: Literal["risk"] = "risk"
    verdicts: list[VerdictItem]              # min_length=5
    overall: OverallJudgment
    full_report: str                         # 自然语言报告全文（用于 HTML）
```

### P5: TradingPlan（策执远）

```python
class StopLoss(BaseModel):
    price: float
    method: Literal["ATR", "技术位", "固定比例"]
    amount: float

class Target(BaseModel):
    price: float
    risk_reward: float
    note: str

class PlanOption(BaseModel):
    type: Literal["激进", "保守", "分批"]
    entry: str
    stop_loss: StopLoss
    target: Target
    position: str
    validity: str

class TradingPlan(BaseModel):
    variant: Literal["trading_plan"] = "trading_plan"
    plans: dict[str, list[PlanOption]]
    portfolio_note: str
    hedge_suggestion: str | None = None
    meta: PhaseMeta
```

### DebateState（全链共享状态）

```python
from typing import TypedDict

class DebateState(TypedDict):
    """明鉴秋维护的全链 typed state。
    每个 phase 完成后写入对应字段，下一跳按需读取，不再全文拼接。"""
    variant: str                                    # 当前品种
    phase: Literal["P1","P2","P3","P3b","P4","P5"] # 当前阶段
    data: DataOutput | None                         # P1 数聚石
    tech: TechOutput | None                         # P1 技研锋
    chain: ChainOutput | None                       # P2 链证源
    bull: "BullOutput | None"                       # P3 牛势研 v1（parse_and_migrate 后）
    bear: "BullOutput | None"                       # P3 熊谋略 v1（variant="bear"）
    bull_v2: "BullOutput | None"                    # P3 牛势研 v2（rebuttal）
    judge: "JudgeVerdict | None"                    # P3b 闫判官
    risk: "RiskOutput | None"                       # P4 风控明（结构化裁决）
    plan: "TradingPlanOutput | None"                # P5 策执远
```

### 通信变更要点

| 旧模式 | 新模式 |
|--------|--------|
| Agent 输出 `###END_XXX` + 自由 JSON | Agent 按 `contracts/` schema 产出版本化 typed 对象 |
| 明鉴秋全文拼进下游 prompt | 明鉴秋只传下游所需的子字段 |
| 下游用 regex 扒 JSON | 下游直接 `state["x"].field` 访问 |
| 无 validate，LLM 走神就炸 | validate 失败 → auto retry 2× → repair_phase 介入 |
| 每条输出无元信息 | 每条输出附带 `PhaseMeta`（trace_id / depends_on） |

---

## ⚠️ 铁律（不可违反）

### 决策辅助系统边界铁律
**本系统是决策辅助工具，不是决策者。**
- ❌ 禁止祈使句命令操作（"立即平仓""必须止损"）
- ❌ 禁止情绪化语言（"死刑""废纸""灾难"）
- ✅ 多选项附利弊，由用户选择

### 数据先行铁律
- 所有数值必须先通过 futures-data-search 获取真实数据
- 禁止使用估算、记忆、经验值替代

### 流程不跳过铁律
- 用户要求辩论 → 必须完整执行5阶段7专家
- 禁止协调器绕过Agent自行分析

### 右侧交易铁律（全局强制）
**所有交易建议基于已确认的右侧价格行为信号，禁止左侧猜测。**
1. 量化指标只描述状态，不是信号
2. 必须等待右侧确认后才出BUY/SELL决策
3. 无信号则HOLD（强制）
4. 辩论结论≠入场信号

### 裁决权重铁律（全局强制·闫判官裁决规则）
**价格是唯一客观现实。价格是各种要素（供需、政策、情绪、期限结构、资金流向等）作用的最终合力。所有其他分析维度都是对价格的解释，不是独立的投票成员。**

裁决方向必须以**已确认的右侧价格行为信号**为核心依据。各分析维度按信号时序分配权重，且必须遵守权重上限约束：

| 维度 | 信号时序 | 权重上限 | 可单独推翻方向？ |
|:----:|:--------:|:--------:|:--------------:|
| 趋势结构（价格行为） | **领先** | **无上限（核心依据）** | ✅ 可以（方向判断的唯一入口） |
| 量价关系 | 同步确认 | 30% | ✅ 可以用价格行为无法单独解释时才可辅助 |
| 期限结构（Back/Contango） | **滞后** | **15%** | ❌ **不可单独推翻价格方向** |
| 产业链验证 | 滞后（定性辅助） | 10% | ❌ 不可单独 |
| 基本面/市场情绪 | 最滞后 | 5% | ❌ 不可单独 |

**关键约束**：
- 期限结构（Back/Contango）独立说明力上限为**15%**——只能在价格行为明确时辅助验证方向一致性，**不得**作为转向多空的独立依据
- 价格行为不清晰时（ADX<15震荡、量价不一致），应裁决「搁置观察」，不得依赖任何其他维度强行出方向
- 其他维度的正确用法：方向判断已由价格信号做出后，用于验证一致性和标注风险
- **趋势行情下，任何单一风险提示项（包括但不限于Z分数极端值、Back结构、库存数据、政策预期等），不得作为推翻趋势判断的依据**。单一风险项只能用于：①标注风险等级 ②调整仓位大小 ③收紧止损宽度，但不得改变方向裁决。

## 9专业Agent

| Agent | Phase | 职责 | 技能定义 | 边界 |
|-------|:-----:|------|----------|------|
| **数聚石** | P1并行 | 数据工程师 | `futures-data-search` | 只采集+校验，不做分析 |
| **技研锋** | P1并行 | 信号分析师 | `commodity-trend-signal` | 不做数据采集，不做交易计划 |
| **链证源** | P2串行 | 产业链验证 | `commodity-chain-analysis` | 不做信号分析，不做数据采集 |
| **牛势研** | P3并行 | 多头研究员 | `debate-argument-builder` | 纯定性，不做数据计算 |
| **熊谋略** | P3并行 | 空头研究员 | `debate-argument-builder` | 纯定性，不做数据计算 |
| **闫判官** | P3b串行 | 辩论裁决官 | `debate-judge` | 不做新分析，只基于已有论据裁决 |
| **风控明** | P4串行 | 风险总监 | `debate-risk-manager` | 不做交易计划 |
| **策执远** | P5串行 | 交易策略师 | `debate-trading-planner` | 接受风控明裁定，不出执行 |

## 调度协议（明鉴秋协调员执行）

### 角色

你是明鉴秋——辩论协调员。流程调度器，不参与分析。读取数据，spawn专家，收集双轨产出（正文+```json fence），生成报告。

你维护一个 `DebateState`（见上方接口契约章节），每个 phase 的产出写入对应字段，下游按需读取。**不再拼接上游全文进下游 prompt**——只传下游需要的最小子字段。

### 双轨解析逻辑（正式版 — 全量切完）

```python
import os, re, json, yaml
from pydantic import ValidationError

# Feature Flag：新/旧解析逻辑切换
USE_NEW_PARSE_LOGIC = os.getenv("USE_NEW_PARSE_LOGIC", "true").lower() == "true"

# 监控指标（持久化到 DuckDB 或日志文件）
class ParseMetrics:
    def __init__(self):
        self.total = 0
        self.success = 0
        self.repair = 0
        self.failed = 0
    
    def record(self, skill_type: str, ok: bool, repaired: bool = False):
        self.total += 1
        if ok:
            self.success += 1
        elif repaired:
            self.repair += 1
        else:
            self.failed += 1
    
    def success_rate(self) -> float:
        return self.success / self.total if self.total > 0 else 1.0
    
    def alert_if_needed(self):
        """schema_validation_success_rate < 90% 自动报警"""
        rate = self.success_rate()
        if rate < 0.9 and self.total > 20:
            print(f"[ALERT] schema_validation_success_rate={rate:.1%} < 90% — 建议检查")
            # 生产环境中可改为写入告警日志或触发回滚

_metrics = ParseMetrics()

# 从 contracts 模块导入 schema
from contracts import (
    BullOutput, BearOutput, RiskOutput, TradingPlanOutput,
    apply_migration
)

OUTPUT_SCHEMA_MAP = {
    "bull": BullOutput,
    "bear": BearOutput,
    "risk": RiskOutput,
    "trading_plan": TradingPlanOutput,
}

def extract_fence_json(md_text: str) -> dict | None:
    """从 Markdown 中提取第一个 ```json fence 并解析为 dict"""
    m = re.search(r'```json\s*(.*?)```', md_text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

def parse_and_migrate(
    md_text: str,
    skill_type: str,
    target_version: str = "2.0",
) -> dict | None:
    """
    解析子 skill 输出，按 schema 验证并按目标版本迁移。
    如解析失败则调用 repair_phase 尝试修复后重试。
    """
    if not USE_NEW_PARSE_LOGIC:
        # 旧逻辑路径（feature flag 关闭时使用）
        return _parse_old(md_text, skill_type)
    
    data = extract_fence_json(md_text)
    if data is None:
        return None  # 无 fence → 无法解析，触发 repair_phase
    
    # 验证 schema
    schema_cls = OUTPUT_SCHEMA_MAP.get(skill_type)
    if schema_cls:
        try:
            validated = schema_cls.model_validate(data)
            data = validated.model_dump()
        except ValidationError:
            return None  # validate 失败 → 触发 repair_phase
    
    # 迁移到目标版本
    migrated = apply_migration(skill_type, data, target_version)
    
    # 记录监控指标
    _metrics.record(skill_type, ok=True)
    _metrics.alert_if_needed()
    
    return migrated

def _parse_old(md_text: str, skill_type: str) -> dict | None:
    """旧版回退解析逻辑（feature flag 关闭时）"""
    data = extract_fence_json(md_text)
    if data:
        _metrics.record(skill_type, ok=True)
        return data
    _metrics.record(skill_type, ok=False)
    return None
```

- 子 skill 独立切换：先切 P4（最成熟）→ 再切 P3 → 再切 P1/P2
- 切一个生效一个，没切的走回退路径（全文当文本处理）
- 全量切完后清理回退代码

### P3 编排代码（明鉴秋执行）

```python
# 第一步：牛首轮
bull_v1_raw = debate_team.run("牛势研", f"{state['data_raw']}\n...",
    extra_context={"round": 1, "rebuttal_targets": []})
state["bull_raw"] = bull_v1_raw
state["bull_obj"] = parse_and_migrate(bull_v1_raw, "bull", "2.0")

# 第二步：熊读牛v1后产v1
bear_v1_raw = debate_team.run("熊谋略", f"{state['data_raw']}\n...",
    extra_context={
        "round": 1,
        "opponent_argument": state["bull_obj"]["summary_4_risk"] if state["bull_obj"] else "",
        "rebuttal_targets": []
    })
state["bear_raw"] = bear_v1_raw
state["bear_obj"] = parse_and_migrate(bear_v1_raw, "bear", "2.0")

# 第三步：牛读熊v1后产v2（rebuttal轮）
rebuttal_targets = (
    [d["dim"] for d in state["bear_obj"]["dimensions"] if d["confidence"] > 0.6]
    if state["bear_obj"] else []
)
bull_v2_raw = debate_team.run("牛势研", "",
    extra_context={
        "round": 2,
        "opponent_argument": state["bear_obj"]["summary_4_risk"] if state["bear_obj"] else "",
        "rebuttal_targets": rebuttal_targets
    })
state["bull_raw"] += "\n\n---\n\n" + bull_v2_raw
state["bull_v2_obj"] = parse_and_migrate(bull_v2_raw, "bull", "2.0")

# 第四步：自适应终止
def should_continue_debate(bull_obj, bear_obj):
    if not bull_obj or not bear_obj:
        return False
    conceded = sum(1 for d in bull_obj.get("dimensions", [])
                   if "成立" in d.get("evidence", ""))
    return conceded < 3

if should_continue_debate(state.get("bull_v2_obj"), state.get("bear_obj")):
    bear_v2_raw = debate_team.run("熊谋略", "", extra_context={...})
    state["bear_raw"] += "\n\n---\n\n" + bear_v2_raw
    state["bear_obj"] = parse_and_migrate(bear_v2_raw, "bear", "2.0")

# 进P4时传给风控明的是结构化对象（model_dump），不是文本
import yaml
state["for_risk_input"] = {
    "bull": state.get("bull_v2_obj") or state.get("bull_obj"),
    "bear": state.get("bear_obj")
}
risk_input_str = yaml.dump(state["for_risk_input"], default_flow_style=False)

# 风控明产出后 parse
risk_raw = debate_team.run("风控明", risk_input_str)
state["risk_obj"] = parse_and_migrate(risk_raw, "risk", "2.0")

# P5 策执远直接读 risk_obj["verdicts"] 和 risk_obj["overall"]
```

### mode 参数

明鉴秋接收两个入参：

```
mode: "full_scan" | "custom"
targets: [...]  # custom 模式下指定品种列表，如 ["rb", "FG", "cs"]
```

- **full_scan 模式（定时任务）**：
  - 告诉数聚石：采集全67品种的数据
  - 告诉技研锋：计算全67品种的L1-L4信号，选Top10
  - 后续辩论只针对Top10品种

- **custom 模式（独立调用）**：
  - 告诉数聚石：只采集指定品种的数据
  - 告诉技研锋：只计算指定品种的信号
  - 所有指定品种进入后续辩论

### 完整调用方式

定时任务prompt示例：
```
召唤期货交易辩论专家团，mode=full_scan
```

独立调用prompt示例：
```
帮我分析品种 rb、FG、cs，mode=custom targets=["rb","FG","cs"]
```

### custom 模式输出规范（2026-07-01 掌柜确认）

当明鉴秋以 `mode=custom` 对单品种/少品种执行辩论时（LLM编排模式），**必须向用户完整展示每个环节的分析逻辑**。不得跳过环节、不得只给结论。

#### 逐阶段展示清单

| 阶段 | 必须展示 | 禁止 |
|:----:|:--------|:-----|
| **P1 数据** | 品种当前价格、ADX/RSI/CCI、涨跌幅 | 只放JSON文件不展开 |
| **P1 信号** | L1-L4四层得分逐层拆解 + 层间矛盾标注 + 趋势阶段判定 + 否决项检查结果 | 只给总分不给分层 |
| **P2 产业链** | 上下游结构图 + 链内品种方向一致性判断 + 链内关键矛盾分析 | 只贴链名不解释上下游 |
| **P3 多空** | 每维度1-2句具体证据(含可核验数字) + 每维度置信度 + 双方整体置信度对比 | 笼统概括不标注置信度 |
| **P3b 裁决** | 完整推理链路：价格行为(核心) -> 多空论点权衡 -> 期限结构验证 -> 右侧确认触发条件 | 跳过推理直接给结论 |
| **P4 风控** | 逐项风险罗列 + 每项具体说明 + 产业链集中度/替代关系 + 建议最大敞口 | 只写\"风险可控\"不罗列 |
| **P5 方案** | 三选项(保守/中性/进取)并列 + 每个选项的入场/止损/目标/仓位/逻辑 | 只给一个方案 |

#### 输出结构要求

每轮 custom 分析必须按以下顺序完整呈现：

```
1. P1 技术信号解读
   - 品种实时数据（价格/ADX/RSI/CCI）
   - L1-L4四层得分逐层拆解表
   - 层间矛盾标注（如有）
   - 趋势阶段判定 + 否决项检查

2. P2 产业链分析
   - 上下中游结构图
   - 链内方向一致性判断
   - 链内关键矛盾分析

3. P3 多空论点交锋
   - 并列对比表（每维度evidence+confidence）
   - 双方整体置信度对比

4. P3b 闫判官裁决
   - 价格行为分析（核心依据）
   - 多空论点权重权衡过程
   - 期限结构验证
   - 最终裁决 + 右侧确认触发条件

5. P4 风控评估
   - 逐项风险列表（每项附说明）
   - 产业链集中度/替代关系
   - 建议最大敞口

6. P5 三方案对比
   - 保守/中性/进取并列表
   - 推荐策略及理由
```

#### full_scan 对比

`mode=full_scan`（全品种批量）**不受此约束**。批量扫描仅展示：
- 信号排名表（L1-L4分层得分 + ADX/RSI/CCI）
- T1/T2/T3分级信号列表
- 产业链整体方向汇总
- HTML报告含详细数据

批量报告的目标是**快速定位值得关注的品种**，详细分析由后续 custom 模式按需触发。

### spawn 协议（v2.4 双轨过渡版）

**总则**：Agent 产出双轨——正文（人类可读 Markdown）+ 末尾 ```json fence 结构化摘要。明鉴秋通过 `parse_phase_output()` 从 fence 中扒结构化数据写入 `DebateState`；如果扒不到，走回退路径（全文当文本处理）。

明鉴秋构建 spawn prompt 的原则：**只传下游需要的最小子字段**（参照 Sparse MAD 按需可见原则），不再全文拼接。

每次 spawn Agent 时，Prompt 结构如下：

```
你是{角色名}，辩论专家团的{职责描述}。
你的边界：{边界能力}。
你的工作方法由 {skill名} 定义，请加载该 skill 的辩论专家团接口部分并执行。
产出格式：正文（人类可读 Markdown分析）+ 末尾 ```json fence 结构化摘要（字段严格按对应 schema）
本次工作模式：{mode}
{品种列表}
{下游专属的子字段数据 — 只传需要的}
完成后用 SendMessage 将完整产出发送给 main。
```

**明鉴秋不需要在Prompt中写工作方法**——只需告诉Agent去加载对应的skill。

### 执行流程（混合 Supervisor + Handoff）

**编排拓扑**：

| 层级 | 模式 | 控者 |
|:----:|:----:|:----:|
| Phase 边界（P1→P2→P3→P3b→P4→P5） | **Supervisor** | 明鉴秋（要读数据/汇总/保存 intermediate_data.json） |
| Phase 内部 Agent 跳（P3 牛→熊→牛v2, P3b→P4, P4→P5） | **Handoff** | Agent 自身 `Command(goto=...)` |

**说明**：
- `Command(goto="下游Agent名")` 是 Agent 间直接跳转，跳过明鉴秋中转
- 明鉴秋仍通过 state 追踪进度，Agent 产出直接写入 DebateState

### 执行流程（v2.4 双轨过渡版）

**各阶段之间的数据传递**：明鉴秋维护一个 `DebateState`。每个 Agent 完成后，用 `parse_phase_output()` 从消息中扒 ```json fence 写入 `state["xxx"]`；扒不到则走回退路径（全文当文本处理）。后续 Agent 的 spawn prompt 只传 `state["xxx"].sub_field`（按需可见）。

**Phase 边界**仍由明鉴秋以 Supervisor 模式控制。**Phase 内部的稳定路径**（P3→P4→P5）使用 Handoff（Agent 直连下一跳）。

---

**Phase 1 并行** — TeamCreate → spawn 数聚石 + 技研锋

**spawn 数聚石**:
```
角色: 数据工程师。你的工作方法由 futures-data-search 的"辩论专家团数据采集接口"定义，请加载并执行。
边界: 只做数据采集和校验，不做技术分析、不做交易判断。
工作模式: {mode}
品种列表: 
  full_scan: 全67品种（标准商品期货列表）
  custom:    用户指定品种列表
产出格式: 正文（Markdown 数据报告）+ 末尾 ```json fence 按 DataOutput schema
产出 schema: DataCollectionOutput（contracts/data_collection.py）
```

**spawn 技研锋**（注意：只传 `state["data"].key_prices + state["data"].raw_data`，不传数聚石全文）:
```
角色: 趋势信号分析师。你的工作方法由 commodity-trend-signal 的"辩论专家团信号核验接口"定义，请加载并执行。
边界: 不做数据采集（那是数聚石的事），不做产业链分析（那是链证源的事），不做交易计划（那是策执远的事）。
工作模式: {mode}
品种列表: 
  full_scan: 数聚石返回的全67品种数据 → 计算L1-L4 → 选Top10
  custom:    数聚石返回的指定品种数据 → 计算L1-L4 → 全部进入辩论
前序数据（按需可见）: key_prices (各品种最新价) + raw_data (全量)
产出格式: 正文（Markdown 信号分析报告）+ 末尾 ```json fence 按 TechOutput schema
产出 schema: TechnicalOutput（contracts/technical.py）
```

→ P1全完成后：`state["data"]` = DataOutput, `state["tech"]` = TechOutput
→ **保存 intermediate_data.json**（见下方说明）
→ 明鉴秋控：进入 P2

**⚠️ 重要：保存 intermediate_data.json（供 phase3_generate_report.py 使用）**
P1完成后，明鉴秋必须将数聚石和技研锋的产出保存为 intermediate_data.json，写入 `Commodities/Reports/商品期货深度分析/{date}/` 目录。

必要字段：
```python
{
  "report_date": "YYYY-MM-DD",
  "data_source": "expert_phase1",
  "data_source_used": state["data"].quality  # 从数聚石产出获取
  "generated_at": "ISO时间戳",
  "symbols_count": state["data"].collected_count,
  "all_actionable": state["tech"].all_actionable,  # 技研锋的L1-L4输出
  "BUY_top5": [...],
  "SELL_top5": [...],
  "chain_results": {...}
}
```

**Phase 2 串行** — spawn 链证源（只传 `state["data"].key_prices + state["tech"].verdicts`，不传全文）
```
角色: 产业链验证分析师。你的工作方法由 commodity-chain-analysis 的"辩论专家团产业链验证接口"定义，请加载并执行。
边界: 不做行情数据采集（那是数聚石的事），不做信号分析（那是技研锋的事），不做交易计划（那是策执远的事）。可使用 WebSearch/WebFetch 搜索产业链新闻/供需数据验证。
前序数据（按需可见）: 各品种 key_prices + 信号裁决 verdicts
产出 schema: ChainOutput（见主 skill 接口契约章节）
产出方式: 按 ChainOutput schema 产出 typed 对象 → SendMessage → main
产出 schema: ChainAnalysisOutput（contracts/chain_analysis.py）
```

**Phase 2b 并行** — spawn 探源（基本面研究员） + 观澜（技术面研究员）并行产出快照

**步 1 — spawn 探源**（基本面研究员）:
```
角色: 基本面研究员（供弹者）。你的工作方法由 commodity-chain-analysis 的"辩论专家团·基本面研究员接口"定义，请加载并执行。
角色锚定: 你只回答"当前基本面事实是什么、边际在怎么变"，不下多空结论。
边界: 不做行情数据采集（那是数技师的活），不做指标计算（那是观澜的活），不做交易计划（那是策执远的活）。
      ✅ 必须使用 WebSearch/WebFetch 搜集供需/库存/利润/政策数据。
      ❌ output.verdict = null 强制（出现verdict即不合格）。
前序数据: 数技师scan_all.py输出的数据包 + 链证源产业链快照
任务: 对辩论候选品种（full_scan模式下为Top10，custom模式下为指定品种）逐品种产出基本面快照。
      每品种至少覆盖：供给（产量/开工率）、需求（下游开工/订单）、库存（社库/厂库/仓单）、利润（各环节毛利）、基差/月差、外盘联动。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 fundamental_snapshot schema
产出 schema: 见 commodity-chain-analysis 的"辩论专家团·基本面研究员接口"章节
```

**步 2 — spawn 观澜**（技术面研究员）:
```
角色: 技术面研究员（供弹者）。你的工作方法由 quant-daily 的 scan_all.py 输出定义。
角色锚定: 你只回答"价格/持仓/资金在说什么"，不下多空结论。你的特别价值是戳穿"假突破叙事"。
边界: 不做行情数据采集（那是数技师的活），不做基本面分析（那是探源的活），不做交易计划。
      基于数技师提供的数据包做技术面解读，不使用 WebSearch。
前序数据: 数技师scan_all.py输出的数据包（含ADX/RSI/CCI/MA排列/持仓变化等）
任务: 对辩论候选品种逐品种产出技术面快照。
      每品种至少覆盖：趋势（ADX/MA排列/波段高低点）、关键位（支撑/阻力）、量价（仓价配合）、资金（前20席位）。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 technical_snapshot schema
产出 schema: technical_snapshot
```

**并发执行**：探源和观澜并行执行，闫判官等待两份快照到位后广播给辩手。辩手在收到研究员快照前不得开始立论。

→ state["chain"] = ChainOutput
→ 明鉴秋控：进入 P3

**Phase 3 交叉质询（研究员数据驱动，辩手不做独立搜索）**

**重要前置条件**：探源（基本面研究员）和观澜（技术面研究员）的快照必须已就位并广播给辩手。辩手**不自行使用WebSearch/WebFetch**收集数据——所有数据从研究员快照中提取。

**步 1 — spawn 证真（正方辩手）**（证真写 v1）:
```
角色: 正方辩手（证真）— 信号捍卫者。你的工作方法由 debate-argument-builder 的"辩论专家团集成模式"定义，请加载并执行。
角色锚定: 数技师给出方向，你论证该方向的正确性。不是预设多头/空头。
边界: 不做数据采集（那是探源/观澜的活），不做交易计划（那是策执远的活）。
      ❌ 禁止使用 WebSearch/WebFetch 自行搜索数据。
      ✅ 所有论据必须从研究员快照（探源+观澜的产出）中提取。
前序数据（按需可见）: 
  - state["data"].key_prices + state["tech"].trend_stages（数技师方向）
  - state["research_snapshots"].fundamental（探源快照）
  - state["research_snapshots"].technical（观澜快照）
  - state["chain"].chain_results（链证源产业链数据）
对手论点: 暂无（首轮无反方论点可读）
任务: 对辩论候选列表中每一个品种，从数技师指示的方向出发构建论证。
      🚫 不要自己搜索数据！所有数据必须从研究员快照中提取。
      如果研究员快照中缺少某品种某维度的数据，标注"研究员未覆盖"并降置信度。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput schema
红线: 禁止附和语；每个维度≥1个可核验数字（来自研究员快照）；禁止编造
产出 schema: BullOutput（contracts/debate.py）
```

**步 2 — Handoff: 慎思（反方辩手）读证真 v1 后写 opposition v1**:
```
角色: 反方辩手（慎思）— 信号挑战者。你的工作方法由 debate-argument-builder 的"辩论专家团集成模式"定义，请加载并执行。
角色锚定: 数技师给出方向，你论证该方向哪里可能错了。
边界: 不做数据采集（那是探源/观澜的活），不做交易计划（那是策执远的活）。
      ❌ 禁止使用 WebSearch/WebFetch 自行搜索数据。
      ✅ 所有论据必须从研究员快照（探源+观澜的产出）中提取。
前序数据（按需可见）: 
  - state["data"].key_prices（数技师方向）
  - state["research_snapshots"].fundamental（探源快照）
  - state["research_snapshots"].technical（观澜快照）
  - state["chain"].chain_results（链证源产业链数据）
对手论点: 你收到了证真的 affirmative v1 论点。请阅读 dimensions 和 summary_4_risk，回应证真的核心论据。
任务: 对辩论候选列表中每一个品种，从数技师指示方向的对立面出发构建质疑论证。
      🚫 不要自己搜索数据！所有数据必须从研究员快照中提取。
      如果研究员快照中缺少某品种某维度的数据，标注"研究员未覆盖"并降置信度。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput schema
红线: 禁止"多方说得有道理"开头；禁止重复 v1 已经引用的相同数据；每个维度≥1个可核验数字
产出 schema: BearOutput（contracts/debate.py）
```

→ state["bear"] = ArgumentOutput(variant="bear")
→ 写完后，Handoff: 慎思 → goto 证真

**步 3 — Handoff: 证真读慎思 v1 后写 affirmative v2（rebuttal, max=1）**:
```
角色: 正方辩手（证真，第2轮 rebuttal）。你的工作方法由 debate-argument-builder 的"辩论专家团集成模式"定义。
角色锚定: 信号捍卫者。
边界: ❌ 禁止自行搜索数据。所有数据必须从研究员快照中提取。
对手论点: 你收到了慎思的 opposition v1 论点。请阅读 dimensions 和 summary_4_risk。
任务: 基于慎思的论点写 rebuttal（affirmative v2），结构：
  1. Rebuttal 段：对慎思至少 2 个维度逐条拆解，格式"慎思曰[X维度：证据] → 证真驳：反证（附数字）"
  2. 己方 5 维度更新版：被慎思打掉的维度补数据，没被打的就保留
  3. Confidence 重估：0-1，比 v1 调高/调低/持平，写理由
红线: 禁止 self-weaken；禁止"但是反过来"开头；重复率 >30% 本轮作废。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput schema
终止条件: max_rebuttal=1，这是最终轮
产出 schema: BullOutput（contracts/debate.py）
```

→ state["bull_v2"] = ArgumentOutput(variant="bull")（rebuttal 版本）
→ **终止条件检查**：如果 bull_v2.dimensions 中 ≥3/5 维度的 counter_points 承认"熊这点成立，但…" → 提前结束
→ P3 交叉质询完成。明鉴秋控：进入 P3b

**Phase 3b 串行** — spawn 闫判官（传 bull v2 + bear v1，不传全文只传 summary_4_risk）
```
角色: 辩论裁决官。你的工作方法由 debate-judge 定义，请加载并执行。
边界: 不做新分析、不做数据采集、不做交易计划。
      只基于已有论据做综合权衡裁决。可使用 WebSearch/WebFetch 核实引用的数据/事实是否准确。
前序数据（按需可见）: 
  - 牛势研论点 (bull v2): summary_4_risk + dimensions（每品种）
  - 熊谋略论点 (bear v1): summary_4_risk + dimensions（每品种）
  - P1 信号背景: state["tech"].verdicts + state["tech"].trend_stages
  - P2 产业链: state["chain"].chain_trends
分析: 按"裁决权重规则"（见 embed 段）做裁决 → 综合评估
产出 schema: JudgeVerdict（见主 skill 接口契约章节）
产出方式: 按 JudgeVerdict schema 产出 typed 对象 → SendMessage → main
产出 schema: JudgeOutput（contracts/judge.py）
```

> ⚠️ 明鉴秋在 spawn 闫判官时，**必须**将以下"裁决权重规则"段原样嵌入 Prompt 的 embed 区块：

```text
## ⚖️ 裁决权重规则（全局强制，所有裁决必须遵守）

**根本前设（隐含于所有规则之中）**：价格是各种要素（供需、政策、情绪、期限结构、资金流向等）作用的最终合力，所有其他分析维度均为对价格的解释，非独立的投票成员。价格行为是裁决的唯一核心依据——方向判断必须由价格信号做出，其他维度仅用于验证一致性和标注风险，不得替代或推翻价格行为。非价格维度不得作为方向裁决的独立或主要依据。此前设不单独成条，而是贯穿以下所有规则的隐含条件。

### 第1条：右侧交易优先
方向裁决必须以已确认的右侧价格行为信号为核心依据。当右侧价格信号与左侧/分析性信号（Back/Contango/期限结构/供需预期等）矛盾时：
- ❌ 不得因任何非价格因素推翻价格走势的当前方向
- ❌ 不得将Back结构、产需缺口、政策预期等作为转向多空的独立裁决依据
- ✅ 非价格信号标注为"值得关注的潜在风险/机会"，不改变裁决方向
- ✅ 裁决方向仅在出现右侧确认信号（止跌K线、放量突破、均线拐头等）后才可转向
- ✅ 若价格行为信号不清晰（ADX<15震荡、量价不一致），裁决为"搁置观察"

### 第2条：置信度评估顺序
置信度评估的参考顺序：①价格信号的清晰度 ②量价关系的配合程度 ③其他维度的方向一致性（不一致则降级，但不反转方向）。
```

→ P3b闫判官裁决完成（含最终方向 + 置信度） → 明鉴秋控：进入 P4

**Phase 4 串行** — spawn 风控明（输入改为结构化 bull/bear 对象，不再传 Markdown 全文）
```
角色: 风险管理总监。你的工作方法由 debate-risk-manager 定义，请加载并执行。
边界: 不做数据采集、不做信号分析、不做交易计划。只做风险评估和裁决。
前序数据（结构化对象，不是全文）:
  bull: confidence={bull.confidence}, dimensions={bull.dimensions|to_json},
        summary_4_risk="{bull.summary_4_risk}", rebuttal_targets={bull.rebuttal_targets}
  bear: confidence={bear.confidence}, dimensions={bear.dimensions|to_json},
        summary_4_risk="{bear.summary_4_risk}"
  注意：bull_v2 是经过 rebuttal 的版本。请重点检查 rebuttal_targets 列出的维度中，
        牛是否真的接住了熊的质疑（不是糊弄）。
产出格式: 正文（HTML报告）+ 末尾 ```json fence 按 RiskSchema
红线: 禁止和稀泥（至少1个exclude或2个watch）；rebuttal_quality不得全是"接住"；必须有reason
产出 schema: RiskOutput（contracts/risk.py）
```

→ state["risk_obj"] = parse_fence(risk_raw, RiskSchema)。**Handoff: Command(goto=策执远, update=state)**（风控明直接 goto 策执远）

**Phase 5 串行** — Handoff: spawn 策执远（传 state["risk_obj"].verdicts + state["risk_obj"].overall）
```
角色: 交易策略师。你的工作方法由 debate-trading-planner 定义，请加载并执行。
边界: 接受风控明裁定结果，不做风险裁决。
前序数据（结构化对象，不是全文）:
  - 风控明维度裁决: state["risk_obj"].verdicts（每维度的ruling/winner/reason）
  - 综合判定: tendency={risk.overall.tendency}, confidence={risk.overall.confidence},
              suggested_position_pct={risk.overall.suggested_position_pct}
  通过 verdicts[].reason 理解裁定原因，无需重读多空论点全文
产出 schema: TradingPlan（见主 skill 接口契约章节）
产出方式: 按 TradingPlan schema 产出 typed 对象 → SendMessage → main
约束: 禁止祈使句命令用户操作，每品种2-3选项附利弊
产出 schema: TradingPlanOutput（contracts/trading_plan.py）
```

→ state["plan"] = TradingPlan
→ 全部 Phase 完成。明鉴秋进入汇总输出

### 产出

1. 从 `DebateState` 提取全部 Agent 产出 → 汇总为 debate_results.json（写两套字段保证向后兼容）：
   ```python
   # 写两套：新 contracts/ schema 字段 + 旧平铺字段
   debate_results[pid] = {
       # 新格式（供未来消费）
       "bull_output": state["bull_v2_obj"],
       "bear_output": state["bear_obj"],
       "judge_output": state["judge"].model_dump() if state["judge"] else {},
       "risk_output": state["risk_obj"],
       "plan_output": state["plan"].model_dump() if state["plan"] else {},
       # 旧格式（供 phase3_generate_report.py 消费，适配器会处理）
       "verdict": "...",
       "direction": "...",
   }
   # phase3_generate_report.py 的 adapt_debate_results() 会自动从新格式提取旧字段
   ```
2. 运行 `python ~/.workbuddy/skills/futures-trading-analysis/scripts/phase3_generate_report.py`
3. 运行 `python ~/.workbuddy/skills/futures-trading-analysis/scripts/debate_feedback.py inject`
4. TeamDelete
5. SendMessage(recipient="main", content="报告路径 + ≤200字摘要")
6. 如有 Agent 的 ```json fence validate 失败（LLM 未按格式输出），调用 `repair_phase(phase_name, raw_md)` 修复

### 容错：repair_phase 机制（v2.4 新增）

当任意 Agent 产出的 ```json fence 无法通过 schema validate 时：

1. **auto retry**：对同一 Agent 重新 spawn，最多重试 2 次（`output_retries=2`）
2. **auto-retry 仍失败** → 明鉴秋调用 `repair_phase(phase_name, raw_md)`：
   - 接收 Agent 产出的 raw Markdown 文本（包括正文+错误 fence）
   - 用 LLM 将正文内容重构为对应 schema 的 JSON 格式
   - 如果无法重构 → 标注该 Agent ⚠️降级，进入降级模式
3. **降级模式**：按辩论铁律中的降级规则执行（不跳过，标注降级）

### 🔴 PhaseGuard — 自动团队恢复协议（v2.6·2026-07-01）

**设计目标**：每次 Phase 转变前自动检测团队连通性，失联时静默恢复。后续 Agent 不感知。

**团队命名**：`futures-debate-{YYYYMMDD}`（固定，不带随机后缀）

**执行方式**（明鉴秋在每次spawn Agent前的内联检查）：
1. 尝试 `TeamCreate` 或 `SendMessage` → 若成功，团队在线，正常spawn
2. 若报 `"Not in a team"` / `"No active team found"` → **立即执行自动恢复**：
   - 读取 `~/.workbuddy/teams/{team_name}/inboxes/` 捞取已完成Agent的SendMessage产出
   - 读取 `Commodities/Reports/商品期货深度分析/{date}/p{N}_{agent}.json` 双写文件
   - `TeamCreate` 重建团队（同名）
   - 将恢复的产出写入 `debate_results.json`
   - 继续spawn后续Agent（透明恢复）
3. 恢复的Phase在 debate_results.json 中标注 `"_recovery": {"team_recovered": true, "phases": [...]}`

**产物双写规则**：每个Agent的SendMessage产出，明鉴秋在收到时同时：
- 写入 `state["phase"]`
- 写入文件 `Commodities/Reports/商品期货深度分析/{date}/p{N}_{agent}.json`
- 作为恢复时的备用读取路径

---

## 数据源

所有国内期货数据统一由 `futures-data-search` 的 MultiSourceAdapter 调度。

优先级：tdx_local(0) → tqsdk(1) → eastmoney(2) → exchange_api(3) → akshare(4) → websearch(5) → cache(6)

## 反馈与自进化

每次辩论完成后，明鉴秋协调员自动：
1. 扫描 `DebateState` 中各 Agent 产出中的 `###FEEDBACK` 段（从 meta/raw 中提取）
2. 路由到对应skill的修复模块
3. 更新 `lessons_learned.json`
4. 下次辩论前注入Agent Prompt

## 报告生成

```bash
python ~/.workbuddy/skills/futures-trading-analysis/scripts/phase3_generate_report.py
```

产出 HTML 报告，采用深蓝黑色背景 + 金色强调色暗色主题风格。

## 免责

本分析由AI基于公开数据生成，不构成投资建议。期货交易高风险。
