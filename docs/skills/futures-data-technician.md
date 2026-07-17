---
name: futures-data-technician
version: 2.0
description: >
  数技师 — 辩论专家团数据管道（只做数据不做分析）。封装quant-daily scan_all.py为"数据管道模式"，含data_manifest溯源。输出干净数据包供研究员加工。
agent_created: true
disable: false
---

# futures-data-technician — 数技师（数据管道）

## 🔒 Data Pipeline Circuit Breaker（新增·全局强制）

| 防呆机制 | 规则 | 触发后果 |
|:---------|:----|:---------|
| 输出中禁止分析性语言 | 输出JSON和日志中**不得出现**"看多/看空/趋势强/弱/应该/建议/多空/震荡上行"等词汇 | 违反即输出不合格，需重新生成不带分析的纯数据输出 |
| 字段范围限制 | `all_ranked`每个条目只能包含：`symbol, name, price, change_pct, volume, adx, rsi, cci, ma_slope, macd_cross, dc20_break, ma_align, stage, total, l1, l2, l3, l4, veto, direction, grade, z_score, cons` + `_meta`溯源字段 | 出现未定义字段标注"非法字段" |
| `_meta`溯源强制 | 每次输出必须包含`_meta.date, _meta.source, _meta.indicators, _meta.symbols_count` | 缺失则标注"缺少数据溯源信息" |
| 数据包大小 | **≤5MB** | 超限裁剪 |
| 运行超时 | **≤120秒**全品种扫描 | 超限输出已采集部分 |

## 定位

辩论专家团的**数据管道**角色。基于 `quant-daily` skill 的数据采集+指标计算能力，包装为"只做数据不做分析"的数技师专用接口。

**核心信条**：数技师不分析。一旦输出中出现"看多/看空/趋势强/弱"等分析性语言，就是越界。

## 依赖

- **数据层**：依赖 `quant-daily` 的 `scan_all.py`（含 `run_scan` 函数）
- **指标层**：依赖 `quant-daily` 的 `_compute_indicators_numpy`（44项指标）
- **评分层**：本 skill **不包含**任何评分——那是研究员和辩手分析的事，数技师只提供原始指标值

## 唯一入口：run_scan()

所有功能通过一个入口暴露：

```python
def run_scan(output_dir: str = None, output_prefix: str = "custom_scan",
             symbols: list = None) -> dict:
    """采集数据+计算指标，返回数据包字典。

    参数:
        output_dir: 输出目录（可选）
        output_prefix: 文件名前缀
        symbols: 品种列表，格式 [(sym, name), ...]。None=全品种
    """
```

### CLI 方式（推荐）

```bash
python ~/.workbuddy/skills/quant-daily/scripts/scan_all.py \
  --symbols PK,RB,B,UR \
  --output /path/to/output \
  --prefix custom_scan
```

### 库函数方式（CLI不可用时回退）

```python
import sys
sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/quant-daily/scripts"))
from scan_all import run_scan
from config.symbols import ALL_SYMBOLS

sym_map = {s: n for s, n in ALL_SYMBOLS}
targets = [(s, sym_map[s]) for s in ["PK", "RB", "B", "UR"]]
result = run_scan(output_dir="/path/to/output", symbols=targets)
```

## 输出格式

输出为 JSON 文件，关键字段：

```json
{
  "_meta": {
    "date": "20260703",
    "source": "通达信本地→MultiSourceAdapter",
    "indicators": "numpy向量化(通达信公式对齐)",
    "symbols_count": 4,
    "tdx_patched_count": 0
  },
  "all_ranked": [
    {
      "symbol": "RB", "name": "螺纹钢",
      "price": 3067, "change_pct": -0.07,
      "adx": 50.0, "rsi": 28.6, "cci": -101.9,
      "ma_slope": -0.5, "stage": "trending"
    }
  ],
  "bull_signals": [...],
  "bear_signals": [...]
}
```

> ⚠️ **数据边界**：本skill不输出评分、不输出方向判定、不输出多空建议。ADX/RSI/CCI等只是数值，分析留给研究员。

## 数据溯源（data_manifest）

每次输出的 `_meta` 字段已包含完整溯源信息，明鉴秋提取后用于 `debate_results.json` 的 `data_manifest`：

| 字段 | 内容示例 |
|:----|:---------|
| `_meta.date` | 报告日期 |
| `_meta.source` | 数据源：通达信本地→MultiSourceAdapter |
| `_meta.indicators` | 指标计算方法 |
| 最新K线日期 | 在 scan_all.py 的终端输出中有显示 |

## 与 quant-daily 的关系

| 维度 | quant-daily | futures-data-technician |
|:----|:------------|:------------------------|
| 服务对象 | 通用期货量化分析 | 辩论专家团数技师专用 |
| 分析能力 | ❌ **不做分析** |
| 角色定位 | 分析师工具 | 数据管道 |
| 调用方式 | `scan_all.py` 直接跑 | 同上，但**使用限制更严格** |
| 输出用途 | 自由使用 | 仅供研究员/辩手加工 |

## 辩论专家团集成模式

当本 skill 被 `futures-trading-analysis` 辩论系统的**数技师** Agent 加载时：

**输入**：品种列表 + 账户权益假设
**产出**：`scan_all.py` 的输出JSON（通过文件持久化）→ 传给研究员

**履职链路**：
1. 团队主管选题后，数技师被调用
2. 调用 `scan_all.py --symbols PK,RB,B,UR` 获取数据包
3. 将数据包文件路径传给基本面研究员 + 技术面研究员
4. **不做任何分析**——只说"数据已就位"，不说"数据看起来偏多/偏空"

## 边界

- ❌ 不做供需/库存/利润分析（那是基本面研究员的事）
- ❌ 不做量价/形态/资金流分析（那是技术面研究员的事）
- ❌ 不做多空判断
- ❌ 不做评分（那是研究员的工作）
- ✅ 数据采集 + 清洗 + 时效校验 + 指标计算
- ✅ 提供带溯源标记的原始数据包
