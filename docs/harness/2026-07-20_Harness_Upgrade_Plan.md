# FDT Harness 工程升级计划 v9.6.4

> **日期**: 2026-07-20
> **版本**: v9.5.0 → v9.6.4
> **定位**: 涵盖规范引擎化、类型注解补齐、缺失维度补充、G21/G22 设计文档的全方位 Harness 升级
> **状态**: ✅ **全部完成** — Phase A/B/C/D/E 五个阶段全部实施完成

---

## 一、范围总览

| Phase | 名称 | 预估 | 交付物 | 优先级 | 状态 |
|:-----:|------|:----:|--------|:------:|:-----:|
| A | 规范引擎化 | 4h | YAML 规则文件 + pre-commit hook + 12项检查自动化 | P0 | ✅ 完成 |
| B | 业务脚本类型注解 | 3h | 32 文件 69 函数补充 `-> None` / 参数注解 | P0 | ✅ 完成 |
| C | 测试函数类型注解 | 2h | 490 个测试方法批量补充 `-> None` | P1 | ✅ 完成 |
| D | 新增缺失规范维度 | 2h | 补充 D3/Hook/验证器/成本 4 个新维度 | P1 | ✅ 完成 |
| E | G21/G22 设计文档 | 3h | 两份完整设计文档（含 Pydantic Schema、API 设计） | P2 | ✅ 完成 |

---

## 二、Phase A: 规范引擎化

### A.1 12项检查 → YAML 规则文件

新建 `docs/harness/harness-rules.yaml`，把 12 项 commit 前检查转为机读格式：

| 规则 ID | 名称 | 严重度 | 触发模式 | 作用域 |
|:-------:|------|:------:|----------|--------|
| C01 | 架构变更反映检查 | P0 | `fdt_langgraph\|futures_data_core\|pipeline` | `docs/harness/01-architecture.md` |
| C02 | 生命周期文档同步 | P0 | `scripts/.*\.py` | `docs/harness/02-lifecycle.md` |
| C03 | 配置项更新检查 | P0 | `config/\|settings.json` | `docs/harness/03-configuration.md` |
| C04 | 降级/熔断路径检查 | P0 | `degrade\|circuit_breaker` | `docs/harness/04-resilience.md` |
| C05 | 可观测性文档检查 | P0 | `trace_id\|logger\|metric` | `docs/harness/05-observability.md` |
| C06 | 测试文档更新检查 | P1 | `tests/\|test_.*\.py` | `docs/harness/06-testing.md` |
| C07 | 版本号 bump 检查 | P0 | 通用触发 | `pyproject.toml` |
| C08 | 差距登记检查 | P1 | 重大变更 | `docs/harness/08-gap-analysis.md` |
| C09 | 晋级计划检查 | P1 | `Phase_\|milestone` | `docs/harness/09-advancement-plan.md` |
| C10 | 流程文档同步检查 | P1 | `pipeline\|flow\|workflow` | `docs/*_flowchart.md` |
| C11 | 角色职责文档检查 | P1 | `agents/` | `agents/*.md` |
| C12 | README 快速参考检查 | P0 | 通用触发 | `README.md` |

### A.2 pre-commit 自动化检查

升级 `scripts/pre_commit_harness_check.py` 为 v2 版本：
1. 从 `harness-rules.yaml` 加载规则（不再是硬编码）
2. `git diff --name-only HEAD` 获取变更文件
3. 检查变更文件是否匹配 trigger_pattern
4. 匹配则检查对应 scope 文档是否已同步更新
5. JSON 结构化输出（可被 IDE 消费）

### A.3 检查结果 Schema

```python
@dataclass
class HarnessCheckResult:
    check_id: str
    check_name: str
    severity: str          # P0/P1/P2
    status: str            # pass/warn/fail
    changed_files: list[str]
    required_docs: list[str]
    missing_docs: list[str]
    message: str
```

---

## 三、Phase B: 业务脚本类型注解

### B.1 目标

补齐 `scripts/` 下 32 个业务文件中 69 个公共函数的类型注解（排除 test_scripts.py）。

### B.2 修复策略

| 模式 | 函数数 | 方式 |
|------|:------:|------|
| 仅缺 `-> None` | ~60 | 批量脚本：正则 `def func(self):` → `def func(self) -> None:` |
| 缺参数+返回注解 | ~9 | 手工逐个补充（update_matrix / self_improve / inference_gate / memory_enforcer / validate_agent_output / confidence_utils） |

### B.3 批量脚本逻辑

```python
# 1. 正则匹配 def func(): 或 def func(self): 模式
# 2. 排除已有 -> 的
# 3. 加 from __future__ import annotations
# 4. 补 -> None
# 5. 跳过多参数无注解的（留给手工）
```

### B.4 手工修复清单

| 文件 | 函数 | 需要 |
|------|------|------|
| `update_matrix.py` | `save_matrix`, `ensure_symbol`, `update_family`, `batch_update`, `parse_verdicts` | 参数+返回注解 |
| `self_improve.py` | `generate_improvement_suggestions` | 参数 `(sc, clusters, replay):` → 类型注解 |
| `self_improve.py` | `enhanced_generate_with_evolution` | 同上 |
| `inference_gate.py` | `run_datatech` | 4 个参数全缺 |
| `memory_enforcer.py` | `save_json` | `data` 参数缺注解 |
| `confidence_utils.py` / `validate_agent_output.py` | `conf` 参数 | `conf: Any` 或具体类型 |

---

## 四、Phase C: 测试函数类型注解

### C.1 方法

纯机械操作：`test_scripts.py` 中所有 pytest 测试方法都应返回 `None`。

### C.2 正则规则

```
def test_\w+\(self\):                 → def test_\w+\(self\) -> None:
def test_\w+\(self, \w+:              → def test_\w+\(self, ...\) -> None:
def my_agent\(agent_name, \*\*kwargs\): → def my_agent(...) -> None:
```

### C.3 验证

每修改一批次执行 `pytest --collect-only test_scripts.py` 确保无语法错误。

---

## 五、Phase D: 新增缺失规范维度

### D.1 新增维度

| 维度 | 目标文档 | 新增内容 |
|------|----------|----------|
| D3 Generation 控制规范 | `10-coding-standards.md` | 温度/max_tokens 配置原则、结构化输出约束 |
| Hook 链架构规范 | `01-architecture.md` | pre-action/post-action/safety hook 接口定义 |
| 验证器质量度量 | `06-testing.md` | 漏放率(false pass)硬指标、误杀率(false block)效率指标 |
| 成本工程规范 | `03-configuration.md` | Token 估算公式、缓存 TTL 耦合策略、降本手段排序 |
| 上线四步评估流程 | `07-operations.md` | 影子模式→金标准→验证器→金丝雀 |

### D.2 反模式检测规则

10 条核心反模式追加到 `harness-rules.yaml`：

| ID | 名称 | 检测 | 严重度 |
|:--:|------|------|:------:|
| AP01 | 巨型 Prompt | AGENTS.md > 300 行 | P1 |
| AP02 | 跳过审核直接编码 | 无 plan 直接提交 | P0 |
| AP03 | Rules 不维护 | YAML 超 30 天未修改 | P1 |
| AP04 | MCP 过度接入 | MCP 服务 > 10 个 | P2 |
| AP05 | Skill 不原子化 | 单 Skill > 200 行 | P1 |
| AP06 | 盲目信任 AI 输出 | 生产路径无独立验证 | P0 |
| AP07 | 循环无停止条件 | Loop Contract stop 为空 | P0 |
| AP08 | 多循环共写 STATE | 多 Loop 同一 state 目录 | P1 |
| AP09 | Chat 历史当文档 | 知识仅在对话历史 | P2 |
| AP10 | 一个 PR 改所有 | PR > 20 文件 | P1 |

---

## 六、Phase E: G21/G22 设计文档

### E.1 G21: Harness 自适应优化

**文件**: `docs/designs/g21-harness-adaptive-optimization.md`

核心设计：
- **双层经验库**：E_t（逐案例记录）+ G_t（全局蒸馏模式）
- **检索适配**：`W(x_j) = W* + Delta(config_delta)`
- **正确性优先**：主指标决定排名，成本仅作平局次级指标
- **六维配置空间**：Context/Tool/Generation/Orchestration/Memory/Output

### E.2 G22: 多循环协作协议

**文件**: `docs/designs/g22-multi-loop-collaboration.md`

核心设计：
- **Handoff 消息 Schema**：Pydantic BaseModel
- **生产者-消费者状态机**：pending → claimed → done/failed → archive
- **背压三级策略**：限产 / 提效 / 降级 stale
- **拓扑定义**：Mermaid 图 + YAML 拓扑文件

---

## 七、实施路线图

```
Phase A (规范引擎化)  ────┬─── A1 harness-rules.yaml (1h)
                          └─── A2 pre-commit v2 (1h)
                                │
Phase B (业务注解)  ──────────┬─── B1 批量脚本 ~60函数 (1h)
                              └─── B2 手工 ~9函数 (1h)
                                    │
Phase C (测试注解)  ──────────┬─── C1 脚本处理 490函数 (1h)
                              └─── C2 pytest 验证 (0.5h)
                                    │
Phase D (规范维度)  ──────────┬─── D1 5篇文档更新 (2h)
                              └─── D2 反模式追加 (0.5h)
                                    │
Phase E (G21/G22设计) ───────┬─── E1 G21 设计文档 (1.5h)
                              └─── E2 G22 设计文档 (1.5h)
                                    │
核验  ────────────────────────┬─── 差距登记 + 版本 bump (0.5h)
                              └─── 12项检查清单 (0.5h)
```

---

## 八、交付物清单

| # | 交付物 | Phase | 类型 | 状态 |
|:-:|--------|:-----:|:----:|:-----:|
| 1 | `docs/harness/harness-rules.yaml` | A | 新文件 | ✅ |
| 2 | `scripts/pre_commit_harness_check.py` v2 | A | 代码修改 | ✅ |
| 3 | 32 个业务脚本类型注解修复 | B | 代码修改 | ✅ |
| 4 | `test_scripts.py` 类型注解修复 | C | 代码修改 | ✅ |
| 5 | 5 篇规范文档更新 | D | 文档修改 | ✅ |
| 6 | `harness-rules.yaml` 反模式章节追加 | D | 追加 | ✅ |
| 7 | `docs/designs/g21-harness-adaptive-optimization.md` | E | 新文件 | ✅ |
| 8 | `docs/designs/g22-multi-loop-collaboration.md` | E | 新文件 | ✅ |
| 9 | 差距登记更新 + 版本 bump + 12项检查 | 核验 | 文档修改 | ✅ |

---

## 九、完成总结（v9.6.4）

### 9.1 实际完成情况

| Phase | 计划 | 实际完成 | 备注 |
|:-----:|------|----------|------|
| A | 规范引擎化 | ✅ 完成 | 12 条规则机读化 + pre-commit v2 + JSON 输出 |
| B | 业务脚本类型注解 | ✅ 完成 | 38 文件 90 函数（计划 32/69，实际覆盖更广） |
| C | 测试函数类型注解 | ✅ 完成 | 490 测试方法全部补充 `-> None` |
| D | 新增缺失规范维度 | ✅ 完成 | 5 维度 + 10 条反模式规则 |
| E | G21/G22 设计文档 | ✅ 完成 | 两份设计文档已存在 |

### 9.2 Phase D 详细交付

| 维度 | 文档 | 内容 |
|------|------|------|
| D3 Generation | `10-coding-standards.md` | 温度/max_tokens 配置原则、结构化输出约束 |
| Hook 链架构 | `01-architecture.md` | pre_hook/post_hook/safety_hook 三层接口定义 |
| 验证器质量度量 | `06-testing.md` | 漏放率≤1%、误杀率≤5% 硬指标 + 质量等级 + 告警规则 |
| 成本工程规范 | `03-configuration.md` | Token 估算公式、缓存 TTL 耦合、降本手段排序 |
| 上线四步评估 | `07-operations.md` | 影子模式→金标准比对→验证器验收→金丝雀发布 |

### 9.3 反模式检测规则

AP01-AP10 全部追加到 `harness-rules.yaml`，涵盖：巨型 Prompt、跳过审核、Rules 不维护、MCP 过度接入、Skill 不原子化、盲目信任 AI 输出、循环无停止条件、多循环共写 STATE、Chat 历史当文档、一个 PR 改所有。

### 9.4 文档同步更新

- ✅ `08-gap-analysis.md`：G80/G81/G82/G83/G21/G22 状态更新为已完成
- ✅ `07-operations.md`：版本历史追加 v9.6.4
- ✅ `README.md`：版本号更新为 v9.6.4
- ✅ `pyproject.toml`：版本号更新为 9.6.4

### 9.5 Harness 检查结果

```
✅ 已加载 12 条规则: D:\Programs\FDT\docs\harness\harness-rules.yaml
✅ 通过的检查: C03 配置项更新检查、C07 版本号 bump 检查、C12 README 快速参考检查
⚠️ 建议更新: C08 重大变更应考虑在 08-gap-analysis.md 登记新差距
⏭️ 跳过的检查: 8 项
总结: 3/12 通过 (0 失败, 1 建议, 8 跳过)
✅ 全部检查通过，可以提交
```
