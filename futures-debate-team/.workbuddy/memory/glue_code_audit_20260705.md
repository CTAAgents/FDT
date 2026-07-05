# 胶水代码审计报告

## 本次产生的胶水代码

| # | 胶水代码 | 根因 | 是否已修复 |
|:-|:---------|:-----|:----------|
| 1 | `generate_debate_report.py` — 一次性HTML生成器 | 现有 `phase3_generate_report.py` 的输入格式是 `intermediate_data.json`，与scan_all产出的 `full_scan_summary_*.json` 不兼容 | ✅ `assemble_intermediate_data.py` 数据适配器 |
| 2 | 多条 `python -c "..."` 临时查询（分歧统计/链归属/Z分数） | 缺少用于数据探查的CLI工具 | ✅ `debate_brief.py --select-debate` |
| 3 | `full_data_js.json` 中间缓存 | HTML报告需要将Python端链映射传到JS端 | ✅ 已纳入 `assemble_intermediate_data.py` |

## 修复清单

### 修复1：`signals/debate_brief.py` 新增 `select_debate_symbols()` + `--select-debate` CLI
```bash
# 替代临时脚本的用法：
python skills/quant-daily/scripts/signals/debate_brief.py \
  full_scan_l1l4_*.json full_scan_factor_timing_*.json \
  --select-debate chain_analysis.json --min-count 22 --min-chains 12
```

### 修复2：新建 `scripts/assemble_intermediate_data.py` 数据适配器
```bash
# 将scan_all产出适配为phase3可消费格式：
python skills/quant-daily/scripts/assemble_intermediate_data.py \
  --summary full_scan_summary_*.json \
  --chain-analysis chain_analysis.json \
  --chain-strategy chain_strategy_report.json
# 产出: intermediate_data.json + debate_results.json
```

### 修复3：清理胶水文件
- ❌ `generate_debate_report.py` → 已删除
- ❌ `full_data_js.json` → 已删除

## 标准数据流（最终版 · 零胶水代码）
```
Phase 1: scan_all.py --dual
    → full_scan_l1l4_*.json + full_scan_factor_timing_*.json + full_scan_summary_*.json

Phase 2: debate_brief.py ... --select-debate chain_analysis.json --min-count 22
    → 辩论品种精选JSON（替代手动python -c查询）

Phase 3: assemble_intermediate_data.py --summary ... --chain-analysis ...
    → intermediate_data.json + debate_results.json

Phase 4: phase3_generate_report.py
    → daily_analysis_*.html
```
