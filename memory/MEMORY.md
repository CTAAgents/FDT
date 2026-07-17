# FDT 专家团长期记忆（MEMORY.md）

> 用户偏好、操作铁律、跨会话长期事实。系统设定预期的长期笔记文件。

## 🔴 用户铁律：FDT 操作一律记入 FDT 自身记忆系统（2026-07-14 确立）

- **规则**：凡对 FDT 专家团（代码 / 配置 / 记忆 / 辩论产物）的任何操作，必须写入 FDT 自身记忆系统
 （`plugins/.../futures-debate-team/memory/` 目录及 `agents/` 目录），**绝不**写入宿主工作空间
  `D:\WorkBuddy\FDT\.workbuddy\memory/`。
- **背景**：2026-07-14 掌柜明确纠正——此前 v2.3 权重调整、early_signal 去重等误记工作空间，违反
  系统「路径边界铁律」。FDT 是独立系统，脱离平台须能独立生存，记忆必须自包含。
- **落点对照**：
  - 代码变更 → `memory/changelog.md`
  - 用户偏好 / 长期事实 → 本文件（`MEMORY.md`）
  - 辩论执行 → `debate_journal.json` + `debates/INDEX.md`
  - 事故与教训 → `memory/incidents.md`
  - 裁决修正 → `memory/judgment_revisions.md`
  - 风控政策 → `memory/policies/veto_policies.md`

## 🔴 用户铁律（续）：FDT 工作文档一律存于 FDT 专家包目录（2026-07-14 确立）

- **规则**：凡 FDT 的**设计文档 / diff 对比报告 / 实施方案 / 架构说明 / 研究笔记**等「工作文档」，必须存放在 FDT 专家包自身目录下，**绝不**散落在宿主工作空间的 `.workbuddy/automations/` 输出目录或工作空间 `design/` 等位置。
- **落点对照（工作文档）**：
  - 设计 / 架构 / diff / 实施方案 → `docs/design/`
  - 研究笔记 / 评估基线 / 技术债务 → `memory/knowledge/` 或 `memory/`
  - 代码 / 配置变更 → 本文件索引 + 实际代码位置（`changelog.md` 详记）
- **背景**：2026-07-14 掌柜纠正——此前 A+B+C 加固方案、信号范式↔验证器框架、P0-4 脚手架 diff、落地总结等误存于 `D:\WorkBuddy\FDT\.workbuddy\automations\automation-1783403060853\`；`channel_breakout_signal_logic.md` 等误存于 `D:\WorkBuddy\FDT\design\`。已全部迁至 `docs/design/`。
- **术语澄清（2026-07-14 掌柜确认）**：掌柜口中的"工作空间记忆系统"＝**FDT 自身 `memory/`**（FDT 是独立系统，记忆须自包含）。规范文档落 `FDT根 + FDT/memory/`，**不**写入宿主 `D:\WorkBuddy\FDT\.workbuddy\memory/`。此理解已获掌柜明确背书。

## 📘 项目规范文档（2026-07-14 落地）

- **定位**：FDT 项目代码风格与开发规范、AI 编码行为准则的权威源，面向所有开发者（人类+AI）。
- **根目录文件（canonical）**：
  - `CLAUDE.md`（项目根）：AI 编码行为准则——先思考再编码 / 简单优先 / 外科手术式修改 / 目标驱动执行（四原则权威源，复制自 `C:\Users\yangd\Desktop\CLAUDE.md`）
  - `CODING_STANDARDS.md`（项目根）：代码风格与开发规范 v0.1.0（Ruff 检查 / isort 导入排序 / Google docstring / 类型提示 / 中文注释 / 命名约定 / 具体异常 / 行宽 120）
- **配套**：AI 行为准则完整版由 `~/.workbuddy/skills/claude-md-guidelines/SKILL.md` 统一管理（CLAUDE.md 引用，不重复）
- **Ruff 现状**：`pyproject.toml [tool.ruff]` 已配 `line-length=120` + `select=["E","F","I","N","W"]`（含 isort `I`），与规范一致
- **遵守**：凡 FDT 开发须先读这两份根文件；新建/修改代码须过 `ruff check --fix` + `ruff format`

## 🟡 v2.3 评分权重调整（2026-07-13 23:40）

DC20 突破、BB 突破均为辩论入口的独立触发信号，权重显著提升：
- **DC20**：break_base_score 30→40，break_strong_bonus 10→15，break_moderate_bonus 5→8
- **DC20 逼近**：near_breakout_score 15→22，near_breakout_ticks 5→7
- **BB 突破**：pos_extreme_score 6→20，pos_upper_score 4→15
- **BB 下轨**：pos_lower_score -4→-15，pos_extreme_lower_score -6→-20
- P0-4 伪突破门禁不变，false_breakout 不会被绕过

## 🔧 early_signal.py 定位（2026-07-14 厘清 + 掌柜确认）

- `signals/early_signal.py` 为**独立旁路预警库**（不挂主扫描链路），仅作早期预警维度可选数据源
- 突破判定单一真相源 = `channel_breakout_strategy.py`；伪突破校验单一真相源 = `scan_all.py` 的 P0-4 门禁
- 已收掉 `detect_price_breakout()` 与 `detect_oi_triangle()` 的 true/false breakout 分支（两份重复定义）
- 保留：放量 / OI / 动量 / 收敛 / 基差 / 期限结构 / Spread 等期货专属早期维度 + `inject_early_signals_to_tech` 注入接口
- 去重后 812 行版本即终态（掌柜 2026-07-14 确认保留为独立旁路预警库）

## 📚 信号因子研究笔记索引

- `memory/knowledge/breakout_factor_research.md` — 通道突破与伪突破过滤在期货上的实证表现 + 过滤器优先级（基于 breakoutos 2500+ 策略研究 + 国内期货圈共识，2026-07-14）。核心结论：期货上只做结构型/零参数过滤（趋势方向 ADX、ATR 幅度、波动率择时、成交量），拒绝 RSI 等阈值优化型（过拟合陷阱）；P0-4 门禁缺口优先级 D(ADX) > B(ATR幅度) > A(close_position) > C/E。

## 📊 系统生产就绪度评估基线（2026-07-14）

- 七维综合均分 **6.29**：强项（≥8）期货垂直业务适配 9.0 / 数据层 8.5 / 落地闭环 8.5；中项（7.5）架构分层；弱项（<5）LLM 调用工程化 4.5 / 并发容错降级 4.0 / 服务化监控运维 2.0。
- 画像：**强研究原型 / 弱生产基建**。护城河在强项三轴，弱项是"把护城河跑稳跑久跑可观测"的管道。
- 弱项整改映射（✅ **已落地 A+B+C 全上，2026-07-14**）：A 并发容错降级（熔断+阶段隔离+缺员降级）★★★、B LLM 调用工程化（角色档案+Token预算+辩论缓存+失败重排）★★★、C 服务化监控运维（统一CLI+运行报告+健康钩子+日志镜像）★★。12 文件（6 新+6 改），零信号逻辑改动，自测 24 项全 PASS。
- 详表与落地状态见 `memory/evaluation_production_readiness_20260714.md` 及 `docs/design/production_hardening_ABC_plan.md`。

## 🏗️ 信号层架构原则

- **信号范式 ↔ 专属验证器**（2026-07-14 确立，2026-07-14 已落地，详见 `memory/technical_debt.md` §5）：信号计算与验证器范式专属配对（`signal_type → [validator_ids]` 声明式映射，单一真相源 = `config/settings.py.SIGNAL_VALIDATOR_MAP`），**非通用验证器验证所有信号**。已建可插板验证器库 `signals/validators/`（7 验证器 V1-V7，全用公开主流因子）+ 范式包 `signals/paradigms/`（P1 已登记 / P3 P4 骨架）；`scan_all.py` 已改为按映射路由。

## 🐍 Agent 统一输出入口 — 方案D（2026-07-14 落地）

- **新增** `scripts/agent_output.py`：`write(phase, symbol, params, workspace)` 统一输出函数，含 schema 校验（字段类型/枚举/范围），`json.dump` 序列化（从源头消灭 F05 JSON 引号冲突）
- **修改** `scripts/run_debate.py`：`build_spawn_plan()` 中所有 agent prompt 从内嵌 JSON schema 文本改为 `agent_output.write()` Python 调用代码（字段名和类型骨架预填，Agent 只填 value）
- **消除的问题**：```BULL```/```MEDIUM``` 等非法枚举值被 schema 校验拦截在写文件前；str/dict/float 类型不匹配在写入时 exit(1) 而非事后 L1 校验失败
- **保留** `scripts/validate_agent_output.py`（L1 校验器仍可用于事后复核，但 agent_output.write() 已在写入时完成等价校验）

---
以下内容从 WorkBuddy 工作空间记忆同步（2026-07-16）

# FDT 工作空间长期记忆

## 🔴 FDT 独立 Agent 系统定位（2026-07-16 确立，优先级最高）

**FDT 的发展方向是一个独立的 Agent 系统，未来不依赖 WorkBuddy 即可独立运行。**
目前寄生在 WorkBuddy 中是过渡形态的权宜之计。

### 所有决策必须遵守的准则

| 维度 | 应该做 | 不应该做 |
|:-----|:-------|:---------|
| 代码 | 把逻辑写进 FDT 源码（`.py` + `docs/`） | 依赖 WorkBuddy 的用户级/项目级 Skill |
| CLI | 通过 `fdt_cli.py` 子命令暴露能力 | 依赖 WorkBuddy 的工具链或加载机制 |
| 配置 | FDT 内部的 `config/` + `settings.py` | 依赖 WorkBuddy 的 `.workbuddy/` 配置 |
| 记忆 | FDT 内部的 `memory/` 目录 | 依赖 WorkBuddy 的工作空间记忆 |
| Agent | 逐步建立独立的 Agent 调度层 | 长期依赖 WorkBuddy 的 spawn 机制 |

### 已完成的去绑定工作
- 2026-07-16: 自检逻辑代码化 → `scripts/self_check.py` + `fdt_cli.py self-check`
- 2026-07-16: 技术指标计算迁入 → `skills/quant-daily/scripts/indicators/`
- 2026-07-16: 清理所有 FDT 相关 WorkBuddy Skill（6 个已删除）
- 2026-07-16: 路径归一化直接写在 `fdt_cli.py._normalize_path()` 中

## 🟢 自检逻辑代码化铁律（2026-07-16 确立）
所有 FDT 系统的 pre-flight 检查、故障修复逻辑必须写在 FDT 代码内（`scripts/self_check.py` + `fdt_cli.py` 自动校验），**禁止**以 WorkBuddy Skill（SKILL.md）形式存放。
- 原因：Skill 绑定到特定 WorkBuddy 工作空间，换空间就丢失；代码化后随 FDT 源码一起迁移
- 已代码化内容：路径归一化、扫描文件检查、ADX 规则注入验证、F01-F10 全部 10 项故障模式
- 调用方式：`python fdt_cli.py self-check` 或 pipeline 模式自动触发

## 🔴 去融合铁律（G41，2026-07-16 确立，优先级仅次于 Harness 铁律）

**不同策略哲学、甚至同策略内子信号均不得融合**。每个子策略信号必须独立产出、独立送辩论层裁决。融合思想本身错误。

**实现规则**：
- `StrategyFusion` 已废弃（Phase 3 直接 flatten，`fusion_method=no_fusion`）
- `mean_reversion.rsi/.cci/.bb` 各独立 `ScoredSignal`，不投票不坍缩
- `trend_following.dc20/.dc55/.bb/.keltner/.supertrend/.sar/.chandelier/.macd/.tsmom/.dual_thrust` 各独立
- 每个信号必须带 `reason` 字段（`[signal_type] dir=... grade=... 指标=...`），向辩论层说明"为什么选这个信号"
- 入口门禁：`signal_passes_entry_gate()` — grade∈{STRONG,WATCH} 即进候选（兼容 `|total|≥20` 兜底）
- 信号出处（哪个子策略）+ reason 在 `reason` 字段中，通过 debate trigger/brief 透传辩论层
- 知识库 `memory/knowledge/strategies/_index.json` 供辩论子 Agent 按 `signal_type` 查阅权威规则

## 🔴 Harness 驾驭工程强制铁律（2026-07-14 确立，优先级高于一切）

**文档先行 (Documentation-First)** — 改任何 `.py` 之前先改对应的 `.md`。Harness 文档 = design spec，测试 = validation spec，代码 = implementation。

**完整顺序（禁止违反）**：
1. 设计评估 —— 扫 8 维影响面
2. 文档先行 —— 更新受影响的 Harness 文档
3. 测试设计 —— 补测试用例
4. 编码实现 —— 按文档敲代码
5. 验证收口 —— 跑测试 → 更新 08-gap-analysis

**commit 前必须自检 12 项**（详见 `docs/harness/10-coding-standards.md` §2）：架构/数据流/阶段/配置/弹性/观测/测试/版本/差距/流程文档/Agent MD/README。缺一不可。

**契约优先**：改 `contracts/` 先写 schema，版本迁移必走 `migrations.py`。**测试随重构**：函数重命名同步改 mock 名。**版本号唯一真相源** `pyproject.toml`。

> 本条违反 = 生产事故同等级别。G16/G17/G18 已用 6 小时代价验证纪律的必要性。

## 🔴 辩论资源管理铁律（2026-07-13 确立）

执行辩论时严格按 spawn_plan.execution_phases 分批：
1. **Phase1** 观澜（技术分析）≤5并发
2. **Phase2** 证真+慎思（辩论）≤6并发
3. **Phase3** 闫判官（裁决）≤5并发
4. **Phase4** 一致性裁判（审计）≤5并发
5. **Phase5** 策略方案（依赖Phase1+Phase3）≤5并发
6. **Phase6** 风控明（审核，依赖Phase5）≤5并发

每批完成后立即 shutdown 回收，不拖到全部结束。
进程数>20时暂停 spawn。

## 🟡 v2.3 评分权重调整（2026-07-13 23:40）

DC20突破、BB突破均为辩论入口的独立触发信号，权重显著提升：
- **DC20**：break_base_score 30→40，break_strong_bonus 10→15，break_moderate_bonus 5→8
- **DC20逼近**：near_breakout_score 15→22，near_breakout_ticks 5→7
- **BB突破**：pos_extreme_score 6→20，pos_upper_score 4→15
- **BB下轨**：pos_lower_score -4→-15，pos_extreme_lower_score -6→-20
- P0-4伪突破拦截保持不变，false breakout不会绕过

## 🔧 early_signal.py 定位（2026-07-14 厘清）
- `signals/early_signal.py` 是**孤儿模块**（无活代码 import），定位为"早期预警旁路库"，**不重复实现突破/伪突破判定**
- 突破判定（DC20/DC55/BB）单一真相源 = `channel_breakout_strategy.py`；伪突破校验单一真相源 = `scan_all.py` 的 P0-4 门禁
- 已收掉其中的 `detect_price_breakout()` 与 `detect_oi_triangle()` 的 true/false breakout 分支（两份重复定义）
- 保留：放量/OI/动量/收敛/基差/期限结构/Spread 等期货专属早期维度 + `inject_early_signals_to_tech` 注入接口（未来若挂主链路用）
- **2026-07-14 掌柜确认：保留为独立旁路预警库，不挂主扫描链路**（docstring 已固化"架构定位"声明；去重后 812 行版本即终态）

## 🔴 FDT 唯一副本铁律（2026-07-14 17:50 确立）
- **总原则**：`C:\Users\yangd\.workbuddy\plugins\marketplaces\my-experts\plugins\futures-debate-team\` 是 **FDT 项目的唯一副本（唯一真身）**。其它所有副本（尤其 `D:\FDT2` 全量：futures-data-core / fdt2 / futures-llm-analysis / futures-orchestrator / futures-report / futures-scan-core 等重构产物）**均不再被引用、不再被修改**。
- **⚠️ 旧「双副本同步」铁律已废止**（原 2026-07-14 厘清版）。
- **吸收原则**：FDT2 重构中发现的优秀改进方向，可 port 回原版 FDT（my-experts/futures-debate-team），但绝不在 D:\FDT2 继续开发。
- **futures_data_core 子规则**：唯一真相源 = FDT 包内 `futures_data_core` 副本。editable 安装已于 2026-07-14 17:47 按方案 B 解除（`__editable__.futures_data_core-0.1.0.pth` 已删，D:\FDT2 目录保留可逆）；验证裸 import 失败、FDT_ROOT 自举加载包内 v0.2.0。
- **FDT2 残留已清理（2026-07-14 1943）**：经核查，site-packages 中 fdt2/futures_llm_analysis/futures_orchestrator/futures_report/futures_scan_core/futures_data_core-0.1.0 共 6 个 stale `.dist-info` 已 `rm -rf` 删除（D:\FDT2 源码保留、可逆）；实际无 `.pth` 指向 D:\FDT2（方案 B 引用切断此前已生效）。删除后验证：pip list 不再报这些包、`D:\FDT2` 不在 sys.path、FDT 包内 `futures_data_core` v0.2.0 经 FDT_ROOT 自举仍正常加载。唯一副本铁律彻底闭环。
- FDT 运行环境内 import 时，仍须在模块顶部补 FDT_ROOT 自举（4 级：scripts→technical-analysis→skills→futures-debate-team），确保加载包内副本。
- **GitHub 推送机制（2026-07-14 2042 确立）**：`futures-debate-team` 目录本身是 `CTAAgents/experts` 的 git 仓库（remote `origin = https://github.com/CTAAgents/experts.git`，分支 `main`），直接 `git add/commit/push` 即可（**无**独立 sync 脚本）。**推送前铁律**：全文件类型扫描密钥明文（如 `Qk5JiD`/`1rc2gt0t6nde`）必须零命中，凭证只走环境变量（DCE_API_KEY/DCE_API_SECRET 存 `~/.bashrc`，与 FDC_* 同段单引号），绝不入库；`.coverage` 等测试产物须 .gitignore 排除。

## 🟢 彻底移除 AKShare 依赖（2026-07-14 1840 确立）
- **总则**：`futures_data_core/f10/position.py` 不再依赖 AKShare，所有 5 个交易所持仓排名均通过官网直连实现。
- SHFE：pm{date}.dat JSON GET，`_parse_shfe_rank` 解析
- CFFEX：{VAR}_1.csv CSV GET，`_parse_cffex_rank` 解析
- CZCE：FutureDataHolding.xlsx GET（openpyxl），`_parse_czce_rank_xlsx` 解析品种块
- DCE：**官方 API 优先**（`futures_data_core/f10/dce_api.py`，`www.dce.com.cn/dceapi`，需 `DCE_API_KEY`/`DCE_API_SECRET` 环境变量）→ 未配置/异常/返回空时回退 `portal.dce.com.cn` 网页抓取（POST 取合约列表 → GET 首合约 xlsx，`_parse_dce_rank_xlsx` 解析）
- GFEX：POST 取合约列表 → POST 3 页合并，`_parse_gfex_rank` 合并 JSON 解析
- 无 Fallback：直连失败直接 UNAVAILABLE（`_fallback_akshare` 已删）
- `data_sources.yaml` 删 akshare，`pyproject.toml` 补 httpx>=0.27
- **实盘验证（2026-07-14 1943 跑通 4/5 → 19:45 升级 5/5 PASS）**：单测 16/16 通过（test_position 9 + 新增 test_dce_api 7）。沙箱实测 SHFE(rb)/CFFEX(IF)/CZCE(MA)/GFEX(si)/**DCE(m，经官方 API 解析到 M2608 合约，21 买+21 卖真实会员排名，top5 多 130,462/空 133,465 手)** 五家全部返回真实持仓排名（grade=2 DAILY）。DCE 官方 API 在沙箱可直连 `www.dce.com.cn/dceapi`（portal.dce.com.cn 仍被 DNS 拦截，但已被官方 API 路径绕过）。验证脚本 `D:\WorkBuddy\FDT\validate_fdc_position_ranking.py`；**注意 DCE 官方 API 需注入 `DCE_API_KEY`/`DCE_API_SECRET` 环境变量方走 API 路径，否则回退 portal（沙箱内即 ENV_BLOCK）**。

## 🗺️ CTA 策略分类与 FDT 覆盖映射（2026-07-14 23:22 更新）
### 已覆盖（纯 Python 信号生产，经 StrategyPipeline 可插拔执行）
- **(1) 趋势跟踪**：channel_breakout_strategy（DC20/DC55/布林带/ADX/ATR/均线排列）
- **(4) 多因子量化**：（carry/momentum/inventory_pct/skew/corr）
- **(2) 均值回归**：MeanReversionStrategy（RSI<25/CCI<-200/BB<0.1 极端反转，ADX<25 震荡市激活）— v6.5.1 新增
  - **配对做空回归**：PairsReversionStrategy（Engle-Granger 协整残差 + 滚动 Z|Z|>=2 出信号 + Hurst 门禁 H<0.75 + OU 半衰期；两腿独立 RawSignal 贵腿 bear/便宜腿 bull，天然双向做空）— **v8.1.0 / G35 Phase 1 新增**
  - **跨期价差 OU 回归**：SpreadReversionStrategy（跨期价差 OU 拟合 b<0 门禁 + 半衰期 [2,120] + 滚动 Z|z|>2；偏高→短近长远，偏低→长近短远；消费 ctx['spread_history']，xtquant 预采集复用 qmt 同源引擎）— **v8.1.1 / G36 新增**
  - **期现基差 OU 回归**：BasisReversionStrategy（消费 ctx['basis_history']，JSONL 持久化每日 100ppi 基差快照；OU+KF z 复用 SpreadReversion 框架，基差大幅偏离→做空/做多回归）— **v8.1.7 / G40 新增**
  - **Kalman 自适应 OU**：`kalman_filter_ou(series,Q,R)` 1D KF 时变均值跟踪，自适应去趋势 z-score；替代固定窗口 `_rolling_z` 应对换月/波动率突变 — **v8.1.4（G37 全部三阶段收口）**：SpreadReversion KF z(G37 P1) + PairsReversion KF z(G37 P2) + MeanReversion 制度过滤(G37 P3)
- **(3) 套利**：ArbitrageStrategy（期现基差>3% + 跨品种6配对 Z-score + 跨期价差）— v6.5.0 新增
- **(6) 宏观对冲**：MacroRegimeStrategy（板块轮动，5板块46品种，weight=0.4）— v6.5.2 新增
### 辩论环节间接覆盖（LLM Agent 推理，非纯 Python 信号）
- **(5) 事件驱动**：EventDrivenStrategy（事件日历+价格偏差捕获，~40 预排事件覆盖 USDA/MPOB/美联储）— v6.6.0 新增
- **(7) AI/ML**：MlSignalStrategy（ONNX 推理桥接 + MODEL_REGISTRY，无模型时优雅降级）— v6.7.0 新增
### 插拔化进程（完成进度）
- Phase A (v6.4.0) ✅：BaseStrategyV2 + StrategyPipeline + StrategyFusion（23 测试）
- Phase B (v6.4.1) ✅：StrategyV1Adapter v1→v2 桥接（4 测试）
- Phase C (v6.5.x-v6.7.0) ✅：**CTA 7/7 全覆盖**，57 策略测试全绿
- Phase D (v7.0.0) ✅：scan_all 默认管线模式 + 废弃旧单策略接口
- v7.2.0 宏观注入 · v7.3.0 G20阈值集中 · v7.4.1 G21降级文档+验证器fix
- v7.5.0 死代码清理 · v7.6.0 事件日历 | G1-G23全关
