# 兼容矩阵 — FDT Skill 间版本依赖

> 记录各 skill、pipeline、scheduler 之间的版本依赖关系和破坏性变更历史。
> 更新时间：2026-07-10

## 依赖关系总览

```
pipeline/runner.py ──→ quant-daily (scan_all)    v2.14+
         │           → commodity-chain-analysis   v2.16+
         │           → futures-trading-analysis   phase3
         │           → scripts/memory_writer
         │
scheduler/engine.py ──→ pipeline/runner.py
         │           → bootstrap.py               v5.6+
         │
quant-daily ─────────→ (独立，数据源层)
commodity-chain ─────→ quant-daily                v2.14+ (品种列表)
debate-argument-builder → quant-daily             v2.14+
         │           → fundamental-data-collector  v1.1+
         │           → commodity-chain-analysis    v2.16+
         │           → technical-analysis          v2.2+
debate-judge ────────→ debate-argument-builder     v2.3+
         │           → debate-risk-manager         v4.1+
         │           → debate-trading-planner
debate-trading-planner → debate-judge (output)
debate-risk-manager ──→ debate-trading-planner    (input)
         │           → technical-analysis          v2.2+ (support_resistance)
futures-trading-analysis → all above skills
```

## Skill 兼容性矩阵

| Skill | 当前版本 | 依赖 | 破坏性变更 | 备注 |
|:------|:--------|:-----|:-----------|:-----|
| **quant-daily** | 2.14.0 | 无 | — | 数据源层，下游依赖最多 |
| **fundamental-data-collector** | 1.1.0 | quant-daily ≥2.12 | v1.1: data_interface API 重构 | 为探源提供因子数据 |
| **commodity-chain-analysis** | 2.16.0 | quant-daily ≥2.14 | v2.16: 动态相关系数替代硬编码 | 链证源单品产出 |
| **technical-analysis** | 2.2.0 | quant-daily ≥2.14 | v2.2: ZigZag 支持 OI 确认 | 观澜支撑阻力输出 |
| **debate-argument-builder** | 2.3.0 | 上述 4 个 | v2.3: 双角色双模式框架 | 正反方辩手共用 |
| **debate-judge** | 2.x | debate-argument-builder ≥2.3 | — | 闫判官裁决引擎 |
| **debate-trading-planner** | — | debate-judge output | — | 策执远策略生成 |
| **debate-risk-manager** | 4.1.0 | debate-trading-planner + technical-analysis ≥2.2 | v4.1: 智能选锚+仓位反推 | 风控明审核 |
| **futures-trading-analysis** | v5.2+ | 全部 skill | phase3_generate_report.py v3.2 | 报告生成入口 |
| **fdt-spawn-debate** | — | futures-trading-analysis | — | 内部流程说明书 |

## Pipeline 兼容性

| 组件 | 版本 | 依赖 | 备注 |
|:-----|:-----|:-----|:-----|
| **pipeline/runner.py** | — | quant-daily scan_all ≥2.14<br>commodity-chain analyze_chain.py<br>quant-daily debate_brief.py<br>quant-daily assemble_intermediate_data.py<br>futures-trading-analysis phase3_generate_report.py | 6阶段全自动流水线 |
| **scheduler/engine.py** | — | bootstrap.py ≥5.6<br>scheduler/triggers.py<br>scheduler/tasks.py | 守护进程调度 |

## 脚本兼容性

| 脚本 | 依赖 | 备注 |
|:-----|:-----|:-----|
| **scripts/unified_logger.py** | 无 | 日志框架，被 runner 和 bootstrap 使用 |
| **scripts/trace_id.py** | 无 | 链路追踪，被 runner 使用 |
| **scripts/agent_waiter.py** | team_config.json (G13 后) | Agent 产出轮询 |
| **scripts/memory_writer.py** | 无 | 记忆写入 |
| **scripts/debate_archiver.py** | memory_writer.py | 辩论归档 |
| **scripts/record_verdicts.py** | memory_writer.py | 裁决同步 |
| **config/schema.py** | pydantic ≥2.0 | 配置校验 |

## 破坏性变更记录

| 日期 | 版本 | 变更内容 | 影响范围 | 迁移路径 |
|:-----|:-----|:---------|:---------|:---------|
| 2026-07-10 | v5.6.0 | trace_id 注入子进程 env `FDT_TRACE_ID` | pipeline/runner.py 子进程 | 消费者可选读取该 env-var |
| 2026-07-10 | v5.6.0 | pipeline 日志迁移到 unified_logger | runner.py log 格式变化 | 日志路径不变，格式统一 |
| 2026-07-06 | v5.2 | 通道突破信号替代 L1-L4+因子择时为主信号源 | scan_all、debate_brief | P1 只跑 channel_breakout |
| 2026-07-03 | v5.1 | L1-L5 鲁棒性防线 + APM-CS 五轴 | 全局 | 新增 validate_agent_output 等校验 |

## 升级检查清单

当升级某个 skill 时，检查以下项目：

1. [ ] 该 skill 的版本号在 SKILL.md 和 pyproject.toml 中一致
2. [ ] 所有上游依赖的版本约束仍然满足
3. [ ] 输出 schema 无破坏性变更（或记录在上表中）
4. [ ] 集成测试通过（G5/G6 覆盖范围）
5. [ ] `selfcheck.py` 健康检查通过
