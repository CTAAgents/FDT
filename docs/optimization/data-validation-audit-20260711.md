# 优化全链路数据完整性/正确性校验审计

> 日期：2026-07-11
> 审计范围：`quant-daily/scripts/optimizer/backtest_optimizer.py`、`scan_all.py`（数据源头）
> 结论：**当前优化全流程没有任何实质性的训练集/测试集数据完整性或正确性校验**，是参数与品种筛选正确性的前置缺口。

## 0. 核心结论

优化入口 `load_historical_data`（`backtest_optimizer.py:227`）→ `collect_kline_for_all`（`scan_all.py:146`）。**全链路唯一的过滤在 `scan_all.py:164`：**

```python
valid = [r for r in dlist if r.get("date", "") and r["volume"] > 0 and r["date"] <= today_str]
if len(valid) >= min_bars:
    kline_data[sym] = (name, valid)
```

即：有日期 ∧ 成交量>0 ∧ 日期不超今天 ∧ 数量≥min_bars。**其余全部默认数据"天然正确"。**

> 这直接解释了 J/JM/I 的 `wf=0`：当前代码无法区分"数据不足 / 数据损坏 / 策略真弱"，三者全坍缩成同一个 `0/weak`。已加的 `classify_tier` 仅在 `test_signals < min` 时返回 `unknown`，**无法识别"数据损坏但信号数够"** —— 垃圾数据仍可能被判 good/medium。

## 1. 未被检验的维度（9 项，均代码实证）

| # | 维度 | 现状（证据） | 后果 |
|:--|:--|:--|:--|
| 1 | OHLC 空值/NaN/inf | `prepare_snapshots` 直接 `float(r["open"])`（`backtest_optimizer.py:251-255`），无有限数守卫 | 任一为空 → 崩，或静默 NaN 进入指标链 → 垃圾信号 |
| 2 | 未来值 NaN 静默误标 | `future_changes` 含 NaN 时 `np.mean=NaN`，`NaN>0=False` 判"错"（train 460-461 / `future_direction` 280） | **系统性低估准确率**，且无法定位 |
| 3 | 重复时间戳 | 无任何去重（多源合并最常见污染） | 同一 bar 被 train/test 双计，扭曲方差 |
| 4 | 交易日缺口/日历覆盖 | 只数 bar 数，不查是否缺周缺月 | 80 根散落 400 天也能过 `min_bars` |
| 5 | 合约换月跳空/复权 | 连续主力 L8 拼接跳空仅按 `volume>0` 放行，无异常单根涨幅检测 | 制造假突破/假反转信号 |
| 6 | 交付量对账 | 不核对"实际 bar 数 / 请求 days" | 源返回少数据仍按现有长度做 70/30 切分，静默 |
| 7 | 跨源一致性 | MultiSourceAdapter 多源回退无一致性校验 | 前段调整后段未调整，序列不自洽 |
| 8 | WF 切分边界 | `split=int(n*0.7)`（`backtest_optimizer.py:419-422`），无日历对齐 | 切在缺口中/跨 regime，测试集非干净样本外 |
| 9 | 冗余且不一致的第二条准确率路径 | `evaluate_signal_accuracy`（310-348）仅用 `snapshots[-1]` 判对错 | 与 WF train/test 口径不同，结果可能矛盾 |

> 第 8 项澄清：WF 的 70/30 训练/测试切分**本身是存在的**（测试准确率确在 `test_snapshots` 上算）。问题在于切分建立在未经校验的数据之上，样本外意义被污染数据架空。

## 2. 直接后果

`wf_accuracy=0` 有**三种完全不同的成因**，输出里无法分辨：
- ① 数据不足（<80 根，如退市/流动性枯竭）
- ② 数据损坏（NaN → 第 2 项，所有信号被静默判错）
- ③ 策略在该品种确实弱

三者坍缩为同一 `0/weak`，使品种筛选决策失去正确性的最前置护栏。

## 3. 修复方案（建议实现，待授权）

在 `load_historical_data` 之后、`prepare_snapshots` 之前插入 `validate_kline_data()`，结果打 `data_quality` 标签：

1. **单根**：OHLC 全为有限数、`high≥low`、`0<close`、单根涨跌幅 ≤ 阈值
2. **序列**：严格递增且唯一的时间戳、与交易日历对比覆盖度 ≥ X%、非交易时段 bar 剔除
3. **连续性**：检测换月跳空（相邻收盘突变 > Y% 且非真实大涨）→ 标记需复权或剔除
4. **交付对账**：实际 bar 数 / 请求天数 占比
5. **输出**：每品种 `data_quality = {status: ok | suspect | bad, n_missing, n_dup, n_gap_days, n_anomaly}`
6. **判定联动**：`status=bad` → 直接 `excluded (data_invalid)`，不进入准确率统计；`suspect` → tier 降一级或标 `unknown`
7. **清理**：删除 `evaluate_signal_accuracy` 的 `snapshots[-1]` 路径，统一用 WF train/test 口径

## 4. 实施注意（生产铁律）

- 该改动影响所有优化结果，属 FDT 内代码修改，须先备份、出 diff、经授权后再改。
- 建议**暂不动**后台正在跑的日线 WF（旧代码内存副本），待其收尾后再落校验层。
- 校验层须与 `classify_tier` 的 `unknown` 带协同：bad → `excluded`，suspect → `unknown`/`weak`，避免垃圾数据流入 good/medium。
