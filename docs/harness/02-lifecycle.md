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
bootstrap.py main()
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
| 入口函数 | `bootstrap.py` | `main()` L65 |
| 记忆加载 | `bootstrap.py` | `load_memory()` L22 |
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
              │  │ P4: 辩论     │ ← 并行
              │  │ 证真 + 慎思  │
              │  └──────┬───────┘
              │         │
              │  ┌──────▼───────┐
              │  │ P5: 裁决链   │ ← 串行
              │  │ 闫判官→策执远 │
              │  │ →风控明      │
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
              │ 归档               │
              │ pg.execution_followup│
              └───────────────────┘
```

> **阶段变更说明**:
> - **P1 重构**: 从"通道突破扫描"升级为"可插拔多策略并行扫描"，支持 trend_following(10子信号)、mean_reversion(3子信号) 及自定义策略插件
> - **P1.5 废弃**: 链证源不再作为独立串行阶段，改为 P3 按需并行数据源之一
> - **P2 增强**: 闫判官新增"调度决策"能力，决定 P3 需要哪些数据源
> - **P3 重构**: 改为"按需并行数据源"，由闫判官调度链证源/观澜/探源并行执行
> - **P5 拆分**: 裁决链拆分为 verdict → trading_plan → risk_check 三步骤

### 2.2 阶段详细规格（按需并行数据源 v8.3.0+）

| 阶段 | 名称 | 执行者 | 输入 | 输出 | 超时 | 降级 |
|:-----|:-----|:-------|:-----|:-----|:-----|:-----|
| P0 | 自进化前置 | 系统 | `pg.execution_followup` | `pg.calibration` + `pg.agent_profiles` 更新 | 60s/步 | 跳过该步 |
| P1 | 数技源信号扫描 | 数技源 | 品种列表 | `pg.scan_signals` | 600s | 提前终止 |
| P2 | 闫判官调度决策 | 闫判官（**调度权**） | P1 信号 | `pg.judge_direction`（选品种+定方向+**调度哪些源**） | 420s | D06 降级 |
| P3 | **按需并行数据源** | 链证源+观澜+探源（闫判官按需调度） | P2 调度指令 | `pg.chain_analysis` + `pg.technical_scores` + `pg.fundamental_scores` | **max(被调度的源)** | 单源失败不影响其他源 |
| P3a | 链证源产业链（按需） | 链证源 | 品种+产业链 | `pg.chain_analysis` | 300s | 跳过链分析 |
| P3b | 观澜技术面（按需） | 观澜 | 品种+方向 | `pg.technical_scores` | 420s | 跳过技术面 |
| P3c | 探源基本面（按需） | 探源 | 品种+方向 | `pg.fundamental_scores` | 420s | 跳过基本面 |
| P4 | 多空辩论 | 证真+慎思 | P3 合并分析结果 | `pg.debate_arguments` | 420s/Agent | D06 降级 |
| P5 | 裁决链 | 闫判官→策执远→风控明 | P4 辩论论据 | `pg.debate_verdicts` + `pg.trading_plans` + `pg.risk_checks` | 420s/Agent | D06 降级 |
| P6 | 汇总输出 | 明鉴秋 | 全部产出 | HTML报告 + `pg.debate_index` | 120s | 拒绝生成报告 |

> **阶段变更说明 (v8.3.0)**:
> - **P1-P2-P3 重构**: 从「数技源串行 → P1.5 链证源 → P2 闫判官 → P3 研究」改为「P1 数技源 → P2 闫判官**调度决策** → P3 **按需并行**触发被调度的源」
> - **调度权**: 闫判官在 P2 阶段不仅选品种定方向，还决定需要哪些数据源（如趋势信号侧重观澜、周期品种侧重链证源）
> - **P1.5 废弃**: 链证源不再作为 P1 后的固定串行步骤，而是作为 P3 的按需并行源之一
> - **数据存储**: 所有中间产出从文件系统迁移到 PostgreSQL (OLTP 层)
> - **并行粒度**: 被调度的源在 LangGraph 中通过 `ParallelMap` 并发执行，超时取 max 而非 sum

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
| `calibrate_weights.py` | 已验证 ≥5 条 | validation_stats.json | calibration.json | `--min-samples` `--lr` |
| `evolve_agents.py` | total_samples ≥5 | calibration.json + agent_profiles.json | agent_profiles.json (更新) | 无参数 |
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
| `cluster_failures` | TimeTrigger | 每周一 08:00 | 失败模式聚类 |
| `apm_scorecard` | TimeTrigger | 每周一 08:30 | APM-CS 五轴评分 |
| `vibench_baseline` | DataTrigger | ≥30 案例 | ViBench 基准回放 |
| `d3_auto_light` | DebateRecordTrigger | 辩论 ≥5 轮 | D3 镇定度自动点亮 |
| `discipline_enforce` | TimeTrigger | 每周一 08:45 | D4 纪律钳制 |

## 5. 全自动流水线 (Pipeline Runner)

### 5.1 六步管道

`pipeline/runner.py` 实现了无人值守的全自动管道：

| 步骤 | 函数 | 脚本 | 失败策略 |
|:-----|:-----|:-----|:---------|
| 1/6 | `step_scan()` | `scan_all.py`(channel_breakout) + `run_l1l4_scan.py` + `run_factor_timing_scan.py` | 三文件缺失则告警继续 |
| 2/6 | `step_chain_analysis()` | `analyze_chain.py` | 跳过链分析 |
| 3/6 | `step_debate_brief()` | `debate_brief.py` | 跳过品种精选 |
| 4/6 | `step_assemble_intermediate()` | `assemble_intermediate_data.py` | 跳过数据适配 |
| 5/6 | `step_generate_report()` | `phase3_generate_report.py` | 标记报告未生成 |
| 6/6 | `step_record_history()` | `debate/history.py` + `record_verdicts.py` + `ml/trainer.py` | 各子步骤独立容错 |

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
