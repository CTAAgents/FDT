# 路径C：辩论专家团预筛选 — 详细实现方案

> **目标**：在 futures-debate-team 的 5 阶段辩论流程中，于 P1（数技源输出）与 P2（链证源）之间插入预筛选步骤，过滤掉不值得辩论的信号，节省辩论资源、加速响应、聚焦高价值信号。
>
> **适用于 CTA 量化交易者，无需 GPU，渐进式投入。**

---

## 一、现状分析

### 当前辩论流程

```
用户触发
    ↓
明鉴秋(团队协调员)
    ↓
P1 【串行】数技源 → scan_all / quant-daily → 全品种JSON输出
    ↓  ← ← ← ← ← ← ★ 路径C在此插入预筛选
P2 【串行】链证源 → 产业链分析
    ↓
P3 【并行】牛势研 + 熊谋略 → 多空辩论
    ↓ 【顺序】闫判官 → 最终裁决
P4 【串行】风控明 → 风险评估
    ↓
P5 【串行】策执远 → 交易方案
    ↓
明鉴秋 → 汇总 → HTML报告
```

### 数技源输出格式（每个品种）

```json
{"RB": {"price": 3061, "l1": -28, "l2": -19, "l3": -21, "l4": -8,
        "veto": 0, "total": -76, "grade": "STRONG",
        "stage": "trending", "adx": 59.5, "rsi": 27.7,
        "data_quality": "✅正常"}}
```

**关键字段含义**：
- `l1` ~ `l4`：四层信号评分（负值=空头，正值=多头，范围≈±100）
- `total`：综合得分 = l1+l2+l3+l4
- `grade`：`"STRONG"` / `"MODERATE"` / `"WEAK"` / `"NONE"`
- `veto`：否决项计数（>0 表示该品种不可交易）
- `stage`：趋势阶段 — `"trending"` / `"ranging"` / `"volatile"` / `"quiet"`
- `adx`：趋势强度（0-100，>25=有趋势）
- `rsi`：RSI 值（0-100）
- `data_quality`：数据质量状态

**现状问题**：当前无论信号强弱，P1 输出的所有品种都进入 P2-P5 全流程。一次 full_scan 模式涵盖 67 品种，产生大量无意义的辩论（弱信号、低 ADX、数据缺失的品种也在辩论）。

---

## 二、方案体系概览

| 级别 | 方法 | 成本 | 时间 | 过滤率 | 风险 |
|------|------|------|------|--------|------|
| **C0** | 无过滤（现状） | 0 | 0 | 0% | 辩论资源浪费 |
| **C1** | 规则过滤 | 0 | 1天 | ~50% | 规则可能漏网或误杀 |
| **C2** | 评分排序 | 0 | 2天 | ~60% | 同上 |
| **C3** | 机器学习争议度预测 | ~$50 | 2周 | ~70% | 需历史数据训练 |
| **C4** | 辩论结果端到端预测 | ~$200 | 1个月 | ~80% | 替换辩论的风险 |

推荐执行顺序：**C1 → C2 → C3 → C4**，每个级别都是上一级别的增强，可独立部署。

---

## 三、C1：规则过滤（Minimal，推荐本周执行）

### 3.1 核心设计

在明鉴秋团队的 P1 与 P2 之间插入一个 **`debate_prefilter.py`** 脚本。接收数技源 JSON 输出，逐品种判断是否值得进入辩论。

### 3.2 过滤规则定义

```python
# debate_prefilter_rules.py — 规则定义

MINIMUM_TOTAL_SCORE = 20       # |total| < 20 的信号强度太低，不值得辩论
MAX_VETO_ALLOWED = 0           # veto > 0 的品种直接跳过
MINIMUM_ADX = 18               # ADX < 18 趋势太弱，辩论无意义
SKIP_STAGES = {"quiet"}        # "quiet" 阶段无辩论价值
MINIMUM_CONFIDENCE = 2         # 至少需要 l1-l4 中有 2 层的方向一致
DATA_QUALITY_FAIL = {"❌异常", "⚠️部分缺失"}  # 数据质量不达标跳过
HISTORY_COOLDOWN_HOURS = 12    # 同一品种过去12小时内已辩论过 → 跳过
```

### 3.3 核心过滤逻辑

```python
# debate_prefilter.py — C1 规则过滤引擎

import json
import time
from pathlib import Path
from datetime import datetime, timedelta

# ============ 配置 ============
RULES = {
    "min_total_score": 20,        # 综合得分绝对值阈值
    "max_veto": 0,                # 否决项上限
    "min_adx": 18,                # 最小ADX
    "skip_stages": {"quiet"},     # 跳过"静默"阶段
    "min_aligned_layers": 2,      # 最少方向一致的层数
    "cooldown_hours": 12,         # 同品种冷却时间
    "fail_data_quality": {"❌异常", "⚠️部分缺失"},
}

# ============ 过滤函数 ============

def should_debate(pid: str, signal: dict, debate_history: dict) -> dict:
    """
    判断单个品种是否值得进入辩论流程
    
    参数:
        pid: 品种代码，如 "RB"
        signal: 数技源输出JSON
        debate_history: 辩论历史记录 {pid: last_debate_timestamp}
    
    返回:
        {"debate": True/False, "reasons": [...], "priority": 0-100}
    """
    reasons = []
    
    # 规则1: 数据质量检查
    dq = signal.get("data_quality", "✅正常")
    if dq in RULES["fail_data_quality"]:
        return {"debate": False, "reasons": [f"数据质量不达标: {dq}"], "priority": 0}
    
    # 规则2: 否决项检查
    veto = signal.get("veto", 0)
    if veto > RULES["max_veto"]:
        return {"debate": False, "reasons": [f"否决项计数: {veto}"], "priority": 0}
    
    # 规则3: 综合得分阈值
    total = abs(signal.get("total", 0))
    if total < RULES["min_total_score"]:
        return {"debate": False, "reasons": [f"综合得分 |{total}| < {RULES['min_total_score']}"], "priority": total}
    
    # 规则4: 趋势强度
    adx = signal.get("adx", 0)
    if adx < RULES["min_adx"]:
        reasons.append(f"ADX {adx} < {RULES['min_adx']}，趋势偏弱")
        # ADX低但其它方面不错的品种可以降级为"观察"而非直接跳过
        if adx < 15:
            return {"debate": False, "reasons": [f"ADX {adx} 过低"], "priority": total * 0.5}
    
    # 规则5: 趋势阶段
    stage = signal.get("stage", "")
    if stage in RULES["skip_stages"]:
        return {"debate": False, "reasons": [f"阶段: {stage}，无需辩论"], "priority": 0}
    
    # 规则6: 方向一致性 — l1-l4 中至少几层方向一致？
    scores = [signal.get(f"l{i}", 0) for i in range(1, 5)]
    positive = sum(1 for s in scores if s > 0)
    negative = sum(1 for s in scores if s < 0)
    aligned = max(positive, negative)
    if aligned < RULES["min_aligned_layers"]:
        reasons.append(f"方向一致层数 {aligned} < {RULES['min_aligned_layers']}，信号混乱")
    
    # 规则7: 冷却时间 —— 避免同一品种反复辩论
    last = debate_history.get(pid)
    if last:
        elapsed = time.time() - last
        if elapsed < RULES["cooldown_hours"] * 3600:
            remaining = int((RULES["cooldown_hours"] * 3600 - elapsed) / 60)
            return {"debate": False, "reasons": [f"冷却中，还需{remaining}分钟"], "priority": total}
    
    # 计算优先级分数
    priority = _calc_priority(signal, total, adx, aligned)
    
    return {"debate": True, "reasons": reasons, "priority": priority}


def _calc_priority(signal: dict, total: float, adx: float, aligned: int) -> int:
    """计算辩论优先级 0-100"""
    score = 0
    score += min(total, 50) * 1.0           # 综合得分权重
    score += min(max(adx - 15, 0), 40) * 0.5 # ADX 超出15的部分
    score += aligned * 5                     # 方向一致性奖励
    score += 10 if signal.get("grade") == "STRONG" else 0  # STRONG评级加分
    score += 5 if signal.get("grade") == "MODERATE" else 0
    return min(int(score), 100)


def filter_all_signals(p1_output: dict, debate_history: dict,
                       min_priority: int = 30) -> dict:
    """
    全品种过滤入口
    
    参数:
        p1_output: 数技源输出的完整JSON {pid: signal_dict, ...}
        debate_history: 辩论历史
        min_priority: 最小优先级阈值（低于此值的品种即使debate=True也跳过）
    
    返回:
        {"pass": {pid: signal},     # 通过过滤的品种
         "skip": {pid: {signal, reasons}},  # 被过滤的品种
         "stats": {...}}            # 统计信息
    """
    result = {"pass": {}, "skip": {}, "stats": {}}
    
    pass_count = 0
    skip_count = 0
    priorities = []
    
    for pid, signal in p1_output.items():
        decision = should_debate(pid, signal, debate_history)
        if decision["debate"] and decision["priority"] >= min_priority:
            result["pass"][pid] = {**signal, "_priority": decision["priority"]}
            pass_count += 1
            priorities.append(decision["priority"])
        else:
            result["skip"][pid] = {"signal": signal, "reasons": decision["reasons"]}
            skip_count += 1
    
    # 按优先级排序通过的品种
    result["pass"] = dict(sorted(
        result["pass"].items(),
        key=lambda x: x[1]["_priority"],
        reverse=True
    ))
    
    result["stats"] = {
        "total": pass_count + skip_count,
        "pass": pass_count,
        "skip": skip_count,
        "pass_rate": f"{pass_count/(pass_count+skip_count)*100:.1f}%",
        "avg_priority": f"{sum(priorities)/len(priorities):.1f}" if priorities else "N/A"
    }
    
    return result
```

### 3.4 与现有辩论流程的集成方式

集成到明鉴秋（团队协调员）的 P1→P2 步骤之间。有两种方案：

**方案A：明鉴秋内嵌（推荐，无需改专家定义）**

直接在明鉴秋团队协调员的 Prompt 中增加一条指令：

> **P1.5 预筛选步骤**：收到数技源的 JSON 输出后，调用 `debate_prefilter.py` 对全品种做过滤。
> 只有 `pass` 列表中的品种才进入 P2 链证源分析。
> 将 `skip` 列表附在报告末尾（标注"已过滤"）以供查阅。

修改位置：团队协调员的 Prompt（`futures-debate-team-team-lead.md` 或自动化触发脚本）。

**方案B：独立预筛选Agent（更干净）**

在 P1 和 P2 之间新增一个预筛选 Agent：

```yaml
name: futures-prescreener
description: 预筛官 — 辩论专家团预筛选分析师。工作方法由 debate-prescreener 定义。
```

> **注意**：新增 Agent 需要修改 `plugins/marketplaces/` 下的文件，按铁律1需先向掌掌柜报告 diff 并获得明确许可。

**建议**：先采用方案A（仅改协调员 Prompt + 加一个 Python 脚本），跑通后若确实需要再考虑方案B。

### 3.5 辩论历史管理

需要一个轻量级的历史数据库来跟踪上次辩论时间（用于冷却规则）：

```python
# debate_history.py — 轻量辩论历史管理

import json
import os
import time
from pathlib import Path

HISTORY_FILE = Path(os.environ.get("QUANT_HISTORY_DIR", 
    str(Path.home() / ".workbuddy" / "data" / "debate_history.json")))

def load_history() -> dict:
    """加载辩论历史 {pid: last_timestamp, ...}"""
    if HISTORY_FILE.exists():
        data = json.loads(HISTORY_FILE.read_text())
        # 清理超过48小时的记录
        now = time.time()
        cutoff = now - 48 * 3600
        data = {k: v for k, v in data.items() if v > cutoff}
        return data
    return {}

def record_debate(pid: str | list[str]):
    """记录某个(些)品种的辩论时间"""
    history = load_history()
    now = time.time()
    if isinstance(pid, str):
        history[pid] = now
    else:
        for p in pid:
            history[p] = now
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

def get_debate_count_last_24h() -> int:
    """过去24小时的辩论次数（用于统计）"""
    history = load_history()
    now = time.time()
    cutoff = now - 24 * 3600
    return sum(1 for v in history.values() if v > cutoff)
```

### 3.6 测试与验证

```python
# test_debate_prefilter.py — C1 测试用例

# 测试数据
test_signals = {
    "RB": {"price": 3061, "l1": -28, "l2": -19, "l3": -21, "l4": -8,
           "veto": 0, "total": -76, "grade": "STRONG", "stage": "trending",
           "adx": 59.5, "rsi": 27.7, "data_quality": "✅正常"},
    "JM": {"price": 1080, "l1": -5, "l2": 3, "l3": -2, "l4": 1,
           "veto": 0, "total": -3, "grade": "NONE", "stage": "quiet",
           "adx": 12.0, "rsi": 48.5, "data_quality": "✅正常"},
    "ZC": {"price": 720, "l1": 0, "l2": 0, "l3": 0, "l4": 0,
           "veto": 1, "total": 0, "grade": "NONE", "stage": "quiet",
           "adx": 8.0, "rsi": 50.0, "data_quality": "⚠️部分缺失"},
    "CU": {"price": 68500, "l1": 15, "l2": 22, "l3": 10, "l4": 8,
           "veto": 0, "total": 55, "grade": "MODERATE", "stage": "trending",
           "adx": 28.0, "rsi": 62.3, "data_quality": "✅正常"},
}

history = {}  # 空历史（无冷却限制）

# 执行过滤
result = filter_all_signals(test_signals, history, min_priority=30)

assert "RB" in result["pass"], "RB: STRONG信号应通过"
assert result["pass"]["RB"]["_priority"] > 80, "RB: 应高优先级"

assert "JM" in result["skip"], "JM: NONE+quiet应跳过"
assert "ZC" in result["skip"], "ZC: veto>0应跳过"
assert "CU" in result["pass"], "CU: MODERATE信号应通过"

print(f"测试通过！过滤率: {result['stats']['pass_rate']}")
print(f"通过: {list(result['pass'].keys())}")
print(f"跳过: {list(result['skip'].keys())}")
```

**预期结果**：
- RB（STRONG，ADX 59.5）→ **通过**，高优先级
- CU（MODERATE，ADX 28）→ **通过**，中等优先级
- JM（NONE，quiet，ADX 12）→ **跳过**（得分低+阶段quiet+ADX过低）
- ZC（veto=1，数据部分缺失）→ **跳过**（否决+数据质量）
- 全品种过滤率：**50%（2/4）**

---

## 四、C2：评分排序增强（第2天可上）

在 C1 规则过滤的基础上，增加**排序而非单纯过滤**的逻辑：

### 4.1 核心改进

```python
def rank_by_debate_worth(signals: dict, top_n: int = 10) -> dict:
    """
    按"辩论价值"排序，保留 top N 品种
    
    加权公式（比 C1 优先级更精细）：
    score = |total| * 0.4 
          + max(adx - 15, 0) * 0.8 
          + |rsi - 50| * 0.3   （极端RSI加分）
          + (方向一致层数/4) * 20
          + stage_bonus(stage) 
          + grade_bonus(grade)
    """
    pass
```

### 4.2 C1+C2 组合效果

```
full_scan (67品种)
    │
    ├─ C1 规则过滤 → 跳过约 30-40 品种（无趋势、数据差、得分低、冷却中）
    │
    └─ C2 排序取 top 10-15 → 只保留最有价值的品种
         │
         ▼
   进入 P2-P5 完整辩论流程
```

**效果对比**：

| 指标 | 现状 | C1+C2 |
|------|------|-------|
| 进入辩论品种数 | 67 | 10-15 |
| 辩论耗时 | ~30分钟 | ~5-8分钟 |
| 关键信号漏掉概率 | 0% | <2%（可配置保守阈值） |
| 每品种辩论质量 | 低（大量无意义辩论） | 高（聚焦强信号） |

---

## 五、C3：争议度预测模型（Standard，2周）

### 5.1 核心思路

不依赖人工标注的历史规则，而是**从历史辩论数据中学习什么样的信号会产生"有争议"的辩论**。

**"有争议"的定义**：
- 正/反方辩手的论点差异大（embedding 余弦距离大）
- 闫判官最终裁决有明确偏向（非"观望/无明确信号"）
- 辩论过程产生了有价值的分析（用户后续基于此做了交易）

### 5.2 训练数据构建

从历史辩论结果中自动构造训练集：

```python
# build_training_data.py — 从历史辩论日志构造训练数据

import json
from pathlib import Path

def extract_from_debate_log(debate_log_path: str) -> list[dict]:
    """
    从历史辩论日志中提取训练样本
    
    每条样本 = {
        "features": {
            "total_score": -76,
            "abs_total": 76,
            "adx": 59.5,
            "rsi": 27.7,
            "rsi_extreme": 22.3,       # |rsi-50|
            "stage_code": 0/1/2/3,     # trending/ranging/volatile/quiet
            "grade_code": 0/1/2/3,     # NONE/WEAK/MODERATE/STRONG
            "veto": 0,
            "l1_to_l4_consistency": 1.0,  # 方向一致比例
            "l1_l4_spread": ...,          # 四层得分的标准差
            "data_quality_code": 0/1/2,   # 正常/部分缺失/异常
        },
        "label": 0/1,  # 0=不值得辩论, 1=值得辩论
        "label_source": "rule_based / judge_divergence / user_action"
    }
    """
    pass
```

**三种自动标注策略**：

| 标注方法 | 描述 | 样本量预期 |
|----------|------|-----------|
| 规则标注 | C1过滤结果作为弱标签 | 大量但噪声 |
| 辩论分歧度 | 牛势研vs熊谋略的论点embedding距离 > 0.6 → 值得辩论 | 中等 |
| 用户行为 | 掌掌柜实际采纳的辩论 → 正样本 | 少但高质量 |

### 5.3 模型选择

**推荐方案：XGBoost 特征工程版本**（无需 GPU，推理 <1ms）

```python
# train_debate_predictor.py — XGBoost 争议度预测器

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

def train_worthiness_predictor(features_df, labels):
    """
    训练辩论价值预测器
    
    特征: total_score, abs_total, adx, rsi, rsi_extreme, stage_code,
          grade_code, veto, l1_to_l4_consistency, l1_l4_spread
    
    模型: XGBoost (n_estimators=200, max_depth=4)
    
    输出: 模型文件 debate_worth_model.json
    """
    X_train, X_test, y_train, y_test = train_test_split(
        features_df, labels, test_size=0.2, random_state=42
    )
    
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=3.0,  # 正样本权重（值得辩论的样本较少）
        random_state=42
    )
    
    model.fit(X_train, y_train,
              eval_set=[(X_test, y_test)],
              verbose=False)
    
    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred))
    
    model.save_model("debate_worth_model.json")
    return model
```

**备选：轻量 Transformer**（直接用数技源的原始 JSON 文本，不提取特征）

```python
# 用 LLM 做零样本争议度预测 — 作为 XGBoost 的补充

DEBATE_WORTH_PROMPT = """你是一位期货辩论调度专家。给定数技源的信号评分数据，
判断该品种是否"值得进入辩论流程"。

【值得辩论的标准】
1. 信号强度显著（|total| > 30 或 grade=STRONG）
2. 趋势明确（ADX > 25，且有方向性）
3. 四层评分方向一致（多数同方向）
4. 市场处于异常状态（RSI极端、趋势反转初期等）

【不值得辩论的标准】
1. 信号混杂（多空层交错，无明确方向）
2. 无趋势（ADX < 18 或 stage=quiet）
3. 数据质量有缺陷
4. 过去12小时内已辩论过同一品种

请输出：
{"worthy": true/false, "confidence": 0-1, "reason": "..."}
"""
```

### 5.4 C3 集成方式

```
P1 数技源输出
    │
    ├─ C1+C2 规则过滤 → 快速淘汰明显不值得的品种
    │
    ├─ C3 XGBoost 预测 → 对"边缘品种"做二次判断
    │   ├─ 预测"值得辩论"概率 > 0.7 → 进入辩论
    │   ├─ 预测"值得辩论"概率 0.3-0.7 → 标记为"可观察"
    │   └─ 预测"值得辩论"概率 < 0.3 → 跳过
    │
    └─ C1+C2+C3 综合打分 → 取 top N 进入辩论
```

---

## 六、C4：辩论结果预测（Advanced，1个月）

### 6.1 核心思路

**不再判断"是否值得辩论"，而是直接预测辩论的最终裁决结果**。

如果预测置信度高（>0.9），直接输出预测结果，跳过整个辩论流程。
如果预测置信度低（<0.6），才触发完整的辩论链。

### 6.2 架构：三层漏斗

```
                       输入：数技源输出 (67品种)
                              │
                    ┌─────────┴──────────┐
                    │  Level 1: C1 规则    │  O(1), 过滤~50%
                    │   (total<20, veto>0, │
                    │    ADX<15, quiet...)  │
                    └─────────┬──────────┘
                              │
                    ┌─────────┴──────────┐
                    │  Level 2: C3 XGBoost │  <1ms, 过滤~20%
                    │   争议度预测          │
                    └─────────┬──────────┘
                              │
                    ┌─────────┴──────────┐
                    │  Level 3: C4 裁决    │  ~1s, 替代~30%
                    │   预测模型           │
                    └─────────┬──────────┘
                              │
                 ┌────────────┴────────────┐
                 │ 高置信度(>0.9)          │ 低置信度(<0.6)
                 │                         │
                 ▼                         ▼
           直接输出裁决              触发完整辩论链
            (替代P2-P5)            P2→P3→P4→P5
                                        │
                                   辩论结果 → 与学生预测对比
                                        │
                                   → 计算蒸馏损失
                                   → 更新C4模型
```

### 6.3 训练方法：模仿Bridgewater的OPD蒸馏

```
Step 1: 收集历史辩论数据
  ├─ 500+ 次完整辩论日志
  ├─ 每次辩论的输入: 数技源 P1 输出
  └─ 每次辩论的输出: 闫判官裁决 + 风控明评估 + 策执远交易方案

Step 2: 训练学生模型
  ├─ 输入: P1 JSON 特征 (与 C3 相同)
  ├─ 输出: 多分类 (BUY/SELL/HOLD/WATCH)
  └─ 基座: XGBoost 多分类 或 Qwen2.5-7B LoRA

Step 3: 在策略蒸馏
  └─ 学生的预测 与 辩论链实际结果 对比
  └─ 低置信度 → 走辩论链 → 用辩论链输出作为"教师信号"
  └─ 计算蒸馏损失 → 回传更新学生模型
  └─ 学生模型持续进化（每次辩论都是一次训练）
```

### 6.4 持续学习循环

```
      初始训练 → 部署 → 新辩论触发 → 记录输入+输出
                                   │
                             辩论链实际裁决
                                   │
                            ┌──────┴──────┐
                            │ 与学生预测对比  │
                            └──────┬──────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ 一致 → 学生置信度加分       │
                    │ 不一致 → 记录为训练样本      │
                    └──────────────┬──────────────┘
                                   │
                             每周重新训练 C4 模型
```

---

## 七、实施计划

### Phase 1：本周（C1 规则过滤）

| 任务 | 工时 | 产出 |
|------|------|------|
| 1.1 编写 `debate_prefilter.py` | 2h | Python脚本 |
| 1.2 编写 `debate_history.py` | 1h | 轻量历史记录 |
| 1.3 修改明鉴秋 Prompt（嵌入过滤步骤） | 1h | 更新协调员指令 |
| 1.4 本地测试验证 | 1h | 测试报告 |
| **合计** | **5h** | **可运行过滤系统** |

### Phase 2：下周（C2 排序 + 集成）

| 任务 | 工时 | 产出 |
|------|------|------|
| 2.1 实现排名加权逻辑 | 1h | 排序函数 |
| 2.2 配置 top N 参数 | 0.5h | 可配置项 |
| 2.3 与明鉴秋流程深度集成 | 2h | 完整集成 |
| 2.4 手动测试 3-5 次辩论 | 2h | 验证报告 |
| **合计** | **5.5h** | **排序过滤一体化** |

### Phase 3：2周后（C3 争议度预测）

| 任务 | 工时 | 产出 |
|------|------|------|
| 3.1 收集历史辩论日志 | 2h | 数据集 |
| 3.2 特征工程 | 4h | 特征代码 |
| 3.3 训练 XGBoost 模型 | 2h | 模型文件 |
| 3.4 集成测试 | 2h | A/B测试结果 |
| **合计** | **10h** | **ML 争议度预测** |

---

## 八、监控与反馈

### 8.1 核心指标

```python
# monitor.py — 辩论预筛选监控

def generate_monitor_report():
    """生成预筛选效果报告"""
    
    metrics = {
        # 过滤效率
        "total_debates_before": ...,    # 之前每次辩论平均品种数
        "total_debates_after": ...,     # 现在每次辩论平均品种数
        "filter_rate": ...,             # 过滤率
        
        # 过滤质量
        "false_negative_count": ...,    # 被过滤但用户手动回查的品种数
        "false_negative_rate": ...,     # 误过滤率
        
        # 辩论质量
        "avg_judge_confidence_before": ...,  # 之前裁决平均置信度
        "avg_judge_confidence_after": ...,   # 现在裁决平均置信度
        "meaningful_debate_rate": ...,       # "有价值的辩论"占比
        
        # 性能
        "avg_debate_duration_before": ...,   # 之前每次辩论平均耗时
        "avg_debate_duration_after": ...,    # 现在每次辩论平均耗时
        "time_saved_per_debate": ...,        # 每次节约的时间
    }
    
    return metrics
```

### 8.2 兜底机制

- **可配置的保守模式**：`min_priority=10` 几乎只过滤最差信号
- **手动回查入口**：被过滤品种在最终报告末尾列出"待观察清单"
- **紧急覆盖**：掌掌柜可以 `--force-debate RB CU` 强制指定某些品种进入辩论
- **A/B 对比**：新系统上线后前两周并行运行，对比辩论质量

---

## 九、关键风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 规则误杀珍贵信号 | 错过交易机会 | 保守阈值 + 待观察清单 + 手动回查 |
| 冷却时间过长 | 错过连续性信号 | 配置化冷却时间 + 警示标志覆盖 |
| 辩论质量下降 | 信息不够深入 | A/B 测试 + 每两周校准规则 |
| 与明鉴秋流程耦合 | 维护成本高 | 独立脚本 + 清晰的接口契约 |

---

## 十、代码文件清单

```
debate_prefilter/
├── __init__.py              # 包入口
├── debate_prefilter.py      # C1: 规则过滤引擎 (核心)
├── debate_history.py        # 辩论历史管理
├── rank_by_worth.py         # C2: 辩论价值排序
├── train_predictor.py       # C3: XGBoost 训练
├── predict_worth.py         # C3: 争议度预测
├── verdict_predictor.py     # C4: 裁决结果预测
├── monitor.py               # 监控指标
├── test_debate_prefilter.py # 测试用例
├── config.yaml              # 可配置参数
└── README.md                # 使用说明
```

---

## 十一、下一步行动

如果掌掌柜确认方向，建议按以下顺序动手：

1. **✅ 确认**：是否同意 C1 规则过滤方案？确认后我今天就开始写脚本
2. **配置确认**：
   - min_total_score 阈值偏好？（建议20-30）
   - 冷却时间偏好？（建议12h）
   - full_scan 模式下每次保留 top N 进入辩论？（建议10-15）
3. **集成确认**：倾向于方案A（改明鉴秋 Prompt）还是方案B（新增预筛选 Agent）？
