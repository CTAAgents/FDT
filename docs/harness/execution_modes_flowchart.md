# FDT 执行模式流程图

> v4.6 | 2026-07-22 | 数技源信号生产 + 闫判官判断调度(链证源/观澜/探源/读心) + 多空头辩论 + 资源管控 + 生命周期 → 8种执行模式 + LangGraph 图编排模式 | 闫判官(含交易参数)，新增 signal_output(CTP)

---

## 明鉴秋全景控制模型

```
┌──────────────────────────────────────────────────────────────┐
│                     明鉴秋（团队主管）                        │
│  流程调度 | 资源管控 | 生命周期 | 数据中转 | 汇总输出        │
└──────────────────────────────────────────────────────────────┘
         │
         ├── 启动时 ──── resource 检测硬件
         │                 CPU/内存/磁盘/Python进程
         │                 risk=red → 停止，等资源释放
         │
         ├── 每批spawn前 ── pre-spawn-check 获取并发建议
         │                   green → 正常并发
         │                   yellow → 降并发到 safe_concurrent
         │                   red → 停止 spawn
         │
         ├── 每批spawn后 ── agent-lifecycle register 注册
         │                   等待产出就绪
         │                   wait-and-shutdown 生成shutdown计划
         │                   SendMessage(shutdown_request)
         │                   确认 active_count=0
         │
         └── 汇总输出 ── finalize → report → present_files
                          记忆归档 → 知识萃取
```

> **调度权归属**：**闫判官**拥有辩论调度权（决定辩论哪些品种/产业链/方向，并 dispatch 哪些分析师）。明鉴秋负责**执行** spawn（按闫判官指令）与资源/生命周期管控。链证源/观澜/探源只做各自分析、**无调度权**。

### 辩论流程

```
数技源出信号 → [过滤?] → 闫判官判断调度 → 三分析师供弹 → 多头/空头辩论 → 闫判官终裁(含交易参数) → 一致性 → 风控明审核 → 报告 → signal_output(CTP)
                            ↑                ↑                ↑         ↑                   ↑         ↑         ↑         ↑
                      ┌─────┴────────────────┴────────────────┴─────────┴───────────────────┴─────────┴─────────┴─────────┘
                      │ 闫判官拥有调度权；链证源/观澜/探源只做各自分析、无调度权
                      │ 每批 spawn 前查资源，完成后 shutdown 释放（明鉴秋管控）
                      └────────────────────────────────────────────────────────────────────────────────────────────────
```

**四分析师（由闫判官判断调度）**

| 分析师 | 身份 | 职责 | 调度权 |
|:------|:-----|:-----|:------|
| 链证源 | 产业链分析师 | 做产业链事实描述 + 景气度分析（不下多空结论） | ❌ 无 |
| 观澜 | 技术面研究员 | 技术面分析供弹 | ❌ 无 |
| 探源 | 基本面研究员 | 基本面分析供弹 | ❌ 无 |
| 读心 | 新闻情绪分析师 | 新闻情绪分析供弹（金十MCP + 网页爬虫） | ❌ 无 |

> **四者为平级分析师**，仅分析方向不同（产业链 / 技术面 / 基本面 / 新闻情绪），**彼此之间不存在调度与被调度关系**；调度权统一在闫判官，由明鉴秋执行 spawn。

---

## 资源管理与生命周期

### 三件套工具

| 工具 | 命令 | 调用时机 |
|:-----|:-----|:--------|
| 资源看门狗 | `fdt_cli.py resource` | pipeline 启动时、每批 spawn 前自动检测 CPU/内存/磁盘/Python进程 |
| 并发建议 | `fdt_cli.py pre-spawn-check --phase phaseN --base N` | 每批 spawn 前获取建议并发数+操作指引 |
| 生命周期 | `fdt_cli.py agent-lifecycle` | spawn 后注册 → 等待 → shutdown |

### 资源阈值策略

| 指标 | 绿色(green) | 黄色(yellow) | 红色(red) |
|:-----|:----------:|:-----------:|:--------:|
| CPU | < 50% | 50-80% → 系数0.5 | > 80% → 系数1/N |
| 内存 | < 60% | 60-80% → 系数0.7 | > 80% → 系数0.5 |
| 磁盘 | < 90% | — | > 90% → 告警 |
| Python进程 | ≤ 10 | 10-15 → 系数0.75 | > 15 → 系数0.5 |
| 活跃 Agent | < 8 | — | ≥ 8 → **暂停 spawn** |

综合并发 = `base × min(CPU系数, 内存系数, 进程系数)`，结果 ≥ 1

### 生命周期流程（逐批清退）

每批 Agent spawn 后执行以下流程，确保用完即走、不积压：

```
spawn Agent → register → 等待产出就绪 → wait-and-shutdown → SendMessage(shutdown_request) → 确认回收 → 下一批
                                                                                                ↓
                                                                                   active_count=0 才继续
```

```
# 完整一轮辩论的资源释放时序（闫判官判断调度 → 明鉴秋执行 spawn）
Phase0 闫判官判断调度 → spawn 1 → register → wait → shutdown ✅ 释放1
Phase1 链证源(产业链分析)×N → spawn N → register → wait → shutdown ✅ 释放N
Phase2 观澜(技术面)+探源(基本面)×N → spawn 2N → register → wait → shutdown ✅ 释放2N
Phase3 多头/空头辩论×N → spawn N → register → wait → shutdown ✅ 释放N
Phase4 闫判官终裁 → spawn N → register → wait → shutdown ✅ 释放N
Phase5 一致性×N   → spawn N → register → wait → shutdown ✅ 释放N
Phase6 风控明×N   → spawn N → register → wait → shutdown ✅ 释放N
                                  ↑
                      每批完成后立即清空，不跨批积压
```

### 底层生命周期命令

```bash
# 1) spawn 后注册一批
python scripts/fdt_cli.py agent-lifecycle register \
  --phase phase2 --agents tech_pb,tech_sc \
  --files p3_technical_pb.json,p3_technical_sc.json

# 2) 等待产出就绪，生成 shutdown 计划
python scripts/fdt_cli.py agent-lifecycle wait-and-shutdown --phase phase2

# 3) 明鉴秋逐个发送 shutdown_request（原聊天层）
#    SendMessage(type='shutdown_request', recipient='tech_pb')
#    SendMessage(type='shutdown_request', recipient='tech_sc')

# 4) 确认活跃 Agent 数
python scripts/fdt_cli.py agent-lifecycle active
# → active_count=0 再 spawn 下一批

# 5) 清理状态（辩论全部完成后）
python scripts/fdt_cli.py agent-lifecycle cleanup
```

---

## 8种模式总览

### 模式一: `full` — 全流程

```
数技源信号 → P0-4伪信号过滤 → 闫判官判断调度(链证源+观澜+探源) → 多头/空头辩论 → 闫判官终裁(含交易参数) → 一致性 → 风控明审核 → 报告 → signal_output(CTP)
```
- `scan_all.py`（channel_breakout，数技源）62品种扫描 → `full_scan_summary_{date}.json`
- validator P0-4 伪信号门禁
- 闫判官判断调度：指定产业链 + 品种 + 方向，dispatch 链证源(产业链)/观澜(技术面)/探源(基本面)
- 三分析师供弹 → 多头/空头基于供弹辩论 → 闫判官终裁（读初判指令+链+辩论→裁决）

```bash
python scripts/fdt_cli.py pipeline --mode full --workspace <dir>
```

### 模式二: `no-filter` — 扫描→辩论(不过滤)

同模式一，仅跳过 P0-4 伪信号过滤（`--disable-filter` 保留伪突破信号）。

```bash
python scripts/fdt_cli.py pipeline --mode no-filter --workspace <dir>
```

### 模式三: `scan-only` — 仅信号计算

```
数技源信号 → 结束输出（不过滤不辩论）
```

```bash
python scripts/fdt_cli.py pipeline --mode scan-only --workspace <dir>
```

### 模式四: `scan-filter` — 信号计算+过滤

```
数技源信号 → P0-4伪信号过滤 → 结束输出（含拦前/拦后分）
```

```bash
python scripts/fdt_cli.py pipeline --mode scan-filter --workspace <dir>
```

### 模式五: `debate` — 指定品种辩论

```
(跳过扫描) → 闫判官判断调度(链证源+观澜+探源) → 多头/空头辩论 → 闫判官终裁(含交易参数) → 一致性 → 风控明审核 → 报告 → signal_output(CTP)
```
- 闫判官初判（无扫描，虚拟触发）指定品种与方向，dispatch 三分析师

```bash
python scripts/fdt_cli.py pipeline --mode debate --symbols pb,sc,l --workspace <dir>
```

### 模式六: `debate-group` — 指定产业链辩论

```
(跳过扫描) → 品种解析 → 闫判官判断调度(产业链列表) → 三分析师 → 辩论 → 终裁 → 报告 → signal_output(CTP)
```

```bash
python scripts/fdt_cli.py pipeline --mode debate-group --chain 黑色系 --workspace <dir>
```

### 模式七: `debate-all` — 强制全品种辩论

```
(跳过扫描) → 全品种列表 → 闫判官判断调度(全品种) → 三分析师 → 辩论 → 终裁 → 报告 → signal_output(CTP)
```

```bash
python scripts/fdt_cli.py pipeline --mode debate-all --workspace <dir>
```

### 模式八: `finalize-only` — 仅收口

```
(spawn完成后) → 组装(含链数据) → 萃取 → 报告生成 → signal_output(CTP)
```

```bash
python scripts/fdt_cli.py pipeline --mode finalize-only --workspace <dir>
```

---

## 模式速查表

| # | 模式 | 扫描 | 过滤 | 链分析 | 辩论 | 用法 |
|:-:|:-----|:----:|:----:|:------:|:----:|:-----|
| 1 | **full** | ✅ | ✅ | ✅ | ✅ | `pipeline --mode full` |
| 2 | **no-filter** | ✅ | ❌ | ✅ | ✅ | `pipeline --mode no-filter` |
| 3 | **scan-only** | ✅ | ❌ | ❌ | ❌ | `pipeline --mode scan-only` |
| 4 | **scan-filter** | ✅ | ✅ | ❌ | ❌ | `pipeline --mode scan-filter` |
| 5 | **debate** | ❌ | ❌ | ✅ | ✅(指定) | `pipeline --mode debate --symbols A,B` |
| 6 | **debate-group** | ❌ | ❌ | ✅ | ✅(产业链) | `pipeline --mode debate-group --chain 能源` |
| 7 | **debate-all** | ❌ | ❌ | ✅ | ✅(全品) | `pipeline --mode debate-all` |
| 8 | **finalize-only** | ❌ | ❌ | ❌* | ❌(收口) | `pipeline --mode finalize-only` |

> * finalize-only 阶段会读取 `p1_chain_analysis.json`（若 plan 阶段已生成），组装到中间数据中

---

## 模式九: `langgraph` — LangGraph 图编排模式（v8.4.0+）

> 替代传统的 subprocess 文件传递模式，使用 LangGraph StateGraph 进行声明式图编排。
> 通过 `FDT_USE_LANGGRAPH=true` 环境变量控制，支持零风险 A/B 切换。

### LangGraph 模式流程图

```
输入: trace_id + selected_symbols + mode
    │
    ▼
┌───────────────────────────────────────┐
│ build_debate_graph(mode)             │ ← 声明式图定义
│  scan → judge_direction              │
│        → Parallel(chain/tech/fund/sentiment)   ← 四源按需并行
│        → merge_research              │
│        → debate? → verdict           │ ← 条件边路由
│        → verdict(含交易参数) → risk_check   │
│        → report → signal_output(CTP) → END  │
└───────────────────────────────────────┘
    │
    ▼
输出: DebateState (包含所有阶段产出)
    │
    ▼
健康检查 → run_health_check(state)
```

### LangGraph 模式命令

```bash
# 方式1: 环境变量控制 pipeline/runner.py
FDT_USE_LANGGRAPH=true FDT_LANGGRAPH_MODE=default python pipeline/runner.py

# 方式2: 直接调用 run_debate.py langgraph 子命令
python scripts/run_debate.py langgraph --symbols RB,CU --mode default

# 方式3: 使用 fdt_cli.py langgraph 子命令（v8.4.0+）
python scripts/fdt_cli.py langgraph --symbols RB,CU --mode default

# 方式4: HTTP API（fdt_api.py）
python fdt_api.py
curl -X POST http://localhost:8000/api/v1/debate \
  -H "Content-Type: application/json" \
  -d '{"mode": "default", "trace_id": "my-trace"}'
```

### LangGraph 模式对比

| 维度 | subprocess 模式 | LangGraph 模式 |
|------|-----------------|----------------|
| 流程编排 | 文件传递 + subprocess | StateGraph 声明式 |
| 并行执行 | 串行 + spawn Agent | 内置 Parallel 节点 |
| 状态管理 | 分散在 JSON 文件 | 统一 DebateState |
| 调试 | 日志 + 文件 | LangSmith + 状态快照 |
| A/B 切换 | 无 | FDT_USE_LANGGRAPH 环境变量 |
| Checkpointer | 无 | PostgreSQL/SQLite 持久化 |

### LangGraph 模式速查表

| 参数 | 选项 | 说明 |
|:-----|:-----|:-----|
| `FDT_USE_LANGGRAPH` | `true`/`false` | 是否启用 LangGraph 模式（默认 false） |
| `FDT_LANGGRAPH_MODE` | `default`/`fast`/`deep_research`/`tournament` | 执行模式 |
| `FDT_CHECKPOINTER` | `sqlite`/`pg` | Checkpointer 后端（默认 sqlite） |

### LangGraph vs 传统模式对比

| 维度 | 传统模式 | LangGraph 模式 |
|:-----|:---------|:--------------|
| 流程驱动 | subprocess 文件传递 | StateGraph 内存传递 |
| 并行执行 | 串行触发 | 声明式并行 |
| 状态管理 | 文件 + SQLite | DebateState + Checkpointer |
| 错误恢复 | S04 轮询 | 节点级错误捕获 + 状态回溯 |
| A/B 切换 | 无 | `FDT_USE_LANGGRAPH` 环境变量 |
| 监控 | 文件日志 | 节点级计时 + 健康检查 |

---

## 链证源注入说明

### 运行时机

`run_chain_analysis()` 在 `run_debate.py` 的 **plan** 和 **debate** 子命令执行时自动运行：

```
plan 子命令: scan加载 → 链分析(analyze_chain.py --symbols) → build_spawn_plan(注入链数据) → 输出spawn_plan.json
debate 子命令: 解析品种 → 链分析(analyze_chain.py --symbols) → build_spawn_plan(注入链数据) → 输出spawn_plan.json
```

### 链证源职责边界（2026-07-14 澄清）

- **只做产业链分析**：描述产业链事实状态 + 景气度，不给任何具体品种出多空结论。
- **无调度权**：调度权（决定辩论哪些品种/产业链/方向、dispatch 哪些分析师）属于**闫判官**；链证源不决定辩论范围、不 spawn 其他 Agent、不替代闫判官裁决。
- 其产出 `p1_chain_analysis.json` 经 `build_spawn_plan` 注入到下游 Agent prompt，供研究/辩论参考。

### 受影响的 Agent 角色

链证源数据被注入到 spawn plan 中以下 6 个角色的 prompt：

| 角色 | 身份 | 链数据用途 |
|:-----|:-----|:----------|
| **chain** | 链证源(产业链分析师) | 自身产业链分析产出 |
| **technical** | 观澜(技术面研究员) | 分析产业链同品种支撑阻力共振 |
| **fundamental** | 探源(基本面研究员) | 产业链上下游基本面联动（成本/库存/开工传导） |
| **bullish** | 多头分析员 | 引用产业链同向品种作为论据 |
| **bearish** | 空头分析员 | 引用产业链反向品种质疑信号 |
| **judge** | 闫判官(裁决+交易参数) | 产业链一致性/冗余/趋势作为裁决维度；产业链联动性影响止损/目标位设定 |

### 注入效果示例

辩论 Agent 收到的 prompt 中新增了 `【链证源数据】` 段：

```
【链证源数据】所属产业链: 有色 | 链成员: cu, al, zn, pb, ni... | 链趋势: 震荡,
链内一致性: 0% | 期限结构: flat, 基差: 平稳 | 【同链去重注意】与 XX 高度相关
```

---

## 开关与参数对照

| 开关 | 参数 | 作用域 | 默认值 |
|:-----|:-----|:-------|:------|
| 伪信号过滤 | `--disable-filter` (scan_all.py) | 扫描阶段 | 开(过滤) |
| 辩论流程 | `--mode` (pipeline) | 整体流程 | `no-filter`(自动化默认) |
| 链证源分析 | 自动运行，无需参数 | plan/debate阶段 | 自动开 |
| 辩论品种选择 | `--mode {trigger,all,symbols}` (debate plan) | 计划阶段 | `trigger` |
| 指定品种 | `--symbols A,B,C` | pipeline/debate | — |
| 指定产业链 | `--chain 名称` | pipeline/debate | — |
| 资源检查 | `fdt_cli.py resource` | 明鉴秋 spawn 前 | 手动触发 |
| 并发建议 | `fdt_cli.py pre-spawn-check --phase --base` | 明鉴秋 spawn 前 | 手动触发 |
| 生命周期 | `fdt_cli.py agent-lifecycle` | 明鉴秋 spawn 后 | 手动触发 |

---

## 底层命令对照

### full (= 模式一)
```bash
# 0. 资源检查
python scripts/fdt_cli.py resource

# 1. 扫描+过滤
python skills/quant-daily/scripts/scan_all.py --output <dir> --prefix scan

# 2. 辩论计划(含链分析 + 闫判官判断调度)
python scripts/run_debate.py plan --scan <scan.json> --workspace <dir>

# 3. (逐批 spawn Agent，每批 register → wait → shutdown)
#    Phase0 闫判官判断调度 → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase1 链证源×N     → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase2 观澜+探源×N  → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase3 多头/空头×N  → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase4 闫判官终裁(含交易参数) → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase5 一致性×N → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase6 风控明×N → spawn → lifecycle register → wait-and-shutdown → shutdown

# 4. 收口
python scripts/run_debate.py finalize --scan <scan.json> --workspace <dir>
```

### no-filter (= 模式二)
```bash
# 0. 资源检查
python scripts/fdt_cli.py resource

# 1. 扫描(跳过过滤)
python skills/quant-daily/scripts/scan_all.py --output <dir> --prefix scan --disable-filter

# 2-4. 同模式一
```

### debate (= 模式五)
```bash
# 直接辩论(无扫描，自动链分析 + 闫判官判断调度)
python scripts/run_debate.py debate --symbols pb,sc,l --workspace <dir>
```

### debate-all (= 模式七)
```bash
python scripts/run_debate.py debate --all --workspace <dir>
```

### 明鉴秋资源 + 生命周期单独使用
```bash
# 查看系统资源
python scripts/fdt_cli.py resource
python scripts/fdt_cli.py resource --json

# 获取 spawn 并发建议
python scripts/fdt_cli.py pre-spawn-check --phase phase3 --base 6

# Agent 生命周期管理
python scripts/fdt_cli.py agent-lifecycle register --phase phase2 --agents a,b --files x,y
python scripts/fdt_cli.py agent-lifecycle wait-and-shutdown --phase phase2 --timeout 900
python scripts/fdt_cli.py agent-lifecycle active
python scripts/fdt_cli.py agent-lifecycle cleanup
```

---

## 状态转换图

```
                            ┌──────────────────┐
                            │    信号计算       │
                            │ (scan_all 62品种) │
                            └────────┬─────────┘
                                     │
                            ┌────────┴─────────┐
                            │  伪信号过滤?      │
                            └────────┬─────────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  │                  │                  │
         ┌────────┴────────┐  ┌─────┴──────┐  ┌───────┴────────┐
         │ 开启过滤         │  │ 跳过过滤   │  │ 结束(scan-only)│
         │(full/scan-filter)│  │(no-filter) │  └────────────────┘
         └────────┬────────┘  └─────┬──────┘
                  │                  │
                  └──────┬──────────┘
                         │
                 ┌───────┴────────┐
                 │  闫判官判断调度  │
                 │  (决定链+品种+  │
                 │   方向+dispatch)│
                 └───────┬────────┘
                         │
              ┌──────────┴──────────────────┐
              │  四分析师供弹（并行）         │
              │  链证源(产业链)             │
              │  观澜(技术面)              │
              │  探源(基本面)              │
              │  读心(新闻情绪)             │
              └──────────┬──────────────────┘
                         │
                 ┌───────┴────────┐
                 │  多头 + 空头 辩论│
                 └───────┬────────┘
                         │
                 ┌───────┴────────┐
                 │  闫判官 终裁    │
                 │  (读指令+链+辩论 │
                 │   →出裁决)      │
                 └───────┬────────┘
                         │
                 ┌──────────┴───────────────┐
                 │  一致性裁判            │
                 │  → verdict(含交易参数)  │
                 │  → 风控明审核          │
                 │  → 报告                │
                 │  → signal_output(CTP)  │
                 └───────┬───────────────┘
```

### 直接辩论模式（跳过扫描）

```
指定品种/产业链/全品种 → 闫判官判断调度 → 四分析师供弹 → 多头/空头辩论 → 终裁(含交易参数) → 一致性 → 风控明审核 → 报告 → signal_output(CTP)
```

---

## 数据流图

```mermaid
flowchart LR
    subgraph 扫描层
        SA[scan_all.py] --> |信号管道| VALIDATE{P0-4过滤?}
        VALIDATE -->|开| V1[validator管道]
        VALIDATE -->|关 --disable-filter| V2[跳过]
        V1 --> OUT[JSON+HTML]
        V2 --> OUT
    end

    subgraph 闫判官驱动层
        OUT --> J0[闫判官判断调度<br/>judge_dispatch]
        J0 --> |dispatch 四源| CHAIN{链分析?}
        CHAIN -->|需要| CA[analyze_chain.py<br/>只分析指定链]
        CHAIN -->|不需要| SKIP_CHAIN[跳过链分析]
        CA --> CHAIN_OUT[p1_chain_analysis.json]
        CHAIN_OUT --> TI[观澜 Technical]
        CHAIN_OUT --> FU[探源 Fundamental]
        CHAIN_OUT --> SE[读心 Sentiment]
        SKIP_CHAIN --> TI
        SKIP_CHAIN --> FU
        SKIP_CHAIN --> SE
        TI --> P3[多头+空头 Debate]
        FU --> P3
        SE --> P3
        P3 --> J4[闫判官终裁<br/>Judge Final]
        J0 -.->|读取指令| J4
        J4 --> CO[一致性裁判]
        CO --> V[闫判官裁决(含交易参数)]
        V --> RK[风控明审核]
    end

    subgraph 收口层
        RK --> FINALIZE[run_debate.py finalize]
        FINALIZE --> REPORT[debate_report.html]
        FINALIZE --> SO[signal_output(CTP)]
    end

    subgraph 直接辩论层
        DB_SYM[--symbols A,B] --> DB_J0[闫判官判断调度]
        DB_CHAIN[--chain 黑色系] --> DB_RESOLVE[解析产业链映射]
        DB_RESOLVE --> DB_J0
        DB_ALL[--all] --> DB_J0
        DB_J0 --> DB_CA[链分析(按需)]
        DB_CA --> TI
    end

    style VALIDATE fill:#f96
    style J0 fill:#fc3
    style J4 fill:#fc3
    style CHAIN fill:#6f9
    style FINALIZE fill:#69f
```

---

## 产出文件清单

| 文件 | 位置 | 说明 | 由哪些模式产生 |
|:-----|:-----|:-----|:--------------|
| `scan_daily_{HHMM}_{YYYYMMDD}.json` | {日期目录}/ | 全品种扫描结果 + 排名数据 | 1-4 |
| `scan_daily_{HHMM}_ranking_{YYYYMMDD}.html` | {日期目录}/ | 排名报告HTML | 1-4 |
| `p1_chain_analysis.json` | {日期目录}/ | 链证源产业链分析结果 | 1,2,5,6,7 |
| `spawn_plan_{YYYYMMDD_HHMM}.json` | {日期目录}/ | 辩论Agent spawn计划（含闫判官判断调度 + 链数据注入） | 1,2,5,6,7 |
| `agent_lifecycle_report.json` | {日期目录}/ | Agent 生命周期报告 | 1,2,5,6,7 |
| `debate_results.json` | {日期目录}/ | 辩论裁决结果 | 1,2,5,6,7 |
| `intermediate_data.json` | {日期目录}/ | 中间数据（含链分析） | 1,2,5,6,7 |
| `debate_report_{YYYYMMDD}.html` | {日期目录}/ | 辩论综合报告HTML | 1,2,5,6,7 |
| `a2a_results.json` | {日期目录}/ | A2A协议导出 | 1,2,5,6,7 |

---

---

> **v9.6.8 变更**：P1 产出新增 `all_ranked[].stats` 纯统计特征对象（MA/ATR/RSI/ADX/量能比/通道位置）。P1.5 闸门从"方向性信号过滤"改为"数据质量闸门"（检查stats完整性、K线数量、流动性）。P2 闫判官优先消费 stats 做独立判断，P1 的 direction/total/grade 降级为参考。详见 `01-architecture.md` P1角色矫正章节。


*文档版本 v4.5 | 2026-07-17 | FDT v8.7.0 | 明鉴秋全程资源管控 + 生命周期管理 | 闫判官判断调度(链证源/观澜/探源) | 闫判官(含交易参数) | 新增 signal_output(CTP)*
