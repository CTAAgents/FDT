---
name: futures-trading-analysis
description: 期货交易辩论专家团 — 6策略管线(趋势/套利/回归/宏观/事件/ML)为信号源→链证源先于闫判官→闫判官筛选触发品种→研究员并行供弹→多头/空头分析员并行论据(多空头机制)→闫判官在多空论据间裁决(含交易参数输出)→风控审方案→CTP信号输出。Agent只Write文件不SendMessage。
allowed-tools: Read,Bash
agent_created: true
disable: false
---

# 商品期货交易辩论专家团 — 按需分析

## 依赖

- **编排层输出**：所有 Phase 的 schema 定义在 `contracts/` 目录下（`data_collection.py`, `technical.py`, `chain_analysis.py`, `debate.py`, `risk.py`）
- **下游子 skill**：
  - `quant-daily`（数技师数据管道）
  - `futures-data-technician`（数技师专用封装）
  - `commodity-chain-analysis`（基本面研究员接口）
  - `debate-argument-builder`（多/空辩手论点构建）
  - `debate-judge`（裁判主持）
  - `debate-risk-manager`（风控三合一）
- **通信协议**：正文（HTML 报告）+ 末尾 ```json fence 结构化摘要 → `parse_and_migrate` → state

## 架构

```
用户/定时任务 触发辩论
    ↓ (传参 mode + targets)
明鉴秋(团队主管) → 选定品种+周期+权益
    ↓
  数技师 scan_all.py --symbols PK,RB → 数据包
    ↓
[辩论全流程]:
  明鉴秋同时 spawn 探源+观澜+链证源（并行并发）→ 三研究员同时产出
    ↓
  闫判官主持 → 多/空辩手立论→互rebuttal→自由交锋→final（轮次由信号等级决定）
    ↓
  闫判官 判胜负 + 输出交易参数
    ↓
  风控明 跑杠杆/回撤/叙事质检 → 审核闫判官交易参数
    ↓
  明鉴秋 将风控审核通过的交易参数 → CTP指令
    ↓
  明鉴秋 拍板 execute/hold/rematch
    ↓
  全员 → 归档 → debate_results.json → HTML报告
    ↓
明鉴秋 → 交付
```

**关键设计**：
- 明鉴秋（团队主管）只做选题和拍板，辩论期不插手
- 闫判官全权主持研究员→辩手→裁决→风控全流程
- 角色分工：数技师不做分析、研究员不下结论、闫判官直接输出交易参数、风控不改多空

---

## 🚫 无胶水代码协议

**胶水代码定义**：在业务执行流程中临时编写的、仅用一次的脚本/函数/胶合逻辑。

### 根本原则

**零胶水。** 任何需要在执行流程中完成的操作，必须通过已有skill的CLI接口、库函数调用、或Agent spawning来完成。**禁止在运行过程中编写一次性脚本。**

### 三条铁律

#### 铁律1：P1 数据采集必须使用 quant-daily 的 CLI（只跑三类信号，不做dual）

当 `mode=custom` 需要扫描指定品种时：

**数技源**（纯数据采集+三类信号计算，不做分析）：
```bash
python scripts/scan_all.py --symbols PK,RB,B,UR
```

**不再使用 `--dual` 模式。这是当前唯一的信号源路径。由研究员（观澜/探源）在分析阶段通过各自的 `data_interface.py` 按需拉取（只计算辩论品种）。

#### 铁律2：Agent 输出必须通过文件持久化读取，不依赖消息路由

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
3. **禁止行为**：编写 `read_agent_output.py`、`parse_inbox.py` 等一次性读取脚本。

#### 铁律3：数据溯源纳入自动化流程，不临时写脚本

所有数据溯源信息必须在 P1 阶段由 `scan_all.py` 的输出来记录（已内置 data_manifest 字段），**禁止**事后编写核查脚本来追补。如果 data_manifest 信息不完整 → 应修改 `scan_all.py` 本身。

### Agent工具权限

| Agent | 所需工具 | 用途 |
|:------|:---------|:-----|
| 数技师 | Read, Bash, SendMessage | 运行scan_all.py（库函数模式） |
| 基本面研究员 | Read, Write, WebSearch, WebFetch, SendMessage | 搜索基本面事实+出快照 |
| 技术面研究员 | Read, Write, WebSearch, SendMessage | 分析量价+出快照 |
| 正方辩手 | Read, WebSearch, WebFetch, SendMessage | 论证方向正确性+反驳反方质疑 |
| 反方辩手 | Read, WebSearch, WebFetch, SendMessage | 质疑方向漏洞+反驳正方论证 |
| 闫判官 | Read, SendMessage, WebSearch, WebFetch | 控场+评分+判胜负+输出交易参数 |
| 风控明 | Read, SendMessage | 仓位沙盘推演+逻辑质检 |

### 违反后果

一旦在执行中产生胶水代码，必须：
1. 立即冻结工作流
2. 追溯根因（缺少CLI参数？Agent工具不全？路由不可靠？）
3. 修复对应的 skill 或 Agent 定义
4. 恢复执行（从当前 phase 继续，不重跑）
5. 将胶水脚本从产出目录中清理

---

## 📐 接口契约

本系统所有 phase 间的通信通过 `contracts/` 模块中的 typed schema 进行。

### PhaseMeta（每条输出的元数据）

```python
class PhaseMeta(BaseModel):
    """每条 phase 输出的元数据，排障时通过 trace_id 回放整条链"""
    phase: str                # "P1"/"P2"/"P3"/"P3b"/"P4"
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
    key_prices: dict[str, float]
    raw_data: dict
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
    all_actionable: list[dict]
    top10: list[str]
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

### P3: ArgumentOutput(role="多头"/"空头")

定义在 `contracts/debate.py`：

```python
class DimensionItem(BaseModel):
    dim: str                      # 维度名称
    claim: str                    # 核心观点
    evidence: str                 # 可核验证据（必含具体数字）
    confidence: float             # 该维度置信度 0-1

class ArgumentOutput(BaseSkillOutput):
    """统一辩手输出，role 决定方法论"""
    role: Literal["多头", "空头"]
    variant: Literal["bull", "bear"]
    dimensions: list[DimensionItem]        # min_length=5, max_length=5
    summary_4_risk: str                    # ≤100字，给风控的精简摘要
    full_text: str                         # 完整论证文本
    confidence: float                      # 整体置信度 0-1
    rebuttal_targets: list[str]            # 本轮反驳了对手的哪些维度
```

### P3b: JudgeVerdict（闫判官 — 含交易参数）

```python
class JudgeVerdict(BaseModel):
    variant: Literal["judge"] = "judge"
    verdicts: dict[str, dict]
    overall_assessment: str
    trading_params: dict       # 含 entry/stop/target/position，闫判官直接输出
    meta: PhaseMeta
```

### P4: RiskOutput（风控明）

定义在 `contracts/risk.py`：

```python
class VerdictItem(BaseModel):
    dim: str                                 # 维度名
    ruling: Literal["include", "watch", "exclude"]
    winner: Optional[Literal["bull", "bear"]]
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
    full_report: str                         # 自然语言报告全文
```

### DebateState（全链共享状态）

```python
class DebateState(TypedDict):
    """明鉴秋维护的全链 typed state"""
    variant: str                                    # 当前品种
    phase: Literal["P1","P2","P3","P3b","P4"]      # 当前阶段
    data: DataOutput | None                         # P1 数聚石
    tech: TechOutput | None                         # P1 技研锋
    chain: ChainOutput | None                       # P2 链证源
    zhengzhen: ArgumentOutput | None                # P3 多头 v1
    zhensi: ArgumentOutput | None                   # P3 空头 v1
    bullish_v2: ArgumentOutput | None               # P3 多头 v2（rebuttal）
    judge: JudgeVerdict | None                      # P3b 闫判官（含 trading_params）
    risk: RiskOutput | None                         # P4 风控明
```

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
- 用户要求辩论 → 必须完整执行全流程
- 禁止协调器绕过Agent自行分析

### 右侧交易铁律（全局强制）
**所有交易建议基于已确认的右侧价格行为信号，禁止左侧猜测。**
1. 量化指标只描述状态，不是信号
2. 必须等待右侧确认后才出BUY/SELL决策
3. 无信号则HOLD（强制）
4. 辩论结论≠入场信号

### 裁决权重铁律（闫判官裁决规则）
**价格是唯一客观现实。价格是各种要素（供需、政策、情绪、期限结构、资金流向等）作用的最终合力。所有其他分析维度都是对价格的解释，不是独立的投票成员。**

裁决方向必须以**已确认的右侧价格行为信号**为核心依据。各分析维度按信号时序分配权重，且必须遵守权重上限约束：

| 维度 | 信号时序 | 权重上限 | 可单独推翻方向？ |
|:----:|:--------:|:--------:|:--------------:|
| 趋势结构（价格行为） | **领先** | **无上限（核心依据）** | ✅ 可以（方向判断的唯一入口） |
| 量价关系 | 同步确认 | 30% | ✅ 可以用价格行为无法单独解释时才可辅助 |
| 期限结构（Back/Contango） | **滞后** | **15%** | ❌ 不可单独推翻价格方向 |
| 产业链验证 | 滞后（定性辅助） | 10% | ❌ 不可单独 |
| 基本面/市场情绪 | 最滞后 | 5% | ❌ 不可单独 |

**关键约束**：
- 期限结构独立说明力上限为**15%**——只能在价格行为明确时辅助验证方向一致性，**不得**作为转向多空的独立依据
- 价格行为不清晰时（ADX<15震荡、量价不一致），应裁决「搁置观察」，不得依赖任何其他维度强行出方向
- 其他维度的正确用法：方向判断已由价格信号做出后，用于验证一致性和标注风险
- **趋势行情下，任何单一风险提示项（包括但不限于Z分数极端值、Back结构、库存数据、政策预期等），不得作为推翻趋势判断的依据**。单一风险项只能用于：①标注风险等级 ②调整仓位大小 ③收紧止损宽度，但不得改变方向裁决。

---

## Agent 职责

| Agent | Phase | 职责 | 技能定义 | 边界 |
|-------|:-----:|------|----------|------|
| **数聚石** | P1并行 | 数据工程师 | `futures-data-search` | 只采集+校验，不做分析 |
| **技研锋** | P1并行 | 信号分析师 | `commodity-trend-signal` | 不做数据采集，不做交易计划 |
| **链证源** | P2串行 | 产业链验证 | `commodity-chain-analysis` | 不做信号分析，不做数据采集 |
| **证真** | P3并行 | 辩护方 | `debate-argument-builder`(角色:证真) | 纯定性，不做数据计算 |
| **慎思** | P3并行 | 质疑方 | `debate-argument-builder`(角色:慎思) | 纯定性，不做数据计算 |
| **闫判官** | P3b串行 | 辩论裁决官+交易参数输出 | `debate-judge` | 不做新分析，只基于已有论据裁决；直接输出交易参数 |
| **风控明** | P4串行 | 风险总监 | `debate-risk-manager` | 审核闫判官交易参数，不做交易计划 |

---

## 调度协议（明鉴秋执行）

### 角色

明鉴秋——辩论协调员。流程调度器，不参与分析。读取数据，spawn专家，收集双轨产出（正文+```json fence），生成报告。

维护 `DebateState`（见接口契约章节），每个 phase 的产出写入对应字段，下游按需读取。**只传下游需要的最小子字段**，不拼接上游全文。

### 双轨解析逻辑

```python
import re, json
from pydantic import ValidationError

def extract_fence_json(md_text: str) -> dict | None:
    """从 Markdown 中提取第一个 ```json fence 并解析为 dict"""
    m = re.search(r'```json\s*(.*?)```', md_text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
```

### mode 参数

明鉴秋接收两个入参：

```
mode: "full_scan" | "custom"
targets: [...]  # custom 模式下指定品种列表，如 ["rb", "FG", "cs"]
```

- **full_scan 模式（定时任务）**：全67品种采集→选Top10→只对Top10辩论
- **custom 模式（独立调用）**：只采集指定品种→只计算指定品种→所有指定品种进入辩论

### spawn 协议

**总则**：
1. Agent通过加载技能（Skill tool）获取工具和能力
2. 产出双轨——正文（人类可读 Markdown）+ 末尾 ```json fence 结构化摘要
3. 明鉴秋通过 `parse_and_migrate()` 从 fence 中扒结构化数据写入 `DebateState`

**明鉴秋构建 spawn prompt 的原则**：**只传下游需要的最小子字段**，不再全文拼接。

每次 spawn Agent 时，Prompt 结构如下：

```
subagent_type: "general-purpose"
模式：{mode}
数据品种：{品种列表}

你是{角色名}，辩论专家团的{职责描述}。
你的边界：{边界能力}。
请使用 Skill 工具加载 {skill名} 的定义，获取领域知识和输出格式要求。
产出格式：正文（Markdown分析）+ 末尾 ```json fence 结构化摘要，字段严格按对应 schema
**【通信约束】** 不要向任何其他Agent发送消息索要数据。如缺少数据，在你的产出中注明缺失内容，明鉴秋会处理。
完成后用 SendMessage 将完整产出发送给 main。
```

### 信号分级驱动辩论深度

明鉴秋在P2完成后、进入P3前对每个品种做信号分级：

| 等级 | 条件 | 辩论轮次 | 预期耗时 |
|:----:|:-----|:--------:|:--------:|
| **C1** | ADX>40 + RSI非极端 + BB扩张 + 链一致性高 + 放量 | **0轮**（快速裁决→闫判官直出） | **~8min** |
| **C2** | 2-3个条件达标 | **2轮**（辩手并行立论 + 1轮rebuttal） | **~15min** |
| **C3** | 信号矛盾/因子分歧 | **4轮**（标准流程） | **~30min** |
| **C4** | 无信号 | **不辩论** | — |

**C1/C4 快速通道**：跳过P3辩论，直接从P1数据进入闫判官裁决。裁决标记 `"signal_tier": "C1", "debate_mode": "fast"` 供风控明参考。

### 时序与通信铁律

| 编号 | 规则 | 违反后果 |
|:----|:----|:---------|
| S01 | **数据就绪信号**：下游Agent的spawn必须等到上游产出的文件**已存在且size稳定≥5秒**。明鉴秋在spawn prompt中附录"上游文件已写入完毕"确认 | 读到半成品→结论错误 |
| S02 | **禁止Agent间直接通信**：所有Agent产出必须通过写文件，然后由明鉴秋统一传递给下游。Agent之间不得互相SendMessage | 控制流断裂→无法追踪 |
| S03 | **原子写入**：Agent写产出文件时先写`.tmp`后缀，写完后rename为正式文件名。明鉴秋检查`.tmp`文件不存在且正式文件mtime≥5秒才算就绪 | 文件竞争→读到半成品 |
| S04 | **轮询就绪**：明鉴秋spawn上游后，每15秒检查一次文件是否存在+size是否稳定，最多60次（15分钟超时） | 无法判断何时推进 |

### 执行流程

#### P1 数据采集

根据 **无胶水代码协议（铁律1）**，P1 直接调用 quant-daily 的 CLI：

```bash
# full_scan 模式
python ~/.workbuddy/skills/quant-daily/scripts/scan_all.py -o <输出目录>

# custom 模式（指定品种）
python ~/.workbuddy/skills/quant-daily/scripts/scan_all.py -o <输出目录> --symbols PK,RB,B,UR
```

`scan_all.py` 完成：数据采集 + 三类信号计算（breakout/pullback/gap）。

**回退**：如果 `scan_all.py` 因模块导入问题失败，直接通过 Python 调用 `run_scan()` 函数：

```python
sys.path.insert(0, "~/.workbuddy/skills/quant-daily/scripts")
from scan_all import run_scan
from config.symbols import ALL_SYMBOLS

codes = ["PK", "RB", "B", "UR"]
sym_map = {s: n for s, n in ALL_SYMBOLS}
targets = [(s, sym_map[s]) for s in codes]
result = run_scan(output_dir=<dir>, symbols=targets)
```

**输出文件**：`scan_all.py` 的输出JSON已包含 `_meta` 字段（含数据来源、日期、指标计算方法等溯源信息）。

→ P1完成后：`state["data"]` = DataOutput, `state["tech"]` = TechOutput
→ **保存 intermediate_data.json**（供 phase3_generate_report.py 使用）
→ 明鉴秋控：进入 P2

**⚠️ 保存 intermediate_data.json（供 phase3_generate_report.py 使用）**

P1完成后，明鉴秋必须将 `scan_all.py` 的产出保存为 intermediate_data.json，写入 `Commodities/Reports/商品期货深度分析/{date}/` 目录。

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

#### P2 并行 — 三个研究员同时 spawn

明鉴秋同时 spawn 三个研究员 Agent（并发，互不依赖）：

```python
import threading

results = {}

def spawn_researcher(name, prompt):
    raw = debate_team.run(name, prompt)
    results[name] = raw

threads = []
for name in ["探源", "观澜", "链证源"]:
    t = threading.Thread(target=spawn_researcher, args=(name, "..."))
    threads.append(t)
    t.start()

for t in threads:
    t.join(timeout=600)

state["tanyuan"] = parse_and_migrate(results.get("探源"), "fundamental")
state["guanlan"] = parse_and_migrate(results.get("观澜"), "technical")
state["chain"] = parse_and_migrate(results.get("链证源"), "chain")
```

若某个研究员超时（600s）或产出校验失败：明鉴秋做降级标注（`state["降级研究员列表"]`），但不阻塞流程。

**探源（基本面研究员）**：
```
角色: 基本面研究员（探源）。由 futures-data-search 的"基本面分析接口"定义。
边界: 不做行情数据采集，不做信号分析。
前序数据: 各品种 key_prices + 最新基本面状态向量
任务: 为辩论品种提供基本面维度的事实依据（供需/库存/利润/政策）。
产出方式: 正文+```json fence → main
```

**观澜（技术面研究员）**：
```
角色: 技术面研究员（观澜）。由 commodity-trend-signal 的"技术面分析接口"定义。
边界: 不做数据采集，不做产业链分析。
前序数据: 各品种 ADX/RSI/支撑阻力/趋势判定
任务: 为辩论品种提供技术面维度的客观事实（支撑阻力/趋势阶段/量价关系）。
产出方式: 正文+```json fence → main
```

**链证源（产业链研究员）**：
```
角色: 产业链验证分析师。由 commodity-chain-analysis 的"辩论专家团产业链验证接口"定义。
边界: 不做行情数据采集，不做信号分析。
前序数据: 各品种 key_prices + 信号裁决 verdicts
任务: 为辩论品种提供产业链上下游的事实验证（上下游结构/一致性问题/关键矛盾）。
产出方式: 正文+```json fence → main
```

→ 明鉴秋等待全部研究员产出（`wait_all` + timeout=600s + min_success=2）→ 信号分级路由 → P3

#### P3 交叉质询

**步 1 — spawn 证真（v1，无对手论点）**:
```
角色: 辩护方（多头分析员）。由 debate-argument-builder 的"辩论专家团集成模式·角色:证真"定义。
角色锚定: 你是正方辩手（多头分析员），从研究员资料中提取论据支持方向。
边界: 不做行情数据采集，不做指标计算。禁止使用 WebSearch/WebFetch 搜集数据。
前序数据（按需可见）: 三类信号数据 + 观澜技术面快照 + 探源基本面快照 + 链证源产业链快照
对手论点: 暂无（首轮无慎思论点可读）
任务: 从正方角度构建论据，引用三类信号（突破/回踩/跳空）+ 研究员快照数据。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="多头") schema
红线: 禁止附和语；每个维度≥1个可核验数字
```

**步 2 — 慎思读证真 v1 后写慎思 v1**:
```
角色: 质疑方（空头分析员）。由 debate-argument-builder 的"辩论专家团集成模式·角色:慎思"定义。
角色锚定: 你是反方辩手（空头分析员），从研究员资料中提取论据质疑方向。
边界: 不做行情数据采集，不做指标计算。禁止使用 WebSearch/WebFetch 搜集数据。
前序数据（按需可见）: 观澜技术面快照 + 探源基本面快照 + 链证源产业链快照
对手论点: 你收到了证真的 v1 论点。请阅读 dimensions 和 summary_4_risk。
任务: 对辩论候选列表中每一个品种，都从质疑方角度提出反驳。特别关注：你的质疑论点必须参考并回应证真的核心论据。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="空头") schema
红线: 禁止"证真说得有道理"开头；禁止重复证真 v1 已经引用的相同数据；每个维度≥1个可核验数字
```

→ state["bearish"] = ArgumentOutput(role="空头")

**步 3 — 证真读慎思 v1 后写证真 v2（rebuttal, 单轮）**:
```
角色: 辩护方（多头分析员）第2轮 rebuttal。由 debate-argument-builder 的角色:证真定义。
对手论点: 你收到了慎思的 v1 论点。请阅读 dimensions 和 summary_4_risk。
任务: 基于慎思的论点写 rebuttal（证真 v2），结构：
  1. Rebuttal 段：对慎思至少 2 个维度逐条拆解
  2. 己方 5 维度更新版：被慎思打掉的维度补数据，没被打的就保留
  3. Confidence 重估：0-1，比 v1 调高/调低/持平，写理由
红线: 禁止 self-weaken；重复率 >30% 本轮作废。
产出格式: 正文（Markdown 分析）+ 末尾 ```json fence 按 ArgumentOutput(role="多头") schema
终止条件: max_rebuttal=1，这是最终轮
```

#### P3b — 闫判官裁决

```
角色: 辩论裁决官。由 debate-judge 定义。
边界: 不做新分析、不做数据采集、不做交易计划。只基于已有论据做综合权衡裁决。
       可使用 WebSearch/WebFetch 核实引用的数据/事实是否准确。
前序数据（按需可见）:
  - 证真论点 (v2 rebuttal): summary_4_risk + dimensions
  - 慎思论点 (v1): summary_4_risk + dimensions
  - P1 信号背景: state["tech"].verdicts + state["tech"].trend_stages
  - P2 产业链: state["chain"].chain_trends
分析: 按"裁决权重规则"做裁决 → 综合评估 → 直接输出交易参数（entry/stop/target/position）
产出 schema: JudgeVerdict（含 trading_params 字段）
```

明鉴秋在 spawn 闫判官时，**必须**将以下"裁决权重规则"嵌入 Prompt：

```text
## ⚖️ 裁决权重规则（全局强制，所有裁决必须遵守）

**根本前设**：价格是各种要素（供需、政策、情绪、期限结构、资金流向等）作用的最终合力，
所有其他分析维度均为对价格的解释，非独立的投票成员。价格行为是裁决的唯一核心依据——
方向判断必须由价格信号做出，其他维度仅用于验证一致性和标注风险，不得替代或推翻价格行为。

### 第1条：右侧交易优先
方向裁决必须以已确认的右侧价格行为信号为核心依据。当右侧价格信号与左侧/分析性信号矛盾时：
- ❌ 不得因任何非价格因素推翻价格走势的当前方向
- ❌ 不得将Back结构、产需缺口、政策预期等作为转向多空的独立裁决依据
- ✅ 非价格信号标注为"值得关注的潜在风险/机会"，不改变裁决方向
- ✅ 裁决方向仅在出现右侧确认信号后才可转向
- ✅ 若价格行为信号不清晰（ADX<15震荡、量价不一致），裁决为"搁置观察"

### 第2条：置信度评估顺序
置信度评估的参考顺序：①价格信号的清晰度 ②量价关系的配合程度 ③其他维度的方向一致性（不一致则降级，但不反转方向）。
```

#### P4 — 风控明审核

```
角色: 风险管理总监。由 debate-risk-manager 定义。
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
```

→ state["risk_obj"] = parse_fence(risk_raw, RiskSchema)。风控明审核完成 → 明鉴秋汇总

#### 汇总输出

1. 从 `DebateState` 提取全部 Agent 产出 → 汇总为 debate_results.json：

   **数据溯源义务**：debate_results.json 必须包含顶层 `data_manifest` 字段，记录每次辩论所用全部数据的来源、日期、时效性。该字段在汇总输出时由明鉴秋补齐。

   ```python
   debate_results = {
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
       },
       # 新格式
       "bullish_output": state["bullish_v2"] or state["bullish"],
       "bearish_output": state["bearish"],
       "judge_output": state["judge"],
       "risk_output": state["risk_obj"],
       # 向后兼容
       "bull_output": state["bullish_v2"] or state["bullish"],
       "bear_output": state["bearish"],
   }
   ```

2. 运行 `python ~/.workbuddy/skills/futures-trading-analysis/scripts/phase3_generate_report.py --debate {YYYY-MM-DD}/debate_results.json --workspace {YYYY-MM-DD}`
3. 运行 `python ~/.workbuddy/skills/futures-trading-analysis/scripts/debate_feedback.py inject`
4. SendMessage(recipient="main", content="报告路径 + ≤200字摘要")

---

## 数据源

所有国内期货数据统一由 `futures-data-search` 的 MultiSourceAdapter 调度。

优先级：tdx_local(0) → tqsdk(1) → eastmoney(2) → exchange_api(3) → akshare(4) → websearch(5) → cache(6)

## 反馈与自进化

每次辩论完成后，明鉴秋自动：
1. 扫描各 Agent 产出中的 `###FEEDBACK` 段
2. 路由到对应skill的修复模块
3. 更新 `lessons_learned.json`
4. 下次辩论前注入Agent Prompt

## 报告生成

```bash
python scripts/phase3_generate_debate_report.py \
  --chain-json /path/to/chain_analysis.json \
  --summary-json /path/to/summary.json \
  --prices-json /path/to/prices.json (可选) \
  -o /path/to/output.html
```

参数：
- `--chain-json` — 链证源分析JSON
- `--summary-json` — 数技源信号JSON（scan_all.py 产出）
- `--prices-json` — 历史价格JSON（可选）
- `-o` — 输出HTML路径

产出 HTML 报告，采用深蓝黑色背景 + 金色强调色暗色主题风格。

## 免责

本分析由AI基于公开数据生成，不构成投资建议。期货交易高风险。
