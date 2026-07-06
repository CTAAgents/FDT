# Futures Debate Team — 期货交易辩论专家团 v5.3.0

> 🧬 **v5.3.0 通道突破策略里程碑**：唐奇安DC20/DC55+布林带替换三类信号为主信号源，TqSDK live模式盘中实时价，盘中/盘后自适应数据获取，信号检查闸门(无信号早停)，单策略默认(非--dual)，多数据源格式对齐，日盘14:30自动化全流程。

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
     │                           信号检查闸门：无STRONG信号则提前终止
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

| 数据源 | 优先级 | 盘中 | 盘后 | 实时价 |
|:-------|:-----:|:----:|:----:|:------:|
| **通达信TDX TQ-Local** | 0（最高） | ✅ 优先 | ✅ 优先 | ✅ close=实时价 |
| **TqSDK** | 1（降级） | ✅ live模式 | ✅ | ✅ close=实时价 |
| **东方财富** | 2 | ✅ | ✅ | ❌ |
| **AKShare** | 3（最后降级） | ❌ | ✅ | ❌ |

中国期货市场日线惯例：一根 TDX 日线覆盖一个完整交易日（前夜盘21:00→当日日盘15:00），`close` 为该交易周期内最后成交价。

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
```

## 依赖的 Skills

| Skill | 版本 | 用途 |
|:------|:----|:-----|
| `quant-daily` | v2.8.0 | 数据采集+通道突破信号计算 |
| `futures-trading-analysis` | v3.5.0 | 主流程编排+报告生成 |
| `commodity-chain-analysis` | v2.15.0 | 产业链分析 |
| `technical-analysis` | v2.2.0 | 技术面分析(支撑阻力+事件日历) |
| `debate-argument-builder` | v2.2.0 | 正反方论点构建 |
| `debate-judge` | v2.0.1 | 辩论裁决 |
| `debate-risk-manager` | v4.0.0 | 风控审核(6层引擎) |
| `debate-trading-planner` | v2.1.0 | 交易方案规划 |

## 核心铁律

| 铁律 | 内容 |
|:----|:------|
| **时序铁律** | 链证源先于闫判官 → 闫判官决策 → 研究员供弹 → 辩手立论，顺序不可逆 |
| **禁止串线** | Agent间不得SendMessage，统一写文件由明鉴秋传递 |
| **文件就绪** | 下游必须poll上游文件就绪(存在+size稳定≥5秒) |
| **辩手禁搜** | 证真/慎思不得自行WebSearch，论据必须来自研究员资料 |
| **胶水代码零容忍** | 所有操作通过已有skill的CLI/库函数/Agent spawn完成 |
| **记忆独立** | 专家团记忆仅写入自身memory/目录，不入宿主工作空间 |

## 输出文件结构

```
Commodities/Reports/商品期货深度分析/{date}/
├── full_scan_channel_breakout_{date}.json     ← 通道突破信号
├── research_snapshots/
│   ├── p2_chain_{symbol}.json                 ← 链证源产业链分析
│   ├── p2_judge_direction.json                ← 闫判官决策
│   ├── p3_technical_{symbol}.json             ← 观澜技术面快照
│   ├── p3_fundamental_{symbol}.json           ← 探源基本面快照
│   ├── p3_affirmative_{symbol}.json           ← 证真正方论据
│   ├── p3_opposition_{symbol}.json            ← 慎思反方论据
│   ├── p4_trading_plan_{symbol}.json          ← 策执远交易方案
│   ├── p4_risk_verdict_{symbol}.json          ← 风控明审核
│   └── p_judge_final_{trace_id}.json          ← 闫判官最终裁决
├── debate_results.json                        ← 汇总决策记录
└── debate_results.html                        ← HTML可视化报告
```

## 依赖安装

```bash
# 核心依赖
pip install numpy pandas pyyaml duckdb requests akshare pydantic psutil lightgbm scikit-learn

# TqSDK（可选，TDX降级备用）
pip install tqsdk
```

## 版本历史

| 版本 | 日期 | 变更 |
|:----|:----|:------|
| **v5.3.0** | **2026-07-07** | **🧬 通道突破策略里程碑**：唐奇安DC20/DC55+布林带替换三类信号为主信号源；TqSDK live模式盘中实时价(非backtest)；盘中/盘后自适应数据获取；信号检查闸门(无信号早停)；单策略默认(非--dual)；多数据源格式对齐(TDX/TqSDK/EM/AKShare统一schema)；TDX date字段str()防TypeError；日盘14:30自动化全流程含辩论团P0-P6；管理员手册合并入README；日线跨夜盘说明新增 |
| **v5.2.1** | **2026-07-07** | **🔧 全面修复**: ADX仅风控不参与评分+Agent输出格式统一+JSON Schema标准导出+时序通信铁律S01-S05+胶水代码清零 |
| **v5.2** | **2026-07-06** | **🧬 架构重构**: 三类信号替代L1-L4+因子择时为主信号源，全部信号全辩论，ADX角色反转，证真/慎思动态正反方 |
| **v5.1** | **2026-07-06** | **🔄 Phase 1独立化**: 内建调度器scheduler/、bootstrap一键启动、daemon看门狗、自循环闭环升级 |
| **v5.0** | **2026-07-06** | **🧬 自进化闭环里程碑**: P0进化链(validate→calibrate→evolve)、全9Agent自进化、裁决修正经验库 |
| **v4.5** | **2026-07-06** | Bridgewater方法论落地: 五维辩论评分+研报质量过滤+辩论档案+ML训练自动化 |
| **v4.4** | **2026-07-05** | P0+P1全面实施: 情感因子+流动性风险+交易摩擦+DAG并行+记忆反思 |
| **v4.2** | **2026-07-05** | P3全量实现: 事件日历+ML特征管道+方向分类器+PnL反馈闭环+风控6层引擎 |
