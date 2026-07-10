# FDT 专家团变更日志

> 记录所有代码/配置/机制的变更。按时间逆序排列。

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
