# quant-daily 用户手册

> 商品期货量化分析一体化工具：数据采集 → 指标计算 → L1-L4 趋势信号评分

---

## 一、环境要求

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
| `numpy>=1.24` | 核心向量化计算 | ✅ |
| `pandas>=2.0` | K线数据处理 | ✅ |
| `pyyaml>=6.0` | 配置文件读取 | ✅ |
| `duckdb>=0.9` | 本地数据持久化 | ⚠️ 强烈推荐 |
| `requests>=2.28` | 东方财富HTTP数据源 | ⚠️ 推荐 |
| `tqsdk>=2.5` | 天勤量化数据源（降级链） | ❌ 可选 |

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
    print(f'✅ TQ-Local 可用, {count} 个期货合约')
"
```

预期输出：`✅ TQ-Local 可用, 85 个期货合约`

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
├── USER_GUIDE.md          ← 本文件
├── scripts/
│   ├── scan_all.py        ← 全品种扫描入口
│   ├── config/            ← 配置
│   ├── data/              ← 数据采集
│   ├── indicators/        ← 指标计算
│   └── signals/           ← 信号评分
└── data/
    ├── futures.db         ← DuckDB 持久化
    └── dominant_maps/     ← 主力映射
```

### 3.2 WorkBuddy 加载

确保 Skill 目录存在于 `~/.workbuddy/skills/` 下。WorkBuddy 自动识别。

### 3.3 手动运行

```bash
cd ~/.workbuddy/skills/quant-daily
python scripts/scan_all.py
```

---

## 四、数据管道说明

### 4.1 三级降级策略

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

### 4.2 数据源优先级（`data_sources.yaml` 配置）

```
价格数据 (盘中/盘后相同):
  0. 通达信TQ-Local (tdx_local)
  1. 东方财富API (eastmoney)
  2. TqSDK (天勤)
  3. 交易所官方API
  4. AKShare
  5. WebSearch（极端降级）
```

---

## 五、CLI 使用

### 5.1 全品种扫描

```bash
# 默认输出到工作空间 Reports
python scripts/scan_all.py

# 指定输出目录和文件名前缀
python scripts/scan_all.py -o /path/to/reports -p my_scan
```

输出文件：
- `{output_dir}/{prefix}_{YYYYMMDD}.json` — 结构化信号数据
- `{output_dir}/{prefix}_ranking_{YYYYMMDD}.html` — 交互式排序报表

### 5.2 一键全流程

```bash
# 从项目根目录
cd ~/.workbuddy/skills/quant-daily
python scripts/scan_all.py --output "./reports"
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
| **L1** | 萌芽/资金结构层（OI/基差/期限/ROC等） | -40 ~ +40 |
| **L2** | 量价领先层（Vortex/CCI/Supertrend/HMA） | -25 ~ +25 |
| **L3** | 价格结构层（RSI健康区/DMI方向/突破） | -25 ~ +25 |
| **L4** | 确认层（通道突破/均线排列/MACD） | -10 ~ +10 |
| **否决** | 硬警报（ADX震荡/RSI极端/缩量/偏离） | -20 ~ 0 |
| **ADX** | 趋势强度，>25为强趋势 | 0~100 |
| **RSI** | 相对强弱指数，>80超买/<20超卖 | 0~100 |
| **Z** | 方向感知Z-score，\|Z\|>1.5统计显著 | 理论无界 |
| **CONS** | 四层方向一致数，4/4为干净信号 | 0~4/4 |

---

## 七、配置参考

### 7.1 品种列表

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
| 果蔬 | 2 | AP, CJ |
| 建材化工 | 6 | FG, ru, nr, br, sp, op |
| 新能源 | 3 | lc, si, ps |
| 航运 | 1 | ec |
| 其他 | 1 | rr |

### 7.2 数据源配置

见 `scripts/references/data_sources.yaml`，切换数据源优先级。

### 7.3 系统参数

见 `scripts/config/settings.py`，包含 L1-L4 打分配置、阈值、市场参数。

---

## 八、数据存储

### 8.1 DuckDB 数据库

位置：`data/futures.db`

| 表名 | 内容 | 数据量 |
|------|------|:------:|
| `oi_ranking` | 前20会员持仓排名 | ~360K行 |
| `warehouse` | 仓单日报 | ~50K行 |
| `futures_news` | 产业资讯 | ~15K行 |
| `term_structure` | 期限结构 | ~500K行 |
| `query_cache` | API查询缓存（4h TTL） | — |

### 8.2 主力映射

位置：`data/dominant_maps/`

每日收盘后更新，格式：
```json
{
  "CU": {
    "main": "CU2609",
    "next_main": "CU2610",
    "prev_main": "CU2608",
    "switched": false,
    "updated_at": "2026-07-02T15:30:00"
  }
}
```

---

## 九、故障排查

### 9.1 扫描失败

| 错误 | 原因 | 解决 |
|------|------|------|
| `No module named 'duckdb'` | DuckDB 未安装 | `pip install duckdb` |
| `TQ-Local不可用` | 通达信未启动 | 打开通达信客户端 |
| `0/62 采集成功` | 所有数据源均不可用 | 检查网络连接 |
| `mean requires at least one data point` | 所有品种评分失败 | 检查数据源 |

### 9.2 数据不一致

| 现象 | 原因 |
|------|------|
| ADX 列为 `nan` | TDX桥接器未连接，使用numpy计算值 |
| 指标与通达信略有偏差 | 数据降级到numpy（<2%偏差） |
| 部分品种空信号 | 品种流动性不足或数据缺失 |

### 9.3 日志

扫描过程输出到 stderr/stdout，关键错误以 `[Warning]` 或 `❌` 标记。

---

## 十、升级说明

### 10.1 从原 3 skill 迁移

quant-daily 是 `futures-data-search` + `commodity-trend-signal` + `technical-indicator-calc` 三者的合并版本。原 3 skill 保留不动。

如果之前使用原 skill 的自动化任务，推荐逐步迁移：
1. 先用 quant-daily 运行一次手动扫描
2. 对比输出报告是否一致
3. 将自动化任务的 `python scripts/scan_all.py` 路径改为 quant-daily

### 10.2 GitHub 仓库

https://github.com/CTAAgents/quant-skills

---

*最后更新：2026-07-02*
*版本：quant-daily v1.0.0*
