# FDT 专家团长期记忆（MEMORY.md）

> 用户偏好、操作铁律、跨会话长期事实。仅保留运行时记忆相关内容。
> 工程规范（文档先行/13项检查/版本号纪律等）归属 `docs/harness/`，不在此处重复。
> 每节标记 `<!-- agents: agent1,agent2 -->` 用于 rules_injector 按 Agent 身份注入。

---

<!-- agents: team_lead -->
## 🔴 用户铁律：FDT 操作一律记入 FDT 自身记忆系统

- **规则**：凡对 FDT 的任何操作（代码/配置/记忆/辩论产物），必须写入 FDT 自身记忆系统（`memory/` 目录），绝不写入外部工作空间。
- **背景**：FDT 是独立系统，脱离平台须能独立生存，记忆必须自包含。
- **落点对照**（记忆系统重构 v10.0.0 后）：
  - 代码版本历史 → `docs/harness/07-operations.md`
  - 用户偏好/长期事实 → 本文件（`MEMORY.md`）
  - 辩论执行 → `journal/debate_journal.json`（通过 `MemoryManager.store_journal()`）
  - 事故与教训 → `incidents/incidents.md`
  - 裁决修正 → `revisions/judgment_revisions.md`
  - 风控政策 → `policies/veto_policies.md`

<!-- agents: team_lead -->
## 🔴 用户铁律（续）：FDT 工作文档一律存于 FDT 自身目录

- **规则**：凡 FDT 的设计文档/diff 对比报告/实施方案/架构说明/研究笔记等「工作文档」，必须存放在 FDT 项目目录下。
- **落点对照**：
  - 设计/架构/diff → `docs/designs/`
  - 研究笔记/评估基线 → `memory/knowledge/`
  - 规范文档 → `docs/harness/`

<!-- agents: bullish_analyst,bearish_analyst -->
## 🔴 去融合铁律（G41）

**不同策略哲学、甚至同策略内子信号均不得融合。** 每个子策略信号必须独立产出、独立送辩论层裁决。

**实现规则**：
- `StrategyFusion` 已废弃（`fusion_method=no_fusion`）
- `mean_reversion.rsi/.cci/.bb` 各独立 `ScoredSignal`，不投票不坍缩
- `trend_following.dc20/.dc55/.bb/...` 各独立
- 每个信号必须带 `reason` 字段
- 知识库 `memory/knowledge/strategies/_index.json` 供辩论子 Agent 查阅

<!-- agents: all -->
## 🔴 FDT 独立 Agent 系统定位

FDT 的发展方向是一个独立 Agent 系统，未来不依赖外部平台即可独立运行。

| 维度 | 应该做 | 不应该做 |
|:-----|:-------|:---------|
| 代码 | 把逻辑写进 FDT 源码（`.py` + `docs/`） | 依赖外部平台的 Skill |
| CLI | 通过 `fdt_cli.py` 子命令暴露能力 | 依赖外部工具链 |
| 配置 | FDT 内部的 `config/` + `settings.py` | 依赖工作空间配置 |
| 记忆 | FDT 内部的 `memory/` 目录 | 依赖工作空间记忆 |
| Agent | 逐步建立独立的 Agent 调度层 | 长期依赖外部 spawn 机制 |

<!-- agents: all -->
## 🏗️ 信号层架构原则

信号计算与验证器范式专属配对（`signal_type → [validator_ids]` 声明式映射），非通用验证器验证所有信号。单一真相源 = `config/settings.py.SIGNAL_VALIDATOR_MAP`。

---

## 以下规则于 2026-07-24 确立（P0 不可违反）

<!-- agents: judge,risk_manager -->
### 🔴 交易建议必须使用当前市价入场

- entry_price 必须使用当前市场实时价格
- 禁止挂单价/等待回调区间（如"5,850-5,950"）
- 禁止价格区间，必须给出确定的单一价格
- 盈亏比须随实际入场价动态计算
- 止损价以当前市价为基准计算
- neutral 方向：入场/目标/止损显示"—（待触发）"

<!-- agents: quality_assurance -->
### 🔴 P3.5 品藻质检是辩论必经阶段

- 每次辩论报告必须包含 P3.5 品藻质检可视化章节
- 质检结果必须在前端可视化显示，不可仅在后台运行
- neutral 方向豁免 entry_price/stop_loss_price/target_price 条件必填

<!-- agents: judge,quality_assurance -->
### 🔴 报告显示规范：中文术语 + 禁止JSON源码

- 报告内禁止展示原始 JSON 源码
- 所有数据必须以可视化表格/卡片展示
- 字段使用中文术语

| 英文规范字段 | 中文术语 |
|:------------|:--------|
| direction | 方向（观望/做多/做空） |
| confidence | 置信度 |
| grade | 信号等级 |
| entry_price | 入场价 |
| target_price | 目标价 |
| stop_loss_price | 止损价 |
| position_pct | 建议仓位 |
| risk_reward_ratio | 盈亏比 |
| risk_color | 风控颜色（绿灯/黄灯/红灯） |
| approved | 风控审批（已通过/未通过） |

<!-- agents: quality_assurance,judge -->
### 🟡 技术指标数据源标注

- FDC 实时计算 → 注明"FDC 实时计算"
- 网络公开数据 → 用 ⚠ 警示框提示可能存在偏差
