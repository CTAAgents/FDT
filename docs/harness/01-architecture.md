# 01 — Harness 架构总览

## 1. 分层架构

FDT 的 Harness 层从下到上分为 5 层，每层有明确的职责边界：

```
┌─────────────────────────────────────────────────────────────────────┐
│                     L5 — 可观测性层 (Observability)                   │
│   APM-CS五轴 · 统一日志 · ViBench回放 · 失败聚类 · 自改进脚手架        │
├─────────────────────────────────────────────────────────────────────┤
│                     L4 — 编排调度层 (Orchestration)                   │
│   bootstrap入口 · scheduler心跳 · pipeline流水线 · 自进化闭环          │
├─────────────────────────────────────────────────────────────────────┤
│                     L3 — 通信契约层 (Contract)                        │
│   JSON Schema(9个) · TypedDict契约 · agent-protocol v3.0 · S04轮询   │
├─────────────────────────────────────────────────────────────────────┤
│                     L2 — 鲁棒性防线 (Resilience)                      │
│   L1产出校验 · L2熔断降级 · L3信号门 · L4路径发现 · L5健康自检        │
├─────────────────────────────────────────────────────────────────────┤
│                     L1 — 基础设施层 (Infrastructure)                   │
│   memory系统 · unified_logger · memory_writer · debate_archiver      │
└─────────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层 | 职责 | 核心组件 |
|:--|:-----|:---------|
| **L1 基础设施** | 持久化、日志、并发安全写入 | `memory/` (27文件), `unified_logger.py`, `memory_writer.py`, `debate_archiver.py` |
| **L2 鲁棒性** | 错误检测、降级、恢复 | L1-L5五层防线, `agent_waiter.py`, D06降级, S04协议 |
| **L3 通信契约** | Agent 间数据格式约束 | `docs/schemas/` (9个JSON Schema), `contracts/debate_argument_schema.py`, `docs/agent-protocol.md` |
| **L4 编排调度** | 流程驱动、任务调度 | `bootstrap.py`, `scheduler/engine.py`, `pipeline/runner.py`, `scripts/validate_verdicts.py`等 |
| **L5 可观测性** | 质量度量、诊断、改进 | `apm_scorecard.py`, `cluster_failures.py`, `run_benchmark.py`, `self_improve.py` |

## 2. 组件关系图

```
                    ┌──────────────┐
                    │  bootstrap   │ ← 入口 (once/daemon/interactive)
                    └──────┬───────┘
                           │
              ┌────────────▼────────────┐
              │   SchedulerEngine       │ ← 心跳调度 (60s间隔)
              │   (scheduler/engine.py) │
              └────────────┬────────────┘
                           │ 触发
              ┌────────────▼────────────┐
              │   Pipeline Runner       │ ← 全自动流水线 (6步)
              │   (pipeline/runner.py)  │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                  ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ 自进化前置   │ │ 6阶段辩论    │ │ 归档+报告    │
  │ validate→    │ │ P1→P1.5→    │ │ archiver→   │
  │ calibrate→   │ │ P2→P3→     │ │ memory_writer│
  │ evolve→ML    │ │ P4→P5→P6   │ │ →HTML报告    │
  └──────────────┘ └──────────────┘ └──────────────┘
                           │
              ┌────────────▼────────────┐
              │   10 Agent 协作         │
              │  (spawn via Agent tool) │
              │  通信: 文件 + S04轮询   │
              │  契约: JSON Schema      │
              │  恢复: L1-L5 + D06      │
              └─────────────────────────┘
```

## 3. 数据流总览

### 3.1 主数据流（一轮完整辩论）

```
用户请求
    │
    ▼
[自进化前置] ──→ validate_verdicts.py ──→ calibrate_weights.py ──→ evolve_agents.py
    │                    (K线验证)           (权重校准)              (参数进化)
    ▼
[P1] 数技源信号扫描+观澜/探源按需能力（v6.3.0 架构，详见 02-lifecycle §5.1）
    ├─ 数技源 scan_all.py(channel_breakout)        ──→ full_scan_summary_{date}.json
    ├─ 观澜 run_l1l4_scan.py(technical-analysis)    ──→ full_scan_l1l4_{date}.json
    └─ 探源 run_factor_timing_scan.py(fundamental-data-collector) ──→ full_scan_factor_timing_{date}.json
    │                    ↓ 信号检查闸门 (读 full_scan_summary, 无 |total|≥DEBATE_ENTRY_MIN_ABS 候选则终止)
    ▼
[P1.5] 链证源 ──→ chain_analysis_{date}.json (产业链景气度)
    │
    ▼
[P2] 闫判官 ──→ p2_judge_direction.json (选品种+定方向)
    │
    ▼
[P3] 观澜+探源 (并行) ──→ p3_technical_{sym}.json + p3_fundamental_{sym}.json
    │
    ▼
[P4] 证真+慎思 (并行) ──→ p4_affirmative_{sym}.json + p4_opposition_{sym}.json
    │
    ▼
[P5] 闫判官裁决 ──→ p_judge_final_{trace_id}.json
    │   ↓
    │ 策执远 ──→ p4_trading_plan_{sym}.json
    │   ↓
    │ 风控明 ──→ p4_risk_verdict_{sym}.json
    │
    ▼
[P6] 明鉴秋汇总 ──→ debate_results.json + debate_results.html
    │
    ▼
record_verdicts.py ──→ execution_followup.json (供下次自进化验证)
```

### 3.2 状态持久化路径

| 数据类型 | 存储位置 | 格式 | 写入者 |
|:---------|:---------|:-----|:-------|
| 信号扫描结果 | `Commodities/Reports/.../{date}/` | JSON | `scan_all.py` |
| Agent 产出 | `Commodities/Reports/.../{date}/research_snapshots/` | JSON | 各 Agent |
| 辩论裁决 | `Commodities/Reports/.../{date}/debate_results.json` | JSON | 明鉴秋 |
| HTML 报告 | `Commodities/Reports/.../{date}/debate_results.html` | HTML | `phase3_generate_report.py` |
| 辩论日志 | `memory/debate_journal.json` | JSON | `debate_archiver.py` |
| 裁决回溯 | `memory/execution_followup.json` | JSON | `record_verdicts.py` |
| Agent 进化参数 | `memory/agent_profiles.json` | JSON | `evolve_agents.py` |
| 权重校准 | `memory/calibration.json` | JSON | `calibrate_weights.py` |
| 验证统计 | `memory/validation_stats.json` | JSON | `validate_verdicts.py` |
| 辩论索引 | `memory/debates/INDEX.md` | Markdown | `debate_archiver.py` |
| 流水线日志 | `Commodities/Reports/.../pipeline_{date}.log` | Log | `pipeline/runner.py` |
| 统一日志 | `~/Documents/WorkBuddy/Logs/fdb_{date}.log` | Log | `unified_logger.py` |
| 调度器日志 | `scheduler/scheduler.log` | Log | `scheduler/engine.py` |

## 4. Agent 拓扑

```
                    ┌─────────────┐
                    │  明鉴秋     │ ← 团队主管 (调度+汇总)
                    │  team-lead  │
                    └──────┬──────┘
                           │ spawn + 文件传递
          ┌────────────────┼────────────────┐
          ▼                ▼                 ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ 数技源       │ │ 链证源       │ │ 闫判官       │
   │ datatech     │ │ chain-analyst│ │ judge        │
   │ (P1 扫描)    │ │ (P1.5 产业链)│ │ (P2+P5 裁决) │
   └──────────────┘ └──────────────┘ └──────┬───────┘
                                          │ 定方向
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
            ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
            │ 观澜         │     │ 探源         │     │              │
            │ technical    │     │ fundamental  │     │ (并行供弹)   │
            │ (技术面)     │     │ (基本面)     │     │              │
            └──────────────┘     └──────────────┘     └──────────────┘
                    │                     │
                    └──────────┬──────────┘
                               │ 研究员资料
                    ┌──────────▼──────────┐
                    │ 证真 ⇄ 慎思         │ ← 动态正反方
                    │ affirmative         │   (方向由闫判官指定)
                    │ opposition          │
                    └──────────┬──────────┘
                               │ 辩论论据
                    ┌──────────▼──────────┐
                    │ 闫判官 (裁决)       │
                    │ → 策执远 (方案)     │
                    │ → 风控明 (审核)     │
                    │ → 一致性裁判 (审计) │ ← 非阻断
                    └─────────────────────┘
```

## 5. 与现有文档的关系

| 现有文档 | 关注点 | 与 Harness 文档的关系 |
|:---------|:-------|:---------------------|
| `README.md` | 功能特性 + 版本历史 + CLI | Harness 文档从工程视角补充"怎么跑起来的" |
| `docs/agent-protocol.md` | Agent 通信契约 | Harness 文档引用其 schema 定义，补充生命周期视角 |
| `docs/business_flow.md` | 业务流程 SOP | Harness 文档关注技术执行层，不重复业务逻辑 |
| `rules/futures-debate-team_rules.md` | 全局规则 | Harness 文档将规则映射到具体的工程实现 |
