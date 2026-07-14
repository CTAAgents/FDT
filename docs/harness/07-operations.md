# 07 — 运维与部署

## 1. 部署模式

### 1.1 单机模式 (默认)

```
┌─────────────────────────────────────────────┐
│              单机部署架构                     │
│                                             │
│  ┌───────────┐    ┌──────────────────────┐  │
│  │ WorkBuddy  │    │  FDT 项目目录         │  │
│  │ Platform   │───▶│  (plugins/.../        │  │
│  │            │    │   futures-debate-team)│  │
│  │ automation │    │                      │  │
│  │ (30min)    │    │  ┌────────────────┐  │  │
│  └───────────┘    │  │ bootstrap.py   │  │  │
│                    │  │ (daemon模式)   │  │  │
│  ┌───────────┐    │  └───────┬────────┘  │  │
│  │ Python     │    │          │           │  │
│  │ 3.12/3.13  │    │  ┌───────▼────────┐  │  │
│  │            │    │  │ SchedulerEngine │  │  │
│  └───────────┘    │  │ (60s心跳)       │  │  │
│                    │  └───────┬────────┘  │  │
│  ┌───────────┐    │          │           │  │
│  │ DuckDB     │    │  ┌───────▼────────┐  │  │
│  │ futures.db │    │  │ Pipeline Runner │  │  │
│  │            │    │  │ (6步流水线)     │  │  │
│  └───────────┘    │  └────────────────┘  │  │
│                    └──────────────────────┘  │
└─────────────────────────────────────────────┘
```

**特点**:
- 所有组件在同一台机器运行
- 通过 WorkBuddy automation 触发 daemon_watchdog.py (每30分钟)
- Python 直接运行，无需容器化
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

## 5. 版本管理

### 5.1 版本号规范

| 位置 | 当前版本 | 格式 |
|:-----|:---------|:-----|
| `pyproject.toml` | 6.3.1 | **唯一版本源**（`bootstrap.py` 经 `scripts/fdt_paths.py:get_fdt_version()` 运行时读取） |
| `bootstrap.py` | 动态 | 从 pyproject.toml 读取，不再硬编码 |
| `README.md` | v6.3.1 | 与 pyproject.toml 同步 |

### 5.2 版本历史

| 版本 | 日期 | 里程碑 |
|:-----|:-----|:-------|
| v6.3.2 | 2026-07-14 | P0-4 多因子增强：select_triggers disable_filter 读 _raw_total；V1 OI/基差覆写；V2 OI+量比联合；V3 基差+低波联合；numpy 60s 品种级超时；finalize-only glob mtime 排序；G19 新登记(9 测试全绿)；阈值常量 G20/100ppi 降级 G21 待后续 |
| v6.3.1 | 2026-07-14 | 技术债 §2/§3 迁移收尾：修复链分析 build_symbol_map 数技源+观澜+探源合并 KeyError + factor_timing NaN 防护 |
| v6.3.0 | 2026-07-14 | 数技源信号+分析师能力架构落地：scan_all 仅留 channel_breakout；L1-L4→technical-analysis(run_l1l4_scan)，factor_timing→fundamental-data-collector(run_factor_timing_scan) |
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
