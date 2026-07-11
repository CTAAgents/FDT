# 优化器品种宇宙稳定性重构（方案 A+B+C）

> 日期：2026-07-11
> 关联：`docs/optimization/README.md` · `wf_universe_refactor_20260711.diff`

## 0. 问题起点

日线辩论管线误报 J 焦炭 STRONG 空头：自优化已将 J 从监测列表剔除，但辩论管线（硬编码 42 品种宇宙）仍扫出。根因是**系统存在三套互相独立的"品种宇宙"，而自优化只重写其中一套**。

## 1. 三套品种宇宙（根因）

| # | 宇宙 | 定义位置 | 含 J 焦炭 | 谁用 |
|:--|:--|:--|:--|:--|
| 1 | `ALL_SYMBOLS`（62） | `quant-daily/scripts/config/symbols.py`（静态） | ✅ | `scan_all.py` 全量扫描默认池（手动用） |
| 2 | `DAILY_SYMBOLS`（42） | `daily_debate.py`（**原硬编码**，J 在"勉强可用"段） | ✅ | 日线辩论管线 |
| 3 | `symbol_list`（日 34 / 120m 12） | `config/monitoring_symbols.json`（自优化动态重建） | ❌ 已排除 | `scan_monitored.py` 监测扫描 | ⚠️ 120m 监测已废弃(2026-07-11)，现仅日线 |

自优化（`update_monitoring_config.py`）只写 #3，碰不到 #1/#2。

**已修复（#2）**：`daily_debate.py` 的 `DAILY_SYMBOLS` 改为 `_load_daily_symbols()`，从 `monitoring_symbols.json` 的 `daily.symbol_list` 动态派生（配置缺失回退硬编码 42）。验证：派生 34 个且 J 不在池；回退路径正确。

## 2. 频率过高的诊断

### 2.1 量化证据（`backtest_optimizer.py` 常量）
- `DAYS_OF_DATA=400`、`MIN_BARS=80`、`SAMPLE_INTERVAL=5`、`WF_TEST_PCT=0.3`
- 测试集约 19 个截面，有效信号（STRONG/WATCH/WEAK）仅 **6–9 个**
- 周频窗口每次平移 5 个交易日 → **相邻两周测试集重叠约 95%**，每周仅新增约 **1 个有效信号**

### 2.2 三个被混为一谈的量
| 量 | 属性稳定性 | 正确节奏 | 周频 WF 是否合适 |
|:--|:--|:--|:--|
| ① 品种是否适合趋势监测（纳入/剔除） | **跨年稳定** | 近静态 / 季度复核 | ❌ 远超合理上限 |
| ② 策略参数重拟合 | 400 天窗口下极稳 | 月度 / 季度 | ❌ 过高，主要引入网格噪声 |
| ③ 当下市况 / 信号权重（regime） | 不稳定，应高频 | 日频轻量指标 | ⚠️ 意图合理、工具错配 |

周频真实动机是"保持对市况敏感"，但被错实现为"每周重写监测宇宙" —— 抖动宇宙而非跟上市况。

## 3. 重构方案（A+B+C 组合，已落地）

### A. 降频
- 自动化 `automation-1783404492691`（原"每周五参数自优化"）改为 **每 4 周周五**：
  `FREQ=WEEKLY;INTERVAL=4;BYDAY=FR;BYHOUR=15;BYMINUTE=5`
- 与"品种适合性是稳定属性"对齐，消除"每周重跑全量只为捕获约 1 个新信号"的算力浪费与噪声注入。

### B. 结构冻结 + 稳定核心宇宙 + 滞后确认
- **结构冻结**：`backtest_optimizer.py` 分散常量整合为版本化 `WF_CONFIG(v1.0.0)` + `WF_CHANGELOG`。任一结构常量变更视为"结构变更"，须全量重基线 + 写 changelog，杜绝"相邻两周尺子不同"导致数字不可比。
- **置信下界定级**：新增 `wilson_ci_lower()` / `classify_tier()`。小样本（`test_signals < min_test_signals_for_ci=10`）→ 定级 `unknown`（未知带），不冒然判 good/weak。轻量路径（`--light`）退回点估计以保持兼容。
- **稳定核心宇宙**：`WF_CONFIG["core_universe"]` 32 品种（流动性 + 趋势持续性强的黑色/能源/聚酯/农产品等），**永不自动剔除**。
- **滞后确认**：`build_monitoring_config` 重写为 `_resolve_inclusion()`，纳入/剔除需**连续 `hysteresis_weeks=3` 周一致**才生效；持久化状态文件 `monitoring_state.json`（首轮以现有 `symbol_list` 为基线）。

### C. 日频 regime 轻量指标（解耦市况敏感）
- 新增 `regime.py`：`compute_regime()` 基于 ADX 长期分位 / 波动率比值 / 斜率 → 权重 **0.5~1.5**；`build_regime_from_kline()` 从本地数据计算。
- 新增 `run.py --regime` 子命令（`--from-json` / `--regime-out`）。
- **仅用于信号权重，不参与纳入/剔除** —— 市况敏感由日频轻量指标承载，而非靠重写监测宇宙。

## 4. 验证（全绿）
- 三文件 `py_compile` 通过
- `classify_tier`：`0.55/6→unknown`、`0.90/30→good`、`0.30/30→weak` 正确
- 轻量重建临时 config 生成 `monitoring_state.json`，核心宇宙 32 强制包含，tiers 含 `unknown` 带
- `regime` 合成数据 → `trend_up / 1.4`

## 5. 过渡说明
后台日线 WF（旧代码内存副本）跑完后写出旧格式 `monitoring_symbols.json`；下一每 4 周运行由新代码以之为基线初始化 `monitoring_state.json`，平滑接管滞后逻辑，无冲突。

## 6. 后续待办
- 将 `regime` 权重真正接进 `scan_monitored` 的信号总分
- 调整 `core_universe` 名单 / 滞后周数（如需）
- **数据校验层**（`validate_kline_data()`）尚未落地，见 `data-validation-audit-20260711.md`
