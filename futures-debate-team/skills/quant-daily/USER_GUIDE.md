# quant-daily 用户手册

> 商品期货量化分析一体化工具：数据采集 → 指标计算 → 策略可插拔
> 版本：v2.2.0 | 更新：2026-07-04

---

## 🏆 快速上手（默认用法）

```bash
cd scripts/

# L1-L4全品种扫描（推荐·唯一正确模式）
python scan_all.py

# 自定义品种
python scan_all.py --symbols PK,RB,B,UR

# 列出可用策略
python scan_all.py --list-strategies
```

> ⚠️ 2026-07-04 实盘验证：`scan_true_layered.py --reverse` 模式存在严重因子方向矛盾
> （如PK的D1趋势=93↑却被标为做空）。已被回退禁用。请使用 `scan_all.py`。

---

## 一、安装与依赖

### 1.1 操作系统

- **Windows 10/11**（推荐，通达信本地数据源需要）
- macOS / Linux（仅支持远程数据源）

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
| `duckdb>=0.9` | 本地数据持久化 | [!] 推荐 |
| `requests>=2.28` | 东方财富HTTP数据源 | [!] 推荐 |
| `tqsdk>=2.5` | 天勤量化数据源（降级链） | [x] 可选 |

```bash
pip install numpy pandas pyyaml duckdb requests
```

---

## 二、通达信 TQ-Local 配置

### 2.1 什么是 TQ-Local

TQ-Local 是通达信软件本地 HTTP 服务，运行在 `http://127.0.0.1:17709`，提供实时行情、K线数据和技术指标公式计算服务。这是 quant-daily 的最高优先级数据源。

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

```
~/.workbuddy/skills/quant-daily/
├── SKILL.md                  ← Skill 定义
├── README.md                 ← 项目说明
├── USER_GUIDE.md             ← 本文件
├── scripts/
│   ├── scan_all.py           ← 全品种扫描入口（策略调度器）
│   ├── strategies/           ← 策略可插拔层
│   │   ├── base.py           ← BaseStrategy 抽象基类
│   │   ├── registry.py       ← 注册器
│   │   ├── layered_l1l4.py   ← L1-L4策略（默认·活跃）
│   │   └── true_layered.py   ← 真分层策略（已废弃）
│   ├── config/               ← 配置（品种列表+系统参数）
│   ├── data/                 ← 数据采集（多源降级）
│   ├── indicators/           ← 指标计算（TDX桥接+numpy）
│   ├── signals/              ← 信号评分（旧模块）
│   └── backtest/             ← 回测框架
└── data/
    ├── futures.db            ← DuckDB 持久化
    └── dominant_maps/        ← 主力映射
```

---

## 四、策略可插拔架构

### 4.1 设计原则

量化打分策略已独立到 `strategies/` 目录，新增策略**无需修改** `data/` 或 `indicators/` 层的任何代码。

### 4.2 使用策略

```bash
# 默认（L1-L4）
python scan_all.py

# 显式指定
python scan_all.py --strategy layered_l1l4

# 列出所有
python scan_all.py --list-strategies
```

### 4.3 新增策略

```python
# 1. 新建 strategies/my_strategy.py
from strategies.base import BaseStrategy, SignalResult
from strategies.registry import register_strategy

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"           # --strategy 参数值
    
    @property
    def display_name(self) -> str:
        return "我的自定义策略"          # 终端显示名
    
    def score(self, tech_list, mode, kline_data=None, df_map=None):
        """
        打分逻辑。
        tech_list: 每个品种的 tech dict，包含 symbol, name, last_price,
                   ADX, RSI14, CCI20, MACD, 均线等44项指标
        df_map: {sym: pd.DataFrame} 含K线数据
        """
        results = []
        for tech in tech_list:
            r = SignalResult(
                symbol=tech["symbol"],
                name=tech.get("name", tech["symbol"]),
                total=...,              # 带方向总分
                abs_score=...,          # 绝对值
                direction="bull" if ... else "bear",
                grade="WATCH",
                sub_scores={"d1": ..., "d2": ...},
                price=tech.get("last_price", 0),
                adx=tech.get("ADX", 0),
                rsi=tech.get("RSI14", 0),
            )
            results.append(r)
        
        all_ranked = sorted(results, key=lambda r: r.abs_score, reverse=True)
        return {
            "_meta": {"strategy": self.name, "total": len(results), ...},
            "all_ranked": [r.to_dict() for r in all_ranked],
            "bull_signals": [r.to_dict() for r in all_ranked if r.direction == "bull"],
            "bear_signals": [r.to_dict() for r in all_ranked if r.direction == "bear"],
        }

# 2. 注册
register_strategy(MyStrategy)

# 3. 使用
# python scan_all.py --strategy my_strategy
```

### 4.4 BaseStrategy 接口

| 方法/属性 | 类型 | 说明 |
|:----------|:----|:-----|
| `name` | `@property str` | 策略标识符 |
| `display_name` | `@property str` | 中文显示名 |
| `score(tech_list, mode, kline_data, df_map)` | `method -> dict` | 核心打分方法 |

### 4.5 SignalResult 字段

| 字段 | 类型 | 说明 |
|:----|:----|:-----|
| `symbol` | str | 品种代码 |
| `name` | str | 品种名称 |
| `total` | float | 带方向总分（正=多头，负=空头） |
| `abs_score` | float | 绝对分 |
| `direction` | str | "bull" / "bear" / "neutral" |
| `grade` | str | "STRONG" / "WATCH" / "WEAK" / "NOISE" |
| `sub_scores` | dict | 子层/因子分数 |
| `veto` | int | 否决计数 |
| `consistency` | int | 子层方向一致性 |
| `price` | float | 最新价 |
| `adx` | float | ADX趋势强度 |
| `rsi` | float | RSI14 |
| `extra` | dict | 策略专属额外字段 |

`to_dict()` 方法自动转为平铺 dict，兼容 scan_all.py 输出格式。

---

## 五、CLI 使用

### 5.1 全品种扫描

```bash
# L1-L4默认策略（推荐）
python scan_all.py

# 指定策略
python scan_all.py --strategy layered_l1l4

# 指定输出目录和文件名前缀
python scan_all.py -o /path/to/reports -p my_scan

# 自定义品种
python scan_all.py --symbols PK,RB,B,UR
```

输出文件：
- `{prefix}_{YYYYMMDD}.json` — 结构化信号数据
- `{prefix}_ranking_{YYYYMMDD}.html` — 交互式排序报表

### 5.2 策略管理

```bash
# 列出所有可用策略
python scan_all.py --list-strategies
```

### 5.3 完整参数

| 参数 | 别名 | 说明 |
|:----|:----|:-----|
| `--output` | `-o` | 输出目录 |
| `--prefix` | `-p` | 文件名前缀（默认 `full_scan`） |
| `--symbols` | `-s` | 指定品种，逗号分隔 |
| `--strategy` | — | 策略名（默认 `layered_l1l4`） |
| `--list-strategies` | — | 列出所有策略（无需其他参数） |
| `--mode` | `-m` | [废弃] 旧版模式参数 |

---

## 六、输出报告解读

### 6.1 信号等级

| 等级 | 总分范围 | 含义 |
|------|:-------:|------|
| **STRONG** | ≥ 75 | 最强信号，L1-L4多层共振 |
| **WATCH** | 60-74 | 重点信号，方向一致 |
| **WEAK** | 40-59 | 信号一般，需验证 |
| **NOISE** | < 40 | 噪音，忽略 |

### 6.2 L1-L4 各层权重

| 层 | 权重 | 指标 | 说明 |
|:--:|:----:|:-----|:-----|
| L1 | **35%** | OI变化、基差、期限结构、ROC | 资金结构驱动 |
| L2 | **35%** | Vortex、CCI、Supertrend、HMA | 量价领先确认 |
| L3 | **20%** | RSI健康区、DMI方向、ADX强度 | 价格结构验证 |
| L4 | **10%** | 通道突破、均线排列、MACD | 确认信号 |

否决项：ADX震荡、RSI极端、缩量、统计偏离（-20 ~ 0）

### 6.3 趋势阶段

| 阶段 | 含义 | 操作建议 |
|:----:|------|---------|
| launch | 趋势刚启动 | 早期布局 |
| trending | 主趋势运行 | 顺势持有 |
| exhausted | 衰竭中 | 减仓或紧止损 |
| reversal | 反转中 | 平仓观望 |

### 6.4 字段说明

| 字段 | 说明 | 范围 |
|------|------|:----:|
| **总分** | L1+L2+L3+L4+否决 综合信号强度 | -100 ~ +100 |
| **L1-L4** | 各层子分 | -35~+35 等 |
| **否决** | 硬警报 | -20 ~ 0 |
| **ADX** | 趋势强度，>25为强趋势 | 0~100 |
| **RSI** | 相对强弱 | 0~100 |
| **Z** | 方向感知Z-score，\|Z\|>1.5显著 | 理论无界 |
| **CONS** | 四层方向一致数，4/4为干净 | 0~4 |

---

## 七、数据管道

### 7.1 三级指标获取

```
第一优先: TdxCollector.get_indicators() → formula_zb 44项
第二优先: tdx_bridge.patch_indicators() → 35字段补丁
最后保障: calc_core.calculate_tdx_compatible() → numpy向量化 45字段
```

### 7.2 数据质量熔断器

| # | 检查项 | 阈值 | 触发后果 |
|:-:|:-------|:----:|:---------|
| 1 | 品种成功率 | ≥90% | 低于终止 |
| 2 | K线条数 | ≥30 | 不足跳过 |
| 3 | 时效性 | ≤5交易日 | 标注过期 |
| 4 | 成交量 | >0占比≥50% | 标注降级 |
| 5 | 扫描耗时 | ≤120秒 | 超限终止 |
| 6 | 降级次数 | ≤2次/品种 | 标记跳过 |
| 7 | 输出JSON | ≤5MB | 裁剪字段 |

---

## 八、配置参考

### 8.1 品种列表

`scripts/config/symbols.py` 包含 **62个主力品种**：

| 板块 | 品种数 | 品种 |
|:-----|:-----:|:----|
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

见 `scripts/references/data_sources.yaml`。

### 8.3 系统参数

见 `scripts/config/settings.py`。

---

## 九、故障排查

### 9.1 扫描失败

| 错误 | 原因 | 解决 |
|------|------|------|
| `No module named 'duckdb'` | DuckDB 未安装 | `pip install duckdb` |
| `TQ-Local不可用` | 通达信未启动 | 打开通达信 |
| `0/62 采集成功` | 所有数据源不可用 | 检查网络 |
| 数据质量标记🔴 | 成功率<90%或时效>5天 | 检查数据源 |

### 9.2 数据不一致

| 现象 | 原因 |
|:-----|:-----|
| ADX 列为 `nan` | TDX桥接器未连接，使用numpy兜底 |
| 指标与通达信略有偏差 | 数据降级到numpy（<2%偏差） |
| 部分品种空信号 | 品种流动性不足或数据缺失 |

---

## 十、升级说明

### 10.1 v2.2.0 主要变更

| 变更 | 说明 |
|:----|:-----|
| 新增 `strategies/` | 策略可插拔层，`--strategy` 参数切换 |
| `scan_all.py` | 新增 `--strategy` / `--list-strategies` |
| L1-L4恢复默认 | true_layered --reverse 已废弃 |
| data/ indicators/ | 完全不变 |

### 10.2 GitHub 仓库

https://github.com/CTAAgents/experts (skills/quant-daily/)

---

*最后更新：2026-07-04*
*版本：quant-daily v2.2.0*
