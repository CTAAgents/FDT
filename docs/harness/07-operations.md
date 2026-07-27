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
- 独立运行，不依赖第三方平台
- CLI (`fdt_cli.py`) + FastAPI (`fdt_api.py`) 双入口
- PostgreSQL OLTP+OLAP 混合存储（替代 DuckDB）
- 依赖本地数据源 (TDX/TqSDK)

### 1.2 分布式模式 (可选)

通过 LangGraph 的 Checkpointer + 共享状态后端，Master Graph 可在多节点间分布式运行。

```
                    ┌───────────────────────┐
                    │  Master Graph (主节点)  │
                    │  fdt_langgraph/        │
                    │  master_graph.py       │
                    │  check_time → dispatch │
                    └──────────┬────────────┘
                               │ 触发任务
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │ Debate Node  │    │  Script Node │    │  Train Node  │
   │              │    │              │    │              │
   │ graph.py     │    │ subprocess   │    │ ml/trainer   │
   │ P0-P6 辩论   │    │ 外部脚本执行  │    │ 模型训练     │
   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                     ┌────────▼────────┐
                     │  Checkpointer   │
                     │  (共享状态)      │
                     │                 │
                     │  PostgreSQL /   │
                     │  SQLite         │
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │  多个 Master     │
                     │  Graph 实例      │
                     │  (worker 节点)   │
                     └─────────────────┘
```

**后端**:
- Checkpointer 支持 PostgreSQL 或 SQLite（通过 `FDT_CHECKPOINTER` 环境变量切换）
- 多实例通过共享 database 协调状态

**适用场景**:
- 需要独立扩展扫描/辩论/训练吞吐量时，在不同节点运行不同 Master Graph 实例
- 高频品种走高频 Master Graph，低频品种走低频 Master Graph
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
| 首选 | 3.13.12 (managed) | `~/.workbuddy/binaries/python/versions/3.13.12/` | 托管管理 |
| 备选 | 3.12.10 (system) | `C:\Program Files\Python312\` | 系统安装 |

> **用户偏好**: 默认使用系统 Python 3.12 (`C:\Program Files\Python312\python.exe`)，包安装走 `--user` 模式。

### 2.3 数据源准备

| 数据源 | 安装/配置 | 优先级 |
|:-------|:----------|:-------|
| 通达信 TDX TQ-Local | 安装通达信客户端 + 开启 TQ-Local HTTP 服务 | 0 (最高) |
| TqSDK | `pip install tqsdk` + 账号配置 | 1 |
| 东方财富 | 无需安装 (HTTP API) | 2 |
| AKShare | `pip install akshare` | 3 (最后降级) |

## 3. Master Graph 运维

### 3.1 启动/停止守护进程

```bash
# 启动守护进程 (LangGraph Master Graph)
python fdt_cli.py daemon

# 单次检查到期任务 (不持续运行)
python fdt_cli.py master

# 一次辩论
python fdt_cli.py run --evolve

# 停止守护进程: Ctrl+C 或 kill -SIGTERM <pid>
```

### 3.2 看门狗配置

| 项 | 配置 | 说明 |
|:---|:-----|:-----|
| 检查频率 | 每 30 分钟 | 定时任务触发 `scripts/daemon_watchdog.py` |
| 心跳阈值 | 3 分钟 | `memory/logs/master_heartbeat.log` 超过 3 分钟判定为挂 |
| PID 文件 | `memory/daemon.pid` | 用于进程存活检查 |
| 自动恢复 | 是 | 挂了自动 `fdt_cli.py daemon` 重启 |

### 3.3 触发状态文件

```json
// memory/schedule_state.json (Master Graph 持久化触发状态)
{
  "last_heartbeat": "2026-07-23 14:30:15",
  "last_triggered": {
    "daily_debate": "2026-07-23 14:15:00",
    "auto_publish": "2026-07-23 23:05:00",
    "validate_and_evolve": "2026-07-23 14:20:00"
  }
}
```

### 3.4 调度注册表

所有自动化任务的触发规则定义在 `fdt_langgraph/master_state.py::_get_default_schedules()`。

| 任务 | 触发类型 | 时间/条件 |
|:-----|:---------|:----------|
| daily_debate | time | 工作日 19:15 |
| update_dominant_mapping | time | 工作日 15:30 |
| auto_publish | time | 每日 23:05 |
| apm_scorecard | time | 周一 08:30 |
| cluster_failures | time | 周一 08:00 |
| discipline_enforce | time | 周一 08:45 |
| self_optimize_evolve | time | 工作日 15:35 |
| self_optimize_verify | time | 周一 08:50 |
| validate_and_evolve | data | 有未验证记录 |
| ml_training_check | data | journal entries ≥ 50 |
| self_optimize_analysis | data | journal entries ≥ 1 |
| vibench_baseline | data | test cases ≥ 30 |
| d3_auto_light | debate_record | 辩论轮次 ≥ 5 |

## 4. 运维 Runbook

### 4.1 常见故障处理

#### 故障 1: 守护进程挂了

```
现象: memory/logs/master_heartbeat.log >3分钟未更新
诊断:
  1. cat memory/daemon.pid → 获取 PID
  2. tasklist /FI "PID eq {pid}" → 检查进程是否存在
  3. 查看 memory/logs/daemon.log → 最后输出

处理:
  - 进程不存在 → `python fdt_cli.py daemon` (重启)
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
| 日志无异常 | 每日 | `tail logs/fdb_{date}.log` |
| 辩论归档完整 | 每周 | `cat memory/debates/INDEX.md` |
| APM 评分 | 每周 | `cat memory/apm_scorecard.json` |
| 心跳正常 | 每日 | `cat memory/schedule_state.json` |
| 测试通过 | 每周 | `python -m pytest tests/ --ignore=tests/commodity-chain --no-cov` |
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
| **输出** | 两份独立的辩论结果（影子 vs 生产） |
| **持续时间** | 至少 3 个交易日 |
| **验收条件** | 影子模式无崩溃，输出格式与生产一致 |

### 5.3 Step 2: 金标准比对

| 项目 | 说明 |
|:-----|:-----|
| **目标** | 对比影子模式与生产模式的结果差异 |
| **比对维度** | 品种选择、方向判定、交易参数、置信度 |
| **工具** | `scripts/verification/run_benchmark.py --replay` |
| **验收条件** | 方向一致性 ≥ 95%，价格偏差 ≤ 5% |

### 5.4 Step 3: 验证器验收

| 项目 | 说明 |
|:-----|:-----|
| **目标** | 通过质量门禁验证新代码的正确性 |
| **验证项** | 漏放率 ≤ 1%，误杀率 ≤ 5% |
| **工具** | `scripts/verification/validate_llm_output.py` + 门禁测试 |
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

| 位置 | 说明 |
|:-----|:-----|
| `pyproject.toml` version | **FDT 唯一版本真相源**（硬规定，§6.2 版本历史以此为准） |
| `docs/harness/07-operations.md §6.2` | 版本历史记录，与 pyproject.toml 同步更新 |
| `README.md` 版本历史 | 同步展示，不视为独立版本源 |

### 6.2 版本历史（降序排列，最新在上）

| 版本 | 日期 | 变更 |
|:-----|:-----|:-----|
| **v0.13.0** | 2026-07-26 | **P4 逐品种辩论子图重构 — 主图节点 23→8** — 将 16 个 P4 辩论节点提取为独立 LangGraph 子图 `per_symbol_graph.py`（带 `@lru_cache` 缓存）。新增 `_routing.py` 打破 graph.py ↔ per_symbol_graph.py 循环导入。主图构建函数 `_register_debate_graph()` 和 `_register_direct_debate_graph()` 分别从 ~95 行和 ~75 行精简至 ~35 行和 ~20 行。修复直接辩论模式缺失 `judge_direction` 节点注册的 bug。所有节点函数签名不变，外部调用 `build_debate_graph()` 接口完全向后兼容。版本号 bump 0.12.0→0.13.0 |
| **v0.12.0** | 2026-07-26 | **MASE 自演化框架落地 — 三环架构完整实现** — Phase 1 Self-Refine 快环：所有 Agent 输出后自动执行自我审查+修正（轮数上限1），计数器 `get_self_refine_rate()` 跟踪修正率。Phase 2a 偏差检测：`deviation_detector.py` 裁决方向 vs 实际走势对比，偏差自动创建 EvoMem 补丁。Phase 2b 权重自调整：`weight_adjuster.py` 5个 Agent 权重代码硬约束微调+累计±0.1 自动冻结+精确回滚。Phase 3 拓扑路由：`topology_router.py` 代码规则引擎 `decide_path()`（基于信号一致性/波动率/历史准确率选择 fast_path/standard_path/full_debate）+ A/B 测试追踪器。Self-Refine 在 `FdtAgentExecutor.run()` 中集成（零节点修改）。进化图新增 `node_detect_deviations` 和 `node_adjust_weights` 节点。新增 4 模块：`self_refine.py`(259行)/`deviation_detector.py`(231行)/`weight_adjuster.py`(376行)/`topology_router.py`(287行)。版本号 bump 0.11.1→0.12.0 |
| **v0.11.1** | 2026-07-26 | **Web 数据降级管线上线 — Primary source 不可用时自动保底 + 溯源** — 新增 `data_adapter/sources/web_data_fetcher.py`（7 个函数：fetch_basis/warrant/spread/inventory/money_flow/north_flow/etf_premium_from_web），通过东方财富 HTTP API 对 AKShare 不可用的因子数据自动保底降级。`data_adapter/__init__.py` 各 get_*() 增加 UNAVAILABLE → web 自动降级逻辑。8 个信号函数 + _nodes_prepare.py 7 处采集检查全部支持 PRIMARY/DERIVED 双等级。降级数据返回 source_url 溯源标记。版本号 bump 0.11.0→0.11.1 |
| **v0.11.0** | 2026-07-26 | **EvoMem 补丁记忆范式落地 — 4 个 Phase 全部完成** — ① Phase 1(session_memory 格式升级): `schemas.py` 新增 `PatchEntry`/`PatchCondition`, `patch_store.py` 新增 patches.jsonl 分片存储+域-补丁倒排索引, `manager.py` 新增 `query_patches_by_domain/version/resolve_conflict`, 迁移脚本 `migrate_session_memory_patches.py` ② Phase 2(补丁创建自动化): `patch_creator.py` 封装 3 种触发点(规则变更/知识库变动/裁决偏差) ③ Phase 3(P4 消费端集成): `_nodes_verdict.py` 注入 EvoMem 补丁历史到闫判官 prompt ④ Phase 4(产业链知识版本化): `knowledge_store.py` 新增 `query_with_patch_history()` 版本感知查询。版本号 bump 0.10.9→0.11.0 |
| **v0.10.9** | 2026-07-26 | **GAP-005 JIN10_TOKEN 配置 + GAP-006 多品种辩论 state 隔离修复** — ① GAP-005: 用户已更新 JIN10_MCP_TOKEN 至 `.env`，金十 MCP 新闻源恢复 ② GAP-006: `state.py` 新增 `_debate_args_reducer` 替换 6 个论据字段的 `operator.add`。`operator.add(current, [])` = `current`（累积不清理），新 reducer 检测 `update=[]` 时返回 `[]`（品种切换正确重置）。版本号 bump 0.10.8→0.10.9 |
| **v0.10.8** | 2026-07-26 | **G98 右侧交易校验实现 + G99 知识库产业链重构文档确认关闭** — ① `_nodes_verdict.py` 新增 `node_right_side_check()`：MA5 vs MA20 判定趋势，反趋势时检查 3 根 K 线是否突破 MA20，未破坏则降级为 neutral+INFO ② `nodes.py` + `graph.py` 注册 right_side_check 节点，插入 verdict→risk_check 之间 ③ 关闭 G98/G99。版本号 bump 0.10.7→0.10.8 |
| **v0.10.7** | 2026-07-26 | **G97 连续合约复权价差校准实施** — ① `types.py` 新增 `contract_price_adjustment` 字段 ② `base.py` 新增 `get_price_adjustment()` 抽象方法 ③ `state.py` 新增 `price_adjustments` 字段 ④ `_nodes_verdict.py` 追加价差校准逻辑（LLM 感知价差表 + entry_price 代码调整 + stop_loss/target 使用调整后价格）⑤ `akshare_source.py` 实现 `get_price_adjustment()`（通过 `futures_zh_realtime()` 计算近月合约与连续合约价差）⑥ 关闭 G97。版本号 bump 0.10.6→0.10.7 |
| **v0.10.6** | 2026-07-26 | **品种映射缺失修复 + 图编排稳定性修复批** — 2026-07-26 SH/OP/SM 三品种辩论过程中发现并修复 6 项 P0/P1 缺陷：① `_AK_SPOT_MAP` 添加 SH/SM/SF/OP（基差修复）；② `SYMBOL_TO_KEYWORDS` 添加 SH/OP（金十新闻搜索修复）；③ `_nodes_verdict.py` f-string 花括号双写转义（`{条件A}→{{条件A}}`）；④ `single_symbol_report.py` f-string `\n` 替换为 `.join()\` 拼接（Python 3.12 兼容）；⑤ `graph.py` P3 多条件边冲突改为单路由函数 `_route_p3_nodes()`；⑥ `_nodes_utils.py` 补充 `import tempfile`。新登记 8 项差距（GAP-001~008），其中 5 项已关闭、2 项开放（JIN10_MCP_TOKEN 配置 / 多品种 state 隔离）、1 项监控中（DCE zip 外部故障）。版本号 bump 0.10.5→0.10.6 |
| **v10.5.0** | 2026-07-26 | **Phase A-F 优化方案落地 — 裁决数据库 + 校准 + 委派协议 + T3 验证** — 基于论文《Human-AI Hybrid Finance》优化方案的 Phase A-F 全部实施：① Phase A（裁决数据库）：新增 `VerdictDB`（JSON 存储，按品种/方向/置信度区间查询）+ `calibrate.py`（置信度校准桶 + ECE 误差计算）；② Phase B（最小关键证据集）：闫判官输出 `if_that_reasoning` 推理链 + `key_evidence_points`，观澜输出 `disagreements` 字段，探源输出 `key_turning_points`，`scan_all.py` 注入 `top_n_indicators`，报告新增裁决溯源树；③ Phase C（置信度校准）：`calibrate_confidence()` 集成到报告输出，校准偏差检测触发 `evolution_graph`；④ Phase D（条件委派协议）：`delegation-protocol.md`（R01-R03 三条规则）+ LangGraph 条件边实现 P3 源主动跳过；⑤ Phase E（T3 验证增强）：`BiasTracker` 偏差跟踪 + `harness-rules.yaml` C17 新增；⑥ Phase F（P3 源主动跳过）：已在 Phase D R01 实现。新增 13 个裁决数据库测试全部通过。版本号 bump 10.4.2→10.5.0 |
| **v10.4.2** | 2026-07-26 | **scripts/ 目录结构化整理（verification/ + harness/ 子目录）** — P1 级整理：① 创建 `scripts/verification/`（12 个验证脚本：validate_*×6 + verify_*×4 + test_scripts + advancement_check + pre_commit_harness_check + self_check + run_benchmark）；② 创建 `scripts/harness/`（10 个 Harness/RHI 脚本：rhi_global_*×3 + rhi_harness_optimizer + rhi_pairwise_eval + harness_adapter + replay_harness + self_improve + skillevolver_evolution + embodiskill_reflect）；③ 更新全部 16 篇 docs/harness 文档路径引用 + 2 个 YAML 契约（harness-rules.yaml + self-evolve.contract.yaml）+ 8 个生产/测试文件的 import 路径；④ 删除 3 个空壳子目录（analysis/ops/reporting）；⑤ §8 同步与备份更新为当前 Git 工作流。版本号 bump 10.4.1→10.4.2 |
| **v10.4.1** | 2026-07-26 | **执行稳定性修复批（3个_SKILLS_DIR + re import + GFEX dict + TECH regex回退）** — ① 修复 `_nodes_prepare.py` 缺少 `_SKILLS_DIR` 定义导致 P1 阶段崩溃；② 修复 `_nodes_debate.py` 缺少 `from _nodes_prepare import node_prepare_data` 导致 P2 逐品种数据准备崩溃；③ 修复 `_nodes_research.py` 缺少 `import re` 导致 P3 探源基本面分析崩溃；④ 修复 `_nodes_output.py` 缺少 `_SKILLS_DIR` 定义导致 P6 报告生成崩溃；⑤ 修复 `judge_direction` user prompt 未包含 `symbols` 字段导致 `enforce_structured_output` 校验失败（prompt 模板注入 `selected_symbols`）；⑥ 修复 `technical_researcher` 缺少正则提取回退链，追加与 fundamental_researcher 同级的 regex per_symbol 提取 + 评分钳制；⑦ 修复 `holding_sentiment.py` 中 `_collect_gfex_rankings` 未兼容 `ak.futures_gfex_position_rank()` dict 返回类型导致的 `'dict' object has no attribute 'columns'` 错误。版本号 bump 10.4.0→10.4.1 |
| **v10.4.0** | 2026-07-25 | **代码-推理边界硬切割（Phase 1~4 全部实施）** — ① Phase 1(entry_price P0): 已在 v10.3.0 中实现 LLM 输出后强制覆写；② Phase 2(stop_loss/target P1): 新增 `_compute_stop_target()` 函数，LLM prompt 移除 stop_loss/target 计算要求，改为代码从 ATR 精确计算（L0 硬约束）；③ Phase 3(仓位 P1): 新增 `_clamp_position()` 函数，LLM 输出后钳制仓位至上限(20%)；④ Phase 4(技术评分 P2): 新增 `data_adapter/factors/technical_score.py`（4 维度加权评分：趋势 40%/动量 30%/量价 20%/波动率 10%），`node_technical` prompt 注入代码计算的基准评分，LLM 在 ±10 范围内调整；⑤ 测试 36 个全部通过（`test_code_reasoning_boundary.py` 22 个 + `test_technical_score.py` 14 个）。版本号 bump 10.3.0→10.4.0 |
| **v10.3.0** | 2026-07-25 | **P2.5 多因子注入 — 零新增 Agent，把 FDT 第二层升级为多因子整合器** — ① 新增 `data_adapter/factors/` 数据适配层（7 文件）：`types.py`（5 种因子数据类型）、`volatility.py`（波动率/HV/偏度/ATR，纯计算）、`cross_spread.py`（跨品种价差/Z-Score，纯计算）、`term_structure.py`（期限结构，AKShare）、`holding_sentiment.py`（多空持仓/前20排名，AKShare）、`dashboard.py`（因子一致性看板 + 分歧度指标）；② `nodes.py` 4 处注入：`node_prepare_data()` 新增 FactorCollector 采集 → state 注入、`node_technical` prompt 追加波动率因子区块、`node_fundamental` prompt 追加多空持仓因子区块、`node_verdict` prompt 追加多因子信号一致性看板；③ 18 个单元测试全部通过（覆盖波动率/跨品种价差/因子看板）；④ 设计文档 `docs/designs/p25-multifactor-injection.md` 含可行性评估（排除社区情绪，资金流更名为多空持仓）。版本号 bump 10.2.1→10.3.0 |
| **v10.2.1** | 2026-07-25 | **新闻数据层清理 + _build_jin10_context 全面替换为 NewsRouter** — ① 删除 `nodes.py` 中 `_SYMBOL_TO_KEYWORDS`/`_SYMBOL_DEFAULT_KEYWORDS`/`_build_jin10_context` 旧代码（~120行）；② `node_fundamental`/`node_sentiment` 均通过 `NewsRouter`（`data_adapter/news`）获取多源聚合新闻数据，关键字映射迁移至 `data_adapter/news/sources/jin10_source.py`；③ 测试文件 `test_jin10_mcp.py` 中 `TestBuildJin10Context` → `TestNewsRouter`（4 个测试，覆盖 prompt_context / quality_report / keyword_mapping）；④ 文档同步：`01-architecture.md` 2处、`CODE_WIKI.md` 1处；⑤ 4 个新测试全部通过，7 个旧测试因 `futures_data_core` 模块缺失为已知失败。版本号 bump 10.2.0→10.2.1 |
| **v10.1.5** | 2026-07-25 | **链证源模块路径修复 + 导航栏过滤 + 量价持仓 K线 fallback + footer 对齐** — ① 修复 `_import_skill_module`/`_import_from_skill` 中模块路径 `.` 未转为 `\\` 导致 `scripts.chains.py` 找不到的问题；② 导航栏 `_render_html()` 过滤只保留 `sym-*` 和 `signal-summary` 两类锚点；③ 量价持仓数据当 scan stats 不足时从 K 线 `open_interest` 字段推导 fallback；④ `report_skeleton.html` footer 添加 `.container` 包裹与头部对齐。 |
| **v10.1.4** | 2026-07-25 | **FDT 自动辩论引擎稳定性修复 × 5** — ① single_symbol_report.py f-string 反斜杠修复(Python 3.12兼容)；② enforce_structured_output 校验降级（core_fields通过时required缺失降级为warning）；③ llm_provider.py JSON mode API支持(response_format参数)+ decode_config.yaml 12 Agent core_fields配置；④ nodes.py 辩论论据逐品种隔离（fix_4: prepare_one_symbol清空上一品种6种论据）+ 单品种内 _trim_arguments 120K字符裁剪(方案1)；⑤ run_debate.py op→造纸产业链映射 + resource_watchdog --quick 模式。 |
| **v10.1.3** | 2026-07-25 | **导航栏简化** — 报告头部导航栏只保留品种链接(sym-*)和汇总链接(signal-summary)，隐藏 P1~P5 详细阶段菜单项。 |
| **v10.1.2** | 2026-07-25 | **FDT_BYPASS_FRESHNESS_GATE 绕过开关** — P0b 新鲜度闸门新增 `FDT_BYPASS_FRESHNESS_GATE=true` 环境变量，非交易时段可强制绕过新鲜度检查直接进入辩论链。docs/harness/03-configuration.md 同步更新。 |
| **v10.1.1** | 2026-07-25 | **链证源导入修复 + 新闻情绪解析 + 报告模板对齐** — ① 修复 commodity-chain-analysis 目录名含连字符导致的 ModuleNotFoundError（`_import_skill_module` importlib 按文件路径加载；修正从 analyze_chain.py 而非 chains.py 导入 `lookup_symbol_names`/`build_symbols_data`）；② 修复新闻情绪模块空数据（`node_sentiment()` 新增 `parse_llm_output` 调用；`decode_config.yaml` 补充 `news_sentiment_analyst` 条目）；③ 新增交易信号汇总章节（`_build_signal_summary_html` 渲染品种/方向/置信度/入出场价/仓位/盈亏比表格）；④ 报告模板对齐（`debate-round` 外层添加 `debate-box.bull`/`.bear` 容器，红蓝左边框区分多空）。 |
| **v10.1.0** | 2026-07-24 | **Phase 3 — 基本面清洗** — 新增 `data_adapter/cleaning/fundamental.py`（5 道清洗：缺失字段检查/值有效性校验/新鲜度评分/口径变更检测/修订版追踪），`clean_fundamental()` / `clean_fundamental_data()` 管线集成。期货专项清洗交割月正则修复（RB2610 误判为主力连续）。20 个 Phase 3 测试，全量 66 清洗测试全部通过。文档同步：01-architecture / 03-configuration / 06-testing。版本号 bump 10.0.1→10.1.0 |
| **v10.0.1** | 2026-07-24 | **K线数据源新浪优先 + FDC CancelledError 修复** — ① `akshare_provider.py` K线数据源顺序从东方财富优先翻转为新浪财经优先（新浪 ~1s vs 东方财富 ~37s 失败），大幅降低 FDC 数据注入超时概率；② `nodes.py` 捕获 `asyncio.CancelledError` 防止 F10 采集超时引发整节点崩溃；③ AKShare 版本兼容修复：`futures_hist_em()` 移除 `adjust=""` 参数（AKShare 1.18.64 不支持）。版本号 bump 10.0.0→10.0.1 |
| **v10.0.0** | 2026-07-24 | **FDC→AKShare 全面迁移 + 全量数据集成** — 废除TqSDK/TDX/QMT/DataCore/WebFallback多源降级链，删除17个文件(~3500行)。AKShare为唯一K线数据源。新增4个F10模块(inventory/fund_flow/foreign/contract_info)，覆盖20+AKShare期货函数。版本号bump 9.26.0→10.0.0 |
| **v9.26.0** | 2026-07-24 | **AKShare 升至第一K线数据源 + 数据源优先级重排** — 新增 `collectors/akshare.py`（AKShareCollector），通过 `akshare.futures_hist_em()` 获取东方财富期货K线，设为第一数据源（priority=0）。数据源链调整为：AKShare（第一）→ TDX TQ-Local（第二）→ TqSDK（第三）→ DataCore → WebFallback → QMT。`data_sources.yaml` 同步更新。 |
| **v9.24.2** | 2026-07-24 | **TqSDK 数据采集修复 + 辩论图降级路径 None 安全加固** — ① 修复 `tqsdk.py::_pump()` 中 `wait_update` 参数名 `timeout→deadline`（TqSDK 3.10.1 API 签名），TqSDK 数据采集从"始终为空"恢复为正常（G26 P0 关闭）；② 修复 `node_signal_output()` P0b 阻断后 `signal_output=None` 崩溃（G27 P0 关闭）；③ 修复 `_resolve_report_dir()` 跨日子目录生成（G28 P1 关闭）；④ 修复 `scan_all.py` summary 未初始化 NameError 隐患（G29 P1 关闭）。文档同步：08-gap-analysis.md 新增 G26-G29 登记。版本号 bump 9.24.1→9.24.2 |
| **v9.24.1** | 2026-07-23 | **P0b 数据新鲜度闸门落地 + D05 Spawn铁律移除** — ① 修复 scan_all.py `_fdc_get_kline_sync` data_grade_label 整数 vs 字符串比较 bug（`grade >= 4` 正确检测 UNAVAILABLE/STALE）；② scan_all.py R24 全局闸门输出嵌入结构化 `freshness_report`（status/valid_symbols/fail_reasons）；③ 新增 `node_freshness_gate()` P0b 节点，在 scan→judge_direction 之间实施新鲜度检查；④ graph.py 新增 `_route_after_freshness()` 条件路由：ALL_STALE/NO_VALID_SYMBOLS → D06 aggregate_results（跳过 P2-P5 辩论链）；⑤ `fdt_cli.py _print_phase_reports()` 输出新鲜度状态；⑥ `resilience.md` 新增 D06 降级规则；⑦ `state.py` 新增 `freshness_report` 字段。⑧ **D05 Spawn铁律移除**：当前系统所有 Agent 通过 FdtAgentExecutor 直调 LLM API，不再使用 TAE SDK spawn。清理 12+ 文件的 spawn_mode/spawn_note/D05 引用。 |
| **v9.24.0** | 2026-07-23 | **数据源体系重构 — TqSDK 第一 + 统一标准化层 + 新鲜度自动降级**：① **TqSDK 升至第一数据源** — `tqsdk.priority` 从 98 改为 -1，`_default_collectors` 重排为 TqSDK→DataCore→TDX→WebFallback→QMT；② **统一 K 线标准化层** — `_wrap_kline` 接入 `normalize_kline_row`，所有采集器数据统一日期格式/字段名；③ **新鲜度自动降级** — 末根 K 线 > 7 天视为过期，自动继续下一源，防止过期货数据阻断；④ **数据质量日期解析修复** — `_calc_freshness_days` 支持 `%Y%m%d` 和 `%Y-%m-%d` 两种格式；⑤ **伪突破过滤配置化** — `ENABLE_PSEUDO_BREAKOUT_FILTER = False` 配置开关；⑥ **P2 闫判官结构化输出修正** — 新增 `judge_direction` decode 配置，required_fields 匹配 P2 产出格式。版本号 bump 9.23.0→9.24.0 |
| **v9.23.0** | 2026-07-23 | **六维高 ROI 提升批**：① **G02 Schema 硬件约束** — `agents.py` 将 `response_format` 从 YAML 注入 httpx payload，LLM API 级 JSON 约束；② **G01 模型差异化路由** — YAML `model` 字段生效，裁决组(4 Agent)用 `deepseek-v4-flash`，研究组(5 Agent)用 `deepseek-chat`；③ **C01 Token 预算控制** — `_build_debate_context()` 出口集成 TokenBudget，`FDT_CONTEXT_MAX_TOKENS` 环境变量控制上限；④ **C03 扫描信号表去重** — 提取 `_build_scan_signal_table()` 共享函数，消除 2 处 20 行重复代码。版本号 bump 9.22.6→9.23.0 |
| **v9.22.6** | 2026-07-23 | **OutputMetrics 硬约束 (G8)**：`validate_verdict()` 接入 `OutputMetrics.score_output()`，评分 < 60 追加 FAIL issue，< 40 强制阻断（error 级）。版本号 bump 9.22.5→9.22.6 |
| **v9.22.5** | 2026-07-23 | (预留 G7 — ToolMetrics 反哺调度，因架构不匹配暂缓) |
| **v9.22.4** | 2026-07-23 | **Vector Memory 接入探源上下文 (G6)**：`_build_fdc_fundamental_context()` 追加 `【品种历史模式】` 区块，通过 `VectorMemory.query()` 查询最多 3 个品种的历史记忆注入基本面分析师上下文。版本号 bump 9.22.3→9.22.4 |
| **v9.22.3** | 2026-07-23 | **Context 按品种过滤 (G5)**：`_build_debate_context()` 新增 `current_symbol` 参数，辩论上下文仅包含当前品种数据，消除全品种注入的 prompt 膨胀；4 处辩论节点调用处传入当前品种。版本号 bump 9.22.2→9.22.3 |
| **v9.22.2** | 2026-07-23 | **LLM 输出解析统一封装 (G4)**：`llm_provider.py` 新增 `parse_llm_output()` 函数，统一封装 5 处 LLM 输出解析调用（node_judge_direction / node_technical / node_fundamental / node_verdict / node_risk_check），消除 nodes.py 中所有手动 `json.loads` 和 inline `enforce_structured_output` 调用；新增 6 个单元测试全部通过。版本号 bump 9.22.1→9.22.2 |
| **v9.22.1** | 2026-07-23 | **D3 Generation 全量接入 enforce_structured_output**：`node_risk_check` LLM 输出解析从手动 `json.loads` 替换为 `enforce_structured_output(agent_name="risk_manager")`，覆盖 5 处 LLM 解析节点全量接入。版本号 bump 9.22.0→9.22.1 |
| **v9.22.0** | 2026-07-23 | **RHI 完整落地 — evolution_graph 集成 + 全局 CLI（G114 完成）**：① **RHI 接入自进化闭环** — `evolution_nodes.py` 新增 `node_rhi` 节点，decide_actions 新增 `need_rhi` 决策，evolution_graph 路由优先级 improve→calibrate→evolve→rhi→ml→complete，`FDT_RHI=true` 环境变量开关；② **全局 Harness CLI** — `scripts/harness/rhi_global_cli.py` 独立 CLI 工具，任何项目可 `rhi-global init/status/step/history/install`，自动创建 CLAUDE.md 最小模板 + 四维评分 + 改进率收敛；③ 22 个 RHI 测试用例全部通过。版本号 bump 9.21.0→9.22.0 |
| **v9.21.0** | 2026-07-23 | **MemoHarness+RHI 整合 — 自适应 Harness 优化框架（G114-G115）**：① **G21 设计文档升级** — 更新为 MemoHarness(六维控制空间+双层经验库) 和 RHI(轨迹局部 pairwise 比较) 的统一方案；② **HarnessSpec 契约** (`contracts/rhi_harness_spec.py`) — RHI 三层规范：Agent Candidates/Workflow(Contract+Hop)/Auxiliary Rules + MemoHarness 六维快照；③ **Pairwise Evaluator** (`scripts/harness/rhi_pairwise_eval.py`) — 四维对比评分(质检通过率/风控/信号/报告完整性)，O(1)时间复杂度；④ **Harness Optimizer** (`scripts/harness/rhi_harness_optimizer.py`) — LLM 基于偏好历史更新 Harness，workflow-first；⑤ **RHI LangGraph 子图** (`fdt_langgraph/rhi_graph.py`) — 可与 evolution_graph 集成，停止条件(ε=0.3, max_iter=5)；⑥ **全局 Harness RHI** (`scripts/harness/rhi_global_harness.py`) — CLAUDE.md 自优化；⑦ 22 个测试用例全部通过。版本号 bump 9.20.1→9.21.0 |
| **v9.20.2** | 2026-07-23 | **Harness 文档一致性三层保障体系** — Layer 1: 10 篇文档追加结构化一致性元数据表格；Layer 2: `scripts/verification/verify_doc_consistency.py` 自动校验脚本，解析元数据并执行检验命令；Layer 3: `docs/harness/_data/` YAML 数据文件分离易变配置。C15 规则纳入 pre-commit。51 测试全绿，81 条断言通过。 |
| **v9.20.0** | 2026-07-23 | **v9.19.0 生产运行问题修复批（G109-G111）**：① **Evolution NoneType 修复（G109）** — `master_nodes.py` 中 `ev_state.get()` 增加 None 防护；② **质检缺字段容错（G110）** — `quality_inspector.py` 增加 `symbol`/`stop_loss`/`target1` 等缺失字段的自动填充和更友好的质检反馈；③ **LLM 解析回退增强（G111）** — `nodes.py` 观澜/探源 LLM 输出解析增加 JSON 修复逻辑（截断/单引号/注释清理），提高解析成功率；④ **FDC N/A 指标兜底** — `node_risk_check` 对 N/A 指标增加更清晰的阻断原因说明，帮助快速定位数据源问题；⑤ **报告路径去重** — `_resolve_report_dir()` 检查 workspace 是否已含日期后缀，避免嵌套；⑥ **analyze_trajectory import 修复** — `self_improve.py` 增加项目根目录 sys.path 插入。版本号 bump 9.19.0→9.20.0 |
| **v9.19.0** | 2026-07-23 | **LangGraph 迁移收尾 · G108 关闭**：① `pipeline/runner.py`/`quality_filter.py`/`__init__.py` 退役；② `FDT_USE_LANGGRAPH` A/B 切换机制清理；③ Master Graph `run_master_daemon()` 心跳文件 `_write_heartbeat()` 落地（`memory/logs/master_heartbeat.log`）；④ `daemon_watchdog` 确认使用 `master_heartbeat.log` 检测存活；⑤ `node_run_data_collection` dangling 引用修复（内联 TDX collector + DominantResolver）；⑥ 外部脚本归档（15 个 subprocess 评估为"有意识保留"）；⑦ 17 处 Harness 文档旧引用全量清理（01/02/03/04/05/07 + designs）；⑧ G108 关闭。版本号 bump 9.18.0→9.19.0 |
| **v9.18.0** | 2026-07-23 | **Master Orchestrator Graph — 全量自动化迁移至 LangGraph**：① 新增 `fdt_langgraph/master_state.py/master_nodes.py/master_graph.py` — Master Orchestrator LangGraph，统一编排所有自动化任务（日常辩论/数据采集/APM评分/自动发布），纯 Python datetime 调度判断，零第三方依赖；② `fdt_cli.py` daemon 模式从 APScheduler 替换为 `run_master_daemon()`；③ 新增 `fdt_cli.py master` 子命令单次检查；④ 移除 APScheduler 依赖；⑤ 18 个测试用例全绿。版本号 bump 9.17.0→9.18.0 |
| **v9.17.0** | 2026-07-23 | **自进化闭环 LangGraph Evolution Graph**... |
| **v9.16.0** | 2026-07-23 | **D2/D5/D6 工程成熟度提升**：① D6 Output: `check_report_integrity` 接入 `OutputMetrics.score_output()`、`node_report` 接入 `OutputVersioning.save_output()`、`node_quality_inspect` 接入 `OutputAudit.log_output()`；② D2 Tool: `FdtAgentExecutor.execute()` 接入 `ToolMetrics.record_call()`；③ D5 Memory: `memory_cleaner` 增强（debate_journal 压缩+generation_metrics 清理）；④ `scheduler/tasks.py` 注册 `apm_scorecard` 定时任务。版本号 bump 9.15.0→9.16.0 |
| **v9.15.0** | 2026-07-23 | **Generation Phase 4 — 解码参数反馈闭环（升温重试）**：① `enforce_structured_output.py` 新增 `retry_with_temperature_escalation()`；② 新增 `write_retry_signal()` 信号文件机制；③ `agent_waiter.py` 校验失败时自动写入重试信号文件。版本号 bump 9.14.0→9.15.0 |
| **v9.13.0** | 2026-07-23 | **品藻角色拆分 + Data Governance Phase 3 收尾**：① 质检+报告职责从明鉴秋剥离，成立独立角色**品藻**（`agents/quality-assurance.md`）；② P3.5 质检和 P6 报告汇编由品藻执行，明鉴秋专注调度/编排；③ 更新 `quality_inspector.py`/`nodes.py` 归属标注；④ 新增 `02-lifecycle.md` P3.5 阶段规格行；⑤ 更新 `01-architecture.md` 数据流图全部 [report] 引用为品藻；⑥ 更新 `agents/fdt-team-lead.md` 九大角色表新增品藻（第10个）；⑦ 更新 README 十 Agent 列表。版本号 bump 9.12.0→9.13.0 |
| **v9.12.0** | 2026-07-23 | Data Governance Phase 2 — 数据源溯源穿透修复 + 策略层质量门禁: ① scan_all.py/multi_source_adapter.py per-bar data_source 修复 meta.sources 穿透; ② 新增 data_quality 验证器(D级降级/C级标记/兜底源标记); ③ 注册为 __global__ 列表级闸门, 所有信号统一受检; ④ scan_all.py 执行顺序调整(data_quality 注入提前到 validators 之前); ⑤ 数据源从 kline_data 溯源传播到 all_ranked |
| **v9.11.3** | 2026-07-22 | 修复G107续: 辩论报告探源从fdc_data补充+过滤无意义f10占位数据+修复nodes.py引号混用 |
| **v9.11.2** | 2026-07-22 | 修复G107: 观澜/探源FDC回退模板丰富化，利用已有指标数据替代占位文本 |
| **v9.11.1** | 2026-07-22 | 修复G103: node_verdict FDC指标key映射 (RSI14/ADX/CCI20)；修复G104: scan_all _calc_volume_ma20类型守卫 |
| **v9.9.0** | 2026-07-22 | Phase C: 案例适配层（W(x_j)）上线 — harness_adapter + Shadow 模式 + 安全边界 + G102 关闭 |
| **v9.8.0** | 2026-07-22 | Phase B: 模式蒸馏层（Gt）上线 — pattern_distiller + pattern_reviewer + staging 机制 + G101 关闭 |
| **v9.7.0** | 2026-07-22 | Phase A: 经验记录层（Et）上线 — ExecutionRecord Schema + experience_recorder + C14 正确性优先规则 + G100/G103 关闭 |
| **v9.6.9** | 2026-07-22 | **单品种报告层落地** — 新增 `fdt_langgraph/single_symbol_report.py`（单品种精简报告生成器）；`node_report` 增加单品种分支，自动跳过无效 P1/P2，从辩论论据回退提取 Agent 输出；浮点数截断到合理精度；风控阻断原因明确展示；修复 PS 交易所映射（CZCE→GFEX）；修复 `asyncio.run()` 事件循环冲突；修复 `node_judge_direction` 覆盖用户指定品种问题 |
| **v9.6.8** | 2026-07-21 | P1角色矫正：数技源输出stats纯统计特征，闫判官去锚定，select_triggers改为数据质量闸门 |
| **v9.4.3** | 2026-07-20 | **G91 Phase 4.8 同品种多子信号合并方向覆盖 bug 修复（P0）**：① `pipeline.py` Phase 4.8 引入 `_merge_acc` 累积器，将"逐个两两平均"改为正确的"简单平均"，消除后序信号权重偏高问题；② grade 升级时不再覆盖 `direction`，direction 完全由最终平均 `total` 符号决定；③ 修复 SC 场景方向错误（4 看多 vs 2 看空，原错误输出 bear，修复后正确输出 bull）；④ 新增 `TestSubSignalMerge` 4 用例（SC 场景/全看空/平衡/grade 升级）。版本号 bump 9.4.2→9.4.3 |
| **v9.4.2** | 2026-07-20 | **G89 debate_only 信号多空论据丢失修复 + G90 信号排序改为交易可靠性优先**：① G89 修复 `phase3_generate_report.py` 补充逻辑遗漏 `bull_args`/`bear_args` 字段（`missing_pids` 品种从 `debate_results` 复制论据）；② G89 修复 `fdt_langgraph/nodes.py` `node_report` 中 LLM 辩论遗漏品种论据时，从 judge reasoning 生成 `[裁决摘要]` 最小 fallback；③ G90 将 T1/T2/T3 信号排序从纯置信度改为 `置信度 × 盈亏比`（隐含胜率 × 潜在盈亏比）；④ 辩论详情模块 `SYMBOL_KEYS` 从字母序改为可靠性排序；⑤ 新增 `tests/quant-daily/test_g35_debate_only_args.py` 3 用例全绿；⑥ 同步更新 `06-testing.md` 测试计数 6→9。版本号 bump 9.4.1→9.4.2 |
| **v9.4.1** | 2026-07-20 | **G88 K 线数据链路根因修复（P0）**：① 修复 `MultiSourceAdapter.get_kline()` 入口处的"自动主力解析" bug — 之前 `DominantResolver` 在 `memory/dominant_map.json` 不存在时返回 `f"{variety}00"`（如 `RB00`），这种合约代码在 WebFallback/TqSDK 等所有采集器中均识别失败，导致 K 线返回空、整个数据链路断裂；改由各采集器内部根据自身能力处理 symbol 转换（如 TqSdk 的 `_resolve_continuous` 将 `RB` 转为 `KQ.m@SHFE.rb`），避免平台无关的后备代码污染降级链；② 修复 `tests/dominant-resolver/test_fdc_fallback.py` 的 `_mock_datacore_unavailable` fixture — 改用 `sys.modules["datacore"] = None`（Python 标准约定的"不可导入"信号）替代 `del sys.modules["datacore"]`，避免 `import datacore.fdc_compat` 触发真实包 `__init__.py` 加载导致 Prometheus Counter 重复注册；③ 移除 `multi_source_adapter.py` 中未使用的 `has_month_suffix` 导入。验证：`get_kline("RB")` 恢复返回 30 根 web_fallback K 线；`compute_indicators` 返回 16 个标准指标键名（MA/EMA/RSI/MACD/BOLL 等），类型正确（MA 为 ndarray，BOLL 为 tuple）；F10 子块结构正常（term_structure/spread/basis/warrant/fundamental 均 success=True）。测试 122 passed, 1 skipped。版本号 bump 9.4.0→9.4.1 |
| **v9.4.0** | 2026-07-20 | **G87 Data-Core F10 全面集成**：① 新增 `futures_data_core/core/_datacore_bridge.py` — 集中式 F10 桥接器，封装 `try_datacore_first()` + `_dc_result_to_a2a()` 模板方法；② 改造 6 个 F10 模块（term_structure/spread/basis/warrant/fundamental/position）入口 — 每模块 +3 行 Data-Core 优先检查，自动降级原有实现；③ `compute_indicators` 优先路由 Data-Core 版；④ 新增 2 个测试文件（test_datacore_bridge.py 24 用例 + test_fdc_fallback.py 12 用例）覆盖全部桥接路径和降级兼容性；⑤ 更新 4 篇 Harness 文档（01-architecture / 04-resilience / 06-testing / 07-operations）；版本号 bump 9.3.0→9.4.0 |
| **v9.3.0** | 2026-07-19 | **G86 主力合约统一解析 + DataCore 集成 + 字段标准化**：① 新增 `futures_data_core/core/dominant_resolver.py` — 统一主力合约判定与换月追踪；② 改造 `MultiSourceAdapter.get_kline()` — 无合约后缀时自动解析为实际主力合约代码；③ 新增 `get_contract_kline()` / `get_all_active_contracts()` 入口确保 F10 基差/期限结构不受影响；④ 废弃 `skills/quant-daily/scripts/data/dominant_mapping.py`；⑤ 激活调度器主力映射更新任务；⑥ 新增 `DataCoreCollector` — 封装 `datacore.fdc_compat` 为 FDT BaseCollector，配置为采集器链最高优先级(0)；⑦ 更新 `data_sources.yaml` 降级链为 DataCore→TDX→WebFallback→QMT→TqSDK；⑧ 新增 `futures_data_core/core/field_normalizer.py` — 统一规范 8 类子 Agent 数据栏位（direction/oi/confidence/entry_price/grade 等），覆盖 14 个不一致点；⑨ 在 `nodes.py` 的 4 个关键数据边界（scan/judge/verdict/risk_check）集成标准化层 |
| **v9.2.0** | 2026-07-18 | **Loop Engineering 剥离**... |
| **v9.1.0** | 2026-07-18 | **G85 本地数据增量缓存与指定品种辩论模式**：① 新增 `fdt_cache/` — 本地 SQLite 增量缓存层，按品种+数据类型持久化 K 线/基本面/基差数据，减少重复 I/O 和网络开销；② 新增**指定品种辩论模式** — 当设置 `FDT_DIRECT_DEBATE=true` 和 `FDT_DEBATE_SYMBOLS=SF,SM,SC` 时，跳过 P1 扫描阶段，直接从 `fdt_cache/` 加载缓存数据进入 P2→P3→P4→P5→P6 流程；③ 新增 3 个环境变量 `FDT_DIRECT_DEBATE`/`FDT_DEBATE_SYMBOLS`/`FDT_CACHE_DIR`；④ 更新 5 篇 Harness 文档（01-architecture / 02-lifecycle / 03-configuration / 06-testing / 07-operations）。版本号 bump 9.0.0→9.1.0 |
| **v9.0.0** | 2026-07-18 | **辩论流程重大重构：正反方→多空头模式**：① 辩论模式重构——正反方模式→多空头攻防模式，多头只论证做多，空头只论证做空；② 六阶段辩论——多头立论→空头立论→空头反驳多头→多头反驳空头→空头最终陈述→多头最终陈述→闫判官裁决；③ 分析师中立化——技术面/基本面/产业链分析师客观供弹，辩手只能使用分析师提供的资料；④ 来源可追溯——辩论上下文中每条数据均携带来源标记（`[scan]/[technical:观澜]/[fundamental:探源]/[chain:链证源]`）；⑤ 闫判官独立裁决——明确强调可推翻数技源方向，裁决输出增加 `overturn_scan` 标记。涉及 `fdt_langgraph/state.py`（新增 bearish_rebuttal_arguments 等字段）、`fdt_langgraph/nodes.py`（重写 8 个辩论节点，新增 4 个节点，删除旧 opposition 模式）、`fdt_langgraph/graph.py`（新增 6 节点辩论图，删除旧路由函数）、`config/agents/bullish_analyst.yaml`（消除内部矛盾指令）、`config/agents/bearish_analyst.yaml`（补全缺失内容）、`docs/business_flow.md`（更新多空头六阶段流程描述）。版本号 bump 8.10.0→9.0.0 |
| **v8.9.4** | 2026-07-18 | **数据源配置文档同步（G78）**：修正 `docs/harness/03-configuration.md` 中数据源降级链描述与代码实际不一致的问题——原文档仍写 "TDX→TqSDK→东方财富→AKShare"，代码已演进为 "TDX→WebFallback→QMT→TqSDK"（2026-07-15 调整 Web 前置于 TqSDK 以规避 close 挂死）。① `03-configuration.md §5` 全面重写：降级链图示更新、新增数据源能力矩阵（K线/快照/指标/Tick/F10/超时）、数据源选择逻辑表补齐 QMT/WebFallback/缓存兜底；② `futures_data_core/config/data_sources.yaml` 补充 `web_fallback`（priority=1）和 `qmt_xtquant`（priority=2）配置项，TqSDK priority 从 1 修正为 98（与代码一致），新增超时/置信度等参数；③ 移除所有 AKShare 残留描述（主链中已不存在）；④ 同步更新 `03-configuration.md §1.2` 中 data_sources.yaml 路径（从 skills 目录改为 futures_data_core/config/）及 §2.3 pyproject.toml 示例版本号。版本号 bump 8.9.3→8.9.4 |
| **v8.9.2** | 2026-07-18 | **深度辩论模式 Bug 修复（G77）+ 报告按需生成**：① 修复 `graph.py` `_register_p3_nodes()` `deep_research` 模式 P3 节点全被跳过导致辩论/裁决/报告无法执行的 P0 级 Bug；② `scan_all.py` 和 `nodes.py` 中 P1 扫描/排序报告改为按需生成（`FDT_GENERATE_SCAN_REPORT` 环境变量控制），默认不生成；③ 全量测试通过，辩论报告正常产出至 `D:\\FDTWorkspace\\{date}\\`。版本号 bump 8.9.1→8.9.2 |
| **v8.9.1** | 2026-07-17 | **逐Agent LLM 配置**：每个子 Agent 可独立配置不同的 LLM（API Key / Base URL / Model），通过 `FDT_LLM_<AGENT_NAME>_*` 环境变量覆盖全局默认值；`agents.py` 新增 `_normalize_env_name()` / `_resolve_llm_config()` 方法，动态解析运行时环境变量；新增 16 个测试用例覆盖完整配置链（名称归一化 / 优先级 / 回退链 / 实际调用）；同步更新 `03-configuration.md §3.3`。版本号 bump 8.9.0→8.9.1 |
| **v8.9.0** | 2026-07-17 | **辩论模式重构 + 测试覆盖增强 + 技术选型文档**：① P4 从「证真+慎思并行一次调用」拆分为「串行三步骤交叉质询」——`node_bullish_v1`（多头立论 v1）→ `node_bearish_v1`（空头质疑 opposition v1）→ `node_bullish_rebuttal`（多头反驳 rebuttal v2，max=1）；② `DebateState` 新增 `debate_round` 轮次计数器 + `Annotated[list, operator.add]` reducer 自动追加多轮辩论产物；③ `graph.py` 新增 `route_after_bullish_v1`/`route_after_bearish_v1`/`route_after_rebuttal` 条件边 + `MAX_DEBATE_ROUNDS=2` 常量；④ 新增 `docs/TECH_STACK_DECISIONS.md` 技术选型文档（8项关键技术决策记录）；⑤ **测试覆盖增强**：新增 3 个测试文件（`test_graph.py` 19用例 → graph.py 覆盖率 25%→93%；`test_agents.py` 56用例 → agents.py 71%→97%；`test_health.py` 42用例 → health.py 0%→100%）；⑥ 修复 state.py 初始化 `bullish_arguments={}`→`[]` 及 `node_verdict`/`node_report` reducer 兼容问题；⑦ 修复 G71 类型注解：为 scripts/ 中 12 个关键公共函数补充类型注解；⑧ 同步更新 12 项检查清单、Harness 文档。版本号 bump 8.8.9→8.9.0 |
| **v8.8.9** | 2026-07-17 | **基差数据近月代理降级（G76）**：100ppi.com 启用 HW_CHECK 反爬导致基差数据全面断裂。新增 `_collect_basis_via_nearmonth()` 降级函数，通过 TdxCollector 获取近月合约价格作为现货代理，计算 `basis = near_price - main_contract_price`。方向性信号已恢复，`data_source` 标注 `near_month_proxy`，下游验证器（atr_vol_timing/p0_4_raw_kline）自动兼容。同步更新 `04-resilience.md §8.1`（降级原理与边界）、`08-gap-analysis.md`（G76 登记关闭）。版本号 bump 8.8.8→8.8.9 |
| **v8.8.8** | 2026-07-17 | **cov-5 测试覆盖（P1/P2 模块）+ G71 类型注解收口**：① 新增 61 个测试用例覆盖 compliance_agent (19)/enforce_discipline (14)/evidence_scorer (14)/pre_commit_harness_check (24)/inference_gate (20)—全部通过；② G71 为 evolve_agents(11个)/extract_knowledge(4个)/run_debate(8个) 共 23 个函数补充类型注解；③ G72 导入组织 18 个文件全部闭合。累计 scripts/ 测试 **474 用例**，覆盖 **68 模块**。版本号 bump 8.8.7→8.8.8 |
| **v8.8.5** | 2026-07-17 | **LangGraph 管线 Bug 修复（P0/P1/P2）**：① G70 `node_scan` 修复——改从文件读取扫描结果而非解析 stdout，scan_all 数据正确流入全管线；② G71 `node_report` 修复——逐品种基于扫描数据生成差异化方向/价格/仓位，报告含6个差异化信号（4BUY/2SELL）；③ G72 `node_signal_output` 修复——新增逐品种信号清单（abs>=60），按评分排序输出最强信号；④ 配套修复 `fdt_daily_runner.py` 禁用均值回归（加 `mean_reversion` 到 `DISABLED_STRATEGIES`）、LangGraph 模式启用、工作空间设置；⑤ `runner.py` 全品种传递。同步更新 `08-gap-analysis.md` G70-G72。版本号 bump 8.8.4→8.8.5 |
| **v8.8.4** | 2026-07-17 | **P1/P2 Bug 修复批**：① G67 `compute_indicators()` API 不匹配修复（`node_prepare_data` 传 OHLCV dict 替代四个独立数组）；② G68 裁决/信号报告 None 格式化修复（`or 0` 模式防御 None）；③ G69 subprocess runner `debate_brief.py` 补全 l1l4/factor 两个必需位置参数；④ `fdt_daily_runner.py` 添加 `mean_reversion` 到 `DISABLED_STRATEGIES`，切换 LangGraph 模式，设置 `FDT_DAILY_WORKSPACE`；⑤ `runner.py` 传递全部品种而非限 10 个。同步更新 `08-gap-analysis.md`。版本号 bump 8.8.3→8.8.4 |
| **v8.8.3** | 2026-07-17 | **Keltner 鲁棒参数训练（鲁棒评分加权）**：① 修改 `keltner_wf.py` 评分函数为鲁棒性加权（`0.1×峰值 + 0.9×3×3邻域均值`），优先选择参数平原广阔的组合；② 对63个品种完成全品种训练，`period=40, atr_mult=1.5` 被验证为最鲁棒的全局参数（25/63品种选该组合，信号加权均值 period=37.0, atr_mult=1.62，全局平均训练准确率61%/测试准确率21%）；③ 新增 `keltner_robustness.py` 鲁棒性分析器；④ 固定参数 `(40, 1.5)` 在10个代表性品种上的平均峰值得分51.4与邻域均值51.5几乎一致，验证了参数平原的广阔性（邻域平坦）；版本号 bump 8.8.2→8.8.3 |
| **v8.8.2** | 2026-07-17 | **cov-4 批量测试覆盖（第二阶段·收官）**：扩展 `scripts/verification/test_scripts.py` 新增 44 个测试用例，覆盖 4 个 scripts/ 模块（run_debate/fdt_cli/extract_knowledge/webui），累计 scripts/ 测试 **413 用例**，覆盖 **63 模块**（**412 passed / 1 skipped**）；修复 `extract_knowledge.py` 的 `confidence_utils` 导入 fallback；同步更新 `docs/harness/06-testing.md` / `08-gap-analysis.md`；G65 关闭；版本号 bump 8.8.1→8.8.2 |
| **v8.8.1** | 2026-07-17 | **Keltner 通道参数 Walk-Forward 优化**：① 新增 `keltner_wf.py` 参数训练脚本，对 `period`（10/15/20/25/30/40）和 `atr_mult`（1.5~3.5，步长0.25）共54种组合进行网格搜索；② 对61个品种完成Walk-Forward训练+测试分割（70%训练/30%测试）；③ 众数参数：period=40, atr_mult=1.5；④ 更新 `TREND_G30_CONFIG.keltner`（20→40, 2.25→1.5）和 `legacy_numpy.py` Keltner计算参数；⑤ 新增 `tests/quant-daily/test_keltner_wf.py` 17个单元测试全部通过；版本号 bump 8.8.0→8.8.1 |
| **v8.8.0** | 2026-07-17 | **明鉴秋报告层调度增强**：① `state.py` 新增 4 个阶段报告字段（`scan_report_path` / `research_report_path` / `verdict_report_path` / `signal_report_path`）；② `nodes.py` 新增报告层调度函数（`_resolve_report_dir` / `_render_html` / `_write_*_report`），覆盖 P1/P3/P5/P6/P6a 五个阶段；③ P6 `node_report` 修复 fallback 路径，输出到用户指定工作空间（`FDT_REPORT_WORKSPACE` / `FDT_DAILY_WORKSPACE`）而非 `/tmp`；④ `fdt_cli.py` 新增 `_print_phase_reports()` 统一输出各阶段报告路径；⑤ 新增 `tests/fdt_langgraph/test_reports.py` 12 个测试用例全部通过；⑥ 同步更新 Harness 文档（01-architecture / 02-lifecycle §2.4 / 04-resilience §9.5.1 / 06-testing §2.1）；版本号 bump 8.7.1→8.8.0 |
| **v8.7.1** | 2026-07-17 | **cov-4 批量测试覆盖（第一阶段）**：扩展 `scripts/verification/test_scripts.py` 新增 57 个测试用例，覆盖 16 个 scripts/ 根目录及子目录模块（logutil/fdt_version/health_check/run_reporter/record_verdicts/notifier/llm.cache/llm.token_budget/spawn_resource_check/model_registry/debate_archiver/ops_monitor/auto_publish/auto_train/market_game_agent/marl_trainer），累计 scripts/ 测试 69 用例；**总测试 69 passed**；版本号 bump 8.7.0→8.7.1；同步更新 `docs/harness/06-testing.md` / `07-operations.md` / `08-gap-analysis.md` |
| **v8.7.0** | 2026-07-17 | **架构精简 v2**：删除策略师子 Agent（策执远），将其职责合并到闫判官（直接输出完整交易参数）和风控明（复验止盈止损/盈亏比）；删除 `node_trading_plan` 节点、`trading_strategist.yaml` 配置；更新 LangGraph 流程为 verdict→risk_check→report→signal_output→END；同步更新 `execution_modes_flowchart.md` v4.6、`agent-protocol.md` v4.1、Harness 文档；版本号 bump 8.6.0→8.7.0 |
| **v8.6.0** | 2026-07-17 | **架构精简 v1**：明鉴秋职责聚焦流程调度（P1-P5 阶段、自进化、记忆归档），删除 L1-L4 评分模块；新增 `node_report`（报告生成）和 `node_signal_output`（CTP 信号输出）；修复探源 Agent（产出 FundamentalStateVector）和观澜 Agent（产出 TechnicalOutput）的 LLM 推理生成逻辑；更新 LangGraph 架构为 risk_check→report→signal_output→END；同步更新 Harness 文档；版本号 bump 8.5.4→8.6.0 |
| **v8.5.4** | 2026-07-17 | **cov-3 候选模块覆盖**：新增 4 个测试文件（test_unified_logger.py/test_fdt_version.py/test_config_manager.py/test_fdt_llm.py）共 144 个用例，覆盖率 91%/100%/92%/71%；解决 `tests/conftest.py` sys.path 遮蔽问题；累计 scripts 测试 7 文件/322 用例全绿；同步更新 pyproject.toml、07-operations.md、06-testing.md、08-gap-analysis.md；G65 Phase B 关闭 |
| **v8.5.3** | 2026-07-17 | **cov-2 候选模块覆盖**：新增 178 个测试用例，覆盖 test_fdt_paths.py（84%）/test_trace_id.py（94%）/test_confidence_utils.py（87%）；累计 13 文件/339 用例（161 langgraph + 178 scripts）；同步更新版本号和文档；G65 Phase A 关闭 |
| **v8.5.0** | 2026-07-17 | **G65 测试覆盖扩展**：启动 scripts/ 模块测试覆盖率提升专项，目标消除 0% 覆盖率模块；cov-1/2/3 阶段规划 |
| **v8.4.0** | 2026-07-16 | **G52-G55 生产集成完成**：① G52 `pipeline/runner.py` 集成 LangGraph A/B 切换（`run_langgraph_pipeline()` + `FDT_USE_LANGGRAPH` 环境变量）；② G53 `scripts/run_debate.py` 添加 `langgraph` 子命令（支持 `--mode`/`--symbols`/`--trace-id`）；③ G54 `fdt_langgraph/graph.py` Checkpointer 支持 PG + SQLite 降级（`_get_checkpointer()` + `FDT_CHECKPOINTER=pg` 切换）；④ G55 新增 `tests/fdt_langgraph/test_integration_ab.py` 18 个集成测试验证 A/B 切换机制等价性；**总测试数：99 passed, 1 warning in 5.08s**（8 文件 / 99 用例）；新增 3 个环境变量 `FDT_USE_LANGGRAPH`/`FDT_LANGGRAPH_MODE`/`FDT_CHECKPOINTER`；三级降级路径（LangGraph import 失败→subprocess / PG Checkpointer 失败→SQLite / A/B 默认 false 零风险） |
| **v8.3.0** | 2026-07-16 | **LangGraph 迁移完成**：DebateState TypedDict(19字段+create_initial_state工厂)、10个异步节点函数、按需并行拓扑图(闫判官→链证源/观澜/探源并行→merge_research)、PostgreSQL OLTP+OLAP 混合架构(14表+3视图)、独立 CLI/FastAPI 双入口；更新9篇Harness文档；**21个pytest测试用例全部通过**(节点96%/State 100%/Graph 77%/Agents 65%)；移除外部平台依赖；P1 可插拔多策略扫描、P3 三源平行关系无先后次序 |
| **v8.2.0** | 2026-07-16 | Harness 工程规范全面固化：用户规则 + 项目记忆 + harness-checker 技能 + commit前12项检查清单 + Git Hook 强制检查 |
| **v6.3.2** | 2026-07-14 | P0-4 多因子增强：select_triggers disable_filter 读 _raw_total；V1 OI/基差覆写；V2 OI+量比联合；V3 基差+低波联合；numpy 60s 品种级超时；finalize-only glob mtime 排序；G19 新登记(9 测试全绿)；阈值常量 G20/100ppi 降级 G21 待后续 |
| **v6.3.1** | 2026-07-14 | 技术债 §2/§3 迁移收尾：修复链分析 build_symbol_map 数技源+观澜+探源合并 KeyError + factor_timing NaN 防护 |
| **v6.3.0** | 2026-07-14 | 数技源信号+分析师能力架构落地：scan_all 仅留 channel_breakout；technical-analysis 和 fundamental-data-collector 独立运行 |
| **v5.7.0** | 2026-07-10 | 驾驭工程（Harness Engineering）落地：**经 07-14 复核 G14 实际未落地、G16 重构后失效，原「4.7/5.0 全部完成」声明需修正** |
| **v5.6.0** | 2026-07-09 | 5层鲁棒性架构 (L1-L5) |
| **v5.5.0** | 2026-07-09 | OmniOpt 分类法集成 (F1-F5) |
| **v5.4.0** | 2026-07-07 | 可观测性与自改进里程碑 |
| **v5.3.0** | 2026-07-07 | 通道突破策略里程碑 |
| **v5.2.0** | 2026-07-06 | 架构重构 (通道突破主信号源) |

---

## 7. 自动发布

```bash
# 手动触发
python scripts/auto_publish.py

# 自动触发 (每日 23:05, 由 Master Graph 调度)
# python fdt_cli.py daemon 守护进程中自动执行
```

发布流程:
1. 版本号自增 (patch/minor/major)
2. 更新 README.md 版本历史
3. Git commit + push
4. 通知 (webhook)

---

## 8. 同步与备份

### 8.1 GitHub 同步

| 项 | 内容 |
|:---|:-----|
| 同步方式 | Git push（手动或通过 `gh` CLI） |
| 自动化 | Master Graph daemon 模式无内置自动推送，通过 CI/CD 或手动执行 |
| 排除文件 | `.env`、`*.log`、`__pycache__/`、`D:\FDTWorkspace\` |
| 手动 | `git add -A && git commit -m "..." && git push` |

### 8.2 项目备份

| 项 | 内容 |
|:---|:-----|
| 代码仓库 | Git 管理，远程 origin 保护所有 `.py`/`.md`/`.yaml` 文件 |
| 报告产物 | `D:\FDTWorkspace\{date}\` 报告和信号文件为非版本控制输出，按需归档 |
| 数据库 | PostgreSQL 16+ 每日 pg_dump（如已配置 PGConnection） |

### 8.3 恢复方式

- **代码恢复**: `git checkout` + `git pull` 还原至任意历史版本
- **数据恢复**: 从 PostgreSQL dump 恢复（如已配置）
- **完整重建**: `pip install -r requirements.txt` + `fdt_cli.py db init`

---

## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `pyproject.toml version` | §6.2 版本历史 | FDT 唯一版本真相源（当前 v0.13.0） | `grep "^version" pyproject.toml` |
| `fdt_langgraph/nodes.py _compute_stop_target()` | §6.2 v10.4.0 | stop_loss/target 代码精确计算（L0），LLM 不可修改 | `grep -n "def _compute_stop_target" fdt_langgraph/nodes.py` |
| `fdt_langgraph/nodes.py _clamp_position()` | §6.2 v10.4.0 | 仓位钳制（L0），LLM 输出超限被强制上限 | `grep -n "def _clamp_position" fdt_langgraph/nodes.py` |
| `data_adapter/factors/technical_score.py compute_technical_score()` | §6.2 v10.4.0 | 技术评分代码化（L1），4 维度加权评分，LLM 在 ±10 范围调整 | `grep -n "def compute_technical_score" data_adapter/factors/technical_score.py` |
| `fdt_langgraph/nodes.py node_chain()` | §6.2 v10.1.1 | 链证源使用 `_import_skill_module` 按文件路径加载（兼容目录名含连字符） | `grep -n "def node_chain\|_import_skill_module" fdt_langgraph/nodes.py` |
| `fdt_langgraph/nodes.py node_sentiment()` | §6.2 v10.1.1 | 新闻情绪使用 `parse_llm_output` 解析结构化情绪评分 | `grep -n "def node_sentiment\|parse_llm_output.*sentiment" fdt_langgraph/nodes.py` |
| `docs/report-template/report_css.html` | §6.2 v10.1.1 | 新增 `debate-box.bull`/`.bear` 样式 | `grep -n "debate-box" docs/report-template/report_css.html` |
| `futures_data_core/core/akshare_provider.py get_kline()` | §6.2 v10.0.1 | K线数据源新浪优先，东方财富降级备选 | `grep -n "_fetch_sina_kline\|futures_hist_em" futures_data_core/core/akshare_provider.py` |
| `multi_source_adapter.py _wrap_kline()` | §6.2 v9.25.1 | K线数据统一升序（最旧→最新），`_wrap_kline` 出口处 | `grep -n "def _wrap_kline\|# 统一K线.*升序\|normalized_bars.*reverse" multi_source_adapter.py` |
| `collectors/akshare.py AKShareCollector` | §6.2 v10.0.0 | AKShare 唯一K线数据源，通过 `futures_hist_em` 获取 | `grep -n "class AKShareCollector\|def _to_akshare_symbol\|futures_hist_em" collectors/akshare.py` |
| `futures_data_core/f10/fund_flow.py` | §6.2 v10.0.0 | 新增资金流向模块 | `grep -n "def get_fund_flow\|akshare" futures_data_core/f10/fund_flow.py` |
| `futures_data_core/f10/foreign.py` | §6.2 v10.0.0 | 新增外盘数据模块 | `grep -n "def get_foreign\|akshare" futures_data_core/f10/foreign.py` |
| `futures_data_core/f10/contract_info.py` | §6.2 v10.0.0 | 新增合约信息模块 | `grep -n "def get_contract_info\|akshare" futures_data_core/f10/contract_info.py` |
| `futures_data_core/f10/inventory.py` | §6.2 v10.0.0 | 新增库存数据模块 | `grep -n "def get_inventory\|akshare" futures_data_core/f10/inventory.py` |
| `scripts/fdt_paths.py get_fdt_version()` | §6.2 | 运行时从 pyproject.toml 动态读取 | `grep -n "def get_fdt_version\|pyproject"` |
| `fdt_cli.py run --evolve` | §3.1 启动 | 辩论+自进化一次性执行 | `grep -n "run.*evolve\|--evolve" fdt_cli.py` |
| `fdt_langgraph/master_graph.py run_master_daemon()` | §3 Master Graph | 60s 心跳检查 | `grep -n "def run_master_daemon\|heartbeat\|60"` |
| `fdt_langgraph/master_state.py _get_default_schedules()` | §3.3 | 13 个自动化任务 | `grep -n "def _get_default_schedules\|schedule"` |
| `scripts/daemon_watchdog.py` | §3.2 看门狗 | 30 分钟检查 + 3 分钟心跳阈值 | `grep -n "30\|3\|heartbeat\|watchdog" daemon_watchdog.py` |
| `memory/schedule_state.json` | §3.3 | Master Graph 持久化触发状态 | `test -f memory/schedule_state.json && echo exists` |
| `scripts/dashboard.py --watch` | §4 运维工具 | APM-CS 五轴 HTML 看板 | `grep -n "def main\|--watch\|dashboard" dashboard.py` |
| `scripts/health_server.py --port 9000` | §4 | /health + /metrics HTTP 端点 | `grep -n "def main\|/health\|/metrics" health_server.py` |
| `scripts/auto_publish.py` | §6.3 发布 | Git 标签 + GitHub Release | `grep -n "def publish\|release\|auto_publish"` |
| `scripts/verification/run_benchmark.py --replay` | §5.2 金标准 | 方向一致性 ≥95% | `grep -n "consistency\|accuracy\|95" run_benchmark.py"` |
