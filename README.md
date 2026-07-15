# Futures Debate Team — 期货交易辩论专家团 v8.1.7

一套 10-Agent 多角色交叉质询的 CTA 决策系统。不是「一个模型给建议」——是**多头分析员和空头分析员独立辩论、闫判官在论据中裁决**。扫描信号只是起点，辩论结论才是终局。

---

## 系统架构

三层结构：**策略管线 → 多空辩论 → 自进化闭环**。

### 第一层：8 策略并行管线

每天开盘前，8 个策略并行扫描全品种，各自独立打分。**不融合**（NO_FUSION）——方向冲突的信号双方都保留，原封不动送给辩论环节。

| 策略 | 类型 | 覆盖 | 机制 |
|:-----|:-----|:----:|:-----|
| `trend_following` | 趋势跟踪 | 28 品种 | 唐奇安通道 + Keltner + Supertrend + SAR + Chandelier + MACD + TSMOM + Dual Thrust 十信号共振投票 |
| `mean_reversion` | 均值回归 | 条件触发 | RSI 极端 / CCI 极值 / BB 带宽 + ADX<25 + KF 制度过滤 + BB 带宽压缩门禁 |
| `arbitrage` | 套利 | 配对品种 | 跨品种 6 组产业链配对 Z-score + 跨期价差 + 期现基差 |
| `macro_regime` | 宏观制度 | 可激活 | 5 板块 46 品种轮动，宏观信号注入触发 |
| `multi_factor` | 多因子量化 | 12 品种 | 量价 / 产业 / 宏观 / 另类四维加权（40/30/20/10），接东方财富宏观公开源 |
| `pairs_reversion` | 配对回归 | 条件触发 | Engle-Granger 协整 + Hurst 门禁 + KF z + 方差比检验；贵腿做空 + 便宜腿做多 |
| `spread_reversion` | 跨期价差回归 | 条件触发 | 近远月 OU 拟合 + KF z；价差偏高→空近多远，偏低→多近空远 |
| `basis_reversion` | 期现基差回归 | 条件触发 | 每日 100ppi 基差快照追溯 JSONL 日志；交割收敛力驱动 OC |

所有策略共用三层门禁防御伪信号：
- **震荡市门禁**：ADX<25（趋势强度）+ BB 带宽压缩（低波动态）+ KF 制度过滤（均值偏移检测）
- **去趋势门禁**：Hurst 指数（趋势 vs 回归分类）+ 方差比检验（随机游走 vs 结构检验）
- **验证器**：OI/基差/低波/伪突破 P0-4 拦截，共 19 种校验模式

### 第二层：10 Agent 辩论制衡

```
数技源 → 8 策略管线 → 各策略独立打分，不融合
                            ↓
                   闫判官 初判 → 辩论计划
                            ↓
          ┌──── 多头分析员（独立举证≥3 条） ────┐
          │                                      │
          └──── 空头分析员（独立举证≥3 条） ────┘
                            ↓
                     闫判官 终裁
                   （多空论据中裁决）
                            ↓
                  策执远 → 交易方案
                            ↓
                   风控明 → 6 层红线审核
```

每个角色只做自己的事：数技源只产信号不下结论、观澜只做技术分析不判断方向、多空分析员只列论据不裁决、闫判官只裁决不分析、策执远只出方案不改方向、风控明只审核不站队。没有全能的 Agent，只有分工明确的团队。

辩论结论天然优先于扫描方向——已验证场景：某品种扫描多头 +514 强信号，辩论后空头论据充分，闫判官判 bear。扫描分高不等于方向对。

### 第三层：自进化闭环

每轮辩论结束后：T+1 回测验证裁决方向 → 校准评分权重 → 进化 Agent prompt → 累计 50+ 样本触发 LightGBM 增量训练。

---

## 策略管线详解

### 趋势跟踪 — trend_following

10 个子信号共振投票。通道突破（DC20/DC55）为骨架，Keltner/Supertrend/SAR/Chandelier 为辅助，TSMOM 时间序列动量捕捉跨周期信号（1/3/6/12 月收益合成），Dual Thrust 覆盖日内突破。十票定方向，不依赖单一指标。

### 均值回归体系

三层回归策略构成完整的做空做多覆盖：

| 回归维度 | 策略 | 数据源 | 入口 |
|:---------|:-----|:------|:----|
| 单合约价格反转 | MeanReversion | tech_list RSI/CCI/BB | RSI<25 / CCI<-200 / BB<0.1 → 多；反方向→空 |
| 跨品种配对 | PairsReversion | kline_data 两腿历史 | Engle-Granger 协整残差 + Hurst 门禁 + KF z |
| 跨期价差 | SpreadReversion | xtquant 近远月 kline pre-collected | OU 拟合 + KF z；Z>2 出信号 |
| 期现基差 | BasisReversion | 100ppi 现货 + JSONL 日志 | 同 OU+KF 框架，交割收敛力驱动 |

全部均值回归策略共用 KF 自适应 z-score（替代固定窗口滚动 Z），自然处理换月跳开和波动率突变。附加方差比检验作为统计准入。

### 多因子量化 — multi_factor

四维 13 因子加权（量价/产业持仓/宏观/另类）。宏观因子 PMI/LPR1Y 直接对接东方财富宏观数据中心（免费公开源），不再硬填 0。warrant 仓单因子覆盖 SHFE/DCE/CZCE/GFEX 四所，真实全量源。

---

## 快速开始

```bash
# 全量扫描 + 辩论
python scripts/fdt_cli.py pipeline --mode no-filter --pipeline
python scripts/run_debate.py plan --scan <workspace>/scan_daily_<date>.json
python scripts/run_debate.py finalize --scan <workspace>/scan_daily_<date>.json

# 或直接对 LLM 说
"全量分析商品期货"
"分析螺纹钢期货的多空博弈"
```

产出：`scan_daily_ranking_{date}.html`（全品种排名报告）+ `debate_report_{date}.html`（完整辩论报告）。

---

## 版本脉络

| 基线 | 范围 |
|:-----|:-----|
| v6.4–v7.6 | 策略层插拔化重构，7 策略全覆盖 |
| v8.0.0–v8.0.2 | 多因子量化 + 宏观因子接入 |
| v8.0.3–v8.0.7 | 趋势跟踪扩展：Keltner/Supertrend/SAR/Chandelier/MACD + TSMOM + Vol Targeting + Dual Thrust + Turtle 完整系统 |
| **v8.1.0–v8.1.7** | 均值回归体系重构：协整配对 + 跨期价差 OU + 期现基差 OU + KF 自适应 z + 方差比门禁 + BB 带宽压缩门禁，**期货做空回归维度全线补齐** |

---

*FDT 是一套持续演化的系统。策略管线、辩论制衡、自进化闭环三者相互独立又相互加强。没有银弹，只有制衡。*
