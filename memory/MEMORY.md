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
