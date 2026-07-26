# EvoMem 补丁记忆范式在 FDT 中的落地优化方案

> 基于 arXiv:2606.13681 (EvoArena: Tracking Memory Evolution for Robust LLM Agents in Dynamic Environments) 的应用分析
> 创建：2026-07-26 | 当前 FDT 版本：v10.4.2
> 关联文档：05-observability.md, 07-operations.md, 08-gap-analysis.md, human-ai-hybrid-finance-fdt-optimization.md

---

## 1. 背景：FDT 同样面临"环境演化"问题

EvoArena 的核心洞察——Agent 记忆被当作"最新状态快照"管理，每次更新直接覆盖旧版本，导致状态坍塌——在 FDT 中长期运行中同样存在：

| FDT 中的演化对象 | 当前处理 | 问题 |
|:----------------|:---------|:-----|
| **市场状态**（波动率 regime / 趋势方向 / 宏观情景） | 每轮辩论从头分析，不保留"状态转移"记录 | 同一品种在不同市场状态下需完全不同的分析框架 |
| **产业链知识**（供需平衡 / 利润传导 / 出口窗口） | 存入静态知识文件，发生口径变更时只记录不追溯 | 旧版本的产业链逻辑可能在新结构下仍然适用于特定情境 |
| **Agent 经验**（裁决偏差 / 规则修正 / 用户反馈） | session_memory 按时间记录 JSONL，但无差异化结构 | 新经验覆盖旧经验，无法追溯\"什么情境下这条经验成立\" |
| **数据源属性**（API 变更 / 字段退役 / 频率变化） | 在口径变更 YAML 事件库中记录，但 Agent 运行时不可查 | Agent 可能引用已过时的数据定义 |

## 2. 核心改进：补丁记忆（Patch Memory）

### 2.1 当前 session_memory 格式

`jsonl
{
  "intent": "修复生猪止损计算偏差",
  "actions": [...],
  "outcome": "止损价改为收盘价 - N×ATR",
  "learned": "【P0铁律】止损价必须由代码精确计算",
  "message_summary_time": "2026-07-24T02:34:05",
  "message_id": "fdt-xxx"
}
`

### 2.2 改进后的补丁格式

在现有字段基础上，增加 EvoMem 风格的 patch 结构：

`jsonl
{
  "patch_id": "patch-20260726-001",
  "domain": "生猪|止损规则",             // 领域标签，用于检索
  "trace_id": "fdt-debate-xxx",
  "pre_state": "止损价由LLM基于ATR估算（±20%偏差常见）",
  "post_state": "止损价由代码按 收盘价 - N×ATR 精确计算",
  "rationale": "LLM估算的止损偏差导致多笔交易提前出局，经掌柜确认改为代码硬计算",
  "evidence": ["回测数据显示LLM止损偏差率32%", "掌柜2026-07-24裁决确认"],
  "conditions": {
    "applicable_regime": ["all"],              // 该补丁适用的市场状态（空=全部适用）
    "inapplicable_regime": [],                 // 不适用状态
    "valid_from": "2026-07-24",
    "valid_until": null                        // null=长期有效
  },
  "intent": "修复生猪止损计算偏差",
  "actions": ["修改node_verdict止损逻辑", "增加L0验证"],
  "outcome": "止损价改为收盘价 - N×ATR",
  "learned": "【P0铁律】止损价必须由代码精确计算",
  "message_summary_time": "2026-07-24T02:34:05"
}
`

新增字段说明：
- **patch_id**：全局唯一，按时间+序号编码
- **domain**：领域标签（多级，用 | 分隔），用于按领域检索
- **pre_state / post_state**：变化前后的状态描述（EvoMem 核心思想）
- **rationale**：更新理由——为什么必须变
- **evidence**：支撑该变更的证据链
- **conditions**：版本适用条件——知道补丁何时生效、何时需检查过往记录

## 3. 架构改动

### 3.1 MemoryManager 接口扩展

在现有 MemoryManager 上增加两个方法：

`
FDT MemoryManager (现有)
├── add_entry()              # 现有：写入 session_memory
├── search()                 # 现有：按关键词检索
├── get_latest()             # 现有：获取最新条目
└── query_by_version()       # **新增**：按版本区间检索相关补丁
    └── query_by_domain()    # **新增**：按领域检索补丁链
    └── resolve_conflict()   # **新增**：当存在矛盾补丁时返回裁决依据
`

### 3.2 版本化知识库索引

在 _session_memory/ 下增加：

`
_session_memory/
├── 20260726/
│   ├── session_memory_fdt-xxx.jsonl    # 现有完整记录
│   └── patches.jsonl                   # 新增：纯补丁索引（仅含 patch 类记录）
├── patches_index.json                  # 新增：域→补丁ID 倒排索引，加速检索
`

### 3.3 补丁创建时机

非 retrospective 创建全部已有历史，而是设 **3 个自动触发点** + 1 个手动触发：

| 触发点 | 触发条件 | 示例 |
|:-------|:---------|:-----|
| **规则变更** | CLAUDE.md 或 harness 规则文件中 P0/P1 规则被新增/修改 | 如\"止损改代码计算\" |
| **知识库更新** | market/ 或 industry-chain/ 下文件新增重大内容（非增量补充） | 如产业链传导逻辑修改 |
| **裁决偏差** | P5 风控发现连续 N 次裁决偏差超阈值，触发的根因分析 | 如猪周期判断持续偏差 |
| **手动触发** | 掌柜确认的重要经验教训 | 按月review时创建 |

### 3.4 数据量预估

| 项目 | 数值 |
|:-----|:-----|
| 日均辩论轮次 | ≈5-8 轮 |
| 日均补丁数（预估） | 1-3 条（规则变更不一定每天发生） |
| 年补丁总量 | ≈500-1000 条 |
| 索引大小 | JSON < 50KB，可忽略不计 |

## 4. 检索与使用场景

### 场景 A：P4 闫判官裁决时检索相关经验

**当前**：P4 的 context 通过 search() 检索最近 N 条 session_memory 条目，相关性取决于关键词匹配。

**改进**：P4 启动时额外调用 query_by_version(domain="生猪", regime="当前市场状态")，获取：
1. 适用当前版本的补丁（valid_until=null 或 时间区间包含当前日期）
2. 该领域的补丁链摘要（\"过去3个月内，生猪相关的规则发生了哪些变化\"）
3. 冲突记录（如果存在相互矛盾的补丁）

**效果**：P4 不仅知道当前规则，还理解\"规则如何演变到当前状态\"，减少在新市场结构下误用旧规则。

### 场景 B：P2.5 多因子注入时校准参数

**当前**：因子参数从代码/配置中读取固定值。

**改进**：查询 query_by_domain(domain="技术参数|生猪|ATR")：
- 获取 ATR 倍数的历史调整记录
- 判断当前市场状态是否接近某次调整的触发条件

### 场景 C：产业链知识的版本化演进

以生猪产业链为例：

`
v1 (2025-12 - 2026-03)：传统猪周期框架（产能-价格 18个月滞后）
  ↓ 补丁：2026-03 产能去化速度超预期，修正滞后系数
v2 (2026-03 - 2026-06)：修正版（滞后缩短至 12-14 个月）
  ↓ 补丁：2026-06 引入集团厂占比变量，修正传导系数
v3 (2026-06 至今)：双轨制（散养户 + 集团厂双产能模型）
`

**不使用文件覆盖，而是 patch chain**：
- 知识库文件中保留当前有效版本
- patch 索引记录\"什么改变了，为什么改变，之前是什么\"
- P1.5 链证源 Agent 在分析时能判断\"当前的市场结构更接近哪个版本\"

## 5. 实施路线

### Phase 1：session_memory 格式升级（预计 2 天）

**交付物**：
- patch_id / domain / pre_state / post_state / rationale / evidence / conditions 字段定义
- MemoryManager 增加 query_by_version() 和 query_by_domain() 接口
- session_memory 迁移脚本（旧条目补空字段）

### Phase 2：补丁创建自动化（预计 3 天）

**交付物**：
- CLAUDE.md 更新检测 hook：规则变更 → 自动创建 patch
- 知识库文件变动检测：按文件路径映射到 domain，创建 patch
- P5 偏差阈值触发：连续 N 次偏差 → 创建 patch + 触发根因分析

### Phase 3：P4/P2.5 消费端集成（预计 3 天）

**交付物**：
- P4 裁决前补丁检索集成（query_by_version + 摘要注入）
- P2.5 因子参数校准（query_by_domain + regime 匹配）
- 补丁链可视化（可选，HTML 报告中增加\"知识演化\"段落）

### Phase 4：产业链知识版本化（预计 5 天）

**交付物**：
- 一条产业链（建议：生猪或铁矿-螺纹）的 patch chain 初始化
- 链知识由\"文件覆盖\"改为\"当前版本 + patch 索引\"双存储
- P1.5 链证源 Agent 版本感知能力

## 6. 成功标准

| 指标 | 当前基线 | 目标（Phase 4 完成后） |
|:-----|:---------|:---------------------|
| P4 裁决引用历史经验的准确度 | 依赖关键词匹配 | 增加版本上下文后，经验引用准确率 > 80% |
| 产业链知识变更追溯时间 | 无（靠人工回忆或翻 git log） | < 5 分钟找到特定变更的 rationale |
| 规则冲突检测 | 无 | 补丁链中自动标出矛盾补丁 |
| 记忆检索相关性 | 最后 N 条按时间 | 域+版本过滤后的高相关性结果 |

## 7. 与现有 FDT 架构的兼容性

| 现有组件 | 兼容分析 |
|:---------|:---------|
| session_memory JSONL | patch 格式向后兼容——旧条目补 null 字段即可 |
| MemoryManager | 增加 3 个方法，不修改现有 add_entry/search/get_latest |
| harness 检查清单 | 增加 C18（补丁完整性检查）C19（补丁域标签合规） |
| pre-commit hook | 增加补丁索引一致性检查 |
| FDT 报告排版 | 可选增加\"知识演化\"小段落，不影响现有结构 |

## 8. 参考文献

- Xu, J. et al. (2026). EvoArena: Tracking Memory Evolution for Robust LLM Agents in Dynamic Environments. arXiv:2606.13681.
- Human-AI Hybrid Finance Framework FDT 优化方案（FDT docs/designs/human-ai-hybrid-finance-fdt-optimization.md）
