# 07 — 运维与部署

## 1. 部署模式

### 1.1 单机模式 (默认)

```
┌─────────────────────────────────────────────────────────────┐
│              单机部署架构 (v8.3.0+ — 独立运行)                │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐  │
│  │ fdt_cli.py       │    │ fdt_api.py                   │  │
│  │ (CLI入口)        │    │ (FastAPI HTTP服务)           │  │
│  └────────┬─────────┘    └─────────────┬────────────────┘  │
│           │                            │                    │
│           └──────────────┬─────────────┘                    │
│                          ▼                                  │
│              ┌────────────────────┐                         │
│              │ APScheduler        │                         │
│              │ (cron: 0 9 * * 1-5)│                         │
│              └──────────┬─────────┘                         │
│                         │ 触发                              │
│              ┌──────────▼─────────┐                         │
│              │ FdtDebateGraph     │ ← LangGraph 编译图      │
│              │ (fdt_langgraph/)   │                         │
│              └──────────┬─────────┘                         │
│                         │                                   │
│              ┌──────────▼─────────┐                         │
│              │ PostgreSQL 16+     │ ← OLTP+OLAP 混合存储    │
│              │ scan_signals       │                         │
│              │ chain_analysis     │                         │
│              │ debate_verdicts    │                         │
│              │ langgraph_checkpoints│                        │
│              │ v_debate_summary   │ ← OLAP 视图            │
│              └────────────────────┘                         │
│                                                             │
│  ┌───────────┐                                              │
│  │ Python    │                                              │
│  │ 3.12/3.13 │                                              │
│  └───────────┘                                              │
└─────────────────────────────────────────────────────────────┘
```

**特点**:
- 所有组件在同一台机器运行
- 独立运行，不依赖 WorkBuddy 平台
- CLI (`fdt_cli.py`) + FastAPI (`fdt_api.py`) 双入口
- PostgreSQL OLTP+OLAP 混合存储（替代 DuckDB）
- 依赖本地数据源 (TDX/TqSDK)

### 1.2 分布式模式 (可选)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scan Node   │     │ Debate Node  │     │ Report Node  │
│              │     │              │     │              │
│ scan_all.py  │     │ Agent spawn  │     │ phase3_      │
│ 数据采集     │     │ 多空辩论     │     │ generate_    │
│              │     │              │     │ report.py    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                   ┌────────▼────────┐
                   │   Redis Broker  │
                   │                 │
                   │ 4个队列:        │
                   │ scanning        │
                   │ debate          │
                   │ backtest        │
                   │ report          │
                   └────────┬────────┘
                            │
                   ┌────────▼────────┐
                   │  Celery Workers │
                   │ (多节点扩展)    │
                   └─────────────────┘
```

**配置文件**: `deploy/celery_config.py`

**特点**:
- Celery + Redis 分布式任务队列
- 4 个独立队列 (扫描/辩论/回测/报告)
- 支持多节点水平扩展
- 需要额外基础设施 (Redis)

## 2. 环境准备

### 2.1 依赖安装

```bash
# 核心依赖
pip install numpy pandas pyyaml duckdb requests akshare pydantic psutil lightgbm scikit-learn

# 可选: TqSDK (TDX降级备用)
pip install tqsdk

# 可选: 分布式部署
pip install celery redis ray

# 可选: ML扩展
pip install xgboost

# 或使用冻结依赖 (推荐, 可复现)
pip install -r requirements.lock
```

### 2.2 Python 环境

| 优先级 | 版本 | 路径 | 用途 |
|:-------|:-----|:-----|:-----|
| 首选 | 3.13.12 (managed) | `~/.workbuddy/binaries/python/versions/3.13.12/` | WorkBuddy 托管 |
| 备选 | 3.12.10 (system) | `C:\Program Files\Python312\` | 系统安装 |

> **用户偏好**: 默认使用系统 Python 3.12 (`C:\Program Files\Python312\python.exe`)，包安装走 `--user` 模式。

### 2.3 数据源准备

| 数据源 | 安装/配置 | 优先级 |
|:-------|:----------|:-------|
| 通达信 TDX TQ-Local | 安装通达信客户端 + 开启 TQ-Local HTTP 服务 | 0 (最高) |
| TqSDK | `pip install tqsdk` + 账号配置 | 1 |
| 东方财富 | 无需安装 (HTTP API) | 2 |
| AKShare | `pip install akshare` | 3 (最后降级) |

## 3. 调度器运维

### 3.1 启动/停止守护进程

```bash
# 启动守护进程 (后台)
python bootstrap.py daemon

# 单次检查 (不持续运行)
python bootstrap.py once

# 持续运行 (前台, 用于调试)
python scheduler/engine.py forever

# 停止守护进程
python scheduler/engine.py stop

# 查看状态
cat memory/schedule_state.json
```

### 3.2 看门狗配置

| 项 | 配置 | 说明 |
|:---|:-----|:-----|
| 检查频率 | 每 30 分钟 | WorkBuddy automation 触发 |
| 心跳阈值 | 3 分钟 | `schedule_state.json` 的 `last_heartbeat` 超过 3 分钟判定为挂 |
| PID 文件 | `memory/daemon.pid` | 用于进程存活检查 |
| 自动恢复 | 是 | 挂了自动 `bootstrap.py daemon` 重启 |

### 3.3 调度器状态文件

```json
// memory/schedule_state.json
{
  "last_heartbeat": "2026-07-10 14:30:15",
  "pid": 12345,
  "triggered": {
    "daily_debate": "2026-07-10 14:15:00",
    "auto_publish": "2026-07-09 23:05:00",
    "validate_and_evolve": "2026-07-10 14:20:00"
  }
}
```

## 4. 运维 Runbook

### 4.1 常见故障处理

#### 故障 1: 守护进程挂了

```
现象: schedule_state.json 心跳 >3分钟未更新
诊断:
  1. cat memory/daemon.pid → 获取 PID
  2. tasklist /FI "PID eq {pid}" → 检查进程是否存在
  3. tail scheduler/daemon.log → 查看最后输出

处理:
  - 进程不存在 → `python bootstrap.py daemon` (重启)
  - 进程存在但不工作 → `python scheduler/engine.py stop` → 等待优雅停机 → 重启
  - 日志报错 → 修复错误后重启
```

#### 故障 2: Agent spawn 超时

```
现象: poll_file_ready 返回 False (15分钟超时)
诊断:
  1. 检查 research_snapshots/ 下是否有 .tmp 文件 (Agent 正在写但未完成)
  2. 检查 Agent 是否被 LLM 限流 (rate limit)
  3. 检查 prompt 是否过长导致推理超时

处理:
  - .tmp 存在 → 等待 Agent 完成 (或手动 rename)
  - LLM 限流 → 降低并发, 串行 spawn
  - prompt 过长 → 精简 prompt, 移除冗余上下文
  - 持续超时 → D06 降级, 基于已有数据裁决
```

#### 故障 3: 数据源全部不可用

```
现象: scan_all.py 报错 "所有数据源均不可用"
诊断:
  1. 检查通达信客户端是否运行
  2. 检查 TQ-Local HTTP 服务是否开启
  3. 检查网络连接 (东方财富/AKShare)
  4. 检查 data_sources.yaml 配置

处理:
  - TDX 客户端未运行 → 启动通达信
  - TQ-Local 未开启 → 通达信设置中开启
  - 网络问题 → 等待恢复
  - 全部不可用 → 跳过当日分析, 记录到 incidents.md
```

#### 故障 4: 报告生成失败

```
现象: phase3_generate_report.py 非零退出
诊断:
  1. 检查 debate_results.json 是否存在且有效
  2. 检查 4 铁律核验是否通过
  3. 检查 HTML 模板是否完整

处理:
  - JSON 无效 → 修复数据格式
  - 铁律未通过 → 补齐缺失字段
  - 模板问题 → 检查 phase3 脚本
  - 路径问题 → 使用 --workspace 参数指定
```

#### 故障 5: 自进化闭环断裂

```
现象: validate_verdicts.py 无输出
诊断:
  1. 检查 execution_followup.json 是否有待验证裁决
  2. 检查 K 线数据是否已更新到 T+1
  3. 检查 validate_verdicts.py 的 --t1/--t3 参数

处理:
  - 无待验证 → 正常 (skip_when_no_pending=true)
  - K线未更新 → 等待数据源更新
  - 参数错误 → 调整 --t1 (T+1) / --t3 (T+3)
```

### 4.2 日常运维检查清单

| 检查项 | 频率 | 命令/方法 |
|:-------|:-----|:----------|
| 守护进程存活 | 每日 | `cat memory/daemon.pid` + `tasklist` |
| 心跳正常 | 每日 | `cat memory/schedule_state.json` |
| 最新报告生成 | 每日 | 检查 `Commodities/Reports/.../{date}/debate_results.html` |
| 日志无异常 | 每日 | `tail ~/Documents/WorkBuddy/Logs/fdb_{date}.log` |
| 辩论归档完整 | 每周 | `cat memory/debates/INDEX.md` |
| APM 评分 | 每周 | `cat memory/apm_scorecard.json` |
| 测试通过 | 每周 | `python -m pytest tests/pipeline/ tests/scheduler/ tests/memory/ tests/contracts/ --no-cov` |
| APM 监控看板 | 实时 | `python scripts/dashboard.py` → 浏览器打开 `dashboard.html` |
| 健康端点 | 实时 | `python scripts/health_server.py &` → `curl 127.0.0.1:8910/health` |
| 依赖更新 | 每月 | `pip list --outdated` |
| 磁盘空间 | 每月 | 检查 `Commodities/Reports/` 目录大小 |
| 版本同步 | 每月 | `python C:/Users/yangd/quant-bare/sync_experts_to_github.py` |

#### 新增运维工具（v5.7）

```bash
# 生成实时监控看板
python scripts/dashboard.py

# 持续监视模式（每30秒刷新）
python scripts/dashboard.py --watch

# 启动健康检查服务器
python scripts/health_server.py                # 默认 127.0.0.1:8910
python scripts/health_server.py --port 9000    # 自定义端口

# 检查系统状态
curl http://127.0.0.1:8910/health    # 组件状态 + uptime
curl http://127.0.0.1:8910/metrics   # APM 五轴 + 测试统计
```

## 5. 上线四步评估流程（v9.6.4+）

> **设计目标**: 通过标准化的四步评估流程，确保每次上线变更的质量和安全性

### 5.1 评估流程

```
Step 1: 影子模式 ──→ Step 2: 金标准比对 ──→ Step 3: 验证器验收 ──→ Step 4: 金丝雀发布
     ↓                      ↓                      ↓                      ↓
  并行运行               结果比对               质量门禁               渐进放量
  不影响生产             差异分析               通过/失败               全量上线
```

### 5.2 Step 1: 影子模式

| 项目 | 说明 |
|:-----|:-----|
| **目标** | 新代码与生产代码并行运行，不影响生产输出 |
| **运行方式** | `FDT_USE_LANGGRAPH=true` + 生产代码同时运行 |
| **输出** | 两份独立的辩论结果（影子 vs 生产） |
| **持续时间** | 至少 3 个交易日 |
| **验收条件** | 影子模式无崩溃，输出格式与生产一致 |

### 5.3 Step 2: 金标准比对

| 项目 | 说明 |
|:-----|:-----|
| **目标** | 对比影子模式与生产模式的结果差异 |
| **比对维度** | 品种选择、方向判定、交易参数、置信度 |
| **工具** | `scripts/run_benchmark.py --replay` |
| **验收条件** | 方向一致性 ≥ 95%，价格偏差 ≤ 5% |

### 5.4 Step 3: 验证器验收

| 项目 | 说明 |
|:-----|:-----|
| **目标** | 通过质量门禁验证新代码的正确性 |
| **验证项** | 漏放率 ≤ 1%，误杀率 ≤ 5% |
| **工具** | `scripts/validate_llm_output.py` + 门禁测试 |
| **验收条件** | 所有验证器质量指标达标 |

### 5.5 Step 4: 金丝雀发布

| 阶段 | 比例 | 持续时间 | 监控重点 |
|:-----|:-----|:---------|:---------|
| **金丝雀** | 10% | 1 交易日 | 错误率、延迟、成本 |
| **灰度** | 50% | 2 交易日 | 全量指标 |
| **全量** | 100% | — | 持续监控 |

### 5.6 回滚条件

| 条件 | 回滚动作 |
|:-----|:---------|
| 错误率 > 5% | 立即回滚到上一版本 |
| 延迟增加 > 20% | 立即回滚 |
| 成本增加 > 30% | 24小时内回滚 |
| 数据不一致 | 立即回滚 |

## 6. 版本管理

### 6.1 版本号规范

| 位置 | 当前版本 | 格式 |
|:-----|:---------|:-----|
| `pyproject.toml` | **9.6.5** | **唯一版本源**（`bootstrap.py` 经 `scripts/fdt_paths.py:get_fdt_version()` 运行时读取） |
| `bootstrap.py` | 动态 | 从 pyproject.toml 读取，不再硬编码 |
| `README.md` | **v9.6.5** | 与 pyproject.toml 同步 |

### 6.2 版本历史

| 版本 | 日期 | 里程碑 |
|:-----|:-----|:-------|
| v9.4.3 | 2026-07-20 | **G91 Phase 4.8 同品种多子信号合并方向覆盖 bug 修复（P0）**：① `pipeline.py` Phase 4.8 引入 `_merge_acc` 累积器，将"逐个两两平均"改为正确的"简单平均"，消除后序信号权重偏高问题；② grade 升级时不再覆盖 `direction`，direction 完全由最终平均 `total` 符号决定；③ 修复 SC 场景方向错误（4 看多 vs 2 看空，原错误输出 bear，修复后正确输出 bull）；④ 新增 `TestSubSignalMerge` 4 用例（SC 场景/全看空/平衡/grade 升级）。版本号 bump 9.4.2→9.4.3 |
| v9.4.2 | 2026-07-20 | **G89 debate_only 信号多空论据丢失修复 + G90 信号排序改为交易可靠性优先**：① G89 修复 `phase3_generate_report.py` 补充逻辑遗漏 `bull_args`/`bear_args` 字段（`missing_pids` 品种从 `debate_results` 复制论据）；② G89 修复 `fdt_langgraph/nodes.py` `node_report` 中 LLM 辩论遗漏品种论据时，从 judge reasoning 生成 `[裁决摘要]` 最小 fallback；③ G90 将 T1/T2/T3 信号排序从纯置信度改为 `置信度 × 盈亏比`（隐含胜率 × 潜在盈亏比）；④ 辩论详情模块 `SYMBOL_KEYS` 从字母序改为可靠性排序；⑤ 新增 `tests/quant-daily/test_g35_debate_only_args.py` 3 用例全绿；⑥ 同步更新 `06-testing.md` 测试计数 6→9。版本号 bump 9.4.1→9.4.2 |
| v9.4.1 | 2026-07-20 | **G88 K 线数据链路根因修复（P0）**：① 修复 `MultiSourceAdapter.get_kline()` 入口处的"自动主力解析" bug — 之前 `DominantResolver` 在 `memory/dominant_map.json` 不存在时返回 `f"{variety}00"`（如 `RB00`），这种合约代码在 WebFallback/TqSDK 等所有采集器中均识别失败，导致 K 线返回空、整个数据链路断裂；改由各采集器内部根据自身能力处理 symbol 转换（如 TqSdk 的 `_resolve_continuous` 将 `RB` 转为 `KQ.m@SHFE.rb`），避免平台无关的后备代码污染降级链；② 修复 `tests/dominant-resolver/test_fdc_fallback.py` 的 `_mock_datacore_unavailable` fixture — 改用 `sys.modules["datacore"] = None`（Python 标准约定的"不可导入"信号）替代 `del sys.modules["datacore"]`，避免 `import datacore.fdc_compat` 触发真实包 `__init__.py` 加载导致 Prometheus Counter 重复注册；③ 移除 `multi_source_adapter.py` 中未使用的 `has_month_suffix` 导入。验证：`get_kline("RB")` 恢复返回 30 根 web_fallback K 线；`compute_indicators` 返回 16 个标准指标键名（MA/EMA/RSI/MACD/BOLL 等），类型正确（MA 为 ndarray，BOLL 为 tuple）；F10 子块结构正常（term_structure/spread/basis/warrant/fundamental 均 success=True）。测试 122 passed, 1 skipped。版本号 bump 9.4.0→9.4.1 |
| v9.4.0 | 2026-07-20 | **G87 Data-Core F10 全面集成**：① 新增 `futures_data_core/core/_datacore_bridge.py` — 集中式 F10 桥接器，封装 `try_datacore_first()` + `_dc_result_to_a2a()` 模板方法；② 改造 6 个 F10 模块（term_structure/spread/basis/warrant/fundamental/position）入口 — 每模块 +3 行 Data-Core 优先检查，自动降级原有实现；③ `compute_indicators` 优先路由 Data-Core 版；④ 新增 2 个测试文件（test_datacore_bridge.py 24 用例 + test_fdc_fallback.py 12 用例）覆盖全部桥接路径和降级兼容性；⑤ 更新 4 篇 Harness 文档（01-architecture / 04-resilience / 06-testing / 07-operations）；版本号 bump 9.3.0→9.4.0 |
| v9.3.0 | 2026-07-19 | **G86 主力合约统一解析 + DataCore 集成 + 字段标准化**：① 新增 `futures_data_core/core/dominant_resolver.py` — 统一主力合约判定与换月追踪；② 改造 `MultiSourceAdapter.get_kline()` — 无合约后缀时自动解析为实际主力合约代码；③ 新增 `get_contract_kline()` / `get_all_active_contracts()` 入口确保 F10 基差/期限结构不受影响；④ 废弃 `skills/quant-daily/scripts/data/dominant_mapping.py`；⑤ 激活调度器主力映射更新任务；⑥ 新增 `DataCoreCollector` — 封装 `datacore.fdc_compat` 为 FDT BaseCollector，配置为采集器链最高优先级(0)；⑦ 更新 `data_sources.yaml` 降级链为 DataCore→TDX→WebFallback→QMT→TqSDK；⑧ 新增 `futures_data_core/core/field_normalizer.py` — 统一规范 8 类子 Agent 数据栏位（direction/oi/confidence/entry_price/grade 等），覆盖 14 个不一致点；⑨ 在 `nodes.py` 的 4 个关键数据边界（scan/judge/verdict/risk_check）集成标准化层 |
| v9.2.0 | 2026-07-18 | **Loop Engineering 剥离**... |
| v9.1.0 | 2026-07-18 | **G85 本地数据增量缓存与指定品种辩论模式**：① 新增 `fdt_cache/` — 本地 SQLite 增量缓存层，按品种+数据类型持久化 K 线/基本面/基差数据，减少重复 I/O 和网络开销；② 新增**指定品种辩论模式** — 当设置 `FDT_DIRECT_DEBATE=true` 和 `FDT_DEBATE_SYMBOLS=SF,SM,SC` 时，跳过 P1 扫描阶段，直接从 `fdt_cache/` 加载缓存数据进入 P2→P3→P4→P5→P6 流程；③ 新增 3 个环境变量 `FDT_DIRECT_DEBATE`/`FDT_DEBATE_SYMBOLS`/`FDT_CACHE_DIR`；④ 更新 5 篇 Harness 文档（01-architecture / 02-lifecycle / 03-configuration / 06-testing / 07-operations）。版本号 bump 9.0.0→9.1.0 |
| v9.0.0 | 2026-07-18 | **辩论流程重大重构：正反方→多空头模式**：① 辩论模式重构——正反方模式→多空头攻防模式，多头只论证做多，空头只论证做空；② 六阶段辩论——多头立论→空头立论→空头反驳多头→多头反驳空头→空头最终陈述→多头最终陈述→闫判官裁决；③ 分析师中立化——技术面/基本面/产业链分析师客观供弹，辩手只能使用分析师提供的资料；④ 来源可追溯——辩论上下文中每条数据均携带来源标记（`[scan]/[technical:观澜]/[fundamental:探源]/[chain:链证源]`）；⑤ 闫判官独立裁决——明确强调可推翻数技源方向，裁决输出增加 `overturn_scan` 标记。涉及 `fdt_langgraph/state.py`（新增 bearish_rebuttal_arguments 等字段）、`fdt_langgraph/nodes.py`（重写 8 个辩论节点，新增 4 个节点，删除旧 opposition 模式）、`fdt_langgraph/graph.py`（新增 6 节点辩论图，删除旧路由函数）、`config/agents/bullish_analyst.yaml`（消除内部矛盾指令）、`config/agents/bearish_analyst.yaml`（补全缺失内容）、`docs/business_flow.md`（更新多空头六阶段流程描述）。版本号 bump 8.10.0→9.0.0 |
| v8.9.4 | 2026-07-18 | **数据源配置文档同步（G78）**：修正 `docs/harness/03-configuration.md` 中数据源降级链描述与代码实际不一致的问题——原文档仍写 "TDX→TqSDK→东方财富→AKShare"，代码已演进为 "TDX→WebFallback→QMT→TqSDK"（2026-07-15 调整 Web 前置于 TqSDK 以规避 close 挂死）。① `03-configuration.md §5` 全面重写：降级链图示更新、新增数据源能力矩阵（K线/快照/指标/Tick/F10/超时）、数据源选择逻辑表补齐 QMT/WebFallback/缓存兜底；② `futures_data_core/config/data_sources.yaml` 补充 `web_fallback`（priority=1）和 `qmt_xtquant`（priority=2）配置项，TqSDK priority 从 1 修正为 98（与代码一致），新增超时/置信度等参数；③ 移除所有 AKShare 残留描述（主链中已不存在）；④ 同步更新 `03-configuration.md §1.2` 中 data_sources.yaml 路径（从 skills 目录改为 futures_data_core/config/）及 §2.3 pyproject.toml 示例版本号。版本号 bump 8.9.3→8.9.4 |
| v8.9.2 | 2026-07-18 | **深度辩论模式 Bug 修复（G77）+ 报告按需生成**：① 修复 `graph.py` `_register_p3_nodes()` `deep_research` 模式 P3 节点全被跳过导致辩论/裁决/报告无法执行的 P0 级 Bug；② `scan_all.py` 和 `nodes.py` 中 P1 扫描/排序报告改为按需生成（`FDT_GENERATE_SCAN_REPORT` 环境变量控制），默认不生成；③ 全量测试通过，辩论报告正常产出至 `D:\\FDTWorkspace\\{date}\\`。版本号 bump 8.9.1→8.9.2 |
| v8.9.1 | 2026-07-17 | **逐Agent LLM 配置**：每个子 Agent 可独立配置不同的 LLM（API Key / Base URL / Model），通过 `FDT_LLM_<AGENT_NAME>_*` 环境变量覆盖全局默认值；`agents.py` 新增 `_normalize_env_name()` / `_resolve_llm_config()` 方法，动态解析运行时环境变量；新增 16 个测试用例覆盖完整配置链（名称归一化 / 优先级 / 回退链 / 实际调用）；同步更新 `03-configuration.md §3.3`。版本号 bump 8.9.0→8.9.1 |
| v8.9.0 | 2026-07-17 | **辩论模式重构 + 测试覆盖增强 + 技术选型文档**：① P4 从「证真+慎思并行一次调用」拆分为「串行三步骤交叉质询」——`node_bullish_v1`（多头立论 v1）→ `node_bearish_v1`（空头质疑 opposition v1）→ `node_bullish_rebuttal`（多头反驳 rebuttal v2，max=1）；② `DebateState` 新增 `debate_round` 轮次计数器 + `Annotated[list, operator.add]` reducer 自动追加多轮辩论产物；③ `graph.py` 新增 `route_after_bullish_v1`/`route_after_bearish_v1`/`route_after_rebuttal` 条件边 + `MAX_DEBATE_ROUNDS=2` 常量；④ 新增 `docs/TECH_STACK_DECISIONS.md` 技术选型文档（8项关键技术决策记录）；⑤ **测试覆盖增强**：新增 3 个测试文件（`test_graph.py` 19用例 → graph.py 覆盖率 25%→93%；`test_agents.py` 56用例 → agents.py 71%→97%；`test_health.py` 42用例 → health.py 0%→100%）；⑥ 修复 state.py 初始化 `bullish_arguments={}`→`[]` 及 `node_verdict`/`node_report` reducer 兼容问题；⑦ 修复 G71 类型注解：为 scripts/ 中 12 个关键公共函数补充类型注解；⑧ 同步更新 12 项检查清单、Harness 文档。版本号 bump 8.8.9→8.9.0 |
| v8.8.9 | 2026-07-17 | **基差数据近月代理降级（G76）**：100ppi.com 启用 HW_CHECK 反爬导致基差数据全面断裂。新增 `_collect_basis_via_nearmonth()` 降级函数，通过 TdxCollector 获取近月合约价格作为现货代理，计算 `basis = near_price - main_contract_price`。方向性信号已恢复，`data_source` 标注 `near_month_proxy`，下游验证器（atr_vol_timing/p0_4_raw_kline）自动兼容。同步更新 `04-resilience.md §8.1`（降级原理与边界）、`08-gap-analysis.md`（G76 登记关闭）。版本号 bump 8.8.8→8.8.9 |
| v8.8.8 | 2026-07-17 | **cov-5 测试覆盖（P1/P2 模块）+ G71 类型注解收口**：① 新增 61 个测试用例覆盖 compliance_agent (19)/enforce_discipline (14)/evidence_scorer (14)/pre_commit_harness_check (24)/inference_gate (20)—全部通过；② G71 为 evolve_agents(11个)/extract_knowledge(4个)/run_debate(8个) 共 23 个函数补充类型注解；③ G72 导入组织 18 个文件全部闭合。累计 scripts/ 测试 **474 用例**，覆盖 **68 模块**。版本号 bump 8.8.7→8.8.8 |
| v8.8.5 | 2026-07-17 | **LangGraph 管线 Bug 修复（P0/P1/P2）**：① G70 `node_scan` 修复——改从文件读取扫描结果而非解析 stdout，scan_all 数据正确流入全管线；② G71 `node_report` 修复——逐品种基于扫描数据生成差异化方向/价格/仓位，报告含6个差异化信号（4BUY/2SELL）；③ G72 `node_signal_output` 修复——新增逐品种信号清单（abs>=60），按评分排序输出最强信号；④ 配套修复 `fdt_daily_runner.py` 禁用均值回归（加 `mean_reversion` 到 `DISABLED_STRATEGIES`）、LangGraph 模式启用、工作空间设置；⑤ `runner.py` 全品种传递。同步更新 `08-gap-analysis.md` G70-G72。版本号 bump 8.8.4→8.8.5 |
|
| v8.8.4 | 2026-07-17 | **P1/P2 Bug 修复批**：① G67 `compute_indicators()` API 不匹配修复（`node_prepare_data` 传 OHLCV dict 替代四个独立数组）；② G68 裁决/信号报告 None 格式化修复（`or 0` 模式防御 None）；③ G69 subprocess runner `debate_brief.py` 补全 l1l4/factor 两个必需位置参数；④ `fdt_daily_runner.py` 添加 `mean_reversion` 到 `DISABLED_STRATEGIES`，切换 LangGraph 模式，设置 `FDT_DAILY_WORKSPACE`；⑤ `runner.py` 传递全部品种而非限 10 个。同步更新 `08-gap-analysis.md`。版本号 bump 8.8.3→8.8.4 |
| v8.8.3 | 2026-07-17 | **Keltner 鲁棒参数训练（鲁棒评分加权）**：① 修改 `keltner_wf.py` 评分函数为鲁棒性加权（`0.1×峰值 + 0.9×3×3邻域均值`），优先选择参数平原广阔的组合；② 对63个品种完成全品种训练，`period=40, atr_mult=1.5` 被验证为最鲁棒的全局参数（25/63品种选该组合，信号加权均值 period=37.0, atr_mult=1.62，全局平均训练准确率61%/测试准确率21%）；③ 新增 `keltner_robustness.py` 鲁棒性分析器；④ 固定参数 `(40, 1.5)` 在10个代表性品种上的平均峰值得分51.4与邻域均值51.5几乎一致，验证了参数平原的广阔性（邻域平坦）；版本号 bump 8.8.2→8.8.3 |
| v8.8.2 | 2026-07-17 | **cov-4 批量测试覆盖（第二阶段·收官）**：扩展 `scripts/test_scripts.py` 新增 44 个测试用例，覆盖 4 个 scripts/ 模块（run_debate/fdt_cli/extract_knowledge/webui），累计 scripts/ 测试 **413 用例**，覆盖 **63 模块**（**412 passed / 1 skipped**）；修复 `extract_knowledge.py` 的 `confidence_utils` 导入 fallback；同步更新 `docs/harness/06-testing.md` / `08-gap-analysis.md`；G65 关闭；版本号 bump 8.8.1→8.8.2 |
| v8.8.1 | 2026-07-17 | **Keltner 通道参数 Walk-Forward 优化**：① 新增 `keltner_wf.py` 参数训练脚本，对 `period`（10/15/20/25/30/40）和 `atr_mult`（1.5~3.5，步长0.25）共54种组合进行网格搜索；② 对61个品种完成Walk-Forward训练+测试分割（70%训练/30%测试）；③ 众数参数：period=40, atr_mult=1.5；④ 更新 `TREND_G30_CONFIG.keltner`（20→40, 2.25→1.5）和 `legacy_numpy.py` Keltner计算参数；⑤ 新增 `tests/quant-daily/test_keltner_wf.py` 17个单元测试全部通过；版本号 bump 8.8.0→8.8.1 |
| v8.8.0 | 2026-07-17 | **明鉴秋报告层调度增强**：① `state.py` 新增 4 个阶段报告字段（`scan_report_path` / `research_report_path` / `verdict_report_path` / `signal_report_path`）；② `nodes.py` 新增报告层调度函数（`_resolve_report_dir` / `_render_html` / `_write_*_report`），覆盖 P1/P3/P5/P6/P6a 五个阶段；③ P6 `node_report` 修复 fallback 路径，输出到用户指定工作空间（`FDT_REPORT_WORKSPACE` / `FDT_DAILY_WORKSPACE`）而非 `/tmp`；④ `fdt_cli.py` 新增 `_print_phase_reports()` 统一输出各阶段报告路径；⑤ 新增 `tests/fdt_langgraph/test_reports.py` 12 个测试用例全部通过；⑥ 同步更新 Harness 文档（01-architecture / 02-lifecycle §2.4 / 04-resilience §9.5.1 / 06-testing §2.1）；版本号 bump 8.7.1→8.8.0 |
| v8.7.1 | 2026-07-17 | **cov-4 批量测试覆盖（第一阶段）**：扩展 `scripts/test_scripts.py` 新增 57 个测试用例，覆盖 16 个 scripts/ 根目录及子目录模块（logutil/fdt_version/health_check/run_reporter/record_verdicts/notifier/llm.cache/llm.token_budget/spawn_resource_check/model_registry/debate_archiver/ops_monitor/auto_publish/auto_train/market_game_agent/marl_trainer），累计 scripts/ 测试 69 用例；**总测试 69 passed**；版本号 bump 8.7.0→8.7.1；同步更新 `docs/harness/06-testing.md` / `07-operations.md` / `08-gap-analysis.md` |
| v8.7.0 | 2026-07-17 | **架构精简 v2**：删除策略师子 Agent（策执远），将其职责合并到闫判官（直接输出完整交易参数）和风控明（复验止盈止损/盈亏比）；删除 `node_trading_plan` 节点、`trading_strategist.yaml` 配置；更新 LangGraph 流程为 verdict→risk_check→report→signal_output→END；同步更新 `execution_modes_flowchart.md` v4.6、`agent-protocol.md` v4.1、Harness 文档；版本号 bump 8.6.0→8.7.0 |
| v8.6.0 | 2026-07-17 | **架构精简 v1**：明鉴秋职责聚焦流程调度（P1-P5 阶段、自进化、记忆归档），删除 L1-L4 评分模块；新增 `node_report`（报告生成）和 `node_signal_output`（CTP 信号输出）；修复探源 Agent（产出 FundamentalStateVector）和观澜 Agent（产出 TechnicalOutput）的 LLM 推理生成逻辑；更新 LangGraph 架构为 risk_check→report→signal_output→END；同步更新 Harness 文档；版本号 bump 8.5.4→8.6.0 |
| v8.5.4 | 2026-07-17 | **cov-3 候选模块覆盖**：新增 4 个测试文件（test_unified_logger.py/test_fdt_version.py/test_config_manager.py/test_fdt_llm.py）共 144 个用例，覆盖率 91%/100%/92%/71%；解决 `tests/conftest.py` sys.path 遮蔽问题；累计 scripts 测试 7 文件/322 用例全绿；同步更新 pyproject.toml、07-operations.md、06-testing.md、08-gap-analysis.md；G65 Phase B 关闭 |
| v8.5.3 | 2026-07-17 | **cov-2 候选模块覆盖**：新增 178 个测试用例，覆盖 test_fdt_paths.py（84%）/test_trace_id.py（94%）/test_confidence_utils.py（87%）；累计 13 文件/339 用例（161 langgraph + 178 scripts）；同步更新版本号和文档；G65 Phase A 关闭 |
| v8.5.0 | 2026-07-17 | **G65 测试覆盖扩展**：启动 scripts/ 模块测试覆盖率提升专项，目标消除 0% 覆盖率模块；cov-1/2/3 阶段规划 |
| v8.4.0 | 2026-07-16 | **G52-G55 生产集成完成**：① G52 `pipeline/runner.py` 集成 LangGraph A/B 切换（`run_langgraph_pipeline()` + `FDT_USE_LANGGRAPH` 环境变量）；② G53 `scripts/run_debate.py` 添加 `langgraph` 子命令（支持 `--mode`/`--symbols`/`--trace-id`）；③ G54 `fdt_langgraph/graph.py` Checkpointer 支持 PG + SQLite 降级（`_get_checkpointer()` + `FDT_CHECKPOINTER=pg` 切换）；④ G55 新增 `tests/fdt_langgraph/test_integration_ab.py` 18 个集成测试验证 A/B 切换机制等价性；**总测试数：99 passed, 1 warning in 5.08s**（8 文件 / 99 用例）；新增 3 个环境变量 `FDT_USE_LANGGRAPH`/`FDT_LANGGRAPH_MODE`/`FDT_CHECKPOINTER`；三级降级路径（LangGraph import 失败→subprocess / PG Checkpointer 失败→SQLite / A/B 默认 false 零风险） |
| v8.3.0 | 2026-07-16 | **LangGraph 迁移完成**：DebateState TypedDict(19字段+create_initial_state工厂)、10个异步节点函数、按需并行拓扑图(闫判官→链证源/观澜/探源并行→merge_research)、PostgreSQL OLTP+OLAP 混合架构(14表+3视图)、独立 CLI/FastAPI 双入口；更新9篇Harness文档；**21个pytest测试用例全部通过**(节点96%/State 100%/Graph 77%/Agents 65%)；移除 WorkBuddy 依赖；P1 可插拔多策略扫描、P3 三源平行关系无先后次序 |
| v8.2.0 | 2026-07-16 | Harness 工程规范全面固化：用户规则 + 项目记忆 + harness-checker 技能 + commit前12项检查清单 + Git Hook 强制检查 |
| v6.3.2 | 2026-07-14 | P0-4 多因子增强：select_triggers disable_filter 读 _raw_total；V1 OI/基差覆写；V2 OI+量比联合；V3 基差+低波联合；numpy 60s 品种级超时；finalize-only glob mtime 排序；G19 新登记(9 测试全绿)；阈值常量 G20/100ppi 降级 G21 待后续 |
| v6.3.1 | 2026-07-14 | 技术债 §2/§3 迁移收尾：修复链分析 build_symbol_map 数技源+观澜+探源合并 KeyError + factor_timing NaN 防护 |
| v6.3.0 | 2026-07-14 | 数技源信号+分析师能力架构落地：scan_all 仅留 channel_breakout；technical-analysis 和 fundamental-data-collector 独立运行 |
| v6.2.0 | — | A2A Agent-to-Agent 协议文件桥（agent-card.json + a2a_results.json）+ validate_final_signals 置信度归一 |
| v6.1.0 | — | 信号验证门（validate_final_signals.py）+ 行动对账（execute/hold/wait）+ 方向-价格一致性检查 |
| v6.0.0 | — | FDC 数据引擎合并：QMT(0) 主源，TDX/TqSDK 降级，移除 AKShare/EastMoney 直连 |
| v5.7.0 | 2026-07-10 | 驾驭工程（Harness Engineering）落地：**经 07-14 复核 G14 实际未落地、G16 重构后失效，原「4.7/5.0 全部完成」声明需修正** |
| v5.6.0 | 2026-07-09 | 5层鲁棒性架构 (L1-L5) |
| v5.5.0 | 2026-07-09 | OmniOpt 分类法集成 (F1-F5) |
| v5.4.0 | 2026-07-07 | 可观测性与自改进里程碑 |
| v5.3.0 | 2026-07-07 | 通道突破策略里程碑 |
| v5.2.0 | 2026-07-06 | 架构重构 (通道突破主信号源) |
| v5.1 | 2026-07-06 | Phase 1 独立化 (scheduler/bootstrap) |
| v5.0 | 2026-07-06 | 自进化闭环里程碑 |
| v4.5 | 2026-07-06 | Bridgewater 方法论落地 |
| v4.4 | 2026-07-05 | P0+P1 全面实施 |
| v4.2 | 2026-07-05 | P3 全量实现 |

### 5.3 自动发布

```bash
# 手动触发
python scripts/auto_publish.py

# 自动触发 (每日 23:05)
# scheduler/triggers.py → TimeTrigger("23:05", ["Mon","Tue",...,"Fri"])
```

发布流程:
1. 版本号自增 (patch/minor/major)
2. 更新 `.version_history.json`
3. Git commit + push
4. 通知 (webhook)

## 6. 同步与备份

### 6.1 GitHub 同步

| 项 | 内容 |
|:---|:-----|
| 脚本 | `C:\Users\yangd\quant-bare\sync_experts_to_github.py` |
| 自动化 | 每日 10:00 自动检测变更并推送 |
| 范围 | 仅 `futures-debate-team/` 目录 |
| 手动 | `python "C:\Users\yangd\quant-bare\sync_experts_to_github.py"` |

### 6.2 Agent 备份

| 项 | 内容 |
|:---|:-----|
| 备份目录 | `agents/backups/` |
| 备份时机 | 修改 Agent .md 文件前 |
| 备份方式 | `cp -r agents/ agents/backups/{date}/` |
| 恢复方式 | 从备份目录复制回 `agents/` |

### 6.3 记忆备份

| 项 | 内容 |
|:---|:-----|
| 关键文件 | `memory/debate_journal.json`, `memory/execution_followup.json`, `memory/agent_profiles.json`, `memory/calibration.json` |
| 备份方式 | Git 版本控制 (sync_experts_to_github.py) |
| 恢复方式 | `git checkout {commit} -- memory/` |


---

## 上线四步评估流程

所有新循环或循环重大变更上线前，必须通过四步评估：

### 1. 影子模式 (Shadow)
- 循环只读运行，连续 N 轮（建议 ≥5）人工抽查
- 评估分诊准确率、漏放率、误杀率
- 产出：Shadow 模式评估报告

### 2. 金标准任务集 (Golden Tasks)
- 5-20 个已知答案的任务（含正例与陷阱负例）
- 所有任务必须通过才能进入下一步
- 金标准任务集本身也是回归测试用例

### 3. 验证器质量度量
- 漏放率（false pass）为硬指标，必须 ≈ 0
- 误杀率（false block）为效率指标，目标 < 20%
- 不达标则必须升级验证档位

### 4. 金丝雀 (Canary)
- 真实环境小范围放量（例如单品种、单时间段）
- 观察 24-48 小时，确认无异常后全量上线

---
## 版本历史（Harness 文档）

| 版本 | 日期 | 变更 |
|:-----|:-----|:-----|

| **v9.6.5 → v9.6.6** | 2026-07-20 | **G? 合约映射动态化修复 — 替换硬编码 2509 为主力合约动态解析**：① `phase3_generate_report.py` 删除硬编码 `DOMINANT_MONTH_MAP`（所有品种写死为 2509/2510/2512），替换为 `_resolve_dominant_months()` 函数—管道运行时优先通过 TQ-Local `get_stock_list` 查询活跃合约列表动态解析当前主力合约月份；TQ-Local 不可用时通过 `datetime.now().year % 100` + 品种典型月份模板自动推算（如 2609/2610/2612）；② fallback 默认值从 `"2509"` 改为 `f"{year}09"` 动态年份；③ 修复后报告中的合约代码从 `I2509.DCE` 变为 `I2609.DCE` 等正确主力合约。| **v9.6.4 → v9.6.5** | 2026-07-20 | **G93-G96 LangGraph 迁移全部完成 + config schema 扩展** — G93: coordinator.py→graph.py Profile切换；G94: debate_protocol_v2.py→nodes.py 常量内联；G95: agent_runner.py→agents.py run_single()；G96: deploy.py INSERT 写入逻辑。3 旧文件删除，16 迁移测试通过，D2/D3/D5/D6 四维升至 ★★★★★。新增 `DataSourcesConfig` + `AgentProfilesData` Pydantic 校验，覆盖全部 4 个配置文件。
| **v9.6.3 → v9.6.4** | 2026-07-20 | **Harness 工程升级计划完成** — Phase D 全部完成：① `harness-rules.yaml` 添加 10 条反模式检测规则（AP01-AP10）；② `01-architecture.md` 添加 Hook 链架构规范（pre_hook/post_hook/safety_hook 三层扩展）；③ `06-testing.md` 添加验证器质量度量（漏放率/误杀率硬指标 + 质量等级 + 告警规则）；④ `03-configuration.md` 添加成本工程规范（Token 估算公式 + 缓存 TTL 耦合策略 + 降本手段排序 + 成本监控指标）；⑤ `07-operations.md` 添加上线四步评估流程（影子模式→金标准比对→验证器验收→金丝雀发布）；G21/G22 设计文档已存在（`docs/designs/g21-harness-adaptive-optimization.md` / `docs/designs/g22-multi-loop-collaboration.md`） |
| **v9.6.2 → v9.6.3** | 2026-07-20 | **G92 Phase B/C 完成 — LLM 幻觉校准与进化闭环** — Phase B：`calibrate_weights.py` 扩展 `--hallucination-stats` 参数，新增 `hallucination_adjustment` 全局修正项（幻觉率>10%→-3分，>5%→-1分，<2%→+1分）；Phase C：`evolve_agents.py` 新增 `evolve_llm_hallucination()` 函数，接收 `--hallucination-patterns` 参数，调整价格引用策略（strict_scan/scan_first/hybrid）、置信度缩放因子、偏差阈值；新增 `LLM幻觉进化器` Agent 配置；更新 `08-gap-analysis.md` G92 Phase B/C 状态标记为已完成 |
| **v9.6.1 → v9.6.2** | 2026-07-20 | **G92 Phase A 完成 — LLM 幻觉检测层落地** — 新增 `scripts/validate_llm_output.py`（价格偏差/置信度/评分三维校验）；新增 `tests/scripts/test_validate_llm_output.py`（18 测试用例全绿）；更新 `05-observability.md` 新增 §8.6 LLM 幻觉率指标表；更新 `08-gap-analysis.md` G92 Phase A 状态标记为已完成 |
| **v9.6.0 → v9.6.1** | 2026-07-20 | **G71 完全关闭 + 循环契约补全** — 8 文件手工注解补全 + ml-training/health-check 两份 Loop Contract |
| **v9.5.0 → v9.6.0** | 2026-07-20 | **Harness 工程全面升级** — 规范引擎化（harness-rules.yaml + pre-commit v2）、类型注解全量补充（580 函数）、5 个缺失规范维度补充、10 条反模式检测规则、G21/G22 设计文档 |
| **v9.4.2 → v9.5.0** | 2026-07-20 | **Loop Engineering 体系化** — 新增 Loop Contract 规范与 daily-debate 首份契约；架构文档添加 Loop Engineering 视角；README 增加 Harness & Loop Engineering 专章；差距分析登记 G20/G21/G22 |
