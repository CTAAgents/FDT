# Delegation Protocol — 条件委派协议

> v1.0 | 关联文档: [human-ai-hybrid-finance-fdt-optimization.md](human-ai-hybrid-finance-fdt-optimization.md) §2.2, §5 Phase D
> 最后更新: 2026-07-26

---

## 1. 概述

本协议定义 FDT 系统中基于条件判断的委派路由规则。每条规则包含四个要素：

| 要素 | 说明 |
|:-----|:------|
| **触发条件** | 什么情况下激活委派 |
| **跳过步骤** | 委派激活后跳过哪些阶段/节点 |
| **恢复条件** | 什么情况下恢复到完整流程 |
| **回退机制** | 委派执行异常时的兜底方案 |

---

## 2. 规则 R01：P3 源主动跳过

### 触发条件
- P3 某分析源（观澜/探源/读心/链证源）对特定品种的**连续 N 轮历史准确率 < 40%**
- N 默认值 = 5（可在 `decode_config.yaml` 中按源调整）
- 准确率来自 VerdictDB 历史裁决记录

### 跳过步骤
- 该源在 P3 阶段**不再被调度**（不等 300s 超时）
- 该源对应的 `node_technical` / `node_fundamental` / `node_sentiment` / `node_chain` 节点条件边直接跳至下一个可用源
- 辩论 prompt 中标注"某源因准确率偏低已跳过"

### 恢复条件
- 该源连续 3 轮**未跳过**（即手动重审通过，或全局校准后准确率回升至 >= 40%）
- 或系统全局重置（全量重新评估准确率）

### 回退机制
- 跳过期间异常：该源按默认 300s 超时降级（现有逻辑）
- 所有源均跳过：触发 G19 无品种跳转（现有逻辑）

### 配置项

```yaml
# decode_config.yaml
delegation_rules:
  r01_skip_p3_source:
    enabled: true
    accuracy_threshold: 0.4
    consecutive_rounds: 5
    exclude_sources: []  # 永不跳过的源
```

### LangGraph 条件边逻辑

```
node_prepare_p3 → should_skip_source()
  ├── accuracy >= threshold and < consecutive_rounds → node_technical (正常)
  ├── accuracy < threshold >= consecutive_rounds      → skip_source (跳过)
  └── skip_count >= 3 (已恢复条件)                     → node_technical (恢复)
```

---

## 3. 规则 R02：跳过副判官独立裁决

### 触发条件
- P4 闫判官初判置信度 > 85%
- 且方向明确（非 neutral/non-directional）
- 且多空论据无明显分歧（一致性裁判未标记矛盾）

### 跳过步骤
- 跳过副判官独立裁决层级
- 闫判官裁决直接进入风控审核

### 恢复条件
- 该品种有以下任一情况时恢复副判官：
  - 历史裁决准确率 < 50%
  - 波动率（HV20）处于历史高位（> 90% 分位）
  - 系统处于"高不确定性"模式

### 回退机制
- 跳过期间若副判官代码抛出异常：不影响主流程（闫判官裁决已足够）
- 若事后发现漏判：登记差距到 `08-gap-analysis.md`

### 配置项

```yaml
delegation_rules:
  r02_skip_vice_judge:
    enabled: true
    min_confidence: 0.85
    max_volatility_percentile: 90
    min_historical_accuracy: 0.5
```

---

## 4. 规则 R03：辩论聚焦矛盾点标注

### 触发条件
- P3 基本面与 P2 技术面信号方向矛盾
  - 例如：观澜（技术面）看多 × 探源（基本面）看空
  - 或：链证源产业链信号与观澜指标矛盾

### 执行行为
- 在 P4 辩论 prompt 开头插入矛盾聚焦段：

```
【矛盾点提示】本品种的基本面与技术面信号方向不一致，请辩论双方聚焦解决以下矛盾：
- 技术面: 观澜判断看多（理由: ...）
- 基本面: 探源判断看空（理由: ...）
- 请双方重点论证哪一方的逻辑更可靠
```

### 恢复条件
- 不改变流程，仅影响 prompt 内容
- 矛盾消失（信号方向一致）后自动取消标注

### 回退机制
- prompt 注入失败：正常辩论（不影响流程）

### 配置项

```yaml
delegation_rules:
  r03_debate_focus:
    enabled: true
```

---

## 5. 委派日志格式

每条委派触发时记录到操作历史：

```json
{
  "timestamp": "2026-07-26T10:00:00",
  "rule": "r01_skip_p3_source",
  "symbol": "RB",
  "trigger": "连续6轮准确率=35%",
  "skipped": "node_technical",
  "recovery": false,
  "fallback": false
}
```

存储路径: `memory/delegation/logs/{YYYY-MM}/`
