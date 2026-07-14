# FDT 专家团变更日志

> 记录所有代码/配置/机制的变更。按时间逆序排列。

---

## 2026-07-14 17:10 — v6.3.1 缺陷修复（§2/§3 迁移收尾 + 系统化测试）

- **系统化测试发现真实集成断裂**：链分析 `build_symbol_map` 硬读 `summary["symbols"]` 且期望嵌套 `l1l4`/`factor_timing`，但迁移后 scan_all 只出 channel_breakout 结构（无 `symbols` 键、无嵌套），导致 P1.5 链分析崩溃 `KeyError: 'symbols'`
- **修复**：`run_full_chain_analysis.py` + `run_final_chain_analysis.py` 的 `build_symbol_map(summary)` → `build_symbol_map(summary, l1l4, ft)`，改为三源合并（summary.all_ranked + l1l4.all_ranked + ft.all_ranked 并集）；`_meta` 容错沿用 Phase D
- **factor_timing._zscore 全 NaN 防护**：FDC K线不可用时因子列全 NaN → `np.nanmean` 报 "Mean of empty slice"，加 `vals.size==0 or not np.isfinite(vals).any()` 返回零
- **回归测试**：新增 `tests/commodity-chain/test_chain_full_analysis.py`（2 用例 PASS），固化三源合并逻辑
- **测试覆盖**：import 级（迁入模块+FDC）全过；三生产者运行时跑通 exit 0；assemble_intermediate_data + 链分析消费端验证；fdc/technical-analysis 既有套件为预存在 SKIP（无关改动）
- **版本**：pyproject 6.3.0→6.3.1；commodity-chain-analysis 2.16→2.17；fundamental-data-collector 1.4→1.5

---

## 2026-07-14 16:15 — 技术债 §2/§3 重构式迁移全案落地 + 版本 bump 6.3.0

- **范围**：layered_l1l4 迁至 technical-analysis（观澜 `run_l1l4_scan.py`），factor_timing 迁至 fundamental-data-collector（探源 `run_factor_timing_scan.py`），scan_all.py 剥离二者仅留 channel_breakout
- **策略注册表**：`strategies/` 仅余 channel_breakout + three_signal；`layered_l1l4.py` / `factor_timing.py` / `true_layered.py` 已删并注销
- **scan_all.py 清理**：删 `--dual` 参数、`mode_labels` 去 true_layered、策略解析恒为 channel_breakout（消除 `--mode true_layered` KeyError 死路径）
- **三生产者链路**：数技源 scan_all(`full_scan_summary_*`) + 观澜 run_l1l4_scan(`full_scan_l1l4_*`) + 探源 run_factor_timing_scan(`full_scan_factor_timing_*`)；`pipeline/runner.py step_scan()` + `scheduler/tasks.py daily_debate()` Step1 已重写为三生产者调用，`full_scan_summary` 文件名精确匹配下游
- **文档全量重指**：agents(datatech/technical-researcher/chain-analyst) + docs(business_flow/harness/02-lifecycle) + `rules/futures-debate-team_rules.md` + 三 SKILL.md + 两 `data_interface.py` + chain 分析脚本防崩(`_meta` KeyError 容错)
- **版本**：pyproject.toml 6.2.0→6.3.0；quant-daily 2.14→2.15 / technical-analysis 2.2→2.3 / fundamental-data-collector 1.3→1.4 / commodity-chain-analysis 2.15→2.16 / futures-trading-analysis 3.10→3.11
- **验证**：6 个改动 .py py_compile 全过；全包 `--dual`/`true_layered` 仅剩历史/备份/注释残留，无活文档驱动；辩论流水线保持可用

---

## 2026-07-14 13:00 — 技术债 §1 收编落地（A' 执行完成）

- **方案**: 收编进 `futures_data_core.indicators/`（FDC 体系内，不新建 skill；原方案 A 新建 futures-data-engine 经掌柜架构质疑废弃）
- **新增文件**（FDC 内）：`indicators/tdx_compat.py`（calc_core 整份搬运）、`indicators/legacy_numpy.py`（_compute_indicators_numpy+safe_float）、`indicators/trend_maturity.py`（assess_trend_maturity 超集版）、`indicators/__init__.py` 统一 re-export（44 公开名）
- **shim 改造**：quant-daily `calc_core.py`/`core.py`/`indicators_legacy.py` 改为 re-export；`tdx_bridge.py` 本就 FDC 依赖无需改；~20 importer 不动
- **合并决策**：assess_trend_maturity 双副本经 byte-diff，legacy 版为超集（多 bb_squeeze/bb_width_pct/dc55_trend），采用 legacy 版为权威
- **验证全过**：py_compile + 四路导入冒烟(符号 is 同源) + 数值回归单测 + 17 importer 结构回归 + 实跑 PK/RB/B/UR 指标管线正常
- **零信号逻辑变更**：验证器/P0-4 未动

---

## 2026-07-14 12:40 — 技术债 §1 方案 A' 文档 v0.3 修订（review 采纳）

- **触发**：掌柜 review `docs/design/tech_debt_s1_indicator_extraction_plan.md` 后采纳 5 项修正建议
- **修正内容（v0.2→v0.3）**：
  1. 行数误述：calc_core.py ~1700→2065、futures_data_core/indicators/core.py "—"→421（~16 基础指标）、取消"69KB/64KB/45 字段"旧描述
  2. 双 core 误述：quant-daily `core.py` 非纯薄壳（L98 另定义 `assess_trend_maturity`），与 indicators_legacy.py:21 构成双副本
  3. 术语矛盾：§2 表"反向依赖"改为"quant-daily→FDC 单向依赖" / "quant-daily 内部 import"
  4. 新增 §6 步 1.5「双定义函数合并前 byte-diff」（必做，不一致则人工裁决）
  5. 新增 §6 验证门 2.5「指标数值回归单测」（rsi/atr 容差 1e-6，捕捉搬移静默漂移）
- **方向未变**：方案 A'（收编进 `futures_data_core.indicators`，不新建 skill、不改 sys.path）已确认，待掌柜授权"执行"

---

## 2026-07-14 12:06 — 项目规范文档落地（CLAUDE.md + CODING_STANDARDS.md）

- **触发**：掌柜要求将 FDT 代码风格与开发规范 + CLAUDE.md 放入「项目根目录及工作空间记忆系统」作为项目规范文档
- **根目录落位（canonical）**：
  - `CLAUDE.md`（项目根）：复制自 `C:\Users\yangd\Desktop\CLAUDE.md`，FDT AI 编码行为准则（四原则权威源）
  - `CODING_STANDARDS.md`（项目根）：掌柜提供的代码风格与开发规范 v0.1.0（Ruff/isort/Google docstring/类型提示/命名/错误处理/行宽120）
- **记忆系统注册**：`memory/MEMORY.md` 新增「📘 项目规范文档」段（定位 + 根路径 + Ruff 现状 + 遵守要求）
- **Ruff 一致性**：`pyproject.toml [tool.ruff]` 已配 `line-length=120` + `select=["E","F","I","N","W"]`，与 `CODING_STANDARDS.md` 指南一致，无需改配置
- **归位铁律遵循**：按 2026-07-14 文档归位铁律，规范文档存于 FDT 专家包根目录 + FDT 自身 `memory/`，未散落宿主工作空间
- **说明**：`CODING_STANDARDS.md` 中 `trend_scanner.*` / `tools/core/sync_data.py` / `docs/TESTING.md` 等为通用模板引用，与 FDT 实际包名不完全对齐，按掌柜原文逐字保留未改

---

## 2026-07-14 11:37 — A+B+C 生产基建加固全量落地（弱项三轴整改）

- **触发**：掌柜「A+B+C 全上」拍板（评估基线弱项三轴：并发容错 4.0 / LLM 工程化 4.5 / 服务运维 2.0）
- **范围硬约束**：不做异步/分布式重写；不做常驻 REST API（本机非管理员+有 automation 调度，改交付 CLI+run-report+health 钩子）；不引入新信号逻辑（验证器/P0-4 行为完全不变）
- **新增 🆕7 文件**：
  - `futures_data_core/core/circuit_breaker.py`（A1 `CircuitBreaker` 状态机 CLOSED/OPEN/HALF_OPEN，失败计数+冷却）
  - `scripts/llm/token_budget.py`（B2 `TokenBudget` per_round 12w/daily 150w 护栏，超 daily 抛 `BudgetExceeded`）
  - `scripts/llm/cache.py`（B3 `DebateCache` key=(symbol,date)，TTL 跳同品种同日重辩）
  - `scripts/run_reporter.py`（C2 `RunReporter` 写 `reports/run_report_{date}.json`，跨阶段累加+同日合并）
  - `scripts/health_check.py`（C3 读 run_report 触发 5 告警规则，rc=1 供 push_to_wechat）
  - `scripts/logutil.py`（C4 `setup_logging` 文件+控制台双输出，只加镜像不删 print）
  - `scripts/fdt_cli.py`（C1 薄分发器 scan/debate(plan|finalize)/report/health）
- **修改 ✏️6 文件**：
  - `futures_data_core/core/multi_source_adapter.py`：A1 降级链三处接 `CircuitBreaker`（连续失败≥5 跳过+60s 冷却），新增 `_breaker()`/`source_health()`
  - `skills/quant-daily/scripts/config/settings.py`：B1 新增 `LLM_PROFILE_MAP`（7 角色：technical0.1/zhengzhen0.4/zhensi0.4/judge0.0/trading_plan0.5/risk0.2/coherence0.0，均 deepseek-v4-flash + cache_ttl 86400）+ `LLM_TOKEN_BUDGET`
  - `scripts/run_debate.py`：B1 注入 `_load_llm_profiles()` + B2 预算 + B3 缓存(`--no-cache`) + C2 报告 + A2 阶段隔离 + B4 `_emit_repair_plan()` + `repair` 子命令
  - `skills/quant-daily/scripts/scan_all.py`：C2 RunReporter 接入（set n_signals/n_symbols + mark_phase + flush + 写 JSON 失败记 error）
  - `skills/fdt-spawn-debate/SKILL.md`：A3 新增「辩论缺员降级与 LLM 工程化」段（degrade-on-failure + B1 约定层说明）
  - `scripts/llm/__init__.py`：空包声明（scripts.llm 可导入）
- **验证**：py_compile 12 文件全过；修正版自测 24 项全 PASS（A1 状态机 / B2 超 daily 中止 / B3 缓存读写清 / C2 报告落地 / C3 健康告警 rc=1 + 无报告跳过 rc=0 / settings 7 角色 / run_debate 钩子 / multi_source_adapter+scan_all 接入）
- **行为回归待复核**：验证器/P0-4 逻辑零改动，下次全量实时盘前扫盘对比 09:10 那次 42 伪突破拦截数应不变
- **索引**：MEMORY.md 评估基线段标「已落地」；`evaluation_production_readiness_20260714.md` §3/§4 更新落地状态

---

## 2026-07-14 11:16 — FDT 工作文档归位（存储铁律落地）

- **触发**：掌柜确立铁律——FDT 所有工作文档须存于 FDT 专家包目录，不得散落工作空间
- **动作**：将 9 份 FDT 工作文档从两处误存位置统一迁入 `docs/design/`：
  - 自动化输出目录 `D:\WorkBuddy\FDT\.workbuddy\automations\automation-1783403060853\`（4 份）：`production_hardening_ABC_plan.md` / `signal_paradigm_validator_framework.md` / `validator_framework_landed.md` / `validator_skeleton_diff.md`
  - 工作空间 `D:\WorkBuddy\FDT\design\`（5 份）：`channel_breakout_signal_logic.md` / `2026-07-11_FDT_self_optimization_enhancement.md` / `2026-07-12_futures_data_collector_skill_design.md` / `2026-07-12_futures_data_core_refactoring_plan.md` / `fdc_README.md`
- **结果**：自动化目录仅余框架必需的 `memory.md`；工作空间 `design/` 已清空；`docs/design/` 现含 9 份 FDT 设计文档
- **索引**：MEMORY.md 新增「FDT 工作文档一律存于 FDT 专家包目录」铁律段（落点 `docs/design/`）

---

## 2026-07-14 11:04 — 系统生产就绪度评估基线记录

- **文件**：`memory/evaluation_production_readiness_20260714.md`（七维评分表 + 画像解读 + 弱项整改映射）
- **综合均分 6.29**：强项 期货垂直业务适配 9.0 / 数据层 8.5 / 落地闭环 8.5；中项 架构分层 7.5；弱项 LLM 调用工程化 4.5 / 并发容错降级 4.0 / 服务化监控运维 2.0
- **画像**：强研究原型 / 弱生产基建；弱项=纯工程化基建，与信号逻辑无关
- **整改映射（未实施）**：A 并发容错降级 ★★★、B LLM 调用工程化 ★★★（同批护核心辩论链路）、C 服务化监控运维 ★★（第二批，复用 WorkBuddy automation 调度）
- **索引**：MEMORY.md 新增「系统生产就绪度评估基线」段

---

## 2026-07-14 10:44 — 信号范式↔验证器 声明式框架落地（可插板 + 主流因子）

- **架构**：确立 `signal_type → [validator_ids]` 声明式映射（`config/settings.py.SIGNAL_VALIDATOR_MAP`），验证层从"唯一硬编码 P0-4 门禁"升级为"可插板验证器库 + 范式包"
- **新增 `signals/validators/`**：`__init__.py`(VALIDATOR_REGISTRY + run_signal_validators 编排) / `base.py`(ValidationContext + demote) / `p0_4_raw_kline.py`(V1, 从 scan_all._revalidate_breakouts 逐字迁移) / `volume_confirm.py`(V2 量比) / `atr_vol_timing.py`(V3 ATR%) / `trend_direction.py`(V4 高周期方向零参数) / `entity_quality.py`(V5 实体比) / `stability.py`(V6, 从 validate_signals 迁移) / `crowding.py`(V7, 从 validate_signals 迁移)
- **新增 `signals/paradigms/`**：`__init__.py`(PARADIGM_REGISTRY) / `breakout.py`(P1 通道突破，登记既有 ChannelBreakoutStrategy) / `mean_reversion.py`(P3 骨架) / `regression.py`(P4 骨架)
- **`config/settings.py`**：新增 `SIGNAL_VALIDATOR_MAP`（channel_breakout/trend_confirmation/bb_squeeze_prebreakout/near_breakout/minor_signal + __global__）
- **`scan_all.py`**：删硬编码 `_revalidate_breakouts`（原 L142-201）；调用改为 `run_signal_validators(summary["all_ranked"], ValidationContext)`，旧 `validate_all` 调用折入 V6/V7 + `__global__`
- **`validate_signals.py`**：标 DEPRECATED（逻辑已迁至 signals/validators/），保留兼容壳
- **因子约束**：全部验证器仅用公开主流因子（Donchian/Bollinger/ATR/Volume/MA/实体比），无黑盒新因子
- **验证**：py_compile 全过；合成数据自测 V1 真拦伪突破(FAKE→false_breakout/NOISE)、保留真突破(TEST channel_breakout 不变)；注册表 7 验证器 + 3 范式齐全；生产等效路径(sys.path 含 root+scripts)导入无 debate_engine 副作用
- **行为回归**：P0-4 拦截逻辑逐字保留，09:10 扫描 42 伪突破拦截数不变（待全量实时扫描复核）；V2-V5 阈值保守（量比 0.8 / ATR% 0.5 / 趋势方向未预计算跳过 / 实体比 0.3），不误伤真实突破

---

## 2026-07-14 09:41 — early_signal.py 去重 + 定位为独立旁路预警库

- **文件**：`skills/quant-daily/scripts/signals/early_signal.py`（917→812 行）
- **去重**：外科手术收掉与主链路重复的「两份定义」——`detect_price_breakout()`（独立 20 周期 Donchian，与 channel_breakout_strategy DC20 重复）、`detect_oi_triangle()` 内 `is_true/false_breakout` 分支（与 scan_all P0-4 伪突破门禁重复）
- **保留**：放量异动 / ATR 收缩→扩张 / OI 变化+量价背离 / 5 周期动量 / 均线收敛 / OI 三角建仓胚 / 基差 / 期限结构 / 跨期 Spread + `inject_early_signals_to_tech` 注入接口
- **定位**：掌柜 2026-07-14 确认保留为**独立旁路预警库**，不挂主扫描链路（scan_all 不调用、strategy 不调用），不参与评分打分
- **验证**：grep 零残留引用；py_compile SYNTAX_OK

---

## 2026-07-13 23:40 — v2.3 评分权重调整（DC20/BB 突破成为独立触发信号）

- **文件**：`skills/quant-daily/scripts/config/settings.py`
- **DC20**：break_base_score 30→40，break_strong_bonus 10→15，break_moderate_bonus 5→8，near_breakout_score 15→22，near_breakout_ticks 5→7
- **BB**：pos_extreme_score 6→20，pos_upper_score 4→15，pos_lower_score -4→-15，pos_extreme_lower_score -6→-20
- **动机**：原评分体系 DC20/BB 突破权重过低，只有行情走远后才达辩论门槛；调整后单凭 DC20 突破+逼近即可达 62 分(STRONG)，使刚突破品种及时进辩论
- **P0-4 伪突破门禁不变**：false_breakout 不会被绕过

---

## 2026-07-11 20:52 — 版本发布 v5.12.0 + 周期发现层

- **版本号**：`pyproject.toml` 5.11.0 → **5.12.0**（唯一真相源，`get_fdt_version()` 运行时读取）；`.version_history.json` 追加 v5.12.0 条目；`team-lead.md` frontmatter/正文版本 `5.10.0`→`5.12.0`（补 5.11.0 遗漏）。
- **周期发现引擎**：新增 `skills/quant-daily/scripts/signals/period_fitness.py`（discover() 纯函数 + build_period_fitness() 批量产出 `period_fitness_{date}.json`），零硬编码、全参数化；`config/settings.py` 新增 `PERIOD_REGISTRY`（{daily,240m,120m,60m,30m} 单一真相源）、`enabled_periods()`/`period_meta()`/`PERIOD_FITNESS_WEIGHTS`/`EXEC_STYLE_MAP`。
- **编排接入**：`daily_debate.py` 对候选品种算周期发现并写入 `debate_trigger.json.period_fitness_path`；`debate_brief.build_signal_summary` 注入 `period_context`；`hourly_debate.py` 读 `HOURLY_PERIOD`。
- **决策层消费**：`futures-judge.md`/`futures-trading-strategist.md`/`futures-risk-manager.md` 各新增「周期发现消费」段（best_period/exec_style/gap_risk 与方向正交、非硬指令、缺失降级日线）。
- **验证**：Demo 用合成 cu/lc 数据验证 discover() —— cu→daily(限价单)、lc→60m(次根市价)、无信号优雅降级 has_signal=False；py_compile 通过。

---

## 2026-07-11 19:08 — 版本发布 v5.11.0 + GitHub 推送

- **版本号**：`pyproject.toml` 5.10.0 → **5.11.0**（唯一真相源，`get_fdt_version()` 运行时读取=5.11.0 已验证对齐）；`.version_history.json` 追加 v5.11.0 条目。
- **README.md**：标题/版本说明更新至 v5.11.0 + 新增「一键辩论驱动（run_debate.py）」章节（plan/assemble/extract/report 用法 + data_benchmark 约定）。
- **文档**：`docs/optimization/fdt_debate_redesign_20260711.md` 状态由"设计稿"标为"✅已实施并验证通过"。
- **GitHub**：`sync_experts_to_github.py` 推送 `futures-debate-team/` 全目录 → CTAAgents/experts (main)，Commit `dd245c6`（含 v5.11.0 + 上一轮 zn/rm 知识萃取产物）。

---

## 2026-07-11 19:05 — 辩论流水线 redesign 实施（B/D/E/G/C/F 全落地）

| 模块 | 文件 | 关键变更 |
|------|------|----------|
| 新增 B | `scripts/run_debate.py` | 主动驱动层：识别触发品种(经 importlib 按路径读 quant-daily `config/settings.py:DEBATE_ENTRY_MIN_ABS`，不写死)、产出标准化 spawn 计划 JSON(含 ADX角色反转/WATCH语义/置信度归一 固定注入)、`assemble`(读 p4/p5→per_pid debate_results.json 含 data_benchmark)/`extract`(批量)/`report`(phase3 --debate) 子命令 |
| 修改 D | `scripts/extract_knowledge.py` | 增 `ingest_from --from debate_results.json` 批量模式；复用 `extract_from_debate` 内置 conf<0.6 质量门控自动跳过；字符串 bull_args/bear_args 归一成 dict |
| 修改 E | `skills/quant-daily/scripts/strategies/channel_breakout_strategy.py` | 量能确认前置：仅 `vol_ratio >= normal_lower_ratio`(已存在=0.8) 才授 DC20 break_base 分，否则记 `weak_no_vol` 不授 base（压低无量伪突破直达 STRONG/WATCH 比例）|
| 修改 G | `skills/futures-trading-analysis/scripts/phase3_generate_report.py` | ① 顶层捕获 `DATA_BENCHMARK`(adapt 重铸前从原始 debate_results.json 取，否则 per_pid 丢失) 并渲染「数据基准」；② `adapt_debate_results` 兼容 reasoning 顶层与嵌套 judge_verdict.reasoning 两种格式；③ `--debate` 子集模式不再硬依赖全量 intermediate_data.json（缺则 intermediate={}，去掉误 sys.exit(1)) |
| 修改 C | `skills/futures-trading-analysis/SKILL.md` | 报告指引统一为 `phase3_generate_report.py --debate debate_results.json`（单/多品种通用，禁止改回手写 HTML）|
| 修改 F | `skills/fdt-spawn-debate/SKILL.md` | 澄清 confidence：0-1 数值 或 高/中/低 标签均可（confidence_utils 归一化，标签非非法）|
| **发现** | 架构漂移 | `DEBATE_ENTRY_MIN_ABS` 真实位置在 `skills/quant-daily/scripts/config/settings.py:330`，FDT 根 `config/settings.py` **不存在**（根 config/ 仅 schema.py+team_config.json）；run_debate.py 经 importlib 按路径加载该常量(读真相源、不写死) |
| **验证** | — | py_compile 4 文件通过；B 生成 6 品种 spawn 计划；D 批量萃取 ZN/RM 入库、J/JD 因 conf0.52<0.6 跳过；G 报告渲染「数据基准 2026-07-10 15:00 收盘」且子集无 intermediate 也能出报告 |

**验证**：4 文件 py_compile 通过；B/D/G 端到端跑通；E 编译通过(全量重扫待实时数据)。

## 2026-07-11 18:15 — v5.10.0 信号体系统一与能力裁剪（文档/版本/推送）

| 模块 | 版本 | 关键变更 |
|------|------|----------|
| FDT系统 | **5.10.0** | 辩论入口阈值统一 DEBATE_ENTRY_MIN_ABS=20（单一真相源）+ 移除120m监控/优化 + 删除盘前预计算缓存 |
| pyproject.toml | 5.9.0→5.10.0 | 版本真相源 bump + description 追加 v5.10 |
| team-lead agent | 5.9.0→5.10.0 | frontmatter + 正文"当前统一版本"同步 bump |
| README.md | 🆕 v5.10章节 | 标题/闸门描述(无STRONG→DEBATE_ENTRY_MIN_ABS) + v5.10能力章节 |
| futures-trading-analysis SKILL | 3.8.0文档修正 | v3.8.0 changelog 去盘前缓存卖点；"预计算缓存路由"章节→"P1实时全量扫描" |
| quant-daily README | 标注 | 120m 监控自动化已废弃（scan_all 仍支持手动 --period 120m） |
| docs | 标注废弃 | latency-optimization(盘前缓存)/wf-universe(120m监测) 加 ⚠️ 已废弃 |
| 代码清理 | — | 删 scripts/precompute_cache.py + cache/precompute_20260711.json（死缓存收尾） |
| 同步 | ✅ | sync_experts_to_github.py → CTAAgents/experts(main) commit 2ecbc14 |

## 2026-07-10 21:15 — v5.8.0 系统架构里程碑

| 模块 | 版本 | 关键变更 |
|------|------|----------|
| FDT系统 | **5.8.0** | 自包含运行时代理+路径真相源 |
| fdt_paths | 🆕 **1.0** | 单一路径真相源，三级fallback自动检测FDT根目录 |
| memory_enforcer | 🆕 **1.0** | 零参数记忆归档+工作空间日志校验+辩论完成后强制运行 |
| futures-trading-analysis | **3.7.0→3.7.1** | A01文件通信协议+changelog |
| fdt-spawn-debate | **1.0→1.1** | 规则10(A01)+自动化环境处理+tiered降级+6个spawn prompt更新 |
| team-lead agent | **5.2.1→5.3.0** | 记忆路由从参考表→开篇动作清单+自检步骤 |
| 目录结构 | 🆕 | `data/` + `reports/` FDT内部产出目录 |
| A01铁律 | 🆕 | 文件优先通信—Agent只Write不使用SendMessage |
| tiered降级 | 🆕 | 链证/观澜/探源600s→裁决/策执/风控300s |

**事故修复**: 自动化context中SendMessage路由失效(16:25+20:10两次)→A01文件优先通信永久修复。
**架构原则**: FDT产出和记忆在FDT内部，工作空间仅做镜像副本。

---

## 2026-07-10 11:06 — 今日版本汇总

| 模块 | 版本 | 关键变更 |
|------|------|----------|
| quant-daily | **2.14.0** | ADX从通道突破评分移除 |
| scan_all | **2.20.0** | ADX移除+TDX对齐+会话感知 |
| channel_breakout_strategy | **1.3** | TDX REF式+HIGH/LOW+动量识别+ADX移除 |
| multi_source_adapter | **2.13.0** | R0归一化+TqSDK盘中优先 |
| 120m_resampler | **同步v1.3** | 会话感知resample+ADX移除 |
| settings | **2.15** | ADX段deprecated |
| futures-trading-analysis | **3.7.0** | 辩论自动归档+Agent轮询+报告CLI |
| debate_archiver | 🆕 **1.0** | 辩论自动归档到FDT memory |
| agent_waiter | 🆕 **1.0** | S04 Agent产出轮询等待 |
| session_rules.md | 🆕 | 子周期K线会话划分规则 |
| R0 | 🆕 | 子周期以通达信/文华/博易为准 |
| R25 | 🔄 | TqSDK子周期归一化后使用 |
| R26 | 🆕 | 所有OHLCV消费者须会话感知 |

---

## 2026-07-10 11:05 — channel_breakout v1.3 ADX从评分移除

**版本号**: channel_breakout_strategy v1.3, 120m_resampler同步

**根因**: ADX是趋势跟踪指标, 用于过滤突破策略信号属范式错配。突破信号不需要趋势强度的配合——最佳突破往往发生在ADX低位（盘整被打破）, ADX高位突破更可能是衰竭。专家团v5.2 prompt要求的"ADX低位鼓励/高位警示"与代码实际行为完全相反。

**修改**:
- `channel_breakout_strategy.py`: 移除4处ADX scoring (2处up-break + 2处strategy_tdx_ref)
- `120m_resampler.py`: 移除2处ADX scoring  
- `config/settings.py`: ADX段标记deprecated, exhaustion_penalty/trend_bonus置0
- ADX保留为display-only指标, `adx_signal`字段改为`info_only`

**影响**: SN -3分(56→53,仍STRONG); SP/RM/FG不变。factor_timing策略中ADX保留(该策略为趋势跟踪, 适用)。

---

## 2026-07-10 10:52 — v3.7.0 三大系统性缺陷修复

**版本号**: futures-trading-analysis v3.7.0

**修复1: 辩论自动归档** (`scripts/debate_archiver.py`)
- `archive_round()`: 辩论完成后自动写入FDT `memory/debate_journal.json` + `memory/debates/INDEX.md`
- 解决: 每次辩论记忆手动写入工作空间memory的问题

**修复2: Agent产出轮询** (`scripts/agent_waiter.py`)
- `poll_file_ready()`: S04轮询等待Agent产出文件就绪(15s×60=15min超时)
- `build_spawn_file_instruction()`: 生成Agent文件输出指令,追加到spawn prompt
- 解决: background Agent超时无产出

**根因分析**:
| 问题 | 根因 | 性质 |
|------|------|------|
| 胶水代码 | 协调员未使用已有的CLI参数化报告生成器 | 使用缺陷 |
| 记忆不归档 | FDT缺乏辩论完成后的自动归档钩子 | 设计缺陷 |
| Agent超时 | 依赖不可靠的background+SendMessage, 无S04轮询 | 实现缺陷 |

---

## 2026-07-10 10:15 — v2.13.0 子周期TDX对齐+会话感知+R0归一化

**版本号**: quant-daily v2.13.0, scan_all v2.19.0, multi_source_adapter v2.13.0, channel_breakout v1.2

**新规则**:
- **R0**: 子周期K线切片以通达信/文华/博易为标准，不一致→转换
- **R25**: TqSDK子周期需经R0归一化后使用（盘中优先，盘后兜底）
- **R26**: 所有OHLCV消费者（技术分析/指标/回测/策略）必须使用会话感知K线

**DC20 TDX对齐**（`channel_breakout_strategy.py` v1.2）:
- REF式通道: `max(highs[-21:-1])` 不含当前bar（原含当前bar→通道随价格膨胀）
- HIGH/LOW检测: `c_high >= dc20_upper` 替代原 `close > dc20_upper`
- 动量逼近识别: bar振幅≥1.2×ATR + 距边界≤2×near_ticks → near_breakout分
- Strategy层兜底: 上游未填充dc20_break时直接REF式检测+评分

**会话感知resample**（`120m_resampler.py`, `optimizer/run_120m_wf.py`）:
- gap>120min检测会话边界，会话内两两合并
- 覆盖全部品种类型: 23:00/01:00/02:30收盘/无夜盘

**降级链优化**（`multi_source_adapter.py` v2.13.0）:
- 盘中: TDX → TqSDK(归一化) → AKShare → 东方财富
- 盘后: TDX → AKShare → 东方财富 → TqSDK(归一化)
- `normalize_sub_period_bars()` 归一化守卫

**FDT记忆固化**:
- 新建 `memory/session_rules.md`
- 更新 `memory/data_sources.md` (R0/R25/R26)
- 更新 `memory/incidents.md`

**SP评分轨迹**: +28 WEAK → +43 WATCH(动量) → +63 STRONG(TDX对齐)

---

## 2026-07-07 20:00 — v5.4.0 可观测性与自改进

**版本号同步**：pyproject.toml / .codebuddy-plugin/plugin.json / .version_history.json / README.md 统一升至 **5.4.0**。

**新能力（向后兼容）**：
- APM-CS 五轴评分卡（D1–D5）+ Telescope 失败模式聚类，周一自动触发（`scheduler/triggers.py`、`scripts/cluster_failures.py`、`scripts/apm_scorecard.py`）
- D1/D3/ViBench 回放落地：`futures-judge-heldout.md` + `memory_writer.append_debate_record` + `scripts/replay_harness.py`（held-out 一致性裁判，非阻断审计）
- D2 Acuity 真实计算 + 成本感知 PnL（`validate_verdicts.py` COST_BPS=2.0）
- D4 纪律钳制 `scripts/enforce_discipline.py`（R13/R14/R-resonance 仓位上限强制）
- D2 信号退化标记 / D5 陈旧失败过滤 / Stage3 `scripts/self_improve.py` 脚手架
- 全周期 K 线支持（日/周/月/240m/60m/15m/5m/1m + 自定义周期，period 透传）

**Bug 修复**：LH2609 MA60 真实合约口径（channel_breakout `_split_symbol_contract`）、`scan_all.py` 原子写入（`_atomic_write`）、`portfolio_backtest.py` 裸 except、RuleChecker 浮点边界（1e-6）、`triggers.py` DataTrigger `run_cmd` 闭包

**质量门禁**：今日 `/loop` 审计 5 门禁全 100%（G1-G4=100%，G5 修复后 134/134）

---

## 2026-07-06 22:25 — v5.2 架构重构

**架构重构**:
- 三类信号(突破/回踩/跳空)替代L1-L4+因子择时作为主信号源
- 所有三类信号品种必须辩论，无直接推荐通道
- ADX角色反转：低位(launch阶段)鼓励参与，高位(ADX>50/60)警示风险
- V型反转时ADX>60警示不适用（特殊例外）
- 证真/慎思改为动态正反方，不再固定多/空方
- 研究员数据接口独立：L1-L4→technical-analysis(data_interface)，因子→fundamental-data-collector(data_interface)
- quant-daily仅保留three_signal一个默认策略
- 技术债务记录于 memory/technical_debt.md

**记忆系统更新**:
- agent_profiles.json → v5.2，辩手角色改为动态，研究员新增data_source字段
- argument_patterns.md → 引用三类信号替代quant-daily双策略
- debater_profiles.md → 备注动态正反方变更
- judgment_revisions.md → 新增R11-R18（ADX规则+V型反转）
- changelog.md → 本条目

**文件改动**:
- `scripts/validate_verdicts.py` — 新增 `save_feedback_entries()`，验证后自动写 `feedback_entries.json`（匹配 risk_engine 的 `build_feedback_entry` 格式），对接 `aggregate_feedback` 的假破统计
- `skills/quant-daily/scripts/signals/debate_brief.py` — 五维权重改为从 `memory/debate_weights.json` 动态加载，`compute_debate_score` 新增 `weights` 参数，评分逻辑改为按权重百分比计算
- `memory/debate_weights.json` — 创建默认权重文件（40/25/20/10/5），供 evolve_agents 调节
- `scripts/evolve_agents.py` — 新增 `evolve_debate_weights()`，按各维度得分与 correct 的相关性调整权重→写回 `debate_weights.json`。加入主循环，名"训辩权重"

---

## 2026-07-06 19:57 — risk_engine BUG修复 + debate_brief硬编码修复

**文件改动**:
- `skills/debate-risk-manager/scripts/risk_engine.py`
  - BUG-1: `calc_transaction_cost` 定义两次→重名覆盖→摩擦降仓静默失效。删除重复定义，重命名统一为 `calc_friction_entry`，修复 `calculate_position` 调用签名
  - BUG-2: `_pattern_risk_override` 中 `return 0.7` 后紧跟 `return 1.0` 死代码。修复为正常控制流

- `skills/quant-daily/scripts/signals/debate_brief.py`
  - chain_score: 从硬编码集 → 按链内品种数动态计算（≤3=3分, ≥4=4分, ≥6=5分）
  - base_confidence: 修复 `f_conf` 可能0-100溢出被cap的问题，归一化到0-1
  - ATR fallback: 从通用2% → 按价格区间分级（≤5000≈3%, 中价2%, ≥50000≈1.5%）
  - `compute_debate_score` 新增 `chain_count` 参数

---

## 2026-07-06 19:51 — FDT机制层问题修复（对照审计清单）

### 背景
掌柜提交9条FDT机制层问题清单（P0×2, P1×2, P2×5），逐条源码验证后确认8条，1条待核实→升级为实际BUG。

### 文件改动

**`scripts/validate_verdicts.py`** (P0/P1根修复)
- 数据获取从单点close → K线序列（8根日K线）
- 验证逻辑从"收盘价判方向"→"bar high/low检测stop/target触发"
- 新增：跳空扫损检测(`gap_stop`)、真实实现盈亏(`realized_pnl_pct`)
- 旧版验证保留为降级路径

**`pipeline/runner.py`** (P2数据流缺口修复)
- `step_record_history` 末尾追加 `record_verdicts.py` 调用
- 查找 REPORT_DIR 下的 `debate_results.json` 同步到 `execution_followup.json`
- 从此 `evolve_agents.py` 能读到数据，自进化闭环接通

**`scripts/evolve_agents.py`** (P0/P1进化指标修复)
- `get_validated_verdicts` 提取 `hit_stop`/`hit_target`/`realized_pnl_pct`
- `evolve_risk_manager`：用真实止损触发率替代 `avg_stop_dist` 代理
- `evolve_strategist`：用真实T1达标率替代 `change_pct>3%` 代理
- 所有Agent改用 `realized_pnl_pct` 替代方向振幅 `pnl_pct`

### 影响范围
| 问题 | 等级 | 状态 |
|:-----|:----:|:-----|
| 验证标签与止损脱节 | P0 | 已修复：K线序列 stop/target检测 |
| 自进化优化方向而非盈亏 | P0 | 已修复：所有Agent改用 realized_pnl_pct |
| 风控参数进化代理指标失真 | P1 | 已修复：真实 stop_hit_rate |
| 验证窗口T+1收盘价 | P1 | 已修复：gap_stop 跳空检测 |
| LLM判LLM裁判循环 | P2 | 设计层局限，缓解措施足够 |
| 进化依赖间接代理 | P2 | 已修复：真实指标替代代理 |
| 无执行层 | P2 | 待修：摩擦成本未完全注入验证结果 |
| 数据流衔接缺口 | P2→**确认BUG** | 已修复：runner调record_verdicts |

---

## 2026-07-11 16:52 — FDT 机制修正：quant-daily 负向过滤 + 全量监控

**根因**：原 `daily_debate.py`/`hourly_debate.py` 信号门仅放行 `STRONG(≥50)`/`WATCH(≥40)`，使 quant-daily 异化为"硬排除门槛"，弱信号品种无法进入辩论，违背 FDT"quant-daily 仅输出信号与方向初始值、降低辩论压力"的设计初衷。掌柜裁定：quant-daily 应**筛掉不适宜辩论的品种（负向过滤）**，而非**筛入评分最高品种（正向选择）**；"适合交易"由下游 辩论→策略→风控→裁决 决定。

**改动文件**：
- `config/settings.py`：新增 `DEBATE_ENTRY_MIN_ABS = 1`（任意非零方向信号即进候选；如需噪音兜底可调 20）
- `daily_debate.py`：① `_load_daily_symbols()` 改取 monitoring_symbols.json 所有周期 symbol_list **并集**（全量 62 品种，含 lc/m/y/p/RM/SR 等原"无日线优化参数"大趋势品种）；② 信号门改为 `candidates = [s for s in all_ranked if abs(total) >= DEBATE_ENTRY_MIN_ABS]`，grade 仅作优先级标签
- `hourly_debate.py`：同步放松信号门（品种池保留 60m 21 品种）
- `fdt-spawn-debate/SKILL.md`：适用范围改为"全量监控 + 任意方向性信号进候选，评分仅作优先级"
- `signals/debate_brief.py`：`MIN_DIVERGENCE_SIGNAL` 30→0（弱分歧不再硬性排除）

**验证**：4 文件 py_compile 通过；`DAILY_SYMBOLS=62`（含 lc/m）；mock 测试确认 WEAK/NOISE 进候选、纯零(total=0)被负向过滤。两个 `--dry-run` 正常。

**备份**：`C:\Users\yangd\Documents\WorkBuddy\Claw\.workbuddy\backup_fdt_20260711_164721\`

---

## 2026-07-11 17:36 — 辩论入口阈值统一配置（单一真相源）+ 删除死代码

**根因（掌柜架构铁律）**：是否可辩论的阈值此前分散在多处（team-lead 写死 STRONG(abs>=60)、fdt-spawn-debate 写死 |total|≥1、L3 信号门写死 STRONG、settings.py 单值），且 signal_classifier.py 的 C4"跳过"是第三套无人执行的口径。掌柜裁定：阈值应统一配置、不分散；不适合辩论的品种不走辩论，需辩论的品种必须走完整流程匹配策略与风控。

**改动文件**：
- `config/settings.py`：`DEBATE_ENTRY_MIN_ABS = 1 → 20`（过滤 NOISE 级 |total|<20，仅 WEAK 及以上进辩论候选）；注释升级为"统一配置·单一真相源·禁止写死"
- `agents/futures-debate-team-team-lead.md`：信号检查闸门 prose 移除写死 STRONG(abs>=60)，改为读 `DEBATE_ENTRY_MIN_ABS`
- `skills/fdt-spawn-debate/SKILL.md`：阈值引用改为 `DEBATE_ENTRY_MIN_ABS`；新增"无候选→不 spawn 任何辩论 Agent，直接回报无信号"
- `docs/harness/04-resilience.md`：L3 信号门两处写死 `grade=="STRONG"(abs>=60)` 改为读 `DEBATE_ENTRY_MIN_ABS`（当前=20）
- 删除 `scripts/signal_classifier.py`（C4 死代码，未被任何模块 import，report.py 自带本地 `_classify_signal`）

**验证**：grep 全包无写死阈值残留（changelog 历史除外）；`DEBATE_ENTRY_MIN_ABS=20` 生效；删除后无 import 断裂。

---

## 2026-07-11 17:42 — 消除最后一处分散：离线 WF 回测优化器统一读 DEBATE_ENTRY_MIN_ABS

**根因（延续掌柜铁律）**：上一轮已统一 daily_debate/hourly_debate/team-lead/SKILL.md/L3信号门 + 删死代码，但离线 WF 回测优化器仍写死 `("STRONG","WATCH","WEAK")` 元组过滤 NOISE，与 `DEBATE_ENTRY_MIN_ABS` 不联动。掌柜"修"授权消除最后一处分散。

**改动文件**：
- `skills/quant-daily/scripts/optimizer/backtest_optimizer.py`：① import 加 `DEBATE_ENTRY_MIN_ABS`；② 3 处 `if grade not in ("STRONG","WATCH","WEAK"): continue` 改为 `if abs(total) < DEBATE_ENTRY_MIN_ABS: continue`（327 用 item["total"]，455/509 用 result_item["total"]）
- `skills/quant-daily/scripts/optimizer/run_120m_wf.py`：① import 加 `DEBATE_ENTRY_MIN_ABS`；② 2 处 `if res["grade"] not in ("STRONG","WATCH","WEAK"): continue` 改为 `if abs(res["total"]) < DEBATE_ENTRY_MIN_ABS: continue`（410/443）

**验证**：2 文件 py_compile 通过；grep 全包无任何 `("STRONG","WATCH","WEAK")` 写死元组残留（changelog 历史除外）；`DEBATE_ENTRY_MIN_ABS` 现被 6 文件统一引用（settings / daily_debate / hourly_debate / fdt-spawn-debate/SKILL.md / backtest_optimizer / run_120m_wf）。

**现状**：阈值全包单一真相源 = `config/settings.py:DEBATE_ENTRY_MIN_ABS`（当前=20，仅 WEAK 及以上进辩论候选）。日后调阈值只改一处。

---

## 2026-07-11 17:56 — 120m(2小时线)信号监控整体废弃：删自动化 + 删盘前缓存 + 参数自优化仅保留日线

**根因（掌柜决策）**：120分钟信号监控已无必要；盘前预计算缓存为"设计了但读取端从未接入"的死缓存（全包 grep 无 import，缓存目录恒空）；参数自优化里的2小时线分支同样废弃。掌柜"A方案 + 只保留日线优化"授权执行。

**删除的自动化任务（5个，均用 automation_update 软删）**：
- `automation-1783603689493` 120m信号-上午开盘9:15
- `automation-1783603695470` 120m信号-上午收盘11:15
- `automation-1783555974126` 120m信号监控-下午14:40
- `automation-1783603700956` 120m信号-夜盘开盘21:15
- `automation-1783723277478` FDT盘前预计算缓存刷新（死缓存，无读取端）

**改动文件（plugins/marketplaces/ 生产目录）**：
- `skills/quant-daily/scripts/optimizer/run.py`：`cmd_update_monitoring_config` 改仅日线——① 去掉 `from optimizer.run_120m_wf import ...`；② `TIER_THRESHOLDS` 推导 `("daily","120m")`→`("daily",)`；③ 删 `run_120m_wf()` 函数；④ `build_monitoring_config` 签名去 `results_120m`、去掉120m块产出与 `_comment` 的120m描述；⑤ 调用点去掉 `r120_rv`/`run_120m_wf()` 回填分支；⑥ `_light_load_results` 去掉 `per=="120m"` 死分支
- `skills/quant-daily/scripts/optimizer/backtest_optimizer.py`：① 删 `WF_CONFIG["tiers"]["120m"]`；② docstring `period: 'daily' | '120m'`→`'daily'`
- 删除 `skills/quant-daily/scripts/optimizer/run_120m_wf.py`（120m专用，删前 grep 确认全包无 import）
- `C:/Users/yangd/Documents/Signal/config/monitoring_symbols.json`：pop `120m` 块，仅留 `daily`（62品种）

**参数自优化自动化任务**：`automation-1783404492691` 改名"参数自优化 - 日线(每4周)"，prompt 修正路径（原 `<FDT>/scripts/optimizer/run.py` 缺 `quant-daily/scripts` 段，已修正为 `<FDT>/skills/quant-daily/scripts/optimizer/run.py`）+ 明确 `--period daily`、不含120m。

**验证**：run.py / backtest_optimizer.py py_compile 通过；grep 全包（除 changelog 历史）无功能性120m残留；monitoring_symbols.json 有效，顶层键 `[version, _comment, daily]`，daily 62品种；run_120m_wf.py 删除后全包无 import 断裂。
