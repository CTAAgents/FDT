# Futures Debate Team — 期货交易辩论专家团 v6.3.1

> 🚀 **v6.3.1 缺陷修复（技术债 §2/§3 收尾）**：修复链分析 `build_symbol_map` 在 channel_breakout-only 摘要下的 `KeyError: 'symbols'`（迁移后数技源/观澜/探源独立 JSON，旧代码期望嵌套结构）——改为三源合并；`factor_timing._zscore` 全 NaN 防护消除运行期警告。
>
> 🧬 **v6.3.0 信号生产链路拆分（当前架构基线）**：`scan_all.py` 重构为纯通道突破信号源（移除 `--dual`/`layered_l1l4`/`factor_timing`/`true_layered`），落地 **P1 数技源信号+分析师能力架构**——数技源（通道突破）产出信号，观澜（L1-L4 技术指标）/ 探源（因子择时）为分析师按需能力，辩论流水线保持可用。本 README 基于权威流程文档（`docs/business_flow.md`、`docs/harness/02-lifecycle.md`、`rules/futures-debate-team_rules.md`、`pipeline/runner.py`、`scheduler/tasks.py`）梳理，版本号唯一真相源为 `pyproject.toml`。

## 类型

Team 型（10 角色多 Agent 协作团队，全 Agent 自进化）

## 快速开始

通过 LLM 对话直接使用，无需手动操作：

```
"全量分析商品期货"
"分析螺纹钢期货的多空博弈情况"
"对比铜期货的多空论点"
```

系统自动执行 6 阶段完整流程：信号生产（数技源）→ 产业链分析 → 闫判官筛选定方向 → 研究员供弹 → 多空辩论 → 风控审核 → 方案输出。

## 系统架构

```
🔴 自进化前置（所有模式强制，全自动）
     │   检测未验证裁决 → validate_verdicts.py
     │   已验证≥5条 → calibrate_weights.py → evolve_agents.py
     │   检查 debate 新样本≥50 → ML TrainingOrchestrator.run_daily_check()
     │   加载最新 calibration.json + agent_profiles.json
     ▼
P1  数技源信号+分析师能力扫描（并行，各自独立 JSON）
     ├─ 数技源 scan_all.py (channel_breakout 默认)
     │     产出: full_scan_summary_{date}.json        ← 通道突破主信号
     ├─ 观澜   run_l1l4_scan.py (technical-analysis)
     │     产出: full_scan_l1l4_{date}.json           ← L1-L4 技术指标
     └─ 探源   run_factor_timing_scan.py (fundamental-data-collector)
           产出: full_scan_factor_timing_{date}.json  ← 5 因子择时信号
     信号检查闸门：通道突破候选 |total| < DEBATE_ENTRY_MIN_ABS(=20) 则提前终止
     ▼
P1.5 产业链分析                    链证源(commodity-chain-analysis)
     │                           产出: chain_analysis_{date}.json（景气度 + redundant_pairs）
     │                           基于通道突破品种，不做全覆盖、不下多空
     ▼
P2  闫判官筛选辩论品种+定方向       闫判官(judge)
     │                           debate_brief.py 计算辩论价值评分 → 精选候选（定正方方向）
     │                           同链冗余硬过滤(r>0.80 保留最强)
     ▼
P3  研究员并行供弹                 观澜(技术面禁WebSearch) + 探源(基本面允WebSearch)
     │                           中立产出，verdict=null；消费 P1 数技源+分析师数据 + WebSearch 基本面事实
     ▼
P4  多空辩论                      证真(正方) + 慎思(反方)
     │                           基于研究员资料提炼论据，禁止自行搜索，动态正反方交叉质询
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
| **观澜** | technical | | | | ● 技术面供弹 | | |
| **探源** | fundamental | | | | ● 基本面供弹 | | |
| **链证源** | chain-analyst | | ● 产业链 | | | | |
| **闫判官** | judge | | | ● 选品种+定方向 | | | ● 裁决 |
| **证真** | affirmative | | | | | ● 正方论据 | |
| **慎思** | opposition | | | | | ● 反方论据 | |
| **策执远** | strategist | | | | | | ● 交易方案 |
| **风控明** | risk | | | | | | ● 6层风控审核 |
| **明鉴秋** | team-lead | ● 启动+调度 | | | ● 轮询传递 | ● 调度 | ● 归档+报告 |

> 注：run_l1l4_scan.py（观澜L1-L4）与 run_factor_timing_scan.py（探源因子择时）在 P1 作为自动化脚本预产数据；但**观澜/探源作为 LLM 分析师 Agent 并不在 P1 工作**——它们在 P3 研究员供弹阶段才被 spawn，消费已产数据 + WebSearch 补充事实。L1-L4 / 因子择时是分析师内在能力，不是阶段工作对照。

## 核心特色

期货交易辩论专家团不是「一个模型给建议」，而是一套**多 Agent 交叉质询 + 自进化闭环**的 CTA 决策系统。区别于普通量化脚本的关键能力：

### 1. 10-Agent 辩论架构（角色边界清晰）
10 个专职 Agent 各司其职、相互制衡：**数技源只采信号不下结论、研究员只供事实不打分、辩手只提炼论据不搜数据、闫判官只裁决不分析、策执远只出方案不改方向、风控明只审核不站队**。任何单一维度的噪声都需经结构化辩论才能进入最终决策。

### 2. P1 数技源信号+分析师能力架构（v6.3.0）
通道突破（数技源）、L1-L4 技术指标（观澜）、因子择时（探源）三者**各自独立脚本、独立 JSON 产出**，经 `debate_brief.py` 命令行读取后合并。信号生产与分析解耦，任一模块失败不影响其他模块，辩论流水线保持可用。

### 3. 通道突破主信号源（唐奇安 + 布林带）
主信号为通道突破（DC20/DC55 唐奇安通道 + 布林带挤压/突破 + 量能确认），全部信号经辩论，**无直接推荐通道**。ADX 角色反转：低位鼓励启动、高位警示过热（仅作辅助，不作致命伤）。信号分级（STRONG/WATCH/WEAK/NOISE）驱动辩论深度，强信号快速裁决、分歧信号充分交锋。

### 4. 自进化闭环（validate → calibrate → evolve → ML）
每轮辩论结束后自动触发反馈闭环：拉 T+1 K 线**验证**裁决方向 → 累计≥5 条已验证样本**校准**评分权重 → 累计≥5 样本**进化** 7 个 Agent 参数（仓位系数/RR 目标/ATR 乘数等）→ 新样本≥50 条触发 LightGBM **增量训练**与部署。系统「每轮辩论都让下一次更聪明」，无需人工干预。

### 5. 5 层鲁棒性防线（L1–L5）
L1 产出校验（schema 校验）→ L2 熔断降级（重试最多 2 次 + D06 裁决降级）→ L3 信号门（通道突破触发文件强制走完整 P3-P5）→ L4 路径自发现（CLI 参数/环境变量/自动发现三级 fallback）→ L5 健康自检（数据源/路径/脚本/Agent 自检）。确保辩论流程在任何异常下**不静默断裂**。

### 6. 最终信号验证门禁（v6.1）
`validate_final_signals.py` 确定性信号复查器，6+ 条硬性规则（action 合法性、交易参数一致性、方向-价格一致性 BULL→target>entry>stop / BEAR→target<entry<stop、RR≥0.5、品种交叉校验、confidence/grade 合法性），推送给交易系统前的**最后一道门**。

### 7. A2A 协议文件桥（v6.2）
`agent-card.json` 声明 FDT 符合 Google A2A v1.0 规范的技能/输入输出 Schema；`run_debate.py a2a`（或 `finalize` 末尾自动）导出 `a2a_results.json`（jsonrpc 信封 + 每品种 artifact），使辩论裁决可被任意 A2A 兼容系统直接消费。

### 8. 品种知识库（v5.9）
五层知识体系（L1 静态画像 / L2 驱动因子 / L3 有效论证模式 / L4 关键价位 / L5 数据源质量），`extract_knowledge.py` 质量门控（confidence≥0.6 才入库）+ EMA 在线更新 + 老化保护，辩论后自动萃取，当期数据与知识库矛盾时以当期数据为准。

### 9. OmniOpt 策略族分类（v5.5）
F1-F5 论证策略族（技术面/基本面/持仓/宏观/套利）分类系统 + 品种×策略族适应性矩阵（EMA 在线更新），闫判官加权裁决（WEAS）按策略族对品种的历史胜率加权，使裁决可量化、可追溯。

### 10. 周期发现层（v5.12）
零硬编码 `PERIOD_REGISTRY`（daily/240m/120m/60m/30m 全参数化），`period_fitness.py` 对候选品种自动选最优交易周期与执行风格，方向正交（非硬指令），缺失时优雅降级日线默认。

### 11. 数据路由与溯源（FDC）
所有期货数据统一经 `futures_data_core`（FDC）调度，外部模块不直接调用任何数据 API。每次辩论 `debate_results.json` 顶层写入 `data_manifest` 溯源字段（来源/日期/时效），报告数据源标注穿透到采集器（如「通达信 TQ-Local」），禁止裸数据。

## 一键辩论驱动（run_debate.py）

> 编排收敛层：把每轮「扫描 → 识别触发品种 → 标准化 spawn 计划 → assemble/extract/report」的易碎手工步骤收进单一脚本。**spawn 仍是团队主管（WorkBuddy Agent）的固有职责**，脚本产出标准化的 spawn 计划 JSON 供主管执行，不替代 Agent 调度。

```bash
# 1) 数技源扫描 + 观澜/探源按需分析
python skills/quant-daily/scripts/scan_all.py -o <dir> -p full_scan_summary
python skills/technical-analysis/scripts/run_l1l4_scan.py --output-dir <dir>
python skills/fundamental-data-collector/scripts/run_factor_timing_scan.py --output-dir <dir>

# 2) 产出 spawn 计划（主管据此 spawn 各辩论 Agent）
python scripts/run_debate.py plan \
  --scan <dir>/full_scan_summary_{date}.json --workspace <dir>/

# 3) 主管按 spawn 计划执行各阶段 Agent，产物落 <dir>/

# 4) 组装 debate_results.json（含顶层 data_benchmark 数据基准字段）
python scripts/run_debate.py assemble --workspace <dir>/

# 5) 批量知识萃取（复用内置质量门控，conf<0.6 自动跳过）
python scripts/run_debate.py extract --workspace <dir>/

# 6) 信号复查（终检：推送给交易系统前的最后一道门）
python scripts/validate_final_signals.py --input debate_results.json --scan full_scan_summary_*.json

# 7) 生成辩论报告（统一调 phase3 --debate，单/多品种通用）
python scripts/run_debate.py report --workspace <dir>/
```

**关键约定**：`data_benchmark`（数据基准时间戳，如 `2026-07-11 15:00 收盘`）由 `assemble` 写入 `debate_results.json` 顶层，`phase3 --debate` 渲染到报告「数据基准」字段，便于判别行情时效。

## 10 角色详情

| # | 角色 | Agent ID | 对应Skill | 核心职责 |
|:-:|:----|:---------|:----------|:--------|
| 1 | 🎯 明鉴秋 | `futures-debate-team-team-lead` | — | 选题+调度+汇总+流程守护 |
| 2 | 📡 数技源 | `futures-datatech` | `quant-daily` | 运行通道突破全量扫描，产出原始信号（不下结论） |
| 3 | 🔗 链证源 | `futures-chain-analyst` | `commodity-chain-analysis` | 产业链事实描述+景气度分析（不下多空） |
| 4 | ⚪ 闫判官 | `futures-judge` | `debate-judge` | 选辩论品种+定方向+评分+裁决 |
| 5 | 🧑‍🔬 观澜 | `futures-technical-researcher` | `quant-daily` + `technical-analysis` | L1-L4 信号（按需能力）+ P3 技术分析/支撑阻力（中立，verdict=null，禁WebSearch） |
| 6 | 🧑‍🔬 探源 | `futures-fundamental-researcher` | `fundamental-data-collector` | 因子择时（按需能力）+ P3 基本面分析（供需库存利润，允许WebSearch） |
| 7 | 🔵 证真 | `futures-affirmative-debater` | `debate-argument-builder` | 正方论据（动态方向，禁止自行搜索） |
| 8 | 🔴 慎思 | `futures-opposition-debater` | `debate-argument-builder` | 反方驳论（动态方向，禁止自行搜索） |
| 9 | 📋 策执远 | `futures-trading-strategist` | `debate-trading-planner` | 合约选型+执行方案 |
| 10 | 🟡 风控明 | `futures-risk-manager` | `debate-risk-manager` | 6层风控引擎：选锚/仓位/动态/覆写/反馈/组合 |

## 信号解读

### 通道突破信号（主信号）

| 信号类型 | 含义 | 权重组合（单一真相源：`skills/quant-daily/scripts/config/settings.py`） |
|:---------|:-----|:---------|
| channel_breakout | 通道突破 | DC20 + DC55(唐奇安) + BB(布林带) + 成交量 加权组合 |
| trend_confirmation | 趋势确认 | DC55 中期位置 + 趋势方向 |
| bb_squeeze_prebreakout | 布林带挤压预警 | BB 带宽低位 + 挤压状态 |

> 信号权重均从配置读取，禁止在代码/文档写死，调参只改 `settings.py` 一处。

### 评分等级

| 等级 | 绝对值范围 | 含义 |
|:----|:--------:|:-----|
| STRONG | ≥ 60 | 最强信号，多层通道共振 |
| WATCH | 40-59 | 重点信号，方向一致 |
| WEAK | 20-39 | 信号一般，需验证 |
| NOISE | < 20 | 噪音，忽略（不进入辩论候选） |

辩论入口阈值单一真相源：`config/settings.DEBATE_ENTRY_MIN_ABS = 20`，`|total| ≥ 20`（WEAK 及以上）才进入辩论候选。

## 数据源

数据路由统一经 `futures_data_core`（FDC）管理，外部模块不直接调任何数据 API。

| 数据源 | 盘中优先级 | 盘后优先级 | 实时价 | 依赖 |
|:-------|:-----:|:----:|:------:|:-----|
| **通达信 TDX TQ-Local** | 0（第一） | 0（第一） | ✅ close=实时价 | 需通达信客户端 |
| **TqSDK 免费版** | 1 | — | ✅ last=实时价 | `pip install tqsdk` + 免费账号 |
| **东方财富** | 2 | 1 | ✅ close | FDC 内置 |
| **AKShare** | 3 | 2 | ✅ close | FDC 内置 |
| **WebSearch / 100ppi 生意社** | 兜底 | 兜底 | ❌ | FDC 内置（基本面现货/资讯） |

实时行情主链（降级回退）：**盘中 TDX → TqSDK → 东方财富 → AKShare；盘后 TDX → 东方财富 → AKShare**。

中国期货市场日线惯例：一根 TqSDK 日线覆盖一个完整交易日（前夜盘 21:00 → 当日日盘 15:00），`close` 为该交易周期内最后成交价。

## CLI 使用

```bash
# 通道突破全量扫描（数技源，唯一信号生产者）
python skills/quant-daily/scripts/scan_all.py -o ./reports -p full_scan_summary
python skills/quant-daily/scripts/scan_all.py --symbols CU,RB,PK

# 观澜 L1-L4（按需分析能力）
python skills/technical-analysis/scripts/run_l1l4_scan.py --output-dir ./reports

# 探源 因子择时（按需分析能力）
python skills/fundamental-data-collector/scripts/run_factor_timing_scan.py --output-dir ./reports

# 辩论候选精选（按辩论价值评分分离候选）
python skills/quant-daily/scripts/signals/debate_brief.py \
  reports/full_scan_l1l4_*.json reports/full_scan_factor_timing_*.json \
  --select-debate chain_analysis.json --min-count 20

# 辩论驱动：plan → spawn → assemble+validate → report
python scripts/run_debate.py plan --scan reports/full_scan_summary_*.json --workspace .
python scripts/run_debate.py finalize --scan reports/full_scan_summary_*.json --workspace .

# 信号复查（终检，推送给交易系统前必跑）
python scripts/validate_final_signals.py -i debate_results.json -s full_scan_summary_*.json --json

# 全自动无人值守流水线（pipeline/runner.py：扫描→链分析→debate_brief→assemble→report→history）
python pipeline/runner.py
```

## 依赖的 Skills

| Skill | 版本 | 用途 |
|:------|:----|:-----|
| `quant-daily` | v2.15.0 | 数据采集+通道突破信号（`scan_all.py` 数技源） |
| `futures-trading-analysis` | v3.11.0 | 主流程编排+5层鲁棒性+A01文件通信+报告生成+A2A文件桥 |
| `fdt-spawn-debate` | v1.1 | Agent spawn流程+A01文件通信协议 |
| `commodity-chain-analysis` | v2.17.0 | 产业链分析（P1.5） |
| `fundamental-data-collector` | v1.5.0 | 基本面分析+因子择时（探源按需能力 + P3 研究员） |
| `technical-analysis` | v2.3.0 | 技术面分析+支撑阻力（观澜按需能力 + P3 研究员） |
| `debate-argument-builder` | v2.3.0 | 正反方论点构建 |
| `debate-judge` | v2.0.1 | 辩论裁决 |
| `debate-risk-manager` | v4.1.0 | 风控审核（6层引擎） |
| `debate-trading-planner` | v2.1.0 | 交易方案规划 |

## 核心铁律

| 铁律 | 内容 |
|:----|:------|
| **时序铁律** | 链证源先于闫判官 → 闫判官决策 → 研究员供弹 → 辩手立论，顺序不可逆 |
| **禁止串线** | Agent 间不得 SendMessage，统一写文件由明鉴秋传递（A01 文件优先通信） |
| **文件就绪** | 下游必须 poll 上游文件就绪（存在 + size 稳定 ≥5 秒） |
| **辩手禁搜** | 证真/慎思不得自行 WebSearch，论据必须来自研究员资料 |
| **胶水代码零容忍** | 所有操作通过已有 skill 的 CLI/库函数/Agent spawn 完成 |
| **记忆独立** | 专家团记忆仅写入自身 `memory/` 目录，不入宿主工作空间 |
| **鲁棒性防线** | L1-L5 五层防线（校验+降级+信号门+路径发现+自检）确保流程不静默断裂 |
| **P5降级 D06** | 闫判官 2 次 spawn 失败 → 明鉴秋基于 P3+P4 论据独立裁决 |
| **阈值单一真相源** | 辩论入口阈值/信号权重均从 `config/settings.py` 读取，禁止写死 |

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
| fdt_paths.py | v1.0 | 单一路径真相源，自动检测 FDT 根目录 |
| memory_enforcer.py | v1.0 | 零参数记忆归档 + 工作空间日志校验 |
| validate_final_signals.py | v1.0 | 确定性信号复查器：6+ 条硬性规则，确保交易系统收到无矛盾信号 |
| run_debate.py | v1.1 | 辩论主动驱动层：plan/assemble/extract/report/a2a 子命令，标准化 spawn 计划 |

## 依赖安装

```bash
# 核心依赖
pip install numpy pandas pyyaml duckdb pydantic psutil lightgbm scikit-learn

# TqSDK（第一数据源，必须）
pip install tqsdk

# FDC 额外依赖
pip install httpx beautifulsoup4 lxml openpyxl

# 可选：通达信 TQ-Local 采集器（本地 HTTP 服务）
pip install httpx beautifulsoup4
```

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v6.3.1** | **2026-07-14** | **🐛 缺陷修复（§2/§3 收尾）**：链分析 `build_symbol_map` 多源合并修复（消除 channel_breakout-only 摘要 `KeyError: 'symbols'`，改为 summary+l1l4+ft 多文件合并）；`factor_timing._zscore` 全 NaN 防护（消 RuntimeWarning）；新增回归测试 `tests/commodity-chain/test_chain_full_analysis.py`。版本：包 6.3.0→6.3.1；commodity-chain-analysis 2.16→2.17 / fundamental-data-collector 1.4→1.5。 |
| **v6.3.0** | **2026-07-14** | **🧬 信号生产链路拆分（技术债 §2/§3）**：`scan_all.py` 重构为纯通道突破信号源(channel_breakout)，移除 `--dual`/`layered_l1l4`/`factor_timing`/`true_layered`；L1-L4 迁 technical-analysis(`run_l1l4_scan.py`)，因子择时迁 fundamental-data-collector(`run_factor_timing_scan.py`)，P1 数技源信号+分析师能力架构落地；`pipeline/runner.py`+`scheduler/tasks.py` Step1 重写，`full_scan_summary_{date}.json` 精确匹配下游，辩论流水线保持可用。版本：包 6.2.0→6.3.0。 |
| **v6.1.0** | **2026-07-13** | **🔴 最终信号验证门禁**：新增 `scripts/validate_final_signals.py` 确定性信号复查器（6+条硬性规则：action合法性、交易参数一致性、方向-价格一致性BULL→target>entry>stop/BEAR→target&lt;entry&lt;stop、RR≥0.5、品种交叉校验、confidence/grade合法性）。`assemble()` 新增 `_derive_action()` 动作消歧——裁决→execute/hold/wait 三值映射，action≠execute 时自动清空所有交易参数。CLI修复：`report`/`extract`/`validate` 子命令不强制加载 scan 文件。`generate_intermediate_data()` 的 `decision` 字段从扫描信号改为读辩论裁决（根因修复：信号与策略不一致）。`phase3_generate_report.py` 新增 confidence 字符串→float 归一化（"高"→0.95/"中"→0.65/"低"→0.35）。 |
| **v6.2.0** | **2026-07-13** | **🔧 FDC v0.2.0 + A2A协议桥 + 置信度归一化**：FDC全面替代MSA(TqSDK免费版第一数据源)。新增A2A文件桥(`agent-card.json`+`export_a2a.py`+`run_debate.py a2a`子命令，`finalize`自动导出`a2a_results.json`)。`validate_final_signals.py`置信度英文→中文归一化(F02永久修复)。仓单日报/持仓排名/100ppi现货聚合迁入FDC。TqSDK全能力封装(28方法)。TickBar/TickData/SymbolInfo类型。连接复用优化(建连4.8s→0.2s)。CZCE大小写修复。|
| **v5.12.1** | **2026-07-11** | **🔧 版本对齐**：pyproject.toml 版本号同步(5.12.0→5.12.1)，无功能变更。 |
| **v5.12.0** | **2026-07-11** | **🧬 周期发现层里程碑**：新增 `skills/quant-daily/scripts/signals/period_fitness.py` 零硬编码周期发现引擎(`discover()`纯函数+`build_period_fitness()`批量产出)；`config/settings.py` 新增 PERIOD_REGISTRY(单一真相源，daily/240m/120m/60m/30m全enabled)+PERIOD_FITNESS_WEIGHTS+EXEC_STYLE_MAP；`daily_debate.py` 对候选品种算周期发现并写入 `debate_trigger.json.period_fitness_path`；3个决策Agent MD(闫判官/策执远/风控明)新增「周期发现消费」段。 |
| **v5.11.0** | **2026-07-11** | **🧬 辩论流水线工程化里程碑**：新增 `scripts/run_debate.py` 主动驱动层（扫描→按DEBATE_ENTRY_MIN_ABS识别触发品种→标准化spawn计划JSON→assemble/extract/report子命令，替代手写胶水代码）；`extract_knowledge.py` 增 `ingest_from --from debate_results.json` 批量萃取；`channel_breakout_strategy` 量能前置门(vol_ratio≥normal_lower_ratio才授DC20 base分)；`phase3 --debate` 子集兼容(adapt兼容reasoning顶层/嵌套两格式+去全量intermediate_data.json硬依赖+数据基准时间戳从debate_results顶层读取)。额外修复：config.settings漂移+phase3 KeyError:slice真根因。 |
| **v5.10.0** | **2026-07-11** | **🔧 信号体系统一与能力裁剪**：辩论入口阈值统一为 `config.settings.DEBATE_ENTRY_MIN_ABS=20`，全链路单一真相源，删除 `signal_classifier.py` 死代码；移除120m(2小时)信号监控与参数优化能力(4个自动化+相关代码全删)；删除盘前预计算死缓存。版本号统一 pyproject.toml 为唯一源。 |
| **v5.9.0** | **2026-07-11** | **🧠 品种知识库 v1.0**：自建品种分析逻辑知识库系统。5层知识体系(L1静态画像/L2驱动因子/L3有效模式/L4关键价位/L5数据质量)；`scripts/extract_knowledge.py` 萃取引擎(质量门控confidence≥0.6+原子写入+EMA在线更新+老化保护)；`scripts/init_knowledge_base.py` 初始化脚本(84品种从varieties.yaml+instrument_strategy_matrix批量初始化)；`memory/knowledge/{84品种}/` 目录；P6汇总后自动萃取(team-lead MD)；Agent进化后自动萃取(evolve_agents.py)；6个Agent消费端注入(闫判官/观澜/探源/证真/慎思/策执远)；每日22:00老化维护自动化。| **🏗 系统架构里程碑—FDT自包含运行时**：`fdt_paths.py`单一路径真相源(三级fallback自动检测FDT根目录)+`memory_enforcer.py`零参数记忆归档+`data/`+`reports/`内部产出目录+A01文件通信协议(tiered降级)。Agent MD v5.3(开篇动作清单记忆路由)+futures-trading-analysis v3.7.1+fdt-spawn-debate v1.1。系统边界清晰——产出和记忆在FDT内部，工作空间仅做镜像副本。修复：Agent SendMessage在自动化context路由失效(2次事故)→文件优先通信协议永久修复。 |
| **v5.7.0** | **2026-07-10** | **🏗 驾驭工程（Harness Engineering）完整落地**: 15项差距全部修复，成熟度4.0→4.7。Phase1正确性修复(G1 Pydantic配置校验/G2 trace_id全链路/G3 pipeline日志统一/G4 bootstrap动态版本)→Phase2测试补齐(G5 pipeline集成10用例/G6 scheduler集成10用例/G7覆盖率扩展到全skill/G8 memory集成9用例)→Phase3运维增强(G9 graceful drain/G10兼容矩阵/G13熔断可配/G14合约版本迁移28条路径)→Phase4体验优化(G11 APM-CS实时看板/G12 HTTP健康端点/G15 JSON结构化日志)。43用例全绿，contracts桥接层统一入口。|
| **v5.6.0** | **2026-07-09** | **🛡 5层鲁棒性架构**：L1产出校验(validate_agent_output.py)+L2熔断降级(debate_orchestrator.py+D06铁律)+L3信号门(daily_debate.py v2.0触发文件)+L4路径自发现(phase3 v3.2 CLI参数化)+L5健康自检(selfcheck.py)。D05-D06辩论完整性铁律。闫判官spawn Bug修复(futures-judge.md v2.1)。JSON产出规范J01-J03注入慎思+证真Agent MD。|
| **v5.5.0** | **2026-07-09** | **🧬 OmniOpt 分类法集成**：F1-F5 论证策略族分类系统；品种×策略族适应性矩阵(EMA在线更新)；闫判官加权裁决(WEAS族加权预处理+族多样性检查)；正反方辩手输出格式扩展(含策略族标签) |
| **v5.4.0** | **2026-07-07** | **🧬 可观测性与自改进里程碑**：APM-CS五轴评分卡(D1-D5)+Telescope失败聚类；D1/D3/ViBench回放+held-out一致性裁判；D2 Acuity真实计算+成本感知PnL(COST_BPS)；D4纪律钳制enforce_discipline(R13/R14/R-resonance仓位上限)；D2信号退化标记/D5陈旧失败过滤/Stage3 self_improve脚手架；全周期K线(日/周/月/240m/60m/15m/5m/1m+自定义)；bug修复(MA60真实合约口径/scan_all原子写入/portfolio_backtest裸except/RuleChecker浮点边界/triggers闭包)；5门禁审计全100% |
| **v5.3.0** | **2026-07-07** | **🧬 通道突破策略里程碑**：唐奇安DC20/DC55+布林带替换三类信号为主信号源；TqSDK live模式盘中实时价(非backtest)；盘中/盘后自适应数据获取；信号检查闸门(无信号早停)；单策略默认(非--dual)；多数据源格式对齐(TDX/TqSDK/EM/AKShare统一schema)；TDX date字段str()防TypeError；日盘14:30自动化全流程含辩论团P0-P6；管理员手册合并入README；日线跨夜盘说明新增 |
| **v5.2.1** | **2026-07-07** | **🔧 全面修复**: ADX仅风控不参与评分+Agent输出格式统一+JSON Schema标准导出+时序通信铁律S01-S05+胶水代码清零 |
| **v5.2** | **2026-07-06** | **🧬 架构重构**: 三类信号替代L1-L4+因子择时为主信号源，全部信号全辩论，ADX角色反转，证真/慎思动态正反方 |
| **v5.1** | **2026-07-06** | **🔄 Phase 1独立化**: 内建调度器scheduler/、bootstrap一键启动、daemon看门狗、自循环闭环升级 |
| **v5.0** | **2026-07-06** | **🧬 自进化闭环里程碑**: P0进化链(validate→calibrate→evolve)、全9Agent自进化、裁决修正经验库 |
| **v4.5** | **2026-07-06** | Bridgewater方法论落地: 五维辩论评分+研报质量过滤+辩论档案+ML训练自动化 |
| **v4.4** | **2026-07-05** | P0+P1全面实施: 情感因子+流动性风险+交易摩擦+DAG并行+记忆反思 |
| **v4.2** | **2026-07-05** | P3全量实现: 事件日历+ML特征管道+方向分类器+PnL反馈闭环+风控6层引擎 |
