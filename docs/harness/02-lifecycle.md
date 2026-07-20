# 02 — 生命周期与编排

## 1. 入口引导 (Bootstrap) — 独立运行模式

### 1.1 三种启动模式（去 WorkBuddy）

| 模式 | 命令 | 用途 | 退出条件 |
|:-----|:-----|:-----|:---------|
| `cli once` | `python fdt_cli.py --once` | 单次执行完整辩论流程 | 执行完即退出 |
| `cli daemon` | `python fdt_cli.py --daemon --cron "0 9 * * 1-5"` | 后台守护进程（APScheduler） | 收到 SIGINT/SIGTERM |
| `api` | `python fdt_api.py --host 0.0.0.0 --port 8000` | FastAPI HTTP 服务 | 收到 SIGINT/SIGTERM |
| `api trigger` | `POST /api/v1/debate` | API 触发单次辩论 | 执行完返回 |

### 1.1a 旧模式（已废弃）

| 模式 | 状态 | 替代方案 |
|:-----|:-----|:---------|
| WorkBuddy automation (30min) | **已废弃** | `fdt_cli.py --daemon` |
| `bootstrap.py` | **已废弃** | `fdt_cli.py` |
| `scheduler/engine.py` (60s心跳) | **可选保留** | APScheduler / Celery Beat |

> **迁移说明**: WorkBuddy 平台依赖已完全移除。FDT 现在作为独立 Python 应用运行，通过 CLI 或 HTTP API 触发。原有 `bootstrap.py` 和 `scheduler/engine.py` 保留为兼容层，但新入口推荐使用 `fdt_cli.py` 和 `fdt_api.py`。

### 1.2 启动序列

```
fdt_cli.py main()
    │
    ├─ 1. 路径校准: os.chdir(_ROOT) + sys.path.insert
    │
    ├─ 2. 记忆加载: load_memory()
    │     ├─ 扫描 memory/*.md (文档文件)
    │     ├─ 扫描 memory/*.json (数据文件)
    │     ├─ 关键文件检查 (judgment_revisions.md, incidents.md, agent_profiles.json, execution_followup.json)
    │     ├─ R规则计数
    │     └─ Agent/Skill 数量统计
    │
    ├─ 3. 模式分发:
    │     ├─ daemon → SchedulerEngine().run_forever()
    │     ├─ once   → run_once() (单次 check_and_run)
    │     └─ interactive → 打印可用命令
    │
    └─ 4. daemon 模式额外:
          ├─ 写入 PID 到 memory/daemon.pid
          ├─ 注册 SIGINT/SIGTERM 信号处理
          └─ 进入 60s 心跳循环
```

### 1.3 代码位置

| 组件 | 文件 | 行号 |
|:-----|:-----|:-----|
| 入口函数 | `fdt_cli.py` | `main()` |
| 守护进程 | `scheduler/engine.py` | `run_forever()` L170 |
| 信号处理 | `scheduler/engine.py` | `_handle_sig()` L185 |
| 进程分离 | `scheduler/engine.py` | `_daemonize()` L131 |

## 2. 六阶段流水线 (P1-P6)

### 2.1 阶段状态机（v8.3.0+ 按需并行版本）

```
                    ┌─────────────────────────┐
                    │   自进化前置 (自动)      │
                    │   validate → calibrate  │
                    │   → evolve → ML check   │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
              ┌─────│   P1: 可插拔多策略扫描   │
              │     │   数技源 (scan_all.py)   │
              │     │   trend_following(10信号)│
              │     │   mean_reversion(3信号) │
              │     │   + 自定义策略插件       │
              │     └───────────┬─────────────┘
              │                 │
              │     ┌───────────▼─────────────┐
              │     │  信号检查闸门             │
              │     │  select_triggers()        │
              │     │  filter=ON: |total|       │
              │     │  filter=OFF: |_raw_total| │
              │     └───┬───────────────┬──────┘
              │         │ Yes           │ No
              │         ▼               ▼
              │  ┌──────────────┐  ┌──────────────┐
              │  │ P2: 闫判官   │  │ 提前终止     │
              │  │ 选品种+定方向 │  │ 汇报"无信号" │
              │  │ + 调度决策    │  └──────────────┘
              │  └──────┬───────┘
              │         │
              │         ▼ (按需并行调度)
              │  ┌──────────────────────────┐
              │  │  P3: 并行数据源           │
              │  │  ┌─────────┬───────────┐  │
              │  │  │ 链证源  │ 观澜     │  │
              │  │  │ 产业链  │ 技术面   │  │
              │  │  └─────────┴───────────┘  │
              │  │  ┌───────────────────┐    │
              │  │  │ 探源              │    │
              │  │  │ 基本面            │    │
              │  │  └───────────────────┘    │
              │  └──────┬────────────────────┘
              │         │
              │  ┌──────▼───────┐
              │  │ P4: 六阶段攻防 │ ← 串行六步
              │  │ bullish_v1→  │
              │  │ bearish_v1→ │
              │  │ bearish_    │
              │  │ rebuttal→   │
              │  │ bullish_    │
              │  │ rebuttal→   │
              │  │ bear_final→ │
              │  │ bull_final  │
              │  └──────┬───────┘
              │         │
              │  ┌──────▼───────┐
              │  │ P5: 裁决链   │ ← 串行
              │  │ 闫判官→风控明│
              │  │ (闫判官含    │
              │  │  交易参数)   │
              │  └──────┬───────┘
              │         │
              └─────────┘ (循环每个品种)
                        │
              ┌─────────▼─────────┐
              │ P6: 汇总输出      │
              │ 4铁律核验→JSON→HTML│
              └─────────┬─────────┘
                        │
              ┌─────────▼─────────┐
              │ P6a: CTP信号输出  │
              │ 交易参数→CTP指令  │
              │ (风控明审核通过后) │
              └─────────┬─────────┘
                        │
              ┌─────────▼─────────┐
              │ 归档               │
              │ pg.execution_followup│
              └───────────────────┘
```

> **阶段变更说明**:
> - **P1 重构**: 从"通道突破扫描"升级为"可插拔多策略并行扫描"，支持 trend_following(10子信号)、mean_reversion(3子信号) 及自定义策略插件
> - **P1.5 废弃**: 链证源不再作为独立串行阶段，改为 P3 按需并行数据源之一
> - **P2 增强**: 闫判官新增"调度决策"能力，决定 P3 需要哪些数据源
> - **P3 重构**: 改为"按需并行数据源"，由闫判官调度链证源/观澜/探源并行执行
> - **P5**: 裁决链为两步串行：闫判官（含交易参数）→ 风控明

### 2.2 阶段详细规格（按需并行数据源 v8.3.0+）

| 阶段 | 名称 | 执行者 | 输入 | 输出 | 超时 | 降级 |
|:-----|:-----|:-------|:-----|:-----|:-----|:-----|
| P0 | 自进化前置 | 系统 | `pg.execution_followup` | `pg.calibration` + `pg.agent_profiles` 更新 | 60s/步 | 跳过该步 |
| P1 | 数技源信号扫描 | 数技源 | 品种列表 | `pg.scan_signals` + **P1 阶段报告 `scan_report_path`** | 600s | 提前终止 |
| P2 | 闫判官调度决策 | 闫判官（**调度权**） | P1 信号 | `pg.judge_direction`（选品种+定方向+**调度哪些源**） | 420s | D06 降级 |
| P3 | **按需并行数据源** | 链证源+观澜+探源（闫判官按需调度） | P2 调度指令 | `pg.chain_analysis` + `pg.technical_scores` + `pg.fundamental_scores` + **P3 阶段报告 `research_report_path`** | **max(被调度的源)** | 单源失败不影响其他源 |
| P3a | 链证源产业链（按需） | 链证源 | 品种+产业链 | `pg.chain_analysis` | 300s | 跳过链分析 |
| P3b | 观澜技术面（按需） | 观澜 | 品种+方向 | `pg.technical_scores` | 420s | 跳过技术面 |
| P3c | 探源基本面（按需） | 探源 | 品种+方向 | `pg.fundamental_scores` | 420s | 跳过基本面 |
| P4 步1 | 多头立论 v1 | 多头分析员 | P3 合并分析结果 | `state.bullish_arguments`（round=1, v1） | 420s | D06 降级 |
| P4 步2 | 空头立论 v1 | 空头分析员 | P3 合并分析结果 | `state.bearish_arguments`（round=2, v1） | 420s | D06 降级 |
| P4 步3 | 空头反驳多头 | 空头分析员 | 多头立论 + P3 合并分析 | `state.bearish_rebuttal_arguments`（round=3, rebuttal_v1） | 420s | D06 降级 |
| P4 步4 | 多头反驳空头 | 多头分析员 | 空头立论+空头反驳 + P3 | `state.bullish_rebuttal_arguments`（round=4, rebuttal_v1） | 420s | D06 降级 |
| P4 步5 | 空头最终陈述 | 空头分析员 | 整合空头所有论据 | `state.bear_final_arguments`（round=5, final） | 420s | D06 降级 |
| P4 步6 | 多头最终陈述 | 多头分析员 | 整合多头所有论据 | `state.bull_final_arguments`（round=6, final） | 420s | D06 降级 |
| P5 | 裁决链 | 闫判官(含交易参数)→风控明 | P4 辩论论据 | `pg.debate_verdicts`(含交易参数) + `pg.risk_checks` + **P5 阶段报告 `verdict_report_path`** | 420s/Agent | D06 降级 |
| P6 | 汇总输出 | 明鉴秋 | 全部产出 | HTML辩论报告 `report_path` + `pg.debate_index` | 120s | 拒绝生成报告 |
| P6a | CTP信号输出 | 明鉴秋 | P6 汇总 + 风控明审核 | CTP交易指令 (`pg.ctp_signals`) + **P6a 阶段报告 `signal_report_path`** | 60s | 跳过信号输出 |

> **v9.6.5 变更 — LangGraph 迁移全部完成 (G93-G96)**:
> - **G93**: `coordinator.py` 已删除，Profile 切换逻辑由 `graph.py` 的 `build_debate_graph_with_profile()` 替代
> - **G94**: `debate_protocol_v2.py` 已删除，辩论协议常量（ATTACK_DIMENSIONS/EVIDENCE_WEIGHT_FACTORS/DEBATE_DIVERGENCE_THRESHOLDS）内联到 `nodes.py`
> - **G95**: `agent_runner.py` 已删除，`run_agent()` 由 `agents.py` 的 `DebateAgentExecutor.run_single()` 替代
> - **G96**: `deploy.py` 的 `migrate_json_to_pg()` 已实现 INSERT 写入逻辑（DebateVerdicts/ExecutionFollowup/AgentProfiles）
>
> **阶段变更说明 (v8.3.0)**:
> - **P1-P2-P3 重构**: 从「数技源串行 → P1.5 链证源 → P2 闫判官 → P3 研究」改为「P1 数技源 → P2 闫判官**调度决策** → P3 **按需并行**触发被调度的源」
> - **调度权**: 闫判官在 P2 阶段不仅选品种定方向，还决定需要哪些数据源（如趋势信号侧重观澜、周期品种侧重链证源）
> - **P1.5 废弃**: 链证源不再作为 P1 后的固定串行步骤，而是作为 P3 的按需并行源之一
> - **数据存储**: 所有中间产出从文件系统迁移到 PostgreSQL (OLTP 层)
> - **并行粒度**: 被调度的源在 LangGraph 中通过 `ParallelMap` 并发执行，超时取 max 而非 sum
>
> **v8.9.0 变更**:
> - **P4 重构**: 从「证真+慎思并行一次调用」改为「串行三步骤交叉质询」：bullish_v1（多头立论）→ bearish_v1（空头质疑）→ rebuttal_v2（多头反驳，max=1）
> - **Redux**: 引入 `Annotated[list, operator.add]` reducer 自动追加多轮辩论产物，不覆盖
> - **路由**: 新增 `debate_round` 计数器 + `MAX_DEBATE_ROUNDS` 常量精确控制轮次

### 2.2a 运行模式

FDT 支持两种执行模式：

1. **全量分析模式**（默认）：现有六阶段流水线不变 — P1 信号扫描 → P2 闫判官调度决策 → P3 按需并行数据源 → P4 六阶段攻防辩论 → P5 裁决链 → P6 汇总输出。从品种列表全量扫描开始，逐级传递。

2. **指定品种辩论模式**：当设置 `FDT_DIRECT_DEBATE=true` 和 `FDT_DEBATE_SYMBOLS=SF,SM,SC` 时，跳过 P1 扫描阶段。系统从 `fdt_cache/` 本地 SQLite 缓存直接加载指定品种的 K 线数据、基本面数据和基差数据，进入 P2→P3→P4→P5→P6 流程。适用于快速对已缓存品种启动辩论，无需等待实时扫描信号。

**配置方式**：通过环境变量 `FDT_DIRECT_DEBATE`（启用开关）和 `FDT_DEBATE_SYMBOLS`（品种列表，逗号分隔）控制。缓存目录由 `FDT_CACHE_DIR` 指定（默认 `FDT_ROOT/memory/`）。详见 [03-configuration.md](03-configuration.md)。

> **调度权边界（2026-07-14 澄清，见 G18）**：辩论调度权（决定辩论品种/产业链/方向、dispatch 哪些分析师）属于**闫判官**；链证源/观澜/探源只做各自分析、**无调度权**；明鉴秋负责按闫判官指令执行 spawn 与资源/生命周期管控。该边界已在 `docs/execution_modes_flowchart.md` v4.1 与 `docs/business_flow.md` 固化。

### 2.3 Agent 生成与销毁

FDT 的 Agent 不是常驻进程，而是按需 spawn 的 LLM 子任务。生命周期如下：

```
明鉴秋 (常驻)
    │
    ├─ build_spawn_file_instruction(output_path, agent_name)
    │   → 生成文件输出指令，追加到 spawn prompt
    │
    ├─ Agent tool spawn (subagent_type: "general-purpose")
    │   │
    │   ├─ Agent 执行任务 (读文件 → 分析 → 写文件)
    │   │
    │   └─ SendMessage(recipient="main", content="产出已写入 {path}")
    │       → 通知完成 (非阻塞)
    │
    ├─ poll_file_ready(filepath, timeout=900)
    │   │
    │   ├─ 每 15s 检查文件是否存在 + size 稳定 ≥5s
    │   │
    │   ├─ 就绪 → 读取 JSON → 传入下一阶段
    │   │
    │   └─ 超时 → D06 降级 (返回 None，基于已有数据裁决)
    │
    └─ Agent 实例销毁 (spawn 完成后自动回收)
```

**关键约束**:
- **D05 铁律**: 辩论 Agent 必须用 `subagent_type: "general-purpose"` spawn（expert 类型 Write 工具不可用）
- **S02 铁律**: Agent 之间禁止 SendMessage，统一由明鉴秋通过文件传递
- **S03 铁律**: Agent 写文件先写 `.tmp`，完成后 rename

### 2.4 报告层数据存储 (v8.8.0+)

明鉴秋负责 P1/P3/P5/P6/P6a 五个阶段报告的调度与输出。报告输出目录由环境变量决定：

| 环境变量 | 作用 | 默认 |
|:---------|:-----|:-----|
| `FDT_REPORT_WORKSPACE` | 用户指定工作空间根目录 | 无 |
| `FDT_DAILY_WORKSPACE` | 每日自动化任务工作空间（D:\FDTWorkspace 之类） | 无 |
| 无环境变量 | 使用系统临时目录 `tempfile.gettempdir()/fdt_reports` | 兜底 |

**目录规则**：所有报告按日期归档至 `{workspace}/{YYYY-MM-DD}/` 子目录。

**阶段报告字段映射**（位于 `DebateState`）：

| 字段 | 阶段 | 文件名模式 | 格式 |
|:-----|:-----|:-----------|:-----|
| `scan_report_path` | P1 信号扫描 | `scan_report_{trace_id}.html` | HTML |
| `research_report_path` | P3 三源研究 | `research_report_{trace_id}.html` | HTML |
| `verdict_report_path` | P5 裁决链 | `verdict_report_{trace_id}.html` | HTML |
| `report_path` | P6 辩论汇总 | `debate_report_{date}.html` | HTML |
| `signal_report_path` | P6a CTP信号 | `signal_report_{trace_id}.html` | HTML |

**降级策略**：
- P1/P3/P5/P6a 报告生成失败时，记录 warning 不中断主流程
- P6 辩论报告失败时，fallback 写入工作空间下的 `debate_report_{trace_id}.html`，保证 `report_path` 永远有效
- 所有 fallback 报告统一使用 `_render_html()` 模板，trace_id 全链路贯穿

## 3. 自进化闭环

### 3.1 自进化状态机

```
                    ┌─────────────────────────┐
                    │  检查 execution_followup │
                    │  有未验证裁决?           │
                    └───────┬─────────┬───────┘
                            │ Yes     │ No
                            ▼         │
                ┌───────────────────┐ │
                │ validate_verdicts │ │
                │ (拉T+1 K线验证)   │ │
                └───────┬───────────┘ │
                        │             │
                ┌───────▼───────────┐ │
                │ 已验证 ≥ 5 条?    │ │
                └───┬───────────┬───┘ │
                    │ Yes       │ No  │
                    ▼           │     │
            ┌───────────────┐   │     │
            │ calibrate_   │   │     │
            │ weights.py   │   │     │
            └───────┬───────┘   │     │
                    │           │     │
            ┌───────▼───────────┐     │
            │ total_samples ≥5? │     │
            └───┬───────────┬───┘     │
                │ Yes       │ No      │
                ▼           │         │
        ┌───────────────┐   │         │
        │ evolve_agents│   │         │
        │ .py (7Agent) │   │         │
        └───────┬───────┘   │         │
                │           │         │
        ┌───────▼───────────┐         │
        │ 新样本 ≥ 50 条?   │         │
        └───┬───────────┬───┘         │
            │ Yes       │ No          │
            ▼           │             │
    ┌───────────────┐   │             │
    │ ML Training   │   │             │
    │ Orchestrator  │   │             │
    └───────┬───────┘   │             │
            │           │             │
            └───────────┴─────────────┘
                        │
            ┌───────────▼───────────┐
            │ 加载最新 calibration  │
            │ + agent_profiles      │
            │ → 注入当前会话        │
            └───────────────────────┘
```

### 3.2 自进化脚本矩阵

| 脚本 | 触发条件 | 输入 | 输出 | CLI |
|:-----|:---------|:-----|:-----|:----|
| `validate_verdicts.py` | 有未验证裁决 + K线已更新 | execution_followup.json | validation_stats.json | `--t1` `--t3` `--cost-bps` |
| `validate_llm_output.py` | 每轮辩论结束后自动运行 | scan_results.json + verdict.json | llm_hallucination_stats.json | `--scan` `--verdict` `--history` `--threshold` |
| `calibrate_weights.py` | 已验证 ≥5 条 | validation_stats.json + llm_hallucination_stats.json | calibration.json | `--min-samples` `--lr` `--hallucination-stats` |
| `evolve_agents.py` | total_samples ≥5 | calibration.json + agent_profiles.json + llm_hallucination_stats.json | agent_profiles.json (更新) | `--hallucination-patterns` |
| `record_verdicts.py` | 每轮辩论结束 | debate_results.json | execution_followup.json | `--input` |
| `ml/trainer.py` | 新样本 ≥50 | debate_journal.json | models/*.txt (LightGBM) | `run_daily_check()` |
| `update_matrix.py` | 每次裁决后 | execution_followup.json | instrument_strategy_matrix.json | `--symbol` `--family` `--correct` |

## 4. 调度器 (Scheduler)

### 4.1 心跳循环

```python
# scheduler/engine.py — 核心循环 (简化)
while self._running:
    triggered = self.check_and_run()  # 检查所有触发器
    save_heartbeat()                   # 保存状态到 schedule_state.json
    time.sleep(self.heartbeat_interval)  # 60s
```

### 4.2 触发器类型

| 类型 | 类名 | 触发条件 | 示例 |
|:-----|:-----|:---------|:-----|
| 时间触发 | `TimeTrigger` | 按时间/星期 | auto_publish 每日 23:05 |
| 数据触发 | `DataTrigger` | 按数据量 | ml_training_check ≥50 样本 |
| 事件触发 | `EventTrigger` | 按文件信号 | debate_trigger.json 存在 |
| 辩论计数触发 | `DebateRecordTrigger` | 按辩论轮次 | d3_auto_light ≥5 轮 |

### 4.3 默认触发配置

| 任务名 | 触发器 | 触发条件 | 执行内容 |
|:-------|:-------|:---------|:---------|
| `daily_debate` | EventTrigger | debate_trigger.json 存在 | 4步管道 (scan→summary→report→copy) |
| `auto_publish` | TimeTrigger | 每日 23:05 | 版本号自增 + Git 推送 |
| `update_dominant_mapping` | TimeTrigger | 工作日 15:30 | 主力合约映射更新 |
| `validate_and_evolve` | EventTrigger | 有未验证记录 | validate→calibrate→evolve→ML |
| `ml_training_check` | DataTrigger | ≥50 条新样本 + 3天冷却 | ML 模型训练 |
| `self_optimize_analysis` | TimeTrigger | 每日 02:00 | SkillAdaptor 归因分析 |
| `self_optimize_evolve` | TimeTrigger | 每日 03:00 | Skillevolver 技能层进化 |
| `self_optimize_verify` | TimeTrigger | 每日 04:00 | Autoresearch A/B 验证 |


## 5. 全自动流水线 (Pipeline Runner)

### 5.1 六步管道

`pipeline/runner.py` 实现了无人值守的全自动管道：

| 步骤 | 函数 | 脚本 | 失败策略 |
|:-----|:-----|:-----|:---------|
| 1/6 | `step_scan()` | `scan_all.py`(channel_breakout) | 文件缺失则告警继续 |
| 2/6 | `step_chain_analysis()` | `analyze_chain.py` | 跳过链分析 |
| 3/6 | `step_debate_brief()` | `debate_brief.py` | 跳过品种精选 |
| 4/6 | `step_assemble_intermediate()` | `assemble_intermediate_data.py` | 跳过数据适配 |
| 5/6 | `step_generate_report()` | `phase3_generate_report.py` | 标记报告未生成 |
| 6/6 | `step_record_history()` | `debate/history.py` + `record_verdicts.py` + `ml/trainer.py` | 各子步骤独立容错 |



### 5.3 基差数据来源 (v8.8.9+)

P1 扫描阶段的基差数据通过 `_collect_basis_data_sync()` 获取，数据来源优先级：

1. **100ppi.com/sf/ 现期表**（主源）— 生意社公开页面，覆盖 ~50 个期货品种的现货价
2. **TDX 近月合约代理**（降级，v8.8.9 新增）— 当 100ppi 不可用时（HW_CHECK 反爬/超时/页面变更），自动降级使用 TdxCollector 的近月合约价格作为现货价格代理
3. **无数据** — 以上均不可用时返回空字典，验证器退化为纯 ATR%/K线重校验判断

**近月代理标注**：返回数据的 `unit` 字段为 `"元/吨(近月代理)"`，`data_source` 为 `"near_month_proxy"`。消费方应据此区分真实基差与代理基差。

### 5.2 容错原则

- **每步失败不阻断后续**: `check=False` 传递给 `run_cmd()`
- **超时保护**: 每步 600s 超时
- **日志双写**: 控制台 + 文件 (`pipeline_{date}.log`)
- **UTF-8 强制**: `PYTHONIOENCODING=utf-8` 环境变量注入

### 5.3 代码位置

| 组件 | 文件 | 关键函数 |
|:-----|:-----|:---------|
| 管道主流程 | `pipeline/runner.py` | `main()` L383 |
| 命令执行器 | `pipeline/runner.py` | `run_cmd()` L77 |
| 日志配置 | `pipeline/runner.py` | L22-30 (logging.basicConfig) |
| ML 训练检查 | `pipeline/runner.py` | `step_record_history()` L271 |


## 6. Loop Engineering：循环生命周期

### 6.1 双层循环架构

FDT 的生命周期管理从单次运行（Inner Loop）扩展到跨会话的持续进化（Outer Loop）：

```
┌─────────────────────────────────────────────────────────────┐
│  Outer Loop（外循环）— 跨会话的 Harness 进化                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  触发: 有未验证裁决 / 累计样本达标                      │  │
│  │  执行: validate → calibrate → evolve → ML train        │  │
│  │  产出: calibration.json + agent_profiles.json + 模型    │  │
│  │  注入: 下一轮辩论加载最新配置                           │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Inner Loop（内循环）— 单次辩论的六阶段攻防                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  P1扫描 → P2调度 → P3并行研究 → P4六阶段攻防            │  │
│  │  → P5裁决链 → P6输出                                   │  │
│  │  含 D06 降级、Maker-Checker 分离、分歧度控制            │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Loop Contract 六维度契约

每个自动化循环必须在 `docs/harness/loop-contracts/` 下有对应的 `.contract.yaml` 文件，定义六维度：

| 维度 | 键 | 说明 | FDT 实现 |
|------|-----|------|----------|
| **触发条件** | `trigger` | 何时启动 | cron / API / 手动 / 事件 |
| **作用范围** | `scope` | 能碰什么、不能碰什么 | allow/deny 路径清单 |
| **具体行为** | `action` | pipeline 步骤 | 预循环 → 主管道 → 后循环 |
| **预算红线** | `budget` | 资源上限 | 时间/Token/成本/重试/品种数 |
| **停止条件** | `stop` | 正常完成 + 安全网 | 完成条件 + 熔断条件 |
| **上报通道** | `report` | 正常输出 + 异常通知 | HTML报告 + PG归档 + 日志 |

详细规范见 [loop-contracts/README.md](loop-contracts/README.md)。

### 6.3 验证档位与权限匹配

| 验证档位 | 权限档位 | FDT 循环示例 | 晋级门槛 |
|----------|----------|-------------|----------|
| L1 (self) | 只读 (RO) | 数据采集、健康自检 | — |
| L2 (test_suite) | 草稿 (Draft) | 自进化闭环、ML 训练 | 影子模式 ≥5 轮，准确率 ≥90% |
| L3 (independent_agent) | 外部写入 (Write) | 每日自动辩论（含 CTP 输出） | 连续 ≥20 次零回退，漏放率 ≈0 |

### 6.4 多循环协作

FDT 多个循环之间通过 handoff 消息协作，不共享状态：

```
[数据采集循环] ──handoff──→ [每日辩论循环] ──handoff──→ [自进化循环]
       │                         │                          │
       ▼                         ▼                          ▼
  state/data-collect/     state/daily-debate/       state/self-evolve/
```

**铁律**：状态跟循环走。每循环自有独立 state 目录，仅本循环读写；协作不靠共享状态，靠 handoff 消息。
