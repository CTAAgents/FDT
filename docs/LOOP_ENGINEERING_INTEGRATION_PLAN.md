# 自动化量化生产线：Loop Engineering + Agentic Factor Investing + FactorEngine 整合方案

> **版本**: v1.2 | **日期**: 2026-07-18 | **状态**: 全部落地实施完毕（Phase 1-4 ✅）

> **实施记录**:
> - v1.1 (2026-07-17): 初始整合方案设计
> - v1.2 (2026-07-18): 全部 Phase 实施完毕 — Phase 1 L2 Evolution Loop (96测试) + Phase 2 L1 Meta-Loop (51测试) + Phase 3 L3 Portfolio Loop (34测试) + Phase 4 人类退场 (16测试) = **197 测试全绿**
> **FDT 基线**: v8.9.1（3 步辩论 + 逐 Agent LLM 配置 + 近月基差降级 + web_collector F10 增强）
> **关联文档**: [FDT 架构](harness/01-architecture.md) | [阶段定义](harness/02-lifecycle.md) | [差距管理](harness/08-gap-analysis.md)

---

## 1. 背景与动机

### 1.1 现状分析

FDT v8.9.1 关键能力：

- **10 Agent CTA 决策框架**（LangGraph 图编排 + 8 策略管线 + 多因子）
- **P4 三步骤交叉质询**：`bullish_v1`（立论）→ `bearish_v1`（质疑）→ `bullish_rebuttal`（反驳），`debate_round` 计数器持久化
- **逐 Agent LLM 配置**：通过 `FDT_LLM_<AGENT_NAME>_*` 环境变量独立指定各 Agent 的 API Key / Base URL / Model
- **F10 Web Collector**：新增强化宏观/基本面数据采集
- **近月代理基差降级**：100ppi 不可用时自动切换 TdxCollector 近月合约代理
- **115+ LangGraph 测试用例**（test_graph 19 + test_agents 56 + test_health 42 + 其余）
- **APScheduler 定时调度 + 5 层鲁棒防线**

### 1.2 核心瓶颈

| 瓶颈 | 表现 | 根因 |
|------|------|------|
| 因子发现低效 | 每周手动触发一次 | 缺乏自动化循环控制 |
| 知识注入空白 | 研报/宏观因子想法未被消化 | 无报告到因子的自动管道 |
| 组合更新滞后 | 多因子权重月度人工调参 | 无自动调整验证循环 |
| Agent 进化为零 | `evolve_agents.py` 有框架但手动运行 | 无 L0→Agent Prompt 的自动演化闭环 |

### 1.3 解决方案

| 框架 | 核心能力 | 填补的空白 |
|------|---------|-----------|
| agentic-factor-investing | 因子发现方法论、经济逻辑评估、过拟合防护 | 往哪个方向挖、挖到什么算好 |
| factorengine | 程序级因子、宏微协同演化、Bootstrapping | 怎么写因子代码、怎么演化 |
| Loop Engineering | 三层循环、Verifier 协议、状态文件、预算控制 | 怎么自动转起来、怎么停下来 |

---

## 2. 整体架构

```
L0: 人类设定层 — 每周 30 分钟写 program.md
    市场环境、因子偏好、Agent 配置、预算上限、风险约束
    ↓
L1: Meta-Loop — 知识补给（每日 09:00）
    agentic感知(f10 web_collector + FDC) + factorengine Bootstrapping → 种子因子
    fdt_langgraph: 每轮 debate 的 6 维度论证框架自动录入经验链
    Verifier: 经济逻辑 ≥ 2/4 | Stop: 5个新因子 | Budget: 50K tokens/天
    ↓
L2: Evolution Loop — 因子演化（夜间 20:00-06:00）
    factorengine宏观演化(LLM改逻辑) → 微观演化(贝叶斯调参) → agentic三级评估链
    精英因子自动注入 multi_factor_strategy.py 配置
    Verifier: IC>0.03 AND 夏普>1.5 AND t>3.0 AND 经济逻辑≥3/4
    Stop: IC>0.08 OR 50代 OR 预算耗尽 | Budget: 200K tokens/夜
    ↓
L3: Portfolio Loop — 组合构建（每周五 15:30）
    信号合成 → 因子正交化 → 组合构建 → 衰减检验 → 注入 FDT
    同步更新 FDT 策略权重 + Agent 系统提示词（debate_round heatmap）
    Verifier: 夏普>2.0, 相关性<0.3, 换手率<50%/月
    Stop: 指标达标 OR 3次无提升 | Budget: 100K tokens/周
    ↓
FDT v8.9.1 CTA 决策系统（消费层）
    新因子注入 multi_factor_strategy.py → 8 策略并行扫描 → P4 三步骤交叉质询
    (bullish_v1 debate_round=1 → bearish_v1 debate_round=2 → rebuttal debate_round=3)
    → P5 裁决+风控+交易参数 → P6 报告+CTP 信号输出
    → T+1 验证反馈回 L0 program.md → 闭环完成
```

**v1.1 更新**: 新增 F10 web_collector 作为 L1 数据源、debate_round 作为质量反馈信号、per-Agent LLM 配置支持。

---

## 3. L0：人类设定层

人类只做一件事：每周写一份 program.md。

```yaml
market_regime: 震荡偏多
factor_preference:
  priority_1: 低波因子
  priority_2: 期限结构因子
  avoid: 趋势动量因子
agent_llm_config:                  # 新增: v8.9.1 per-Agent LLM 独立配置
  bullish_analyst:
    model: claude-sonnet-4         # 辩论 Agent 用强模型
  bearish_analyst:
    model: claude-sonnet-4
  judge:
    model: deepseek-chat           # 裁决 Agent 用本地模型
  default: deepseek-chat           # 其余 Agent 走默认
budget:
  daily_tokens: 50000
  nightly_tokens: 200000
  max_tokens_per_factor: 10000
risk_constraints:
  max_drawdown: 0.20
  max_turnover_per_month: 0.50
  min_sharpe: 1.5
  min_economic_logic_score: 3
```

---

## 4. L1：知识补给 Meta-Loop

**触发**：每日 09:00 开盘前，Schedule 驱动。

**流程**：
1. **agentic 感知模块** → FDC + `f10/web_collector`（新增） → 62 品种市场快照
2. **factorengine Bootstrapping** → 提取Agent / 验证Agent / 代码生成Agent → 新因子候选
3. **agentic 记忆模块** → 检索历史因子模式 + L2 经验链
4. **fdt_langgraph 辩论质量分析**（新增 v1.1）：读取昨日各品种 `debate_round` 数据，识别论证薄弱维度 → 反馈至种子因子优先级
5. 更新 `factor_pool.json`

**Verifier**：`economic_logic_score >= 2/4 AND is_executable AND not_duplicate`

**状态文件**：`memory/knowledge/factor_pool.json`

```json
{
  "seeds": [{
    "id": "seed_001", "name": "波动率锥斜率",
    "source": "研报-中信期货",
    "debate_gap": "期限结构维度弱",  // 新增: L1 从 debate_round 数据中识别的论证缺口
    "economic_logic": {"理论":4,"行为":2,"微观":3,"可执行":4},
    "priority": "high", "status": "pending"
  }]
}
```

---

## 5. L2：因子演化 Inner Loop

**触发**：每日 20:00 夜盘前，种子池 ≥ 3 个 pending 因子。

### 5.1 宏观演化（factorengine Evolution）

LLM 读取经验链 + program.md + **L1 debate_gap 标签**（新增 v1.1） → 生成因子逻辑修改 → 编译验证。

### 5.2 微观演化（贝叶斯优化）

optuna 100 trials 搜索参数空间 → 连续 20 次无提升跳出。

**三层分离**：LLM 只管逻辑，CPU 只管参数。

### 5.3 agentic 三级评估链

- Level 1 回测验证：IC>0.03? 夏普>1.5? 单调性? 样本外≥30%?
- Level 2 经济逻辑：四维评分 ≥ 3/4
- Level 3 多重检验：FDR + Bonferroni

### 5.4 经验链

成功记入 `memory/evolution/success/`，失败记入 `memory/evolution/failure/`。

**新增 v1.1**：L2 产出精英因子同时更新 `multi_factor_strategy.py` 配置，通过 L3 正式注入前先占位。

---

## 6. L3：组合构建 Portfolio Loop

**触发**：每周五 15:30，或精英因子池新增 ≥ 3 个。

**流程**：
1. agentic 信号合成（等权/夏普加权/LightGBM 对比选最优）
2. factorengine 因子正交化（剔除相关性 > 0.7）
3. agentic 组合构建（十分位 + 多空 + 成本 10-20bps + 换手率 < 50%）
4. 衰减检验（6 个月滚动窗口，衰减 > 30% 剔除）
5. 注入 FDT：

**新增 v1.1** L3 同时输出两份配置：
- **因子组合** → `multi_factor_strategy.py` 权重配置
- **Agent 优化建议** → 基于 `debate_round` 和 `evolve_agents.py` 框架，每两周自动生成 Agent prompt 改进，通过 `FDT_LLM_<AGENT_NAME>_*` 环境变量切换实验模型

**Verifier**：`夏普>2.0 AND 相关性<0.3 AND 换手率<50%/月 AND 衰减率<30%`

---

## 7. 与 FDT v8.9.1 的集成映射

| FDT 组件 | 角色 | 改造 |
|----------|------|------|
| auto_factor_mining.py | 被 L2 取代 | 保留备份 |
| multi_factor_strategy.py | L3 输出目标 | 新增配置接口（因子权重 + Agent 优化） |
| memory/knowledge/ | L1 种子池 + L2 经验链 | 扩展 evolution/portfolio/ |
| memory/debates/ | T+1 反馈源 | 新增 debate_round 解析 → L0 |
| fdt_langgraph/nodes.py | 三步骤辩论消费层 | `bullish_arguments`/`bearish_arguments` 读取适配 reducer list 格式 |
| fdt_langgraph/state.py | 新增 `debate_round` 字段 | 作为辩论质量反馈信号 |
| fdt_langgraph/agents.py | 逐 Agent LLM 配置 | L0 program.md 可直接控制各 Agent 模型 |
| futures_data_core/f10/web_collector.py | L1 感知层新数据源 | 新增宏观/基本面信号提取接口 |
| scheduler/engine.py | 共享调度 | 新增三个 Loop 任务 |
| scripts/evolve_agents.py | L3 Agent 自改进框架 | 接入 L3 管道代替手动运行 |

### 目录扩展

```
memory/
├── knowledge/factors/           # 新增
│   ├── elite/                   # L2 精英因子
│   ├── decayed/                 # L3 衰减因子
│   └── factor_pool.json         # L1 种子池
├── evolution/                   # 新增
│   ├── state.json               # 演化状态
│   ├── success/                 # 成功轨迹
│   ├── failure/                 # 失败轨迹
│   └── experience_chain.md      # 经验链摘要
├── portfolio/                   # 新增
│   ├── current_combo.json       # 当前组合
│   ├── history/                 # 历史快照
│   └── agent_proposals/         # 新增: Agent 优化建议
└── debates/                     # 不变，新增 debate_round 解析
```

---

## 8. Loop 协调与预算控制

### 时间窗口

```
05:00  L1 [05:00-06:00] 感知(f10 web + FDC) + 研报Bootstrapping + debate_round分析
09:00  FDT 开盘 → 8策略扫描 → P4三步骤辩论
15:00  收盘
15:30  L3 [周五 15:30-16:30] 组合构建 + Agent 优化建议生成
20:00  L2 [20:00-06:00] 整夜因子演化 + 经验链更新
```

### Token 预算

| Loop | 每日 | 每月 | 熔断 |
|------|------|------|------|
| L1 | 50K | 1.5M | 日超 100K |
| L2 | 200K | 6M | 夜超 400K |
| L3 | 100K(周五) | 400K | 周超 200K |
| **合计** | **250K** | **~7.5M** | **月超 10M** |

### 熔断条件

Token 超 2x / L2 连续 3 轮 IC<0.01 / L3 夏普 < 1.0 / FDC 全部降级。

---

## 9. 过拟合防护（7 道防线）

| # | 防线 | 来源 | 说明 |
|---|------|------|------|
| 1 | 经济正则化 | agentic | 因子必须有经济学解释，score≥3/4 |
| 2 | 统计门槛 | agentic | t>3.0, 夏普>1.5, 信息比率>0.5 |
| 3 | 多重检验校正 | agentic | Bonferroni + FDR |
| 4 | 衰减检验 | agentic | 滚动窗口，衰减率<30% |
| 5 | 时间隔离 | agentic | L2发现/L3筛选/FDT验证各用独立时段 |
| 6 | 经验链约束 | factorengine | LLM 每次读取失败轨迹 |
| 7 | 预算控制 | Loop Eng | 代数上限 + Token 上限 |

**新增 v1.1**：FDT v8.9.1 的逐 Agent LLM 配置允许 L3 在输出 Agent 优化建议时指定不同模型做 A/B 对比测试，减少单一模型偏差导致的过拟合。

---

## 10. 实施路线图

### Phase 1（已完成）：L2 Evolution Loop

**状态**: ✅ **v8.9.3 已落地**（2026-07-18） → v8.10.0 持续运行

- ✅ `loop_engine/` 包（12 模块）
- ✅ 96 个测试用例全绿
- ✅ scheduler 集成（每晚 20:00）
- ✅ Verifier 协议锁定 + 四重熔断
- ✅ 经验链 + 精英因子库

### Phase 2（已完成）：L1 Meta-Loop

**状态**: ✅ **v8.10.0 已落地**（2026-07-18）

- ✅ `loop_engine/meta_loop.py`（~1160 行）实现 5 步流程：感知→分析→Bootstrapping→Verifier→注入
- ✅ `contracts.py` L1 契约层（~160 行新增）
- ✅ `seed_pool.py` 新增 `inject_from_l1()` 注入接口
- ✅ 51 个测试用例全绿（8 个测试类）
- ✅ scheduler 集成（每日 05:00 TimeTrigger）

### Phase 3（已完成）：L3 Portfolio Loop

**状态**: ✅ **v8.10.0 已落地**（2026-07-18）

- ✅ `loop_engine/portfolio_loop.py`（~600 行）实现 5 步流程：信号合成→正交化→组合构建→衰减检验→注入 FDT
- ✅ `contracts.py` L3 契约层（6 个 TypedDict + 默认配置常量）
- ✅ L3 Verifier 锁定 5 维度判定：夏普>2.0/相关性<0.3/换手率<50%/衰减率<30%/最少 3 因子
- ✅ 34 个测试用例全绿（10 个测试类）
- ✅ scheduler 集成（每周五 15:30 TimeTrigger）
- ✅ Agent 优化建议生成 + factor_weights.json 注入

### Phase 4（已完成）：人类退场

**状态**: ✅ **v8.10.0 已落地**（2026-07-18）

- ✅ `loop_engine/program.py` — program.md 模板 + YAML 解析器 + `init_program()` 一键初始化
- ✅ `loop_engine/monitor.py` — `python -m loop_engine.monitor status` 统一状态查询（L1/L2/L3 健康检查）
- ✅ 熔断检测 + 过期状态告警（超过 24h 未更新）
- ✅ 逐 Agent LLM 配置切换（已由 FDT v8.9.1 架构原生支持）
- ✅ 16 个测试用例全绿
- ✅ `memory/program.md` 已初始化（默认模板，人类可编辑）

### 验证结果

```text
197 passed in 2.36s  ← loop_engine 全量测试
├── Phase 1 L2: 96 测试
├── Phase 2 L1: 51 测试
├── Phase 3 L3: 34 测试
└── Phase 4 L0: 16 测试
```

### 差距登记

| 差距项 | 优先级 | 计划 | 状态 |
|--------|--------|------|------|
| L2 演化引擎 | P0 | Phase 1 | ✅ 已关闭 (v8.9.3 → v8.10.0) |
| Bootstrapping | P1 | Phase 2 | ✅ 已关闭 (v8.10.0, G80) |
| 组合自动构建 + Agent 优化 | P1 | Phase 3 | ✅ 已关闭 (v8.10.0, G81) |
| debate_round 反馈解析 | P1 | Phase 2 | ✅ 已关闭 (v8.10.0) |
| 监控与 program.md | P2 | Phase 4 | ✅ 已关闭 (v8.10.0) |
| 经验链为空 | P2 | 持续积累 | ⏳ 运行时自动填充 |

---

## 11. 收益估算

| 指标 | 现状 | 改造后 | 提升 |
|------|------|--------|------|
| 因子发现速度 | 3-5/周 | 50-100/周 | **10-20x** |
| 平均 IC | 0.02-0.03 | 0.04-0.06 | **2x** |
| 组合更新 | 月度 | 周度 | **4x** |
| 知识注入 | 零 | 每日 5 份+debate_gap 标签 | **新增** |
| Agent 进化 | 手动运行 evolve_agents.py | L3 自动生成建议 | **新增能力** |
| 过拟合核查 | 人工 | 7 道自动 | **系统化** |
| 人工时间 | 5-10h/周 | 30min/周 | **10-20x 减少** |
| 理论组合夏普 | 1.5-2.0 | 2.5-3.0 | **+50%** |

月成本：LLM API ≈ $15-30，已有 GPU，存储 < 100MB。

---

## 12. 风险与债务管理

| 债务 | 表现 | 缓解 |
|------|------|------|
| 验证债 | 循环跑快了验证跟不上 | Verifier 版本管理 + 周审计 |
| 理解腐烂 | 代码量膨胀人脑追不上 | 每因子附经济逻辑文档 |
| 认知投降 | 系统可靠人不做判断 | L3 组合权重强制人审 |
| Token 失控 | 多层并发烧光预算 | 三层熔断 + 全局监控 |
| Agent 退化 | LLM 配置切换导致辩论质量下降 | debate_round 指标连续 3 日下降则回滚 |

---

## 13. 附录

### 参考文献

1. 0xCodila. *Loop Engineering: The Karpathy Method*. 2026.
2. Addy Osmani. *Loop Engineering: What It Is and When to Use It*. Google Chrome, 2026.
3. 数据STUDIO. *Agentic Loop Engineering 手册（17 种 Loop 原语）*. 2026.
4. Lin et al. *FactorEngine: Program-level Knowledge-Infused Factor Mining*. arXiv:2603.16365, 2026.
5. FDT v8.9.0/v8.9.1 版本历史（`docs/harness/07-operations.md`）

### 术语表

| 术语 | 定义 |
|------|------|
| Loop Engineering | 把人类敲回车自动化，让 Agent 自动循环运行 |
| 宏微协同演化 | LLM 改逻辑（宏观）+ 贝叶斯调参（微观），资源分离 |
| Bootstrapping | 金融报告到可执行因子程序的自动管道 |
| 经验链 | 变异轨迹记录，LLM 下一轮参考避免重复踩坑 |
| debate_round | FDT P4 辩论轮次计数器（v8.9.0），作为辩论质量指标 |
| Verifier 协议 | 锁定评估机制不可修改 |
| Orchestra 模式 | 多 Loop 共享 registry 协调碰撞 |

### 与 Harness 规范衔接

| 规范 | 对应 |
|------|------|
| 文档先行 | ✅ |
| 契约优先 | ✅ JSON Schema |
| 测试随重构 | ✅ Phase 1-4 先写测试（基线与 FDT 115+ 测试一致） |
| trace_id 全链路 | ✅ 每 Loop/因子有唯一 ID |
| 角色边界钉死 | ✅ L0-L3 职责分离 |
| 版本号纪律 | ✅ v1.1，对应 FDT v8.9.1 |
| 差距管理 | ✅ 已登记 |

---

*本文档结束 | v1.1 更新: FDT v8.9.1 三步骤辩论 + 逐Agent LLM配置 + F10 web_collector + debate_round 反馈*
