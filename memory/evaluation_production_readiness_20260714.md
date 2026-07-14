# FDT 生产就绪度评估基线（2026-07-14）

> 系统级横评，用于定位下一阶段工程化投入方向。掌柜 2026-07-14 提供。
> 七维评分（满分 10），综合均分 **6.29**。

## 一、评分原表

| 评估维度 | 得分 | 客观说明 |
|----------|------|----------|
| 期货垂直业务适配 | 9.0 | 开源独有 FDC 本地多源数据集成 + 辩论博弈投研范式，差异化极强 |
| 数据层工程完备度 | 8.5 | 内置 TDX-TQ/QMT/TQSDK/ 本地缓存一体化 FDC，解决本地量化数据痛点 |
| 架构分层与扩展性 | 7.5 | Agent 抽象规范，调度分层清晰，但无异步、分布式原生设计 |
| LLM 调用工程化 | 4.5 | 缺少 Token 管控、差异化参数、缓存重试等生产级能力 |
| 并发、容错、降级机制 | 4.0 | 同步线程调度，无限流熔断，单模块报错易阻塞全流程 |
| 落地闭环完整度（数据→信号） | 8.5 | 本地数据输入到交易信号输出链路完整 |
| 服务化、监控、运维配套 | 2.0 | 无 API、监控、定时任务等生产运维组件 |

## 二、画像解读

**强项（≥8，解决"真问题"层）**：垂直业务适配 / 数据层 / 落地闭环三轴齐高 —— 说明 FDT 在"期货本地多源数据 + 辩论投研 + 信号闭环"这个最难、最有差异化的命题上已经站住。

**中项（7.5）**：架构分层清晰，但缺异步/分布式的"原生"设计 —— 当前是单进程串行 + 子 Agent 进程编排，够用但非云原生。

**弱项（<5，解决"能稳定运行"层）**：LLM 工程化、并发容错、服务化运维三轴塌方 —— 典型"强研究原型 / 弱生产基建"画像。这三块与信号逻辑无关，是纯工程化基建。

**关键洞察**：FDT 的护城河在强项三轴，弱项是"把护城河跑稳、跑久、跑可观测"的管道。弱项不补，系统永远停留在"个人牛逼工具"而非"可托付的生产系统"。

## 三、弱项 → 整改映射（✅ 已落地 2026-07-14，详见 `docs/design/production_hardening_ABC_plan.md` + changelog）

### A. 并发容错降级（4.0）→ 优先级 ★★★（与 LLM 工程化同批，护核心辩论链路）
- 管线各阶段（scan → validate → debate → report）加 try/except 故障隔离，单模块报错降级而非阻塞全流程（信号验证器层已实现 fail-soft，可作为样板推广）
- 数据源熔断：multi_source_adapter 现有 fallback 链补"失败计数熔断"（连续 N 次失败切下一源并标记冷却）
- LLM 调用限流：令牌桶（每模型 QPS）+ 429/5xx 指数退避
- 辩论降级保留：子 Agent 失败则该轮缺员继续，而非整轮中止（现有 tiered 降级 + agent_waiter 已部分覆盖）

### B. LLM 调用工程化（4.5）→ 优先级 ★★★（与 A 同批）
- 角色化 LLM 档案 `LLM_PROFILE_MAP`（role → {model, temperature, top_p, max_tokens, cache_ttl}）：观澜(技术)低温精准、闫判官(裁决)近确定、策执远(策略)可略激进
- Token 预算：每轮上限 + 日级总上限，超额预警/熔断
- 响应缓存：相同 prompt-hash 复用（同品种同日辩论收益极大）
- 重试 + 回退模型（主 → 备）

### C. 服务化监控运维（2.0）→ 优先级 ★★（第二批，杠杆最高但体量最大）
- 调度：直接复用 WorkBuddy automation（本任务即定时盘前扫盘，勿自建 cron）
- 入口：scan_all + run_debate 收敛为单一 CLI 入口（scan / debate / report 子命令）
- 可观测：每次运行产出结构化 run-report JSON（run_id / 起止 / 扫描品种数 / 信号数 / 触发辩论数 / 各验证器拦截数 / 错误清单）+ 分级结构化日志
- 监控：run-report 喂入健康看板 / 异常告警（缺信号、某源全挂、辩论 0 产出等）

## 四、落地状态

- 评估基线已记录（2026-07-14），整改 **已全部落地（A+B+C 全上，2026-07-14）**。
- 落地范围（12 文件：6 新 + 6 改，零信号逻辑改动）：
  - **A 并发容错降级**：A1 数据源熔断 `CircuitBreaker`（multi_source_adapter 降级链，连续失败≥5 跳过+60s 冷却）；A2 阶段隔离（run_debate finalize 各阵营 try/except 标 partial 继续）；A3 缺员降级（SKILL.md degrade-on-failure + `repair` 子命令）。
  - **B LLM 调用工程化**：B1 角色化档案 `LLM_PROFILE_MAP`（7 角色约定层写入 settings.py，注入 spawn prompt）；B2 Token 预算 `TokenBudget`（per_round 12w / daily 150w 护栏，超 daily 中止 plan）；B3 辩论缓存 `DebateCache`（同品种同日期 TTL 跳过重辩）；B4 失败重排 `_emit_repair_plan`。
  - **C 服务化监控运维**：C1 统一 CLI `fdt_cli.py`（scan/debate/report/health）；C2 运行报告 `RunReporter`（写 `reports/run_report_{date}.json`，scan_all+run_debate 接入）；C3 健康钩子 `health_check.py`（5 告警规则，rc=1 供 push_to_wechat）；C4 日志镜像 `logutil.py`（文件+控制台双输出，只加不删 print）。
- **验证**：py_compile 12 文件全过；修正版自测 24 项全 PASS（A1 状态机 / B2 预算 / B3 缓存 / C2 报告 / C3 健康告警+跳过 / settings 7 角色 / run_debate 钩子 / multi_source_adapter+scan_all 接入）。
- **范围硬约束（已遵守）**：不做异步/分布式重写、不做常驻 REST API（本机非管理员+有 automation 调度，改交付 CLI+run-report+health 钩子）、不引入新信号逻辑（验证器/P0-4 行为完全不变，42 伪突破拦截数待全量实时重扫复核）。
- **下一步**：日后若调 LLM 参数只改 `LLM_PROFILE_MAP` 一处；全量实时盘前扫盘后对比 09:10 那次 42 伪突破拦截数，确认行为无回归。
