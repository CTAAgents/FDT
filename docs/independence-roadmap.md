# FDT 独立 Agent 系统路线图

> 版本: v0.1 (2026-07-16)
> 定位: FDT 的终极形态是独立 Agent 系统，不依赖任何宿主平台。
> 当前: 寄生在 WorkBuddy 中，为过渡形态的权宜之计。

---

## 一、寄生点全景

### 第1层：基础设施层（最难脱离，最晚动）

| # | 寄生点 | 现状 | 脱离难度 |
|:-:|:-------|:-----|:--------:|
| 1 | **AI 模型推理** | 依赖 WorkBuddy 的 LLM 后端（DeepSeek/Claude等） | ★★★★★ |
| 2 | **Agent 运行时** | spawn 子 Agent 靠 WorkBuddy 的 Agent 工具 | ★★★★★ |
| 3 | **用户交互界面** | 通过 WorkBuddy 对话界面操作 | ★★★★ |
| 4 | **团队协作机制** | TaskCreate/TaskUpdate/SendMessage 靠 WorkBuddy | ★★★★ |

### 第2层：数据层（可逐步替换）

| # | 寄生点 | 现状 | 脱离难度 |
|:-:|:-------|:-----|:--------:|
| 5 | **行情数据** | TDX TQ-Local HTTP 直连（已独立） | ★★ |
| 6 | **持仓排名** | 5 家交易所官网直连（已独立） | ★★ |
| 7 | **东方财富数据** | HTTP 直连（已独立） | ★★ |
| 8 | **MCP 连接器** | tdx-connector / westock-mcp 通过 WorkBuddy | ★★★ |

### 第3层：能力层（核心剥离对象）

| # | 寄生点 | 现状 | 脱离难度 |
|:-:|:-------|:-----|:--------:|
| 9 | **自检逻辑** | ✅ 已代码化 `scripts/self_check.py` | ★ 已解决 |
| 10 | **技术指标计算** | ✅ 已迁入 `skills/quant-daily/scripts/indicators/` | ★ 已解决 |
| 11 | **FDT Skill 定义** | 13 个 skill 是 WorkBuddy SKILL.md 格式 | ★★★ |
| 12 | **Expert Agent 定义** | 13 个 Agent 定义是 WorkBuddy 格式 | ★★★ |
| 13 | **记忆/日志系统** | 部分在 WorkBuddy 工作空间 | ★★ |
| 14 | **自动化调度** | 依赖 WorkBuddy automation | ★★★ |
| 15 | **辩论流程控制** | 协调器在 FDT 内部，但 spawn 依赖外部 | ★★★★ |

---

## 二、三阶段路线图

### 里程碑 M1：代码完整自治（4周）

**目标**：FDT 的 Python 代码层彻底不依赖 WorkBuddy，可 clone 即跑。

| 任务 | 工作内容 | 优先级 | 预估工作量 |
|:-----|:---------|:------:|:----------:|
| M1.1 | 将 13 个 WorkBuddy Skill（`skills/*/SKILL.md`）转为 FDT 原生格式（`.py` + `docs/`），删除 WorkBuddy Skill 依赖 | P0 | 2周 |
| M1.2 | 将 13 个 Expert Agent 定义（`agents/*.md`）转为 FDT 内部 Agent 配置（YAML/JSON），独立解析 | P0 | 1周 |
| M1.3 | 建立 `fdt_data_core` 直连数据管道，消除对 tdx-connector/westock-mcp MCP 的依赖 | P0 | 2周 |
| M1.4 | 记忆系统全部迁移到 FDT 内部 `memory/` 目录，消除对 WorkBuddy 工作空间记忆的依赖 | P1 | 3天 |
| M1.5 | `self_check.py` 扩展为 FDT 独立健康检查系统，不再通过 `Skill()` 加载 | ✅ 已完成 | — |

### 里程碑 M2：调度自治（3个月）

**目标**：FDT 有自己的定时调度、日志、告警系统，不依赖 WorkBuddy automation / 推送。

| 任务 | 工作内容 | 优先级 | 预估工作量 |
|:-----|:---------|:------:|:----------:|
| M2.1 | 实现 FDT 内置调度器（cron 表达式 + 任务队列），替代 WorkBuddy automation | P0 | 2周 |
| M2.2 | 辩论流程内置化：`fdt_cli.py debate` 直接控制辩论全流程，不依赖外部 spawn | P0 | 3周 |
| M2.3 | 实现基于文件的 Agent 间通信协议，替代 SendMessage | P0 | 1周 |
| M2.4 | 告警推送系统（Email / 企业微信 / Telegram），替代 WorkBuddy push_to_wechat | P1 | 1周 |
| M2.5 | 守护进程模式：`fdt_cli.py daemon` 后台运行，替代 WorkBuddy 会话 | P1 | 1周 |

### 里程碑 M3：交互自治（6个月+）

**目标**：FDT 可作为独立服务运行，有自己的 Web UI / API / Agent 管理界面。

| 任务 | 工作内容 | 优先级 | 预估工作量 |
|:-----|:---------|:------:|:----------:|
| M3.1 | 实现 Web Dashboard（Flask/FastAPI），查看扫描结果、辩论报告 | P1 | 3周 |
| M3.2 | REST API 暴露所有 `fdt_cli.py` 能力 | P1 | 2周 |
| M3.3 | 多种 LLM 后端适配（OpenAI API / 本地模型），消除对 WorkBuddy 模型后端的依赖 | P0 | 3周 |
| M3.4 | Agent 自托管运行时：FDT 自己管理 Agent 生命周期，不再依赖 WorkBuddy spawn | P0 | 6周 |
| M3.5 | WebSocket 实时推送（行情/信号/告警） | P2 | 1周 |

---

## 三、依赖关系图

```
M1 (代码自治) ─── M2 (调度自治) ─── M3 (交互自治)
    │                   │                  │
    ├─ M1.1 Skill 转换   ├─ M2.1 调度器     ├─ M3.1 Dashboard
    ├─ M1.2 Agent 配置   ├─ M2.2 辩论内置   ├─ M3.2 REST API
    ├─ M1.3 数据直连     ├─ M2.3 通信协议   ├─ M3.3 LLM 适配
    ├─ M1.4 记忆迁移     ├─ M2.4 告警推送   ├─ M3.4 Agent 运行时
    └─ M1.5 健康检查 ✅   └─ M2.5 守护进程   └─ M3.5 实时推送

关键路径: M1.1 → M1.2 → M2.2 → M3.4
```

每个里程碑都**可独立交付**，M1 完成后 FDT 就可以脱离 WorkBuddy 以 CLI 方式运行（虽然仍依赖 WorkBuddy 的 LLM 和 Agent 运行时）。M2 完成后可以不打开 WorkBuddy 也自动跑扫描。M3 完成后完全独立。

---

## 四、风险与权衡

| 风险 | 影响 | 缓解措施 |
|:-----|:-----|:---------|
| AI 模型推理成本 | 自建 LLM 后端增加成本 | M3.3 先做 OpenAI API 兼容层，用好现有 API Key |
| Agent 运行时复杂度 | 自己管理 Agent 生命周期是巨大工程 | M3.4 优先实现简化版（顺序执行，不并行 spawn），后续再优化 |
| 数据管道可靠性 | 直连交易所官网可能因反爬/API 变更中断 | 保持多源降级链，为每个源做健康监控 + 自动切换 |
| 与 WorkBuddy 共存期 | 两个系统并行，可能冲突 | 逐步替换而非一次性切换，每个模块独立验收后再切 |

---

## 五、优先级原则

1. **P0：先切数据层，再切逻辑层，最后切交互层**
2. **P0：每项改动必须可独立提效**（不为了去绑定而做无价值重构）
3. **P1：不破坏现有 WorkBuddy 运行路径**，旧路径和新路径并行运行直至验证通过
4. **P2：先不追求性能，先追求功能独立**（Agent 运行时初期可以很慢）
