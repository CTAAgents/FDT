# FDT 执行模式流程图

> v4.0 | 2026-07-14 | 伪信号过滤 + 辩论开关 + 链证源 + 资源管控 + 生命周期 → 8种执行模式

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

### 辩论流程

```
信号计算 → [过滤?] → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → 审计 → 方案 → 风控 → 报告
                           ↑          ↑          ↑       ↑       ↑           ↑      ↑      ↑      ↑
                     ┌─────┴──────────┴──────────┴───────┴───────┴───────────┴──────┴──────┴──────┘
                     │ 每批 spawn 前查资源，完成后 shutdown 释放
                     └──────────────────── 明鉴秋管控 ────────────────────
```

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
# 完整一轮 8 阶段的资源释放时序
Phase0 闫判官初判 → spawn 1 → register → wait → shutdown ✅ 释放1
Phase1 链证源     → 自动运行（不占用 Agent 资源）
Phase2 观澜×N    → spawn N → register → wait → shutdown ✅ 释放N
Phase3 辩论×N    → spawn N → register → wait → shutdown ✅ 释放N
Phase4 闫判官终裁 → spawn N → register → wait → shutdown ✅ 释放N
Phase5 一致性×N   → spawn N → register → wait → shutdown ✅ 释放N
Phase6 策执远×N   → spawn N → register → wait → shutdown ✅ 释放N
Phase7 风控明×N   → spawn N → register → wait → shutdown ✅ 释放N
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

# 3) 明鉴秋逐个发送 shutdown_request（WorkBuddy 聊天层）
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
信号计算 → P0-4伪信号过滤 → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → ... → 报告
────┬────   ──────┬──────   ────┬────   ──────┬────   ────┬   ────┬   ────┬────   ────┬───
   │                 │             │             │           │       │       │           │
   │  scan_all.py    │  validator  │ judge_      │ 只分析    │ 技术   │ 正反  │ 读指令+   │ HTML
   │  62品种        │  P0-4门禁  │ initial     │ 闫判官    │ 分析   │ 辩论  │ 链+辩论   │
   │                 │             │ 指定链+品种 │ 指定产业链 │        │       │ →裁决    │
```

```
python scripts/fdt_cli.py pipeline --mode full --workspace <dir>
```

---

### 模式二: `no-filter` — 扫描→辩论(不过滤)

```
信号计算 → (跳过过滤) → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → ... → 报告
────┬────                  ────┬────   ──────┬────   ────┬   ────┬   ────┬────   ────┬───
   │  --disable-filter       │ judge_      │ 只分析    │ 技术   │ 正反  │ 读指令+   │ HTML
   │  保留伪突破信号         │ initial     │ 闫判官    │ 分析   │ 辩论  │ 链+辩论   │
   │                          │ 指定链+品种 │ 指定产业链 │        │       │ →裁决    │
```

```
python scripts/fdt_cli.py pipeline --mode no-filter --workspace <dir>
```

---

### 模式三: `scan-only` — 仅信号计算

```
信号计算 → 结束输出
────┬────   ────┬───
   │  --disable-filter  │ JSON + HTML
   │  不过滤不辩论      │ 排名报告
```

```
python scripts/fdt_cli.py pipeline --mode scan-only --workspace <dir>
```

---

### 模式四: `scan-filter` — 信号计算+过滤

```
信号计算 → P0-4伪信号过滤 → 结束输出
────┬────   ──────┬──────   ────┬───
   │               │             │ JSON + HTML
   │  scan_all    │  过滤后     │ (含拦前/拦后分)
   │              │  信号       │
```

```
python scripts/fdt_cli.py pipeline --mode scan-filter --workspace <dir>
```

---

### 模式五: `debate` — 指定品种辩论

```
(跳过扫描) → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → ... → 报告
              ────┬────   ──────┬────   ────┬   ────┬   ────┬────   ────┬───
                   │ judge_      │ 只分析    │ 技术   │ 正反  │ 读指令+   │ HTML
                   │ initial     │ 指定链    │ 分析   │ 辩论  │ 链+辩论   │
                   │ (无扫描     │           │        │       │ →裁决    │
                   │  虚拟触发)  │           │        │       │           │
```

```
python scripts/fdt_cli.py pipeline --mode debate --symbols pb,sc,l --workspace <dir>
```

---

### 模式六: `debate-group` — 指定产业链辩论

```
(跳过扫描) → 品种解析 → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → 报告
              ────┬───   ────┬────   ──────┬────   ────┬   ────┬   ────┬────   ────┬───
                   │ --chain  │ judge_      │ 只分析    │ 技术   │ 正反  │ 读指令+   │ HTML
                   │ 黑色系   │ initial     │ 指定链    │ 分析   │ 辩论  │ 链+辩论   │
                   │ 解析品种 │ (产业链列表)│           │        │       │ →裁决    │
```

```
python scripts/fdt_cli.py pipeline --mode debate-group --chain 黑色系 --workspace <dir>
```

---

### 模式七: `debate-all` — 强制全品种辩论

```
(跳过扫描) → 全品种列表 → 闫判官初判 → 链证源(按需) → 观澜 → 辩论 → 闫判官终裁 → 报告
              ─────┬────   ────┬────   ──────┬────   ────┬   ────┬   ────┬────   ────┬───
                   │ --all     │ judge_      │ 只分析    │ 技术   │ 正反  │ 读指令+   │ HTML
                   │ 62品种    │ initial     │ 指定链    │ 分析   │ 辩论  │ 链+辩论   │
                   │           │ (全品种)    │           │        │       │ →裁决    │
```

```
python scripts/fdt_cli.py pipeline --mode debate-all --workspace <dir>
```

---

### 模式八: `finalize-only` — 仅收口

```
(spawn完成后) → 组装(含链数据) → 萃取 → 报告生成 → 输出
                 │                  │       │         │
                 │ assemble         │ 提取知识  │ HTML报告
                 │ debate_          │ 入库     │
                 │ results +        │          │
                 │ 链分析数据        │          │
```

```
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

## 链证源注入说明

### 运行时机

`run_chain_analysis()` 在 `run_debate.py` 的 **plan** 和 **debate** 子命令执行时自动运行：

```
plan 子命令: scan加载 → 链分析(analyze_chain.py --symbols) → build_spawn_plan(注入链数据) → 输出spawn_plan.json
debate 子命令: 解析品种 → 链分析(analyze_chain.py --symbols) → build_spawn_plan(注入链数据) → 输出spawn_plan.json
```

### 受影响的 Agent 角色

链证源数据被注入到 spawn plan 中以下 5 个角色的 prompt：

| 角色 | 身份 | 链数据用途 |
|:-----|:-----|:----------|
| **technical** | 观澜(技术面研究员) | 分析产业链同品种支撑阻力共振 |
| **zhengzhen** | 证真(正方辩手) | 引用产业链同向品种作为论据 |
| **zhensi** | 慎思(反方辩手) | 引用产业链反向品种质疑信号 |
| **judge** | 闫判官(裁决) | 产业链一致性/冗余/趋势作为裁决维度 |
| **trading_plan** | 策执远(出方案) | 产业链联动性影响止损/目标位设定 |

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

# 2. 辩论计划(含链分析)
python scripts/run_debate.py plan --scan <scan.json> --workspace <dir>

# 3. (逐批 spawn Agent，每批 register → wait → shutdown)
#    Phase0 闫判官初判 → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase2 观澜×N     → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase3 辩论×N     → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase4 闫判官终裁 → spawn → lifecycle register → wait-and-shutdown → shutdown
#    Phase5-7 同上

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
# 直接辩论(无扫描，自动链分析)
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
                 │  闫判官初判     │
                 │  (决定链+品种)  │
                 └───────┬────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
     ┌────────┴────────┐  ┌────────┴────────┐
     │ 无需辩论         │  │ 需要辩论         │
     │ (结束输出)       │  │                 │
     └─────────────────┘  │  ┌──────────────┴──────────────┐
                          │  │  链分析(只分析指定产业链)    │
                          │  └──────────────┬──────────────┘
                          │                 │
                          │  ┌──────────────┴──────────────┐
                          │  │  观澜 技术分析               │
                          │  └──────────────┬──────────────┘
                          │                 │
                          │  ┌──────────────┴──────────────┐
                          │  │  证真 + 慎思 辩论            │
                          │  └──────────────┬──────────────┘
                          │                 │
                          │  ┌──────────────┴──────────────┐
                          │  │  闫判官 终裁                 │
                          │  │  (读指令+链+辩论→出裁决)     │
                          │  └──────────────┬──────────────┘
                          │                 │
                          │  ┌──────────────┴──────────────┐
                          │  │  一致性裁判 → 策执远方案      │
                          │  │  → 风控明审核               │
                          │  └──────────────┬──────────────┘
                          │                 │
                          └──────┬──────────┘
                                 │
                         ┌───────┴────────┐
                         │  组装收口       │
                         │  知识萃取       │
                         │  报告生成       │
                         │  输出           │
                         └────────────────┘
```

### 直接辩论模式（跳过扫描）

```
指定品种/产业链/全品种 → 闫判官初判 → 链分析(按需) → 观澜 → 辩论 → 终裁 → 审计 → 方案 → 风控 → 报告
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
        OUT --> J0[闫判官初判<br/>judge_initial]
        J0 --> |p0_judge_directive.json| CHAIN{链分析?}
        CHAIN -->|需要| CA[analyze_chain.py<br/>只分析指定链]
        CHAIN -->|不需要| SKIP_CHAIN[跳过链分析]
        CA --> CHAIN_OUT[p1_chain_analysis.json]
        CHAIN_OUT --> TI[观澜 Technical]
        SKIP_CHAIN --> TI
        TI --> P3[证真+慎思 Debate]
        P3 --> J4[闫判官终裁<br/>Judge Final]
        J0 -.->|读取指令| J4
        J4 --> CO[一致性裁判]
        CO --> TP[策执远方案]
        TP --> RK[风控明审核]
    end

    subgraph 收口层
        RK --> FINALIZE[run_debate.py finalize]
        FINALIZE --> REPORT[debate_report.html]
    end

    subgraph 直接辩论层
        DB_SYM[--symbols A,B] --> DB_J0[闫判官初判]
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
| `spawn_plan_{YYYYMMDD_HHMM}.json` | {日期目录}/ | 辩论Agent spawn计划 | 1,2,5,6,7 |
| `agent_lifecycle_report.json` | {日期目录}/ | Agent 生命周期报告 | 1,2,5,6,7 |

---

*文档版本 v4.0 | 2026-07-14 14:05 | FDT v5.12.1 | 明鉴秋全程资源管控 + 生命周期管理*
| `debate_results.json` | {日期目录}/ | 辩论裁决结果 | 1,2,5,6,7 |
| `intermediate_data.json` | {日期目录}/ | 中间数据（含链分析） | 1,2,5,6,7 |
| `debate_report_{YYYYMMDD}.html` | {日期目录}/ | 辩论综合报告HTML | 1,2,5,6,7 |
| `a2a_results.json` | {日期目录}/ | A2A协议导出 | 1,2,5,6,7 |

---

*文档版本 v4.0 | 2026-07-14 14:05 | FDT v5.12.1 | 明鉴秋全程资源管控 + 生命周期管理*
