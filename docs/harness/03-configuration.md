# 03 — 配置管理

## 1. 配置文件清单

### 1.1 项目级配置

| 文件 | 路径 | 格式 | 用途 | 修改频率 |
|:-----|:-----|:-----|:-----|:---------|
| `plugin.json` | 根目录 | JSON | 插件清单: 10 agents + 2 skills 声明 | 低 (版本升级时) |
| `settings.json` | 根目录 | JSON | 全局设置: 模式/阈值/webhooks/backtest | 中 |
| `team_config.json` | `config/team_config.json` | JSON | 团队环境: 自进化开关/快通道/venv | 低 |
| `pyproject.toml` | 根目录 | TOML | Python 包: 依赖/pytest/black/ruff | 低 |
| `requirements.txt` | 根目录 | TXT | 核心依赖列表 | 低 |
| `requirements.lock` | 根目录 | TXT | 冻结依赖 (可复现安装) | 低 |

### 1.2 Skill 级配置 (YAML)

| 文件 | 路径 | 用途 |
|:-----|:-----|:-----|
| `varieties.yaml` | `skills/quant-daily/scripts/references/` | 62 个期货品种定义 |
| `symbol_map.yaml` | `futures_data_core/config/` | 品种映射定义（含交易所/合约乘数/最小变动价位/分类） |
| `overseas_varieties.yaml` | `skills/quant-daily/scripts/references/` | 海外品种定义 |
| `data_sources.yaml` | `futures_data_core/config/` | 数据源降级链配置 (DataCore→TDX→WebFallback→QMT→TqSDK) |
| `datatech.yaml` | `config/agents/datatech.yaml` | 数技源角色定义 + P1角色矫正(v9.6.8) stats产出规范 |
| `judge.yaml` | `config/agents/judge.yaml` | 闫判官角色定义 + P1角色矫正(v9.6.8) 数据消费优先级 |
| `technical_researcher.yaml` | `config/agents/technical_researcher.yaml` | 观澜角色定义 + P1角色矫正(v9.6.8) 输出语义澄清 |

### 1.3 记忆级配置 (JSON, 运行时可变)

| 文件 | 路径 | 用途 | 写入者 |
|:-----|:-----|:-----|:-------|
| `agent_profiles.json` | `memory/` | Agent 进化参数 (ATR乘数/仓位%/论据权重) | `evolve_agents.py` |
| `calibration.json` | `memory/` | 评分权重校准表 | `calibrate_weights.py` |
| `debate_weights.json` | `memory/` | 辩论权重配置 | 手动/脚本 |
| `execution_followup.json` | `memory/` | 裁决执行回溯 (待验证队列) | `record_verdicts.py` |
| `instrument_strategy_matrix.json` | `memory/` | 品种×策略族适应性矩阵 (F1-F5) | `update_matrix.py` |
| `schedule_state.json` | `memory/` | 调度器状态 (PID/心跳/触发时间) | `scheduler/engine.py` |
| `dominant_map.json` | `memory/` | 主力合约映射持久化（品种→当前主力合约代码） | `dominant_resolver.py` |

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
  "max_debate_rounds": 2,                     // v8.9.0 交叉质询最大轮次
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
version = "9.0.0"   # 唯一版本源（经 scripts/fdt_paths.py:get_fdt_version() 运行时读取）
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
| `FDB_LOG_DIR` | `logs/` | 日志文件目录 | `unified_logger.py` |
| `DEBATE_HISTORY_DIR` | 项目内默认路径 | 辩论历史目录 (可覆盖) | `debate/history.py` |
| `TRAINING_ORCHESTRATOR_DIR` | 项目内默认路径 | ML 模型存储目录 | `ml/trainer.py` |
| `PYTHONIOENCODING` | (未设置) | Python IO 编码 (pipeline 强制设为 `utf-8`) | `pipeline/runner.py` |
| `DCE_API_KEY` | (未设置) | 大商所官方 API key；设置后 DCE 持仓排名走官方 API（见 `futures_data_core/f10/dce_api.py`） | `f10/position.py` |
| `DCE_API_SECRET` | (未设置) | 大商所官方 API secret；与 `DCE_API_KEY` 配对 | `f10/position.py` |
| `FDT_USE_LANGGRAPH` | `false` | 控制 `pipeline/runner.py` 使用 LangGraph 模式（A/B 切换）：`true`=走 LangGraph 路径，`false`=走旧 subprocess 路径（零风险） | `pipeline/runner.py` |
| `FDT_LANGGRAPH_MODE` | `default` | LangGraph 模式选择：`default`/`fast`/`deep_research`/`tournament`；仅当 `FDT_USE_LANGGRAPH=true` 时生效 | `pipeline/runner.py` `fdt_langgraph/graph.py` |
| `FDT_CHECKPOINTER` | `sqlite` | Checkpointer 后端选择：`pg`=PostgreSQL，`sqlite`=SQLite；`pg` 连接失败自动降级到 `sqlite` | `fdt_langgraph/graph.py` `_get_checkpointer()` |
| `FDT_DIRECT_DEBATE` | `false` | 设为 `true` 时跳过 P1 扫描阶段，直接从 `fdt_cache/` 加载缓存数据进入指定品种辩论模式 | `fdt_langgraph/graph.py` |
| `FDT_DEBATE_SYMBOLS` | (未设置) | 指定辩论品种列表，逗号分隔（如 `SF,SM,SC`）；仅当 `FDT_DIRECT_DEBATE=true` 时生效 | `fdt_langgraph/graph.py` |
| `FDT_DATA_SOURCE` | `fdc` | 数据源选择：`fdc`=futures_data_core 包（默认），`datacore`=datacore.fdc_compat 包。通过 `data_source_adapter.py` 统一适配层切换所有消费者的数据路由 | `data_source_adapter.py` |
|
| `FDT_CACHE_DIR` | `{FDT_ROOT}/memory/` | 本地 SQLite 缓存数据库目录，存放按品种+数据类型持久化的 K 线/基本面/基差数据缓存文件 | `fdt_cache/` 模块 |
| `JIN10_MCP_URL` | `https://mcp.jin10.com/mcp` | 金十数据 MCP 服务地址 | `futures_data_core/f10/jin10_mcp.py` |
| `JIN10_MCP_TOKEN` | (未设置) | 金十数据 MCP Bearer Token；设置后启用金十 MCP 快讯/资讯/日历数据 | `futures_data_core/f10/jin10_mcp.py` |
| `FDT_MCP_TIMEOUT` | `30` | MCP 工具调用超时时间（秒） | `futures_data_core/mcp_client.py` |

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
    _LOG_DIR = "logs/"                                     # 代码默认值
```

## 5. 数据源配置

### 5.1 降级链 (data_sources.yaml)

```
通达信 TDX TQ-Local (优先级 0, 最高)
    ↓ 不可用时降级
WebFallback (优先级 1, 东方财富+新浪免费API)
    ↓ 不可用时降级
QMT/xtquant (优先级 2, 本地TCP直取)
    ↓ 不可用时降级
TqSDK (优先级 98, 末位兜底, 云端API)
    ↓ 全部实时源失败
缓存兜底 (Postgres / Redis)
    ↓ 缓存未命中
UNAVAILABLE (无数据)
```

> **2026-07-15 调整说明**：WebFallback 前置于 QMT/TqSDK，以规避 TqSDK `TqApi.close()` 偶发挂死 300s 的问题。TqSDK 作为末位兜底，由超时保护（建连 15s + 拉取 25s + close 5s）兜住。

### 5.2 数据源能力矩阵

| 数据源 | K线周期 | 行情快照 | 技术指标 | Tick | F10数据 | 超时 |
|:-------|:--------|:--------|:--------|:-----|:--------|:-----|
| **TDX TQ-Local** | daily/60m/120m/240m/weekly | ✅ | ✅ (DMI/RSI/CCI/MACD/MA/BOLL/OBV) | ❌ | ❌ | 3s |
| **WebFallback** | daily (新浪主, 东方财富辅) | ❌ | ❌ | ❌ | ❌ | — |
| **QMT/xtquant** | tick/1m/5m/15m/30m/60m/daily/weekly/monthly | ❌ | ❌ | ✅ | ✅ (期限结构/基差期货端) | 20s |
| **TqSDK** | 全周期 (含 tick) | ✅ | ❌ | ✅ | ✅ (EDB库存/基差/宏观/利润) | 建连15s/拉取25s |

### 5.3 数据源选择逻辑

| 场景 | 盘中 | 盘后 | 实时价 |
|:-----|:-----|:-----|:-------|
| TDX 可用 | TDX (close=实时价) | TDX | TDX |
| TDX 不可用 | WebFallback | WebFallback | (无实时价) |
| WebFallback 不可用 | QMT | QMT | (无实时价) |
| QMT 不可用 | TqSDK | TqSDK | TqSDK |
| 全部实时源不可用 | 缓存兜底 | 缓存兜底 | (无实时价) |

### 5.4 K线一致性

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

> **2026-07-20 更新**：G1 已扩展——`config/schema.py` 现提供 `Settings` / `TeamConfig` / `AgentWaiterConfig` / `DataSourcesConfig` / `AgentProfilesData` 等 Pydantic 模型，覆盖全部 4 个配置文件。环境变量校验因运行时快速暴露（LLM 调用失败立即报错），保留为已知缺口不补。

| 配置 | 状态 | 残留风险 |
|:-----|:-----|:-----|
| `settings.json` | ✅ `Settings` 模型校验 | — |
| `team_config.json` | ✅ `TeamConfig` 模型校验 | — |
| 熔断参数 | ✅ `AgentWaiterConfig` 模型校验 | — |
| `data_sources.yaml` | ✅ `DataSourcesConfig` 模型校验 | 优先级(0-99)、名称唯一性、降级/新鲜度阈值 |
| `agent_profiles.json` | ✅ `AgentProfilesData` 模型校验 | `_meta` 版本格式、风控明参数范围、辩手置信度边界 |
| 环境变量 | ⚠️ 无类型检查 | FDB_LOG_LEVEL 写错值静默降级为 INFO |
| 逐Agent LLM 环境变量 (v8.9.1) | ⚠️ 无类型校验 | `FDT_LLM_<NAME>_API_KEY` 空值不报错、`FDT_LLM_<NAME>_API_BASE` 格式错误不报错 |

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
| `FDT_LOG_DIR` | `logs/` | 日志目录 | `unified_logger.py` |

### 3.3 逐Agent LLM 配置 (v8.9.1)

每个子 Agent 可独立配置不同的 LLM（API Key、Base URL、模型名）。优先级：**逐Agent 环境变量 > 全局 LLM 环境变量 > 代码默认值**。

**环境变量命名规则：**

```
FDT_LLM_<AGENT_NAME>_API_KEY    # 逐Agent API Key
FDT_LLM_<AGENT_NAME>_API_BASE   # 逐Agent API Base URL
FDT_LLM_<AGENT_NAME>_MODEL      # 逐Agent 模型名
```

其中 `<AGENT_NAME>` 为 Agent 注册名的大写蛇形（如 `TECHNICAL_RESEARCHER`、`FUNDAMENTAL_RESEARCHER`）。

**当前注册的 Agent 列表**（来自 `agents/` 目录）：

| Agent 注册名 | 对应文件 | 默认角色 |
|:-------------|:---------|:---------|
| `futures-affirmative-debater` | `agents/futures-affirmative-debater.md` | 正方辩手 |
| `futures-chain-analyst` | `agents/futures-chain-analyst.md` | 产业链分析师（链证源） |
| `futures-datatech` | `agents/futures-datatech.md` | 数技源 |
| `futures-debate-team-team-lead` | `agents/futures-debate-team-team-lead.md` | 明鉴秋（调度） |
| `futures-fundamental-researcher` | `agents/futures-fundamental-researcher.md` | 基本面研究员（探源） |
| `futures-judge-deputy` | `agents/futures-judge-deputy.md` | 副裁官 |
| `futures-judge-heldout` | `agents/futures-judge-heldout.md` | 独立裁官 |
| `futures-judge` | `agents/futures-judge.md` | 闫判官 |
| `futures-opposition-debater` | `agents/futures-opposition-debater.md` | 反方辩手 |
| `futures-risk-manager` | `agents/futures-risk-manager.md` | 风控明 |
| `futures-technical-researcher` | `agents/futures-technical-researcher.md` | 技术面研究员（观澜） |

**各节点实际使用的 Agent 映射**（`fdt_langgraph/nodes.py` 内）：

| LangGraph 节点 | Agent 注册名 | 可用的逐Agent 环境变量前缀 |
|:---------------|:-------------|:---------------------------|
| `node_judge_direction` | `judge` | `FDT_LLM_JUDGE_*` |
| `node_technical` | `technical_researcher` | `FDT_LLM_TECHNICAL_RESEARCHER_*` |
| `node_fundamental` | `fundamental_researcher` | `FDT_LLM_FUNDAMENTAL_RESEARCHER_*` |
| `node_bullish_v1` | `bullish_analyst` | `FDT_LLM_BULLISH_ANALYST_*` |
| `node_bearish_v1` | `bearish_analyst` | `FDT_LLM_BEARISH_ANALYST_*` |
| `node_bullish_rebuttal` | `bullish_analyst` | `FDT_LLM_BULLISH_ANALYST_*` |
| `node_bearish_rebuttal` | `bearish_analyst` | `FDT_LLM_BEARISH_ANALYST_*` |
| `node_bear_final` | `bearish_analyst` | `FDT_LLM_BEARISH_ANALYST_*` |
| `node_bull_final` | `bullish_analyst` | `FDT_LLM_BULLISH_ANALYST_*` |
| `node_verdict` | `judge` | `FDT_LLM_JUDGE_*` |
| `node_risk_check` | `risk_manager` | `FDT_LLM_RISK_MANAGER_*` |

**配置示例：**

```bash
# 全局默认（所有 Agent 共用 Deepseek）
set FDT_LLM_API_KEY=sk-your-deepseek-key
set FDT_LLM_API_BASE=https://api.deepseek.com/v1
set FDT_LLM_MODEL=deepseek-chat

# 覆盖：观澜（技术面研究员）使用 GPT-4o
set FDT_LLM_TECHNICAL_RESEARCHER_API_KEY=sk-your-openai-key
set FDT_LLM_TECHNICAL_RESEARCHER_API_BASE=https://api.openai.com/v1
set FDT_LLM_TECHNICAL_RESEARCHER_MODEL=gpt-4o

# 覆盖：探源（基本面研究员）使用 Claude
set FDT_LLM_FUNDAMENTAL_RESEARCHER_API_KEY=sk-ant-your-claude-key
set FDT_LLM_FUNDAMENTAL_RESEARCHER_API_BASE=https://api.anthropic.com/v1
set FDT_LLM_FUNDAMENTAL_RESEARCHER_MODEL=claude-3-5-sonnet-20241022

# 覆盖：风控明使用本地部署模型
set FDT_LLM_RISK_MANAGER_API_KEY=not-needed
set FDT_LLM_RISK_MANAGER_API_BASE=http://localhost:1234/v1
set FDT_LLM_RISK_MANAGER_MODEL=local-model
```

**回退链逻辑（`fdt_langgraph/agents.py`）：**

```
逐Agent 环境变量 FDT_LLM_<NAME>_XXX
    ↓ 不存在时回退
全局环境变量 FDT_LLM_XXX
    ↓ 不存在时回退
代码默认值（FDT_LLM_API_BASE 默认 https://api.deepseek.com/v1）
```

> **日志目录**: 默认使用项目内 `logs/` 目录，通过 `FDT_LOG_DIR` 环境变量可自定义。

## 9. 成本工程规范（v9.6.4+）

> **设计目标**: 通过系统化的成本控制策略，在保证服务质量的前提下最小化 LLM 调用成本

### 9.1 Token 估算公式

**单次 LLM 调用成本估算**:

```python
# 输入成本 = 输入 tokens × 输入单价
input_cost = input_tokens * input_price_per_token

# 输出成本 = 输出 tokens × 输出单价  
output_cost = output_tokens * output_price_per_token

# 总成本 = 输入成本 + 输出成本
total_cost = input_cost + output_cost

# 每轮辩论成本（估算）
debate_cost = sum(total_cost for agent in [judge, chain, technical, fundamental, bullish, bearish])
```

**各 Agent 典型 Token 消耗**:

| Agent | 输入 Token | 输出 Token | 调用次数/轮 | 估算成本/轮 |
|:------|:----------:|:----------:|:-----------:|:-----------:|
| 数技源 | 500 | 300 | 1 | 低 |
| 闫判官 | 5000 | 500 | 2 (方向+裁决) | 中高 |
| 链证源 | 3000 | 800 | 1 | 中 |
| 观澜 | 3000 | 800 | 1 | 中 |
| 探源 | 4000 | 1000 | 1 | 中高 |
| 证真 | 6000 | 1200 | 2 (立论+反驳) | 高 |
| 慎思 | 6000 | 1200 | 2 (立论+反驳) | 高 |
| 风控明 | 2000 | 300 | 1 | 低 |

### 9.2 缓存 TTL 耦合策略

**缓存层级与 TTL**:

| 缓存层级 | 数据类型 | TTL | 存储位置 |
|:---------|:---------|:----|:---------|
| L1 内存缓存 | 当日 K线/指标 | 10分钟 | `fdt_cache/` |
| L2 本地 SQLite | 历史 K线/基本面 | 24小时 | `memory/fdt_cache/` |
| L3 PostgreSQL | 辩论历史/裁决 | 永久 | `pg.debate_verdicts` |

**TTL 耦合规则**:

```python
# TTL 与数据新鲜度要求耦合
if data_type == "kline":
    ttl = 10 * 60  # 10分钟（盘中实时）
elif data_type == "fundamental":
    ttl = 24 * 3600  # 24小时（基本面变化慢）
elif data_type == "verdict":
    ttl = 0  # 永久（历史裁决不可变）
elif data_type == "debate_history":
    ttl = 7 * 24 * 3600  # 7天（辩论历史参考）
```

### 9.3 降本手段排序

| 优先级 | 手段 | 预期降本 | 实现难度 | 风险 |
|:-------|:-----|:--------:|:--------:|:-----|
| **P0** | 缓存优先 | 30-50% | 低 | 低 |
| **P0** | 低精度模型降级 | 40-60% | 中 | 中 |
| **P1** | Token 裁剪 | 10-20% | 中 | 低 |
| **P1** | 并行调用限制 | 10-15% | 低 | 低 |
| **P2** | 批量请求合并 | 5-10% | 高 | 低 |
| **P2** | 本地模型替换 | 80-90% | 高 | 高 |

### 9.4 成本监控指标

| 指标 | 定义 | 阈值 | 告警动作 |
|:-----|:-----|:-----|:---------|
| `daily_cost` | 每日 LLM 调用总成本 | > ¥50 | 发送告警 |
| `avg_cost_per_debate` | 每轮辩论平均成本 | > ¥5 | 审查 Agent 配置 |
| `cache_hit_rate` | 缓存命中率 | < 70% | 优化缓存策略 |
| `token_waste_rate` | 无效 Token 比例 | > 20% | 优化 Prompt |

### 9.5 成本控制环境变量

| 变量 | 默认值 | 用途 |
|:-----|:-------|:-----|
| `FDT_COST_LIMIT_DAILY` | `50` | 每日成本上限（元） |
| `FDT_COST_LIMIT_PER_DEBATE` | `5` | 每轮辩论成本上限（元） |
| `FDT_CACHE_ENABLED` | `true` | 是否启用缓存 |
| `FDT_MODEL_FALLBACK` | `true` | 是否启用模型降级 |
| `FDT_TOKEN_TRIM_ENABLED` | `true` | 是否启用 Token 裁剪 |

## 10. CI/CD 流水线配置（v9.12.0+）

### 10.1 流水线架构

配置文件：`.github/workflows/ci.yml`

4 个并行 Job：

| Job | 运行环境 | 覆盖范围 | 预计耗时 |
|:----|:---------|:---------|:--------|
| **lint** | ubuntu-latest | ruff 代码检查 + Harness pre-commit 规范检查 | ~2min |
| **test-core** | windows-latest | `tests/strategies/`、`tests/fdt_langgraph/`、`tests/fdt_scripts_tests/`、`tests/validators/` | ~5min |
| **test-data** | windows-latest | `tests/commodity-chain/`、`tests/contracts/`、`tests/fdt-gate/`、`tests/technical-analysis/` | ~3min |
| **test-skills** | windows-latest | `tests/quant-daily/`、`tests/debate-argument-builder/`、`tests/debate-risk-manager/`、`tests/fundamental-data-collector/` | ~4min |

### 10.2 触发器

- `push` 到 `main` 分支
- `pull_request` 到 `main` 分支
- 支持 `workflow_dispatch` 手动触发

### 10.3 GitHub Secrets 配置

在仓库 **Settings → Secrets and variables → Actions** 中添加：

| 名称 | 用途 | 必需 |
|:-----|:-----|:----|
| `JIN10_MCP_TOKEN` | 金十 MCP 财经数据 Bearer Token | 否（无此 Token 则跳过相关测试） |

### 10.4 Python 依赖安装策略

每个 Job 独立安装最小依赖集（而非全量安装），以缩短安装时间：

| Job | 安装包 |
|:----|:-------|
| lint | `ruff`, `pyyaml` |
| test-core | `pytest`, `pytest-cov`, `numpy`, `pandas`, `scipy`, `lightgbm`, `scikit-learn`, `langgraph`, `sqlalchemy`, `pydantic` |
| test-data | `pytest`, `numpy`, `pandas`, `scipy`, `sqlalchemy`, `pydantic` |
| test-skills | `pytest`, `numpy`, `pandas`, `scipy`, `pydantic`, `sqlalchemy` |

### 10.5 检查档位

| 检查 | 档位 | 阻断 |
|:-----|:-----|:-----|
| ruff lint | L1 | 否（`continue-on-error: true`） |
| Harness pre-commit | L1 | 否（`continue-on-error: true`） |
| 测试失败 | L2 | 否（`continue-on-error: true`） |

> 所有测试 Job 当前设为 `continue-on-error: true`（信息性），待基础测试稳定后逐步改为阻断。

### 10.6 本地模拟 CI 运行

```bash
# 安装依赖
pip install ruff pyyaml pytest numpy pandas scipy

# 检查
ruff check .
python scripts/pre_commit_harness_check.py

# 运行测试
python -m pytest tests/strategies/ --tb=short -q -o "addopts="
```
