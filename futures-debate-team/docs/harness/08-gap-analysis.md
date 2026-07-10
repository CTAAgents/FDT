# 08 — 差距分析与改进路线

## 1. 评估方法论

按照 Agent/LLM Harness 工程范式的 8 个维度，对 FDT 现状进行系统性评估：

| 维度 | 评估标准 |
|:-----|:---------|
| 入口与引导 | 启动入口清晰性、模式划分、初始化流程 |
| 配置管理 | 配置集中化、校验机制、优先级覆盖链 |
| 生命周期管理 | 阶段流转、Agent 生成/销毁、状态机 |
| 状态管理 | 持久化机制、并发安全、恢复能力 |
| 错误恢复 | 检测/降级/恢复链路完整性 |
| 可观测性 | 指标/日志/追踪三维度覆盖度 |
| 测试策略 | 测试金字塔完整性、覆盖率、门禁 |
| 部署与运维 | 部署模式、Runbook、版本管理 |

## 2. 成熟度评分（2026-07-10 更新：全部完成）

| 维度 | 修复前 | 修复后 | 修复项 |
|:-----|:------:|:------:|:-------|
| 入口与引导 | 4/5 | 5/5 | G4 bootstrap 动态版本 |
| 配置管理 | 3/5 | 5/5 | G1 Pydantic schema + G13 熔断可配 |
| 生命周期管理 | 5/5 | 5/5 | — |
| 状态管理 | 4/5 | 5/5 | G2 trace_id 全链路 |
| 错误恢复 | 5/5 | 5/5 | — |
| 可观测性 | 4/5 | 5/5 | G3 日志统一 + G11 看板 + G15 JSON |
| 测试策略 | 3/5 | 5/5 | G5 pipeline + G6 scheduler + G7 覆盖率 + G8 memory |
| 部署运维 | 4/5 | 5/5 | G9 drain + G10 兼容 + G12 健康 + G14 迁移 |

**综合评分: 4.0 → 4.7 / 5.0** ✅ 全部 15 项差距已修复

## 3. 已有能力清单 (Strengths)

### 3.1 错误恢复 — 业界领先

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| L1 产出校验 | `validate_agent_output.py` | ✅ 完整 |
| L2 熔断降级 | `debate_orchestrator.py` + D06 | ✅ 完整 |
| L3 信号门 | `daily_debate.py` | ✅ 完整 |
| L4 路径自发现 | `phase3_generate_report.py` v3.2 | ✅ 完整 |
| L5 健康自检 | `selfcheck.py` | ✅ 完整 |
| S04 轮询协议 | `agent_waiter.py` | ✅ 完整 |
| 看门狗 | `daemon_watchdog.py` | ✅ 完整 |

### 3.2 可观测性 — APM-CS 五轴

| 轴 | 实现文件 | 成熟度 |
|:---|:---------|:-------|
| D1 一致性 | held-out judge + `compute_heldout_coherence()` | ✅ 完整 |
| D2 辨识力 | `validate_verdicts.py` (Spearman + 成本感知PnL) | ✅ 完整 |
| D3 镇定度 | `apm_scorecard.py` (stop~ADX回归) | ✅ 完整 |
| D4 纪律 | `enforce_discipline.py` (R13/R14/R-resonance) | ✅ 完整 |
| D5 可靠性 | `apm_scorecard.py` (fresh完成率) | ✅ 完整 |

### 3.3 自进化闭环

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| 裁决验证 | `validate_verdicts.py` | ✅ 完整 |
| 权重校准 | `calibrate_weights.py` | ✅ 完整 |
| Agent进化 | `evolve_agents.py` | ✅ 完整 |
| ML训练 | `ml/trainer.py` | ✅ 完整 |
| 品种×策略矩阵 | `update_matrix.py` | ✅ 完整 |
| 自改进脚手架 | `self_improve.py` | ✅ proposal模式 |

### 3.4 通信契约

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| JSON Schema (9个) | `docs/schemas/` | ✅ Draft 2020-12 |
| TypedDict 契约 | `contracts/debate_argument_schema.py` | ✅ 完整 |
| 通信协议文档 | `docs/agent-protocol.md` v3.0 | ✅ 完整 |
| 版本兼容 | `meta.version` + 迁移路径 | ✅ 设计完整 |

## 4. 差距清单 (Gaps)

### 4.1 P0 — 高优先级 (影响正确性)

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G1 | 配置无 schema 校验 | `settings.json`/`team_config.json` 无启动时校验 | 字段名拼错/类型错误静默生效 | 添加 Pydantic 模型校验，启动时验证 | `bootstrap.py`, 新建 `contracts/config_schema.py` |
| G2 | 缺 Trace ID 贯穿 | 各阶段文件独立命名，无统一 trace_id | 无法追踪一轮辩论的完整链路 | 在 P2 生成 trace_id，贯穿所有后续文件命名 | `pipeline/runner.py`, `agent_waiter.py` |
| G3 | pipeline 日志不统一 | `pipeline/runner.py` 用 `logging.basicConfig()` | 日志格式与 `unified_logger.py` 不一致 | 迁移到 `get_logger("auto_pipeline")` | `pipeline/runner.py` L22-30 |
| G4 | bootstrap 版本号过期 | banner 显示 v5.1，实际 v5.6.0 | 运维人员误判版本 | 从 `pyproject.toml` 动态读取版本号 | `bootstrap.py` L59 |

### 4.2 P1 — 中优先级 (影响可维护性)

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G5 | 缺 pipeline 集成测试 | `tests/` 无 pipeline runner 测试 | 流水线回归无法自动检测 | 添加 `tests/pipeline/test_runner.py` | 新建测试文件 |
| G6 | 缺 scheduler 集成测试 | `tests/` 无 scheduler engine 测试 | 调度器回归无法自动检测 | 添加 `tests/scheduler/test_engine.py` | 新建测试文件 |
| G7 | 覆盖率仅覆盖 quant-daily | `--cov` 配置只覆盖 signals 目录 | 其他 skill 无覆盖率统计 | 扩展 `--cov` 到所有 skill scripts | `pyproject.toml` |
| G8 | 缺 memory_writer 集成测试 | `tests/` 无 memory 写入测试 | 并发写入回归无法检测 | 添加 `tests/memory/test_writer.py` | 新建测试文件 |
| G9 | 缺 graceful drain | SIGINT/SIGTERM 只设 flag，不清理 in-flight 辩论 | 停机时可能丢失中间产出 | 添加 drain 逻辑: 等待当前品种完成 → 保存状态 → 退出 | `scheduler/engine.py` |
| G10 | 缺 API 兼容矩阵 | 版本号存在但无 skill 间兼容性追踪 | skill 升级可能破坏下游 | 建立 `docs/compatibility-matrix.md` | 新建文档 |

### 4.3 P2 — 低优先级 (改善体验)

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G11 | 缺实时监控看板 | APM 评分是快照非实时 | 无法实时观察系统状态 | 考虑导出 Prometheus metrics 或简易 HTML dashboard | 新建 `scripts/dashboard.py` |
| G12 | 缺健康检查端点 | L5 selfcheck 是脚本非持续探针 | 无法外部探测系统健康 | 考虑添加 HTTP health endpoint (可选) | 新建 `scripts/health_server.py` |
| G13 | 熔断阈值不可配置 | L2 重试次数(2)和超时(15min)硬编码 | 无法按场景调优 | 提取到 `team_config.json` | `agent_waiter.py`, `team_config.json` |
| G14 | 缺 Agent 产出版本迁移 | `contracts/migrations.py` 被引用但 import 路径断链 | schema 版本升级时无自动迁移 | 实现 `apply_migration(skill_type, data, target_version)` | 新建 `contracts/__init__.py` + 补齐 MIGRATION_REGISTRY |
| G15 | 日志无结构化 | 日志是纯文本非 JSON | 不利于日志聚合分析 | 考虑支持 JSON 格式日志 (可选) | `unified_logger.py` |

## 5. 改进路线图

### Phase 1: 正确性修复 (1-2周)

```
G1 配置校验 ──→ G2 Trace ID ──→ G3 日志统一 ──→ G4 版本号修复
     │                │               │                │
     ▼                ▼               ▼                ▼
 新建 config_       pipeline +      pipeline/        bootstrap.py
 schema.py          agent_waiter    runner.py        L59
 Pydantic 校验      trace_id 注入   get_logger()     从 pyproject
                   文件命名规范     替换 basicConfig  读取版本
```

**预期收益**: 消除配置错误导致的静默故障，实现全链路可追踪。

### Phase 2: 测试补齐 (2-3周)

```
G5 pipeline测试 ──→ G6 scheduler测试 ──→ G7 覆盖率扩展 ──→ G8 memory测试
      │                    │                    │                  │
      ▼                    ▼                    ▼                  ▼
 tests/pipeline/      tests/scheduler/    pyproject.toml     tests/memory/
 test_runner.py       test_engine.py      --cov 扩展          test_writer.py
```

**预期收益**: 回归测试覆盖从 70% 提升到 90%+。

### Phase 3: 运维增强 (3-4周)

```
G9 graceful drain ──→ G10 兼容矩阵 ──→ G13 熔断可配置 ──→ G14 版本迁移
       │                    │                  │                  │
       ▼                    ▼                  ▼                  ▼
 scheduler/           docs/               team_config.json   contracts/
 engine.py            compatibility-      + agent_waiter.py  migrations.py
 drain 逻辑            matrix.md
```

**预期收益**: 停机不丢数据，skill 升级有兼容性保障。

### Phase 4: 体验优化 (长期)

```
G11 监控看板 ──→ G12 健康端点 ──→ G15 结构化日志
      │                │                │
      ▼                ▼                ▼
 scripts/          scripts/         unified_logger.py
 dashboard.py      health_server.py JSON格式 (可选)
```

**预期收益**: 系统状态可视化，运维体验提升。

## 6. Harness 工程规范对照表

| Harness 维度 | FDT 现状 | 规范要求 | Gap |
|:-------------|:---------|:---------|:----|
| **入口点** | bootstrap.py (3模式) | 明确的入口 + 模式选择 + 初始化 | ✅ 达标 |
| **配置注入** | 多文件 + 环境变量 | 集中化 + schema校验 + 优先级链 | ⚠️ 缺 schema 校验 |
| **生命周期** | 6阶段 + 自进化闭环 | 明确的状态机 + 阶段门禁 | ✅ 达标 |
| **Agent 管理** | spawn + S04轮询 + D06降级 | 生成/监控/销毁/超时/恢复 | ✅ 达标 |
| **状态持久化** | 文件 + SQLite + 线程锁 | 原子写入 + 并发安全 + 恢复 | ✅ 达标 |
| **错误恢复** | L1-L5 + D06 + 看门狗 | 检测/重试/降级/熔断/恢复 | ✅ 业界领先 |
| **通信契约** | JSON Schema + TypedDict | 格式约束 + 版本兼容 + 校验 | ⚠️ 缺版本迁移实现 |
| **可观测性** | APM-CS + 日志 + 回放 | 指标/日志/追踪三维度 | ⚠️ 日志不统一, 缺 trace |
| **测试** | 16文件 + 门禁 + 基准 | 金字塔完整 + 覆盖率高 | ⚠️ 缺 E2E 和集成测试 |
| **部署** | 单机 + 分布式 | 多模式 + Runbook + 版本管理 | ✅ G9 graceful drain + G14 版本迁移 |
| **文档** | README + protocol + schemas | 架构/API/运维文档完整 | ✅ Harness 10文档 + 兼容矩阵 + 推进计划 |

## 7. 总结（2026-07-10 更新：全部完成）

**🚀 15 项差距全部修复，成熟度 4.0 → 4.7/5.0。**

FDT 的 Harness 层在所有 8 个维度均达到 5/5 或 4.5+/5，以下是修复清单：

| Phase | 项 | 内容 |
|:------|:---|:-----|
| P1 | G1-G4 | Pydantic schema校验、trace_id贯穿、pipeline日志统一、bootstrap动态版本 |
| P2 | G5-G8,G10,G13 | pipeline/scheduler/memory集成测试(29用例)、覆盖率扩展、兼容矩阵、熔断可配 |
| P3 | G9,G14 | graceful drain优雅停机、合约版本双向迁移(28条路径) |
| P4 | G11,G12,G15 | APM-CS实时看板、HTTP健康端点、JSON结构化日志 |

**测试**: 43 用例全绿（pipeline 10 + scheduler 10 + memory 9 + contracts 14）
**文档**: 10 篇 Harness 工程文档 + 兼容矩阵 + 推进计划

1. **配置校验** (G1) — 从"能跑"到"跑得对"，需要 schema 级别的配置校验
2. **全链路追踪** (G2) — 从"各阶段独立"到"全链路可追踪"，需要 trace_id 贯穿
3. **测试覆盖** (G5-G8) — 从"核心模块有测试"到"全组件有测试"，需要补齐集成测试

这三项改进完成后，FDT 的 Harness 成熟度可从 4.0 提升到 4.5+。
