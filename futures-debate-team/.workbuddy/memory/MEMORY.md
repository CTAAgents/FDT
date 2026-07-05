# 期货辩论专家团 — 长期项目笔记

## Agent 角色分工（2026-07-05重构）

| Agent | 职责 | 数据来源 |
|:------|:-----|:---------|
| **quant-daily** | 纯数据输出，不做判断 | L1-L4 + factor_timing 计算 |
| **闫判官** | 选辩论品种、定正方方向、主持裁决 | `full_scan_summary_{date}.json` |
| **多方（证真）** | 论证多头方向 | L1-L4 + factor_timing 两份策略数据 |
| **空方（慎思）** | 论证空头方向 | L1-L4 + factor_timing 两份策略数据 |

**辩论标的**: 品种方向（多头 vs 空头），而非策略
**方向来源**: 闫判官自主决定（非预设）
**quant-daily 边界**: 只输出原始数值，不分类、不推荐、不指定辩论标的

## 辩论方案：方案C 仲裁者动态裁决（2026-07-05最终版）
**方案**: 仲裁者动态裁决 — 不预设正方/反方
**核心文件**: `signals/debate_brief.py`
**辩论标的**: 品种方向（多头 vs 空头），而非策略

**辩论流程**:
1. 闫判官发布证据简报
2. 多方从两份策略中提取多头论据
3. 空方从两份策略中提取空头论据
4. 交叉质询
5. 闫判官综合判断 → 裁决

**品种分类**: divergence(分歧→辩论) / directional(单边信号) / consensus(共识)

## 双策略默认模式（2026-07-05）

### 核心改进
- **真实数据源**：`far_close` 通过 `MultiSourceAdapter.get_term_structure()` 获取；`warehouse_receipt` 通过 `DuckDBStore` 获取
- **板块 beta 保留**：`sector_neutral: false`，全市场标准化
- **ADX-OI 联动**：仅 ADX>25 趋势市启用 OI 三角过滤
- **多因子投票 + G1/G10**：5因子独立投票，过半数出手；G1(3)动手组，G10(3)观望组
- **降频预留**：`kline_period` 参数已添加（当前 daily）

### 已知限制
- DuckDB warehouse 表暂无实时填充，仓单数据降级到估值
- 4h/1h 降频需 scan_all.py 层配合传入对应周期 K 线
