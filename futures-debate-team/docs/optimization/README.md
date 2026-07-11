# 优化器（Walk-Forward）稳定性与正确性审查 — 工作索引

> 工作日期：2026-07-11
> 归属系统：`futures-debate-team` / `quant-daily/scripts/optimizer`
> 触发原因：日线辩论管线误报 J 焦炭 STRONG 空头信号（自优化已剔除却在硬编码宇宙仍被扫出），引发对"品种适合性判定稳定性"与"优化数据正确性"的系统性审查。

## 文档清单

| 文件 | 内容 |
|:--|:--|
| `wf-universe-stability-refactor-20260711.md` | 三宇宙架构脱钩根因 + 周频过高诊断 + A/B/C 组合重构（降频/结构冻结/稳定核心宇宙+滞后确认/日频 regime 指标） |
| `data-validation-audit-20260711.md` | 优化全链路数据完整性/正确性校验缺失审计（9 项实证缺陷 + 修复方案） |
| `wf_universe_refactor_20260711.diff` | A/B/C 重构的逐行 diff 对比报告（基线：`backups_wf_universe_20260711_0949`） |

## 本轮已落地改动（代码侧）

1. **方案 B 整合**：优化总控从 Signal `scripts/update_monitoring_config.py` 迁入 FDT `quant-daily/scripts/optimizer/run.py` 的 `--update-config` 子命令；Signal 侧降级为 thin wrapper。消除硬编码 `SKILL_DIR` 跨层依赖。
2. **`daily_debate.py` 品种池脱钩修复**：`DAILY_SYMBOLS` 改为从 `config/monitoring_symbols.json` 的 `daily.symbol_list` 动态派生（含回退），使自优化排除传导到辩论管线。
3. **A/B/C 重构**（详见稳定性文档）：
   - 频率：周频 → 每 4 周（`automation-1783404492691`）
   - 结构冻结：`WF_CONFIG(v1.0.0)` + `WF_CHANGELOG`，杜绝"相邻两周尺子不同"
   - 置信下界定级：`classify_tier()`（小样本 → `unknown`）
   - 稳定核心宇宙（32 品种，永不自动剔除）+ 滞后确认（连续 3 周一致才增删）
   - 新增 `regime.py` 日频轻量指标（用于信号权重，不参与纳入/剔除）

## 待办（未落地，需授权）

- **数据校验层**（`validate_kline_data()`）：当前优化链路**无任何实质性数据完整性/正确性校验**，是参数与品种筛选正确性的前置缺口。审计与方案见 `data-validation-audit-20260711.md`。

## 备份位置

- `C:/Users/yangd/backups_daily_debate_20260711_093057`（daily_debate.py 修复前）
- `C:/Users/yangd/backups_wf_universe_20260711_0949`（run.py + backtest_optimizer.py 重构前）
- `C:/Users/yangd/backups_daily_wf_20260711_093529`（含原总控脚本、monitoring_symbols.json、optimized_params.json）
