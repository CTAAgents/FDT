# Data Governance Phase 3 — 辩论输出数据质量治理

## 1. 动机

Phase 1+2 解决了**输入数据质量**（K线/F10/指标/新闻），但辩论流程自身的**输出数据质量**缺乏闭环：

- P3 多头/空头 Agent 产出可能缺少字段、格式走样、论据空洞
- P4 闫判官裁决可能遗漏交易参数
- P5 风控明审核可能不完整
- 目前没有机制**退回不合格数据要求重修**
- 明鉴秋（P6）被动接收，不做质检，直接组装

## 2. 设计目标

1. **闫判官** — 辩论质量全面监控（论点逻辑、论据充分性、多空力量对比），已有六维评分体系
2. **明鉴秋** — 数据质量监控：逐 Agent 产出校验 Schema → 不合格退回 → 通过后组装报表
3. **重试契约** — 明确重试次数、退避策略、熔断条件

## 3. 质量校验 Schema

### 3.1 多头/空头论据（P3 六阶段）

```python
ARGUMENT_SCHEMA = {
    "required_fields": ["symbol", "arguments", "confidence", "source_refs"],
    "field_types": {
        "symbol": str,
        "arguments": list,       # 每条论据字符串
        "confidence": float,     # 0.0~1.0
        "source_refs": list,     # 来源标记如 ["[technical:观澜]", ...]
    },
    "rules": {
        "min_arguments": 1,              # 至少1条论据
        "max_arguments": 10,             # 最多10条
        "confidence_range": (0.0, 1.0),  # 置信度范围
        "source_ref_required": True,     # 必须引用数据源
    }
}
```

### 3.2 闫判官裁决（P4）

```python
VERDICT_SCHEMA = {
    "required_fields": [
        "symbol", "direction", "confidence",
        "entry_price", "stop_loss", "target1",
        "adx", "atr", "six_dim_scores",
    ],
    "field_types": {
        "symbol": str,
        "direction": str,        # "bull" / "bear" / "neutral"
        "confidence": str,       # "高" / "中" / "低"
        "entry_price": (int, float),
        "stop_loss": (int, float),
        "target1": (int, float),
        "target2": (int, float),
        "adx": (int, float),
        "atr": (int, float),
        "six_dim_scores": dict,  # 六维评分
    },
    "rules": {
        "entry_vs_stop_spacing": 0.5,       # 入场与止损间距 >= 0.5%
        "take_profit_ratio": 1.5,           # 盈亏比 >= 1.5
        "stop_loss_max_pct": 5.0,           # 止损最大 5%
        "confidence_valid": ["高", "中", "低"],
    }
}
```

### 3.3 风控审核（P5）

```python
RISK_SCHEMA = {
    "required_fields": ["symbol", "risk_level", "check_items", "conclusion"],
    "field_types": {
        "symbol": str,
        "risk_level": str,       # "green" / "yellow" / "red"
        "check_items": list,     # 检查项列表
        "conclusion": str,
    },
    "rules": {
        "risk_level_valid": ["green", "yellow", "red"],
        "min_check_items": 3,              # 至少3项检查
    }
}
```

## 4. 状态流转

```
P3 Agent 产出 ──→ 明鉴秋 Schema 校验 ──→ 通过 ──→ 进入下一阶段
                      │                      │
                      │ 不合格                 │
                      ▼                      ▼
                  退回重修                P4 闫判官裁决
                  (max_retry=2)              │
                      │                      ▼
                  Agent 重产           明鉴秋 Schema 校验
                      │                 │         │
                      ▼              通过        不合格
                  再次校验              │          │
                  │      │              ▼         ▼
               通过    超限熔断        P5 风控  退回重修
                          │              │
                      记录到              ▼
                   gap-analysis.md   明鉴秋校验 → 通过
                                         │
                                         ▼
                                     P6 明鉴秋组装报表
```

### 4.1 重试契约

| 参数 | 值 | 说明 |
|:-----|:---|:-----|
| `max_retries` | 2 | 同一数据最多退 2 次 |
| `retry_backoff` | 1.0 | 退回后无延迟（同步流程） |
| `circuit_breaker` | 3 次熔断 | 同一 Agent 连续 3 次不合格 → 本轮跳过 |
| `escalation` | 记录 gap | Agent 触发熔断时登记到 gap-analysis |

## 5. 明鉴秋报表组装逻辑

```
明鉴秋.assemble_report():
  1. 遍历 selected_symbols
  2. 对每品种收集：
     - P3 多头/空头论据（通过质检的）
     - P4 闫判官裁决（通过质检的）
     - P5 风控审核（通过质检的）
  3. 跳过未通过质检的品种（标记原因）
  4. 组装为 debate_report_{trace_id}.html
  5. 写入 memory 归档
```

## 6. 已确认的设计决策（2026-07-23）

| 问题 | 决策 | 影响 |
|:-----|:-----|:-----|
| 超时处理 | 超时累计计入总流程时间 + 自优化指标；大面积超时 → 重新梳理流程和 Agent 角色能力 | `quality_report` 需记录每阶段耗时 |
| 退回粒度 | **只退回不合格品种**。新流程按品种逐个辩论，并行/串行由明鉴秋根据设备性能统一调度 | state 需支持品种级重试计数器 |
| 质检方案 | 采纳提案 | 进入实现阶段 |
| 明鉴秋职责 | 选方案 C：不拆分，明鉴秋一人承担，加硬约束防死锁 | 见下文 §7 |

## 7. 明鉴秋角色边界分析

### 7.1 当前职责清单

| # | 职责 | 类型 | 复杂度 | 备注 |
|:-:|:-----|:----|:------|:-----|
| ① | 选题 + spawn 子 Agent | 调度 | 低 | 已有 |
| ② | 汇总辩论结果 | 聚合 | 中 | 已有 |
| ③ | 写入记忆归档 | 持久化 | 低 | 已有 |
| ④ | **逐品种调度生命周期** | **调度** | **高** | **新增** |
| ⑤ | **Schema 校验** | **质检** | **中** | **新增** |
| ⑥ | **退回重修管理** | **编排** | **高** | **新增** |
| ⑦ | **自优化指标记录** | **数据** | **中** | **新增** |
| ⑧ | **报表组装** | **排版** | **中** | **新增** |

### 7.2 风险评估

**结论：责任过重。** 明鉴秋一人身兼 5 类截然不同的职责（调度/聚合/质检/编排/排版），且第④⑥两项复杂度高、需要状态追踪。风险：

- **调度+质检耦合**：明鉴秋既要决定「谁该跑」又要判定「跑得是否合格」，裁判兼运动员
- **退回回路死锁**：明鉴秋发现数据不合格 → 自己调度重跑 → 又自己检查 → 如果调度器有 bug 可能无限循环
- **缺乏制衡**：没有独立角色复核明鉴秋的裁定

### 7.3 实际执行方案 — 明鉴秋瘦身，新增「品藻」接管质检+报告

**方案**（2026-07-23 掌柜确认）:

| 角色 | 定位 | 职责 | 来源 |
|:-----|:------|:-----|:------|
| **明鉴秋** | 团队主管·调度 | 选题、spawn、逐品种生命周期管理、汇总、记忆写入 | 现有角色瘦身 |
| **品藻** | 质检+文书 | Schema 校验、退回裁定、自优化指标记录、报告排版、HTML 生成、文件归档 | **新增**（合并原质监署+文胆） |

> **命名出处**：「品藻」— 品=品评鉴定，藻=文采辞藻。一字双关，既管质量品评，又管文字润色。

职责转移：

```
明鉴秋(当前)              明鉴秋(新)              品藻(新)
─────────────             ──────────              ──────
选题 ✓                   选题 ✓
spawn ✓                  spawn ✓
汇总 ✓                   汇总(移交警报) ✓
记忆写入 ✓               记忆写入 ✓
                                                                        
质检 Schema 校验 ❌                              Schema 校验(接管) ✓
退回裁定 ❌                                      退回裁定(接管) ✓
自优化指标 ❌                                      自优化指标(接管) ✓
报告排版 ❌                                      报告排版(接管) ✓
HTML 生成 ❌                                      HTML 生成(接管) ✓
文件归档 ❌                                      文件归档(接管) ✓

逐品种调度(新增) ✓       逐品种调度 ✓
质检(新增) ❌                                    质检(接管) ✓
退回管理(新增) ❌                                退回管理(接管) ✓
报表组装(新增) ❌                                报表组装(接管) ✓
```

**为什么要将质检和报告合并给同一角色**：

质检和报告生成在时间线上天然衔接（质检 per symbol → 循环 → 报告 P6），同属「辩论后处理」流水线。合并省去角色间上下文传递开销，且品藻质检基于硬性 Schema 规则（非自由裁量），不存在"自己放水"的风险。

### 7.4 防死锁约束（继承自方案 C）

退回重修机制沿用之前设计的硬约束，不依赖品藻自主决策：

1. **退回计数器在 state 层硬限**：`max_retries_per_symbol = 2`，LangGraph 条件边直接读 state 判断，不经过品藻决策
2. **质检逻辑下沉为纯函数**：`validate_argument()` 等做成无状态工具函数，品藻只调用不修改规则
3. **品藻自身质检**：在 `debate_results.json` 写出后做自动化 `check_report_integrity()` 检查：必需区块存在、无占位文本、文件大小合理

## 8. 实现计划（v9.13.0 品藻拆分）

| 步骤 | 改动文件 | 内容 |
|:-----|:---------|:-----|
| 1 | `docs/designs/data-quality-phase3-debate-output-governance.md` | 更新 §7 角色边界分析（品藻方案） |
| 2 | `agents/futures-quality-assurance.md` | **新增** — 品藻角色定义（质检+报告双职责） |
| 3 | `agents/futures-debate-team-team-lead.md` | 更新明鉴秋角色定义 — 移除质检/报告职责，保留调度 |
| 4 | `docs/harness/02-lifecycle.md` | 更新流程图（P3.5→品藻）+ 阶段规格表 |
| 5 | `docs/harness/01-architecture.md` | 更新数据流（品藻接管质检+报告） |
| 6 | `fdt_langgraph/quality_inspector.py` | 更新文件头注释（明鉴秋→品藻） |
| 7 | `fdt_langgraph/nodes.py` | 更新 node_quality_inspect/node_report docstring 归属标注 |
| 8 | `docs/harness/06-testing.md` | 更新测试统计 |
| 9 | `docs/harness/07-operations.md` | bump 版本号 + 记录变更 |
| 10 | `docs/harness/08-gap-analysis.md` / `09-advancement-plan.md` | 视情况更新 |
| 11 | `README.md` | 更新角色列表 |
| 12 | commit + push | — |

---

**状态**: v2 — 待确认角色拆分方案
