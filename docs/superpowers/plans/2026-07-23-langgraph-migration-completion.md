# LangGraph 迁移收尾实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭 G108，完成 FDT LangGraph 迁移的全部收尾工作 — 删除共存的老流水线、补齐 Master Graph 基础设施、清理所有遗留引用。

**Architecture:** 6 个独立 Task，按依赖顺序推进。Task 1-2 为代码变更，Task 3-4 为基础设施，Task 5 为文档同步，Task 6 为验证收口。每个 Task 生成独立可验证的变更。

**Harness 约束：** 每 Task 必须先更新对应 Harness 文档再写代码。commit 前通过 13 项检查清单。

**Gap 关联:** G108（08-gap-analysis.md 已登记）

**Trace ID 前缀:** `lg-migrate-{YYYYMMDD}`

---
## 任务拓扑

```
Task1 (pipeline退役) ──→ Task2 (Master心跳) ──→ Task3 (看门狗升级)
                                                      │
Task4 (外部脚本内联) ─────────────────────────────────┘
                                                      │
                              Task5 (文档同步) ←──────┘
                                      │
                              Task6 (验证收口)
```

---

### Task 1: pipeline/runner.py 强制退役

**说明:** 移除 `pipeline/runner.py` 以及 `FDT_USE_LANGGRAPH` A/B 切换机制。LangGraph 辩论图为唯一执行路径。pipeline/runner.py 中 `run_langgraph_pipeline()` 函数迁移到 `fdt_cli.py` 或 `fdt_langgraph/` 顶层的兼容入口。

**文件变更清单:**
- Modify: `pipeline/runner.py` — 在文件顶部添加 [DEPRECATED] 横幅，`main()` 中移除 subprocess 分支，仅保留 LangGraph 路径；或者**直接删除整个文件**，将 `run_langgraph_pipeline()` 迁移到 `fdt_cli.py`
- Modify: `fdt_cli.py` — 确保 `run` 子命令直接调用 LangGraph 而不经过 pipeline/runner.py（当前已如此，但需确认无间接依赖）
- Delete: `pipeline/quality_filter.py` — 检查是否被任何节点引用，如无则删除
- Delete: `pipeline/__init__.py`
- Check: 搜索 `FDT_USE_LANGGRAPH` 环境变量的所有引用，逐个清理

- [ ] **Step 1: 扫描 FDT_USE_LANGGRAPH 所有引用**

Run: `python -c "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import os; print(os.environ.get(\"FDT_USE_LANGGRAPH\", \"NOT_SET\"))'], capture_output=True, text=True)
print('FDT_USE_LANGGRAPH:', result.stdout.strip())
" 2>&1`

然后 Grep 代码库确认引用位置。

- [ ] **Step 2: 将 run_langgraph_pipeline() 迁移到 fdt_cli.py**

`fdt_cli.py` 的 `run_debate()` 已经直接调用 `build_debate_graph_no_checkpoint()`。确认 `pipeline/runner.py` 的 `run_langgraph_pipeline()` 无外部调用者。

```bash
grep -n "run_langgraph_pipeline\|from pipeline.runner\|import pipeline.runner" *.py scripts/*.py fdt_langgraph/*.py
```

预期：零引用（仅有 pipeline/runner.py 内部自引用）。

- [ ] **Step 3: 删除 pipeline/runner.py + pipeline/quality_filter.py + pipeline/__init__.py**

```bash
rm pipeline/runner.py pipeline/quality_filter.py pipeline/__init__.py
rm -rf pipeline/__pycache__
```

- [ ] **Step 4: 清理 FDT_USE_LANGGRAPH 环境变量引用**

搜索并移除 `FDT_USE_LANGGRAPH` 的读取/设置代码：

```bash
grep -rn "FDT_USE_LANGGRAPH" --include="*.py" --include="*.md" .
```

清理 hits（主要在 pipeline/runner.py 自身，以及 README.md 和 harness 文档中）。

- [ ] **Step 5: 更新 07-operations.md 中 LangGraph A/B 切换环境变量段落**

删除 `FDT_USE_LANGGRAPH` 相关描述行。

- [ ] **Step 6: 运行完整测试确认无破坏**

```bash
python -m pytest tests/ --ignore=tests/commodity-chain --ignore=tests/pipeline -x --tb=short -q
```

预期：所有测试通过。`tests/pipeline/` 目录也需要评估是否保留（测试 runner.py 的用例应该删除或重写为测试 LangGraph graph.py）。

- [ ] **Step 7: 评估并处理 tests/pipeline/ 目录**

```bash
ls tests/pipeline/
```

如果测试用例全是 runner.py 的，直接删除整个目录。如果有可迁移到 LangGraph 测试的，标记迁移。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(v9.19.0): pipeline/runner.py 强制退役，LangGraph 为唯一辩论执行路径

- 删除 pipeline/runner.py、quality_filter.py、__init__.py
- 清理 FDT_USE_LANGGRAPH A/B 切换机制
- 删除 tests/pipeline/（旧 pipeline 测试）
- 清理 README.md / 07-operations.md 中 A/B 切换描述
- G108 Task 1/6"
```

---

### Task 2: Master Graph 心跳文件

**说明:** `daemon_watchdog.py` 目前通过检查 `memory/logs/master_heartbeat.log` 的 mtime 判断存活，但 Master Graph 的 `run_master_daemon()` 并未写入此文件。需要在 `master_graph.py` 的每次心跳循环中写入心跳时间戳。

**文件变更清单:**
- Modify: `fdt_langgraph/master_graph.py` — 在 `run_master_daemon()` 循环中写入心跳文件
- Modify: `fdt_langgraph/master_nodes.py` — `_set_triggered()` 已写 `memory/schedule_state.json`，补充 `last_heartbeat` 字段

- [ ] **Step 1: 在 run_master_daemon() 心跳中写入时间戳文件**

修改 `fdt_langgraph/master_graph.py`，在 `run_master_daemon()` 的循环末尾写入心跳文件：

```python
def run_master_daemon(interval_seconds: int = 60):
    logger.info(f"[MasterGraph] 守护进程启动, 检查间隔={interval_seconds}s")
    loop_count = 0
    while True:
        loop_count += 1
        loop_id = f"master-loop-{loop_count}-{datetime.now().strftime('%H%M%S')}"
        logger.info(f"[MasterGraph] Loop #{loop_count} 开始")
        try:
            result = run_master_once(loop_id=loop_id)
            tasks = result.get("task_results", {})
            if tasks:
                for name, r in tasks.items():
                    icon = "✅" if r.get("success") else "❌"
                    logger.info(f"[MasterGraph]  {icon} {name}: {r.get('summary', '')[:80]}")
        except Exception as e:
            logger.error(f"[MasterGraph] Loop #{loop_count} 异常: {e}")

        # 写入心跳时间戳文件（供 daemon_watchdog 检测）
        _write_heartbeat()

        logger.info(f"[MasterGraph] 休眠 {interval_seconds}s...")
        time.sleep(interval_seconds)


_HEARTBEAT_PATH = PROJECT_ROOT / "memory" / "logs" / "master_heartbeat.log"


def _write_heartbeat():
    """写入心跳时间戳供看门狗检测存活。"""
    try:
        PROJECT_ROOT.joinpath("memory/logs").mkdir(parents=True, exist_ok=True)
        PROJECT_ROOT.joinpath(_HEARTBEAT_PATH).write_text(
            datetime.now().isoformat(), encoding="utf-8"
        )
    except Exception:
        pass
```

- [ ] **Step 2: 验证心跳写入**

```bash
python -c "
from fdt_langgraph.master_graph import run_master_once
run_master_once()
import json
state = json.loads(open('memory/schedule_state.json').read())
print('Heartbeat:', state.get('last_heartbeat', 'N/A'))
"
```

预期：`last_heartbeat` 显示当前时间。

- [ ] **Step 3: 更新 07-operations.md 中看门狗配置表的心跳阈值路径**

确认 `memory/logs/master_heartbeat.log` 已在`§3.2` 看门狗配置表中正确描述（上次更新已改，核实即可）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(v9.19.0): Master Graph 守护进程心跳文件

- run_master_daemon() 每心跳写入 master_heartbeat.log
- 供 daemon_watchdog.py 直接检测进程存活
- G108 Task 2/6"
```

---

### Task 3: daemon_watchdog.py 升级

**说明:** daemon_watchdog.py 已更新为 `fdt_cli.py daemon` 启动，但心跳检测仍依赖日志文件 mtime（降级方案）。升级到直接检测 `master_heartbeat.log`。

**文件:** `scripts/daemon_watchdog.py`

- [ ] **Step 1: 确认 daemon_watchdog.py 当前状态**

```bash
grep -n "heartbeat\|master_heartbeat" scripts/daemon_watchdog.py
```

预期：上次更新已改为 `LOG_DIR / "master_heartbeat.log"`，确认即可。

- [ ] **Step 2: 看门狗检测时优先检查 PID，再 fallback 到心跳文件**

当前实现已覆盖此逻辑（先检查 PID_FILE，再检查 heartbeat_file），无需修改。

- [ ] **Step 3: 验证看门狗可正确检测 Master 存活**

```bash
python -c "
from scripts.daemon_watchdog import check_daemon, PID_FILE
print('PID file exists:', PID_FILE.exists())
alive, status = check_daemon()
print('Status:', status)
"
```

如果 PID 文件不存在，预期 fallback 到"无心跳日志"。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(v9.19.0): daemon_watchdog 确认使用 master_heartbeat.log

- 看门狗优先检查 PID，fallback 到心跳文件 mtime
- G108 Task 3/6"
```

---

### Task 4: 外部脚本内联（部分）

**说明:** 并非全部 15 个外部脚本都需要内联。按耦合度/变更频率分级：

| 级别 | 脚本 | 处理方式 |
|:-----|:------|:---------|
| **内联高优** | `scripts/apm_scorecard.py`（被 2 个图共用） | 在 evolution_nodes.py 和 master_nodes.py 中各有一份 `_run_script` 调用，提取为公共函数 |
| **内联中优** | `scripts/validate_verdicts.py` / `calibrate_weights.py` / `evolve_agents.py`（多步管道频繁调用） | 保留 subprocess 但提取公共路径常量 |
| **保留 subprocess** | `scripts/scan_all.py`（800+ 行，独立技能）、`ml/trainer.py`（依赖 ML 库） | 保持现状，仅确认 LangGraph 编排正确 |
| **保留 subprocess** | 其余 10 个脚本（cluster_failures/enforce_discipline/self_improve/verify_evolution/auto_publish/run_benchmark/skillevolver 等） | 保持现状 |

**实际任务：** 只做"内联高优"项。其余保持现状，确认所有入口已归档到 G108 差距描述。

- [ ] **Step 1: 提取 apm_scorecard.py 调用为公共函数**

在 `fdt_langgraph/master_nodes.py` 和 `fdt_langgraph/evolution_nodes.py` 中：

`master_nodes.py` 现有:
```python
def node_run_apm_scorecard(state: dict) -> dict:
    ...
    ok, msg = _run_script("scripts/apm_scorecard.py", timeout=120)
    ...
```

`evolution_nodes.py` 现有类似调用。

创建一个公共函数 `_run_apm_scorecard()` 并引用, 或者确认两者已足够独立（当前各自有完整节点函数日志和状态记录，重复度可控，不做强行提取）。

- [ ] **Step 2: 确认所有外部脚本入口已归档**

在 G108 差距描述的"涉及文件"中已列出全部 15 个脚本。确认 master_graph.py 和 evolution_graph.py 对它们的调用路径正确。

- [ ] **Step 3: 对保留 subprocess 的脚本，在 08-gap-analysis.md 中标记为"设计决策·有意识保留"**

```bash
# 已确认: subprocess 调用是合理的架构边界，不作内联
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(v9.19.0): 外部脚本内联评估与归档

- apm_scorecard 跨 2 图调用已确认可独立运行
- 12 个脚本保留 subprocess（架构边界合理）
- G108 Task 4/6"
```

---

### Task 5: 文档全量同步

**说明:** 扫清所有 Harness 文档中仍引用 `scheduler/`、`pipeline/runner.py` 旧架构的描述。

- [ ] **Step 1: 全量 grep 旧引用**

```bash
grep -rn "scheduler/engine\|scheduler/triggers\|scheduler/tasks\|pipeline/runner\|FDT_USE_LANGGRAPH\|phase3_generate\|bootstrap.py" --include="*.md" docs/
```

- [ ] **Step 2: 逐个文档清理**

按 Grep 结果逐个清理。上次已清理的主要文档，本次重点检查是否有遗漏。

预期清理的文档和段落:
- `docs/harness/README.md` — 确认 `pipeline/runner.py` 入口已替换
- `docs/harness/06-testing.md` — 确认测试树已删除 scheduler/ 分支
- `docs/harness/07-operations.md` — 确认 A/B 切换描述已删除
- `docs/harness/01-architecture.md` — 确认架构图已更新

- [ ] **Step 3: 更新 README.md 的脚本数和入口点**

```bash
grep -n "pipeline\|scheduler" README.md
```

更新为最新计数（pipeline/ 删除后脚本数减少）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(v9.19.0): LangGraph 迁移收尾文档全量同步

- 清理 pipeline/runner.py / scheduler/ 等旧引用的所有残存
- 更新 README.md 入口点和计数
- G108 Task 5/6"
```

---

### Task 6: 验证收口

**说明:** 全量测试 + G108 关闭登记 + 版本号 bump。

- [ ] **Step 1: 全量运行测试**

```bash
python -m pytest tests/ --ignore=tests/commodity-chain --ignore=tests/pipeline -x --tb=short -q
```

预期：全部通过（预存失败的 test_record_filename_format 除外）。

- [ ] **Step 2: 运行 Master Graph 单次检查**

```bash
python -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
from fdt_langgraph.master_graph import run_master_once
result = run_master_once()
print('OK: %d tasks, %d errors' % (len(result.get('task_results', {})), len(result.get('errors', []))))
" 2>&1 | grep -v "Registered agent"
```

预期：无到期任务（当前时间无匹配），或数据触发任务正确跳过。

- [ ] **Step 3: Bump 版本号**

```bash
python -c "
import re
p = open('pyproject.toml').read()
old = re.search(r'version\s*=\s*\"([\d.]+)\"', p).group(1)
new = old.rsplit('.', 1)[0] + '.' + str(int(old.rsplit('.', 1)[1]) + 1)
print(f'{old} -> {new}')
"
```

手动更新 `pyproject.toml` 的 `version` 字段。

- [ ] **Step 4: 更新 07-operations.md 版本历史**

追加一行：
```
| v9.19.0 | 2026-07-23 | **LangGraph 迁移收尾** — G108 关闭。pipeline/runner.py 强制退役，LangGraph 为唯一辩论路径。Master Graph 心跳文件落地，daemon_watchdog 直接检测。Harness 文档全量同步。 |
```

- [ ] **Step 5: 关闭 G108 差距**

在 `docs/harness/08-gap-analysis.md` G108 行中，将状态栏从 `开放` 改为 `✅ 已关闭（v9.19.0）`，填入修复内容摘要。

- [ ] **Step 6: 更新 09-advancement-plan.md Phase 13 状态**

将 Phase 13 行从 `🔄` 改为 `✅`。

- [ ] **Step 7: Final Commit**

```bash
git add -A
git commit -m "release(v9.19.0): LangGraph 迁移收尾完成

- pipeline/runner.py 强制退役
- Master Graph 心跳文件
- G108 关闭
- Harness 文档全量同步
- G108 Task 6/6"
```

---

## 文件变更总览

| Task | 创建 | 修改 | 删除 |
|:-----|:-----|:-----|:-----|
| T1 pipeline 退役 | — | `fdt_cli.py` | `pipeline/runner.py`, `pipeline/quality_filter.py`, `pipeline/__init__.py`, `tests/pipeline/` |
| T2 Master 心跳 | — | `fdt_langgraph/master_graph.py` | — |
| T3 看门狗升级 | — | `scripts/daemon_watchdog.py`（确认） | — |
| T4 脚本内联 | — | `fdt_langgraph/master_nodes.py` / `evolution_nodes.py` | — |
| T5 文档同步 | — | 多篇 Harness 文档 + README.md | — |
| T6 验证收口 | — | `pyproject.toml`, `08-gap-analysis.md`, `09-advancement-plan.md`, `07-operations.md` | — |

## 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|:-----|:----:|:-----|:-----|
| pipeline/runner.py 有外部依赖 | 低 | 高 | Step 1 先扫描所有引用 |
| 删除 pipeline/ 后 tests/pipeline/ 测试失败 | 中 | 中 | 测试目录一并删除 |
| 看门狗心跳检测不准 | 低 | 低 | fallback 到日志 mtime |
| 文档有遗漏引用 | 中 | 低 | 多次 grep 交叉验证 |
