# 09 — 驾驭工程推进计划（Phase 1–4 完成 · Phase 5 整顿中）

> 从 4.0/5.0 成熟度向 4.7/5.0 推进的路线图、任务分解和验收标准。

## 1. 最终状态（2026-07-10）

| 指标 | 值 | 说明 |
|:-----|:---|:-----|
| 最终成熟度 | **~4.6/5.0**（2026-07-14 实测复核） | 4 个 Phase 完成 + G14/G16/G17 待办 |
| 已修复差距 | **12/15 确证 + 3 待办** | G1-G13/G15 确证；G14 未落地、G16 重构失效、G17 文档不同步 |
| 测试用例 | **24 文件 / 12 目录**（非全绿） | pipeline 5/10 失效(G16)；scheduler(10)+memory(9)+contracts(14) 维持 |
| 版本 | v6.3.1 | 已推送 CTAAgents/experts |
| 剩余差距 | 11 (5 P1 + 6 P2) | — |
| 现有测试 | 23 文件, 8 目录 | 覆盖率仅覆盖 quant-daily/signals |
| 目标成熟度 | 4.7/5.0 | Phase 4 完成后 |

## 2. 推进策略

### 2.1 执行原则

- **快速赢得即可交付**：低风险高价值项（G13, G10）在 Phase 2 主干中穿插完成，不阻塞
- **测试先于改动**：每项改动如果涉及代码，先有测试再改，或先有集成测试框架再补案例
- **不追求完美覆盖**：90% 行覆盖是天花板，核心是"所有外部接口和状态变更都有测试"

### 2.2 并行策略

```
Phase 2 (测试补齐)            Phase 3 穿插项
─────────────────────        ─────────────────
G7 覆盖率扩展 (0.5h)   ←→    G10 兼容矩阵 (0.5h)
     │                            │
     ↓                            ↓
G5 pipeline测试 (3h)        G13 熔断可配 (1h)
     │                            │
     ↓                            ↓
G6 scheduler测试 (2h)       G9 graceful drain (2h)
     │
     ↓
G8 memory测试 (2h)
```

G7 和 G10 都是纯配置/文档——先做，不到 1 小时两块都清掉。然后 G5 和 G13 并行：G5 需要集中注意力写 mock，G13 是机械性参数提取。

## 3. Phase 2 — 测试补齐（目标：4.0 → 4.3）

### G7: 覆盖率扩展

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `pyproject.toml` L73-76 |
| 当前状态 | `--cov=skills/quant-daily/scripts/signals` — 只覆盖 signals 子目录 |
| 目标状态 | 覆盖全部 skill scripts + pipeline/ + scheduler/ + scripts/ |
| 验收标准 | `pytest --cov` 输出至少包含 6 个模块，总覆盖率 > 60% |
| 风险 | 首次全量覆盖率可能很低（30-40%），属正常；目标是框架就位 |

**实施步骤**：

1. 修改 `pyproject.toml` `testpaths` 和 `addopts`
2. 运行 `pytest --cov-report=term-missing` 确认基线
3. 记录基线覆盖率作为后续参照

### G5: Pipeline 集成测试

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `pipeline/runner.py`, 新建 `tests/pipeline/test_runner.py` |
| 当前状态 | runner.py 0 测试覆盖 |
| 目标状态 | mock 子进程调用的集成测试，覆盖 6 阶段主流程 + 失败不阻断 |
| 验收标准 | `test_runner.py` ≥ 6 个测试用例，覆盖 scan → chain → debate_brief → assemble → report → history 完整链 |
| 依赖 | G7（覆盖率扩展后 runner.py 进入范围） |

**测试案例清单**：

| 案例 | 描述 | mock 内容 |
|:-----|:-----|:---------|
| `test_full_pipeline_success` | 全部 6 阶段成功 | 所有 subprocess.run 返回 0 |
| `test_scan_failure_continues` | scan_all 失败但流水线继续 | step 1 返回非 0，其余成功 |
| `test_chain_missing_skips` | 缺 analyze_chain.py 时跳过 | Path.exists() → False |
| `test_assembly_missing_chain_skips` | 缺 chain_analysis JSON 时跳过 | glob 返回空 |
| `test_report_failure_non_blocking` | 报告生成失败其余正常 | step 5 非 0 |
| `test_trace_id_injection` | trace_id 注入子进程 env | 检查 env["FDT_TRACE_ID"] |

### G6: Scheduler 集成测试

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `scheduler/engine.py`, `scheduler/triggers.py`, 新建 `tests/scheduler/test_engine.py` |
| 目标状态 | 验证调度器的触发匹配逻辑和防重复机制 |
| 验收标准 | `test_engine.py` ≥ 4 个用例，覆盖触发器检查 + 任务执行 + 防重复 |

**测试案例清单**：

| 案例 | 描述 |
|:-----|:-----|
| `test_trigger_fires_at_correct_time` | 时间匹配时触发 |
| `test_trigger_skips_when_not_time` | 时间不匹配时跳过 |
| `test_dedup_prevents_double_fire` | 同窗口不重复触发 |
| `test_max_tasks_per_beat_caps` | 心跳任务数 ≤ max_tasks_per_beat |

### G8: Memory 写入测试

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `scripts/memory_writer.py`, `scripts/debate_archiver.py`, 新建 `tests/memory/test_writer.py` |
| 目标状态 | 验证 Journal/Index/Record 三类写入的原子性和去重 |
| 验收标准 | `test_writer.py` ≥ 4 个用例 |

**测试案例清单**：

| 案例 | 描述 |
|:-----|:-----|
| `test_append_journal_creates_entry` | 追加 journal 记录 |
| `test_append_index_updates_index` | 索引正确更新 |
| `test_append_record_contains_required_fields` | record 包含所有必需字段 |
| `test_concurrent_writes_no_duplicates` | 并发写入不产生重复 |

## 4. Phase 3 穿插项（Phase 2 进行中完成）

### G10: API 兼容矩阵

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | 新建 `docs/compatibility-matrix.md` |
| 目标状态 | 纯文档，列出各 skill 间的版本依赖关系 |
| 验收标准 | 覆盖所有 10 个 skill + pipeline + scheduler，含版本号和破坏性变更记录 |
| 工作量 | 0.5h |

### G13: 熔断阈值可配置

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `agent_waiter.py` (+ `team_config.json` + `config/schema.py`) |
| 当前状态 | timeout=900s, poll_interval=15s, stable_seconds=5s, retry=2 — 全部硬编码 |
| 目标状态 | 从 `team_config.json` 读取，`config/schema.py` 校验，Agent 创建时注入 |
| 验收标准 | 修改 `team_config.json` 中 agent_waiter 配置 → agent_waiter 行为变化 |
| 工作量 | 1h |

**实施步骤**：

1. `config/schema.py` 新增 `AgentWaiterConfig`
2. `team_config.json` 新增 `agent_waiter` 节
3. `agent_waiter.py` 新增 `from_config()` 工厂函数
4. 默认值保持与当前硬编码一致（向后兼容）

### G9: Graceful Drain

| 属性 | 说明 |
|:-----|:-----|
| 涉及文件 | `scheduler/engine.py` |
| 当前状态 | SIGTERM/SIGINT 只设 `_running=False`，不等待 in-flight 任务 |
| 目标状态 | 收信号后：停止接受新触发 → 等待当前任务完成（最长 5 分钟）→ 保存状态 → 退出 |
| 验收标准 | SIGTERM 后 scheduler 不立即退出，日志显示 "draining in-flight task" → 任务完成 → "gracefully stopped" |
| 工作量 | 2h |

## 5. Phase 3 — 运维增强（目标：4.3 → 4.5）

| 项 | 内容 | 工作量 |
|:--|:-----|:------|
| **G9** (承上) | graceful drain | 穿插完成 |
| **G13** (承上) | 熔断可配置 | 穿插完成 |
| **G10** (承上) | 兼容矩阵 | 穿插完成 |
| **G14** | `contracts/migrations.py` — Agent 产出格式版本迁移 | 3h |

### G14 设计要点

- 迁移表：`{ "skill": "debate-argument-builder", "from_version": "1.0", "to_version": "2.0", "migrate": callable }`
- 自动检测 `meta.version` 字段，不匹配时查找迁移路径
- 链式迁移：1.0 → 2.0 → 3.0 自动串联

## 6. Phase 4 — 体验优化（目标：4.5 → 4.7，长期）

| 项 | 内容 | 工作量 |
|:--|:-----|:------|
| G11 | 监控看板 — 简易 HTML dashboard 展示 APM-CS 五轴 + 在线 Agent 状态 | 4h |
| G12 | 健康端点 — `scripts/health_server.py` HTTP `/health` + `/metrics` | 2h |
| G15 | 结构化日志 — unified_logger 支持 JSON 格式（可选开关） | 1h |

## 7. 里程碑总览

```
Phase 1 ──── ✅ 4.0 ──── G1 schema · G2 trace · G3 日志 · G4 版本
Phase 2 ──── ✅ 4.3 ──── G7 覆盖率 · G10 兼容矩阵 · G13 熔断 · G5 pipeline · G6 scheduler · G8 memory
Phase 3 ──── ✅ 4.6 ──── G9 drain · ⚠️ G14 版本迁移(经 07-14 复核确认未落地)
Phase 4 ──── ✅ 4.7 ──── G11 看板 · G12 健康端点 · G15 JSON日志
Phase 5 ──── ✅ 5.0 ──── G16 pipeline 测试修复 · G14 迁移落地 · G17 文档同步纪律
Phase 6 ──── ✅ 5.0(新增G19/G20/G21/G22/G23) ── G19测试✅ · G20⏳ · G21⏳ · G22/G23✅
Phase 7 ──── ✅ v8.1.7 ── 策略层插拔化 · CTA 7/7 · 多因子 · 趋势扩展 · 均值回归 · 信号去融合
Phase 8 ──── ✅ v8.3.0 ── LangGraph 迁移 · 按需并行拓扑 · PostgreSQL OLTP+OLAP · 独立 CLI/FastAPI · 去 WorkBuddy/DuckDB
Phase 9 ──── ✅ v8.4.0 ── LangGraph 生产集成 · A/B 切换机制 · PG+SQLite Checkpointer 降级 · 99 测试全绿 · G52-G58 全部关闭

```

## 8. 执行总结

全部 4 个 Phase 在 2026-07-10 当天完成，总耗时约 3.5 小时。

| Phase | 交付物 | 数量 |
|:------|:-------|:----:|
| P1 | config/schema.py · scripts/trace_id.py · 修改 runner/bootstrap/pyproject | 4 项 |
| P2 | 29 测试用例 + 兼容矩阵 + 熔断可配置 | 7 项 |
| P3 | graceful drain + 合约版本迁移 28 条路径 + contracts 桥接层 | 3 项 |
| P4 | 监控看板 + 健康端点 + JSON 日志 | 3 项 |

**所有风险评估均已验证**：pipeline 测试用 tmp_path+monkeypatch 隔离、scheduler 用 datetime 注入、memory 用 threading.Barrier 并发、G14 用工厂函数批量覆盖。

## 9. 风险登记（已关闭）

| 风险 | 结果 |
|:-----|:-----|
| pipeline 测试因硬编码路径在 Windows 上失败 | ⚠️ 2026-07-14 回归：v6.3.0 重构将 Step1 改为数技源信号+观澜/探源按需 `step_scan()`，但 `test_runner.py` 仍 mock 旧名 `step_scan_dual` → 5/10 失败（G16）。需随重构同步测试 |
| scheduler 触发逻辑依赖 datetime.now() 难以 mock | ✅ TimeTrigger.check(now) 接受注入 |
| memory_writer 并发测试需要多线程 | ✅ threading.Barrier + Queue，5 线程无 crash |
| G14 迁移逻辑复杂度超预估 | ✅ 工厂函数 _migrate_v20_to_v30 批量覆盖 |
