# quant-daily 用户手册

> 商品期货量化分析一体化工具：数据采集 → 指标计算 → 真分层打分 → 反向交易信号
> 版本：v2.0.0 | 更新：2026-07-04

---

## 🏆 快速上手（默认用法）

```bash
# 全品种真分层打分 + 反向交易信号
cd scripts/
python scan_true_layered.py --reverse

# 输出：
# 🔴 做空 TOP 10（最超买 → 预期下跌）
# 🟢 做多 BOTTOM 10（最超卖 → 预期上涨）
```

## 用法模式

| 命令 | 模式 | 说明 |
|:----|:----|:----|
| `scan_true_layered.py --reverse` | **真分层+反向（默认）** | 截面均值回归策略信号 |
| `scan_all.py` | L1-L4传统模式 | 向后兼容 |
| `scan_true_layered.py` | 真分层正向 | 不做反向（IC为负不建议） |
| `scan_all.py --mode compare` | 双模式对比 | 对照L1-L4与真分层排名 |

### 1.1 操作系统

- **Windows 10/11**（推荐，通达信本地数据源需要）
- macOS / Linux（仅支持远程数据源模式，不支持本地通达信）

### 1.2 Python 环境

| 项目 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Python | 3.10+ | 3.12 |
| pip | 21.0+ | 最新 |

### 1.3 Python 依赖

| 包 | 用途 | 必须 |
|---|------|:----:|
| `numpy>=1.24` | 核心向量化计算 | [OK] |
| `pandas>=2.0` | K线数据处理 | [OK] |
| `pyyaml>=6.0` | 配置文件读取 | [OK] |
| `duckdb>=0.9` | 本地数据持久化 | [!] 强烈推荐 |
| `requests>=2.28` | 东方财富HTTP数据源 | [!] 推荐 |
| `tqsdk>=2.5` | 天勤量化数据源（降级链） | [x] 可选 |

安装：
```bash
pip install numpy pandas pyyaml duckdb requests
```

---

## 二、通达信 TQ-Local 配置

### 2.1 什么是 TQ-Local

TQ-Local 是通达信软件本地 HTTP 服务，运行在 `http://127.0.0.1:17709`，提供实时行情、K线数据和技术指标公式计算服务。**这是 quant-daily 的最高优先级数据源。**

### 2.2 安装通达信客户端

1. 下载通达信软件：https://www.tdx.com.cn
2. 安装并启动通达信客户端
3. 登录交易账户（免费行情账户即可）
4. 确保客户端运行中，**不要关闭软件窗口**

### 2.3 验证 TQ-Local 可用

```bash
python -c "
import urllib.request, json
req = urllib.request.Request(
    'http://127.0.0.1:17709/',
    data=json.dumps({'id':1,'method':'get_stock_list','params':{'market':'92','list_type':1}}).encode(),
    headers={'Content-Type':'application/json; charset=utf-8'},
    method='POST')
with urllib.request.urlopen(req, timeout=5) as resp:
    data = json.loads(resp.read())
    count = len(data['result']['Value'])
    print(f'[OK] TQ-Local 可用, {count} 个期货合约')
"
```

预期输出：`[OK] TQ-Local 可用, 85 个期货合约`

### 2.4 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `Connection refused` | 通达信未启动 | 打开通达信客户端 |
| `Timeout` | 网络拥堵 | 等待几秒重试 |
| `ErrorId` 非零 | 参数错误 | 重启通达信 |

---

## 三、Skill 安装

### 3.1 位置

quant-daily 是一个 WorkBuddy Skill，安装位置：

```
~/.workbuddy/skills/quant-daily/
├── SKILL.md
├── README.md
├── USER_GUIDE.md          ← 本文件
├── scripts/
│   ├── scan_all.py              ← 全品种扫描入口（假分层）
│   ├── scan_true_layered.py     ← 真分层扫描（v1.1新增）
│   ├── scan_true_layered.py ← AKShare版真分层
│   ├── analyze_targets.py       ← 目标品种量化分析
│   ├── config/                  ← 配置
│   ├── data/                    ← 数据采集
│   ├── indicators/              ← 指标计算
│   ├── signals/                 ← 信号评分
│   └── backtest/                ← 回测框架
└── data/
    ├── futures.db               ← DuckDB 持久化
    └── dominant_maps/           ← 主力映射
```

### 3.2 WorkBuddy 加载

确保 Skill 目录存在于 `~/.workbuddy/skills/` 下。WorkBuddy 自动识别。

### 3.3 手动运行

```bash
cd ~/.workbuddy/skills/quant-daily

# 假分层扫描（原L1-L4阈值累加）
python scripts/scan_all.py

# 真分层扫描（截面排序+秩变换）
python scripts/scan_true_layered.py

# 自定义品种
python scripts/scan_all.py --symbols PK,RB
python scripts/scan_true_layered.py --symbols SA,RB,FU
```

---

## 四、数据管道说明

### 4.1 三级指标获取管道

```
┌─ 第一优先 ──────────────────────────────────┐
│ TdxCollector.get_indicators()               │
│ → 通达信TQ-Local formula_zb 直接获取 (44项)  │
│ → 与通达信客户端数值100%一致                  │
└─────────────────────────────────────────────┘
                    ↓ 失败时
┌─ 第二优先 ──────────────────────────────────┐
│ tdx_bridge.patch_indicators()               │
│ → 委托TdxCollector，降级到本地formula_zb直连 │
│ → 35字段补丁                                │
└─────────────────────────────────────────────┘
                    ↓ 失败时
┌─ 最后保障 ──────────────────────────────────┐
│ calc_core.calculate_tdx_compatible()        │
│ → numpy 向量化计算，算法与通达信100%对齐      │
│ → 45字段                                    │
└─────────────────────────────────────────────┘
```

### 4.2 数据质量熔断器（v1.1新增·全局强制）

每次扫描输出时在 `_meta` 中标注数据质量分级：

- 🟢 **正常**: 成功率≥95% + 时效正常 + 成交量完整
- 🟡 **降级**: 成功率90-94% 或 时效延迟1-3天
- 🔴 **不可用**: 成功率<90% 或 时效延迟>5天

7 道防呆机制：

| # | 检查项 | 阈值 | 触发后果 |
|:-:|:-------|:----:|:---------|
| 1 | 品种成功率 | ≥90%（62中≥56成功） | 低于则终止评分 |
| 2 | K线条数 | ≥30条 | 不足则跳过 |
| 3 | 数据时效性 | ≤5交易日 | 标注"数据过期" |
| 4 | 成交量有效性 | volume>0占比≥50% | 标注"成交量差" |
| 5 | 扫描耗时 | ≤120秒 | 超限终止 |
| 6 | 降级次数 | ≤2次/品种 | 标记"数据源耗尽" |
| 7 | 输出JSON | ≤5MB | 裁剪字段 |

---

## 五、CLI 使用

### 5.1 全品种扫描

```bash
# 假分层——原L1-L4阈值累加（默认）
python scripts/scan_all.py

# 真分层——截面排序+秩变换
python scripts/scan_true_layered.py

# AKShare数据源版真分层
python scripts/scan_true_layered.py

# 指定输出目录和文件名前缀
python scripts/scan_all.py -o /path/to/reports -p my_scan
```

输出文件：
- `{output_dir}/{prefix}_{YYYYMMDD}.json` — 结构化信号数据
- `{output_dir}/{prefix}_ranking_{YYYYMMDD}.html` — 交互式排序报表

### 5.2 自定义品种分析

```bash
# 快速分析目标品种
python scripts/analyze_targets.py                           # 默认: PK,RB,B,UR
python scripts/analyze_targets.py --symbols SA,RB,FU        # 自定义品种

# 真分层自定义
python scripts/scan_true_layered.py --symbols PK,RB,B,UR
```

---

## 六、输出报告解读

### 6.1 信号等级

| 等级 | 总分范围 | 含义 |
|------|:-------:|------|
| **STRONG** | ≥ 75 | 最强信号，L1-L4多层共振，优先关注 |
| **WATCH** | 60-74 | 重点信号，方向一致性高，可纳入观察 |
| **WEAK** | 40-59 | 信号存在但质量一般，需验证后入场 |
| **NOISE** | < 40 | 噪音，建议忽略 |

### 6.2 趋势阶段

| 阶段 | 含义 | 操作建议 |
|:----:|------|---------|
| 🟢 launch | 趋势刚启动 | 早期布局，空间最大 |
| 🔵 trending | 主趋势运行 | 趋势确认，顺势持有 |
| 🟡 exhausted | 衰竭中 | 趋势末端，减仓或紧止损 |
| 🔴 reversal | 反转中 | 方向可能转变，平仓观望 |

### 6.3 字段说明

| 字段 | 说明 | 范围 |
|------|------|:----:|
| **总分** | L1+L2+L3+L4+否决 综合信号强度 | -100 ~ +100 |
| **L1** | 萌芽/资金结构层（OI/基差/期限/ROC等） | -35 ~ +35 |
| **L2** | 量价领先层（Vortex/CCI/Supertrend/HMA） | -35 ~ +35 |
| **L3** | 价格结构层（RSI健康区/DMI方向/突破） | -20 ~ +20 |
| **L4** | 确认层（通道突破/均线排列/MACD） | -10 ~ +10 |
| **否决** | 硬警报（ADX震荡/RSI极端/缩量/偏离） | -20 ~ 0 |
| **ADX** | 趋势强度，>25为强趋势 | 0~100 |
| **RSI** | 相对强弱指数，>80超买/<20超卖 | 0~100 |
| **Z** | 方向感知Z-score，\|Z\|>1.5统计显著 | 理论无界 |
| **CONS** | 四层方向一致数，4/4为干净信号 | 0~4/4 |

### 6.4 真分层输出说明

真分层输出添加了以下额外字段：
- **rank_total**: 全品种综合排名（1=最强多头，62=最强空头）
- **factor_scores[]**: 各因子独立排名，不预判方向
- **consensus**: 各维度排名一致性指标

---

## 七、回测框架（v1.1新增）

`scripts/backtest/` 目录包含完整的回测和信号追踪工具：

| 文件 | 用途 | 用法 |
|------|------|------|
| `evaluate.py` | 历史回放评估 | `python -m scripts.backtest.evaluate --mode eval --days 120` |
| `optimize_weights.py` | 权重网格搜索 | `python -m scripts.backtest.optimize_weights` |
| `run_backtest.py` | 全量回测（多截面+蒙特卡罗） | `python -m scripts.backtest.run_backtest` |
| `backtest_true_layered.py` | 真分层回测引擎 | `python -m scripts.backtest.backtest_true_layered` |
| `daily_signal_tracker.py` | 实盘信号追踪 | `python -c "from backtest.daily_signal_tracker import track_signals; track_signals(results)"` |

### 权重优化结果

33组合 × 62品种网格搜索，Baseline (40/30/20/10) WATCH=10 → 最优 (35/35/20/10) WATCH=14 (+40%)。

---

## 八、配置参考

### 8.1 品种列表

见 `scripts/config/symbols.py`，包含 **62 个主力非僵尸品种**：

| 板块 | 品种数 | 品种列表 |
|------|:-----:|---------|
| 黑色系 | 7 | rb, hc, i, j, jm, SF, SM |
| 能源链 | 6 | sc, lu, fu, bu, pg, PX |
| 聚酯链 | 5 | TA, PF, PR, eg, eb |
| 塑化链 | 4 | v, pp, l, MA |
| 化工 | 3 | SH, SA, UR |
| 有色金属 | 8 | cu, al, zn, pb, ni, sn, ao, SS |
| 贵金属 | 2 | au, ag |
| 油脂油料 | 8 | a, b, m, y, p, OI, RM, PK |
| 农产品 | 6 | c, cs, SR, CF, jd, lh |
| 建材化工 | 6 | FG, ru, nr, br, sp, op |
| 其他 | 7 | ap, CJ, lc, si, ps, ec, rr |

### 8.2 数据源配置

见 `scripts/references/data_sources.yaml`，切换数据源优先级。

### 8.3 系统参数

见 `scripts/config/settings.py`，包含 L1-L4 打分配置、阈值、市场参数。

---

## 九、故障排查

### 9.1 扫描失败

| 错误 | 原因 | 解决 |
|------|------|------|
| `No module named 'duckdb'` | DuckDB 未安装 | `pip install duckdb` |
| `TQ-Local不可用` | 通达信未启动 | 打开通达信客户端 |
| `0/62 采集成功` | 所有数据源均不可用 | 检查网络连接 |
| `mean requires at least one data point` | 所有品种评分失败 | 检查数据源 |
| 数据质量标记🔴 | 成功率<90%或时效>5天 | 检查数据源连接 |

### 9.2 数据不一致

| 现象 | 原因 |
|------|------|
| ADX 列为 `nan` | TDX桥接器未连接，使用numpy计算值 |
| 指标与通达信略有偏差 | 数据降级到numpy（<2%偏差） |
| 部分品种空信号 | 品种流动性不足或数据缺失 |

### 9.3 日志

扫描过程输出到 stderr/stdout，关键错误以 `[Warning]` 或 `[x]` 标记。

---

## 十、升级说明

### 10.1 从 v1.0.x 升级

| 变更项 | v1.0.x | v1.1.0 |
|--------|--------|--------|
| L1-L4权重 | 40/30/20/10 | **35/35/20/10** |
| 评分方式 | 假分层（阈值累加） | 假分层 + **真分层（截面排序）** |
| 数据质量 | 基础校验 | **Data Quality Circuit Breaker**（7道熔断） |
| 回测 | 基础回测 | 真分层回测引擎 |
| CLI | `--symbols` | 沿用 |
| 新脚本 | — | `scan_true_layered.py`, `backtest_true_layered.py`, `analyze_targets.py` |

### 10.2 GitHub 仓库

https://github.com/CTAAgents/experts (skills/quant-daily/)

---

*最后更新：2026-07-04*
*版本：quant-daily v1.1.0*
