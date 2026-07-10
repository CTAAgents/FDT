# FDT 能力解锁设计书 — D1 / D3 / ViBench 阶段二

> 日期：2026-07-07 ｜ 关联：CLQT (arXiv:2606.29771) APM-CS 五轴 ｜ 专家团 v5.2/5.3
> 状态：**设计完成，待掌柜"改"/"执行"确认后落地**（铁律：plugins/marketplaces/ 任何修改须经 diff 报告 + 显式确认）

---

## 〇、当前阻塞根因（一句话）

| 轴 | 状态 | 根因 |
|:--|:--|:--|
| **D1 Coherence** | blocked | `debate_journal.json` 只存 `verdict` 与 `debate_thesis`，**未把"正方论据 / 反方论据 / 裁决"三相打包成可审计的 `debate_record`**；且无 held-out judge 给一致性分数 |
| **D3 Composure** | blocked | 仅 1 轮辩论（RB_20260706），回归所需 `≥5 轮 × (波动率, 止损触发)` 配对不足 |
| **ViBench 回放** | BLOCKED | `run_benchmark.py` 回放引擎待"原始辩论输入快照"——即 D1 升级后的 `debate_record` |

**关键发现（落地前必须定夺）**
1. **双 journal 副本不一致**：`memory/debate_journal.json` 与 `skills/memory/debate_journal.json` 内容 DIFFER。`apm_scorecard.py` 只读 `memory/`。须指定唯一 canonical 副本并同步。
2. **round_id 不连通**：`execution_followup.round_id` = `debate_20260706_1319`（按记录），`debate_journal` 的 `verdict.round` = `RB_20260706`（按品种）。ViBench 回放要把"辩论输入"和"ground_truth PnL 对错"join 起来，必须统一键。

---

## 一、① 解开 D1（schema 升级 + held-out judge）

### 1.1 目标
让 `debate_journal.json` 每轮辩论携带 **可审计三元组** `{pro_args, con_args, verdict}` + **held-out judge 一致性分**，使 D1 = 裁决是否真正源于辩论论据（CLQT §6.4.1 held-out judge 思想）。

### 1.2 新增 journal entry 类型 `debate_record`
明鉴秋在 P6 汇总时，从 证真/慎思/闫判官 的输出**组装**此条目写入：

```json
{
  "timestamp": "2026-07-06 13:19:00",
  "agent": "futures-debate-team-team-lead",
  "action": "debate_record",
  "round_id": "debate_20260706_1319",          // ← 与 execution_followup.round_id 对齐（见 §1.7）
  "symbol": "RB",
  "signal_type": "channel_breakout",          // channel_breakout / trend_confirmation / bb_squeeze_prebreakout
  "pro_args": [                                // 来自 证真 debate_thesis.key_arguments（复用既有字段，不改辩手md）
    {"id": "证真-D1", "claim": "DC20 向上突破 + 量能 1.8×均量确认", "evidence": "DC20=+3.2%, vol_ratio=1.8", "source": "通道突破信号"},
    {"id": "证真-D2", "claim": "产业链黑色系 86% 一致性偏空", "evidence": "链证源景气度快照", "source": "链证源"}
  ],
  "con_args": [                                // 来自 慎思 debate_thesis.key_arguments
    {"id": "慎思-D1", "claim": "ADX=67.2 趋势运行过远，追空风险", "evidence": "ADX=67.2", "source": "L1-L4"},
    {"id": "慎思-D2", "claim": "factor_timing 展期结构 Back 但幅度收窄", "evidence": "vote_net=0", "source": "factor_timing"}
  ],
  "verdict": {"direction": "bear", "confidence": "高", "winner": "bear_win", "reasoning": "..."},
  "held_out_judge": {                          // ← 新增角色产出
    "coherence_score": 0.82,                   // 0~1：裁决对论据的还原度
    "rationale": "裁决方向(bear)与正方核心论据(突破+产业链)一致，且回应了反方 ADX 末端风险",
    "judge": "futures-judge-heldout"
  },
  "volatility": {"adx": 67.2, "atr": 10.7},    // ← 供 D3 使用
  "hit_stop": null                             // ← validate_verdicts 回填（ViBench join 用）
}
```

> **复用而非新增**：`pro_args`/`con_args` 直接来自辩手既有 `key_arguments`，**无需修改 证真/慎思 .md**（降低生产文件改动面）。

### 1.3 新增角色：`agents/futures-judge-heldout.md`（**新增文件，低风险**）
- **定位**：CLQT held-out judge。不参与原辩论，独立评审"裁决是否由辩论论据推出"。
- **输入**：明鉴秋注入的 `pro_args` + `con_args` + `verdict`（来自本轮 `debate_results.json`）。
- **输出**：`held_out_judge` JSON（coherence_score 0~1 + rationale），经 `memory_writer.append_debate_journal(..., "coherence", {...})` 写入。
- **评分 rubric（held-out）**：
  - `≥0.8`：裁决方向/入场/止损/目标全部有对应论据支撑，反方核心质疑已被正面回应。
  - `0.5~0.79`：大体支撑，存在 1 处论据缺口或未回应次要质疑。
  - `<0.5`：裁决偏离论据主流，或忽视反方重大质疑（逻辑跳跃/诉诸权威）。
- **可扩展**：CLQT 用 dual-judge（minimax-m3 + GLM-5.2）；本期先单 held-out judge，预留 `judge_model` 字段支持双 judge 对照。

### 1.4 修改：`agents/futures-debate-team-team-lead.md`（**生产文件，需确认**）
P4 辩论期流程**新增 Step 2.5（一致性裁判）**，插在"Step 2 闫判官裁决"与"Step 3 策执远"之间：

```text
├─ Step 2: spawn 闫判官(裁决)  → poll_file_ready(p5_judge.json)
├─ Step 2.5: spawn 闫判官裁决后，spawn futures-judge-heldout(一致性裁判)
│     ├─ 注入 pro_args(证真) + con_args(慎思) + verdict(闫判官) 文件路径
│     ├─ prompt末尾加: "注意：不要向其他Agent发送消息"
│     └─ poll_file_ready(p5_coherence.json) ✅
├─ Step 3: spawn 策执远(方案)  → ...
```

并在 **P6 汇总**处新增组装步骤（在"归档"段）：
```python
from scripts.memory_writer import append_debate_record
append_debate_record({
    "round_id": latest_followup_round_id,   # 取 execution_followup 最新记录 round_id
    "symbol": sym, "signal_type": ...,
    "pro_args": zhengzhen_args, "con_args": shensi_args,
    "verdict": judge_verdict,
    "held_out_judge": heldout_score,        # 读 p5_coherence.json
    "volatility": {"adx":..., "atr":...},
})
```
> 此改动**不改变 SOP 阶段顺序**（仍 P1→P6），仅追加一个非阻断评审步。

### 1.5 修改：`scripts/memory_writer.py`（**脚本，低风险**）
新增 helper（additive）：
```python
def append_debate_record(record: Dict[str, Any], round_id: str = None):
    """写入升级后的 debate_record 条目（含 pro_args/con_args/verdict/held_out_judge）"""
    writer = MemoryWriter(round_id=round_id or datetime.now().strftime("%Y%m%d"))
    return writer.write("team-lead", record, "debate_record")
```
（并可选：写入时同步 `skills/memory/debate_journal.json` 副本，解决 §〇 发现1）

### 1.6 修改：`scripts/apm_scorecard.py`（**脚本，低风险**）
- 新增 `compute_coherence(entries)`：读取 `debate_record` / `coherence` 条目 → `coherence_score` 均值；叠加"论据-方向一致性"自动校验（winner 方是否论据更多/更强）。
- D1 激活条件：`≥1` 条带 `held_out_judge` 的 `debate_record` 存在即算分（不再 blocked）。
- `apm_overall` 纳入 D1（激活时）。

### 1.7 待定：round_id 对齐方案（需你拍板）
- **方案 A（推荐）**：`debate_record.round_id` 直接取 `execution_followup` 最新记录 `round_id`（`debate_20260706_1319`），join key = `round_id + symbol`。
- **方案 B**：改 `debate_journal` 的 `verdict.round` 命名规则，与 followup 对齐（需回溯旧数据）。
- ViBench 回放用 `round_id + symbol` join `execution_followup.records[].verdicts[]` 的 ground_truth。

---

## 二、② D3 自动点亮（≥5 轮）

### 2.1 设计
- `compute_composure(entries, followup)`：取各 `debate_record` 的 `volatility.adx/atr`（自变量）与 `hit_stop`/净 PnL（因变量），做线性回归 `hit_stop ~ volatility`，输出斜率与 R²。
- **D3 = 组合度得分**：波动率越高、止损触发率/亏损越大 → 组合度越差。定义 `D3 = clamp(1 - normalize(|slope|), 0, 1)`（斜率越陡越差）。
- **激活门控**：`distinct_rounds(debate_record) >= 5` 才计算；否则输出 `blocked (n/5 轮)`。

### 2.2 修改：`scripts/apm_scorecard.py`（同上文件）
- 在 `main()` 中调用 `compute_composure`，门控 ≥5 轮。
- `apm_overall` 纳入 D3（激活时）。

### 2.3 修改：`scheduler/triggers.py`（**脚本，低风险**）
新增 DataTrigger（与既有 vibench_baseline 并列）：
```python
DataTrigger(
    task_name="d3_auto_light",
    data_path="memory/debate_journal.json",
    count_key="entries",            # 或按 debate_record 计数
    threshold=5,                    # 辩论轮次≥5
    cooldown_minutes=1440,
    run_cmd="python scripts/apm_scorecard.py",
)
```
> "等…自动点亮"语义达成：D3 代码就绪但门控，轮次满 5 后触发器自动重算并点亮，无需人工干预。

---

## 三、③ 启动 ViBench 历史回放 benchmark（阶段二）

### 3.1 设计
`run_benchmark.py` 升级：从"仅聚合 ground_truth"进阶为"消费升级后的 `debate_record` 做结构回放"。

### 3.2 修改：`scripts/run_benchmark.py`（**脚本，低风险**）
- 新增 `--replay` 模式（或升级 `--run`）：
  1. 加载 `memory/debate_journal.json` 的 `debate_record`（含 pro_args/con_args/verdict/held_out_judge）。
  2. 按 `round_id + symbol` join `execution_followup` 的 ground_truth（correct / correct_net / realized_pnl_pct）。
  3. 输出回放基线：
     - `direction_accuracy`、`net_accuracy`（既有）
     - **`coherence_weighted_accuracy`**：coherence≥0.7 子集的准确率（CLQT：高一致性辩论应更可靠）
     - `replay_status`：`BLOCKED → ACTIVE`（当有 ≥1 条 debate_record 时）
     - `replay_delta` 占位（供阶段三 self-improve before/after 对照）
- `--build` 同步：抽取 test_cases 时，附加 `debate_record` 输入快照作为回放输入。

### 3.3 新增（可选）：`benchmarks/replay_harness.py`（**新增文件，低风险**）
轻量 v1 回放引擎：用确定性评分从存储的 `pro_args/con_args` 重推裁决方向，与 `verdict.direction` + ground_truth 比对，产出"输入→输出"一致性报告。
> 注：脚本环境无 LLM API，完整 LLM 重辩留作未来；v1 以"结构一致性 + ground_truth 对照"落地，已满足"启动回放"诉求。

### 3.4 现状可执行性
当前仅有 1 轮辩论且无 `debate_record`，故回放首跑将输出 `ACTIVE 但 n=0~1` 的管线验证报告；**每跑一次辩论即自动累积 debate_record，回放基线随数据增长而充实**。

---

## 四、文件改动清单（风险分级）

| # | 文件 | 类型 | 风险 | 触发铁律 |
|:--|:----|:--|:--|:--|
| 1 | `agents/futures-judge-heldout.md` | **新增** | 低（additive） | 否 |
| 2 | `scripts/memory_writer.py` | 修改（+helper） | 低 | 否（脚本） |
| 3 | `scripts/apm_scorecard.py` | 修改（D1+D3） | 低 | 否（脚本） |
| 4 | `scheduler/triggers.py` | 修改（+trigger） | 低 | 否（脚本） |
| 5 | `scripts/run_benchmark.py` | 修改（replay） | 低 | 否（脚本） |
| 6 | `benchmarks/replay_harness.py` | **新增** | 低 | 否 |
| 7 | `agents/futures-debate-team-team-lead.md` | 修改（P4 Step2.5 + P6 组装） | **中**（生产角色定义） | **是 → 需确认** |
| 8 | `memory/debate_journal.json` / `skills/memory/` 同步 | 数据 | 中 | 需确认（删/同步策略） |

> 辩手(证真/慎思)与闫判官 .md **无需修改**（复用既有 `key_arguments`）。

---

## 五、待你拍板的两点

1. **canonical journal**：以 `memory/debate_journal.json` 为唯一权威，`skills/memory/` 副本改为同步写入（不删除），是否同意？
2. **round_id 对齐**：采用方案 A（`debate_record.round_id` 取 followup 最新 `round_id`）？

---

## 六、确认后执行顺序（预计 ≤ 8 步）

1. 定夺 §五两点 → 写 `memory_writer` 同步逻辑。
2. 新增 `futures-judge-heldout.md`（角色定义 + rubric）。
3. 改 `team-lead.md`：Step 2.5 + P6 组装（**你确认后动手**）。
4. 改 `memory_writer.py` 加 `append_debate_record`。
5. 改 `apm_scorecard.py`：D1 `compute_coherence` + D3 `compute_composure`（门控）。
6. 改 `triggers.py`：加 `d3_auto_light`。
7. 改 `run_benchmark.py`：replay 模式 + 可选 `replay_harness.py`。
8. 跑 `apm_scorecard.py` 验证 D1 就绪（当前 n=0 → blocked 转"ready"）、`run_benchmark.py --replay` 验证管线。

---

**请回复"改"/"执行"（或 "yes"）以授权落地 ④⑦⑧ 等 plugins/marketplaces/ 文件改动；新增文件(①④⑥)可一并授权。**
