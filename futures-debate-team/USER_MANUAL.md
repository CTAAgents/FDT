# 期货交易辩论专家团 — 用户使用手册 (v4.0)

## 1. 概述

期货交易辩论专家团是一个 **多Agent深度辩论型期货分析系统**，通过 **11个专业角色Agent** 在 **3阶段串行管道** 中协作，对商品期货品种进行结构化多空辩论分析。

**核心理念**：不是AI替你做决定，而是AI帮你把分析做透。v4.0关键升级：Agent从"嘴炮"进化为"数据辩论"——每个Agent可通过```tool协议调用真实数据工具，所有因子数据带`_provenance`溯源标签，评分带收敛判据自动决定是否追加轮次。

**版本**：v4.0 | **Agent数**：11（1协调员 + 10角色）| **核心创新**：数据溯源+Agent工具+自适应收敛+复盘系统

## 2. 系统架构

```
                    ┌── 用户（交易员）
                    │
┌───────────────────▼────────────────────┐
│           明鉴秋（独立协调员）           │
│  选题→触发→工具协调→收束→拍板→复盘     │
└───────────────┬────────────────────────┘
                │
    ┌───────────┬───────────┬───────────┐
    ▼           ▼           ▼           ▼
 数技源     探源(工具)   观澜(技术)   量化分析
 (数据)   (researcher)  (debater)   (7因子+provenance)
    │           │           │           │
    └───────────┴───────────┴───────────┘
                    │
                    ▼
          ┌──────────────────┐
          │  闫判官（裁判）    │
          │  收敛判据检测轮数  │
          │  评分工具计算      │
          └──────────────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
    证真（正方）            慎思（反方）
    debater_tools查因子     debater_tools驳因子
    引用4层+provenance     质疑数据质量+溯源
         │                     │
         └──────────┬──────────┘
                    ▼
          ┌──────────────────┐
          │  策执远（策略师）   │
          │  方案+情景分析     │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │  风控明（审核）    │
          └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │  明鉴秋复盘归档   │
          │  INDEX.md写入     │
          │  Agent表现跟踪    │
          └──────────────────┘
```

## 3. 辩论流程详解

### 阶段一：选题与准备（明鉴秋负责）

1. 选定品种、周期、账户权益
2. 启动数技师：`scan_all.py` 产出基础数据
3. **启动量化分析（新增）**：`scan_true_layered.py --reverse` 产出7因子排名+九宫格+左右侧
4. 广播数据包给全体角色

### 阶段二：辩论（闫判官主持）

**准备期**：
- 基本面研究员 → 供需/库存/利润快照
- 技术面研究员 → 量价/持仓/关键位
- 链证源 → 产业链快照
- **量化信号包（新增）** → 7因子排名、九宫格、左右侧识别

**辩论期**（自适应轮数·v4.0收敛判据）：
| 时段 | 内容 | 工具 |
|:----|:------|:-----|
| 0-8min | 正方立论（引用4层数据+debater_tools查因子分解） | `get_factor_decomp` |
| 8-16min | 反方立论（从4层数据找漏洞+质疑provenance） | `get_factor_decomp` |
| 16-24min | 正方rebuttal | - |
| 24-32min | 反方rebuttal | - |
| ⚡收敛检测 | 闫判官检测分歧度 → spread≥15提前终止 / ≤3结束 / else续辩 | `check_convergence` |
| 32-42min | 自由交锋（如果需要） | - |
| 42-48min | 最终陈述 → 评分工具计算总分 | `compute_total_score` |

**评审期**：
- 策略师出可执行方案（含scenario_analysis情景推演）
- 风控审核（含quant-daily vetor_penalty检查）
- 风控有red veto时打回修改

**判决期**：
- 6维评分（含量化一致性维度）
- 输出判决+评分明细
- 提炼论证模式→记忆系统

### 阶段三：决策与归档（明鉴秋负责）

- 结合量化信号左右侧做最终决策
- 追加辩论日志到记忆系统（INDEX.md + agent_performance）
- 输出HTML报告（含不确定性标注+分歧度数据）

## 4. 记忆系统

专家目录下的 `memory/` 文件夹包含：

| 文件 | 用途 | 说明 |
|:----|:----|:-----|
| `debate_journal.json` | 所有历史辩论记录 | JSON编辑器 |
| `data_sources.md` | 各数据源可靠性评级 | Markdown阅读器 |
| `argument_patterns.md` | 有效论证模式 | Markdown阅读器 |
| `debater_profiles.md` | 各角色表现 | Markdown阅读器 |
| `execution_followup.json` | 实盘执行回溯 | JSON编辑器 |
| `rules/veto_rules.md` | 否决规则 | Markdown阅读器 |
| `rules/weighting_rules.md` | 评分权重历史 | Markdown阅读器 |
| `debates/INDEX.md` | **v4.0**辩论索引（品种→ID→评分→胜方） | 复盘检索 |
| `debates/analysis/agent_performance.md` | **v4.0**Agent表现跟踪（各轮评分对比） | 复盘分析 |

## 5. 依赖的Skills

| Skill | 版本 | 用途 | v4.0新增组件 |
|:------|:----:|:-----|:-------------|
| quant-daily | >=2.0.0 | 数据管道+真分层打分引擎 | `_provenance`数据溯源标签 |
| commodity-chain-analysis | >=2.13.0 | 基本面+产业链分析 | `scripts/researcher_tools.py` |
| debate-argument-builder | v4.0 | 正反方论点构建 | `scripts/debater_tools.py` |
| debate-judge | v4.0 | 闫判官辩论主持+收敛判据 | `scripts/judge_tools.py` |
| debate-risk-manager | >=3.1 | 风控审核（含veto_penalty） | - |
| debate-trading-planner | v4.0 | 策执远策略生成 | `scripts/scenario_analysis.py` |
| futures-trading-analysis | v4.0 | 主协调+工具执行+复盘 | `scripts/agent_tool_executor.py`+`post_debate_analysis.py` |

## 6. 变更日志

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v4.0** | **2026-07-04** | **数据辩论升级**：Agent真实工具绑定(agent_tool_executor+researcher_tools+debater_tools+judge_tools)；数据溯源标签_provenance；收敛判据(分歧度自适应轮数)；情景分析(Bull/Base/Bear)；复盘系统(post_debate_analysis+INDEX.md+agent_performance)；Agent prompts升级工具协议；文档全面更新 |
| v3.3 | 2026-07-04 | 集成quant-daily真分层打分：新增量化信号包、九宫格分类、左右侧识别；辩手数据来源4层；风控新增veto_penalty红线；评分模型6维；内建记忆系统7文件 |
