---
agent_created: true
name: fdt-spawn-debate
description: "FDT内部流程说明书 — 禁止裁剪的完整多Agent辩论流程（P3-P6）+A01文件通信协议"
---

# fdt-spawn-debate — 完整多Agent辩论流程

> ⚠️ **禁止对辩论流程进行任何裁剪**。以下每一步都是强制的，不因时间/复杂度/便捷性跳过。
> 本技能定义的是**最小不可裁剪流程**，不是建议流程。

## 适用范围

quant-daily 仅做负向过滤：排除无数据/无市场的品种，全量监控其余品种。
监控到方向性信号（|total| ≥ DEBATE_ENTRY_MIN_ABS，当前=20 即 WEAK 及以上，已过滤 NOISE 级）即进入辩论候选池；
评分仅作方向初始值与辩论优先级，不作为排除辩论的硬性门槛。
哪些品种更适合交易，由辩论→策略→风控→裁决环节决定。
🔴 **无信号跳过辩论（统一阈值）**：若扫描后 `candidates` 为空（全品种 `|total| < DEBATE_ENTRY_MIN_ABS`）→ **不 spawn 任何辩论 Agent**，直接回报"无有效信号，跳过辩论"。阈值唯一真相源 = `config/settings.py:DEBATE_ENTRY_MIN_ABS`，本文件禁止写死。

## 核心规则

| # | 规则 | 来源铁律 |
|:-:|:----|:---------|
| 1 | **品种独立性**：每个品种独立spawn完整的Agent链条。严禁一个Agent同时处理多个品种 | D01 |
| 2 | **Spawn类型**：**所有文件产出Agent**（P1.5链证源/P3研究员/P4辩手/P5裁决/风控/一致性裁判）统**必须用 `subagent_type: "general-purpose"`**，不可用expert subagent_type。Expert spawn时Tools为空(无Write)→文件写不出去 | D05 |
| 3 | **角色注入**：角色prompt在spawn prompt中手动注入，不依赖MD自动加载 | D05 |
| 4 | **禁止代写**：明鉴秋不得自行撰写论据、裁决、方案。必须spawn对应Agent | D01/D02 |
| 5 | **禁止串线**：Agent之间不得互相SendMessage。产出一律写文件 | S02 |
| 6 | **文件就绪**：spawn下游前，上游文件必须已稳定≥5秒（poll_file_ready） | S01/S04 |
| 7 | **禁止胶水**：不得编写一次性Python脚本模拟Agent产出 | 零胶水代码铁律 |
| 8 | **Phase门禁**：P6汇总前检查是否有缺失的产出文件。缺失则拒绝生成报告 | D03 |
| 9 | **D06降级**：闫判官spawn 2次均无产出 → 基于多头分析员/空头分析员论据独立裁决 | D06 |
| 10 | **🔴 文件优先通信**：Agent产出**只写文件，不使用SendMessage**。明鉴秋只用poll_file_ready轮询文件就绪后读取。SendMessage在自动化context中路由不可靠——Agent完成但消息永不送达 | A01 |
| 11 | **🔴 ADX角色反转**：ADX低位鼓励趋势启动确认、高位警示趋势过热。所有spawn prompt中必须注入ADX角色反转规则——不得以ADX<20作为"无趋势=不做"的首要理由。裁决reasoning中ADX提及占比≤1/3。监控条件不得以ADX为首要触发标准 | R11 |
| 12 | **🔴 L1产出校验**：每个Agent写文件→poll_file_ready就绪后，必须调用 `validate_agent_output.py --file <path> --phase <P4/P5_JUDGE/P5_RISK>` 做JSON解析+结构校验。校验失败（exit≠0，多为裸引号致JSON损坏）→ 立即重spawn该Agent（最多2次）。未校验不得进入下一阶段 | R29 |
| 13 | **🔴 Spawn 重试协议**：调用 Agent 工具 spawn 子Agent 时若返回工具错误（如 402 Insufficient Balance 等**瞬时**错误），立即用相同参数重试同款 spawn 最多2次（间隔5s），仍失败才进入降级（D06/明鉴秋直行）。禁止因单次瞬时错误放弃该阶段辩论 | R32 |

## 辩论缺员降级与 LLM 工程化

### 缺员降级（degrade-on-failure）

子 Agent 超时 / 缺失 / 产出损坏时，**以可用输入继续**，而非整轮中止：

- 某品种缺 `p4_bullish` / `p4_bearish` → 闫判官拿到的论据不全，裁决标注 `partial_evidence`，仍出裁决。
- 缺 `p5_judge` → 该品种在 assemble 阶段跳过（run_debate.assemble 已实现），不阻断其他品种。
- 缺 `p5_risk_review` → 该品种标 `仅裁决`，仍进报告。
- 主管 spawn 完毕后若仍有缺产出品种，运行
  `python scripts/run_debate.py repair --scan <json> --workspace <ws>`
  生成 `repair_plan_*.json` 补辩计划，重 spawn 即可。

### 角色化 LLM 档案（约定层）

各辩论角色的 model / temperature / max_tokens 建议值单一真相源 =
`skills/quant-daily/scripts/config/settings.py:LLM_PROFILE_MAP`。

run_debate 已在每个 spawn prompt 末尾注入【模型建议·约定层】行（如
`model=deepseek-v4-flash temperature=0.0`）。**团队主管 spawn 子 Agent 时应据此设置
model / temperature**（若平台支持 per-spawn 覆盖则生效；否则仅为建议，不报错）。

角色默认值：观澜 0.1 / 多头分析员·空头分析员 0.4 / 闫判官·一致性裁判 0.0 / 风控明 0.2，
均用 `deepseek-v4-flash`，max_tokens 1500~4000 按角色粒度递减。

## 根因

`expert subagent_type` spawn时MD frontmatter的`allowed-tools`不被平台加载，Write工具不可用。
**修复**：统一使用`subagent_type: "general-purpose"`（拥有`Tools: *`全部工具）+ 手动注入角色prompt。

## 自动化环境特殊处理

### 问题

自动化context中，Agent spawn后SendMessage(recipient="main")**永不送达**。根因：自动化main agent处于单次执行模式，没有持续的消息监听循环。Agent完成分析→SendMessage→消息无人接收→静默丢失。

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
    # ── L1产出校验（R29：防止裸引号等JSON损坏静默流入下游）──
    from pathlib import Path
    import subprocess, json as _json
    _vresp = subprocess.run(
        ["C:/Program Files/Python312/python.exe",
         os.path.join(fdt_root, "scripts", "validate_agent_output.py"),
         "--file", output_path, "--phase", phase],
        capture_output=True, text=True,
    )
    _vresult = _json.loads(_vresp.stdout or "{}")
    if not _vresult.get("valid"):
        print(f"[L1-FAIL] {sym} {phase}: {_vresult.get('error')}")
        # 最多重spawn 2次
        for _retry in range(2):
            print(f"[L1-RETRY] {sym} {phase} 第{_retry+1}次重spawn")
            Agent(  # 复用原spawn参数，prompt追加: 严禁裸引号，JSON必须合法
                description=f"{phase}-{symbol}-retry{_retry+1}",
                subagent_type="general-purpose",
                prompt=orig_prompt + "

🔴 上轮产出JSON损坏（裸引号/未转义），重做：所有字符串禁用任何引号，用括号代替。完成后Write合法JSON。",
                model="default", max_turns=10,
            )
            if poll_file_ready(output_path, timeout=900, stable_seconds=5):
                _r2 = subprocess.run(
                    ["C:/Program Files/Python312/python.exe",
                     os.path.join(fdt_root, "scripts", "validate_agent_output.py"),
                     "--file", output_path, "--phase", phase],
                    capture_output=True, text=True,
                )
                if _json.loads(_r2.stdout or "{}").get("valid"):
                    data = read_json(output_path)
                    break
        else:
            raise RuntimeError(f"[L1-FATAL] {sym} {phase} 校验2次重spawn仍失败")
```

### 降级规则

| 阶段 | 超时时间 | 超时动作 |
|:-----|:--------|:---------|
| P1.5 链证源 | 600s | 明鉴秋用WebSearch自行完成产业链分析 |
| P3 观澜/探源 | 600s | 明鉴秋用WebSearch自行提供技术/基本面数据 |
| P4 多头分析员/空头分析员 | 600s | 明鉴秋基于已有数据自行构建多空论据 |
| P5 闫判官 | 300s | D06降级→明鉴秋基于P4论据独立裁决（含交易参数） |
| P5 风控明 | 300s | 明鉴秋基于闫判官裁决+风控规则自行审核 |

**关键**: 降级≠跳过。降级时明鉴秋**必须完成该阶段的分析工作**，只是不通过Agent spawn来完成。

## Spawn 重试协议

### 问题

盘中自动化可能出现 `402 Insufficient Balance` 等**瞬时** spawn 错误——子Agent 实际已运行并写入产物，但 Agent 工具返回报错。若无重试机制，存在静默断裂风险（若当次产物未落盘则整阶段丢失）。

### 永久修复：spawn 工具错误立即重试

明鉴秋（或自动化主循环）在调用 Agent 工具 spawn 子Agent 时，必须包裹重试：

```python
import time

def spawn_with_retry(spawn_fn, max_retry=2, wait_s=5):
    """spawn 子Agent，遇工具瞬时错误自动重试。仍失败抛异常交降级处理。"""
    last_err = None
    for attempt in range(max_retry + 1):
        try:
            return spawn_fn()          # 内部调用 Agent(...) 工具
        except Exception as e:          # 402 Insufficient Balance 等瞬时错误
            last_err = e
            if attempt < max_retry:
                print(f"[SPAWN-RETRY] 第{attempt+1}次spawn失败({e})，{wait_s}s后重试")
                time.sleep(wait_s)
                continue
    raise RuntimeError(f"[SPAWN-FATAL] spawn 2次重试仍失败: {last_err}")

# 用法：将每个 Agent(...) 调用包进 spawn_with_retry
spawn_with_retry(lambda: Agent(
    description=f"多头分析员-{symbol}",
    subagent_type="general-purpose",
    prompt=build_prompt(symbol, output_path),
))
```

### 与 L1 校验重试的区别

| 层级 | 触发 | 重试对象 | 上限 |
|:----|:----|:--------|:----|
| **Spawn重试** | Agent 工具调用本身报错（402等） | 整个 spawn 动作 | 2次 |
| **L1校验重试** | 产物文件JSON损坏/缺字段 | 重spawn该Agent | 2次 |

两者独立：Spawn重试解决"没跑起来"，L1重试解决"跑起来但产出坏"。

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

  **步1** 多头分析员(正方) v1 → Write(p4_bullish_{sym}.json) — 立论
     ↓ 等待多头文件就绪
     
  **步2** 空头分析员(反方) v1 → Read(p4_bullish) → Write(p4_bearish_{sym}.json) — 质疑
     ↓ 等待空头文件就绪
     
  **步3** 多头分析员(正方) v2 → Read(p4_bearish) → Write(p4_bullish_rebuttal_{sym}.json) — 反驳 (max=1)
     ↓ 等待反驳文件就绪
     
  闫判官(裁决+交易参数) → Read(多头v1 + 空头v1 + 反弹v2) → Write(p5_judge_{sym}.json)
  
     ↓ 等待裁决文件就绪
     
  一致性裁判(审计) → Read(多头分析员+空头分析员+裁决) → Write(p5_coherence_{sym}.json)
  (非阻断审计步, 超时不阻塞下游)
  
     ↓
     
  风控明(审核) → Read(裁决+交易参数) → Write(p5_risk_review_{sym}.json)

     ↓ 等待审核文件就绪
     
明鉴秋汇总 → 合并全部产出的JSON → 生成debate_results.json + HTML报告
```

### Step 1: spawn 多头分析员 v1（立论）— 每个品种独立

```python
Agent(
    description=f"多头分析员-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=10,
    prompt=f"""
你是多头分析员，期货辩论专家团成员。

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

### Step 2: spawn 空头分析员 v1（质疑）— 每个品种独立（读多头v1后触发）

```python
Agent(
    description=f"空头分析员-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=10,
    prompt=f"""
你是空头分析员，期货辩论专家团成员。

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

### Step 3: spawn 多头分析员 v2（反驳）— 每个品种独立（读空头v1后触发）

**注意**：此步仅在 `debate_round < MAX_DEBATE_ROUNDS` 时执行。读空头v1的 opposition 后，对每个质疑点针对性反驳。

```python
Agent(
    description=f"多头反驳-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=10,
    prompt=f"""
你是多头分析员（正方），对空头的质疑进行针对性反驳。

❗JSON要求：所有字符串文本中禁止使用任何引号。

闫判官指定的信号方向: {direction}
品种: {symbol} {name}
价格: {price}

【空头 v1 质疑 — 请逐条回应】
（从 p4_bearish_{symbol}.json 读取）

研究数据同上轮。

这是**反驳阶段（rebuttal v2）**：
1. 针对每条质疑，用研究员数据正面回应
2. 禁止"你说得对""但是反过来"开头
3. 如果质疑成立，承认并降置信度
4. 至少覆盖空头提出的主要质疑点

输出文件：{symbol}_rebuttal.json
"""
)
```

### Step 4: 轮询等待

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

### Step 5: spawn 闫判官（裁决）— 每个品种独立

```python
Agent(
    description=f"闫判官裁决-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=15,
    prompt=f"""
你是闫判官，期货辩论专家团裁决官。

先用Read工具读以下两个文件：
1. bullish_path}（多头分析员/多方论据）
2. {bearish_path}（空头分析员/空方论据）

品种: {symbol} {name} | 当前价格: {price} | ATR: {atr}

读完后做裁决，并直接输出交易参数。闫判官直接输出交易参数供风控明审核。

JSON输出格式：
{{
  "agent": "闫判官",
  "symbol": "{symbol}",
  "generated_at": "...",
  "verdict": "BUY/SELL/HOLD",
  "confidence": 0.0-1.0 数值（如0.6表示中等），禁止高/中/低裸字符串",
  "confidence_label": "高/中/低（可选，仅人类可读展示用）",
  "bull_score": 0-100,
  "bear_score": 0-100,
  "winner": "bull/bear/tie",
  "reasoning": "裁决逻辑（不使用引号）",
  "key_observation": "关键判断",
  "score_breakdown": {{ "趋势": 0-100, "量价": 0-100, "供需": 0-100, "持仓": 0-100, "宏观": 0-100, "估值": 0-100 }},
  "trading_params": {{
    "direction": "BUY/SELL/HOLD",
    "entry_price": {price},
    "stop_loss": "入场价 ± N*ATR",
    "target_1": "入场价 ± M1*ATR",
    "target_2": "入场价 ± M2*ATR",
    "position_size_pct": "15-20（高置信度）/ 10（中置信度）/ 5（低置信度）",
    "timeframe": "120m波段",
    "risk_note": "风险说明（不使用引号）"
  }}
}}

🔴 ADX角色反转规则（必须遵守）：
- ADX低位(<20) = 趋势可能正在启动，关注DC20/DC55通道确认信号，不得据此判定不做
- ADX高位(≥60) = 趋势可能过热，警示追单风险
- 裁决中ADX不得成为首要判断依据或致命伤
- reasoning中ADX提及占比不得超过总论证篇幅的1/3
- 六维评分中趋势结构维度应将ADX作为通道突破的辅助验证，而非独立主导

仓位建议（按 confidence 数值 0-1 映射）：
- confidence ≥ 0.7（高）: 正常仓位15-20%
- 0.4 ≤ confidence < 0.7（中）: 轻仓10%
- confidence < 0.4（低）: 极小仓位5%
- HOLD: 0%仓位，仅给监控方案

BUY裁决交易参数规则：入场{price}附近, 止损{price}-2*ATR, 目标1{price}+2*ATR, 目标2{price}+3*ATR
SELL裁决交易参数规则：入场{price}附近, 止损{price}+2*ATR, 目标1{price}-2*ATR, 目标2{price}-3*ATR
HOLD裁决交易参数规则：0%仓位，仅给监控方案

输出文件：{judge_path}
注意：只能读文件，不得SendMessage给任何Agent。

❗ 现货基准选取警示：
当多方和空方引用不同现货基准（如进口CFR vs 国内现货/挂牌价）时：
- 闫判官必须明确说明选择了哪个基准、为何选择
- 不得片面采纳某一方的基准而不做解释
- 建议优先参考：①交易所仓单报价 ②权威机构现货均价 ③盘面近月合约价格
- 若多源差异过大，在reasoning中注明基准选取存在±X%误差范围
"""
)
```

### Step 6: spawn 一致性裁判（held-out judge）— 非阻断审计步

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
1. bullish_path} — 多头分析员论据
2. {bearish_path} — 空头分析员论据
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

### Step 7: spawn 风控明（风控审核）— 每个品种独立

```python
Agent(
    description=f"风控审核-{symbol}",
    subagent_type="general-purpose",
    model="default",
    max_turns=8,
    prompt=f"""
你是风控明，风险管理总监。

先用Read工具读文件: {judge_path}（闫判官裁决，含交易参数）

品种: {symbol} {name}

读取闫判官裁决中的 verdict 和 trading_params，对交易参数做风控审核：

6层风控检查：
1. ADX趋势强度（ADX<25 → 趋势弱标记）
2. 成交量配合度（vol_ratio<0.6 → 量能不足标记）
3. 超买/超卖风险（RSI>70或<30）
4. 数据源质量（子周期数据为AKShare分钟降级）
5. 仓位合理性（验证闫判官给出的 position_size_pct 是否符合风控红线）
6. 止损合理性（验证 stop_loss 是否在权益5%红线内）

品种扫描数据: ADX={adx}, RSI={rsi}, 成交量={vol_ratio}

输出文件：{risk_path}。完成后用Write直接写入文件，不使用SendMessage。
格式：{{ "symbol": "{symbol}", "risk_level": "低/中/高", "veto": false, "risk_items": [["ADX趋势弱","注意","ADX<25趋势不明朗"]], "recommendation": "可执行/需谨慎/否决" }}
"""
)
```

### Step 8: 明鉴秋汇总

读取**所有**品种的**全部**5个产出文件：

```
每个品种: p4_bullish_{sym}.json + p4_bearish_{sym}.json 
          + p5_judge_{sym}.json + p5_coherence_{sym}.json
          + p5_risk_review_{sym}.json
```

合并为 `debate_results.json`，然后调用：
```bash
python phase3_generate_report.py \
  --debate debate_results.json \
  --output . \
  --output-html debate_report.html
```

🔴 P6报告生成（二选一，必须执行）：
- **全量辩论（多品种）**：调用 `phase3_generate_report.py`（强依赖全量 `intermediate_data.json` + 62/62覆盖铁律）
- **单品种辩论**：直接Write结构化HTML报告（含P1信号表 / P1.5产业链 / P4多空论据 / P5裁决+方案+风控 / P6结论 六模块），**不依赖全量脚本**（phase3为全量62品种设计，单品种直接套会卡在全量依赖上）

🔴 P6知识萃取强制门禁（不可跳过）：
组装 `debate_results.json` 后，必须对每个辩论品种调用知识萃取，将本轮辩论写入品种知识库：
```bash
python extract_knowledge.py ingest   --symbol {sym}   --pro p4_bullish_{sym}.json   --con p4_bearish_{sym}.json   --judge p5_judge_{sym}.json   --bypass
```
品种知识库路径：`{FDT_ROOT}/memory/knowledge/{sym}/`（patterns.json / drivers.md / key_levels.json）。
**缺少知识萃取步骤 → P6不视为完成**（辩论跑完但未回填知识库，品种经验无法积累）。

**Phase门禁检查（D03）**：若任一缺少 `p4_bullish_{sym}.json` / `p4_bearish_{sym}.json` / `p5_judge_{sym}.json` / `p5_risk_review_{sym}.json` 文件 → **拒绝生成报告**。

## 产出文件清单（每个品种独立）

| 阶段 | 产出文件 | 说明 |
|:----|:---------|:-----|
| P4 步1 | `p4_bullish_{sym}.json` | 多头分析员论据 v1（立论，至少5条） |
| P4 步2 | `p4_bearish_{sym}.json` | 空头分析员论据 v1（质疑，至少3条） |
| P4 步3 | `p4_rebuttal_{sym}.json` | 多头反驳 v2（rebuttal，max=1，如有） |
| P5 | `p5_judge_{sym}.json` | 闫判官裁决（含六维评分+交易参数） |
| P5 | `p5_coherence_{sym}.json` | 一致性裁判审计意见 |
| P5 | `p5_risk_review_{sym}.json` | 风控明审核 |
| P6 | `debate_results.json` | 汇总结果 |
| P6 | `debate_report_*.html` | HTML报告 |

## 路径常量

```
FDT_ROOT = <项目根目录>
SIGNAL_DIR = C:\Users\yangd\Documents\Signal
REPORT_SCRIPT = {FDT_ROOT}/skills/futures-trading-analysis/scripts/phase3_generate_report.py
AGENTS_DIR = {FDT_ROOT}/agents/
   ├── futures-bullish-analyst.md  (多头分析员)
   ├── futures-bearish-analyst.md  (空头分析员)
   ├── futures-judge.md            (闫判官)
   ├── futures-judge-heldout.md    (一致性裁判)
   └── futures-risk-manager.md     (风控明)
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
- 非阻断审计步，不阻塞下游风控明流程
- 超时则标记"一致性审计未完成"，继续执行后续步骤
