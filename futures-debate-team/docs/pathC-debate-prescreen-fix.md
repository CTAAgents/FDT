# 路径C：辩论专家团预筛选 — 纠正方案

> **状态修正**：此前我错误地读取了旧版 futues-debate-team 路径（`experts/`下的通用版本），而掌掌柜实际使用的是 `plugins/marketplaces/my-experts/` 下的 v4.1 定制版，该版本**已经实现了品种预筛选**机制。
>
> **本文基于 v4.1 真实架构，重新定位"预筛选增强"的切入点。**

---

## 一、当前流程的完整分析（v4.1）

### 1.1 已有筛选机制

现有 v4.1 流程中，品种筛选已经通过**两层机制**实现：

```
第1层：debate_brief.py --select-debate（规则筛选）
  ├─ 将全品种分为4类：
  │   ├─ 分歧品种（divergence）—— 双策略方向相反 → 优先辩论
  │   ├─ 共识多头（consensus_bull）—— 双策略一致看多
  │   ├─ 共识空头（consensus_bear）—— 双策略一致看空
  │   └─ 中性品种（neutral）—— 强度不足
  ├─ 精选策略：分歧优先 → 新链补充 → 链覆盖补充 → 补足数量
  ├─ 同链冗余过滤：r>0.80 且强度差<20% → 只保留1个
  └─ 约束：min_count≥20, min_chains≥12

第2层：闫判官LLM综合决策
  ├─ 接收 debate_brief 的精选候选列表
  ├─ 结合链证源产业链分析、流动性风险、事件日历
  ├─ 自行决定"哪些品种值得辩论"
  └─ 每个品种指定正方方向
```

**结论：品种预筛选并非缺失，而是已存在**。我此前设计的 C1（规则过滤）等价于 `debate_brief.py:select_debate_symbols()`，C3 等价于 `signal-quality-plan.md` 中已有的 ML 计划。

### 1.2 真正的差距在哪？

虽然筛选机制已存在，但我仔细分析了 `debate_brief.py` 的 `select_debate_symbols()` 函数后，发现三个可改进之处：

| 差距                      | 现状                                                       | 影响                           |
| ----------------------- | -------------------------------------------------------- | ---------------------------- |
| **Gap 1: 评分指标粗放**       | `divergence_score = \|total_l\| + \|total_f\|`，仅用总分绝对值叠加 | 忽略 ADX、RSI极端值、数据质量、历史辩论效果等维度 |
| **Gap 2: 无历史反馈**        | `select_debate_symbols()` 每次独立运行，不知道之前辩论的效果              | 无法"记住"哪些品种的辩论最有价值            |
| **Gap 3: 闫判官看到的预处理太简单** | 候选列表只有 symbol/chain/direction/reason 四个字段                | 闫判官需要手动回头看原始数据做判断            |

---

## 二、修正后的方案定位

```
┌─────────────────────────────────────────────────────────────────┐
│                     原有流程（保持不变）                          │
├─────────────────────────────────────────────────────────────────┤
│  scan_all.py --dual → build_signal_summary() → full_scan_*.json │
│                                     ↓                          │
│           debate_brief.py --select-debate → candidates.json     │
│                                     ↓                          │
│                    闫判官综合决策 → 辩论品种列表                   │
│                                     ↓                          │
│                    研究员供弹 → 辩论 → 裁决                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
              ★ 增强箭头处的数据质量，而非跳过或替换 ★
```

**核心原则**：

1. **不替换、不跳过现有流程** — 闫判官始终拥有最终决策权
2. **增强 `debate_brief.py:select_debate_symbols()` 的输出** — 让闫判官拿到更丰富的辅助信息
3. **利用历史辩论反馈** — 让品种筛选有"记忆"和"学习"能力
4. **所有代码修改限定在修改 `debate_brief.py` 和新增数据文件** — 不改 agents/ 目录（避免触及铁律1）

---

## 三、具体改进方案

### 3.1 Gap 1: 多维辩论价值评分（今日可实施）

**现状**：`divergence_score` 仅 = `|total_l| + |total_f|`

**改进**：引入加权多维辩论价值评分

```python
# 在 debate_brief.py 中新增函数

def compute_debate_score(l_entry: dict, f_entry: dict) -> dict:
    """
    计算多维辩论价值评分。
    
    评分维度及权重（共100分）：
    ├─ 信号强度 40%: |total_l| + |total_f| 归一化
    ├─ 趋势质量 25%: ADX(>25加分)、stage(非quiet加分)、cons(一致性加分)
    ├─ 极端性   20%: RSI极端、z-score极端、方向分歧 → 好辩论素材
    ├─ 数据质量 10%: veto计数、data_quality字段
    └─ 链重要性 5%: 是否产业链关键节点品种
    
    Returns:
        {"debate_value": 0-100, "breakdown": {...}, "tags": [...]}
    """
    l_total = abs(l_entry.get("total", 0))
    f_total = abs(f_entry.get("total", 0))
    l_adx = l_entry.get("adx", 0)
    f_adx = f_entry.get("adx", 0)
    l_stage = l_entry.get("stage", "unknown")
    l_cons = l_entry.get("cons", 0)
    l_rsi = l_entry.get("rsi", 50)
    l_veto = l_entry.get("veto", 0)
    f_veto = f_entry.get("veto", 0)
    l_dir = l_entry.get("direction", "neutral")
    f_dir = f_entry.get("direction", "neutral")
    
    # 1. 信号强度分 (0-40)
    signal_score = min(l_total * 0.3 + f_total * 0.3, 40)
    
    # 2. 趋势质量分 (0-25)
    adx_score = min(max(l_adx - 15, 0) * 0.8, 15)
    stage_bonus = 0 if l_stage in ("quiet", "unknown") else 5
    cons_score = min(l_cons * 2, 5)
    quality_score = adx_score + stage_bonus + cons_score  # max 25
    
    # 3. 极端性分 (0-20) — 极端的信号是好辩论素材
    rsi_extreme = max(abs(l_rsi - 50) - 15, 0) * 0.3  # RSI>65或<35开始加分
    z_bonus = 5 if abs(l_entry.get("z_score", 0)) > 2 else 0
    divergence_bonus = 5 if (l_dir != f_dir and 
                              l_dir != "neutral" and f_dir != "neutral") else 0
    extreme_score = min(rsi_extreme + z_bonus + divergence_bonus, 20)
    
    # 4. 数据质量分 (0-10)
    veto_penalty = (l_veto + f_veto) * 5
    data_score = max(10 - veto_penalty, 0)
    
    # 5. 链重要性 (0-5) — 由调用者传入
    chain_score = 0  # 外部赋值
    
    total_score = signal_score + quality_score + extreme_score + data_score + chain_score
    
    # 标签
    tags = []
    if l_dir != f_dir and l_dir != "neutral" and f_dir != "neutral":
        tags.append("方向分歧")
    if l_adx > 40 or f_adx > 40:
        tags.append("强趋势")
    if abs(l_rsi - 50) > 25:
        tags.append("RSI极端")
    if abs(l_entry.get("z_score", 0)) > 2:
        tags.append("Z分数极端")
    if l_veto > 0 or f_veto > 0:
        tags.append("有否决项")
    if l_stage in ("exhaustion", "reversal"):
        tags.append("关键阶段")
    
    return {
        "debate_value": round(min(total_score, 100), 1),
        "breakdown": {
            "signal_score": round(signal_score, 1),
            "quality_score": round(quality_score, 1),
            "extreme_score": round(extreme_score, 1),
            "data_score": round(data_score, 1),
            "chain_score": round(chain_score, 1),
        },
        "tags": tags,
    }
```

**将此评分集成到 `select_debate_symbols()` 的输出中**——闫判官看到的候选列表不再只是 `symbol/chain/direction/reason`，而是附带 debata_value 分数和标签：

```python
# 改进后的候选列表条目结构
{
    "symbol": "RB",
    "chain": "黑色链",
    "debate_value": 87.3,        # ★ 新增：综合辩论价值
    "breakdown": {...},           # ★ 新增：分项
    "tags": ["方向分歧", "强趋势"],  # ★ 新增：标签
    "proposition_side": "bear",
    "reason": "方向分歧: L1L4=多头(+76) vs 因子=空头(-45)"
}
```

### 3.2 Gap 2: 历史反馈集成（本周可实施）

**现状**：`select_debate_symbols()` 每次独立运行，无记忆

**改进**：引入轻量级历史档案文件

```python
# new file: quant-daily/scripts/signals/debate_history.py

import json, os, time
from pathlib import Path

HISTORY_DIR = Path("memory/debates")
HISTORY_FILE = HISTORY_DIR / "debate_feedback.json"

def load_feedback() -> dict:
    """
    加载历史辩论反馈。
    
    Returns:
        {symbol: {
            "debate_count": int,       # 该品种被辩论总次数
            "high_value_count": int,   # 被评为"高价值"的次数
            "avg_judge_confidence": float,  # 闫判官平均置信度
            "last_debate_date": str,
            "win_rate": float,         # 辩论后交易胜率
            "debate_value_history": [float],  # 历史辩论价值评分
        }}
    """
    if HISTORY_FILE.exists():
        data = json.loads(HISTORY_FILE.read_text())
        return data
    return {}

def record_feedback(symbol: str, debate_value: float, 
                    judge_confidence: str, outcome: str = None):
    """记录一次辩论反馈。"""
    data = load_feedback()
    if symbol not in data:
        data[symbol] = {
            "debate_count": 0,
            "high_value_count": 0,
            "avg_judge_confidence": 0.0,
            "debate_value_history": [],
            "last_debate_date": "",
            "win_rate": 0.0,
            "wins": 0,
            "losses": 0,
        }
    entry = data[symbol]
    entry["debate_count"] += 1
    if debate_value > 70:
        entry["high_value_count"] += 1
    entry["debate_value_history"].append(debate_value)
    # 只保留最近50次
    entry["debate_value_history"] = entry["debate_value_history"][-50:]
    # 置信度映射
    conf_map = {"高": 0.85, "中": 0.6, "低": 0.3}
    old_total = entry["avg_judge_confidence"] * (entry["debate_count"] - 1)
    entry["avg_judge_confidence"] = round(
        (old_total + conf_map.get(judge_confidence, 0.5)) / entry["debate_count"], 2
    )
    entry["last_debate_date"] = time.strftime("%Y-%m-%d")
    if outcome:
        if outcome == "win":
            entry["wins"] += 1
        elif outcome == "loss":
            entry["losses"] += 1
        total = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / total, 2) if total > 0 else 0.0
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_symbol_value_score(symbol: str, feedback: dict) -> float:
    """
    基于历史反馈的加分/减分。
    
    高价值辩论历史的品种 → 加分，有更好历史表现
    每次都低价值的品种 → 减分
    """
    entry = feedback.get(symbol)
    if not entry or entry["debate_count"] < 2:
        return 0.0
    
    # 高价值比例
    high_value_ratio = entry["high_value_count"] / entry["debate_count"]
    
    # 置信度因子
    confidence_factor = entry.get("avg_judge_confidence", 0.5)
    
    # 最终得分调整：[-10, +10]
    return round((high_value_ratio * 10) + (confidence_factor * 5) - 7.5, 1)
```

**集成到 `select_debate_symbols()` 中**：

```python
# 在 select_debate_symbols() 开头加载反馈
feedback = load_feedback()

# 在候选条目中添加历史信息
candidate["history"] = {
    "debate_count": fb.get("debate_count", 0),
    "avg_judge_confidence": fb.get("avg_judge_confidence", 0),
    "win_rate": fb.get("win_rate", 0),
    "value_adjustment": get_symbol_value_score(sym, feedback),
}
```

### 3.3 Gap 3: 为闫判官生成更丰富的决策素材（明日可实施）

**现状**：闫判官收到的候选列表信息量不够，需要手动回溯原始信号数据

**改进**：在 `select_debate_symbols()` 输出中为每个候选品种附加"速览摘要"

```python
def build_judge_brief(symbol_entry: dict) -> dict:
    """为闫判官生成品种速览摘要。"""
    l = symbol_entry["l1l4"]
    f = symbol_entry["factor_timing"]
    risk = symbol_entry.get("risk_input", {})
    
    l_total = l.get("total", 0)
    f_total = f.get("total", 0)
    conflict = (l.get("direction") != f.get("direction") and
                l.get("direction") != "neutral" and f.get("direction") != "neutral")
    
    return {
        "symbol": symbol_entry["symbol"],
        "quick_summary": (
            f"L1-L4{'多头' if l_total>0 else '空头'}(总分{l_total:+d}, ADX{l.get('adx',0)}, "
            f"阶段{l.get('stage','?')}) vs "
            f"因子{'多头' if f_total>0 else '空头'}(总分{f_total:+d}, "
            f"投票{f.get('vote_net',0)})"
        ),
        "conflict": conflict,
        "strength": {
            "l1l4": l.get("grade", "NONE"),
            "factor": f.get("grade", "NONE"),
        },
        "risk_flags": risk.get("pattern_risk", "无"),
        "debate_score": compute_debate_score(l, f),
    }
```

**闫判官最终看到的每条候选数据示例**：

```json
{
  "symbol": "RB",
  "chain": "黑色链",
  "debate_value": 87.3,
  "breakdown": {"signal": 32.0, "quality": 22.5, "extreme": 18.0, "data": 10.0, "chain": 4.8},
  "tags": ["方向分歧", "强趋势", "RSI极端"],
  "quick_summary": "L1-L4多头(总分+76, ADX59.5, 阶段trending) vs 因子空头(总分-45, 投票-3)",
  "conflict": true,
  "strength": {"l1l4": "STRONG", "factor": "MODERATE"},
  "risk_flags": "ADX极端但一致性低 | RSI极端(27.7)",
  "history": {"debate_count": 5, "avg_judge_confidence": 0.80, "win_rate": 0.6, "value_adjustment": 3.2},
  "proposition_side": "bear",
  "reason": "方向分歧: L1L4=多头(+76) vs 因子=空头(-45)"
}
```

---

## 四、实施路线

### 4.1 实施范围

| 文件                                                     | 操作     | 说明                              |
| ------------------------------------------------------ | ------ | ------------------------------- |
| `skills/quant-daily/scripts/signals/debate_brief.py`   | **修改** | 增强 `select_debate_symbols()` 输出 |
| `skills/quant-daily/scripts/signals/debate_history.py` | **新增** | 辩论历史反馈模块                        |
| 其他 agents/*.md                                         | **不改** | 闫判官和明鉴秋的 Prompt 无需修改            |

> 🔴 按铁律1：`plugins/marketplaces/my-experts/` 下的修改**必须先出 diff 对比报告**，等你明确确认后才执行。

### 4.2 Phase 1：本周（多维评分 + 历史反馈）

| 步骤     | 内容                                               | 涉及文件              | 工时       |
| :----- | :----------------------------------------------- | :---------------- | :------- |
| 1.1    | 在 `debate_brief.py` 中新增 `compute_debate_score()` | `debate_brief.py` | 1h       |
| 1.2    | 新增 `debate_history.py`                           | 新建                | 1h       |
| 1.3    | 集成到 `select_debate_symbols()` 输出                 | `debate_brief.py` | 1h       |
| 1.4    | 新增 `build_judge_brief()` 生成速览摘要                  | `debate_brief.py` | 0.5h     |
| 1.5    | 本地测试 + 对比新旧输出                                    | —                 | 1h       |
| **合计** |                                                  |                   | **4.5h** |

### 4.3 Phase 2：下月（ML 争议度预测）

遵照 `signal-quality-plan.md` 中已有的 ML 迭代计划（2.1-2.3 节），将 ML 模型的预测输出集成到 `debate_brief.py` 中：

```python
# 在 select_debate_symbols() 中增加 ML 预测分支
ml_prediction = direction_classifier.predict(feature_vector)  
# debate_value 中加入 ML 输出的置信度因子
```

该部分 `signal-quality-plan.md` 已有完整规划（6h），此处不再重复。

### 4.4 无需做的事

| 事项                                        | 原因                        |
| :---------------------------------------- | :------------------------ |
| ❌ 新增预筛选 Agent                             | 现有流程已有筛选，新增 Agent 带来通信复杂度 |
| ❌ 修改闫判官 Prompt                            | 闫判官已有决策权，只需提供更丰富数据        |
| ❌ 替换 `debate_brief.py` 的逻辑                | 现有的分歧/共识分类策略正确，只需增强输出     |
| ❌ 动 `plugins/marketplaces/` 下的 agents/ 目录 | 高风险的违规操作                  |

---

## 五、预期效果

### Before vs After

| 对比项    | Before                             | After                                                                    |
| ------ | ---------------------------------- | ------------------------------------------------------------------------ |
| 候选条目字段 | symbol/chain/direction/reason 4个字段 | + debate_value / breakdown / tags / quick_summary / history / risk_flags |
| 评分方式   | `\|total_l\|+\|total_f\|` 粗放叠加     | 5维度加权（信号/趋势/极端/数据/链），0-100分                                              |
| 历史利用   | 无                                  | 品种级辩论次数/置信度/历史胜率                                                         |
| 闫判官负担  | 需要手动查看原始 JSON                      | 一眼看到速览摘要 + 综合评分                                                          |
| 辩论质量   | 好辩论题材和差题材混在一起                      | 闫判官可以按 debate_value 排序，优先选高分                                             |

### 预期效果量化

- 闫判官做品种筛选的效率提升约 **40%**（不需要频繁回去看原始数据）
- 辩论候选列表的前 50% 品种（按 debate_value 排序）的辩论后采纳率预期提升 **15-25%**
- 历史反馈积累 2 周后，可开始做"哪些品种历史辩论价值高"的数据分析

---

## 六、后续可选增强

### 6.1 PnL 反馈闭环（信号质量计划已有）

辩论后交易的 PnL 结果 → 回写到 `debate_history.py` → `win_rate` 字段自动更新 → `select_debate_symbols()` 更倾向历史高胜率品种。

### 6.2 自动阈值学习

收集 100+ 次辩论的 `debate_value` 与实际采纳率的关系 → 自动调整 `min_count/min_chains` 参数：

```python
# 自动学习的阈值调整
if 采纳率 < 30% 且 平均debate_value < 60:
    自动提高 min_debate_value 阈值
```

### 6.3 闫判官反馈回路

闫判官可以给每个被选中的品种打"选题质量分"（0-10）→ 写入 `debate_history.py` → 下次 `select_debate_symbols()` 参考：

```
闫判官: "RB 这轮辩论很有价值，选题质量: 8/10"
  ↓
debate_history.record_feedback("RB", ..., judge_rating=8)
  ↓
下次 select_debate_symbols: RB 的 value_adjustment += 2
```

---

## 七、修正后回答掌掌柜的三个问题

**Q1: 预筛选工作的位置是否合理？**

> **不合理**。此前我读取的是旧版路径（`experts/futures-debate-team`），而当前 v4.1 版本已通过 `debate_brief.py --select-debate` + 闫判官 LLM 决策实现了双层筛选。**正确的增强点不是新增一层筛选，而是增强 `debate_brief.py` 的输出质量**，让闫判官拿到更丰富、更有结构的信息来辅助决策。

**Q2: 如何与闫判官的筛选协作？**

> 保持闫判官的最终决策权不变。改进后的 `debate_brief.py` 会输出：
>
> - 每条候选品种的 **多维辩论价值评分**（0-100）
> - **速览摘要**（一句话概括分歧点）
> - **历史辩论反馈**（该品种以往辩论效果）
> - **风险标签**（RSI极端/ADX强趋势等）
>
> 闫判官可以按 `debate_value` 排序，优先处理高分品种。但最终选谁、不选谁，依然是闫判官自行决定。

**Q3: 改动范围是否可控？**

> **是**。改动仅限 `skills/quant-daily/scripts/signals/debate_brief.py`（增强输出字段）+ 新增 `debate_history.py`。不涉及 agents/ 目录，不动 `plugins/marketplaces/` 下的角色定义文件。如需执行，我会先出完整 diff 对比报告供确认。

