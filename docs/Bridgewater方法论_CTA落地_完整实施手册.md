# Bridgewater 论文方法论 × CTA 量化交易 — 完整实施手册

> **总纲** | 基于 Bridgewater AIA Labs × Thinking Machines Lab 论文  
> 《Learning to Replicate Expert Judgment in Financial Tasks》的方法论，
> 结合掌掌柜 CTA 量化交易现有技术栈（futures-debate-team v4.1、quant-daily、
> polyester-chain-analysis、energy-chain-analysis）的工程化实施方案。
>
> **发布**: 2026-07-06 | **状态**: 规划就绪，待掌掌柜确认后启动

---

## 目录

- [一、核心启示与三条落地路径](#一核心启示与三条落地路径)
- [二、路径A：品种分类模型](#二路径a品种分类模型)
- [三、路径B：研报质量过滤模型](#三路径b研报质量过滤模型)
- [四、路径C：辩论专家团预筛选增强](#四路径c辩论专家团预筛选增强)
- [五、ML 训练自动化框架](#五ml-训练自动化框架)
- [六、实施路线图](#六实施路线图)
- [七、附录](#七附录)

---

## 一、核心启示与三条落地路径

### 1.1 论文核心启示

Bridgewater AIA Labs 的论文核心结论（见 `Learning_to_Replicate_Expert_Judgment_解读报告.md`）：

> **用高质量专家标注数据微调 Qwen3-235B，在金融信息过滤任务上以 84.7% 准确率超越 GPT/Claude 等前沿模型，同时推理成本降低 13.8 倍。**

三条关键技术路线对我们有直接借鉴价值：

| 论文技术 | 我们的对应路径 |
|---------|--------------|
| 高质量专家标注的重要性 | **路径B**: 利用现有技能的输出作为"弱监督信号" |
| 交错批处理 + CISPO + OPD | **路径C-ML**: 争议度预测模型的蒸馏训练 |
| 差异化智能（小模型 > 通用前沿模型） | **三条路径共同指导思想** |

### 1.2 三条路径总览

| 路径 | 目标 | 核心方法 | 优先级 | 预计总工时 |
|:----|:-----|:---------|:------|:---------|
| **A** | 品种分类 | 资讯→品种多标签分类 | P2 | ~6h |
| **B** | 研报质量过滤 | 蒸馏现有五层打分逻辑 | P1 | ~8h |
| **C** | 辩论预筛选增强 | 增强 `debate_brief.py` + ML 预测 | **P0** | ~12h |

**执行顺序**: C → B → A，因为 C 直接提升辩论效率（当前最痛），B 次之（研报噪声大），A 是锦上添花。

---

## 二、路径A：品种分类模型

> **目标**：给定新闻/研报/资讯，自动判断影响哪些期货品种（67品种多标签分类）

### 2.1 A-Minimal：Prompt 分类（2天）

**思路**：不训练模型，直接用 LLM + 提示词做分类。**适合验证效果。**

**步骤**：

```
Step 1: 定义分类体系
  └─ 67品种 → 按板块分组（黑色系、能化系、聚酯系、有色金属、贵金属、农产品）
  └─ 每板块一份"特征说明书"

Step 2: 构建分类 Prompt（代码见附录 A）
  └─ 输入：新闻/研报正文 → 输出：["RB","HC"] 带置信度

Step 3: 集成到 futures-data-search 技能
  └─ 在 scan_all.py 的资讯采集后插入分类步骤

Step 4: 验证
  └─ 手动标注 50 篇测试集，对比准确率
```

**依赖**：`futures-data-search` 技能  
**成本**：零（仅 API 调用费）  
**预期精度**：~70-75%

### 2.2 A-Standard：Embedding+分类器（3周）

**思路**：用文本 Embedding + 轻量分类器（XGBoost），**适合正式部署。**

**步骤**：

```
Phase 1: 构建标注数据集（500-2000篇）
  ├─ 先用 A-Minimal 自动标注（弱标签）
  ├─ 争议验证法：多个 prompt 变体标注 → 不一致的 → 人工仲裁

Phase 2: 训练（二选一）
  ├─ 方案A（推荐，本地<10ms）: Embedding(1024d) + XGBoost 多标签
  └─ 方案B（更准）: Qwen2.5-7B + LoRA

Phase 3: 部署
  └─ 集成到 scan_all.py 的资讯采集流程 → 输出添加品种标签字段
```

**成本**：~$50-200  
**预期精度**：~80-85%

### 2.3 A-Advanced：完整微调（1-3月）

完整复刻 Bridgewater 路线：Qwen3-235B + 专家标注 + GRPO/CISPO/OPD。  
**暂不推荐**，投入产出比对于 CTA 个人/小团队偏低。

---

## 三、路径B：研报质量过滤模型

> **目标**：判断研报是否包含"值得关注的产业链驱动信号"，过滤噪声

### 3.1 现有优势

`polyester-chain-analysis` 和 `energy-chain-analysis` 已内置**五层量化打分体系**和**主驱动识别引擎**。可以直接将现有打分逻辑作为弱监督信号来标注训练数据——**无需人工标注**。

### 3.2 B-Minimal：Prompt 过滤（1天）

**方法**：将五层打分的规则转化为 Checklist Prompt，在数据流中插入过滤步骤。

```python
PROMPT = """判断研报是否包含"值得关注的产业链驱动信号":
1. ✅ 包含量化数据（开工率、库存、利润、基差等）
2. ✅ 包含供给冲击（检修、停产、进出口变化）
3. ✅ 包含需求变化（政策、季节性、终端需求数据）
4. ✅ 对价格方向有明确判断（利多/利空）
...
返回: {"is_valuable": true/false, "score": 0-100}"""
```

### 3.3 B-Standard：蒸馏打分逻辑到分类器（1周）

**核心思路**：将现有五层打分逻辑作为**教师**，训练学生模型直接输出分类结果，**加速 300 倍**（30s → 0.1s）。

**步骤**：

```
Phase 1: 自动生成训练数据（无需人工）
  ├─ 源数据：过去3个月 polyester/energy 处理过的研报
  ├─ 已有标签：五层打分结果（总评分>60且触发主驱动识别=有价值）
  ├─ 预期样本量：5000-10000篇
  └─ 正负样本比例：约 1:3

Phase 2: 训练二分类模型
  ├─ 模型：BERT-base-chinese / DistilBERT
  ├─ 重点指标：Recall > 0.9（不要漏掉有价值的研报）
  └─ 类别不平衡处理：加权损失

Phase 3: 部署
  └─ 嵌入数据采集流程 → 过滤前80%低质量内容 → 不再进入五层打分
```

**成本**：~$50  
**预期效果**：每日研报处理量减少 70%，关键信号零漏报

### 3.4 B-Advanced：多维度评分模型

训练多任务回归模型，输出与五层打分体系对齐的6维评分（数据丰富度/供给冲击/需求变化/方向判断/时效性/综合质量）。基座模型推荐 Qwen2.5-7B + LoRA。

---

## 四、路径C：辩论专家团预筛选增强

> **这是三条路径中最核心、投入产出比最高的路径。**
> 
> **修正说明**：此前我基于旧版路径设计了 C1-C4 过滤方案。经掌掌柜指正，当前 `plugins/marketplaces/my-experts/` 下的 v4.1 版本已有双层筛选机制（`debate_brief.py --select-debate` + 闫判官 LLM 决策）。因此**正确的增强点不是新增筛选层，而是增强现有 `debate_brief.py` 的输出质量**。

### 4.1 现有流程分析

```
debate_brief.py --select-debate → 闫判官综合决策 → 研究员供弹 → 辩论 → 裁决
         ↑ 已有4分类精选               ↑ 有最终决策权
         ↑ 已有同链冗余过滤
         ↑ 已有 min_count≥20 约束
```

但 `select_debate_symbols()` 存在三个可改进的差距：

| 差距 | 现状 | 改进 |
|------|------|------|
| **Gap 1: 评分粗放** | `divergence_score = \|total_l\|+\|total_f\|` | → 五维加权评分（信号/趋势/极端/数据/链） |
| **Gap 2: 无历史反馈** | 每次独立运行，无记忆 | → 轻量历史档案 `debate_history.py` |
| **Gap 3: 闫判官信息少** | 候选列表仅4个字段 | → 附加速览摘要 + 评分分解 + 风险标签 |

### 4.2 C-Phase 1：多维辩论价值评分（本周 · 2h）

在 `debate_brief.py` 中新增 `compute_debate_score()`，替换原有的简单 `divergence_score` 计算。

```python
def compute_debate_score(l_entry, f_entry) -> dict:
    """
    五维加权评分 (0-100)：
    ├─ 信号强度 40%: |total_l|+|total_f| 归一化
    ├─ 趋势质量 25%: ADX≥25加分 + stage非quiet加分 + cons一致性加分
    ├─ 极端性   20%: RSI极端 + z-score极端 + 方向分歧 → 好辩论素材
    ├─ 数据质量 10%: veto计数罚分
    └─ 链重要性  5%: 是否产业链关键节点
    → {"debate_value": 87.3, "breakdown": {...}, "tags": ["方向分歧","强趋势"]}
    """
```

**改动范围**：仅 `skills/quant-daily/scripts/signals/debate_brief.py`，不动 agents/ 目录。

### 4.3 C-Phase 2：历史反馈集成（本周 · 2h）

新增 `debate_history.py`，自动记录每次辩论的品种评分和结果。

```python
# debate_history.py — 轻量JSON档案（append-only）
def load_feedback() -> dict:
    """返回 {symbol: {debate_count, high_value_count, avg_judge_confidence, win_rate}}"""
    
def record_feedback(symbol, debate_value, judge_confidence, outcome=None):
    """每次辩论结束后自动记录"""
    
def get_symbol_value_score(symbol, feedback) -> float:
    """基于历史反馈的加分/减分 [-10, +10]"""
```

**集成**：在 `select_debate_symbols()` 加载反馈 → 候选品种附带 `history` 字段：
```json
{"history": {"debate_count": 5, "avg_judge_confidence": 0.80, "win_rate": 0.6, "value_adjustment": 3.2}}
```

### 4.4 C-Phase 3：闫判官速览摘要（本周 · 1h）

为每个候选品种自动生成一句话摘要 + 关键指标速览：

```python
def build_judge_brief(symbol_entry) -> dict:
    return {
        "quick_summary": "L1-L4多头(总分+76, ADX59.5) vs 因子空头(总分-45)",
        "conflict": True,
        "strength": {"l1l4": "STRONG", "factor": "MODERATE"},
        "risk_flags": "ADX极端但一致性低 | RSI极端(27.7)",
    }
```

**闫判官最终看到的每条候选数据**（从4个字段扩展到12个字段）：
```json
{
  "symbol": "RB", "chain": "黑色链",
  "debate_value": 87.3,
  "breakdown": {"signal":32,"quality":22.5,"extreme":18,"data":10,"chain":4.8},
  "tags": ["方向分歧","强趋势"],
  "quick_summary": "L1-L4多头(+76, ADX59.5) vs 因子空头(-45)",
  "conflict": true,
  "strength": {"l1l4":"STRONG","factor":"MODERATE"},
  "risk_flags": "ADX极端但一致性低 | RSI极端(27.7)",
  "history": {"debate_count":5, "win_rate":0.6, "value_adjustment":3.2},
  "proposition_side": "bear",
  "reason": "方向分歧: L1L4=多头(+76) vs 因子=空头(-45)"
}
```

### 4.5 C-Phase 4：ML 争议度预测（下月 · 可选项）

当辩论历史积累到 100+ 条后，训练 LightGBM 分类器预测品种的辩论价值。

**特征**：现有的五维评分 + 历史反馈指标 + 品种波动率 + 时间特征  
**标签**：闫判官实际选中率 / 辩论后交易采纳率  
**训练方式**：使用已有的 `DirectionClassifierV2.incremental_train()` 增量训练

> 🟢 **此阶段非必须**。Phase 1-3 的规则增强已经显著提升闫判官的决策效率。ML 是 Phase 1-3 跑通后的锦上添花。

---

## 五、ML 训练自动化框架

### 5.1 核心理念

> **系统自主决定训练时机 + 自己跑训练 + 自己评审 + 自己决定是否上线。**
> 你只在异常时收到一条通知，日常零干预。

### 5.2 训练调度中心

```python
class TrainingOrchestrator:
    """训练调度中心 — 自主决策是否训练、何时训练、是否上线"""
    
    def run_daily_check(self):
        # Step 1: 检查触发条件
        conditions = [
            "新样本累积 ≥ 50 条",
            "或 距上次训练 ≥ 7 天", 
            "或 模型性能下降 > 5%"
        ]
        # 任一条件满足 → 训练
        
        # Step 2: 增量训练 (已有 incremental_train)
        # Step 3: 自动评审 (新模型 vs 生产模型 on 验证集)
        # Step 4: 决策 (deploy/skip/flag)
```

### 5.3 全自动决策树

```
每日收盘后 → 检查触发条件
    ├─ 不满足 → 无事发生（静默）
    └─ 满足 → 增量训练 → 验证集评估 → 自动对比
                                         ├─ 新模型更优 → 自动部署（静默）
                                         ├─ 新模型略差 → 自动部署 + 通知
                                         └─ 新模型显著更差 → 不部署 + 通知
```

### 5.4 安全兜底

| 防护 | 机制 |
|:----|:-----|
| 备份 | 部署前自动备份生产模型 |
| 基线 | 每次部署记录 AUC/Precision/F1 快照 |
| 自动回滚 | 部署后3天性能下降>10% → 切回备份 |
| 人工覆写 | `--force-retrain` 强制重训 |

### 5.5 各组件自动化程度

| 组件 | 训练需求 | 自动化级别 | 人工参与 |
|:----|:---------|:----------|:--------|
| 辩论评分规则 | 无 | L3 全自动 | 零 |
| 历史反馈 | 无 | L3 全自动 | 零 |
| 争议度 ML | 有（增量） | L2 半自动 | 首次一次 + 异常通知 |
| 方向分类器（已有） | 有（增量） | L2 半自动 | 已就绪无需额外工作 |

> **自动化级别定义**：L0=全手动 | L1=系统提建议你审批 | L2=系统决定+异常通知 | L3=全自动

---

## 六、实施路线图

### 6.1 时间线总图

```
本周 (2026-07-06 ~ 07-12)                              下周 (07-13 ~ 07-19)                      下月 (08月)
                                                                                                                
┌─────────────────────────────────────┐      ┌─────────────────────────────────────┐      ┌─────────────────────┐
│ Phase 1: 基础增强 (7h)              │      │ Phase 2: 研报质量过滤 (8h)           │      │ Phase 3: ML 增强     │
│                                     │      │                                     │      │                     │
│ C-Phase 1 多维评分   2h             │ ──→  │ B-Minimal Prompt过滤  1h            │ ──→  │ C-Phase 4 争议度预测  │
│ C-Phase 2 历史反馈   2h             │      │ B-Standard 蒸馏训练  5h             │      │ (LightGBM, 需100+    │
│ C-Phase 3 闫判官摘要  1h            │      │ B-部署集成           2h             │      │  辩论历史积累)       │
│ 测试验证              2h            │      │                                     │      │                     │
└─────────────────────────────────────┘      └─────────────────────────────────────┘      └─────────────────────┘
                                                                                                         
         P0：提升辩论效率                                 P1：降低研报噪声                            P2：ML 辅助决策
```

### 6.2 Phase 1 详细排期（本周）

| 天 | 任务 | 产出 | 工时 |
|:-:|:-----|:-----|:----:|
| **Day 1** | `debate_brief.py` 新增 `compute_debate_score()` | 多维评分函数 | 2h |
| **Day 1** | 新增 `debate_history.py` + 集成到 `select_debate_symbols()` | 历史反馈模块 | 2h |
| **Day 2** | 新增 `build_judge_brief()` + 完善候选输出结构 | 闫判官增强输出 | 1h |
| **Day 2** | 本地测试：对比新旧输出 + 验证3轮历史记录 | 测试报告 | 2h |
| **Day 2** | 出完整 diff + **等掌掌柜确认后**部署 | Deploy | — |

### 6.3 Phase 2 详细排期（下周）

| 任务 | 工时 | 依赖 |
|:-----|:----:|:----|
| B-Minimal: 写 Prompt 过滤工具 | 1h | 熟悉 polyester/energy 数据流 |
| B-Standard: 准备训练数据（自动标注） | 2h | 3个月历史研报数据 |
| B-Standard: 训练 BERT 分类器 | 3h | GPU 或 API |
| B-部署: 集成到数据采集流程 | 2h | — |

### 6.4 成功标准

| 阶段 | 可量化指标 | 验收方式 |
|:----|:----------|:---------|
| Phase 1 完成 | 闫判官选的辩论品种平均得分 > 70 | 对比10轮辩论 |
| Phase 1 完成 | 候选列表字段从4→12个 | 肉眼检查 |
| Phase 2 完成 | 研报过滤 recall > 0.9 | 手动复核200篇 |
| Phase 3 完成 | ML 模型 AUC > 0.75 | 验证集评估 |

---

## 七、附录

### 附录 A：文件清单与改动范围

| 操作 | 文件路径 | 路径 |
|:----|:---------|:-----|
| **修改** | `debate_brief.py` | `skills/quant-daily/scripts/signals/debate_brief.py` |
| **新增** | `debate_history.py` | `skills/quant-daily/scripts/signals/debate_history.py` |
| **新增** | `auto_train_orchestrator.py` | `skills/quant-daily/scripts/auto_train_orchestrator.py` |
| **不修改** | agents/*.md | `plugins/marketplaces/my-experts/plugins/futures-debate-team/agents/` |
| **不修改** | rules/*.md | 同上 `rules/` |

> ⚠️ 按铁律1，`plugins/marketplaces/my-experts/` 下的修改必须先出完整 diff 报告，经掌掌柜明确确认后才可执行。

### 附录 B：同时废弃的旧文档

| 废弃文档 | 原因 | 替代 |
|:---------|:-----|:-----|
| `路径C_辩论预筛选_实现方案.md` | 基于旧版流程，预筛选方案已过时 | 本文第4章 |

### 附录 C：参考文档索引

| 文档 | 用途 |
|:-----|:-----|
| `Learning_to_Replicate_Expert_Judgment_解读报告.md` | Bridgewater 论文详细解读 |
| `三条实现路径_详细方案.md` | 三条路径的总纲（含 A/B 的 Minimal/Standard/Advanced 详细代码） |
| `ML训练_自动化程度设计.md` | ML 训练自动化的完整设计（含 TrainingOrchestrator 代码） |
| `路径C_辩论预筛选_纠正方案.md` | 路径C纠正方案的完整 doc（含全部代码细节） |

> **本文是总纲文档，各子模块的完整代码实现请参考上述分册。**
