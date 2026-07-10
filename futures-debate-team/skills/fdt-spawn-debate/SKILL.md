---
agent_created: true
name: fdt-spawn-debate
description: "FDT内部流程说明书 v1.1 — 禁止裁剪的完整多Agent辩论流程（P3-P6）+A01文件通信协议"
---

# fdt-spawn-debate — 完整多Agent辩论流程

> ⚠️ **禁止对辩论流程进行任何裁剪**。以下每一步都是强制的，不因时间/复杂度/便捷性跳过。
> 本技能定义的是**最小不可裁剪流程**，不是建议流程。

## 适用范围

当盘中信号监控检测到`STRONG`（≥50）或`WATCH`（≥40）信号时，执行本流程。

## 核心规则

| # | 规则 | 来源铁律 |
|:-:|:----|:---------|
| 1 | **品种独立性**：每个品种独立spawn完整的Agent链条。严禁一个Agent同时处理多个品种 | D01 |
| 2 | **Spawn类型**：必须用 `subagent_type: "general-purpose"`，不可用expert subagent_type | D05 |
| 3 | **角色注入**：角色prompt在spawn prompt中手动注入，不依赖MD自动加载 | D05 |
| 4 | **禁止代写**：明鉴秋不得自行撰写论据、裁决、方案。必须spawn对应Agent | D01/D02 |
| 5 | **禁止串线**：Agent之间不得互相SendMessage。产出一律写文件 | S02 |
| 6 | **文件就绪**：spawn下游前，上游文件必须已稳定≥5秒（poll_file_ready） | S01/S04 |
| 7 | **禁止胶水**：不得编写一次性Python脚本模拟Agent产出 | 零胶水代码铁律 |
| 8 | **Phase门禁**：P6汇总前检查是否有缺失的产出文件。缺失则拒绝生成报告 | D03 |
| 9 | **D06降级**：闫判官spawn 2次均无产出 → 基于证真/慎思论据独立裁决 | D06 |
| 10 | **🔴 文件优先通信（2026-07-10确立·P0）**：Agent产出**只写文件，不使用SendMessage**。明鉴秋只用poll_file_ready轮询文件就绪后读取。SendMessage在自动化context中路由不可靠——Agent完成但消息永不送达 | A01 |

## 根因

`expert subagent_type` spawn时MD frontmatter的`allowed-tools`不被平台加载，Write工具不可用。
**修复**：统一使用`subagent_type: "general-purpose"`（拥有`Tools: *`全部工具）+ 手动注入角色prompt。

## 🔴 自动化环境特殊处理（2026-07-10事故修复）

### 问题

自动化context中，Agent spawn后SendMessage(recipient="main")**永不送达**。根因：自动化main agent处于单次执行模式，没有持续的消息监听循环。Agent完成分析→SendMessage→消息无人接收→静默丢失。

两次事故记录（2026-07-10）：
- 16:25轮：5次spawn失败，最终用Python脚本模拟→违反D01/D02
- 20:10轮：3个研究员spawn成功但SendMessage未达→入降级直接执行

### 永久修复：文件唯一通信协议

```
❌ 旧方案: Agent产出 → SendMessage → main接收（自动化中路由断）
✅ 新方案: Agent产出 → Write文件 → main poll_file_ready → Read文件
```

### 修复实施

每个Agent的spawn prompt末尾必须写：
```
❗【通信协议】完成分析后将结果直接写入文件 {output_path}。
不要使用SendMessage通知任何人。文件写入完毕即视为任务完成。
```

明鉴秋调度代码：
```python
# 1. Spawn Agent（background）
agent_id = Agent(
    description=f"链证源-{sym}",
    subagent_type="general-purpose",
    run_in_background=True,
    prompt=build_prompt(sym, output_path)
)

# 2. 轮询文件就绪（15秒间隔，最多15分钟）
if not poll_file_ready(output_path, timeout=900, stable_seconds=5):
    # 3. 超时→降级：明鉴秋自行完成该阶段分析
    print(f"[FALLBACK] {sym} {phase} Agent超时无产出，明鉴秋降级直行")
    inline_analysis(sym)
else:
    data = read_json(output_path)
```

### 降级规则

| 阶段 | 超时时间 | 超时动作 |
|:-----|:--------|:---------|
| P1.5 链证源 | 600s | 明鉴秋用WebSearch自行完成产业链分析 |
| P3 观澜/探源 | 600s | 明鉴秋用WebSearch自行提供技术/基本面数据 |
| P4 证真/慎思 | 600s | 明鉴秋基于已有数据自行构建多空论据 |
| P5 闫判官 | 300s | D06降级→明鉴秋基于P4论据独立裁决 |
| P5 策执远 | 300s | 明鉴秋按ATR公式计算入场/止损/目标 |
| P5 风控明 | 300s | 明鉴秋基于裁决+风控规则自行审核 |

**关键**: 降级≠跳过。降级时明鉴秋**必须完成该阶段的分析工作**，只是不通过Agent spawn来完成。

## 完整辩论流程（P3-P6）— 不可裁剪

### 数据准备

每个品种需要准备以下数据（从P1扫描JSON + P1.5链分析JSON提取）：

```
symbol: 品种代码
name: 品种中文名
direction: 信号方向(bull/bear)
price: 当前价格
total: 总分
grade: STRONG/WATCH
adx: ADX值
rsi: RSI值
cci: CCI值
dc20_dir: DC20方向
dc55_trend: DC55趋势
vol_ratio: 成交量比
vol_style: 成交量风格
bb_width: 布林带宽度
bb_squeeze: 布林带是否挤压
fundamental: 基本面数据摘要
chain: 产业链
chain_trend: 产业链趋势
atr: ATR值
```

### 流程总览

```
每个品种循环执行以下完整链条（品种之间可并行）:

  证真(正方) → Write(p4_zhengzhen_{sym}.json)
     并行              
  慎思(反方) → Write(p4_zhensi_{sym}.json)
     
     ↓ 等待两个文件就绪
     
  闫判官(裁决) → Read(证真+慎思) → Write(p5_judge_{sym}.json)
  
     ↓ 等待裁决文件就绪
     
  一致性裁判(审计) → Read(证真+慎思+裁决) → Write(p5_coherence_{sym}.json)
  (非阻断审计步, 超时不阻塞下游)
  
     ↓
     
  策执远(方案) → Read(裁决) → Write(p5_trading_plan_{sym}.json)
  
     ↓ 等待方案文件就绪
     
  风控明(审核) → Read(方案) → Write(p5_risk_review_{sym}.json)

     ↓ 等待审核文件就绪
     
明鉴秋汇总 → 合并全部产出的JSON → 生成debate_results.json + HTML报告
```

### Step 1: spawn 证真（正方辩手）— 每个品种独立

```python
Agent(
    description=f"证真辩手-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=10,
    prompt=f"""
你是正方辩手（证真），期货辩论专家团成员。

❗JSON要求：所有字符串文本中禁止使用任何引号（包括中英文引号）。
需要引用的概念用括号代替或无引号。

闫判官指定的信号方向: {direction}（这是你要辩护的方向）
品种: {symbol} {name}
价格: {price}

【P1技术面数据】
扫描总分: {total} | 等级: {grade}
ADX: {adx}, RSI: {rsi}, CCI: {cci}
DC20方向: {dc20_dir}, DC55趋势: {dc55_trend}
成交量比: {vol_ratio}, 成交量风格: {vol_style}
布林带宽度: {bb_width}, 布林带挤压: {bb_squeeze}

【P3基本面数据】
{fundamental}

【产业链数据】
链: {chain}, 链趋势: {chain_trend}

你的任务：撰写至少5条{dir_label}论据。
每条论据必须包含：id, claim, evidence, reasoning, family(F1-F5), confidence(0-1)

输出文件：{output_path}
完成后用Write工具直接写入{output_path}。不要使用SendMessage通知任何人。
"""
)
```

### Step 2: spawn 慎思（反方辩手）— 每个品种独立（可与Step 1并行）

```python
Agent(
    description=f"慎思辩手-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=10,
    prompt=f"""
你是反方辩手（慎思），期货辩论专家团成员。

❗JSON要求：所有字符串文本中禁止使用任何引号。

闫判官指定的信号方向: {direction}（这是你要质疑的方向）
品种: {symbol} {name}

【P1技术面数据】
扫描总分: {total} | 等级: {grade}
ADX: {adx}, RSI: {rsi}, CCI: {cci}
DC20方向: {dc20_dir}, DC55趋势: {dc55_trend}
成交量比: {vol_ratio}, 成交量风格: {vol_style}
布林带宽度: {bb_width}, 布林带挤压: {bb_squeeze}

【P3基本面数据】
{fundamental}

【产业链数据】
链: {chain}, 链趋势: {chain_trend}

你的任务：撰写至少5条{opposite_dir_label}论据。
格式同上。输出文件：{output_path}。完成后用Write直接写入文件，不使用SendMessage。
"""
)
```

### Step 3: 轮询等待

```python
import os, time
def poll_file(path, timeout=300, stable_seconds=3):
    start = time.time()
    last_size = -1
    stable_count = 0
    while time.time() - start < timeout:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > 0 and size == last_size:
                stable_count += 1
                if stable_count >= stable_seconds:
                    return True
            else:
                stable_count = 0
            last_size = size
        time.sleep(5)
    return False
```

### Step 4: spawn 闫判官（裁决）— 每个品种独立

```python
Agent(
    description=f"闫判官裁决-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=12,
    prompt=f"""
你是闫判官，期货辩论专家团裁决官。

先用Read工具读以下两个文件：
1. {zhengzhen_path}（证真/多方论据）
2. {zhensi_path}（慎思/空方论据）

品种: {symbol} {name} | 当前价格: {price} | ATR: {atr}

读完后做裁决。

JSON输出格式：
{{
  "agent": "闫判官",
  "symbol": "{symbol}",
  "generated_at": "...",
  "verdict": "BUY/SELL/HOLD",
  "confidence": "高/中/低",
  "bull_score": 0-100,
  "bear_score": 0-100,
  "winner": "bull/bear/tie",
  "reasoning": "裁决逻辑（不使用引号）",
  "key_observation": "关键判断",
  "score_breakdown": {{ "趋势": 0-100, "量价": 0-100, "供需": 0-100, "持仓": 0-100, "宏观": 0-100, "估值": 0-100 }}
}}

输出文件：{judge_path}
注意：只能读文件，不得SendMessage给任何Agent。

❗ 现货基准选取警示（2026-07-10 实战教训）：
当多方和空方引用不同现货基准（如进口CFR vs 国内现货/挂牌价）时：
- 闫判官必须明确说明选择了哪个基准、为何选择
- 不得片面采纳某一方的基准而不做解释
- 建议优先参考：①交易所仓单报价 ②权威机构现货均价 ③盘面近月合约价格
- 若多源差异过大，在reasoning中注明"基准选取存在±X%误差范围"
"""
)
```

### Step 5: spawn 一致性裁判（held-out judge）— 非阻断审计步

**不能被裁剪。这是独立审计层，与闫判官形成制衡。**

```python
Agent(
    description=f"一致性裁判-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=8,
    prompt=f"""
你是外部一致性裁判（futures-judge-heldout）。
你独立审计辩论裁决的一致性，不重新撰写论据。

先用Read工具读以下三个文件：
1. {zhengzhen_path} — 证真论据
2. {zhensi_path} — 慎思论据
3. {judge_path} — 闫判官裁决

评估：
- 闫判官的裁决是否基于双方论据
- 是否有明显遗漏的证据或逻辑跳跃
- 给出coherence_score(0-100)和简要审计意见

输出文件：{coherence_path}
格式：{{ "agent": "一致性裁判", "symbol": "{symbol}", "coherence_score": 85, "rationale": "审计意见（不使用引号）", "agrees": true/false }}

注意：仅审计，不重写论据。不得SendMessage。
"""
)
```

### Step 6: spawn 策执远（交易方案）— 每个品种独立

```python
Agent(
    description=f"策执远方案-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=8,
    prompt=f"""
你是策执远，交易策略师。

先用Read工具读文件: {judge_path}

品种: {symbol} {name} | 价格: {price} | ATR: {atr}

交易方案规则：
- BUY裁决: 入场{price}附近, 止损{price}-2*ATR, 目标1{price}+2*ATR, 目标2{price}+3*ATR
- SELL裁决: 入场{price}附近, 止损{price}+2*ATR, 目标1{price}-2*ATR, 目标2{price}-3*ATR
- HOLD裁决: 观望

仓位建议：
- 置信度高: 正常仓位15-25%
- 置信度中: 轻仓10-15%
- 置信度低: 极小仓位5%

输出文件：{plan_path}。完成后用Write直接写入文件，不使用SendMessage。
格式：{{ "symbol": "{symbol}", "action": "做多/做空/观望", "entry": {price}, "stop_loss": ..., "target_1": ..., "target_2": ..., "position_size": "...", "timeframe": "120m波段", "note": "..." }}
"""
)
```

### Step 7: spawn 风控明（风控审核）— 每个品种独立

```python
Agent(
    description=f"风控审核-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=8,
    prompt=f"""
你是风控明，风险管理总监。

先用Read工具读文件: {plan_path}

品种: {symbol} {name}

6层风控检查：
1. ADX趋势强度（ADX<25 → 趋势弱标记）
2. 成交量配合度（vol_ratio<0.6 → 量能不足标记）
3. 超买/超卖风险（RSI>70或<30）
4. 数据源质量（子周期数据为AKShare分钟降级）
5. 仓位合理性
6. 其他风险

品种扫描数据: ADX={adx}, RSI={rsi}, 成交量={vol_ratio}

输出文件：{risk_path}。完成后用Write直接写入文件，不使用SendMessage。
格式：{{ "symbol": "{symbol}", "risk_level": "低/中/高", "veto": false, "risk_items": [["ADX趋势弱","注意","ADX<25趋势不明朗"]], "recommendation": "可执行/需谨慎/否决" }}
"""
)
```

### Step 8: 明鉴秋汇总

读取**所有**品种的**全部**6个产出文件：

```
每个品种: p4_zhengzhen_{sym}.json + p4_zhensi_{sym}.json 
          + p5_judge_{sym}.json + p5_coherence_{sym}.json
          + p5_trading_plan_{sym}.json + p5_risk_review_{sym}.json
```

合并为 `debate_results.json`，然后调用：
```bash
python phase3_generate_report.py \
  --debate debate_results.json \
  --output . \
  --output-html debate_report.html
```

**Phase门禁检查（D03）**：若任一缺少 `p4_zhengzhen_{sym}.json` / `p4_zhensi_{sym}.json` / `p5_judge_{sym}.json` 文件 → **拒绝生成报告**。

## 产出文件清单（每个品种独立）

| 阶段 | 产出文件 | 说明 |
|:----|:---------|:-----|
| P4 | `p4_zhengzhen_{sym}.json` | 证真论据（至少5条） |
| P4 | `p4_zhensi_{sym}.json` | 慎思论据（至少5条） |
| P5 | `p5_judge_{sym}.json` | 闫判官裁决（含六维评分） |
| P5 | `p5_coherence_{sym}.json` | 一致性裁判审计意见 |
| P5 | `p5_trading_plan_{sym}.json` | 策执远交易方案 |
| P5 | `p5_risk_review_{sym}.json` | 风控明审核 |
| P6 | `debate_results.json` | 汇总结果 |
| P6 | `debate_report_*.html` | HTML报告 |

## 路径常量

```
FDT_ROOT = C:\Users\yangd\.workbuddy\plugins\marketplaces\my-experts\plugins\futures-debate-team
SIGNAL_DIR = C:\Users\yangd\Documents\Signal
REPORT_SCRIPT = {FDT_ROOT}/skills/futures-trading-analysis/scripts/phase3_generate_report.py
AGENTS_DIR = {FDT_ROOT}/agents/
   ├── futures-affirmative-debater.md  (证真)
   ├── futures-opposition-debater.md   (慎思)
   ├── futures-judge.md                (闫判官)
   ├── futures-judge-heldout.md        (一致性裁判)
   ├── futures-trading-strategist.md   (策执远)
   └── futures-risk-manager.md         (风控明)
```

## 已知故障与预防

### F1: JSON含未转义中文引号
- **现象**: evidence/reasoning字段中出现"趋势加速"等引号，解析失败
- **预防**: spawn prompt中显式声明"所有字符串文本中禁止使用任何引号"
- **修复**: 已写入则用 `(?<=[\u4e00-\u9fff])"([^"]*?)"(?=[，。、；：,])` → 中文括号

### F2: Agent超时无产出
- **预防**: 前台spawn + prompt末尾明确写"完成后直接用Write工具写入{path}"
- **处理**: 若max_turns完毕且文件不存在 → 记录为降级。**不得自行代写论据**

### F3: 一致性裁判超时
- 非阻断审计步，不阻塞下游策执远/风控明流程
- 超时则标记"一致性审计未完成"，继续执行后续步骤

## 实地验证记录（2026-07-10）

| 批次 | Agent | 正常 | 并行数 |
|:----|:------|:----:|:------|
| 第1批 | 证真+慎思 | ✅ | 每个品种各1个，N个并行 |
| 第2批 | 闫判官 | ✅ | 每个品种1个，N个串行 |
| 第3批 | 策执远 | ✅ | 每个品种1个，N个串行 |
| 第4批 | 风控明 | ✅ | 每个品种1个，N个串行 |

**结论**: general-purpose spawn + Write工具 = 正常工作。禁止以此为由跳过spawn。
