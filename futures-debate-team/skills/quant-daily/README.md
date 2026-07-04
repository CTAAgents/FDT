# quant-daily — 商品期货量化分析一体化

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-2.1.0-orange)

**quant-daily** 是一套面向中国商品期货市场的真分层打分量化分析系统，覆盖 **数据采集 → 指标计算 → 7因子截面排序 → 九宫格左右侧分类** 全流程。

- 覆盖 **62个主力品种**，14个板块
- 双轨数据源：**通达信TQ-Local**（实盘）+ **AKShare**（回测，含真实持仓量OI）
- **真分层打分**：7因子独立裁判 + 截面排序 + 秩变换（Fama-French 1992学术正统）
- **九宫格模糊分类器**：高斯隶属度区分左右侧信号，消除硬阈值跳跃
- **D7期限结构因子**：期货专属维度，基于近远月价差
- **反向交易信号模式**：`--reverse` 自动转换负IC为可交易策略
- **回测框架**：107截面×59品种，IC评估 + 多空价差 + 分层收益
- **Data Quality Circuit Breaker**：7道全局防呆机制

## 快速开始

### 安装

```bash
git clone git@github.com:CTAAgents/experts.git
cd experts/skills/quant-daily
pip install -e .
```

### 全品种信号扫描（推荐）

```bash
# 真分层打分 + 九宫格分类 + 反向信号（默认）
python scripts/scan_true_layered.py --reverse

# 指定品种
python scripts/scan_true_layered.py --symbols PK,RB,HC --reverse

# 正常模式（做多排名高品种）
python scripts/scan_true_layered.py -o ./reports
```

### 回测

```bash
# 真分层回测（AKShare数据源，107截面）
python -m backtest.backtest_true_layered
```

## 因子法官席（7独立裁判）

| # | 风格 | 因子 | 原始指标 | 九宫格归属 |
|:-:|:---|:---|:--------|:----------|
| D1 | 趋势 | ROC10 | 最近10日变化率 | TrendScore |
| D2 | 回归 | -BIAS乖离率 | 价格偏离MA20的负值 | RegScore |
| D3 | 回归 | -(RSI14-50) | RSI以50为中点的反向 | RegScore |
| D4 | 资金 | OI_CHANGE_PCT | 持仓量变化率 | — |
| D5 | 资金 | CMF21 | 21日资金流量 | — |
| D6 | 确认 | 放量×方向 | 量比乘以价格变动方向 | — |
| D7 | **期限** | **term_signal** | 期限结构(contango~/backwardation~) | RegScore |

## 九宫格左右侧分类

基于高斯隶属函数的模糊九宫格分类器，输入 RegScore 和 TrendScore 输出：

| 格子 | Reg | Trend | 方向 | 强度 | 含义 |
|:---:|:---:|:----:|:---:|:----:|:----|
| 强多区 | H | H | +1 | 1.0 | 双击信号 |
| 左侧多 | H | L/M | +1 | 0.5 | 回归驱动，需确认 |
| 趋势多 | M | H | +1 | 0.3 | 趋势跟随 |
| 混沌区 | M | M | 0 | 0 | 观望 |
| 强空区 | L | L | -1 | 1.0 | 双击信号 |
| 左侧空 | L | H/M | -1 | 0.5 | 回归驱动，需确认 |

## 回测绩效（107截面×59品种）

| 持有期 | IC均值 | IC胜率 | t值 | Top10多空价差 |
|:-----:|:-----:|:-----:|:---:|:------------:|
| 5日 | -0.004 | 46% | -0.21 | -0.06% |
| 10日 | -0.028 | 47% | -1.70 | -0.32% |
| 20日 | **-0.039** | 43% | **-2.33** | **-0.75%** |

IC 偏负 → 做空排名高品种（反向操作），20日持有期统计显著。

## 版本历史

- **v2.1.0** (2026-07-04): 九宫格模糊分类器 + D7期限结构因子 + 代码审计17轮
- **v2.0.0** (2026-07-04): 真分层打分设为默认，新增 `--reverse` 反向模式，回测框架
- **v1.1.0** (2026-07-03): 权重优化，真分层评分系统v1
- **v1.0.0** (2026-07-02): 初始版本

## 许可

本项目基于 MIT 许可证开源。
