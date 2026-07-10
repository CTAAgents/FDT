# 三条落地路径：详细实现方案

> 基于 Bridgewater × Thinking Machines Lab 论文《Learning to Replicate Expert Judgment in Financial Tasks》的方法论，结合掌掌柜 CTA 量化交易现有技术栈（futures-data-search、polyester-chain-analysis、energy-chain-analysis、futures-debate-team）的工程化实施方案。

---

## 概述

本文给出三个等级的方案，每条路径按**最小可行（Minimal）→ 标准（Standard）→ 高阶（Advanced）** 三个层级递进：

| 层级 | 适用范围 | 成本 | 实现周期 |
|------|---------|------|---------|
| **Minimal** | 1-2天可完成，利用现有模型+Prompt | 零成本 | ~2天 |
| **Standard** | 2-4周，微调中等模型（7B-72B） | API调用费~$50-500 | 2-4周 |
| **Advanced** | 1-3月，完整复刻Bridgewater路线 | 训练费~$2000+ | 1-3月 |

---

## 路径A：品种分类模型

> **目标**：给定一篇新闻/研报/资讯，自动判断它影响哪个(些)期货品种（RB、HC、I、J、JM、ZC、FU、LU、BU、PX、TA、EG 等 67 品种），实现多标签分类。

### A1：Minimal — Prompt-Based 分类

**核心思路**：不训练任何模型，直接用 LLM + 精心设计的提示词做分类。

**实现步骤**：

```
Step 1: 定义分类体系
  └─ 从 futures-data-search 的品种清单提取 67 品种 → 按板块分组
     （黑色系、能化系、聚酯系、有色金属、贵金属、农产品、软商品）
  └─ 每个板块写一份 "板块特征说明书"（品种关联的典型事件类型）

Step 2: 构建分类 Prompt 模板
  └─ 输入：新闻/研报正文
  └─ 输出：["RB","HC"] 这种多标签数组 + 置信度评分 + 简要理由

Step 3: 用 futures-data-search 中的 scan_all.py 做数据源
  └─ 从各数据源（东财、AKShare、TqSDK）获取的资讯/研报
  └─ 传入分类 prompt → 得到品种标注

Step 4: 集成到现有工作流
  └─ 在研报推送流程中插入分类步骤
  └─ 分类结果作为标签附加在数据上
  └─ 用户可基于品种标签做筛选/聚合
```

**具体实现代码示例（可在现有 WorkBuddy 技能中嵌入）：**

```python
# prompt_based_classifier.py — 嵌入到 futures-data-search 技能
import json

SYSTEM_PROMPT = """你是一位专业的CTA商品期货信息分类专家。
你的任务是将一篇金融/产业新闻或研报分类到受影响的期货品种。

【品种分类体系】
- 黑色系：RB(螺纹钢)、HC(热卷)、I(铁矿石)、J(焦炭)、JM(焦煤)、ZC(动力煤)
- 能化系：SC(原油)、FU(燃料油)、LU(低硫燃料油)、BU(沥青)、LPG(液化气)
- 聚酯系：PX(对二甲苯)、TA(PTA)、EG(乙二醇)、PF(短纤)、PR(瓶片)
- 有色金属：CU(铜)、AL(铝)、ZN(锌)、PB(铅)、NI(镍)、SN(锡)
- 贵金属：AU(黄金)、AG(白银)
- 农产品/软商品：根据实际补充

【判断规则】
1. 只标注文中明确提及或强烈暗示的品种
2. 如果事件影响整个板块（如"黑色系全面走强"），标注板块内所有核心品种
3. 输出格式必须是合法JSON数组，每项包含 symbol 和 reason

【返回格式】
{
  "symbols": [
    {"symbol": "RB", "confidence": 0.9, "reason": "文章提到螺纹钢社会库存连续5周下降"},
    {"symbol": "HC", "confidence": 0.7, "reason": "热卷出口订单回暖，与螺纹钢高度联动"}
  ]
}"""

def classify_article(article_text, model_client):
    """调用LLM对文章做品种分类"""
    response = model_client.chat.completions.create(
        model="gpt-4o",  # 或 claude / deepseek / qwen
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"【文章正文】\n{article_text[:8000]}"}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)
```

**局限**：
- 依赖外部API，延迟和成本按调用量线性增长
- 长文本可能超过context window
- 缺乏针对性的领域校准

---

### A2：Standard — Embedding + 少量微调

**核心思路**：用 LLM 提取文本嵌入向量（embedding），训练一个轻量分类器（LR/SVM/XGBoost）或小模型 LoRA。

**实现步骤**：

```
Phase 1: 构建标注数据集（最重要、最耗时）
  ├─ 从三类数据源收集原始文章：
  │   ├─ scan_all.py 采集的新闻资讯（东财、AKShare）
  │   ├─ polyester-chain-analysis 采集的聚酯链资讯
  │   └─ energy-chain-analysis 采集的能源链资讯
  │   └─ 目标：2000-5000篇标注文章
  ├─ 标注策略（降低人工成本）：
  │   ├─ 方法1：先用 A1 的 prompt 做自动标注（弱标签）
  │   ├─ 方法2：用 "争议验证法"（仿Bridgewater论文）
  │   │   ├─ 多个 prompt 变体分别标注
  │   │   └─ 结果不一致的 → 人工仲裁
  │   └─ 方法3：从已有研报标题/摘要中自动提取品种关键词
  └─ 最终产出：{article_text, [symbol_labels]} 数据集

Phase 2: 选择训练方案（二选一）
  ├─ 方案A：Embedding + 浅层分类器
  │   ├─ 用 text-embedding-3-large / bge-large 提取 1024d/768d 向量
  │   ├─ 训练 XGBoost 多标签分类器
  │   ├─ 推理速度：<10ms/篇，可在本地运行
  │   └─ 精度：预期 ~75-82%
  └─ 方案B：小模型 LoRA 微调
      ├─ 用 Qwen2.5-7B / LLaMA-3.1-8B + LoRA
      ├─ 单卡 24GB GPU即可（或使用 API 微调）
      ├─ 框架：Unsloth / Axolotl / LLaMA-Factory
      └─ 精度：预期 ~80-88%

Phase 3: 集成到交易工作流
  └─ 写作 WorkBuddy Skill，封装为 CLI 命令
  └─ 集成到 scan_all.py 的资讯采集流程中
  └─ 输出添加品种标签字段，支持按品种筛选
```

**LoRA 微调代码框架**：

```python
# 使用 LLaMA-Factory 或 Unsloth 微调
# 数据集格式示例 (alpaca format):

"""
{
  "instruction": "判断这篇新闻影响哪些期货品种",
  "input": "据Mysteel，截至7月5日当周，螺纹钢社会库存586万吨...",
  "output": '{"symbols": [{"symbol":"RB","confidence":0.95}, {"symbol":"HC","confidence":0.6}]}'
}
"""

# 训练命令示例 (LLaMA-Factory):
"""
CUDA_VISIBLE_DEVICES=0 llamafactory-cli train \
  --model_name_or_path Qwen/Qwen2.5-7B \
  --dataset futures_classification \
  --template qwen \
  --lora_target q_proj,v_proj \
  --finetuning_type lora \
  --num_train_epochs 3 \
  --per_device_train_batch_size 8 \
  --learning_rate 5e-5 \
  --output_dir ./futures-classifier-lora
"""
```

**关键决策**：对掌掌柜而言，**方案A（Embedding+XGBoost）性价比最高**。原因：
1. 不需要 GPU 资源
2. 推理在本地 <10ms
3. 微调 API 调用成本低
4. 精度对分类任务已足够

---

### A3：Advanced — 完整复刻Bridgewater路线

**核心思路**：用 Qwen3-235B + 专家标注数据 + CISPO/OPD 训练，完整复现论文方法。

**实现步骤**：

```
Step 1: 数据集工程
  ├─ 收集 5000-20000 篇标注文章
  ├─ 至少 3 位交易员参与标注仲裁
  ├─ 采用 Bridgewater 的争议导向验证流程
  └─ 数据集分训练/验证/测试（70/15/15）

Step 2: 训练基础设施
  ├─ 方案A：使用 Thinking Machines Lab 的 Tinker（需申请）
  ├─ 方案B：使用 AutoTrain / Modal / RunPod 等云 GPU
  ├─ 方案C：使用 DeepSeek / Fireworks 的 API 微调
  └─ Qwen3-235B 需 8×A100-80G 或等效算力

Step 3: 训练流程
  ├─ 基线：GRPO 训练
  ├─ 交错批处理（Interleaved Batching）实现
  ├─ CISPO 损失 + 非对称裁剪
  ├─ OPD 在策略蒸馏 + 动态教师
  └─ 评估：每20步计算验证准确率

Step 4: 部署
  ├─ 量化到 INT4/INT8 部署（vLLM / TGI）
  ├─ 推理延迟要求：< 2秒/篇
  └─ 持续监控 + 定期重训练
```

**成本估算**：

| 项目 | 估算费用 |
|------|---------|
| 云 GPU 训练（8×A100×72h） | ~$3000-5000 |
| 专家标注（5000篇×$0.5/篇） | ~$2500 |
| 推理部署（vLLM+单卡A100 持续运行） | ~$1000/月 |
| **合计首次投入** | **~$6500-8000** |

> **掌掌柜评估**：对于CTA量化交易个人/小团队，A3方案投入产出比偏低。除非：
> - 每日处理 500+ 篇原文需要分类
> - 分类精度要求 >90%
> - 有持续的数据回流和迭代计划

---

## 路径B：研报质量过滤模型

> **目标**：判断一篇研究报告是否包含"值得关注的产业链驱动信号"，过滤噪声，保留有交易价值的研报。

### 现有优势基础

polyester-chain-analysis 和 energy-chain-analysis 两个技能已经内置了**五层量化打分体系**和**主驱动识别引擎**。这意味着我们不需要从零构建评价标准——现有打分逻辑就可以作为自动标注的"弱监督信号"。

### B1：Minimal — 规则+Prompt过滤

**实现步骤**：

```
Step 1: 定义"值得关注"的质量标准
  ├─ 来自 polyester-chain-analysis 中已有的驱动识别规则：
  │   ├─ 是否包含价格/库存/开工率/利润等量化数据
  │   ├─ 是否涉及供给冲击（检修、停产、出口管制）
  │   ├─ 是否涉及需求变化（政策、季节性、出口）
  │   └─ 是否有明确的方向性判断（利多/利空）
  └─ 将上述规则转化为 Checklist-Prompt

Step 2: 在现有技能中嵌入过滤步骤
  └─ polyester-chain-analysis 的数据采集 → 先过过滤模型 → 再进五层打分
  └─ 过滤掉"无实质驱动"的资讯，节省后续处理成本

Step 3: 验证过滤效果
  └─ 对比过滤前后的五层打分分布
  └─ 确保高评分文章不会被误过滤（低漏报率）
```

**Prompt 模板示例**：

```
你是一位资深的大宗商品产业链研究员。
给定一篇行业研究报告或新闻，判断它是否包含"值得关注的产业链驱动信号"。

【值得关注的判定标准】
1. ✅ 包含量化数据（开工率、库存、利润、价格、基差等）
2. ✅ 包含供给冲击信息（检修计划、停产、进口/出口变化）
3. ✅ 包含需求变化信号（政策、季节性、终端需求数据）
4. ✅ 对价格方向有明确判断或强暗示（利多/利空）
5. ❌ 纯宏观叙事、无具体数据
6. ❌ 重复已知信息、无新增驱动
7. ❌ 过于短期/无实质性影响的日常报道

请用以下格式输出：
{"is_valuable": true/false, "score": 0-100, "reasons": ["...","..."], "direction": "bullish/bearish/neutral"}
```

---

### B2：Standard — 蒸馏打分逻辑到分类模型

**核心思路**：将现有技能中的五层打分逻辑作为"教师"，训练一个学生模型直接输出质量分，大幅加速。

**实现步骤**：

```
Phase 1: 准备训练数据（可以从现有交易日志中自动生成）
  ├─ 源数据：过去3个月 polyester-chain-analysis 和 energy-chain-analysis
  │   处理过的所有研报/资讯
  ├─ 已有信号：每篇文章经由现有技能处理后，已经有一个
  │   五层打分结果和主驱动识别标签
  ├─ 构造训练样本：
  │   ├─ 输入：研报原文
  │   └─ 标签：{有价值的（总评分>60且触发主驱动识别）/ 无价值的}
  └─ 样本量预期：5000-10000篇（自动生成，无需人工标注）

Phase 2: 训练二分类模型
  ├─ 模型选择：DistilBERT / BERT-base-chinese / Qwen2.5-0.5B
  ├─ 训练方法：分类微调
  ├─ 正负样本比例：预估 1:3（噪声远多于信号）
  └─ 评估指标：重点是 Recall（不要漏掉有价值的研报）> 0.9

Phase 3: 部署与集成
  └─ 嵌入到 skills 的数据采集流程中，作为前置过滤
  └─ 过滤掉的前80%低质量内容不再进入五层打分
  └─ 预期：单篇处理时间从 30秒（LLM打分）→ 0.1秒（蒸馏模型）
```

**训练代码框架**：

```python
# quality_filter_training.py — BERT蒸馏分类器
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from datasets import Dataset

# 1. 从现有技能处理日志中提取训练数据
# 数据格式: {"text": "研报全文", "label": 1(有价值)/0(无价值)}
dataset = Dataset.from_json("training_data.jsonl")

# 2. 初始化模型
model_name = "bert-base-chinese"  # 或 "Qwen/Qwen2.5-0.5B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(
    model_name, num_labels=2
)

# 3. 数据预处理
def tokenize_fn(examples):
    return tokenizer(
        examples["text"], truncation=True, max_length=1024, padding="max_length"
    )
dataset = dataset.map(tokenize_fn, batched=True)

# 4. 训练（处理类别不平衡）
from sklearn.utils.class_weight import compute_class_weight
# ... 标准训练循环 ...
```

---

### B3：Advanced — 多维度质量评分模型

**核心思路**：不只是二分类，而是训练一个**多维度评分模型**，输出与五层打分体系对齐的多维评分。

**输出维度**：

| 维度 | 评分范围 | 说明 |
|------|---------|------|
| 数据丰富度 | 0-100 | 是否包含量化数据及数据质量 |
| 供给端冲击 | 0-100 | 供给变化信号的强度 |
| 需求端变化 | 0-100 | 需求信号强度 |
| 方向性判断 | 0-1 | 是否有明确多空方向 |
| 时效性 | 0-100 | 信息的新鲜度和时效 |
| **综合质量** | **0-100** | 加权总分 |

**训练方法**：多任务回归模型，输出6个连续分数，用 MSE 损失训练。基座模型推荐 Qwen2.5-7B + LoRA。

---

## 路径C：辩论专家团预筛选增强

> **目标**：在 futures-debate-team 的辩论流程中，引入前置过滤步骤——数技源的 scan_all 输出先经模型预筛选，只将有意义的信号送入后续辩论流程（探源→观澜→链证源→正反方辩手→闫判官），避免为噪声信号做完整辩论。

### C1：Minimal — 触发阈值过滤

**不涉及任何模型训练，直接修改工作流配置**。

```
Step 1: 分析数技源输出结构
  └─ 读取 scan_all.py 输出格式（_meta字段、score、signal_type等）
  └─ 确定哪些字段可以作为"值得辩论"的指标

Step 2: 设定过滤规则
  └─ 规则示例：
  │   ├─ scan_all 的信号强度评分 < 30 → 跳过辩论
  │   ├─ scan_all 的信号类型为 "常规数据更新" → 跳过辩论
  │   ├─ scan_all + 历史模式匹配（过去3天已有相同信号→不重复辩论）
  │   └─ 仅 "新出现的趋势反转/突破" 类型才触发辩论流程

Step 3: 在辩论调度器中实现
  └─ 修改闫判官（主持人）角色定义
  └─ 在接到数技源输出后 → 先过过滤规则 → 决定是否广播给研究员
```

**优势**：零训练成本、规则透明可解释、当天可上线。
**局限**：规则是硬编码的，无法捕获隐含的"值得辩论"信号。

---

### C2：Standard — 争议度预测模型

**核心思路**：训练一个模型预测"某个信号是否值得辩论"——即预测如果该信号进入辩论流程，辩论专家们是否能产生有价值的输出（而非"无争议的一致同意"）。

**为什么是"争议度"**？Bridgewater 论文的隐含前提：当不同专家对信息的判断一致时，信息本身没什么价值。真正有价值的是**专家之间产生争议、需要深入讨论才能得出结论的信号**。

```
Phase 1: 构建训练数据（从辩论历史中自动生成）
  ├─ 历史数据源：过去 futures-debate-team 每次辩论的完整日志
  ├─ 正样本（值得辩论）：
  │   ├─ 正/反方辩手论点差异大（embedding 余弦距离 < 0.6）
  │   ├─ 闫判官最终裁决有明确偏向而非"无明确信号"
  │   └─ 辩论结果最终被用户采纳用于交易
  ├─ 负样本（不值得辩论）：
  │   ├─ 正反方论点高度一致
  │   ├─ 闫判官裁决为"无明确方向"
  │   └─ 辩论结果未被用户采纳
  ├─ 输入特征：数技源 scan_all 的输出 + 当前持仓/市场状态
  └─ 输出：值得辩论的概率 [0,1]

Phase 2: 模型选择
  └─ 方案A：XGBoost 在 特征向量上（特征工程）
  │   ├─ 特征：信号强度、信号类型、品种近期波动率、持仓量变化、等
  │   └─ 精度预期：~75-85%
  └─ 方案B：轻量 Transformer（输入 scan_all 输出的原始 JSON）
      ├─ 直接处理 scan_all 的 _meta 字段
      └─ 精度预期：~80-90%

Phase 3: 集成到辩论流程
  └─ 在闫判官（主持人）角色定义中增添一个前置步骤
  └─ 数技源输出 → 争议度预测模型 → 低于阈值 → 跳过辩论，直接输出摘要
  └─ 数技源输出 → 争议度预测模型 → 高于阈值 → 触发完整辩论链
```

**争议度预测的特征工程示例**：

```python
# debate_worth_features.py — 特征构建
def extract_debate_worthiness_features(scan_output, market_state):
    """
    从 scan_all 输出 + 市场状态提取特征
    """
    features = {}

    # 1. 信号强度特征
    features['signal_strength'] = scan_output.get('score', 0)
    features['signal_type_code'] = encode_signal_type(scan_output.get('signal_type', ''))
    features['has_direction'] = 1 if scan_output.get('direction') in ('bullish', 'bearish') else 0

    # 2. 市场状态特征
    features['recent_volatility'] = market_state.get('volatility_20d', 0)
    features['volume_anomaly'] = market_state.get('volume_zscore', 0)
    features['open_interest_change'] = market_state.get('oi_change_pct', 0)

    # 3. 历史模式特征
    features['days_since_last_signal'] = scan_output.get('days_since_same_type', 99)
    features['signal_frequency_7d'] = scan_output.get('signal_count_7d', 0)

    # 4. 品种特征
    features['symbol_correlation'] = market_state.get('correlation_with_portfolio', 0)
    features['current_position'] = encode_position(market_state.get('position', 'none'))

    return features
```

---

### C3：Advanced — 辩论结果预测 + 端到端优化

**核心思路**：不只是预测"是否值得辩论"，而是直接预测"辩论后的最终结果是什么"——相当于用一个端到端模型来替代完整的辩论链。

**架构设计**：

```
┌──────────────────────────────────────────────────┐
│              三层漏斗架构                         │
├──────────────────────────────────────────────────┤
│  Level 1: 快速过滤（C1 规则过滤）                │
│  └─ 规则引擎，O(1)时间，过滤80%噪声               │
├──────────────────────────────────────────────────┤
│  Level 2: 争议度预测（C2 模型）                  │
│  └─ 轻量模型，<0.1s，过滤剩余噪声的50%            │
├──────────────────────────────────────────────────┤
│  Level 3: 辩论结果预测（C3 Advanced）            │
│  └─ 中等模型，~1s，预测辩论最终裁决               │
│  └─ 高置信度预测 → 跳过辩论，直接输出            │
│  └─ 低置信度预测 → 触发完整辩论专家团             │
└──────────────────────────────────────────────────┘
```

**训练方法**：模仿 Bridgewater的 OPD 策略，但把"教师"定义为完整的辩论专家团：

```
Step 1: 让完整辩论链运行 1000 次 → 收集输入(scan输出) → 输出(辩论最终裁决)
Step 2: 训练一个学生模型来预测辩论裁决（多分类：bullish/bearish/neutral/skip）
Step 3: 学生模型高置信度(>0.9) → 直接输出，跳过辩论
Step 4: 学生模型低置信度(<0.9) → 走完整辩论链
Step 5: 辩论链产生的结果与学生的预测对比 → 计算蒸馏损失
Step 6: 用 CISPO 损失回传更新学生模型
```

**这实际上是对 Bridgewater 论文方法论的一次反向应用**：
- Bridgewater：用专家标注训练模型
- 我们：用辩论专家团的裁决作为"教师"训练预筛选模型

---

## 三条路径的优先级建议

基于掌掌柜现有资源和CTA交易的需求紧急性，建议按以下顺序推进：

```
Phase 1（本周） ─────────────── Phase 2（本月） ─────────── Phase 3（季度）
                                                                                            
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│ 路径C-Minimal   │ ──────→ │ 路径C-Standard  │ ──────→ │ 路径A-Standard  │
│ 辩论规则过滤    │          │ 争议度预测模型   │          │ 品种分类模型     │
│ 成本: 0         │          │ 成本: ~$50       │          │ 成本: ~$100-200  │
│ 时间: 2天       │          │ 时间: 2周        │          │ 时间: 3周        │
│ 效果: 减少50%   │          │ 效果: 减少70%    │          │ 效果: 自动标记   │
│ 无用辩论        │          │ 无用辩论        │          │ 所有资讯品种     │
└─────────────────┘          └─────────────────┘          └─────────────────┘
                                                                                            
         │                            │                            │
         ▼                            ▼                            ▼
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│ 路径B-Minimal   │ ──────→ │ 路径B-Standard  │ ──────→ │ 全链路集成      │
│ 研报Prompt过滤  │          │ 研报质量蒸馏模型  │          │ scan输入→品种分类 │
│ 成本: 0         │          │ 成本: ~$50       │          │ →质量过滤→辩论   │
│ 时间: 1天       │          │ 时间: 1周        │          │ 触发→交易信号    │
│ 效果: 快速试错  │          │ 效果: 80倍加速   │          │                   │
└─────────────────┘          └─────────────────┘          └─────────────────┘
```

**执行原则**：
1. **从 Minimal 开始**：在1-2天内跑通流程，验证效果
2. **无人工标注启动**：利用现有技能的输出作为弱监督信号
3. **MVP 优先**：先减少90%的工作量，再优化10%的质量
4. **以使用反馈驱动**：每版上线后收集掌掌柜的使用反馈，决定是否进入下一级

---

## 与 Bridgewater 论文的异同对照

| 维度 | Bridgewater（论文） | 我们的实施方案 |
|------|-------------------|--------------|
| **领域** | 宏观投资（桥水） | CTA商品期货 |
| **任务** | 金融文档相关性/分类 | 品种分类+质量过滤+辩论预筛选 |
| **模型规模** | 235B (Qwen3) | 7B-72B(标准)/Embedding+GBDT(轻量) |
| **标注方式** | 专家人工标注+争议验证 | 现有技能自动标注+争议验证 |
| **训练框架** | Tinker (Thinking Machines) | LLaMA-Factory / Unsloth / API微调 |
| **核心技术** | GRPO + CISPO + OPD | 蒸馏学习 + LoRA + 争议度预测 |
| **成本** | ~$5000+ | ~$50-500 |
| **部署** | 云端推理 | 本地推理(轻量)/云端(重量) |
| **核心理念** | 用专家数据训练更好模型 | 用现有流程自动化产生信号 |

**我们的差异化优势**：
- 不需要从零构建标注数据——已有 skills 的输出可作为弱监督信号
- 任务更聚焦（CTA品种+产业驱动），模型可以更小
- 辩论专家团的裁决天然可作为"教师信号"用于蒸馏

---

## 下一步行动

如果掌掌柜同意以上方向，建议的下一步具体行动：

1. **先做路径C-Minimal**：花1天分析 scan_all.py 的输出结构，设定过滤规则
2. **再做路径B-Minimal**：花半天写一个 Prompt 过滤工具，在现有技能数据流中插入
3. **根据两周使用反馈**，决定是否进入 Standard 级别的模型训练

是否需要我：
- (a) 直接开始实现路径C-Minimal的规则过滤脚本
- (b) 深入设计路径B-Standard的蒸馏训练方案
- (c) 先做一份现有 scan_all 输出格式的详细分析文档

请选择。
