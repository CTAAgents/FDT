# FDT 生产基建加固 · A+B+C 完整实施方案（待执行）

> 对应评估弱项三轴：A 并发容错降级(4.0) / B LLM 调用工程化(4.5) / C 服务化监控运维(2.0)。
> 本文件是 `plugins/marketplaces/` 改动前的 **完整 diff 对比报告**。按铁律，掌柜明确说"执行"后才动手。
> 设计原则：**行为零改变**（加固=加外壳/加旁路，不重写核心逻辑）、**可独立开关**（风险项走 settings 开关，回滚不碰代码）、**不引入新信号逻辑**。

---

## 〇、范围与硬约束（先讲清边界）

1. **不做**异步/分布式重写（评估中"无异步原生设计" 7.5 分，体量过大，列为未来项，本次不碰）。
2. **不做**常驻 REST API 服务。理由：本机 yangd 非管理员、无法注册 Windows 服务，且已有 WorkBuddy automation 提供调度。"服务化"交付为 **统一 CLI 入口 + 结构化 run-report + 健康钩子**，足够且规避服务约束。
3. **B 轴的现实分层**（关键，避免空许）：
   - FDT 的 `run_debate.py` **不自己调 LLM**——它只产出 spawn 计划 JSON，由平台（团队主管 Agent）按机制 spawn 子 Agent。模型/温度由 automation 的 `model_id` 决定。
   - 因此 **FDT 能直接控的**：token 预算（plan 期估算+日级上限）、辩论结果缓存（同品种同日期跳过重辩）、失败重排（空/失败 spawn 重排 N 次）。
   - **只能走约定层**：每角色 model/temperature 由 spawn 时平台决定——FDT 以 `LLM_PROFILE_MAP` 形式写入 SKILL.md 供团队主管 spawn 时遵循（若平台支持 per-spawn 覆盖则生效，否则为建议性，不报错）。

---

## 一、Track A — 并发容错降级（★★★）

### A1 数据源熔断（插入点已锚定）
- **新文件** `futures_data_core/core/circuit_breaker.py`：`CircuitBreaker` 类（失败计数 + 冷却窗口 + 半开探测）。默认 `failure_threshold=5, cooldown=60s`，全参数化。
- **改** `futures_data_core/core/multi_source_adapter.py`：
  - L95 `for collector in select_by_priority(self._collectors):` 循环外，为每个 collector 名挂一个 `CircuitBreaker` 实例（存 `self._breakers`）。
  - 调用前若 breaker 处于 OPEN，跳过该 collector（不再空打）；调用抛 `CollectorUnavailableError` 记一次失败，达阈值则 OPEN；冷却后下次调用进入 HALF_OPEN，成功则 CLOSE。
  - 暴露 `self.source_health()` → `{"tdx": "open"/"closed", ...}` 供 run-report 读取。
- **行为**：TDX 连续 5 次不可用 → 自动跳过、直落 TqSDK/Web，不再每根 K 线重试 TDX 拖慢全流程；60s 后自动恢复探测。

### A2 管线阶段故障隔离
- **改** `skills/quant-daily/scripts/scan_all.py`：scan → validate → 写 JSON 三阶段各包 `try/except`；validate 失败则带 `unvalidated=True` 标记继续（不再整轮崩），并打印降级告警。
- **改** `scripts/run_debate.py`：`plan` / `finalize` 两阶段隔离；`finalize` 容忍缺失的子 Agent 产出（部分品种无 p4/p5 → 该品种标 `partial`，其余正常出报告）。

### A3 辩论缺员降级策略（约定层）
- **改** `skills/fdt-spawn-debate/SKILL.md`：新增「degrade-on-failure」段——子 Agent 超时/缺失时，该轮以可用输入继续（裁决方拿到的论据不全则标注 `partial_evidence`），而非整轮中止。

**A 风险**：熔断阈值误配可能短暂屏蔽健康源 → 默认保守(5/60s)+settings 可调；阶段隔离可能掩盖真实错误 → 所有 except 均打印 ERROR 级日志并计入 run-report。

---

## 二、Track B — LLM 调用工程化（★★★）

### B1 角色化 LLM 档案（约定层 + 部分可控）
- **改** `skills/quant-daily/scripts/config/settings.py`：新增 `LLM_PROFILE_MAP`：
  ```
  观澜(技术):   {model: "deepseek-v4-flash", temperature: 0.1, top_p: 0.9, max_tokens: 4000, cache_ttl: 86400}
  证真/慎思:    {model: "deepseek-v4-flash", temperature: 0.4, top_p: 0.95, max_tokens: 3000, cache_ttl: 86400}
  闫判官(裁决): {model: "deepseek-v4-flash", temperature: 0.0, top_p: 0.8, max_tokens: 2000, cache_ttl: 86400}
  策执远(策略): {model: "deepseek-v4-flash", temperature: 0.5, top_p: 0.95, max_tokens: 3000, cache_ttl: 86400}
  风控明(风控): {model: "deepseek-v4-flash", temperature: 0.2, top_p: 0.85, max_tokens: 2000, cache_ttl: 86400}
  一致性裁判:    {model: "deepseek-v4-flash", temperature: 0.0, top_p: 0.8, max_tokens: 1500, cache_ttl: 86400}
  ```
  新增 `LLM_TOKEN_BUDGET = {"per_round": 120000, "daily": 1500000}`（估算值，settings 可调）。
- **改** `skills/fdt-spawn-debate/SKILL.md`：注入「按 LLM_PROFILE_MAP 选 model/temperature spawn」指引。

### B2 Token 预算（FDT 可控）
- **新文件** `scripts/llm/token_budget.py`：`TokenBudget` 类，日级用量持久化到 `data/.llm_budget_{date}.json`；`estimate(prompt)` 用 `len(chars)/2.5` 粗估；`consume(role, prompt)` 在 `plan` 阶段对每个 spawn prompt 计费，超 `per_round` 预警、超 `daily` 中止 plan 并报错。

### B3 辩论结果缓存（FDT 可控）
- **新文件** `scripts/llm/cache.py`：`DebateCache` 类，key=`hash(symbol+date+round)`，存 `debate_results_{symbol}_{date}.json` 路径 + TTL（读 `LLM_PROFILE_MAP.cache_ttl`）。`plan` 阶段若命中且未过期 → 跳过该品种 spawn，直接复用。提供 `--no-cache` 强制重辩。

### B4 失败重排（FDT 可控）
- **改** `scripts/run_debate.py`：`finalize` 前检测各品种 p4/p5 是否齐备；缺失且未超 `max_retry=2` → 重排 spawn 计划片段（产出「补辩计划」供主管重 spawn），超限则标 `partial` 继续。

**B 风险**：`LLM_PROFILE_MAP` 的 model 覆盖依赖平台 per-spawn 能力；若不支持，profile 仅为建议、不报错（已在 §〇 说明）。缓存可能因同日同品种重复辩论而"吞掉"本该重辩的场景 → TTL=86400 且 `--no-cache` 可破。

---

## 三、Track C — 服务化监控运维（★★）

### C1 统一 CLI 入口
- **新文件** `scripts/fdt_cli.py`：薄分发器，子命令 `scan`(→scan_all) / `debate plan|finalize`(→run_debate) / `report`(→phase3_generate_report)。不重写已有逻辑，仅收敛入口。日后 automation 可直接调 `fdt_cli.py debate plan ...`。

### C2 运行报告（可观测 backbone）
- **新文件** `scripts/run_reporter.py`：`RunReporter` 跨阶段累加指标，`flush()` 写 `reports/run_report_{date}.json`：
  `run_id / start_ts / end_ts / phase_durations / n_symbols_scanned / n_signals / n_triggered_debates / per_validator_demotions(借新验证器框架 last_run_stats) / source_health(借 A1) / errors[]`。
- **改** `scan_all.py`（扫描末）与 `run_debate.py`（`finalize` 末）各挂一次 `RunReporter.flush()` 钩子。

### C3 健康钩子
- **新文件** `scripts/health_check.py`：读最新 run_report，触发告警规则（0 信号 / 全源 dead / 有信号却 0 辩论 / 验证器错误率>阈值），产出 `alerts_{date}.json` + 打印。自动化 `push_to_wechat=true` 已能把运行输出推送。

### C4 结构化日志（渐进式，最低风险）
- **新** `scripts/logutil.py`：`setup_logging(date)` 同时输出到 `logs/fdt_{date}.log` 与控制台。
- **改** `scan_all.py` / `run_debate.py` / `multi_source_adapter.py`：先**镜像**（print 照留，额外写 logger），再逐步把关键节点 print 换 logger。首版为"加文件镜像"，不删 print，避免破坏任何 stdout 解析方。

**C 风险**：日志重构若误删 print 可能影响其他 grep stdout 的脚本 → 首版只加镜像、不删；run-report 字段若取数失败 → 字段置 null 而非抛错。

---

## 四、改动清单（文件级 manifest）

| 类型 | 文件 | Track | 改动性质 |
|------|------|-------|----------|
| 🆕 | `futures_data_core/core/circuit_breaker.py` | A | 新增熔断类 |
| ✏️ | `futures_data_core/core/multi_source_adapter.py` | A | L95 循环挂 breaker + 暴露 source_health() |
| ✏️ | `skills/quant-daily/scripts/scan_all.py` | A/C | 阶段隔离 + RunReporter 钩子 + 日志镜像 |
| ✏️ | `scripts/run_debate.py` | A/B/C | finalize 容缺 + token预算 + 缓存 + 重排 + reporter 钩子 |
| ✏️ | `skills/fdt-spawn-debate/SKILL.md` | A/B | degrade-on-failure 段 + LLM_PROFILE_MAP 指引 |
| ✏️ | `skills/quant-daily/scripts/config/settings.py` | B | 新增 LLM_PROFILE_MAP + LLM_TOKEN_BUDGET |
| 🆕 | `scripts/llm/token_budget.py` | B | Token 预算追踪 |
| 🆕 | `scripts/llm/cache.py` | B | 辩论结果缓存 |
| 🆕 | `scripts/fdt_cli.py` | C | 统一 CLI 分发 |
| 🆕 | `scripts/run_reporter.py` | C | 运行报告 |
| 🆕 | `scripts/health_check.py` | C | 健康钩子 |
| 🆕 | `scripts/logutil.py` | C | 日志设置 |

总计：🆕 6 个新文件，✏️ 6 个改动文件。无删除、无覆盖既有逻辑。

---

## 五、实施顺序（每 Phase 独立可交付）

- **Phase 1（A）**：circuit_breaker + multi_source_adapter 熔断 + scan_all/run_debate 阶段隔离 + SKILL degrade 段。
- **Phase 2（B）**：settings LLM_PROFILE_MAP + token_budget + cache + run_debate 集成 + SKILL 注入。
- **Phase 3（C）**：fdt_cli + run_reporter + health_check + logutil 镜像。
- 依赖：C2 run-report 借 A1 的 `source_health()` 与验证器框架 `last_run_stats`（已存在），故 C 在 A 之后收尾最顺。

---

## 六、回归与验证

1. `py_compile` 全部 12 文件通过。
2. **09:10 扫描回放**：42 伪突破拦截数不变（验证器未动；reporter 只读数不改数）。
3. **熔断单测**：mock TDX 连败 5 次 → breaker OPEN → 自动落 TqSDK；60s 后 HALF_OPEN 恢复。
4. **token 预算**：mock scan 跑 `plan` → 估算 token 打印；超 `daily` → 中止并告警。
5. **缓存**：同品种同日期二次 `plan` → 命中缓存跳过 spawn（或 `--no-cache` 强制）。
6. **run-report**：扫描后 JSON 含 n_symbols/n_signals/per_validator_demotions；finalize 后含 n_triggered_debates/errors。
7. **health_check**：对一次干净 run_report → 无告警。

---

## 七、风险与回滚

- 所有风险项（熔断阈值、日志、缓存 TTL、token 上限）均为 `settings.py` 参数，**可一键关/调**，无需回滚代码。
- 阶段隔离所有 except 必打印 ERROR 且计入 run-report，不静默吞错。
- 日志首版只"加镜像"不"删 print"，零破坏 stdout 解析方。
- 若 Phase 出问题，独立 Phase 可单独 revert（彼此文件耦合低）。

---

## 八、明确不做（out of scope）

- ❌ 异步/分布式重写（未来项）。
- ❌ 常驻 REST API 服务（本机非管理员+有 automation 调度，CLI+report 足够）。
- ❌ 任何新信号逻辑 / 新因子（只加固基建）。

---

## 九、铁律闸门

本方案涉及 `plugins/marketplaces/` 生产目录。**当前未做任何改动**。掌柜回复"执行"后，按 Phase 1→3 落地，落地后同步更新 FDT 自身 `changelog.md` / `MEMORY.md`（评估整改段）+ `memory/technical_debt.md`（如涉及）。
