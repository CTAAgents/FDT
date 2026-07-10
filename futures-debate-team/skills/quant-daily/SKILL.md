---
name: quant-daily
version: 2.13.0
agent_created: true
description: 商品期货量化分析skill v2.13.0 — TDX对齐DC20(REF式+HIGH/LOW)+会话感知子周期+动量识别+R0归一化+TqSDK盘中优先。AKShare分钟→东方财富→TqSDK(15s超时保护)。
---

# quant-daily — 商品期货量化分析一体化

## 🔴 通道突破默认模式（v2.8.0+）

**quant-daily 默认策略 = channel_breakout（双通道突破）**，产出通道突破信号报告：

- **`channel_breakout`** (唐奇安DC20/DC55 + 布林带确认) → `full_scan_channel_breakout_{date}.json/.html`
- **L1-L4研究员辅助数据** → 仅通过 `--dual` 模式产出
- 所有通道突破品种必须辩论 —— 无直接推荐通道

```bash
# ✅ 默认命令：通道突破扫描（默认策略=channel_breakout）
python scripts/scan_all.py

# 双策略模式（如需研究员辅助数据）
python scripts/scan_all.py --dual
```

输出文件结构：
```
reports/
├── full_scan_channel_breakout_20260706.json        # 通道突破信号（主信号源）
├── full_scan_channel_breakout_ranking_20260706.html
```

### 职责边界

**quant-daily 只做客观计算**：
- 所有数据源对置信度统一为 1.0
- 输出通道突破信号（channel_breakout/trend_confirmation/bb_squeeze_prebreakout）为主信号
- L1-L4原始指标为辅助分析工具
- **不包含** 辩论推荐、品种分类、风险提示（所有信号必须辩论）

**闫判官 Agent 负责决策**：
- 读取signal_type字段，筛选通道突破品种
- 所有通道突破品种必须辩论，无直接推荐通道
- 决定正方方向
- 裁决最终方向
```

**默认模式**：`channel_breakout`（双通道突破，v2.8.0 新增）
其他模式可通过 `--strategy` 参数切换：

```bash
# 通道突破扫描（默认）
python scripts/scan_all.py

# 双策略模式（如需L1-L4研究员辅助数据）
python scripts/scan_all.py --dual

# 三类信号扫描（可选）
python scripts/scan_all.py --strategy three_signal

# L1-L4全品种扫描（研究员辅助）
python scripts/scan_all.py --strategy layered_l1l4

# 列出所有可用策略
python scripts/scan_all.py --list-strategies

# 指定输出目录+文件前缀
python scripts/scan_all.py -o ./reports -p full_scan

# 自定义品种
python scripts/scan_all.py --symbols PK,RB,B,UR
```

> **⚠️ 禁止使用 scan_true_layered.py（包括 --reverse）**

## 策略可插拔架构（v2.2.0）

量化打分策略已独立到 `scripts/strategies/` 目录，新增策略无需修改核心代码。

### 架构

```
data/   →  indicators/   →   strategies/   →   scan_all.py (入口)
 不变       不变              可插拔              --strategy 参数切换
```

### 目前策略

| 策略名 | 文件 | 状态 | 说明 |
|:-------|:-----|:----|:-----|
| `channel_breakout` | `strategies/channel_breakout_strategy.py` | ✅ **默认 v1.1** | 唐奇安DC20/DC55 + 布林带确认 + Tick逼近 + 大小写修复 |
| `three_signal` | `strategies/three_signal_strategy.py` | ✅ 可选 | 三类信号(突破/回踩/跳空) |
| `layered_l1l4` | `strategies/layered_l1l4.py` | ✅ 可选 | L1-L4四层累加(研究员辅助) |
| `true_layered` | `strategies/true_layered.py` | ⛔ 废弃 | 真分层打分(IC=-0.039不显著) |

```bash
# 使用三类信号策略（可选）
python scripts/scan_all.py --strategy three_signal --symbols PK,RB,B
```

### 如何新增一个策略

```python
# 1. 在 strategies/ 下新建文件，如 my_macd_strategy.py
from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy

class MyMACDStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_macd"          # --strategy 参数用的名称
    
    @property
    def display_name(self) -> str:
        return "我的MACD策略"      # 终端显示的中文名
    
    def score(self, tech_list, mode, kline_data=None, df_map=None):
        # tech_list: 指标引擎产出的每个品种的 tech dict
        # 每个 tech 包含: symbol, name, last_price, ADX, RSI14, MACD, MA等
        # df_map: pandas.DataFrame {sym: df}
        
        results = []
        for tech in tech_list:
            r = SignalResult(
                symbol=tech["symbol"],
                total=...,         # 带方向的总分
                abs_score=...,     # 绝对值
                direction="bull" if ... else "bear",
                grade="WATCH",     # STRONG/WATCH/WEAK/NOISE
                sub_scores={"d1": ..., "d2": ...},
                price=tech.get("last_price", 0),
                adx=tech.get("ADX", 0),
            )
            results.append(r)
        
        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)
        return {
            "_meta": {"strategy": self.name, "total": len(results), ...},
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
        }

# 2. 注册（在文件末尾）
register_strategy(MyMACDStrategy, is_default=False)

# 3. 使用
# python scan_all.py --strategy my_macd
```

### BaseStrategy 接口

```python
class BaseStrategy(ABC):
    @property
    def name(self) -> str        # 策略标识符
    @property
    def display_name(self) -> str # 中文名
    def score(self, tech_list, mode, kline_data=None, df_map=None) -> dict
```

### SignalResult 数据类

字段: symbol, name, total, abs_score, direction, grade, sub_scores, veto, consistency, price, change_pct, volume, adx, rsi, cci, ma_slope, macd_cross, dc20_break, ma_align, z_score, stage, extra

`.to_dict()` 方法可直接转为 scan_all.py 兼容的平铺 dict。
>
> 2026-07-04 实盘验证：`true_layered`模式的 `--reverse` 参数导致6/62品种出现"因子方向与信号方向完全矛盾"的严重错误（如PK的D1趋势=93↑却被标为做空）。该模式的IC=-0.039(20日，胜率43%)回测统计不显著，产生大量虚假信号。已被回退。

## L1-L4四层打分权重

```python
WL1 = 35  # L1 萌芽/资金结构 — 趋势动量+持仓变化
WL2 = 35  # L2 量价领先 — 成交量+价格变动配合
WL3 = 20  # L3 价格结构 — ADX+RSI+均线排列
WL4 = 10  # L4 确认 — MACD金叉/死叉+突破+一致性
```

## scan_all.py CLI

| 参数 | 说明 | 示例 |
|:----|:-----|:-----|
| `--strategy` | 策略名: `channel_breakout`(默认) / `three_signal` / `layered_l1l4` | `--strategy three_signal` |
| `--dual` | 双策略模式（主策略+L1-L4研究员辅助），默认只跑主策略 | `--dual` |
| `--output`, `-o` | 输出目录 | `-o ./reports` |
| `--prefix`, `-p` | 文件名前缀 | `-p full_scan` |
| `--symbols`, `-s` | 指定品种（逗号分隔），不传则全品种 | `-s PK,RB,B` |

## 权重配置（仅 L1-L4 传统模式使用）

```python
WL1 = 35  # L1 萌芽/资金结构
WL2 = 35  # L2 量价领先
WL3 = 20  # L3 价格结构
WL4 = 10  # L4 确认
```

**注意**：真分层打分不使用此权重配置。真分层使用`signals/true_layered_scoring.py`中的7因子等权投票 + 九宫格分类。

---

## 回测框架

`scripts/backtest/` 目录包含回测工具：

| 文件 | 用途 | 用法 |
|------|------|------|
| `backtest_true_layered.py` | **真分层回测（主框架）** | `python -m backtest.backtest_true_layered` |
| `evaluate.py` | 历史回放评估（遗留 L1-L4） | `python -m scripts.backtest.evaluate` |
| `optimize_weights.py` | 权重网格搜索（遗留 L1-L4） | `python -m scripts.backtest.optimize_weights` |
| `run_backtest.py` | 全量回测多截面（遗留） | `python -m scripts.backtest.run_backtest` |

**推荐**：所有新回测使用 `backtest_true_layered.py`（AKShare数据源，多截面多空评估，IC分析）。

---

## Data Quality Circuit Breaker（全局强制）

| 防呆机制 | 规则 | 触发后果 |
|:---------|:----|:---------|
| 品种扫描成功率 | **≥90%**（62品种中至少56品种成功） | 低于则标注"数据不完整"并终止评分 |
| 单品种K线条数 | **≥30条** | 不足30条K线的品种标记"数据不足"并跳过评分 |
| 数据时效性+R24 | 最新K线日期与运行日期**间隔≤5个交易日(日线)/≤7天(子周期)** | 超间隔则整品种跳过+原因打印 |
| 价格真实性(R24) | 最新收盘价必须>0 + 数据源不可虚构 | 无效价格则跳过该品种 |
| 成交量有效性 | volume字段必须存在且>0的K线占比**≥50%** | 低于则标注"成交量数据质量差" |
| scan_all.py运行时间 | 全量扫描**≤120秒** | 超限终止并输出已有结果 |
| 多源降级次数 | 单品种降级次数**≤2次** | 超限标记"数据源耗尽，跳过" |
| 子周期数据源可用性（R23） | 子周期扫描如最终数据源非TDX/TqSDK新鲜数据（≤7天），明鉴秋**拒绝分析退出流程** | 告知用户每个源失败原因 |
| 输出JSON大小 | **≤5MB** | 超限裁剪低频/无用字段 |

**数据质量分级**（每次扫描输出时在`_meta`中标注）：
- [OK] **正常**: 成功率≥95% + 时效正常 + 成交量完整
- [!] **降级**: 成功率90-94% 或 时效延迟1-3天
- [x] **不可用**: 成功率<90% 或 时效延迟>5天

## 定位

合并 `futures-data-search` + `commodity-trend-signal` + `technical-indicator-calc` 为一站式期货量化分析 skill。

内部按三层组织：**数据获取 → 指标计算 → 信号评分**，单向依赖，无循环引用。

## 目录结构

```
scripts/
├── scan_all.py                    # 全品种扫描入口（L1-L4 / true_layered 双模式）
├── scan_true_layered.py           # 真分层打分入口（TDX实盘+AKShare OI注入）
├── config/                        # 配置层（零依赖）
│   ├── symbols.py                 # 62品种列表 + 交易所映射
│   └── settings.py                # 系统参数配置
├── data/                          # 数据获取层（依赖config）
│   ├── multi_source_adapter.py    # 统一调度 + 多源降级
│   ├── duckdb_store.py            # DuckDB存储引擎
│   ├── data_source_config.py      # 数据源YAML配置
│   ├── data_freshness_monitor.py  # 数据新鲜度监控
│   ├── dominant_mapping.py        # 主力合约映射算法
│   └── collectors/
│       ├── tdx_collector.py       # 通达信TQ-Local HTTP采集器
│       └── eastmoney_collector.py # 东方财富API采集器
├── indicators/                    # 指标计算层（依赖config，不依赖data）
│   ├── tdx_bridge.py              # formula_zb桥接器
│   ├── calc_core.py               # numpy向量化（通达信100%对齐，45字段）
│   └── core.py                    # 统一指标引擎（待合并）
├── signals/                       # 信号评分层（依赖indicators）
│   ├── true_layered_scoring.py    # 真分层打分核心引擎（7因子截面排序+九宫格分类）
│   ├── scoring_system.py          # L1-L4四层打分（遗留）
│   ├── early_signal.py            # 早期信号检测
│   ├── signal_screener.py         # 信号筛选
│   ├── trade_plan.py              # 交易计划
│   ├── term_basis.py              # 期限结构分析
│   ├── report.py                  # 报告生成
│   └── debate_brief.py            # 辩论证据简报 + risk_input字段注入
├── ml_models/                     # P3: ML方向预测（v2.4.0新增）
│   └── direction_classifier.py    # LightGBM包装器 + EnsemblePredictor(规则+ML加权)
├── feature_pipeline/              # P3: 特征工程（v2.4.0新增）
│   └── feature_engineering.py     # 30+维度特征: 动量/OI/技术指标/期限结构/跨品种
├── feedback/                      # P3: PnL反馈闭环（v2.4.0新增）
│   └── trade_journal.py           # 交易记录+反向标注+replay buffer+性能汇总
└── backtest/                      # 回测框架
    ├── backtest_true_layered.py   # 真分层回测（AKShare，多截面多空评估）
    ├── evaluate.py                # 历史回放评估
    ├── optimize_weights.py        # 权重网格搜索
    ├── run_backtest.py            # 全量回测（遗留）
    └── daily_signal_tracker.py    # 实盘信号追踪
```

## 数据源获取管道（v2.9.1）

### K线数据降级链（get_kline）— 统一降级链，不分盘中/盘后

```
TDX(本地TQ-Local) → 新鲜度检查 → TqSDK → 东方财富 → AKShare分钟(子周期) → AKShare日线
```

| 序号 | 数据源 | 触发条件 | 失败跳转 |
|:----|:-------|:---------|:---------|
| ① | **TDX TQ-Local** | 日线/周线/月线无条件；子周期(60m/120m/240m)需**最后K线≤7天** | 新鲜度>7天→跳过 |
| ② | **TqSDK** | `tqsdk_available=True` + 非`TQ_SKIP_DISCLAIMER` | 异常/挂起→跳过 |
| ③ | **东方财富** | `eastmoney_available=True` | RemoteDisconnected→跳过 |
| ④ | **AKShare分钟** (v2.9.1新增) | `akshare_available=True` + period非daily | `futures_zh_minute_sina(SC0, period)` + **时间过滤**（排除未来K线） |
| ⑤ | **AKShare日线** | 兜底 | `futures_zh_daily_sina(SC0)` — 仅日线可用 |

**新鲜度检查**（v2.9.1 `multi_source_adapter.py`）：
- 子周期(60m/120m/240m)：TDX数据最后K线距今天>7天→`print警告`→**不return**→触发降级链
- 日线：沿用已有5交易日规则

**AKShare分钟时间过滤**（v2.9.1）：
- `futures_zh_minute_sina` 返回的条形数据含"datetime"时间戳
- 解析为pandas datetime → 过滤 `≤当前时间` → 排除未来/异常K线
- 输出仅含date(YYYYMMDD)字段，丢失具体时间（子周期指标计算仅需序列，不依赖时间戳）

### 指标计算管道（v2.9.1 — period感知）

```
第一优先: TdxCollector.get_indicators() → formula_zb直取，44项（仅日线）
第二优先: tdx_bridge.patch_indicators() → 委托TdxCollector，35字段补丁（仅日线）
第三优先: numpy向量化 → calc_core最后保障（仅日线）
--------------------------------------------------------------
⚠️ v2.9.1 重大变更：period!="daily"时，跳过以上所有桥接。
只使用 `_compute_indicators_numpy` 对DataFrame直接做numpy计算。
```

**为什么需要跳过桥接**（2026-07-08事故提炼）：
- `_compute_indicators_numpy` 收到的是正确的60m DataFrame（1022根小时K线）
- numpy计算出正确的60m指标（RSI=71.1, ATR=3.4, ADX=23.8）
- 但 `bridge.patch_indicators(tech, symbol)` 用TDX日线指标覆盖了tech字典
- 结果输出ADX=81.7(日线)、RSI=28.8(日线)、ATR=17.0(日线)
- 用户确认RSI=71.61(正确)、ATR=3.36(正确)与numpy计算结果一致

**数据源溯源**（v2.9.1 — R19-R22合规）：
- 子周期指标JSON输出含 `tdx_note` 字段，标注数据来源
- 降级数据（非TDX/TqSDK）→ `tdx_note` = "子周期数据: 降级计算(非TDX/TqSDK), 连续合约可能异于L8, ADX等全序列指标仅供参考"
- ADX类全序列Wilder平滑指标因连续合约不同(SC0 vs L8)可能有>100%偏差
最后保障: calc_core.calculate_tdx_compatible() → numpy向量化，45字段
```

## 使用方法

详见 [README.md](../../README.md)

```bash
# 全品种信号扫描
python scripts/scan_all.py

# 自定义品种扫描（消除胶水脚本，2026-07-03新增）
python scripts/scan_all.py --symbols PK,RB,B,UR

# 指定输出目录
python scripts/scan_all.py -o /path/to/output -p custom_scan --symbols PK,RB
```

> **设计原则**：`--symbols` 参数的设计目的就是消灭"为特定品种集写胶水脚本"的需求。任何辩论场景下如需扫描指定品种，应直接调用 `scan_all.py --symbols`，不得自行编写 `phase1_custom_scan.py` 之类的一次性脚本。

## 版本历史

- **v2.11.1** (2026-07-09): **评分系统修复** — ① `config/settings.py resolve_param` P1层新增大小写不敏感查找(31/44个optimized_params key为小写但运行时传大写→静默失效); ② `channel_breakout_strategy.py` DC20 else分支新增tick size逼近判定(near_breakout), 价格距DC20边界≤N个tick给予15分逼近分; ③ `config/settings.py` 新增 SYMBOL_TICK_SIZES(42品种tick size映射) + get_tick_size(); ④ 策略版本v1.0→v1.1, scan_all v2.18.1→v2.18.2, settings v2.13→v2.14

- **v2.11.0** (2026-07-08): **子周期全量扫描管道修复** — ① `multi_source_adapter.py` 子周期降级链重构: TDX→AKShare分钟→东方财富→TqSDK(原链TqSDK在AKShare分钟前导致每个品种5+s WebSocket); ② TqSDK加15s超时保护(Concurrent Futures), 避免rr等罕见品种死锁; ③ AKShare分钟调用加固(try/except防list index out of range); ④ 移除子周期东方财富/AKShare市场时段闸门(盘中也可走HTTP源); ⑤ scan_all.py/SKILL.md/文档全部补上120m(2小时)周期; ⑥ 120m全量扫描实测通过(61/62品种AKShare分钟, 仅rr无分钟数据)

- **v2.9.1** (2026-07-08): **数据管道大修** — ① `multi_source_adapter.py` 新增子周期K线新鲜度检查(>7天拒绝TDX→降级); ② 新增AKShare分钟数据降级(`futures_zh_minute_sina`)用于60m/120m/240m子周期; ③ `scan_all.py` 非交互环境跳过挂起TqSDK; ④ `indicators_legacy.py` 传入period参数,period!="daily"时跳过TDX桥接/日线指标覆盖; ⑤ `scan_all.py` 建df时传入period至`_compute_indicators_numpy`
- **v2.8.1** (2026-07-07): **SCI指标修复** — channel_breakout_strategy补传z_score/consistency/stage字段；three_signal_backtest→channel_breakout_backtest重命名；fingerprint降级警告静默化；USER_GUIDE引用修复为README
- **v2.8.0** (2026-07-07): **默认策略改为通道突破** — 新增 channel_breakout_strategy.py（唐奇安DC20/DC55 + 布林带确认），替换原 three_signal 为默认策略；scan_all.py dual 模式同步更新；registry.py 注册链更新
- **v2.5.0** (2026-07-06): **新增TqSdk盘中K线数据源** — `multi_source_adapter.py.get_kline()` 盘中时段新增TqSdk降级路径（TDX→TqSdk→东方财富→AKShare）；新增 `_fetch_tqsdk_kline()` 方法通过 TqSdk 主力连续合约（`KQ.{exchange}@{variety}`）获取 K 线；SKILL.md 数据源管道文档同步更新
- **v2.4.0** (2026-07-05): **P3全量实现** — 新增 ml_models/direction_classifier.py(LightGBM+EnsemblePredictor), feature_pipeline/feature_engineering.py(30+维度特征), feedback/trade_journal.py(PnL反馈闭环+反向标注); debate_brief.py 新增 risk_input字段注入(confidence/ATR/ADX/pattern_risk); indicators_legacy.py 除零修复(numpy安全向量化); SC斜率异常值过滤(abs>20%→0)
- **v2.3.1** (2026-07-05): factor_timing 12项优化 — 真实数据源、展期斜率异常过滤、多因子十分组投票、G1/G10动手组/观望组

- **v2.0.0** (2026-07-04): 真分层打分设为默认
  - 新增 true_layered_scoring 模块（7因子等权投票、否决降权、趋势成熟度）
  - 新增九宫格模糊分类器（高斯隶属度、左右侧识别）
  - 新增 D7 期限结构因子（term_signal）
  - 新增 scan_true_layered.py（通达信TDX实盘 + AKShare OI注入）
  - 新增 backtest/backtest_true_layered.py 回测框架（107截面×59品种）
  - 新增 `--reverse` 反向信号模式（IC为负，反向有效）
  - 新增合格信号筛选 + Agent JSON输出 + 九宫格side字段
  - SKILL.md 默认命令改为 `scan_true_layered.py --reverse`
  - 代码审计17轮（死代码清理、命名规范、编码兼容、bare except修复）
- **v1.0.1** (2026-07-03): [关键] 新增 `--symbols` 参数支持自定义品种扫描
  - 设计目的：消灭为特定品种集编写胶水脚本的需求
  - 辩论场景下：直接 `scan_all.py --symbols PK,RB`，禁止写自定义扫描脚本
- **v1.0.0** (2026-07-02): 初始版本
  - 合并 futures-data-search v4.1.0 + commodity-trend-signal v2.18.0 + technical-indicator-calc v2.4.2
  - 消除跨skill sys.path hack
  - 保持原有3个skill不动
