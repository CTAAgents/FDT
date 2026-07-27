# P3 因子驱动改造实施记录

> 日期: 2026-07-26

## 已实施变更

### 1. P3 四源节点: refined_factor 精炼因子输出
- 观澜: volatility -> refined_factor
- 探源: holding_sentiment+term_structure -> refined_factors
- 读心: sentiment -> refined_factor

### 2. 辩论节点: 因子锚定(消除AP16)

### 3. 裁决节点: 因子加权裁决

### 4. 报告: P2.5 因子信号看板

### 5. 此前修复
- _nodes_utils.py: _SKILLS_DIR / importlib / sys
- _nodes_research.py: 链证源导入 + 情绪FDC兜底 + P3 fanout
- single_symbol_report.py: 情绪state直读回退
