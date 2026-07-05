# 探源 Agent v2 升级报告

**时间**: 2026-07-05 20:38
**范围**: Agent MD + fundamental-data-collector SKILL.md + 脚本模块

## 变更清单

### 1. agents/futures-fundamental-researcher.md — 重写~60%

| 项 | 旧（v1） | 新（v2） |
|:---|:---------|:---------|
| 角色定位 |"基本面研究员"|"链证源搭骨架→探源填肉→喂给证真/慎思"|
| 分析框架 | 4行泛化Methods | 5大维度结构化模块 |
| Output JSON | 扁平文本x7字段 | 结构化"基本面状态向量"x14字段 |
| 辩手支持 | 辩手自己从文字里扒 | `narrative_for_bull/bear` 双向预标记 |
| 领先关系 | 无 | `leading_indicators[]` 领先滞后链路 |
| 预期差 | 无 | `expectation_gap` 字段 |
| 数据保鲜 | 无 | `data_staleness_days` + `data_reliable` |
| 软技能 | 无 | 事实vs叙事 / 领先滞后链 / 预期差 / 换月意识 |
| 3个坑 | 无 | 数据滞后 / 库存降≠必涨 / 换月失真 |

### 2. skills/fundamental-data-collector/ → v1.1.0

- 新增 `macro_link.py`（query_macro）— 宏观外盘联动
- 新增 `chain_balance.py`（query_chain_balance）— 供需平衡表估算
- `term_basis.py` 新增 `query_basis()` 别名 + 持有成本理论价
- SKILL.md 对齐新Output JSON + 9条校验规则

### 3. plugin.json

- tags: 4→3（移除"机器学习"，保留"期货交易+数据驱动辩论+基本面研究"）

## 文件备份

- `agents/futures-fundamental-researcher.md.bak.20260705` — 原版备份
- `agents/futures-fundamental-researcher.md.bak.20260705-v2` — 改写前备份
- `skills/fundamental-data-collector/SKILL.md.bak.20260705` — SKILL备份

## 状态

✅ validate_expert 通过
✅ register_expert 注册成功
