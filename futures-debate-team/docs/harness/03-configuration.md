# 03 — 配置管理

## 1. 配置文件清单

### 1.1 项目级配置

| 文件 | 路径 | 格式 | 用途 | 修改频率 |
|:-----|:-----|:-----|:-----|:---------|
| `plugin.json` | `.codebuddy-plugin/plugin.json` | JSON | 插件清单: 10 agents + 2 skills 声明 | 低 (版本升级时) |
| `settings.json` | 根目录 | JSON | 全局设置: 模式/阈值/webhooks/backtest | 中 |
| `team_config.json` | `config/team_config.json` | JSON | 团队环境: 自进化开关/快通道/venv | 低 |
| `pyproject.toml` | 根目录 | TOML | Python 包: 依赖/pytest/black/ruff | 低 |
| `requirements.txt` | 根目录 | TXT | 核心依赖列表 | 低 |
| `requirements.lock` | 根目录 | TXT | 冻结依赖 (可复现安装) | 低 |

### 1.2 Skill 级配置 (YAML)

| 文件 | 路径 | 用途 |
|:-----|:-----|:-----|
| `varieties.yaml` | `skills/quant-daily/scripts/references/` | 62 个期货品种定义 |
| `overseas_varieties.yaml` | `skills/quant-daily/scripts/references/` | 海外品种定义 |
| `data_sources.yaml` | `skills/quant-daily/scripts/references/` | 数据源降级链 (TDX→TqSDK→EM→AKShare) |

### 1.3 记忆级配置 (JSON, 运行时可变)

| 文件 | 路径 | 用途 | 写入者 |
|:-----|:-----|:-----|:-------|
| `agent_profiles.json` | `memory/` | Agent 进化参数 (ATR乘数/仓位%/论据权重) | `evolve_agents.py` |
| `calibration.json` | `memory/` | 评分权重校准表 | `calibrate_weights.py` |
| `debate_weights.json` | `memory/` | 辩论权重配置 | 手动/脚本 |
| `execution_followup.json` | `memory/` | 裁决执行回溯 (待验证队列) | `record_verdicts.py` |
| `instrument_strategy_matrix.json` | `memory/` | 品种×策略族适应性矩阵 (F1-F5) | `update_matrix.py` |
| `schedule_state.json` | `memory/` | 调度器状态 (PID/心跳/触发时间) | `scheduler/engine.py` |

## 2. 配置内容详解

### 2.1 settings.json

```json
{
  "agent": "futures-debate-team-team-lead",  // 主 Agent ID
  "seed": null,                              // 随机种子 (null=不固定)
  "selection_threshold": 0.65,               // 品种选择阈值
  "mode": "dry-run",                         // 运行模式: dry-run/live
  "webhooks": {                              // 通知渠道
    "wecom": "",                             // 企业机器人 URL
    "dingtalk": "",                          // 钉钉机器人 URL
    "email": ""                              // 邮件通知
  },
  "backtest": {
    "min_days": 600,                         // 回测最小天数
    "fee_rate": 0.001                        // 手续费率
  }
}
```

### 2.2 team_config.json

```json
{
  "version": "1.0",
  "single_variety_fast_track": true,         // 单品种快通道
  "agent_watchdog_seconds": 420,             // Agent 超时 (7分钟)
  "self_evolution": {
    "skip_when_no_pending": true,            // 无待验证时跳过
    "run_calibrate_when_validated_ge_5": true,
    "run_evolve_when_total_samples_ge_5": true,
    "skip_ml_when_feedback_lt_50": true      // 反馈<50跳过ML
  },
  "skip_for_single_variety": {
    "full_62_scan": false,                   // 单品种仍扫全量(用于对比)
    "cross_chain_dedup_30plus": true         // 跳过30+品种去重
  },
  "venv": {
    "path": "venv/Scripts/python.exe",
    "locked": "requirements.lock"
  }
}
```

### 2.3 pyproject.toml 关键配置

```toml
[project]
name = "futures-debate-team"
version = "5.5.1"
requires-python = ">=3.10"
dependencies = [
    "pandas", "numpy", "pyyaml", "duckdb", "requests",
    "akshare", "pydantic", "psutil", "lightgbm", "scikit-learn",
]

[project.optional-dependencies]
distributed = ["celery", "redis", "ray"]     // 分布式部署
ml = ["xgboost"]                              // ML 扩展

[tool.pytest.ini_options]
testpaths = ["tests/quant-daily"]
addopts = "--cov=skills/quant-daily/scripts/signals --cov-report=term-missing"

[tool.ruff]
line-length = 120
```

## 3. 环境变量

| 变量 | 默认值 | 用途 | 来源 |
|:-----|:-------|:-----|:-----|
| `FDB_LOG_LEVEL` | `INFO` | 统一日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL) | `unified_logger.py` |
| `FDB_LOG_DIR` | `~/Documents/WorkBuddy/Logs/` | 日志文件目录 | `unified_logger.py` |
| `DEBATE_HISTORY_DIR` | 项目内默认路径 | 辩论历史目录 (可覆盖) | `debate/history.py` |
| `TRAINING_ORCHESTRATOR_DIR` | 项目内默认路径 | ML 模型存储目录 | `ml/trainer.py` |
| `PYTHONIOENCODING` | (未设置) | Python IO 编码 (pipeline 强制设为 `utf-8`) | `pipeline/runner.py` |

### 环境变量设置示例

```bash
# 调试模式
export FDB_LOG_LEVEL=DEBUG

# 自定义日志目录
export FDB_LOG_DIR=/var/log/fdt

# 自定义辩论历史目录
export DEBATE_HISTORY_DIR=/data/fdt/debate_history
```

## 4. 配置优先级覆盖链

```
1. 环境变量 (最高优先级)
   ↓ 覆盖
2. settings.json
   ↓ 覆盖
3. team_config.json
   ↓ 覆盖
4. memory/*.json (运行时状态)
   ↓ 覆盖
5. 代码内默认值 (最低优先级)
```

### 覆盖示例

```python
# unified_logger.py 中的优先级链
_LOG_LEVEL = os.environ.get("FDB_LOG_LEVEL", "INFO").upper()  # 环境变量 > 默认值
_LOG_DIR = os.environ.get("FDB_LOG_DIR", None)                 # 环境变量 > 代码默认
if _LOG_DIR is None:
    _LOG_DIR = "~/Documents/WorkBuddy/Logs/"                   # 代码默认值
```

## 5. 数据源配置

### 5.1 降级链 (data_sources.yaml)

```
通达信TDX TQ-Local (优先级 0, 最高)
    ↓ 不可用时降级
TqSDK (优先级 1, 盘中live模式)
    ↓ 不可用时降级
东方财富 EastMoney (优先级 2)
    ↓ 不可用时降级
AKShare (优先级 3, 最后降级)
```

### 5.2 数据源选择逻辑

| 场景 | 盘中 | 盘后 | 实时价 |
|:-----|:-----|:-----|:-------|
| TDX 可用 | TDX (close=实时价) | TDX | TDX |
| TDX 不可用 | TqSDK (live模式) | TqSDK | TqSDK |
| TqSDK 不可用 | 东方财富 | 东方财富 | (无实时价) |
| 东方财富不可用 | (无数据) | AKShare | (无实时价) |

### 5.3 K线一致性

> **MA60 真实合约铁律**: `get_kline` 不传 `contract` 时默认取主力连续合约(L8)，其 MA60 与真实合约不符。单品种分析须带合约月份（如 `LH2609`），`scan_all -s LH2609` 自动解析并透传。

## 6. 配置校验现状

### 已有的校验

| 配置 | 校验方式 | 位置 |
|:-----|:---------|:-----|
| Agent 产出 | JSON Schema (Draft 2020-12) | `docs/schemas/` (9个文件) |
| Agent 产出 | Pydantic v2 model | `contracts/` |
| Agent 产出 | L1 产出校验脚本 | `validate_agent_output.py` (skill内) |
| 启动时关键文件 | 存在性检查 | `bootstrap.py` `load_memory()` |

### 缺失的校验 (Gap)

| 配置 | 缺失项 | 风险 |
|:-----|:-------|:-----|
| `settings.json` | 无 schema 校验 | 字段名拼错不报错 |
| `team_config.json` | 无 schema 校验 | 布尔值写错不报错 |
| `data_sources.yaml` | 无 schema 校验 | 优先级配置错误不报错 |
| `agent_profiles.json` | 无 schema 校准 | 进化参数越界不报错 |
| 环境变量 | 无类型检查 | FDB_LOG_LEVEL 写错值静默降级为 INFO |

> 详见 [差距分析](08-gap-analysis.md) 中的配置校验改进项。
