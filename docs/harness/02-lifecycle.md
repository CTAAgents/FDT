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
| `self_optimize_analysis` | TimeTrigger | 每日 02:00 | SkillAdaptor 归因分析 |
| `self_optimize_evolve` | TimeTrigger | 每日 03:00 | Skillevolver 技能层进化 |
| `self_optimize_verify` | TimeTrigger | 每日 04:00 | Autoresearch A/B 验证 |

## 4a. L2 因子演化循环 (Loop Engineering, v8.9.3+)

L2 演化循环独立于 P1-P6 主流水线，作为 FDT 的「因子自动发现与进化」子系统，每晚 20:00 由 scheduler 触发。

### 4a.1 Karpathy 五步法落地

| 步骤 | 实现 | 文件 |
|:-----|:-----|:-----|
| 1. program.md | 因子程序模板（name + code + 经济逻辑 + dependencies + verifiers） | `loop_engine/factor_program.py` |
| 2. 锁定验证器 | Verifier 协议锁定后不可修改，任何修改尝试抛 RuntimeError | `loop_engine/verifier_protocol.py` |
| 3. 启动循环 | L2 主循环逐代演化（变异 → 评估 → 筛选 → 繁殖） | `loop_engine/evolution_loop.py` |
| 4. 状态文件 | `evolution_state.json` + `evolution_state.backup`（先写主文件再镜像） | `loop_engine/state.py` |
| 5. 停止条件 | 四重熔断：Token>2x / 连续 3 代 IC<0.01 / 失败率>90% / 状态 24h 未更新 | `loop_engine/evolution_loop.py` |

### 4a.2 三层评估链（agentic-factor-investing）

```
Level 1: 回测验证
   │  IC > 0.03 / 夏普 > 1.5 / 回撤 < 30%
   ▼
Level 2: 经济逻辑
   │  四维（可解释性/市场结构/数据质量/统计鲁棒性）≥ 3/4 通过
   ▼
Level 3: 多重检验
   │  Bonferroni 校正 + FDR 控制（防 p-hacking）
   ▼
入精英库（elite_archive）
```

### 4a.3 三层分离原则（factorengine）

| 分离维度 | 实现 |
|:---------|:-----|
| 逻辑分离 | LLM 修改因子代码逻辑（变异），不接触回测/评估代码 |
| 资源分离 | API 调用（LLM）与 CPU 计算（回测）使用不同执行器 |
| 时间分离 | 慢决策（夜间演化）与快迭代（日间扫描）解耦 |

### 4a.4 经验链与种子因子

- **经验链**：成功/失败轨迹按 `trace_id` 存储，LLM 每次变异必须读取最近 20 条避免重复踩坑
- **种子因子**：12 个来自现有 `trend_following`（10 子信号）+ `mean_reversion`（3 子信号）+ 多因子策略的因子
- **精英库**：通过三级评估链的因子入 `memory/knowledge/factors/elite/`，可供 FDT 主流水线消费

### 4a.5 调度集成

| 任务 | 触发器 | 触发条件 | 执行内容 |
|:-----|:-------|:---------|:---------|
| `l2_evolution_loop` | TimeTrigger | 每晚 20:00 | `python -m loop_engine.evolution_loop --once`（4h timeout） |

**环境变量配置**：
- `FDT_L2_MAX_GENERATION`：最大演化代数（默认 50）
- `FDT_L2_MEMORY_DIR`：演化状态存储目录（默认 `memory/evolution`）
- `FDT_L2_ELITE_DIR`：精英因子库目录（默认 `memory/knowledge/factors/elite`）

### 4a.6 安全沙箱

因子代码在受限沙箱中执行：
- `_safe_import` 白名单：仅允许 `numpy`/`pandas`/`scipy`/`statsmodels`/`talib`/`math`/`statistics`
- `FORBIDDEN_MODULES`：禁止 `os`/`sys`/`subprocess`/`socket` 等系统级模块
- `builtins` 白名单：仅暴露 `len`/`range`/`min`/`max`/`sum`/`abs`/`hasattr`/`callable` 等纯函数
- 因子 ID 使用 `secrets.token_hex(8)` 确保全局唯一性

## 4b. L1 Meta-Loop (Loop Engineering Phase 2, v8.10.0+)

L1 Meta-Loop 独立于 P1-P6 主流水线和 L2 演化循环，作为 FDT 的「因子知识补给」子系统，每日 05:00 由 scheduler 触发，承担"感知市场 → 识别辩论缺口 → Bootstrapping 候选因子 → L1 Verifier 判定 → 注入 factor_pool"的五步流程。

### 4b.1 五步流程落地

| 步骤 | 实现 | 文件 |
|:-----|:-----|:-----|
| 1. 感知 | f10/web_collector (fetch_quote/fetch_kline/search_news/collect_fundamental_web) | `loop_engine/meta_loop.py:MetaLoop._perceive_market()` |
| 2. 质量分析 | DebateQualityAnalyzer 识别 4 种缺口 (bullish_weak/bearish_weak/insufficient_rounds/no_debate) | `loop_engine/meta_loop.py:DebateQualityAnalyzer` |
| 3. Bootstrapping | 3 个内置模板 + LLM 注入接口 | `loop_engine/meta_loop.py:BootstrappingChain` |
| 4. L1 Verifier 判定 | 4 维度锁定判定 (economic_logic/is_executable/not_duplicate/narrative_length) | `loop_engine/meta_loop.py:L1Verifier` |
| 5. 注入 factor_pool | FactorPoolManager.add_or_update() + seed_pool.inject_from_l1() | `loop_engine/meta_loop.py:FactorPoolManager` + `loop_engine/seed_pool.py` |

### 4b.2 L1 Verifier 锁定协议

```python
# 4 维度判定（配置不可运行时修改）
class L1Verifier:
    def __init__(self, config: L1VerifierConfig):
        self._locked = True
        self._config = config  # 锁定后不可修改

    def check(self, candidate: SeedCandidate) -> tuple[bool, list[str]]:
        if not self._locked:
            raise RuntimeError("L1 Verifier 未锁定")
        # 严格按配置判定，不接受任何 override
        # 维度1: economic_logic >= min_economic_score (默认 2/4)
        # 维度2: is_executable (factor_program 安全沙箱编译通过)
        # 维度3: not_duplicate (factor_id 不与 factor_pool 重复)
        # 维度4: narrative_length >= min_narrative_length (默认 20 字符)
```

### 4b.3 L1 熔断机制

| 熔断条件 | 阈值 | 行为 |
|:---------|:-----|:-----|
| Token 超额 | tokens_consumed > 2.0 × daily_token_limit (100,000) | status = circuit_broken |
| 失败率 | total_failed / total_candidates > 0.95 | status = circuit_broken |
| 连续低质量 | consecutive_low_quality > 5 | status = circuit_broken |

### 4b.4 调度集成

| 任务 | 触发器 | 触发条件 | 执行内容 |
|:-----|:-------|:---------|:---------|
| `l1_meta_loop` | TimeTrigger | 每日 05:00 | `python -m loop_engine.meta_loop --once`（1h timeout） |

**环境变量配置**：
- `FDT_L1_MAX_BOOTSTRAPS`：单次运行最大 bootstrapping 候选数（默认 5）
- `FDT_L1_MEMORY_DIR`：L1 状态存储目录（默认 `memory/meta_loop`）
- `FDT_L1_FACTOR_POOL`：factor_pool.json 路径（默认 `memory/meta_loop/factor_pool.json`）
- `FDT_L1_INJECT_DIR`：L2 种子注入目录（默认 `memory/evolution`）

### 4b.5 与 L2 的衔接

- L1 产出 `SeedCandidate` → 通过 `seed_pool.inject_from_l1()` 注入 L2 种子池
- L2 演化时优先消费 L1 注入的 pending 候选（标记 `injected_to_l2=True`）
- L1 通过 `debate_round` 质量反馈识别 L2 演化失败模式（形成 L1↔L2 闭环）

### 4b.6 测试覆盖

- `tests/loop_engine/test_meta_loop.py`：51 个测试用例（8 个测试类）全部通过
- 全量 loop_engine 测试：147 用例（96 L2 + 51 L1）全绿

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
