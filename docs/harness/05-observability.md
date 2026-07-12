# 05 — 可观测性

## 1. 可观测性架构

FDT 的可观测性体系由三个维度组成：

```
┌─────────────────────────────────────────────────────────────┐
│                    可观测性三大维度                           │
├─────────────────┬─────────────────┬─────────────────────────┤
│   Metrics       │   Logging       │   Tracing               │
│   (指标度量)     │   (日志记录)     │   (追踪回放)             │
├─────────────────┼─────────────────┼─────────────────────────┤
│ APM-CS 五轴     │ unified_logger  │ debate_journal.json     │
│ (D1-D5)         │ (统一日志)       │ (辩论全链路记录)          │
│                 │                 │                         │
│ 失败聚类         │ pipeline日志    │ ViBench 回放            │
│ (cluster_       │ (流水线日志)     │ (replay_harness.py)     │
│  failures.py)   │                 │                         │
│                 │                 │ held-out judge          │
│ 纪律钳制         │ scheduler日志   │ (一致性审计)             │
│ (enforce_       │ (调度器日志)     │                         │
│  discipline.py) │                 │                         │
└─────────────────┴─────────────────┴─────────────────────────┘
```

## 2. APM-CS 五轴评分卡

### 2.1 五轴定义

| 轴 | 名称 | 含义 | 计算方法 | 触发 |
|:--|:-----|:-----|:---------|:-----|
| **D1** | Coherence (一致性) | 裁决是否真正源于辩论论据 | held-out judge 一致性评分 (0-1) | 每轮辩论 |
| **D2** | Acuity (辨识力) | 信号-噪音辨识能力 | Spearman ρ(PnL,信息) − ρ(PnL,噪音) | 每周一 |
| **D3** | Composure (镇定度) | 波动率-过度反应控制 | stop~ADX 回归分析 | ≥5轮辩论自动点亮 |
| **D4** | Discipline (纪律) | 规则自检遵守度 | RuleChecker 检查 R13/R14/R-resonance | 每周一 |
| **D5** | Reliability (可靠性) | 闭环完成率 | 剔除陈旧基础设施失败后的 fresh 完成率 | 每周一 |

### 2.2 评分流程

```
每周一 08:30 (scheduler 触发)
    │
    ▼
apm_scorecard.py
    │
    ├─ 读取 memory/debate_journal.json (辩论记录)
    ├─ 读取 memory/execution_followup.json (验证结果)
    ├─ 读取 memory/validation_stats.json (统计)
    │
    ├─ D1: 对每轮辩论, 检查 held_out_judge.coherence_score
    │      → 计算平均一致性
    │
    ├─ D2: 对已验证裁决, 计算 Spearman 秩相关
    │      → 成本感知 PnL (COST_BPS=2.0)
    │      → ρ(PnL, 信息信号) − ρ(PnL, 噪音信号)
    │
    ├─ D3: 回归分析 stop_distance ~ ADX
    │      → 检查高波动时是否过度反应
    │
    ├─ D4: RuleChecker 检查每条裁决
    │      → R13: ADX≥70 仓位上限 3.5%
    │      → R14: ADX≥50 仓位上限 2.5%
    │      → R-resonance: 多共振仓位上限
    │
    ├─ D5: 统计闭环完成率
    │      → 剔除 >14天 的陈旧失败
    │      → fresh_completion_rate = completed / (completed + fresh_failed)
    │
    └─ 输出: memory/apm_scorecard.json
```

### 2.3 评分卡输出格式

```json
{
  "generated_at": "2026-07-10 08:30",
  "period": "2026-07-03 ~ 2026-07-09",
  "scores": {
    "D1_coherence": 0.82,
    "D2_acuity": 0.15,
    "D3_composure": null,
    "D4_discipline": 0.95,
    "D5_reliability": 0.88
  },
  "details": {
    "D1": {"avg_coherence": 0.82, "total_debates": 12},
    "D2": {"spearman_info": 0.34, "spearman_noise": 0.19, "net": 0.15},
    "D3": {"status": "not_lit", "reason": "debates < 5"},
    "D4": {"violations": 1, "total_checked": 20, "rules_checked": ["R13", "R14", "R-resonance"]},
    "D5": {"completed": 15, "fresh_failed": 2, "stale_failed": 1}
  }
}
```

### 2.4 代码位置

| 组件 | 文件 | 说明 |
|:-----|:-----|:-----|
| 评分卡主逻辑 | `scripts/apm_scorecard.py` | 五轴计算 + 输出 |
| D2 成本感知 PnL | `scripts/validate_verdicts.py` | `COST_BPS=2.0` 参数 |
| D4 纪律钳制 | `scripts/enforce_discipline.py` | R13/R14/R-resonance 仓位上限 |
| held-out judge | `agents/futures-judge-heldout.md` | D1 一致性审计 Agent |
| 种子回填 | `scripts/memory_writer.py` | `compute_heldout_coherence()` 确定性 rubric |

## 3. 统一日志框架

### 3.1 日志架构

```
unified_logger.py
    │
    ├─ 日志级别: DEBUG < INFO < WARNING < ERROR < CRITICAL
    │   ↓ 环境变量 FDB_LOG_LEVEL 控制 (默认 INFO)
    │
    ├─ 日志格式: [时间] [FDB.模块名] [级别] 消息
    │   例: [2026-07-10 14:30:15] [FDB.scan_all] [INFO] 扫描开始
    │
    ├─ 输出目标:
    │   ├─ 控制台 (StreamHandler → stdout)
    │   └─ 文件 (FileHandler → ~/Documents/WorkBuddy/Logs/fdb_{date}.log)
    │
    ├─ Logger 缓存: _loggers dict (避免重复创建)
    │
    └─ 传播控制: logger.propagate = False (不传播到根 logger)
```

### 3.2 使用方式

```python
from scripts.unified_logger import get_logger

logger = get_logger("scan_all")
logger.info("扫描开始")
logger.warning("数据延迟")
logger.error("连接失败", exc_info=True)
```

### 3.3 日志文件清单

| 日志文件 | 路径 | 写入者 | 用途 |
|:---------|:-----|:-------|:-----|
| `fdb_{date}.log` | `~/Documents/WorkBuddy/Logs/` | `unified_logger.py` | 统一日志 (所有模块) |
| `pipeline_{date}.log` | `Commodities/Reports/.../` | `pipeline/runner.py` | 流水线执行日志 |
| `scheduler.log` | `scheduler/` | `scheduler/engine.py` | 调度器心跳日志 |
| `daemon.log` | `scheduler/` | `bootstrap.py daemon` | 守护进程输出 |

### 3.4 已知不一致

> **Gap**: `pipeline/runner.py` 使用 `logging.basicConfig()` 直接配置日志，而非使用 `unified_logger.py`。导致流水线日志与统一日志格式不一致。
>
> **改进建议**: 迁移 `pipeline/runner.py` 到 `unified_logger.get_logger("auto_pipeline")`。

## 4. 失败模式聚类 (Telescope)

### 4.1 聚类流程

```
每周一 08:00 (scheduler 触发)
    │
    ▼
cluster_failures.py
    │
    ├─ 读取 memory/execution_followup.json (所有历史裁决)
    │
    ├─ 7 维特征提取:
    │   1. direction (多/空)
    │   2. ADX 区间 (<25 / 25-50 / 50-70 / >70)
    │   3. RSI 区间 (<30 / 30-70 / >70)
    │   4. 产业链 (黑色/有色/能化/农产品/贵金属)
    │   5. signal_type (breakout/pullback/gap)
    │   6. confidence (高/中/低)
    │   7. position_pct (≤2% / 2-5% / >5%)
    │
    ├─ 聚类分析:
    │   ├─ 单维聚类 (7个维度各聚类)
    │   ├─ 二维交叉聚类 (21种组合)
    │   └─ 品种×方向聚类
    │
    ├─ 规则关联诊断:
    │   └─ 将聚类结果与 judgment_revisions.md 中的 R 规则关联
    │
    ├─ 严重度评估:
    │   ├─ 样本数 ≥5 且胜率 <40% → 🔴 高严重度
    │   ├─ 样本数 ≥3 且胜率 <50% → 🟡 中严重度
    │   └─ 其他 → 🟢 低严重度
    │
    └─ 输出: memory/failure_clusters.json
```

### 4.2 CLI 接口

```bash
python scripts/cluster_failures.py                    # 默认运行
python scripts/cluster_failures.py --min-cases 5      # 最小样本数
python scripts/cluster_failures.py --min-winrate 40   # 最小胜率阈值
```

## 5. ViBench 历史回放

### 5.1 回放架构

```
benchmarks/test_cases.json (金标准集, 20案例)
    │
    ▼
run_benchmark.py --replay
    │
    ├─ 按 (round_id, 品种) 加载历史场景
    │
    ├─ replay_harness.py (确定性回放引擎)
    │   ├─ 重放研究员资料
    │   ├─ 重放辩手论据
    │   ├─ 重放闫判官裁决
    │   └─ 计算 coherence_weighted_accuracy
    │
    └─ 输出: benchmarks/benchmark_replay.json
```

### 5.2 CLI 接口

```bash
python scripts/run_benchmark.py --build    # 构建测试集
python scripts/run_benchmark.py --run      # 运行基准
python scripts/run_benchmark.py --replay   # 回放历史
```

## 6. 自改进脚手架

### 6.1 改进闭环

```
Stage 1: APM-CS 评分卡 (apm_scorecard.py)
    │ → 识别弱轴 (D1-D5 中低于阈值的)
    │
Stage 2: 失败聚类 (cluster_failures.py)
    │ → 识别失败模式
    │
Stage 3: ViBench 回放 (run_benchmark.py)
    │ → 识别回归
    │
    ▼
self_improve.py (自改进脚手架)
    │
    ├─ 消费 APM + 聚类 + 基准 三源数据
    │
    ├─ 生成改进建议 (proposal):
    │   ├─ "D2 Acuity 偏低, 建议增加噪音过滤阈值"
    │   ├─ "黑色系空单胜率 <40%, 建议增加 ADX>50 过滤"
    │   └─ "R14 规则违反 1 次, 建议收紧仓位上限"
    │
    └─ 输出: memory/self_improve_log.json
        (proposal 模式: 不直接改 Agent, 需人工审核后部署)
```

### 6.2 Proposal 格式

```json
{
  "timestamp": "2026-07-10 09:00",
  "source": "apm+cluster+benchmark",
  "proposals": [
    {
      "id": "P-2026-0710-001",
      "severity": "high",
      "axis": "D2",
      "finding": "Acuity net=0.15, 低于阈值0.20",
      "suggestion": "增加噪音信号过滤, 提高信息信号权重",
      "affected_agents": ["futures-judge"],
      "status": "pending_review"
    }
  ]
}
```

## 7. 辩论归档

### 7.1 归档内容

`debate_archiver.py` 在每轮辩论完成后归档：

| 归档项 | 存储位置 | 格式 |
|:-------|:---------|:-----|
| 辩论日志 | `memory/debate_journal.json` | JSON (最多500条) |
| 辩论索引 | `memory/debates/INDEX.md` | Markdown 表格 |
| 事故记录 | `memory/incidents.md` | Markdown |

### 7.2 归档特性

- **幂等**: 相同 round_id 不重复写入
- **容错**: 写入失败不阻断辩论流程
- **截断**: journal 保留最近 500 条
- **双写**: canonical (`memory/debate_journal.json`) + 副本 (`skills/memory/debate_journal.json`)

### 7.3 竞态安全写入

`memory_writer.py` 解决 10 个 Agent 并发写入问题：

| 机制 | 实现 |
|:-----|:-----|
| 独立文件 | 每个 Agent 写入 `memory/{round_id}/{agent_id}_{type}.json` |
| SQLite 备份 | 同时写入 `memory/{round_id}/debate_journal.db` (支持并发) |
| 线程锁 | `_journal_lock` 保护 journal 的读-改-写操作 |
| 完整性校验 | `validate()` 检查缺失/重复/损坏 |
