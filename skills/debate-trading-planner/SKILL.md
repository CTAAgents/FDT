---
name: debate-trading-planner
version: 2.1.0
description: >
  通用期货交易策略制定器（策略师专用）。接收闫判官判决->合成可执行方案->传风控审核。8工具(select_contract/size_position/design_hedge/plan_entries/plan_stop/plan_take/plan_roll/exit_triggers)，不改方向不改目标价。
agent_created: true
changelog: |
  v2.1.0 (2026-07-03): 流程修正 — 输入由裁判改为"闫判官判决"；产出传给风控审核而非最终交付；履职链路更新
  v2.0.0 (2026-07-03): 升级为策略师专用 — 新增8工具清单、策略师履职链路、对话风控的red回退机制；不改方向不改目标价约束
  v1.1.0 (2026-07-01): 重构为通用接口 — 支持独立使用模式，输入输出格式去辩论化
  v1.0.0 (2026-07-01): 初始版本 — 从 futures-trading-analysis 剥离
disable: false
---

# 通用期货交易计划制定器

## 依赖
- **输入方**：`RiskOutput`（`contracts/risk.py`）
- **输出方**：`TradingPlanOutput`（`contracts/trading_plan.py`）
- **版本**：`2.0`
- **输出方式**：正文 + 末尾 ```json fence 结构化摘要

## ⚠️ 仓位计算铁律（全局强制）

**所有仓位建议和盈亏比计算必须基于权威、经过实证检验的理论模型，不得编造、不得使用"魔法数字"、不得使用固定盈亏比例。**

1. **仓位计算模型**：仓位分配必须基于以下经过实证检验的模型之一，**严禁使用凭空设定的固定百分比**（如"10%仓位"）且不做解释：
   - **凯利公式**（Kelly Criterion）：`f* = (bp - q) / b`，其中b为赔率、p为胜率、q为败率。需明确说明使用的胜率/赔率假设。
   - **风险平价**（Risk Parity）：基于波动率贡献等权重分配，需说明波动率数据来源和计算周期。
   - **VaR/CVaR约束**：基于在险价值设定仓位上限，需说明置信水平和持有期。
   - **固定分数模型**（Fixed Fractional）：`仓位 = 总资金 × 固定风险比例 ÷ 单笔止损金额`，需说明风险比例的理论依据。
   - **倒波动率加权**：仓位与历史波动率成反比。

2. **盈亏比计算**：
   - 必须基于**具体技术位**（支撑位/阻力位/ATR倍数/前高前低），而非随意设定的"1.5:1""2:1"等固定比例。
   - 止损距离：必须有合理依据（ATR倍数、波动率乘数、技术位外延等），**不得使用固定比例止损**（如"3%止损"不做解释）。
   - 目标位：需说明技术依据（关键阻力/支撑、等距目标、斐波那契扩展等）。

3. **禁止魔法数字**：所有出现在方案中的数字（仓位百分比、止损宽度、盈亏比、ATR倍数等）必须附带明确的推导过程和理论依据。**严禁使用未经实证研究支撑的固定数值。**

4. **禁止编造**：**严禁凭空编造仓位建议、虚构回测盈亏比、捏造止损目标位。** 无法获取合理的止损/目标位时应如实报告，使用替代方案（如"使用前低作为止损"）需说明合理性。

## 概述

交易执行方案生成工具。接收风控裁定结果，生成具体的入场/止损/目标/仓位/对冲方案。
不依赖数据采集或信号分析模块，纯LLM推理+规则执行。

**可复用于**：期货交易辩论专家团、自定义交易系统、策略回测后的执行方案生成、投资组合管理等。

## 独立使用模式

### 输入格式

接收风控裁定结果和市场数据：

```json
{
  "risk_assessment": {
    "excluded": ["排除品种"],
    "watch": ["观察品种"],
    "chain_limits": {
      "产业链名": {"actual": 值, "limit": 值, "status": "超标/正常"}
    },
    "verdicts": {
      "品种代码": {"status": "可执行/观察/排除", "risk_level": "高/中/低", "note": "备注"}
    }
  },
  "symbols": [
    {
      "id": "品种代码",
      "direction": "BUY/SELL",
      "price": 当前价格,
      "technical": {
        "trend_stage": "主升/主跌/衰竭/启动/反转",
        "atr": 数值,
        "support": 支撑位,
        "resistance": 阻力位
      },
      "term_structure": "contango/back/flat"
    }
  ]
}
```

### 输出格式

每个品种输出：

```json
{
  "symbol": "SA",
  "direction": "SELL",
  "options": [
    {
      "type": "激进/保守/分批",
      "entry": "入场描述和价位",
      "stop_loss": {"price": 止损价, "method": "ATR/技术位", "amount": 亏损金额},
      "target": {"price": 目标价, "risk_reward": 盈亏比},
      "position": "仓位百分比",
      "validity": "有效期限"
    }
  ],
  "portfolio_note": "组合约束说明",
  "hedge_suggestion": "对冲建议或不建议"
}
```

### 独立调用示例

```bash
# 传入风控裁定生成交易方案
echo '{"risk_assessment":{"excluded":[],...},"symbols":[...]}' | \
  python -c "import sys,json; data=json.load(sys.stdin); # 应用仓位规则生成方案"
```

或直接由LLM Agent加载本skill后，基于传入的数据执行。

## 接口契约（Pydantic Schema）

当本 skill 被辩论专家团集成使用时，按以下 schema 结构化产出。schema 定义在 `futures-trading-analysis` 主 skill 的"接口契约"章节。

```python
from pydantic import BaseModel
from typing import Literal, Optional

class PhaseMeta(BaseModel):
    """每条 phase 输出的元数据"""
    phase: str                     # "P5"
    agent_id: str                  # "futures-trading-strategist"
    variant: str                   # "trading_plan"
    trace_id: str                  # 整条辩论链一致的跟踪 ID
    depends_on: list[str]          # ["P1_data", "P1_tech", "P2_chain", "P3_bull", "P3_bear", "P3b_judge", "P4_risk"]

class StopLoss(BaseModel):
    price: float
    method: Literal["ATR", "技术位", "固定比例"]
    amount: float                  # 预计亏损金额
    note: str                      # 说明依据

class Target(BaseModel):
    price: float
    risk_reward: float             # 盈亏比
    note: str                      # 支撑位/前高/等距目标 等技术依据

class PlanOption(BaseModel):
    type: Literal["激进", "保守", "分批"]
    entry: str                     # 入场描述和价位
    stop_loss: StopLoss
    target: Target
    position: str                  # 仓位百分比
    validity: str                  # 有效期限

class TradingPlan(BaseModel):
    """策执远交易计划的最终产出"""
    variant: Literal["trading_plan"] = "trading_plan"
    plans: dict[str, list[PlanOption]]     # 每品种2-3个选项
    portfolio_note: str                    # 组合约束说明
    hedge_suggestion: Optional[str]        # 对冲建议
    meta: PhaseMeta
```

**产出规范**：
- Agent 必须按 `TradingPlan` schema 产出 typed 对象
- 下游通过 `output.plans`、`output.portfolio_note` 等属性访问
- 完全迁移至 contracts/ schema 

## 辩论专家团集成模式

当被 `futures-trading-analysis` 辩论系统的 **策略师（策执远）** Agent 加载时：

**输入**：由闫判官传入 `judgment_to_strategist` 结构化对象（含胜方提案+败方提案+评分）
**产出**：按 `TradingPlan` schema 产出 typed 对象 → SendMessage + 文件双写 → 传风控审核
**约束**：禁止祈使句命令用户操作，禁止改方向/改目标价

### 策略师履职链路

```
① 接闫判官判决（winner + 胜方提案 + 败方提案参考）
② select_contract: 合约选型（主力→次主→交割月检查）
③ plan_entries: 建仓方案（一次性/分批，含价位区间）
④ plan_stop + plan_take: 止损止盈（ATR倍数/技术位，附验证参数）
⑤ design_hedge: 对冲检查（跨期/跨品种）
⑥ plan_roll: 移仓计划（交割月前换月时间点+预期成本）
⑦ exit_triggers: 动态退出条件
⑧ size_position: 按凯利公式算仓位 → 打包 → 传风控审核
⑨ 若风控red → 修改 → 再审（最多1轮）
```

### 策略师工具清单

```json
[
  {"name": "select_contract", "desc": "合约选型：主力/次主/当月，检查交割日与流动性"},
  {"name": "size_position", "desc": "按凯利公式/固定分数模型反推开仓手数"},
  {"name": "design_hedge", "desc": "跨期/跨品种对冲方案设计"},
  {"name": "plan_entries", "desc": "建仓节奏：一次性 vs 分批（含价位区间）"},
  {"name": "plan_stop", "desc": "止损设置：ATR倍数/技术位，附验证参数"},
  {"name": "plan_take", "desc": "止盈目标：T1/T2/T3分级止盈"},
  {"name": "plan_roll", "desc": "移仓计划：交割月前换月时间点+预期成本"},
  {"name": "exit_triggers", "desc": "动态退出条件：什么情况下提前离场"}
]
```

## 执行方法

### Step 1: 筛选品种

- excluded → 跳过，不出计划
- watch → 半仓/小仓设计
- 可执行 → 正常出计划

### Step 2: 仓位分配

```
可执行: 8-10%    观察: 4-5%    排除: 0%
同链 ≤ chain_limits值（默认10%）
强相关品种合并为单一敞口
前3大 ≤ 30%
总仓 ≤ 80%
```

### Step 3: 入场方案

每品种2-3个选项：

| 类型 | 适合场景 |
|:----:|---------|
| 激进 | 趋势明确、流动性好 → 现价入场 |
| 保守 | 有回调风险 → 等支撑位 |
| 分批 | 方向明确但波动大 → 分2-3批 |

### Step 4: 止损设置

**禁止使用固定倍数（如1.5×ATR）作为默认止损宽度。** 止损倍数必须按品种从数据库中验证得到，当前已验证参数如下：

| 品种 | 止损倍数 | 来源 | 触发率(半年) | 误杀率 |
|:----:|:--------:|:----:|:----------:|:-----:|
| SA(纯碱) | **1.5×ATR** | ✅ 已验证 | 15.7% | 0.0% |
| RB(螺纹钢) | **1.8×ATR** | ✅ 已验证 | 35.3% | 0.0% |
| SM(锰硅) | **1.5×ATR** | ✅ 已验证 | 23.5% | 0.0% |
| NI(沪镍) | **1.8×ATR** | ✅ 已验证 | 27.7% | 3.8% |
| FU(燃油) | **2.0×ATR** | ✅ 已验证 | 13.1% | 12.5% |
| 其他品种 | 1.5×ATR(默认) | ⚠️ 待验证 | — | — |

**未在表中的品种**使用1.5×ATR默认值，但必须在方案中标注"本止损倍数未经数据库验证"。

| 类型 | 方法 | 适用场景 |
|:----:|------|---------|
| ATR追踪 | 入场价 ± 品种专属止损倍数×ATR | **优先使用** |
| 技术位 | 前低/前高/通道外 | ATR无法覆盖时使用 |
| 固定比例 | 总资金1-2% | 仅作为补充参考 |

### Step 5: 止盈目标

**禁止使用固定倍数（如2R）作为默认T2目标。** T2目标倍数必须基于ADX>30强趋势区间的价格延续距离确定，当前已验证参数如下：

| 品种 | T2目标 | ≥目标达成率 | 平均延续(ATR) | 说明 |
|:----:|:------:|:----------:|:-------------:|:----:|
| SA(纯碱) | **2.5R** | 62.9% | 3.12x | 2R偏保守 |
| RB(螺纹钢) | **2.0R** | 70.0% | 3.83x | ✅ 合理 |
| SM(锰硅) | **1.2R** | 41.4%(≥1.5R) | 1.11x | ⚠️ 2R严重高估 |
| NI(沪镍) | **2.0R** | 53.8% | 2.41x | ✅ 合理 |
| FU(燃油) | **2.0R** | 75.0% | 3.28x | ✅ 合理 |
| 其他品种 | 2.0R(默认) | ⚠️ 待验证 | — | — |

**参数来源**: `C:\Users\yangd\Documents\WorkBuddy\.workbuddy\memory\MEMORY.md` → `止损/目标参数自我演化规则`
**验证脚本**: 内联调用 `daily_data` 表的 ATR/ADX 验证（约200行/品种，2025-2026数据）
**更新频率**: 每季度重新验证一次

```
T1: DC20轨道回归 → 减30%（无品种差异）
T2: 品种专属倍数R → 减50%
T3: 趋势终结 → 清仓
盈亏比要求: ≥ 1.5:1（T2目标对应）
