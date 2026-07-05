---
name: commodity-chain-analysis
version: 2.15.0
description: 商品期货产业链分析系统 v2.16.0 — 产业链聚类+动态相关系数冗余检测(取代硬编码)+跨链品种主导链判断。链证源产出双报告供闫判官裁决。
agent_created: true
user_invocable: true
triggers:
  - 产业链分析
  - 期限结构
  - 基差分析
  - 动态相关性检测
  - 多空辩论
  - 风险评估
---

# 商品期货产业链分析系统 v2.14

## 依赖
- **输出方**：`ChainAnalysisOutput`（`contracts/chain_analysis.py`）
- **版本**：`2.0`
- **输出方式**：正文（Markdown 产业链分析报告）+ 末尾 ```json fence 结构化摘要

## CLI 使用（避免胶水代码）

```bash
# 直接指定品种分析
python scripts/analyze_chain.py --symbols PK,RB,B,UR

# 读取 P1 JSON 输出（含价格和信号数据）
python scripts/analyze_chain.py --input ../phase1_output.json

# 只输出 JSON 不打印详细报告
python scripts/analyze_chain.py --symbols SA,RB,FU --json-only

# 动态相关系数冗余检测（v2.15.0+）
python scripts/analyze_chain.py --symbols PF,TA,RB --correlation-prices prices.json

# 自定义窗口和阈值
python scripts/analyze_chain.py --symbols ALL --correlation-prices p.json --correlation-window 90 --correlation-threshold 0.85
```

> ⚠️ **胶水代码零容忍**：禁止为单次分析创建独立脚本。用 `--symbols` 或 `--input` 参数复用现有 CLI。

## 🔴 辩论工作流时序（2026-07-05）

链证源在辩论专家团中的工作时序为 **P0-②**（紧接数技源之后，在闫判官之前）：

```
数技源(P0-①) ──行情数据──→ 链证源(P0-②) ──双报告──→ 闫判官(P1)
   scan_all.py                analyze_chain.py          确定辩论品种
                                     │
                                     ├─ 策略报告: 链趋势+锚点+期限
                                     └─ 产业链分析: 动态冗余+一致性+基本面
```

**链证源产出——两份独立报告：**
1. **策略报告**: 每条产业链的锚点识别(成本推动/需求拉动/断裂/替代切换) + 趋势方向 + 期限结构
2. **产业链分析报告**: 动态相关系数(r>0.80标记冗余) + 产业链一致性验证 + Z分数极端性检查 + 基本面验证笔记者

**闫判官必须等两份报告都到齐后**，结合数技源的信号数据，才能做辩论品种和方向的裁决。

## 🔴 链证源数据工作法（核心方法论）

链证源的数据来源分为两个完全独立的领域，**每个领域有各自的采集方法、使用规范和溯源要求**：

### 领域一：价格/技术数据

| 维度 | 规范 |
|:----|:-----|
| **来源** | 数技源（quant-daily scan_all.py --dual 产物） |
| **文件** | `full_scan_l1l4_{date}.json` + `full_scan_factor_timing_{date}.json` + `full_scan_summary_{date}.json` |
| **方法** | 直接读取已有 JSON 文件，**不得独立重新采集**（不得自行调 TqSDK/东方财富/AKShare） |
| **用途** | ①动态相关系数检测的输入（60日滚动价格序列） ②期限结构判断的数据源 ③链内品种信号比较 |
| **格式约定** | 价格序列以品种 symbol 为 key，close 数组按时间升序排列 |

### 领域二：基本面/新闻/产业资料

| 维度 | 规范 |
|:----|:-----|
| **来源** | WebSearch / WebFetch（互联网公开信息） |
| **方法** | 对每个品种所在产业链搜索 2-3 条基本面信息 |
| **溯源要求** | **每条引用必须附带来源URL + 数据截止日期**，格式严格遵循： |
| **引用格式** | `"数据描述（来源：XX网站/报告，截至7月X日）"` |
| **时效限制** | 见下方时序搜索规则表 |
| **未找到处理** | 如实报告"未找到近期数据，以量化信号为准"，不得用LLM内部知识替代 |
| **禁止** | 无来源的泛化表述如"库存偏高""需求疲弱"·无URL的陈述如"市场普遍认为"·编造模拟数据 |

### 数据链路架构

```
┌─────────────────────┐    直接读取JSON      ┌──────────────────────┐
│  数技源 (P0-①)      │ ──────────────────→  │  链证源 (P0-②)       │
│  scan_all.py --dual  │  价格/技术数据        │  analyze_chain.py    │
└─────────────────────┘                      │  + LLM链趋势解读      │
                                             │  + WebSearch基本面验证 │
┌─────────────────────┐    每条带URL+日期     └──────────────────────┘
│  WebSearch/WebFetch │ ──────────────────→          │
│  产业链新闻/库存等   │  基本面/产业资料              │
└─────────────────────┘                              ↓
                                              ┌──────────────────────┐
                                              │  闫判官 (P1)         │
                                              │  结合两份报告做裁决   │
                                              └──────────────────────┘
```

> ⚠️ **关键约束**：价格/技术数据来自数技源的已有产出，链证源不做二次采集。基本面数据来自互联网公开信息，每条必须有可追溯的来源。这两个领域的数据**不可混用标签**——价格数据引用时注明`（来源：scan_all.py --dual 扫描结果）`，基本面数据引用时注明具体网站/报告名。

## 核心能力

- **产业链聚类**：12大产业链、60+品种自动归类
- **产业链验证**：检查品种信号是否与产业链方向一致（+15%一致/-10%背离）
- **期限结构分析**：contango/backwardation识别，近远月价差分析
- **基差分析**：期货vs现货价格偏离度评估
- **多空辩论**：多头/空头/研究主管三方博弈
- **风险评估**：激进/保守/中性三方风险评估+风险主管裁决

## 使用方式

### 独立使用（产业链分析）

```python
from scripts.chains import get_chain_for_symbol, get_chain_members
from scripts.chain_verifier import chain_verification
from scripts.term_basis import analyze_term_structure, analyze_basis
from scripts.debate import bull_argument, bear_argument, research_manager_decision
from scripts.risk import aggressive_risk_assessment, conservative_risk_assessment, neutral_risk_assessment
```

### 与 commodity-trend-signal 配合

commodity-trend-signal 负责信号发现，本 skill 负责产业链验证和多空辩论。
两个 skill 独立部署，通过数据字典传递中间结果。

## 模块说明

| 模块 | 功能 |
|------|------|
| `config.py` | 产业链特有指标、辩论权重、类型映射 |
| `chains.py` | 产业链定义、聚类、龙头选择、品种映射、跨链判断 |
| `chain_verifier.py` | 产业链验证（信号与产业链方向一致性检查） |
| `term_basis.py` | 期限结构分析、基差分析 |
| `debate.py` | 多空辩论、研究主管裁决 |
| `risk.py` | 三方风险评估（激进/保守/中性）+ 风险主管裁决 |

## 产业链覆盖

黑色系、能源链、聚酯链、油化工、煤化工、有色金属、贵金属、油脂油料、谷物软商品、建材、橡胶、纸浆造纸

## 🔴 产业链分类核心原则（动态框架·不可硬编码）

**产业链分类不是固定的，而是根据分析目标、市场状态和品种关系动态调整的。** 以下原则定义分类的方法论，而非固定映射表。

### 为什么动态分类

1. **分析目的决定切法**：同一品种（如甲醇）在煤化工视角和能化视角下归入不同链
2. **锚点会切换**：市场有时是成本推动（上游定价），有时是需求拉动（下游定价），链的方向感随之改变
3. **新链在重构**：纯碱传统归建材（平板玻璃），光伏起来后要并链"纯碱→光伏玻璃→组件"
4. **权重在漂移**：废钢替代铁矿、光伏玻璃占比抬升、进口工艺份额变化——系数不是常数

### 四步调链法（链证源每次执行前先做）

```
1. 当前市场的核心矛盾是什么？——成本驱动 or 需求驱动？（决定链的方向）
2. 有没有新变量打断旧传导？——政策/新需求/替代工艺？（决定是否需要重画链）
3. 关键系数还成立吗？——产能/配方/比价有没有漂移？（决定链内权重）
4. 这个品种有没有跨链属性？——纯碱跨建材+光伏、甲醇跨煤化工+能化？（决定是否需要并链分析）
```

### 跨链品种清单

| 品种 | 主链 | 副链 | 当前主导判断 |
|------|------|------|-------------|
| 甲醇(MA) | 煤化工 | 能源化工(油气并链) | 看煤价/油价谁在边际定价 |
| 纯碱(SA) | 建材 | 光伏(浮法玻璃+光伏玻璃双下游) | 光伏占比抬升中,权重动态调 |
| 尿素(UR) | 煤化工/建材 | 农业(化肥) | 看当期是工业需求还是农业需求为主 |
| 乙二醇(EG) | 聚酯链 | 煤化工(煤制乙二醇路线) | 看煤头vs油头产能利用率 |
| 碳酸锂(LC) | 新能源 | 有色(传统矿→锂盐) | 定价权已从矿端移到中游正极厂 |
| 工业硅(SI) | 新能源(多晶硅) | 有色 | 光伏装机→多晶硅需求是本位 |
| 沪铝(AL) | 有色 | 能源(电力成本≈煤价传导) | 电解铝耗电,煤→电→铝是隐藏链 |

### 颗粒度分层规则

| 层级 | 用途 | 品种粒度 | 链表示 |
|------|------|---------|--------|
| **宏观档** | 定多空大方向 | 全链=1个贝塔 | "黑色链偏空""有色链承压" |
| **中观档** | 跨品种对冲 | 拆3-4段(原料/加工/成品/消费) | 看利润在环节间流转 |
| **微观档** | 精细化套利 | 拆到单品种系数 | 螺焦比、油粕比、钢厂利润公式 |

**辩论系统默认使用中观档**——拆到产业链段，验证品种信号是否与所在段的利润流向一致。需要做套利/价差分析时降档到微观。

## 辩论专家团产业链验证接口 — 链证源工作方法（v2.15.0）

### 角色声明

```
你是链证源——辩论专家团的产业链验证分析师。
你的职责：P0-②阶段执行（紧接数技源，在闫判官之前），产出两份独立报告供闫判官裁决。
```

### 工作时序（严格遵循）

```
数技源(P0-①) → 链证源(P0-②) → 闫判官(P1) → 多空辩论(P2) → 风控明(P3) → 策执远(P4)
```

**链证源必须等待数技源的行情数据和信号数据就绪后才能开始工作。**
**闫判官必须等链证源的两份报告到齐后才能确定辩论品种和方向。**

### 产出——两份独立报告

**报告1：策略报告（给闫判官参考辩论方向）**
- 每条产业链的锚点识别：成本推动型/需求拉动型/断裂型/替代切换型
- 链趋势方向：强势多头/偏多震荡/分化/偏空震荡/强势空头
- 期限结构分析：contango/back/flag
- 全链品种信号一览

**报告2：产业链分析报告（给闫判官做辩论品种取舍）**
- 动态相关系数冗余检测（v2.15.0+ 取代硬编码）
- 产业链一致性验证
- Z分数极端性检查
- 基本面验证笔记（WebSearch）
- 冗余排除建议（按一链一代表原则）

## 🔒 Anti-Hallucination Circuit Breaker（链证源专用·新增）

| 防呆机制 | 规则 |
|:---------|:-----|
| 产业链数量上限 | 每次分析最多识别**7条产业链**，超出合并 |
| 单链品种数上限 | 每条链最多**15个品种**，超出分裂子链 |
| 证据来源强制 | 每个方向判断必须引用具体数据源（库存/开工率/价差），禁止纯定性描述 |
| 置信度上限 | 单链一致性评分≤0.95，整体≤0.90 |
| 全文输出 | **≤4000 tokens** |
| 递归深度 | 链内分析最多3层（产业链→子链→品种），禁止自我递归 |
| 冗余检测上限 | 最多标注**5对**冗余品种，超出仅保留分数最高的5对 |
```
         并使用 WebSearch/WebFetch 搜索产业链基本面信息验证趋势逻辑。
你的边界：不做行情数据采集（那是数聚石的事），不做信号分析（那是技研锋的事），
         不做交易计划（那是策执远的事）。
         可以使用 WebSearch/WebFetch 搜索产业链新闻、供需数据、政策动态。
```

### 输入

由 明鉴秋 传入辩论候选品种的结构化数据（含品种pid、预计算L1-L4得分、方向）。

### 分析步骤

每个品种依次执行以下分析，调用 commodity-chain-analysis 的量化模块：

#### Step 1: 产业链归类（动态·含跨链判断）

```python
from scripts.chains import get_chain_for_symbol, get_chain_members
chain = get_chain_for_symbol(pid)         # → 默认主链
members = get_chain_members(chain)         # → 该链全部品种
```

**但如果品种在「跨链品种清单」中，必须额外执行**：
1. 判断当前市场的核心矛盾（成本驱动/需求驱动/新变量打断）
2. 标注该品种当前的实际主导链和副链
3. 如果主导链与默认主链不同，输出中注明"当前主导链为X，非默认主链Y"

#### Step 1b: 锚点识别（新增）

对每个链，判断当前驱动类型并写入 `chain_results[pid].anchor`：

| 驱动类型 | 特征 | 链的方向 |
|---------|------|---------|
| 成本推动型 | 上游原料涨价/紧缺 → 全链跟涨 | 锚在成本端 |
| 需求拉动型 | 下游消费/订单强劲 → 上游被拉动 | 锚在需求端 |
| 断裂型 | 政策/产能打断传导（如煤→电被长协限价打断） | 传导中断 |
| 替代切换型 | 新工艺/新需求重构了链的方向 | 按新链走 |

#### Step 2: 期限结构分析

```python
from scripts.term_basis import analyze_term_structure, analyze_basis
term = analyze_term_structure(pid)        # → "contango" / "back" / "flat"
basis = analyze_basis(pid)                # → "走强" / "走弱" / "平稳"
```

期限结构对交易方向的指导：
- **Contango**（远期>近期）：做空有利，展仓收益
- **Back**（近期>远期）：做多有利，现货紧张
- **Flat**（价差<0.5%）：无显著倾向

#### Step 3: 产业链一致性验证

```python
from scripts.chain_verifier import chain_verification
consistency = chain_verification(chain, signals)
# → 返回一致性评分(0-100%)和趋势方向
```

#### Step 4: Z分数极端性检查（commodity-chain-analysis未覆盖，补充计算）

基于200日收盘价计算z-score：
- |z| > 2 → ⚠️价格处于统计极端位置，标注"异常预警"
- |z| > 3 → 🔴价格处于极度极端位置，标注"高度异常预警"

**⚠️ 边界限制**：
- Z分数仅用于识别价格偏离均值的程度，**不得用于预判趋势方向改变或建议均值回归交易**
- Z分数是纯统计指标（正态假设），金融数据有厚尾特征，强趋势行情中Z可长期维持>2而不回归
- Z分数正确用途：①数据质量校验 ②风险预警标注 ③辅助风控判断当前价格位置是否极端
- 所有交易方向判断必须基于右侧确认信号，Z分数不得作为左侧预判依据

#### Step 5: 组合级产业链聚合 + 动态相关系数冗余检测（v2.15.0+）

**v2.15.0 重大变更：** 废弃硬编码 `WITHIN_CHAIN_HIGH_CORRELATION`，改为 **60日滚动Pearson相关系数动态计算**。

```bash
# 运行冗余检测（v2.15.0+）
python scripts/analyze_chain.py --symbols PF,TA,RB,HC \
  --correlation-prices /path/to/prices.json \
  --correlation-window 60 \
  --correlation-threshold 0.80
```

**价格数据格式：**
```json
{
  "PF": [6950, 6930, 6900, ...],   // 每个品种的close价格数组(按时间升序)
  "TA": [5480, 5460, 5430, ...],
  "RB": [3120, 3100, 3080, ...]
}
```

**检测规则：**
1. 按链分组所有品种
2. 组内两两计算60日Pearson相关系数
3. 相关系数 r > threshold(默认0.80) → 标记为冗余配对吧
4. 每对中保留信号得分较高的为primary，排除redundant
5. **一链仅保留1个代表品种**（除非在 `WITHIN_CHAIN_INDEPENDENT` 中声明为独立）

**独立品种（不参与冗余检测）：**
- 黑色系: SM(锰硅), SF(硅铁) — 铁合金受独立供需+锰矿进口影响
- 其他链同理

**输出：**
- `redundant_pairs` — 冗余配对列表 [{primary, redundant, chain, reason}]
- 品种级 `redundant=True/False` + `redundant_with` 字段

**闫判官根据此报告决定辩论品种取舍，按"一链一代表"原则。**

#### Step 6: 基本面验证（WebSearch/WebFetch 搜索验证）

> 📖 参见上方「🔴 链证源数据工作法」章节— 领域二（基本面/新闻/产业资料）的完整溯源规范。以下为执行细则。

**⏱️ 时序搜索规则（必须遵守）**：

| 数据类别 | 有效窗口 | 超窗处理 |
|---------|:------:|---------|
| 价格/行情 | ≤1天 | 超窗丢弃 |
| 突发新闻 | ≤3天 | 标注"X天前"+降置信度 |
| 周度数据（库存/开工率） | ≤7天 | 标注间隔天数 |
| 月度数据（产量/进出口） | ≤31天 | 标注月份+降一级 |
| 季度/半年报 | ≤45天 | 标注"可能已过时" |
| 政策/法规 | ≤90天 | 标注发布时间 |

**搜索查询必须包含时间限定词**，如 `"纯碱 库存 2026年7月 最新 周度"`，而非仅 `"纯碱 库存"`。

对每个候选品种所在产业链，使用 WebSearch/WebFetch 搜索以下基本面信息，验证产业链趋势的基本面逻辑：

```
对每个品种所在产业链，搜索 2-3 条基本面信息（含时间限定）：
查询1: "{产业链名} 供需 库存 2026年7月" → 了解产业链整体供需格局
查询2: "{品种名} 新闻 政策 价格 2026年6月 最新" → 了解近期行业动态
查询3: "{品种名} 产能 产量 开工率 最新" → 了解供给侧情况

示例：对黑色系 rb/hc
查询1: "螺纹钢 热卷 库存 需求 房地产 基建 2026年7月"
查询2: "钢铁 限产 政策 环保 粗钢产量 2026年6月"
查询3: "铁矿石 焦炭 成本 利润 钢厂 2026年 最新"
```

搜索到的每一条基本面信息写入 `fundamental_notes` 时，**必须附带数据截止日期 + 来源**，格式如下：
- `"五大钢材总库存1600.99万吨（来源：Mysteel周度数据，截至6月30日）"`
- **禁止**无时间戳的泛化表述如 `"库存偏高""需求疲弱"`
- **禁止**无来源的陈述如 `"市场普遍认为"`

---

### 接口契约（Pydantic Schema）

当本 skill 被辩论专家团集成使用时，按以下 schema 结构化产出。schema 定义在 `futures-trading-analysis` 主 skill 的"接口契约"章节。此处为子 skill 实现版。

```python
from pydantic import BaseModel
from typing import Literal, Optional

class PhaseMeta(BaseModel):
    """每条 phase 输出的元数据"""
    phase: str                     # "P2"
    agent_id: str                  # "futures-chain-analyst"
    variant: str                   # "chain_analysis"
    trace_id: str                  # 整条辩论链一致的跟踪 ID
    depends_on: list[str]          # ["P1_data", "P1_tech"]

class ChainOutput(BaseModel):
    """链证源产业链验证的最终产出"""
    variant: Literal["chain_analysis"] = "chain_analysis"
    chain_results: dict                     # 逐品种产业链分析结果（兼容现有JSON格式）
    redundant_pairs: list[dict]             # 冗余配对列表 [{"primary": "rb", "redundant": "hc", "reason": "..."}]
    chain_trends: dict[str, str]            # 逐产业链趋势方向 {"黑色系": "强势空头", ...}
    chain_consistencies: dict[str, float]   # 逐产业链一致性评分 {"黑色系": 100, ...}
    fundamental_notes: dict[str, list[str]] # 逐品种基本面验证笔记
    meta: PhaseMeta
```

**产出规范**：
- Agent 必须按 `ChainOutput` schema 产出 typed 对象
- 下游通过 `output.chain_results`、`output.redundant_pairs`、`output.chain_trends` 等属性访问
- 完全迁移至 contracts/ schema 
- `chain_results` 保持与现有逐品种JSON格式兼容，方便下游消费

### 输出格式（向后兼容）

```json
{
  "rb": {
    "chain": "黑色系",
    "chain_members": ["rb", "hc", "i", "j", "jm", "SF", "SM"],
    "term_structure": "contango",
    "basis": "走弱",
    "chain_trend": "强势空头",
    "chain_consistency": 100,
    "z_score": 1.5,
    "z_status": "正常",
    "redundant": false,
    "redundant_with": null,
    "fundamental_notes": ["黑色系整体供需宽松，库存累积", "环保限产政策松动，供给端压力增加"],
    "notes": []
  },
  "hc": {
    "chain": "黑色系",
    "term_structure": "contango",
    "chain_consistency": 100,
    "z_score": 1.3,
    "redundant": true,
    "redundant_with": "rb",
    "fundamental_notes": [],
    "notes": ["⚠️同链冗余，建议取rb"]
  }
}
```

## 版本历史

### v2.14.1 (2026-07-04)
- **移除 researcher_tools.py** — 基本面数据采集职责已剥离至独立 skill `fundamental-data-collector`
- 删除 SKILL.md 中"辩论专家团·基本面研究员接口"章节（已移至新 skill）

### v2.14.0 (2026-07-04)
- 新增 CROSS_CHAIN_VARIETIES 跨链品种清单（MA/SA/UR/EG/LC/SI/AL）
- 新增 get_dominant_chain() 主导链动态判断（支持4种市场状态）
- 新增 get_secondary_chain() / is_cross_chain_variety() / get_all_chains_for_symbol()
- 品种映射100%覆盖 futures-data-search 的 ALL_VARIETIES（66个品种交叉验证）
- 新增32个测试，总测试100/100通过
- cluster_chains() 新增 cross_chain_info 输出字段
- **目录结构标准化**：全部 .py/.json/.md 文件移至 scripts/，清除缓存的 __pycache__，修复硬编码路径
- 对照版：files/commodity-chain-analysis-v2.13-to-v2.14.diff

### v2.11.1 (2026-06-29)
- term_basis.py exchange-futures-data→futures-data-search 引用更新

### v2.11.0 (2026-06-26)
- 从futures-industry-chain-analysis拆分为独立skill
- 新增chain_verifier.py（从screen.py拆分）
- 独立config.py（产业链特有配置）

### v2.10.0 (2026-06-25)
- 产业链辩论权重优化
- 期限结构+基差分析模块
