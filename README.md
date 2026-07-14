# Futures Debate Team — 期货交易辩论专家团 v6.3.0

> 🚀 **v6.3.0 信号生产链路拆分（技术债 §2/§3）**：`scan_all.py` 重构为纯通道突破信号源（移除 `--dual`/`layered_l1l4`/`factor_timing`/`true_layered`）。P1 三生产者架构正式落地——数技源 `scan_all`(channel_breakout) + 观澜 `run_l1l4_scan.py`(L1-L4) + 探源 `run_factor_timing_scan.py`(因子择时)，各自独立产出 JSON，辩论流水线保持可用。

## 类型

Team 型（10角色多角色协作团队，全Agent自进化）

## 快速开始

通过 LLM 对话直接使用，无需手动操作：

```
"全量分析商品期货"
"分析螺纹钢期货的多空博弈情况"
"对比铜期货的多空论点"
```

系统自动执行 6 阶段完整流程：数据采集 → 产业链分析 → 闫判官筛选 → 研究员供弹 → 多空辩论 → 风控审核 → 方案输出。

## 系统架构

```
🔴 自进化前置（所有模式强制，全自动）
     │   检测未验证裁决 → validate_verdicts.py
     │   已验证≥5条 → calibrate_weights.py → evolve_agents.py
     │   加载最新 calibration.json + agent_profiles.json
     ▼
P1  通道突破全量扫描               数技源(quant-daily - channel_breakout策略)
     │                           产出: full_scan_channel_breakout_*.json
     │                           信号检查闸门：无候选信号(|total| < DEBATE_ENTRY_MIN_ABS，当前=20)则提前终止
     ▼
P1.5 产业链分析                    链证源(commodity-chain-analysis)
     │                           产出: 产业链景气度快照 + redundant_pairs
     │                           基于通道突破品种，不做全覆盖
     ▼
P2  闫判官筛选辩论品种             闫判官(judge)
     │                           输入: 通道突破信号 + 链分析
     │                           按R26指定正方方向(signal_type隐含方向)
     │                           同链冗余硬过滤(r>0.80保留最强)
     ▼
P3  研究员并行供弹                 观澜(技术面禁WebSearch) + 探源(基本面允WebSearch)
     │                           中立产出，verdict=null
     ▼
P4  多空辩论                      证真(正方) + 慎思(反方)
     │                           基于研究员资料提炼论据，禁止自行搜索
     ▼
P5  裁决→方案→风控→决策（串行）      闫判官→策执远→风控明→明鉴秋
     │                           六维评分→6层风控→execute/hold/rematch
     ▼
P6  汇总输出                      明鉴秋
                                 4铁律核验→debate_results.json→HTML报告
```

### 角色与阶段对照

| 角色 | Agent | P1 | P1.5 | P2 | P3 | P4 | P5 |
|:-----|:------|:--:|:----:|:--:|:--:|:--:|:--:|
| **数技源** | datatech | ● 通道突破信号 | | | | | |
| **链证源** | chain-analyst | | ● 产业链 | | | | |
| **闫判官** | judge | | | ● 选品种+定方向 | | | ● 裁决 |
| **探源** | fundamental | | | | ● 基本面供弹 | | |
| **观澜** | technical | | | | ● 技术面供弹 | | |
| **证真** | affirmative | | | | | ● 正方论据 | |
| **慎思** | opposition | | | | | ● 反方论据 | |
| **策执远** | strategist | | | | | | ● 交易方案 |
| **风控明** | risk | | | | | | ● 6层风控审核 |
| **明鉴秋** | team-lead | ● 启动+调度 | | | ● 轮询传递 | ● 调度 | ● 归档+报告 |

## 一键辩论驱动（run_debate.py）

> 编排收敛层：把每轮「扫描 → 识别触发品种 → 标准化 spawn 计划 → assemble/extract/report」的易碎手工步骤收进单一脚本。**spawn 仍是团队主管（WorkBuddy Agent）的固有职责**，脚本产出标准化的 spawn 计划 JSON 供主管执行，不替代 Agent 调度。

```bash
# 1) 扫描 → 按 DEBATE_ENTRY_MIN_ABS=20 识别触发品种 → 输出 spawn 计划 JSON
python scripts/run_debate.py plan \
  --scan {YYYY-MM-DD}/scan_daily_*.json --workspace {YYYY-MM-DD}/

# 2) 主管按 spawn 计划执行各阶段 Agent，产物落 {YYYY-MM-DD}/

# 3) 组装 debate_results.json（含顶层 data_benchmark 数据基准字段）
python scripts/run_debate.py assemble --workspace {YYYY-MM-DD}/

# 4) 批量知识萃取（复用内置质量门控，conf<0.6 自动跳过，不加 --bypass）
python scripts/run_debate.py extract --workspace {YYYY-MM-DD}/

# 5) 信号复查（终检：推送给交易系统前的最后一道门）
python scripts/validate_final_signals.py --input debate_results.json --scan scan_daily_*.json

# 6) 生成辩论报告（统一调 phase3 --debate，单/多品种通用）
python scripts/run_debate.py report --workspace {YYYY-MM-DD}/
```

**关键约定**：`data_benchmark`（数据基准时间戳，如 `2026-07-11 15:00 收盘`）由 `assemble` 写入 `debate_results.json` 顶层，`phase3 --debate` 渲染到报告「数据基准」字段，便于判别行情时效。

## 10 角色详情

| # | 角色 | Agent ID | 对应Skill | 核心职责 |
|:-:|:----|:---------|:----------|:--------|
| 1 | 🎯 明鉴秋 | `futures-debate-team-team-lead` | — | 选题+调度+汇总+流程守护 |
| 2 | 📡 数技源 | `futures-datatech` | `quant-daily` | 运行通道突破全量扫描，产出原始信号 |
| 3 | 🔗 链证源 | `futures-chain-analyst` | `commodity-chain-analysis` | 产业链事实描述+景气度分析（不下多空） |
| 4 | ⚪ 闫判官 | `futures-judge` | `debate-judge` | 选辩论品种+定方向+评分+裁决 |
| 5 | 🧑‍🔬 观澜 | `futures-technical-researcher` | `quant-daily` + `technical-analysis` | 技术分析+支撑阻力（中立，verdict=null，禁WebSearch） |
| 6 | 🧑‍🔬 探源 | `futures-fundamental-researcher` | `fundamental-data-collector` | 基本面分析（供需库存利润，允许WebSearch） |
| 7 | 🔵 证真 | `futures-affirmative-debater` | `debate-argument-builder` | 正方论据（动态方向，禁止自行搜索） |
| 8 | 🔴 慎思 | `futures-opposition-debater` | `debate-argument-builder` | 反方驳论（动态方向，禁止自行搜索） |
| 9 | 📋 策执远 | `futures-trading-strategist` | `debate-trading-planner` | 合约选型+执行方案 |
| 10 | 🟡 风控明 | `futures-risk-manager` | `debate-risk-manager` | 6层风控引擎：选锚/仓位/动态/覆写/反馈/组合 |

## 信号解读

### 通道突破信号（主信号）

| 信号类型 | 含义 | 权重组合 |
|:---------|:-----|:---------|
| channel_breakout | 通道突破 | DC20(40%) + DC55(35%) + BB(15%) + 成交量(10%) |
| trend_confirmation | 趋势确认 | DC55中期位置+趋势方向 |
| bb_squeeze_prebreakout | 布林带挤压预警 | BB带宽低位+挤压状态 |

### 评分等级

| 等级 | 绝对值范围 | 含义 |
|:----|:--------:|:-----|
| STRONG | ≥ 60 | 最强信号，多层通道共振 |
| WATCH | 40-59 | 重点信号，方向一致 |
| WEAK | 20-39 | 信号一般，需验证 |
| NOISE | < 20 | 噪音，忽略 |

## 数据源

| 数据源 | 优先级 | 盘中 | 盘后 | 实时价 | 依赖 |
|:-------|:-----:|:----:|:----:|:------:|:-----|
| **TqSDK 免费版** | 0（第一） | ✅ 实时 | ✅ 保留最后 | ✅ last=实时价 | `pip install tqsdk` + 免费账号 |
| **QMT/xtquant** | 0（降级） | ✅ | ✅ | ✅ close | 需QMT终端 + xtquant包 |
| **通达信TDX TQ-Local** | 0（降级） | ✅ | ✅ | ✅ close=实时价 | 需通达信客户端 |
| **100ppi 生意社** | 基本面现货 | ✅ | ✅ 16:30发布 | ❌ | 免费Web，FDC内置 |
| **WebFallback** | 99（兜底） | ✅ | ✅ | ❌ | FDC内置(东方财富+新浪) |

数据路由统一经 `futures_data_core` (FDC) 管理，外部模块不直接调任何数据API。

中国期货市场日线惯例：一根 TqSDK 日线覆盖一个完整交易日（前夜盘21:00→当日日盘15:00），`close` 为该交易周期内最后成交价。

## CLI 使用

```bash
# 通道突破全量扫描（默认策略）
python skills/quant-daily/scripts/scan_all.py

# 指定品种
python skills/quant-daily/scripts/scan_all.py --symbols CU,RB,PK

# 输出到指定目录
python skills/quant-daily/scripts/scan_all.py -o ./reports -p full_scan

# 列出可用策略
python skills/quant-daily/scripts/scan_all.py --list-strategies

# 辩论驱动：plan → spawn → assemble+validate → report
python scripts/run_debate.py plan --scan scan.json --workspace .
# ... spawn Agents ...
python scripts/run_debate.py finalize --scan scan.json --workspace .

# 信号复查（终检，推送给交易系统前必跑）
python scripts/validate_final_signals.py -i debate_results.json -s scan_daily_*.json --json

# 单独运行各阶段
python scripts/run_debate.py validate --workspace . --scan scan.json
python scripts/run_debate.py report --workspace .
```

## 依赖的 Skills

| Skill | 版本 | 用途 |
|:------|:----|:-----|
| `quant-daily` | v2.15.0 | 数据采集+通道突破信号+信号触发文件 |
| `futures-trading-analysis` | v3.11.0 | 主流程编排+5层鲁棒性+A01文件通信+报告生成+A2A文件桥 |
| `fdt-spawn-debate` | v1.1 | Agent spawn流程+A01文件通信协议 |
| `commodity-chain-analysis` | v2.16.0 | 产业链分析 |
| `fundamental-data-collector` | v1.4.0 | 基本面分析(供需库存利润) |
| `technical-analysis` | v2.3.0 | 技术面分析(支撑阻力+事件日历) |
| `debate-argument-builder` | v2.3.0 | 正反方论点构建 |
| `debate-judge` | v2.0.1 | 辩论裁决 |
| `debate-risk-manager` | v4.1.0 | 风控审核(6层引擎) |
| `debate-trading-planner` | v2.1.0 | 交易方案规划 |

## v5.5 新能力（OmniOpt 分类法集成）

v5.5 将 OmniOpt 论文(arXiv:2607.04033) 的双维度分类法和几何统一方法论引入辩论裁决流程，使闫判官的评估从"综合判断"升级为**基于策略族分类的加权评估**。

### F1-F5 论证策略族分类
- **F1 技术面量价**：均线、MACD、布林带、ADX、RSI、CCI 等技术指标
- **F2 基本面供需**：库存、基差、利润、开工率、供需平衡表
- **F3 持仓资金**：主力持仓变化、持仓量创新高、净多/净空头
- **F4 宏观政策**：利率决议、财政政策、地缘事件、贸易政策
- **F5 套利结构**：跨期价差、跨品种价差、展期收益

### 品种×策略族适应性矩阵
- `memory/instrument_strategy_matrix.json` — 每个品种对各策略族的历史胜率权重
- EMA 在线更新（学习率 0.3），每次裁决后自动校准
- 初始值按品种大类预设（黑色系/有色/能化/农产品/贵金属）
- `scripts/update_matrix.py` 提供 CLI 批量/单条更新接口

### 闫判官加权裁决（WEAS）
在六维评分前增加族加权预处理步骤：
```
WEAS = Σ IMPACT_numeric(论据) × w(策略族, 品种)
IMPACT映射: HIGH=3.0, MEDIUM=1.5, LOW=0.5
族覆盖 ≥3 → 证据充分性 +1分
族覆盖 ≤1 → 证据充分性 -1分
```
裁决 `reasoning` 字段追加 WEAS 摘要，使裁决可量化、可追溯。

## v5.4 新能力（可观测性与自改进）

v5.4 在 v5.3 通道突破主信号源之上，补齐了**系统级可观测性**与**自动自改进**能力，使专家团的决策质量可被量化、审计与迭代。

### APM-CS 五轴评分卡（D1–D5）
- **D1 论据一致性**：held-out 一致性裁判评估"裁决是否真正源于辩论论据"（CLQT §6.4.1），非阻断审计。
- **D2 Acuity 辨识力**：Spearman 秩相关 ρ(PnL, 信息) − ρ(PnL, 噪音)；成本感知 PnL（COST_BPS=2.0）建模交易摩擦。
- **D3 镇定度**：stop~ADX 回归，≥5 轮辩论自动点亮。
- **D4 纪律遵守**：R13/R14/R-resonance 仓位上限，落库前 `enforce_discipline.py` 强制钳制。
- **D5 可靠性**：剔除陈旧基础设施失败后的 fresh 完成率。
- 触发：每周一自动运行（`scheduler/triggers.py`）。

### Telescope 失败模式聚类
- `scripts/cluster_failures.py`：7 维特征提取 + 单维/二维交叉/品种方向聚类 + 规则关联诊断 + 严重度评估，输出 `memory/failure_clusters.json`。

### ViBench 历史回放（阶段二）
- `scripts/run_benchmark.py --replay` + `scripts/replay_harness.py`：按 `(round_id, 品种)` 结构一致性回放，金标准集 `benchmarks/test_cases.json`。

### self_improve 自改进脚手架（阶段三）
- `scripts/self_improve.py`：消费 APM/failure_clusters/benchmark 生成改进建议（proposal，不直接改 Agent），写入 `memory/self_improve_log.json`。

### 全周期 K 线
- 日/周/月/240m/60m/15m/5m/1m + 自定义周期（90m/180m），`PERIOD_CONFIG` 统一路由，指标窗口按 `bar_min` 缩放。

### 反馈闭环
- 自进化前置（validate → calibrate → evolve）全自动；`debate_journal.json` 升级捕获辩手论据 + held-out judge，双副本同步。

## v5.10 新能力（信号体系统一 + 能力裁剪）

v5.10 聚焦「信号口径统一」与「去除无效能力」两项治理，不改变既有分析能力。

### 辩论入口阈值统一（单一真相源）
- 阈值定义收敛到 **`config/settings.DEBATE_ENTRY_MIN_ABS`**（当前 = 20），全链路统一引用：`daily_debate.py` / `hourly_debate.py` / `fdt-spawn-debate` / `backtest_optimizer.py` / `04-resilience.md`。
- 语义：**`|total| ≥ 20`（WEAK 及以上）才进入辩论候选**；NOISE 级（< 20）被过滤，不 spawn 任何辩论 Agent，直接回报无信号。
- 删除 `signal_classifier.py` 死代码（第三套无人执行的「无信号」口径）。
- 禁止任何位置写死阈值（team-lead / SKILL.md / 文档均改为读配置），日后调阈值只改 `settings.py` 一处。

### 移除 120m(2小时) 信号监控与参数优化
- 删除 4 个 120m 信号监控自动化（9:15 / 11:15 / 14:40 / 21:15）。
- 删除盘前预计算缓存自动化（读取端从未接入主流程，属死缓存）。
- 代码层：`scripts/optimizer/run_120m_wf.py` 删除；`run.py` 去 120m 分支；`backtest_optimizer.py` 去 120m tiers；`monitoring_symbols.json` 去 120m 块。
- 参数自优化自动化改名「参数自优化 - 日线(每4周)」，`run.py --update-config --period daily` 仅重建日线监测宇宙。

### 能力不变
- 品种知识库(v5.9)、OmniOpt 分类法(v5.5)、可观测性与自改进(v5.4)、通道突破主信号源(v5.3) 等既有能力均保留。

---

## v6.2 新能力（A2A 协议桥 + 置信度修复）

v6.2 新增 **Agent-to-Agent (A2A) 协议文件桥**，使 FDT 的辩论裁决可被任意 A2A 兼容系统直接消费。

### A2A Agent Card
- `agent-card.json` — FDT 能力声明（skills/input/output schema），符合 Google A2A v1.0 规范
- 声明三项技能：通道突破扫描 / 多Agent辩论裁决 / 辩论知识萃取
- 明确定义输入 Schema（`debate_results.json` 结构）与输出 Schema（`a2a_results.json` 结构）

### A2A 信封输出
- `run_debate.py finalize` 管道末尾自动导出 `a2a_results.json`
- 也可独立运行：`python scripts/run_debate.py a2a --workspace <工作空间>`
- 格式：`jsonrpc: "2.0"` + `method: "tasks/send"` + `params: {id, sessionId, status, parts}`
- 每个品种裁决是一个 `artifact`（含 symbol/decision/confidence/entry/stop_loss/targets）
- 末尾附带产业链汇总 artifact（`chain-summary`）

### 置信度归一化修复
- `validate_final_signals.py` 增加 `CONFIDENCE_MAP`，自动将英文标签（HIGH/MEDIUM/LOW）映射为中文（高/中/低）
- 同步更新 `fdt-self-heal` 自愈技能 F02 故障记录，标注三处均已修复
- 经验证：`validate_final_signals.py --json → passed: true, error_count: 0`

### 外部集成示例
```python
import json
with open("a2a_results.json") as f:
    task = json.load(f)
for part in task["params"]["parts"]:
    artifact = part["artifact"]
    if artifact["id"] == "chain-summary":
        print(f"产业链: {len(artifact['content']['chains'])} 条")
    else:
        c = artifact["content"]
        print(f"{c['symbol']}: {c['decision']} (conf={c['confidence']})")
```

---

## v5.12 新能力（周期发现层）

v5.12 新增**零硬编码周期发现引擎**，使辩论流程可以根据品种当前市场微观结构自动选择最优交易周期（日线/240m/120m/60m/30m），取代此前全品种固定日线的粗放模式。

### 周期注册表（PERIOD_REGISTRY）

单一真相源定义在 `config/settings.py`，所有周期参数化配置：

| 周期 | 分钟数 | min_bars | wf_key | gap_sensitive | exec_default |
|:----|:------:|:--------:|:------:|:-------------:|:-----------|
| **daily** | 1440 | 60 | daily | 3（低） | limit |
| **240m** | 240 | 120 | h4 | 5（中） | limit |
| **120m** | 120 | 120 | h2 | 8（高） | market-if-touched |
| **60m** | 60 | 120 | h1 | 10（高） | market |
| **30m** | 30 | 120 | m30 | 12（很高） | market |

- `enabled_periods()` 返回启用周期列表
- `period_meta()` 返回全元数据
- `PERIOD_FITNESS_WEIGHTS`: wf_acc(0.35) / signal_strength(0.45) / gap_risk(0.20)
- `EXEC_STYLE_MAP`: 按 gap_sensitive 分层映射执行风格

### 周期发现引擎

`skills/quant-daily/scripts/signals/period_fitness.py`

- `discover()`: 纯函数，对单品种算全周期 fitness 分（复用 `strategies.base.score(period=)` / `config.settings.resolve_param` / `optimizer.knowledge_bridge.get_symbol_knowledge`）
- `build_period_fitness()`: 全品种批量产出 `period_fitness_{date}.json`

### 消费链路

| 组件 | 消费内容 | 产出 |
|:----|:--------|:----|
| `daily_debate.py` | 对候选品种算周期发现 | `debate_trigger.json.period_fitness_path` |
| `debate_brief.build_signal_summary` | 注入 `period_context` | 辩论简报含 best_period/exec_style 元信息 |
| ⚪ 闫判官 | 消费 `best_period`/`exec_style`/`gap_risk` | 裁决时参考周期匹配度 |
| 📋 策执远 | 消费 `best_period` 等（与方向正交） | 交易方案按最优周期设计执行参数 |
| 🟡 风控明 | 消费 `gap_risk` | 风控阈值按 gap 敏感度动态调整 |

方向正交性：周期发现提供的是执行风格和持仓时长建议，**非硬指令**。缺失时自动降级日线默认值。



## v5.9 新能力（品种分析逻辑知识库 v1.0）

v5.9 新增品种知识库系统，使 FDT 可以在辩论过程中自动积累品种特异性分析知识，实现"每轮辩论都让下一次更聪明"。

### 五层知识体系

| 层级 | 内容 | 文件 | 更新方式 |
|:----|:-----|:-----|:--------|
| **L1 静态画像** | 品种合约规格、产业链归属、波动率基线 | `profile.json` | 初始化脚本从 `varieties.yaml` 生成 |
| **L2 驱动因子** | 核心影响因素及权重（如 RB: 地产>限产>铁矿） | `drivers.md` | 每轮辩论后从闫判官推理自动萃取 |
| **L3 有效论证模式** | 该品种历史有效论证结构及胜率 | `patterns.json` | 每轮辩论后从 debate_record 自动萃取 |
| **L4 关键价位** | 聚合支撑/阻力位、持仓密集区 | `key_levels.json` | 从策执远交易方案自动提取+聚类 |
| **L5 数据源质量** | 各数据源可靠性评分、延迟天数 | `data_quality.json` | 每次数据采集后更新 |

### 知识萃取引擎

`scripts/extract_knowledge.py` 是核心引擎，6个关键设计：

```
质量门控 ── confidence ≥ 0.6 才入库，seed/reconstructed 记录跳过
原子写入 ── .tmp → rename 确保并发安全
去重检测 ── 相同模式再次出现时 EMA 更新 win_rate
老化保护 ── 每品种上限 20 条，超限淘汰最低效
自动老化 ── 每日 22:00 降级 60 天未使用的模式
可审计 ── deprecated 模式保留不删除，标注淘汰原因
```

### 知识消费链路

| Agent | 消费内容 | 用途 |
|:------|:--------|:-----|
| ⚪ 闫判官 | `patterns.json` | P2 加载历史有效模式作为方向参考 |
| 🟢 观澜 | `key_levels.json` + `profile.json` | 支撑/阻力位交叉验证，波动率基线 |
| 🟢 探源 | `profile.json` 驱动因子权重 + `data_quality.json` | 按权重排序搜索，优先用高质量数据源 |
| 🔵 证真 | `patterns.json` | 参考历史模式增强论证，禁止复制历史论据 |
| 🔴 慎思 | `patterns.json` | 找与正方方向相反的历史模式 |
| 📋 策执远 | `key_levels.json` 聚合支撑/阻力位 | 辅助止损/目标设定 |

知识库仅在 spawn prompt 中注入作为**参考层**，禁止直接复制历史论据。当期数据与知识库矛盾时以当期数据为准。

### 使用接口

```python
# P6 汇总后自动萃取（已嵌入 team-lead prompt）
from scripts.memory_writer import batch_knowledge_extraction
batch_knowledge_extraction(debate_results)

# 手动触发老化
python scripts/extract_knowledge.py decay

# 初始化/重新初始化知识库
python scripts/init_knowledge_base.py [--force]

# 查看知识库状态
cat memory/knowledge/variety_index.json
```

### 目录结构

```
memory/knowledge/
├── variety_index.json           # 84品种索引（含各文件状态）
├── rb/ → profile.json + drivers.md + data_quality.json
├── sc/ → profile.json + drivers.md + data_quality.json
├── ...                          # 84品种各一套
└── (patterns.json + key_levels.json 在辩论后自动生成)
```

## 核心铁律

| 铁律 | 内容 |
|:----|:------|
| **时序铁律** | 链证源先于闫判官 → 闫判官决策 → 研究员供弹 → 辩手立论，顺序不可逆 |
| **禁止串线** | Agent间不得SendMessage，统一写文件由明鉴秋传递 |
| **文件就绪** | 下游必须poll上游文件就绪(存在+size稳定≥5秒) |
| **辩手禁搜** | 证真/慎思不得自行WebSearch，论据必须来自研究员资料 |
| **胶水代码零容忍** | 所有操作通过已有skill的CLI/库函数/Agent spawn完成 |
| **记忆独立** | 专家团记忆仅写入自身memory/目录，不入宿主工作空间 |
| **鲁棒性防线** | L1-L5五层防线(校验+降级+信号门+路径发现+自检)确保流程不静默断裂 |
| **P5降级D06** | 闫判官2次spawn失败→明鉴秋基于P3+P4论据独立裁决 |

## 输出文件结构

```
FDT内部 (自包含系统):
  data/debate_results.json                 ← 辩论数据（交易系统接口，含action=execute/hold/wait）
  reports/debate_report_*.html             ← HTML报告
  scripts/validate_final_signals.py        ← 最终信号复查器（确定性校验，推送交易系统前调用）
  memory/debate_journal.json               ← 辩论执行记录
  memory/debates/INDEX.md                  ← 辩论索引
  memory/knowledge/{variety}/              ← 品种知识库（v5.9）
  memory/incidents.md                      ← 事故与教训

工作空间镜像 (用户入口):
  Commodities/debate_report_*.html         ← 报告副本
  .workbuddy/memory/YYYY-MM-DD.md          ← 操作摘要 <=5行
```

## 系统基础设施

| 模块 | 版本 | 功能 |
|:-----|:----|:-----|
| fdt_paths.py | v1.0 | 单一路径真相源，自动检测FDT根目录 |
| memory_enforcer.py | v1.0 | 零参数记忆归档+工作空间日志校验 |
| validate_final_signals.py | v1.0 | 确定性信号复查器：6+条硬性规则，确保交易系统收到无矛盾信号 |

## 依赖安装

```bash
# 核心依赖
pip install numpy pandas pyyaml duckdb pydantic psutil lightgbm scikit-learn

# TqSDK（第一数据源，必须）
pip install tqsdk

# FDC 额外依赖
pip install httpx beautifulsoup4 lxml openpyxl

# 可选：通达信TQ-Local采集器（本地HTTP服务）
pip install httpx beautifulsoup4
```

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v6.3.0** | **2026-07-14** | **🧬 信号生产链路拆分（技术债 §2/§3）**：`scan_all.py` 重构为纯通道突破信号源(channel_breakout)，移除 `--dual`/`layered_l1l4`/`factor_timing`/`true_layered`；L1-L4 迁 technical-analysis(`run_l1l4_scan.py`)，因子择时迁 fundamental-data-collector(`run_factor_timing_scan.py`)，P1 三生产者架构落地；`pipeline/runner.py`+`scheduler/tasks.py` Step1 重写，`full_scan_summary_{date}.json` 精确匹配下游，辩论流水线保持可用。版本：包 6.2.0→6.3.0。 |
| **v6.1.0** | **2026-07-13** | **🔴 最终信号验证门禁**：新增 `scripts/validate_final_signals.py` 确定性信号复查器（6+条硬性规则：action合法性、交易参数一致性、方向-价格一致性BULL→target>entry>stop/BEAR→target&lt;entry&lt;stop、RR≥0.5、品种交叉校验、confidence/grade合法性）。`assemble()` 新增 `_derive_action()` 动作消歧——裁决→execute/hold/wait 三值映射，action≠execute 时自动清空所有交易参数。CLI修复：`report`/`extract`/`validate` 子命令不强制加载 scan 文件。`generate_intermediate_data()` 的 `decision` 字段从扫描信号改为读辩论裁决（根因修复：信号与策略不一致）。`phase3_generate_report.py` 新增 confidence 字符串→float 归一化（"高"→0.95/"中"→0.65/"低"→0.35）。
| **v6.2.0** | **2026-07-13** | **🔧 FDC v0.2.0 + A2A协议桥 + 置信度归一化**：FDC全面替代MSA(TqSDK免费版第一数据源)。新增A2A文件桥(`agent-card.json`+`export_a2a.py`+`run_debate.py a2a`子命令，`finalize`自动导出`a2a_results.json`)。`validate_final_signals.py`置信度英文→中文归一化(F02永久修复)。仓单日报/持仓排名/100ppi现货聚合迁入FDC。TqSDK全能力封装(28方法)。TickBar/TickData/SymbolInfo类型。连接复用优化(建连4.8s→0.2s)。CZCE大小写修复。|
| **v5.12.1** | **2026-07-11** | **🔧 版本对齐**：pyproject.toml 版本号同步(5.12.0→5.12.1)，无功能变更。 |
| **v5.12.0** | **2026-07-11** | **🧬 周期发现层里程碑**：新增 `skills/quant-daily/scripts/signals/period_fitness.py` 零硬编码周期发现引擎(`discover()`纯函数+`build_period_fitness()`批量产出)；`config/settings.py` 新增 PERIOD_REGISTRY(单一真相源，daily/240m/120m/60m/30m全enabled)+PERIOD_FITNESS_WEIGHTS+EXEC_STYLE_MAP；`daily_debate.py` 对候选品种算周期发现并写入 `debate_trigger.json.period_fitness_path`；3个决策Agent MD(闫判官/策执远/风控明)新增「周期发现消费」段。 |
| **v5.11.0** | **2026-07-11** | **🧬 辩论流水线工程化里程碑**：新增 `scripts/run_debate.py` 主动驱动层（扫描→按DEBATE_ENTRY_MIN_ABS识别触发品种→标准化spawn计划JSON→assemble/extract/report子命令，替代手写胶水代码）；`extract_knowledge.py` 增 `ingest_from --from debate_results.json` 批量萃取；`channel_breakout_strategy` 量能前置门(vol_ratio≥normal_lower_ratio才授DC20 base分)；`phase3 --debate` 子集兼容(adapt兼容reasoning顶层/嵌套两格式+去全量intermediate_data.json硬依赖+数据基准时间戳从debate_results顶层读取)。额外修复：config.settings漂移+phase3 KeyError:slice真根因。 |
| **v5.10.0** | **2026-07-11** | **🔧 信号体系统一与能力裁剪**：辩论入口阈值统一为 `config.settings.DEBATE_ENTRY_MIN_ABS=20`，全链路单一真相源，删除 `signal_classifier.py` 死代码；移除120m(2小时)信号监控与参数优化能力(4个自动化+相关代码全删)；删除盘前预计算死缓存。版本号统一 pyproject.toml 为唯一源。 |
| **v5.5.1** | **2026-07-09** | **🧬 Multi-Agent通信效率优化**：P0新增 `contracts/debate_argument_schema.py` 辩论论点结构化Schema(证真/慎思输出改为JSON结构化，闫判官解析耗时减50%)；P1闫判官按Agent类型差异化分发信息包(上下文噪声减约35%)；P2风控明拆为前置(品种级审核与研究员并行)+后置(方案级审核)。 |
| **v5.9.0** | **2026-07-11** | **🧠 品种知识库 v1.0**：自建品种分析逻辑知识库系统。5层知识体系(L1静态画像/L2驱动因子/L3有效模式/L4关键价位/L5数据质量)；`scripts/extract_knowledge.py` 萃取引擎(质量门控confidence≥0.6+原子写入+EMA在线更新+老化保护)；`scripts/init_knowledge_base.py` 初始化脚本(84品种从varieties.yaml+instrument_strategy_matrix批量初始化)；`memory/knowledge/{84品种}/` 目录；P6汇总后自动萃取(team-lead MD)；Agent进化后自动萃取(evolve_agents.py)；6个Agent消费端注入(闫判官/观澜/探源/证真/慎思/策执远)；每日22:00老化维护自动化。| **🏗 系统架构里程碑—FDT自包含运行时**：`fdt_paths.py`单一路径真相源(三级fallback自动检测FDT根目录)+`memory_enforcer.py`零参数记忆归档+`data/`+`reports/`内部产出目录+A01文件通信协议(tiered降级)。Agent MD v5.3(开篇动作清单记忆路由)+futures-trading-analysis v3.7.1+fdt-spawn-debate v1.1。系统边界清晰——产出和记忆在FDT内部，工作空间仅做镜像副本。修复：Agent SendMessage在自动化context路由失效(2次事故)→文件优先通信协议永久修复。 |
| **v5.7.0** | **2026-07-10** | **🏗 驾驭工程（Harness Engineering）完整落地**: 15项差距全部修复，成熟度4.0→4.7。Phase1正确性修复(G1 Pydantic配置校验/G2 trace_id全链路/G3 pipeline日志统一/G4 bootstrap动态版本)→Phase2测试补齐(G5 pipeline集成10用例/G6 scheduler集成10用例/G7覆盖率扩展到全skill/G8 memory集成9用例)→Phase3运维增强(G9 graceful drain/G10兼容矩阵/G13熔断可配/G14合约版本迁移28条路径)→Phase4体验优化(G11 APM-CS实时看板/G12 HTTP健康端点/G15 JSON结构化日志)。43用例全绿，contracts桥接层统一入口。|
| **v5.6.0** | **2026-07-09** | **🛡 5层鲁棒性架构**：L1产出校验(validate_agent_output.py)+L2熔断降级(debate_orchestrator.py+D06铁律)+L3信号门(daily_debate.py v2.0触发文件)+L4路径自发现(phase3 v3.2 CLI参数化)+L5健康自检(selfcheck.py)。D05-D06辩论完整性铁律。闫判官spawn Bug修复(futures-judge.md v2.1)。JSON产出规范J01-J03注入慎思+证真Agent MD。|
| **v5.5.0** | **2026-07-09** | **🧬 OmniOpt 分类法集成**：F1-F5 论证策略族分类系统；品种×策略族适应性矩阵(EMA在线更新)；闫判官加权裁决(WEAS族加权预处理+族多样性检查)；正反方辩手输出格式扩展(含策略族标签) |
| **v5.4.1** | **2026-07-07** | **🔧 信息源扩充**：新增 `memory/info_portals.md` 定性信息门户目录 — 三层级分类框架(监管/交易所→综合资讯聚合→产业垂直聚合)，合并金瑞期货权威清单与资深交易员实战配置，共30+权威站点，附品种映射速查表；`data_sources.md` 新增定性门户交叉引用节（与 A/B/C/D 定量评级体系隔离）；团队主管 SOP 新增定性信息取证职责 |
| **v5.4.0** | **2026-07-07** | **🧬 可观测性与自改进里程碑**：APM-CS五轴评分卡(D1-D5)+Telescope失败聚类；D1/D3/ViBench回放+held-out一致性裁判；D2 Acuity真实计算+成本感知PnL(COST_BPS)；D4纪律钳制enforce_discipline(R13/R14/R-resonance仓位上限)；D2信号退化标记/D5陈旧失败过滤/Stage3 self_improve脚手架；全周期K线(日/周/月/240m/60m/15m/5m/1m+自定义)；bug修复(MA60真实合约口径/scan_all原子写入/portfolio_backtest裸except/RuleChecker浮点边界/triggers闭包)；5门禁审计全100% |
| **v5.3.0** | **2026-07-07** | **🧬 通道突破策略里程碑**：唐奇安DC20/DC55+布林带替换三类信号为主信号源；TqSDK live模式盘中实时价(非backtest)；盘中/盘后自适应数据获取；信号检查闸门(无信号早停)；单策略默认(非--dual)；多数据源格式对齐(TDX/TqSDK/EM/AKShare统一schema)；TDX date字段str()防TypeError；日盘14:30自动化全流程含辩论团P0-P6；管理员手册合并入README；日线跨夜盘说明新增 |
| **v5.2.1** | **2026-07-07** | **🔧 全面修复**: ADX仅风控不参与评分+Agent输出格式统一+JSON Schema标准导出+时序通信铁律S01-S05+胶水代码清零 |
| **v5.2** | **2026-07-06** | **🧬 架构重构**: 三类信号替代L1-L4+因子择时为主信号源，全部信号全辩论，ADX角色反转，证真/慎思动态正反方 |
| **v5.1** | **2026-07-06** | **🔄 Phase 1独立化**: 内建调度器scheduler/、bootstrap一键启动、daemon看门狗、自循环闭环升级 |
| **v5.0** | **2026-07-06** | **🧬 自进化闭环里程碑**: P0进化链(validate→calibrate→evolve)、全9Agent自进化、裁决修正经验库 |
| **v4.5** | **2026-07-06** | Bridgewater方法论落地: 五维辩论评分+研报质量过滤+辩论档案+ML训练自动化 |
| **v4.4** | **2026-07-05** | P0+P1全面实施: 情感因子+流动性风险+交易摩擦+DAG并行+记忆反思 |
| **v4.2** | **2026-07-05** | P3全量实现: 事件日历+ML特征管道+方向分类器+PnL反馈闭环+风控6层引擎 |
