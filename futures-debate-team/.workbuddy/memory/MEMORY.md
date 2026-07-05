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

## 胶水代码防复发方案（2026-07-05新增）

### 历史胶水代码案例分析
2026-07-05执行全量辩论流程时产生了以下胶水代码：

| 胶水代码 | 根因 | 修复方案 |
|:---------|:-----|:---------|
| `generate_debate_report.py`（一次性HTML生成） | `phase3_generate_report.py` 输入格式与scan_all产出不兼容 | 新增 `assemble_intermediate_data.py` 数据适配器 |
| 多条 `python -c` 临时查询：统计分歧/链归属/Z分数 | 缺少用于数据探查的CLI | `debate_brief.py` 新增 `--select-debate` 参数 + `select_debate_symbols()` 函数 |
| `full_data_js.json` 中间缓存 | 报表生成需要Python→JS链映射桥接 | `assemble_intermediate_data.py` 统一构建符号→链映射，传递结构化数据 |

### 标准数据流（现）
```
scan_all.py --dual
    → full_scan_l1l4_*.json + full_scan_factor_timing_*.json
    → 自动 build_signal_summary() → full_scan_summary_*.json
  
debate_brief.py --select-debate chain_analysis.json
    → 直接用CLI输出辩论候选列表（含分歧度/链覆盖统计）
    → 禁止 python -c 临时查询

assemble_intermediate_data.py --summary + --chain-analysis
    → intermediate_data.json + debate_results.json
    → phase3_generate_report.py 可以消费

phase3_generate_report.py
    → daily_analysis_*.html（现有流程，无改动）
```

### 执行顺序（不再产生胶水代码）
```bash
# Phase 1: 双策略扫描
python skills/quant-daily/scripts/scan_all.py --dual

# Phase 2: 辩论品种精选（替代临时脚本）
python skills/quant-daily/scripts/signals/debate_brief.py \
  reports/full_scan_l1l4_*.json reports/full_scan_factor_timing_*.json \
  --select-debate chain_analysis.json --min-count 22

# Phase 2.5: 数据适配（替代generate_debate_report.py）
python skills/quant-daily/scripts/assemble_intermediate_data.py \
  --summary reports/full_scan_summary_*.json \
  --chain-analysis chain_analysis.json

# Phase 3: 报告生成（现有流程）
python skills/futures-trading-analysis/scripts/phase3_generate_report.py
```
