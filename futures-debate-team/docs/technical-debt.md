# Futures-Debate-Team 技术债清单

> **版本**: v4.4 | **日期**: 2026-07-05 | **来源**: 全项目代码扫描 + 架构分析
> **状态**: P0+P1+P2+P3 全部25项优化已完成，以下为仍需关注的遗留技术债

---

## 1. 代码质量问题

### 1.1 大文件重构（500+行文件）

| 文件 | 行数 | 风险 | 建议 |
|:-----|:-----|:-----|:-----|
| `skills/quant-daily/scripts/strategies/factor_timing.py` | 1358 | 🔴 | 拆分为 `factor_definitions.py` + `factor_score.py` + `factor_timing.py` |
| `skills/quant-daily/scripts/indicators/calc_core.py` | 1475 | 🔴 | 拆分为按指标类别的子模块（trend/momentum/volatility/volume） |
| `skills/quant-daily/scripts/indicators/indicators_legacy.py` | 1442 | 🔴 | 标记为 `deprecated`，逐步迁移到 `calc_core.py` |
| `skills/quant-daily/scripts/data/multi_source_adapter.py` | 1092 | 🟡 | 拆分为 `adapter_base.py` + `tdx_adapter.py` + `tqsdk_adapter.py` |
| `skills/quant-daily/scripts/signals/scoring_system.py` | 1010 | 🟡 | 拆分为 `scoring_base.py` + `scoring_signals.py` |
| `skills/debate-risk-manager/scripts/risk_engine.py` | 771 | 🟡 | 拆分为 `portfolio_risk.py` + `position_sizing.py` + `risk_scenarios.py` |
| `skills/quant-daily/scripts/scan_all.py` | 633 | 🟡 | 拆分HTML生成器到独立模块 |

**影响**: 代码维护困难，单文件修改易引入bug

### 1.2 异常处理薄弱

| 文件 | 行 | 问题 | 严重程度 |
|:-----|:---|:-----|:---------|
| `skills/quant-daily/scripts/data/multi_source_adapter.py:830` | `except Exception: pass` | 静默吞异常 | 🔴 |
| `scripts/compliance_agent.py:145` | `except:` | 裸except，捕获系统退出 | 🟡 |
| `scripts/ops_monitor.py:80` | `except:` | 裸except | 🟡 |
| `scripts/auto_factor_mining.py` | 多处 | `random.random()` 模拟评分，无真实数据路径 | 🟡 |
| `skills/commodity-chain-analysis/scripts/term_basis.py:331` | `except:` | 裸except | 🟡 |
| `skills/technical-analysis/scripts/support_resistance.py` | 多处 | 计算异常仅 `return 0` | 🟡 |

**影响**: 运行中异常难以追踪，数据管道断裂时无告警

### 1.3 冗余/废弃代码

| 问题 | 位置 | 建议 |
|:-----|:-----|:-----|
| `indicators_legacy.py` 1442行被6个回测模块引用 | `skills/quant-daily/scripts/backtest/*.py` | 逐步迁移到 `calc_core.py`，标记为 `@deprecated` |
| `scan_all.py` 中的 HTML 生成器（约300行HTML/CSS/JS字符串） | `skills/quant-daily/scripts/scan_all.py` | 提取到 `report_templates.py` |
| `WITHIN_CHAIN_HIGH_CORRELATION` 空字典占位 | `skills/commodity-chain-analysis/scripts/chains.py:249` | 可以安全删除 |
| `true_layered` 策略已废弃但 `--mode` 参数仍保留其作为选项 | `skills/quant-daily/scripts/scan_all.py` | 移除废弃选项 |

---

## 2. 测试覆盖缺口

### 2.1 测试覆盖率统计

| Skill | 测试文件 | 覆盖模块 | 缺失模块 |
|:------|:---------|:---------|:---------|
| quant-daily | ❌ 无 | — | `scan_all, factor_timing, direction_classifier, debate_engine, backtest*` |
| futures-trading-analysis | ✅ `test_contracts.py` | contracts全套 | — |
| debate-risk-manager | ✅ `test_risk_manager.py` | 风控核心 | 未覆盖portfolio_risk |
| commodity-chain-analysis | ✅ 5个测试 | chain/risk/debate/screen | 未覆盖全链路 |
| fundamental-data-collector | ⚠️ `test_collector.py` | 全是"XXXXX"占位符 | **全部待补** |
| debate-argument-builder | ✅ `test_debater.py` | 辩手工具 | — |
| technical-analysis | ✅ `test_technical.py` | 技术分析 | 未覆盖event_calendar/regime |
| scripts/（新模块） | ❌ 无 | — | 全部9个新模块 |
| compliance/ops/execution | ❌ 无 | — | 全部需补 |

### 2.2 必须补的测试优先级

| 优先级 | 测试 | 原因 |
|:------|:-----|:------|
| 🔴 | `fundamental-data-collector/test_collector.py` | 现有4个测试全是占位符，跑即报错 |
| 🔴 | `quant-daily/scripts/strategies/test_factor_timing.py` | 核心策略，1358行，改坏风险最高 |
| 🟡 | `scripts/test_memory_writer.py` | 并行记忆写入，数据完整性关键 |
| 🟡 | `scripts/test_fingerprint.py` | 决策确定性，seed锁定核心 |
| 🟡 | `scripts/test_portfolio_risk.py` | L6组合风控，大资金安全 |

---

## 3. 架构遗留问题

### 3.1 Pydantic v2 未全量迁移

| 文件 | 状态 | 问题 |
|:-----|:------|:------|
| `contracts/base.py` | ✅ 已升级 | 已配置 `extra="ignore"` + `schema_version` |
| `contracts/*.py`（其他12个） | ⚠️ 部分升级 | 部分 schema 仍使用 Pydantic v1 Config 类写法 |
| 各Agent输出的裸JSON | ❌ 无schema | 部分Agent输出的自由格式JSON未经过schema校验 |

**建议**: 全量审计所有 schema，统一为 `model_config = ConfigDict(extra='ignore')`

### 3.2 数据源持久化层脆弱

| 组件 | 问题 |
|:-----|:-----|
| DuckDB | 多处 `DuckDBStore()` 初始化失败但无降级 |
| sentiment 缓存 | 脆弱JSON文件存储，无并发保护 |
| trade_journal | JSON文件追加写入，无法并发查询 |
| memory_writer | 今日新建，SQLite过渡方案还未完全落地 |

**建议**: 统一数据持久化到 SQLite（中期）→ PostgreSQL（长期）

### 3.3 配置集中管理缺失

| 问题 | 当前 | 建议 |
|:-----|:-----|:------|
| settings.json 不完整 | 仅有 agent/seed/mode | 统一管理所有配置项（数据源/LLM/风控阈值/回测参数） |
| 配置散落 | fee_table.py 中有62品种费率，backtest_report 中有默认参数 | 全部收敛到 settings.json |

### 3.4 依赖管理不完整

| 问题 | 影响 |
|:-----|:------|
| `pyproject.toml` 今日新建，未经过实际安装验证 | 首次 `pip install` 可能依赖缺失 |
| 部分代码 `import lightgbm` 无条件捕获 ImportError | 无 LightGBM 环境直接崩溃 |
| psutil 在 ops_monitor 中无 `try/except` | Windows 可能缺少该包 |

---

## 4. 可观测性缺失

### 4.1 日志系统

| 严重程度 | 问题 |
|:---------|:------|
| 🔴 | 10个Agent无统一日志框架，使用 `print()` 输出 |
| 🔴 | DAG调度无结构化的日志级别（debug/info/warn/error） |
| 🟡 | 风控明引擎有 `logger` 但未标准化到其他Agent |
| 🟡 | 无日志轮转（log rotation），长时间运行磁盘撑满 |

**建议**: 统一使用 `logging` 模块 + JSON 格式化日志 + 日志轮转

### 4.2 监控告警

| 组件 | 状态 |
|:-----|:------|
| `scripts/ops_monitor.py` | ✅ 今日新建，已有健康检查+面板基础 |
| 企微/钉钉 webhook | ❌ 配置为空，告警发不出去 |
| 数据源中断检测 | ❌ 未实现 |
| Agent 心跳 | ❌ 未实现 |

---

## 5. 安全与合规

### 5.1 敏感信息泄露风险

| 路径 | 风险 | 处置 |
|:-----|:-----|:-----|
| `settings.json` | 包含agent名称 | ✅ 已加入 `.gitignore` |
| 各skill未检查 `.gitignore` | 默认不在 git 管理中 | ✅ `.gitignore` 已覆盖 |
| Webhook URLs 硬编码 | 可能被提交 | ⚠️ 需统一改到环境变量 |

### 5.2 合规审计

| 组件 | 状态 |
|:-----|:------|
| `scripts/compliance_agent.py` | ✅ 今日新建，哈希链日志 |
| 持仓限额自动校验 | ✅ 已实现 |
| 大户报告自动触发 | ✅ 已实现 |
| 实际部署到辩论流程中 | ❌ 未集成到 DAG |

---

## 6. 文档与技术债务

### 6.1 文档缺口

| 文档 | 状态 | 缺失内容 |
|:-----|:------|:---------|
| `docs/agent-protocol.md` | ✅ 完整 | — |
| `docs/optimization-plan-v4.4.md` | ✅ 完整 | — |
| `docs/audit-report-20260705.md` | ✅ 完整 | — |
| `docs/reports/` | ✅ 有回测报告 | 缺回测结果分析 |
| `USER_MANUAL.md` | ✅ v4.3 | ⚠️ 需更新到 v4.4（25项新功能） |
| `README.md` | ✅ v4.3 | ⚠️ 需更新到 v4.4 |
| `skill` 各SKILL.md | ⚠️ 部分过时 | factor_timing仍在写5因子，实际已6因子 |

### 6.2 代码注释

| 文件 | 注释覆盖率 | 建议 |
|:-----|:----------|:------|
| 新建 scripts/ 下9个文件 | ✅ 有完整 docstring | — |
| `scan_all.py` | ⚠️ 函数注释不全 | 补全 `run_scan` 的参数说明 |
| `factor_timing.py` | ⚠️ 部分函数缺注释 | 1358行大文件，注释覆盖不足 |

---

## 7. 技术债优先级排序

| 优先级 | 项目 | 预估工时 | 影响 |
|:------|:-----|:--------|:-----|
| 🔴 | **fundamental-data-collector 测试修复** | 2h | 测试不可用，回退信心不足 |
| 🔴 | **大文件拆分: factor_timing(1358行)** | 1天 | 改坏风险最高 |
| 🔴 | **统一日志框架替代 print()** | 1天 | 排查问题效率低 |
| 🟡 | **Pydantic v2 全量迁移** | 6h | 版本兼容风险 |
| 🟡 | **README/USER_MANUAL 更新到v4.4** | 2h | 版本号不一致 |
| 🟡 | **新增模块测试: scripts/下9个文件** | 1天 | 新代码无保护 |
| 🟡 | **大文件拆分: multi_source_adapter(1092行)** | 6h | 数据源抽象层耦合高 |
| 🟢 | **配置收敛到 settings.json** | 4h | 配置散落 |
| 🟢 | **废弃代码清理 (legacy/true_layered)** | 2h | 仅整洁性问题 |
| 🟢 | **webhook 告警配置接入** | 2h | 运维告警不发 |

---

## 8. 风险提示

1. **indicators_legacy.py 仍在被6个backtest模块引用**：回测改坏风险最高，任何修改必须跑全量回测
2. **fundamental-data-collector 测试的占位符**：`query_supply("XXXXX")` 意味着该skill从未真正测试过，属于"假测试"
3. **DAG调度无超时兜底的fallback验证**：P1-4 添加了重试机制，但降级缓存路径未经过实盘验证
4. **情感因子数据源未接入**：`sentiment_collector.py` 各层采集函数均为 `return {}`，实际部署需接入第三方API
5. **新增的 scripts/ 模块未集成到 DAG**：execution_agent/ops_monitor/compliance_agent/marl_trainer/market_game_agent/auto_factor_mining 等新模块尚未嵌入 DAG 调度流程

---

*文档生成: 2026-07-05 22:53 | 基于全项目代码扫描*  
*下次巡检: 建议每周一次技术债回顾*
