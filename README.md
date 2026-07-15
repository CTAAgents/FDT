# Futures Debate Team — 期货交易辩论专家团

一套 10-Agent 多角色交叉质询的 CTA 决策系统。8 策略管线并行扫描 → 多头空头独立举证辩论 → 闫判官终裁。扫描信号只是起点，辩论结论才是终局。

**v8.2.0 起支持独立运行模式** — 不依赖任何宿主平台，CLI + Web Dashboard + 调度器 + LLM 驱动全自包含。

```bash
# 独立模式（无需 WorkBuddy）
python fdt_cli.py serve --workspace ./data     # Web Dashboard
python fdt_cli.py daemon start                 # 定时调度器
python scripts/agent_runner.py flow --workspace ./data  # 辩论流程
```

### 独立运行说明（v8.2.0+）

FDT 可脱离 WorkBuddy 独立运行。最小依赖：

```bash
pip install pandas numpy httpx psutil requests
pip install fastapi uvicorn jinja2    # Web Dashboard 可选
export FDT_LLM_API_KEY="sk-xxx"      # DeepSeek / OpenAI API Key
python fdt_cli.py serve              # 启动 Dashboard
```

核心命令：

| 命令 | 功能 |
|:-----|:------|
| `python fdt_cli.py serve --workspace <dir>` | Web Dashboard + REST API |
| `python fdt_cli.py daemon start` | 内置定时调度器（替代 cron） |
| `python fdt_cli.py self-check` | 系统自检 |
| `python scripts/agent_runner.py flow --workspace <dir>` | 全自动辩论流程 |
| `python scripts/notifier.py --channel wecom_bot --msg "..."` | 告警推送 |

完整规划见 `docs/independence-roadmap.md`。

---

## 业务逻辑

每天开盘前，系统自动执行一套固定管道：

**数据采集 → 策略扫描 → 辩论 → 裁决 → 方案 → 风控 → 报告**

各环节独立运行，前序的输出是后序的输入。任何一个环节可单独重跑。

---

## 数据流

```
┌──────────────────────────────────────────────────┐
│ 数据层: FDC 统一数据引擎                          │
│ TQ-Local(主) → TqSDK(备) → QMT(备) → 降级链     │
│ 采集: 日线120天K线 / 实时报价 / 持仓排名 / 仓单   │
│       基差(100ppi) / 宏观(东方财富) / 跨期价差    │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│ 策略层: 8 策略并行扫描 | NO_FUSION                │
│ 各策略独立打分，方向冲突不融合，全部送给辩论        │
│ 三层门禁: 震荡市(ADX+BB+KF) + 去趋势(Hurst+VR)   │
│          + P0-4 伪突破 19 种校验模式               │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│ 辩论层: 10 Agent 分工制衡                         │
│ 多头分析员独立举证 → 空头分析员独立举证            │
│ → 闫判官在多空论据中裁决 → 策执远定方案           │
│ → 风控明审核 → 报告输出                          │
└──────────────────────────────────────────────────┘
```

---

## 8 策略管线

| 策略 | 类型 | 做什么 | 触发条件 |
|:-----|:-----|:-------|:---------|
| `trend_following` | 趋势跟踪 | 10 子信号共振投票定方向 | 每日扫描，28 品种活跃 |
| `mean_reversion` | 价格反转 | RSI/CCI/BB 极端值回归 | ADX<25 震荡市 + KF 无偏移 |
| `arbitrage` | 套利 | 跨品种产业链配对 Z-score | 配对品种均活跃 |
| `pairs_reversion` | 配对回归 | EG 协整 + Hurst + KF z | 两腿均非趋势型 |
| `spread_reversion` | 近远月价差 | OU 拟合 + KF z | 价差偏离 > 2σ |
| `basis_reversion` | 期现基差 | OU 拟合 + KF z | 基差偏离 > 2σ |
| `macro_regime` | 宏观轮动 | 5 板块 46 品种制度切换 | 宏观信号到位 |
| `multi_factor` | 多因子加权 | 四维 13 因子评分 | 每日扫描，12 品种 |

均值回归四策略（`mean_reversion` + `pairs_reversion` + `spread_reversion` + `basis_reversion`）构成完整的做空做多覆盖：单合约价格反转、跨品种协整配对、跨期价差、期现基差 — 四个维度独立捕获回归机会，互不重叠。

---

## 10 Agent 辩论制衡

10 个 Agent 各司其职，**不越界、不重叠**：

| Agent | 职责 | 不做什么 |
|:------|:-----|:---------|
| 数技源 | 跑 8 策略管线产信号 | 不下方向结论 |
| 观澜 | 技术分析（支撑/阻力/POC） | 不判断多空 |
| 探源 | 基本面分析（产业链数据） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 多头分析员 | 独立列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 独立列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 在多空论据中裁决方向 | 不独立分析行情 |
| 策执远 | 制定可执行交易方案 | 不改裁决方向 |
| 风控明 | 6 层风控红线审核 | 不参与方向判断 |
| 明鉴秋 | 管道调度 + 报告归档 | 不介入内容决策 |

辩论结论**天然优先**于扫描方向。已验证场景：某品种扫描信号 bull+514（强多），辩论后空头论据更充分，闫判官判 bear。

---

## 自进化闭环

每轮辩论产出后自动触发反馈链：

**T+1 回测验证** → 累计 ≥5 条有效样本 → **校准评分权重** → **进化 Agent Prompt** → 累计 ≥50 样本 → **LightGBM 增量训练**

进化过程不依赖人工标注，用实际行情验证结果作为真值。

---

## 关键能力

| 能力 | 说明 |
|:-----|:------|
| NO_FUSION 策略管线 | 8 策略各自独立打分，方向冲突不融合、不掩盖、不平均 |
| 三层信号门禁 | 震荡市 + 去趋势 + P0-4 伪突破拦截，共 20+ 道校验 |
| KF 自适应 z-score | 全部均值回归策略用 Kalman Filter 替代固定窗口 Z，换月/波动率突变不产生假信号 |
| 多空辩论 | CJ 多头分析员和空头分析员独立举证，闫判官裁决 |
| A2A 协议 | Google A2A v1.0 兼容，agent-card + a2a_results.json |
| 品种知识库 | 辩论结论自动萃取入库，confidence≥0.6 门控 |
| 全量 HTML 报告 | 品种排名 + 辩论报告，可直接查看 |

---

## 快速开始

```bash
# 全量扫描
python scripts/fdt_cli.py pipeline --mode no-filter --pipeline

# 触发辩论
python scripts/run_debate.py plan --scan <workspace>/scan_daily_<date>.json
python scripts/run_debate.py finalize --scan <workspace>/scan_daily_<date>.json

# 或直接告诉 LLM
"全量分析商品期货"
"分析螺纹钢期货的多空博弈"
```

输出：`scan_daily_ranking_{date}.html`（全品种排名报告）+ `debate_report_{date}.html`（完整辩论报告）。
