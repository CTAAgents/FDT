---
name: futures-trading-analysis
version: 3.5.0
description: 期货交易辩论专家团 v5.2 — 三类信号(突破/回踩/跳空)为主信号源→链证源先于闫判官→闫判官筛选三类信号品种全辩论→研究员供弹→证真(慎思)动态正反方交叉质询→策执远出策略→风控审方案。所有三类信号必须辩论，无直接推荐通道。P1只跑三类信号，L1-L4/因子择时由研究员按需调用。
allowed-tools: Read,Bash
agent_created: true
changelog: |
  v3.5.0 (2026-07-07): ADX仅风控不参与评分+Agent输出格式统一+JSON Schema导出+时序通信铁律S01-S05+phase3加载辩论详情+交易方案合并
  v3.3.0 (2026-07-06): P1不再使用--dual。L1-L4和因子择时取消全量计算，研究员按需调用data_interface
  v3.2.1 (2026-07-05): 适配v4.1架构 — 移除量析师引用；更新为数技源三类信号扫描；闫判官自主决定辩论品种与方向；证真/慎思改为从研究员资料中提取论据
  v3.2.0 (2026-07-04): 角色框架重写 — 主框架从多空方向(bull/bear)改为辩论角色(证真/慎思)；统一 schema (ArgumentOutput)；Agent spawn prompt 全部更新；向后兼容旧字段
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
- **下游子 skill**：
  - `quant-daily`（数技师数据管道）
  - `futures-data-technician`（数技师专用封装）
  - `commodity-chain-analysis` v2.13+（基本面研究员接口）
  - `debate-argument-builder`（多/空辩手论点构建）
  - `debate-judge` v2+（裁判主持）
  - `debate-risk-manager` v3+（风控三合一）
  - `debate-trading-planner` v2+（策略师方案合成）
- **版本**：全部 `2.0`（前端按 version 字段路由）
- **解析方式**：`parse_and_migrate()`（见调度协议章节）
- **通信协议**：正文（HTML 报告）+ 末尾 ```json fence 结构化摘要 → `parse_and_migrate` → state

## 架构

```
用户/定时任务 触发辩论
    ↓ (传参 mode + targets)
WorkBuddy 自动化协调器 → spawn 明鉴秋(团队主管)
    ↓
[阶段一] 选题与准备:
  明鉴秋 选定品种+周期+权益 → 通知全员
    ↓
  数技师 scan_all.py --symbols PK,RB → 数据包
    ↓
[阶段二] 辩论全流程（闫判官主持）:
  闫判官 spawn 基本面研究员 + 技术面研究员 → 快照广播
    ↓
  闫判官主持 → 多/空辩手立论→互rebuttal→自由交锋→final
    ↓
  闫判官 判胜负 → 传给策略师
    ↓
[阶段三] 策略合成:
  策略师 合成可执行方案 → 传给风控
    ↓
[阶段四] 风控审核:
  风控 跑杠杆/回撤/叙事质检 → verdict
    ↓ (若red则打回策略师修改，最多1轮)
[阶段五] 决策与归档:
  闫判官 出最终判决
    ↓
  明鉴秋 拍板 execute/hold/rematch
    ↓
  全员 → 归档 → debate_results.json → HTML报告
    ↓
明鉴秋: SendMessage → WorkBuddy → present_files 交付
```

**关键设计**：
- 明鉴秋（团队主管）只做选题和拍板，辩论期不插手
- P2-P4（研究员→辩手→策略→风控）由闫判官全权主持
- 9角色分工：数技师不做分析、研究员不下结论、策略师不改方向、风控不改多空、裁判不站队

---

## 🚫 无胶水代码协议（2026-07-03 掌柜确立·不可违反）

**胶水代码定义**：在业务执行流程中临时编写的、仅用一次的脚本/函数/胶合逻辑。包括但不限于：`phase1_custom_scan.py`、临时数据提取脚本、手工拼接的Agent输出读取代码。

### 根本原则

**零胶水。** 任何需要在执行流程中完成的操作，必须通过已有skill的CLI接口、库函数调用、或Agent spawning来完成。**禁止在运行过程中编写一次性脚本。**

### 三条铁律

#### 铁律1：P1 数据采集必须使用 quant-daily 的 CLI（只跑三类信号，不做dual）

当 `mode=custom` 需要扫描指定品种时：

**数技源**（纯数据采集+三类信号计算，不做分析）：
```bash
python scripts/scan_all.py --symbols PK,RB,B,UR
```

**不再使用 `--dual` 模式。L1-L4和因子择时不是全量信号源**，由研究员（观澜/探源）在P3阶段通过各自的 `data_interface.py` 按需拉取（只计算辩论品种）。

#### 铁律2：Agent 输出必须通过文件持久化读取，不依赖消息路由

Agent的SendMessage路由不可靠（历史教训：2026-07-03团队消息未送达导致手动读收件箱+写胶水脚本）。因此：

1. **产物双写**：每个Agent完成后，必须同时：
   - `SendMessage` 通知协调员（主通道）
   - 写入文件 `Commodities/Reports/商品期货深度分析/{date}/p{N}_{agent}.json`（备用通道）
2. **协调员读取逻辑**（按优先级）：
   ```
   1. 尝试接收 SendMessage → 如有，直接用
   2. 如无消息 → 从 inbox 文件或产物文件中读取
   3. 如都读不到 → 重新 spawn Agent（retry=1）
   4. retry 仍失败 → 直接调用下游 skill 的 Python 库函数，不写胶水脚本
   ```
3. **禁止行为**：编写 `read_agent_output.py`、`parse_inbox.py` 等一次性读取脚本。Agent的产出始终通过双写通道获取。

#### 铁律3：数据溯源纳入自动化流程，不临时写脚本

所有数据溯源信息必须在 P1 阶段由 `scan_all.py` 的输出来记录（已内置 data_manifest 字段），**禁止**事后编写 `data_audit.py` 之类的核查脚本来追补。

如果 `scan_all.py` 的 data_manifest 信息不完整 → 应修改 `scan_all.py` 本身，而不是写一个新脚本。

### Agent工具权限保障

| Agent | 所需工具 | 用途 |
|:------|:---------|:-----|
| futures-datatech（数技师） | Read, Bash, SendMessage | 运行scan_all.py（库函数模式） |
| futures-fundamental-researcher（基本面研究员） | Read, Write, WebSearch, WebFetch, SendMessage | 搜索基本面事实+出快照 |
| futures-technical-researcher（技术面研究员） | Read, Write, WebSearch, SendMessage | 分析量价+出快照 |
| futures-affirmative-debater（正方辩手） | Read, WebSearch, WebFetch, SendMessage | 论证数技师方向的正确性+反驳反方质疑 |
| futures-opposition-debater（反方辩手） | Read, WebSearch, WebFetch, SendMessage | 质疑数技师方向的漏洞+反驳正方论证 |
| futures-judge（裁判/主持） | Read, SendMessage, WebSearch, WebFetch | 控场+评分+判胜负+核实论据 |
| futures-risk-manager（风控） | Read, SendMessage | 仓位沙盘推演+逻辑质检 |
| futures-trading-strategist（策略师） | Read, SendMessage | 接收判决+合成方案+过风控 |
| futures-judge | Read, SendMessage, WebSearch, WebFetch | 核实论据、输出裁决 |
| futures-risk-manager | Read, SendMessage | 读取结构化数据、输出风控 |
| futures-trading-strategist | Read, SendMessage | 读取裁决、输出交易计划 |

> 如发现某Agent工具为空或缺失 → **修复Agent定义**，不要为绕过工具限制而写胶水代码。

### 违反后果

一旦在执行中产生胶水代码，必须：
1. 立即冻结工作流
2. 追溯根因（缺少CLI参数？Agent工具不全？路由不可靠？）
3. 修复对应的 skill 或 Agent 定义
4. 恢复执行（从当前 phase 继续，不重跑）
5. 将胶水脚本从产出目录中清理

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

### P3: ArgumentOutput(role="证真"/"慎思")

定义在 `contracts/debate.py`（v2.2 统一 schema）：

```python
class DimensionItem(BaseModel):
    dim: str                      # 维度名称
    claim: str                    # 核心观点
    evidence: str                 # 可核验证据（必含具体数字）
    confidence: float             # 该维度置信度 0-1

class ArgumentOutput(BaseSkillOutput):
    """统一辩手输出，role 决定方法论"""
    role: Literal["证真", "慎思"]          # 辩论角色（主标识）
    variant: Literal["bull", "bear"]       # 向后兼容
    dimensions: list[DimensionItem]        # min_length=5, max_length=5
    summary_4_risk: str                    # ≤100字，给风控的精简摘要
    full_text: str                         # 完整论证文本
    confidence: float                      # 整体置信度 0-1
    rebuttal_targets: list[str]            # 本轮反驳了对手的哪些维度

# 向后兼容别名（contracts/debate.py 已定义）
# BullOutput = ArgumentOutput(role="证真")
# BearOutput = ArgumentOutput(role="慎思")
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
    zhengzhen: "ArgumentOutput | None"               # P3 证真 v1（role="证真"）
    zhensi: "ArgumentOutput | None"                  # P3 慎思 v1（role="慎思"）
    zhengzhen_v2: "ArgumentOutput | None"            # P3 证真 v2（rebuttal）
    judge: "JudgeVerdict | None"                     # P3b 闫判官
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
| **证真** | P3并行 | 辩护方 | `debate-argument-builder`(角色:证真) | 纯定性，不做数据计算 |
| **慎思** | P3并行 | 质疑方 | `debate-argument-builder`(角色:慎思) | 纯定性，不做数据计算 |
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

# 从 contracts 模块导入 schema（v2.2: ArgumentOutput 含 role 字段）
from contracts import (
    ArgumentOutput, BullOutput, BearOutput, RiskOutput, TradingPlanOutput,
    apply_migration
)

OUTPUT_SCHEMA_MAP = {
    "zhengzhen": ArgumentOutput,  # role="证真"
    "zhensi": ArgumentOutput,     # role="慎思"
    "bull": BullOutput,           # 向后兼容
    "bear": BearOutput,           # 向后兼容
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

### spawn 协议（v3.0 Agent工具链适配版）

**总则**：
1. Agent通过加载技能（Skill tool）获取工具和能力，不依赖 `allowed-tools` frontmatter
2. 产出双轨——正文（人类可读 Markdown）+ 末尾 ```json fence 结构化摘要
3. 明鉴秋通过 `parse_phase_output()` 从 fence 中扒结构化数据写入 `DebateState`

**明鉴秋构建 spawn prompt 的原则**：**只传下游需要的最小子字段**（参照 Sparse MAD 按需可见原则），不再全文拼接。

每次 spawn Agent 时，Prompt 结构如下：

```
subagent_type: "general-purpose"    # 使用通用型agent（有完整工具集）
模式：{mode}
数据品种：{品种列表}

你是{角色名}，辩论专家团的{职责描述}。
你的边界：{边界能力}。
请使用 Skill 工具加载 {skill名} 的定义，获取领域知识和输出格式要求。
产出格式：正文（Markdown分析）+ 末尾 ```json fence 结构化摘要，字段严格按对应 schema
**【通信约束】** 不要向任何其他Agent发送消息索要数据。如缺少数据，在你的产出中注明缺失内容，明鉴秋会处理。
完成后用 SendMessage 将完整产出发送给 main。
```

### 🔴 时序与通信铁律（P0不可违反）

| 编号 | 规则 | 违反后果 |
|:----|:----|:---------|
| S01 | **数据就绪信号**：下游Agent的spawn必须等到上游产出的文件**已存在且size稳定≥5秒**。明鉴秋在spawn prompt中附录"上游文件已写入完毕"确认。禁止直接spawn并发让下游自己去猜文件是否写完 | 读到半成品→置信度偏低→结论错误 |
| S02 | **禁止Agent间直接通信**：所有Agent产出必须通过写文件，然后由明鉴秋统一传递给下游。Agent之间不得互相SendMessage（包括"索取数据"请求）。如果缺数据，告知明鉴秋，由明鉴秋调度 | 控制流断裂→重复工作→谁在做什么无法追踪 |
| S03 | **原子写入**：Agent写产出文件时先写`.tmp`后缀，写完后rename为正式文件名。明鉴秋检查`.tmp`文件不存在且正式文件mtime≥5秒才算就绪 | 文件竞争→读到半成品JSON |
| S04 | **轮询就绪**：明鉴秋spawn上游后，等待上游文件就绪的策略：每15秒检查一次文件是否存在+size是否稳定，最多60次（15分钟超时）。不依赖TaskOutput的block模式 | TaskOutput不阻塞→无法判断何时推进 |

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

**Phase 1 统一执行** — 使用 quant-daily scan_all.py（只跑三类信号，不做dual）

根据 **无胶水代码协议（铁律1）**，P1 直接调用 quant-daily 的 CLI，只跑三类信号策略：

```bash
# full_scan 模式
python ~/.workbuddy/skills/quant-daily/scripts/scan_all.py -o <输出目录>

# custom 模式（指定品种）
python ~/.workbuddy/skills/quant-daily/scripts/scan_all.py -o <输出目录> --symbols PK,RB,B,UR
```

`scan_all.py` 完成：数据采集 + 三类信号计算（breakout/pullback/gap）。

**L1-L4和因子择时不是P1全量扫描的一部分**。研究员（观澜/探源）在P3通过各自的 `data_interface.py` 按需拉取（只计算辩论品种）。

**回退**：如果 `scan_all.py` 因模块导入问题失败，直接通过 Python 调用 `run_scan()` 函数（传 `symbols` 参数），而非写新脚本：

```python
sys.path.insert(0, "~/.workbuddy/skills/quant-daily/scripts")
from scan_all import run_scan
from config.symbols import ALL_SYMBOLS

# 构造目标品种列表
codes = ["PK", "RB", "B", "UR"]
sym_map = {s: n for s, n in ALL_SYMBOLS}
targets = [(s, sym_map[s]) for s in codes]
result = run_scan(output_dir=<dir>, symbols=targets)
```

**禁止行为**：编写 `phase1_custom_scan.py` 或其他一次性数据采集脚本。

**输出文件**：`scan_all.py` 的输出JSON已包含 `_meta` 字段（含数据来源、日期、指标计算方法等溯源信息），明鉴秋直接读取即可满足数据溯源要求。

→ P1全完成后：`state["data"]` = DataOutput, `state["tech"]` = TechOutput
→ **保存 intermediate_data.json**（见下方说明）
→ 明鉴秋控：进入 P2

**⚠️ 重要：保存 intermediate_data.json（供 phase3_generate_report.py 使用）**
P1完成后，明鉴秋必须将 `scan_all.py` 的产出保存为 intermediate_data.json，写入 `Commodities/Reports/商品期货深度分析/{date}/` 目录。

必要字段：
```python
{
  "report_date": "YYYY-MM-DD",
  "data_source": "quant-daily scan_all.py",
  "data_manifest": {
    "kline": {"source": "通达信TQ-Local", "capture_time": "HH:MM", "latest_bar_date": "YYYYMMDD", "gap_days": 0, "freshness": "正常"},
    "indicators": {"method": "numpy向量化(通达信公式对齐)", "base_on": "基于上述K线数据"}
  },
  "generated_at": "ISO时间戳",
  "symbols_count": scan_result["_meta"]["total"],
  "all_actionable": scan_result["all_ranked"],
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

→ state["chain"] = ChainOutput
→ 明鉴秋控：进入 P3

**Phase 3 交叉质询（v2.4 新增·3 跳）**

**步 1 — spawn 证真**（证真写 v1 + 注入慎思论点=空）:
```
角色: 辩护方（证真）。你的工作方法由 debate-argument-builder 的"辩论专家团集成模式·角色:证真"定义，请加载并执行。
角色锚定: 你是正方辩手（证真），从研究员资料中提取论据支持闫判官指定的方向。关注三类信号数据+技术面+基本面中支持正方方向的证据。
边界: 不做行情数据采集，不做指标计算。禁止使用 WebSearch/WebFetch 搜集数据——论据只能从三类信号/研究员快照/辅助数据中提炼。
前序数据（按需可见）: 三类信号数据 + 观澜技术面快照 + 探源基本面快照 + 链证源产业链快照 + L1-L4原始数据 + factor_timing原始数据
对手论点: 暂无（首轮无慎思论点可读）
任务: 对闫判官指定的辩论品种和方向，从正方角度构建论据。引用三类信号（突破/回踩/跳空）+ 研究员快照数据。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="证真") schema
红线: 禁止附和语；每个维度≥1个可核验数字
产出 schema: ArgumentOutput(role="证真")（contracts/debate.py）
```

**步 2 — Handoff: 慎思读证真 v1 后写慎思 v1**:
```
角色: 质疑方（慎思）。你的工作方法由 debate-argument-builder 的"辩论专家团集成模式·角色:慎思"定义，请加载并执行。
角色锚定: 你是反方辩手（慎思），从研究员资料中提取论据质疑闫判官指定的方向。关注三类信号的矛盾点+技术面/基本面中的反向证据。
边界: 不做行情数据采集，不做指标计算。禁止使用 WebSearch/WebFetch 搜集数据——论据只能从三类信号/研究员快照/辅助数据中提炼。
前序数据（按需可见）: 观澜技术面快照 + 探源基本面快照 + 链证源产业链快照 + L1-L4原始数据 + factor_timing原始数据
对手论点: 你收到了证真的 v1 论点。请阅读 dimensions 和 summary_4_risk。
任务: 对辩论候选列表中每一个品种，都从质疑方角度提出反驳。
       特别关注：你的质疑论点必须参考并回应证真的核心论据。
       每条 evidence 要足够具体，让证真能在下一轮逐条回应——不要写"库存偏高"，写"社会库存同比+15%×4周"。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="慎思") schema
红线: 禁止"证真说得有道理"开头；禁止重复证真 v1 已经引用的相同数据；每个维度≥1个可核验数字
产出 schema: ArgumentOutput(role="慎思")（contracts/debate.py）
```

→ state["zhensi"] = ArgumentOutput(role="慎思")
→ 慎思写完后，Handoff: 慎思 → goto 证真

**步 3 — Handoff: 证真读慎思 v1 后写证真 v2（rebuttal, max=1）**:
```
角色: 辩护方（证真）第2轮 rebuttal。你的工作方法由 debate-argument-builder 的角色:证真定义。
角色锚定: 辩护方。
对手论点: 你收到了慎思的 v1 论点。请阅读 dimensions 和 summary_4_risk。
任务: 基于慎思的论点写 rebuttal（证真 v2），结构：
  1. Rebuttal 段：对慎思至少 2 个维度逐条拆解，格式"慎思曰[X维度：证据] → 辩护方驳：反证（附数字）"
  2. 己方 5 维度更新版：被慎思打掉的维度补数据，没被打的就保留
  3. Confidence 重估：0-1，比 v1 调高/调低/持平，写理由
红线: 禁止 self-weaken；禁止"但是反过来"开头；重复率 >30% 本轮作废。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="证真") schema
终止条件: max_rebuttal=1，这是最终轮
产出 schema: ArgumentOutput(role="证真")（contracts/debate.py）
```

→ state["zhengzhen_v2"] = ArgumentOutput(role="证真")（rebuttal 版本）
→ **终止条件检查**：如果 zhengzhen_v2.dimensions 中 ≥3/5 维度的 counter_points 承认"慎思这点成立，但…" → 提前结束
→ P3 交叉质询完成。明鉴秋控：进入 P3b

**Phase 3b 串行** — spawn 闫判官（传证真 v2 + 慎思 v1，不传全文只传 summary_4_risk）
```
角色: 辩论裁决官。你的工作方法由 debate-judge 定义，请加载并执行。
边界: 不做新分析、不做数据采集、不做交易计划。
      只基于已有论据做综合权衡裁决。可使用 WebSearch/WebFetch 核实引用的数据/事实是否准确。
前序数据（按需可见）: 
  - 证真论点 (v2 rebuttal): summary_4_risk + dimensions（每品种）
  - 慎思论点 (v1): summary_4_risk + dimensions（每品种）
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

**Phase 4 串行** — spawn 风控明（输入改传结构化证真/慎思对象，不再传 Markdown 全文）
```
角色: 风险管理总监。你的工作方法由 debate-risk-manager 定义，请加载并执行。
边界: 不做数据采集、不做信号分析、不做交易计划。只做风险评估和裁决。
前序数据（结构化对象，不是全文）:
  证真: confidence={zhengzhen.confidence}, dimensions={zhengzhen.dimensions|to_json},
        summary_4_risk="{zhengzhen.summary_4_risk}", rebuttal_targets={zhengzhen.rebuttal_targets}
  慎思: confidence={zhensi.confidence}, dimensions={zhensi.dimensions|to_json},
        summary_4_risk="{zhensi.summary_4_risk}"
  注意：证真_v2 是经过 rebuttal 的版本。请重点检查 rebuttal_targets 列出的维度中，
        证真是否真的接住了慎思的质疑（不是糊弄）。
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
   
   **数据溯源义务（2026-07-03 掌柜确认）**：debate_results.json 必须包含顶层 `data_manifest` 字段，记录每次辩论所用全部数据的来源、日期、时效性。该字段在汇总输出时由明鉴秋补齐。
   
   ```python
   # 写两套：新 contracts/ schema 字段 + 旧平铺字段
   debate_results = {
       # ...原有字段...
       "data_manifest": {
           "kline": {
               "source": "通达信TQ-Local",
               "capture_time": "采集时间",
               "latest_bar_date": "YYYYMMDD",
               "gap_days": 0,
               "freshness": "正常/延迟/过期"
           },
           "indicators": {
               "method": "numpy向量化(通达信公式对齐)",
               "base_on": "基于上述K线数据"
           },
           "fundamental": [
               {"fact": "数据内容", "source": "来源机构名", "date": "数据日期", "url": "WebSearch查询关键词/URL"}
           ]
       }
   }
   ```
       # 新格式（供未来消费）
       "zhengzhen_output": state["zhengzhen_v2"] or state["zhengzhen"],
       "zhensi_output": state["zhensi"],
       "judge_output": state["judge"].model_dump() if state["judge"] else {},
       "risk_output": state["risk_obj"],
       "plan_output": state["plan"].model_dump() if state["plan"] else {},
       # 向后兼容旧字段名（供 phase3_generate_report.py 消费，适配器会处理）
       "bull_output": state["zhengzhen_v2"] or state["zhengzhen"],  # 兼容旧名
       "bear_output": state["zhensi"],                                # 兼容旧名
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

### 全量辩论报告（v2.15.0+ 链证源增强版）

读取链证源分析结果 + 数技源信号数据，生成含动态相关性检测的深度分析HTML。

```bash
python scripts/phase3_generate_debate_report.py \
  --chain-json /path/to/chain_analysis.json \
  --summary-json /path/to/summary.json \
  --prices-json /path/to/prices.json (可选) \
  -o /path/to/output.html
```

参数：
- `--chain-json` — 链证源分析JSON（analyze_chain.py 产出）
- `--summary-json` — 数技源信号JSON（scan_all.py --dual 产出的 summary JSON）
- `--prices-json` — 历史价格JSON（可选，用于展示相关系数）
- `-o` — 输出HTML路径
- `--title` — 报告标题（可选）
- `--version` — 版本号（可选）

### 旧版辩论报告（向后兼容）

```bash
python scripts/phase3_generate_report.py
```

产出 HTML 报告，采用深蓝黑色背景 + 金色强调色暗色主题风格。

## 免责

本分析由AI基于公开数据生成，不构成投资建议。期货交易高风险。
