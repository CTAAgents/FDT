# 全系统运行审计报告 — 2026-07-05

## 测试品种: RB(螺纹钢), PK(花生), SC(原油)

### P0 — 运行时问题（影响正常执行）

| # | 问题 | 文件 | 影响 | 建议 |
|:-:|:-----|:-----|:-----|:-----|
| 1 | `RuntimeWarning: divide by zero` × N 次 | `indicators/indicators_legacy.py:605,606,658` | 控制台输出被警告淹没，调式困难 | 替换为 `np.divide(..., out=np.zeros_like(), where=denom!=0)` |
| 2 | 仓单数据 0/3 成功 | `strategies/factor_timing.py` | factor_timing 因子的"反向仓单"维度永远为0 | 已知L: DuckDB未填充，需填充或设为可选因子 |
| 3 | `Exchange collector not available` | scan_all.py 启动时 | 不影响运行但显脏 | 抑制或条件导入 |

### P1 — 边界情况（风控引擎未覆盖）

| # | 问题 | 文件 | 影响 | 建议 |
|:-:|:-----|:-----|:-----|:-----|
| 4 | ATR=0时选锚返回 anchor=current_price → 仓位计算报"止损距为零" | `risk_engine.py:select_stop_anchor()` | 极端情况导致整条链崩 | ATR=0时直接返回 `{"error": "ATR为零，无法计算仓位", "final_lots": 0}` |
| 5 | 空支撑列表返回 fake soft 支撑 | `risk_engine.py:select_stop_anchor()` | 辩手和策执远可能误用一个不存在的支撑 | 空列表时返回 `{"hardness": "none", "note": "无有效支撑"}` |

### P2 — 数据质量

| # | 问题 | 数据 | 影响 | 建议 |
|:-:|:-----|:-----|:-----|:-----|
| 6 | SC 展期斜率 -91.87%（正常 -0.5%~-5%） | factor_timing 期限结构 | 因子评分异常，可能污染方向判断 | MultiSourceAdapter 加 outlier 过滤：斜率绝对值>20% 时标记无效 |
| 7 | RB ADX=69.2 强趋势但 CONS=0/4, grade=NOISE | L1-L4 评分 | 技术信号被低估，辩论时观澜和风控明信任度不足 | 检查 L1-L4 的 cons 计算逻辑：ADX>60 时死叉不算否决 |

### P3 — 文档/工程

| # | 问题 | 关联 | 建议 |
|:-:|:-----|:-----|:-----|
| 8 | factor_timing 因子"反向仓单"维度永久缺失 | 数据管道 | DuckDB warehouse 表填充后自动恢复；填充前设为可选因子，避免因子投票计数受影响 |

## 修复优先级

```
P0-1  divide by zero warning  →  15min  (indicators_legacy.py)
P1-4  ATR=0 crash             →  5min   (risk_engine.py)
P1-5  空支撑 fake soft         →  5min   (risk_engine.py)
P2-6  SC斜率异常值              →  10min  (MultiSourceAdapter)
P2-7  CONS/ADX 逻辑偏差       →  30min  (layered_l1l4.py scoring logic)
P3-8  仓单可选因子             →  20min  (factor_timing.py)
P0-3  Exchange警告             →  2min   (scan_all.py)
P0-2  仓单数据填充             →  需数据管道改造（已知限制）
```
