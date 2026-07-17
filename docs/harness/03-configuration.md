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
version = "8.8.6"   # 唯一版本源（经 scripts/fdt_paths.py:get_fdt_version() 运行时读取）
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0", "numpy>=1.24", "python-dateutil>=2.8",
    "lightgbm>=4.0", "scikit-learn>=1.3", "tqdm>=4.65",
    "scipy>=1.11", "psutil>=5.9", "requests>=2.31", "pydantic>=2.0",
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
| `DCE_API_KEY` | (未设置) | 大商所官方 API key；设置后 DCE 持仓排名走官方 API（见 `futures_data_core/f10/dce_api.py`） | `f10/position.py` |
| `DCE_API_SECRET` | (未设置) | 大商所官方 API secret；与 `DCE_API_KEY` 配对 | `f10/position.py` |
| `FDT_USE_LANGGRAPH` | `false` | 控制 `pipeline/runner.py` 使用 LangGraph 模式（A/B 切换）：`true`=走 LangGraph 路径，`false`=走旧 subprocess 路径（零风险） | `pipeline/runner.py` |
| `FDT_LANGGRAPH_MODE` | `default` | LangGraph 模式选择：`default`/`fast`/`deep_research`/`tournament`；仅当 `FDT_USE_LANGGRAPH=true` 时生效 | `pipeline/runner.py` `fdt_langgraph/graph.py` |
| `FDT_CHECKPOINTER` | `sqlite` | Checkpointer 后端选择：`pg`=PostgreSQL，`sqlite`=SQLite；`pg` 连接失败自动降级到 `sqlite` | `fdt_langgraph/graph.py` `_get_checkpointer()` |

### 环境变量设置示例

```bash
# 调试模式
export FDB_LOG_LEVEL=DEBUG

# 自定义日志目录
export FDB_LOG_DIR=/var/log/fdt

# 自定义辩论历史目录
export DEBATE_HISTORY_DIR=/data/fdt/debate_history

# 大商所官方 API 凭证（启用 DCE 持仓排名官方 API 路径；不设则回退 portal 网页抓取）
export DCE_API_KEY=your_api_key
export DCE_API_SECRET=your_api_secret
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

> **2026-07-14 整顿**：G1 已落地——`config/schema.py` 提供 `Settings` / `TeamConfig` / `AgentWaiterConfig` 等 Pydantic 模型，bootstrap 启动校验。`03-configuration.md` 此前「G1 缺失」注记已过时，特此校正。

| 配置 | 状态 | 残留风险 |
|:-----|:-----|:-----|
| `settings.json` | ✅ `Settings` 模型校验 | — |
| `team_config.json` | ✅ `TeamConfig` 模型校验 | — |
| 熔断参数 | ✅ `AgentWaiterConfig` 模型校验 | — |
| `data_sources.yaml` | ⚠️ 未纳入 schema | 优先级配置错误不报错 |
| `agent_profiles.json` | ⚠️ 未纳入 schema | 进化参数越界不报错 |
| 环境变量 | ⚠️ 无类型检查 | FDB_LOG_LEVEL 写错值静默降级为 INFO |

> 详见 [差距分析](08-gap-analysis.md) G1 / G14 状态。

## 7. PostgreSQL 数据库配置 (v8.3.0 新增)

### 7.1 数据库连接配置

> PG 配置通过环境变量管理（见 §7.2），由 `fdt_pg/config.py` 中的代码默认值提供，无独立 YAML 配置文件。

### 7.2 环境变量

| 变量 | 默认值 | 用途 | 来源 |
|:-----|:-------|:-----|:-----|
| `PG_HOST` | `localhost` | PostgreSQL 主机 | `fdt_pg/config.py` |
| `PG_PORT` | `5432` | PostgreSQL 端口 | `fdt_pg/config.py` |
| `PG_DATABASE` | `fdt` | 数据库名 | `fdt_pg/config.py` |
| `PG_USERNAME` | `fdt_user` | 用户名 | `fdt_pg/config.py` |
| `PG_PASSWORD` | (必填) | 密码 | `fdt_pg/config.py` |
| `PG_SCHEMA` | `public` | Schema | `fdt_pg/config.py` |
| `PG_POOL_MAX` | `10` | 连接池最大连接数 | `fdt_pg/config.py` |

### 7.3 表与视图清单

| 对象 | 类型 | 用途 | 分区 |
|:-----|:-----|:-----|:-----|
| `scan_signals` | 表 | 信号扫描结果 | 按 `date` 分区 |
| `chain_analysis` | 表 | 产业链分析 | 按 `date` 分区 |
| `technical_scores` | 表 | 技术面评分 | 按 `date` 分区 |
| `fundamental_scores` | 表 | 基本面评分 | 按 `date` 分区 |
| `debate_verdicts` | 表 | 辩论裁决 | 按 `date` 分区 |
| `trading_plans` | 表 | 交易方案 | 按 `date` 分区 |
| `risk_checks` | 表 | 风控审核 | 按 `date` 分区 |
| `langgraph_checkpoints` | 表 | LangGraph 状态历史 | 按 `thread_id` 分区 |
| `log_entries` | 表 | 统一日志 | 按 `timestamp` 分区 |
| `execution_followup` | 表 | 裁决回溯 | 按 `date` 分区 |
| `agent_profiles` | 表 | Agent 进化参数 | — |
| `calibration` | 表 | 权重校准 | — |
| `v_debate_summary` | 视图 | 辩论汇总 (OLAP) | — |
| `v_signal_performance` | 视图 | 信号绩效 (OLAP) | — |
| `v_agent_effectiveness` | 视图 | Agent 效能 (OLAP) | — |

## 8. 独立运行配置 (v8.3.0 新增)

### 8.1 CLI 入口配置

> CLI 参数通过命令行参数和环境变量配置，`config/cli.yaml` 不存在。

### 8.2 API 服务配置

> API 配置通过环境变量管理，`config/api.yaml` 不存在。


### 8.3 独立运行环境变量

| 变量 | 默认值 | 用途 | 来源 |
|:-----|:-------|:-----|:-----|
| `FDT_MODE` | `cli` | 运行模式: cli / api | `fdt_cli.py` / `fdt_api.py` |
| `FDT_CRON` | `0 9 * * 1-5` | 守护进程 cron 表达式 | `fdt_cli.py` |
| `FDT_API_HOST` | `0.0.0.0` | API 监听地址 | `fdt_api.py` |
| `FDT_API_PORT` | `8000` | API 监听端口 | `fdt_api.py` |
| `FDT_API_KEY` | (未设置) | API 认证密钥 | `fdt_api.py` |
| `FDT_LOG_DIR` | `logs/` | 日志目录 (去 WorkBuddy) | `unified_logger.py` |

> **WorkBuddy 路径迁移**: `~/Documents/WorkBuddy/Logs/` 已废弃，默认改为项目内 `logs/` 目录。通过 `FDT_LOG_DIR` 环境变量可自定义。
