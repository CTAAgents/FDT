# Loop Engineering 操作手册

> **适用系统**: FDT v8.10.0+ | **版本**: v1.0 | **最后更新**: 2026-07-18
>
> 本文档面向**量化运维人员**，涵盖自动化量化生产线的日常操作、故障处理和状态检查。

---

## 目录

1. [系统架构速览](#1-系统架构速览)
2. [调度时间线](#2-调度时间线)
3. [L0：人类设定层](#3-l0人类设定层)
4. [L1：Meta-Loop 知识补给](#4-l1meta-loop-知识补给)
5. [L2：Evolution Loop 因子演化](#5-l2evolution-loop-因子演化)
6. [L3：Portfolio Loop 组合构建](#6-l3portfolio-loop-组合构建)
7. [监控与运维](#7-监控与运维)
8. [熔断处理](#8-熔断处理)
9. [故障处理](#9-故障处理)
10. [FAQ](#10-faq)
11. [文件索引](#11-文件索引)

---

## 1. 系统架构速览

```
时间线                    Loop 层                   产出物
─────────                ────────                 ──────
周日 30min                 L0 人类设定           program.md
                         (编辑 YAML 配置)
                             │
每日 05:00-06:00            L1 Meta-Loop          factor_pool.json
                         (感知+分析+Bootstrap)     l1_injected/
                             │
每日 09:00-15:00           FDT 辩论系统           辩论报告
                         (8策略+P4辩论)            裁决结果
                             │
每日 20:00-06:00           L2 Evolution Loop      精英因子
                         (宏微演化+评估)         经验链轨迹
                             │
每周五 15:30-16:30         L3 Portfolio Loop      current_combo.json
                         (合成+正交化+构建)       factor_weights.json
                                                    Agent 优化建议
```

### 关键文件位置

| 内容 | 路径（相对 FDT 根） |
|------|-------------------|
| 人类设定 | `memory/program.md` |
| L1 状态 | `memory/meta_loop/state.json` |
| L1 备份 | `memory/meta_loop/state.json.backup` |
| 种子池 | `memory/knowledge/factors/factor_pool.json` |
| L2 状态 | `memory/evolution/state.json` |
| L2 备份 | `memory/evolution/state.json.backup` |
| 精英因子 | `memory/knowledge/factors/elite/` |
| 经验链 | `memory/evolution/success/` + `failure/` |
| L3 状态 | `memory/portfolio/state.json` |
| 组合 | `memory/portfolio/current_combo.json` |
| 权重 | `memory/portfolio/factor_weights.json` |
| Agent 建议 | `memory/portfolio/agent_proposals/` |
| 调度状态 | `memory/schedule_state.json` |

---

## 2. 调度时间线

| 时间 | 任务 | 窗口 | 说明 |
|:----:|:----|:----:|:-----|
| 05:00 | L1 Meta-Loop | 1h | 市场感知 + Bootstrapping + debate 分析 |
| 09:00 | FDT 辩论 | 6h | 8 策略扫描 + P4 三步骤辩论（工作日） |
| 15:00 | 收盘 | — | 数据就绪 |
| 15:30 (周五) | L3 Portfolio Loop | 1h | 信号合成 + 组合构建 |
| 20:00 | L2 Evolution Loop | 4h | 因子宏微协同演化 + 评估 |
| 23:05 | 自动发布 | 5min | 版本号自增 + Git 推送 |

所有调度通过 `scheduler/engine.py` 守护进程运行，或通过 WorkBuddy Automation 触发。

---

## 3. L0：人类设定层

### 3.1 你的工作

每周一次，编辑 `memory/program.md`，设定本周的量化生产参数。

### 3.2 快速开始

```bash
# 初始化默认模板（首次使用）
python -c "from loop_engine.program import init_program; init_program('memory/program.md')"

# 查看当前配置
python -c "from loop_engine.program import load_program; c=load_program(); print(c)"
```

### 3.3 配置项说明

| 配置 | 示例 | 作用域 |
|:-----|:-----|:-------|
| `market_regime` | 震荡偏多 | L2 因子偏好导向 |
| `factor_preference.priority_1` | 低波因子 | L2 宏观演化方向 |
| `factor_preference.avoid` | 趋势动量因子 | L2 宏观演化排除 |
| `agent_llm.default` | deepseek-chat | 全局 LLM 模型 |
| `agent_llm.overrides` | bullish: claude-4 | 逐 Agent 独立模型 |
| `budget.daily_tokens` | 50000 | L1 每日 token 预算 |
| `budget.nightly_tokens` | 200000 | L2 每夜 token 预算 |
| `budget.weekly_portfolio` | 100000 | L3 每周 token 预算 |
| `risk_constraints` | min_sharpe: 1.5 | 三级 Verifier 默认阈值 |

### 3.4 熔断恢复确认

熔断发生后，程序.md 底部的复选框必须手动确认：

```markdown
- [x] L1 熔断已审查（原因: 低质量候选）
- [x] L2 熔断已审查（原因: 连续低 IC）
- [ ] L3 熔断已审查（原因: ________）
- [x] program.md 已更新
- [x] 确认恢复运行
```

只有全部勾选后，系统才会在下次调度时解除暂停状态。

---

## 4. L1：Meta-Loop 知识补给

### 4.1 职责

每日 05:00 自动执行，从外部市场感知和辩论质量反馈中生成因子候选，注入种子池。

### 4.2 手动触发

```bash
# 标准模式（带 LLM Bootstrapping）
python -m loop_engine.meta_loop --once

# 限制 bootstrapping 数量（调试用）
python -m loop_engine.meta_loop --once --max-bootstraps=2

# 指定目录
python -m loop_engine.meta_loop --once --memory-dir=memory/meta_loop --factor-pool=memory/knowledge/factors/factor_pool.json
```

### 4.3 5 步流程

```
Step 1: 感知        f10/web_collector 拉取 62 品种市场快照
Step 2: 质量分析    DebateQualityAnalyzer 识别 4 种缺口
                    (bullish_weak/bearish_weak/insufficient_rounds/no_debate)
Step 3: Bootstrapping  3 模板 + LLM 注入 → 候选因子
Step 4: L1 Verifier   economic_logic>=2/4 + is_executable + not_duplicate
Step 5: 注入         factor_pool.json + seed_pool.inject_from_l1()
```

### 4.4 环境变量

| 变量 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `FDT_L1_MAX_BOOTSTRAPS` | 5 | 单次最大候选数 |
| `FDT_L1_MEMORY_DIR` | memory/meta_loop | L1 状态目录 |
| `FDT_L1_FACTOR_POOL` | memory/knowledge/factors/factor_pool.json | 种子池路径 |
| `FDT_L1_INJECT_DIR` | memory/knowledge/factors/l1_injected | 注入目录 |

### 4.5 熔断条件

| 条件 | 阈值 | 恢复 |
|:-----|:-----|:-----|
| Token 超额 | > 2x daily_limit (100K) | 人类审查后恢复 |
| 失败率 | > 95% | 审查 LLM 输出质量 |
| 连续低质量 | > 5 次 | 调整 program.md 因子偏好 |

---

## 5. L2：Evolution Loop 因子演化

### 5.1 职责

每日 20:00 自动执行，从种子池读取 pending 因子，执行宏微协同演化 + 三级评估链，产出精英因子。

### 5.2 手动触发

```bash
# 标准模式
python -m loop_engine.evolution_loop --once

# 限制演化代数（调试用）
python -m loop_engine.evolution_loop --once --max-generation=5

# 查看状态
python -c "from loop_engine.state import EvolutionStateManager; m=EvolutionStateManager(); s=m.load_or_init(); print(s)"
```

### 5.3 流程

```
种子因子 → [for generation 0..MAX_GEN]:
  ├─ macro_evolution  (LLM 改逻辑)
  ├─ micro_evolution  (optuna 100 trials)
  ├─ evaluation_chain (Level 1 回测 → Level 2 经济逻辑 → Level 3 多重检验)
  ├─ verifier.check() (锁定判定不可修改)
  └─ experience_chain (记录成功/失败轨迹)
                       ↓
             精英因子 → elite/
```

### 5.4 三级评估链

| 级别 | 指标 | 阈值 |
|:-----|:-----|:-----|
| Level 1 | IC/夏普/单调性/样本外 | IC>0.03, 夏普>1.5, OOS≥30% |
| Level 2 | 经济逻辑四维 | ≥3/4 维度达标 |
| Level 3 | Bonferroni/FDR/t 统计 | α/n, q<0.05, t>3.0 |

### 5.5 环境变量

| 变量 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `FDT_L2_MAX_GENERATION` | 50 | 最大演化代数 |
| `FDT_L2_MEMORY_DIR` | memory/evolution | 状态目录 |
| `FDT_L2_ELITE_DIR` | memory/knowledge/factors/elite | 精英库 |

### 5.6 熔断条件

| 条件 | 阈值 |
|:-----|:-----|
| Token 超额 | > 2x nightly (400K) |
| 连续低 IC | > 3 代 IC < 0.01 |
| 失败率 | > 90% |
| 状态卡死 | 24h 未更新 |

---

## 6. L3：Portfolio Loop 组合构建

### 6.1 职责

每周五 15:30 自动执行，从精英因子库读取因子，执行信号合成 + 正交化 + 组合构建，注入 FDT。

### 6.2 手动触发

```bash
# 等权模式（默认）
python -m loop_engine.portfolio_loop --once

# 夏普加权模式
python -m loop_engine.portfolio_loop --once --mode=sharpe_weight

# 指定目录
python -m loop_engine.portfolio_loop --once --elite-dir=memory/knowledge/factors/elite
```

### 6.3 流程

```
精英因子
  │
  ├─ Step 1: 信号合成 (synthesize_signals)
  │   → 等权/夏普加权
  ├─ Step 2: 因子正交化 (orthogonalize_factors)
  │   → 剔除相关性 > 0.7
  ├─ Step 3: 衰减检验 (decay_test)
  │   → 6 月滚动窗口，衰减 > 30% 剔除
  ├─ Step 4: 组合构建 (build_combo)
  │   → 权重归一化 + 组合指标
  ├─ Step 5: L3 Verifier (5 维度判定)
  │   → 夏普>2.0 / 相关性<0.3 / 换手率<50%
  └─ Step 6: 注入 FDT (inject_to_fdt)
      → combo.json + factor_weights.json + agent_proposals/
```

### 6.4 产出物

| 文件 | 格式 | 说明 |
|:-----|:-----|:-----|
| `current_combo.json` | JSON | 组合完整定义（含各因子权重） |
| `factor_weights.json` | JSON | 可直接被 multi_factor_strategy.py 加载的权重配置 |
| `agent_proposals/*.json` | JSON | Agent 优化建议（draft 状态，需人工确认） |

### 6.5 环境变量

| 变量 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `FDT_L3_MODE` | equal_weight | 合成模式（equal_weight/sharpe_weight） |
| `FDT_L3_MEMORY_DIR` | memory/portfolio | 状态目录 |
| `FDT_L3_ELITE_DIR` | memory/knowledge/factors/elite | 精英库 |

---

## 7. 监控与运维

### 7.1 快速状态检查

```bash
# 查看三层循环状态
python -m loop_engine.monitor status

# JSON 格式（供脚本/仪表盘消费）
python -m loop_engine.monitor status --json
```

输出示例：

```
======================================================================
  Loop Engineering — 状态总览 @ 2026-07-18T14:30:00
======================================================================
Loop  状态               运行ID                         Token      已过(h)  健康
----------------------------------------------------------------------
L1    🟢 running        run_3f9a2b1c_20260718T050030   5000/50000  0.5h    OK
L2    🟢 completed      run_8c4d7e2f_20260717T200000   185000/200K 18.0h   OK
L3    🟡 unknown        -                              0/100000    0.0h    OK
----------------------------------------------------------------------
```

### 7.2 状态解读

| 状态 | 含义 | 行动 |
|:-----|:-----|:-----|
| `running` | 正在执行 | 等待完成 |
| `completed` | 上次执行成功 | 无操作 |
| `paused` | 被暂停 | 检查 last_error |
| `circuit_broken` | 熔断触发 | 紧急处理（见 §8） |
| `unknown` | 从未运行过 | 等待首次调度或手动触发 |

### 7.3 查看关键产出

```bash
# 查看当前因子池
cat memory/knowledge/factors/factor_pool.json | python -m json.tool

# 查看 elite 因子列表
ls memory/knowledge/factors/elite/

# 查看当前组合
cat memory/portfolio/current_combo.json | python -m json.tool

# 查看待处理 Agent 建议
ls memory/portfolio/agent_proposals/

# 查看经验链摘要
cat memory/evolution/experience_chain.md

# 查看调度触发器状态
cat memory/schedule_state.json | python -m json.tool
```

### 7.4 日志查看

```bash
# L1 日志
python -m loop_engine.meta_loop --once 2>&1 | tee /tmp/l1_log.txt

# L2 日志
python -m loop_engine.evolution_loop --once 2>&1 | grep -E "\[L2\]|ERROR|WARNING"

# L3 日志
python -m loop_engine.portfolio_loop --once --mode=sharpe_weight 2>&1
```

---

## 8. 熔断处理

### 8.1 熔断识别

```bash
# 快速检查是否有熔断
python -m loop_engine.monitor status | grep circuit_broken

# 查看详细原因
python -c "
from loop_engine.monitor import check_all
s = check_all()
for l in s.loops:
    if l.status == 'circuit_broken':
        print(f'{l.name}: {l.last_error}')
"
```

### 8.2 恢复步骤

```
Step 1: 读取 last_error 确认熔断原因
Step 2: 检查经验链/日志找出根因
  ├─ Token 超限 → 检查 program.md 预算配置
  ├─ 连续低质量 → 检查 LLM 输出/因子偏好
  └─ 失败率过高 → 检查 Verifier 配置是否合理
Step 3: 编辑 program.md 底部勾选熔断恢复确认
Step 4: 系统会在下次调度时自动恢复
        或手动触发恢复:
        python -m loop_engine.portfolio_loop --once  (按需)
```

### 8.3 紧急手动重置

```bash
# 警告：这会导致当前运行状态丢失！
python -c "
from pathlib import Path
import shutil

# 备份损坏状态
for d in ['memory/meta_loop', 'memory/evolution', 'memory/portfolio']:
    p = Path(d)
    if (p / 'state.json').exists():
        shutil.copy2(str(p / 'state.json'), str(p / 'state.json.crashed'))
        (p / 'state.json').unlink()
    if (p / 'state.json.backup').exists():
        (p / 'state.json.backup').unlink()
print('状态已重置，下次运行将冷启动')
"
```

---

## 9. 故障处理

### 9.1 LLM 调用超时

**现象**: L1/L2 运行报 `timeout` 或 LLM API 错误
**处理**:
1. 检查 API Key 是否有效
2. 检查网络连通性
3. L1: 单次 Bootstrapping 失败不阻断其他步骤
4. L2: 当前因子跳过宏观演化，仅做微观演化

### 9.2 状态文件损坏

**现象**: `state.json` 解析失败
**处理**: 系统自动从 `.backup` 文件恢复。若 backup 也损坏：

```bash
# 手动检查
python -c "
import json
try:
    json.loads(open('memory/evolution/state.json').read())
    print('正常')
except Exception as e:
    print(f'损坏: {e}')
    # 检查 backup
    try:
        json.loads(open('memory/evolution/state.json.backup').read())
        print('backup 可用')
    except:
        print('backup 也损坏，需冷启动')
"
```

### 9.3 没有 elite 因子

**现象**: L3 运行报"无 elite 因子"
**处理**:
1. L2 需要运行至少 1 代才能产生精英因子
2. 检查 L2 种子池是否有 pending 因子
3. 手动运行 L2：`python -m loop_engine.evolution_loop --once --max-generation=5`

### 9.4 守护进程未运行

**现象**: 调度器不触发任何任务
**处理**:

```bash
# 启动守护进程
python bootstrap.py daemon

# 检查是否运行
cat memory/schedule_state.json | python -c "import json,sys; d=json.load(sys.stdin); print('心跳:', d.get('last_heartbeat','无'))"
```

### 9.5 factor_pool.json 为空

**现象**: L1 注入后 L2 没有可消费因子
**处理**:

```bash
# 查看 L1 状态
python -c "
from loop_engine.contracts import FactorPoolManager
m = FactorPoolManager()
pool = m.load_or_init()
print(f'pending: {pool.get(\"pending_count\", 0)}, total: {pool.get(\"total_count\", 0)}')
"
```

---

## 10. FAQ

### Q: 如何验证系统是否正常工作？

```bash
python -m pytest tests/loop_engine/ -q --no-cov 2>&1 | tail -1
# 输出: 197 passed → 正常
```

### Q: 如何查看某个因子的详细信息？

```bash
ls memory/knowledge/factors/elite/fct_*.json | head -1 | xargs python -m json.tool
```

### Q: L3 如何注入 multi_factor_strategy.py？

L3 产出 `factor_weights.json`，格式如下：

```json
{
  "version": "8.10.0",
  "weights": {
    "动量因子": 0.25,
    "波动率回归": 0.20,
    "持仓量变化": 0.15
  },
  "combo_sharpe": 2.1
}
```

目前需要人工或脚本将权重注入策略配置。后续版本会实现自动化注入。

### Q: 监控面板在哪里？

当前提供 CLI 监控（`monitor status --json`），可配合任意 JSON 消费工具做仪表盘。

### Q: 如何调整熔断阈值？

编辑 `loop_engine/contracts.py` 中的 `DEFAULT_*_CONFIG` 常量，然后重启调度器。

### Q: 长期不更新 program.md 会怎样？

超过 14 天未更新时，`monitor status` 会标记告警。Verifier 不强制阻断，但建议每周维护。

---

## 11. 文件索引

### 核心代码

| 文件 | 行数 | 职责 |
|:-----|:-----|:-----|
| `loop_engine/meta_loop.py` | ~1160 | L1 Meta-Loop 主循环 |
| `loop_engine/evolution_loop.py` | ~400 | L2 Evolution Loop 主循环 |
| `loop_engine/portfolio_loop.py` | ~600 | L3 Portfolio Loop 主循环 |
| `loop_engine/contracts.py` | ~560 | 全部三层 TypedDict 契约 |
| `loop_engine/factor_program.py` | ~300 | 安全沙箱 + 因子编译 |
| `loop_engine/program.py` | ~200 | L0 program.md 解析器 |
| `loop_engine/monitor.py` | ~170 | 状态监控 CLI |
| `loop_engine/state.py` | ~230 | L2 状态管理 + trace_id |
| `loop_engine/seed_pool.py` | ~400 | 种子池 + L1 注入 |
| `loop_engine/evaluation_chain.py` | ~360 | 三级评估链 |
| `loop_engine/experience_chain.py` | ~280 | 经验链存储 |
| `loop_engine/verifier.py` | ~150 | L2 Verifier 锁定协议 |
| `loop_engine/macro_evolution.py` | ~200 | 宏观演化（LLM） |
| `loop_engine/micro_evolution.py` | ~200 | 微观演化（optuna） |

### 测试

| 文件 | 用例数 | 覆盖 |
|:-----|:-------|:-----|
| `tests/loop_engine/test_meta_loop.py` | 51 | L1 全部 |
| `tests/loop_engine/test_evolution_loop.py` | 22 | L2 主循环 |
| `tests/loop_engine/test_portfolio_loop.py` | 34 | L3 全部 |
| `tests/loop_engine/test_program.py` | 16 | L0 解析器 + 监控 |
| 其余 7 个 L2 测试文件 | 74 | L2 子模块 |
| **合计** | **197** | **全部通过** |

### 调度

| 文件 | 内容 |
|:-----|:-----|
| `scheduler/tasks.py` | 11 个注册任务（含 l1_meta_loop / l2_evolution_loop / l3_portfolio_loop） |
| `scheduler/triggers.py` | 16 个触发器（含 05:00 / 20:00 / 周五 15:30） |

---

*本文档结束 | 更多信息请参考 [LOOP_ENGINEERING_INTEGRATION_PLAN.md](LOOP_ENGINEERING_INTEGRATION_PLAN.md)*
