# FDT Harness 驾驭工程编码规范

> 版本 v1.2 | 2026-07-23 | 硬性约束，所有 FDT 修改必须遵守

---

## 1. 核心原则：文档先行 (Documentation-First)

**动手改任何 `.py` 之前，先改好对应的 `.md`。**

代码只是把文档里已经定义好的东西翻译成 Python。Harness 文档 = design spec，测试 = validation spec，代码 = implementation。

### 修改顺序（强制）

```
① 设计评估 ──→ 扫一遍 8 维影响面（01-09）
② 文档先行 ──→ 更新受影响的设计文档
③ 测试设计 ──→ 补测试用例（定义「什么叫改对了」）
④ 编码实现 ──→ 按文档敲代码
⑤ 验证收口 ──→ 跑测试 → 08-gap-analysis 登记/关闭差距 → 09-advancement-plan 更新里程碑
```

---

## 2. 文档-代码同步检查清单（每次 commit 前自问）

| # | 检查项 | 对应文档 |
|:-:|:-------|:---------|
| 1 | 数据流/架构变更是否反映？ | `01-architecture.md` |
| 2 | 阶段/文件名/产出物是否反映？ | `02-lifecycle.md` / `04-resilience.md` |
| 3 | 新配置项是否更新？ | `03-configuration.md` |
| 4 | 降级/熔断/超时路径是否更新？ | `04-resilience.md` |
| 5 | 新指标/日志是否已加？ | `05-observability.md` |
| 6 | 测试文件和用例数是否更新？ | `06-testing.md` |
| 7 | 版本号和版本历史是否追加？ | `07-operations.md` |
| 8 | 差距登记/关闭是否更新？ | `08-gap-analysis.md` |
| 9 | 晋级里程碑是否更新？ | `09-advancement-plan.md` |
| 10 | 流程文档 (`execution_modes_flowchart.md` / `business_flow.md`) 是否同步？ | `docs/` |
| 11 | 角色 MD (`agents/*.md`) 职责变更是否反映？ | `agents/` |
| 12 | README 快速参考（Skill 数/脚本数/测试数）是否刷新？ | `README.md` |
| 13 | **退役模块是否已清理？**（代码/测试/文档引用全删除） | 本项目文档全部 |

**做不到就暂时禁止 commit。** 先用 `git stash` 把代码暂存，补完文档再继续。

---

## 3. 契约优先 (Contract-First)

| 规则 | 说明 |
|:-----|:------ |
| **改 `contracts/` 前先写 schema** | 任何通信结构变化先定义 JSON Schema / TypedDict，再改 `migrations.py` 的迁移函数，最后改消费端 |
| **版本迁移必走 migrations.py** | `apply_migration(skill_type, data, target_version)` 是唯一合法的版本迁移路径，不允许硬编码做版本兼容 |
| **A2A 桥优先** | 跨 Agent 通信走 `contracts/a2a_payload.py` 的 A2APayload 信封，不允许直接用裸 dict |

---

## 4. 测试随重构 (Test-Always)

| 规则 | 说明 |
|:-----|:------ |
| **函数重命名 → 同步改 mock 名** | v6.3.0 `step_scan_dual`→`step_scan` 未同步 test 导致 5/10 绿了 5 天无人发现 —— `tests/pipeline/test_runner.py` 必须同步 |
| **新功能 → 新测试文件** | `pyproject.toml` 已覆盖 12 个目录（`tests/` 下），新功能加测试时加到对应子目录 |
| **commit 前跑受影响目录** | `python -m pytest tests/affected_module/` |
| **CI 门禁** | 所有 `tests/` 目录下的测试必须全绿才能合入 main |

---

## 5. 版本号纪律

| 规则 | 说明 |
|:-----|:------ |
| **pyproject.toml 是唯一真相源** | 所有文档读 `get_fdt_version()`（`scripts/fdt_paths.py` 导出），不允许在任何文档中硬编码版本字符串 |
| **每次代码变更（非纯文档）必须 bump** | patch（修复/微调）、minor（新功能）、major（不兼容） |
| **版本历史追加** | `docs/harness/07-operations.md §5.2` 每发版追加一行，格式：`vX.Y.Z \| 日期 \| 变更摘要` |

---

## 6. trace_id 全链路

| 规则 | 说明 |
|:-----|:------ |
| **trace_id 从 scan 贯穿到 report** | 缺 trace_id 的产出被视为无效，`validate_agent_output.py` 会拒绝 |
| **新数据通路必须传 trace_id** | 新增的 JSON 产出/中间文件必须包含 `meta.trace_id` 字段 |

---

## 8. 退役模块及时清理（2026-07-23 新增）

**模块退役时不只删代码——代码、测试、文档引用三部曲全部删干净。**

### 清理清单（退役模块时逐项检查）

| # | 检查项 | 说明 |
|:-:|:-------|:------|
| 1 | Python 源文件 | 整个模块目录及 `__pycache__` |
| 2 | 测试文件 | 对应的 `tests/` 子目录 |
| 3 | 入口引用 | `fdt_cli.py` 等入口文件中转发调用 |
| 4 | 监控与运维 | `dashboard.py` / `webui.py` / `health_server.py` 中状态检查 |
| 5 | 看门狗 | `daemon_watchdog.py` 等自动恢复脚本 |
| 6 | 门禁测试 | `tests/fdt-gate/` 中 import smoke / integration 用例 |
| 7 | Harness 文档 | 01-09 文档中所有引用（架构图/命令/配置/运维/测试树） |

### 反模式

- ❌ 只删 `.py` 不删文档 → 项目知识变僵尸文档
- ❌ 保留 `__init__.py` 空包 → 误导后续阅读者"这还有个模块"
- ❌ 注释说"已废弃"但代码不删 → 三年后没人敢删
- ❌ 删了代码不更新测试 → 门禁集成测试报 ImportError

### 正确做法

```python
# ❌ 错误：留着不删
# from scheduler.engine import SchedulerEngine  # 已废弃

# ✅ 正确：直接删文件，文档同步更新
```

---
## 7. 角色边界（2026-07-14 钉死）

| 角色 | 职责 | 禁止 |
|:-----|:-----|:------|
| **数技源** | 唯一信号生产者（channel_breakout） | 不下多空结论 |
| **链证源** | 产业链分析师（平级） | 下多空结论、dispatch 其他 Agent |
| **观澜** | 技术面分析师（平级） | 下结论 |
| **探源** | 基本面分析师（平级，LLM 推理生成 FundamentalStateVector） | 下结论 |
| **读心** | 新闻情绪分析师（平级，LLM 推理生成 SentimentStateVector） | 下结论 |
| **闫判官** | 辩论调度权（选品种+dispatch 分析师） | 替链证源/观澜/探源/读心做分析 |
| **明鉴秋** | 执行 spawn + 资源/生命周期管控 | 不替闫判官做调度决策 |

> 链证源/观澜/探源/读心为 **平级分析师**，仅分析方向不同（产业链/技术面/基本面/新闻情绪），**彼此无调度与被调度关系**。

---

## 8. 差距管理纪律

| 阶段 | 操作 |
|:-----|:------ |
| **发现新差距** | 立即登记到 `08-gap-analysis.md` §4（G+编号），按 P0/P1/P2 定优先级 |
| **修复差距** | 验证后更新对应 Gap 行为「已修复 ✅」，改涉及文件为带 ✅ 标记路径 |
| **全部差距关闭** | 更新 §2 成熟度评分 + §7 总结为「全部差距关闭，达成 8 维满分」 |
| **晋级计划** | `09-advancement-plan.md` 各 Phase 完成后打 ✅，最终状态保持同步 |

---

## 9. 交易建议可操作性原则（Operability-First）

**FDT 产出的每一条交易建议都必须回答"以当前价格，你能不能做、做多少、止损止盈在哪？"** 不允许以偏离现价的挂单价作为核心建议。

### 9.1 核心定义

可操作性 = 交易指令在给出时即可执行，无需等待"行情走到某个特定价格"。具体而言，每个辩论的输出必须包含以下信息之一：

| 状态 | 含义 | 必须包含 |
|:-----|:-----|:---------|
| **立即执行** | 现价直接入场 | 方向 + 仓位比例 + 止损价 + 目标价 |
| **等待触发** | 需要挂条件单 | 挂单价 + 触发条件 + 未触发的放弃时限 + 止损 + 目标 |
| **不交易** | 现价不可操作 | 不可操作的理由（如盈亏比不达标、分歧度过高） |

### 9.2 禁止模式（设计反模式）

1. **"纯挂单价"**：仅给一个偏离现价的入场区间，不说明"现价该不该做"——这是交易幻想，不是交易建议
2. **"双向说得都对"**：辩论后给出"如果涨就做多、如果跌就做空"——等于什么都没说
3. **"等完美价格"**：要求等一个几乎不可能触发的价格才入场——等于建议不交易但不好意思直接说

### 9.3 辩论过程中的执行规则

- **多头/空头分析员**：在立论和结辩中必须明确"现价能否执行"的立场
- **闫判官裁决**：必须评估现价的可操作性，给出具体的"立即执行 / 等待触发 / 不交易"判定，并附盈亏比验算
- **风控明审核**：必须以现价为基准验证止损距离和仓位，如现价执行风控不达标(单笔亏损>4%或盈亏比<1:2)，否决现价开仓

### 9.4 现价可操作性检查清单（每次裁决前执行）

- [ ] 方向判断是否基于**当前价格**而非某个假想价格？
- [ ] 如果建议现价入场，止损距离是否在风控阈值内（单笔≤4%）？
- [ ] 如果建议等待挂单，是否明确了触发条件和放弃时限？
- [ ] 如果裁决为"不交易"，是否给出了替代方案或等待信号？
- [ ] 盈亏比是否≥1:2？（特殊品种如高波动原油可放宽至1:1.5）

---

## 10. 辩论能力演化路径与品种范围

### 10.1 演化哲学

FDT 的辩论分析能力遵循**循序渐进、逐步深化**的演化路径：

```
当前 ──→ 按品种特性深化 ──→ 按行情特点细化 ──→ 按关键因子定制
(通用)      (产品层)          (市场层)            (因子层)
```

| 阶段 | 层次 | 说明 | 状态 |
|:-----|:------|:------|:----:|
| **Layer 0** | 通用辩论策略 | 所有品种使用同一套辩论流程和 prompt 模板，不区分品种差异 | **当前** |
| **Layer 1** | 品种特性适配 | 根据品种类别（黑色/有色/能化/农产品/软商品/股指）差异化辩论策略、技术参数、分析侧重点 | 待建 |
| **Layer 2** | 行情特点适配 | 根据当前市场状态（趋势/震荡/高波/低波/切换点）动态调整辩论深度、风险偏好、持仓周期 | 待建 |
| **Layer 3** | 关键因子定制 | 各品种识别其最核心的 3-5 个驱动因子，辩论围绕这些因子展开，过滤噪声 | 待建 |

> **指导思想**：FDT 不是一个开发好就不变的死系统，而是一个跟随用户、跟随市场、跟随自身分析能力而渐进深化开发的**活系统**。每一步深化都让 FDT 更贴合市场实际状况，提升辩论分析能力。不追求一步到位，而是持续迭代、逐步逼近。

### 10.2 当前范围

FDT 当前仅处理**商品期货**（黑色/有色/能化/农产品/软商品），使用 Layer 0 通用辩论策略。不处理任何股指期货品种。

### 10.3 设计约束（2026-07-23 掌柜确立）

| 约束 | 说明 |
|:-----|:------|
| **商品期货 → 从通用起步** | 当前使用通用辩论策略，以 `trend_following` 为唯一信号源（趋势跟踪与大波段捕捉方向一致）。后续按演化路径逐步分层深化 |
| **股指期货 → 独立路径** | 将来接入股指期货时同样遵守上述演化路径，但从 Layer 0 起步，**不与商品期货共享 Layer 1+ 的定制逻辑**。参数（DC 周期、ATR 乘数、ADX 阈值等均针对各自品种波动特征独立校准）|
| **隔离要求** | 任何涉及股指期货的代码、配置、Agent prompt 必须与商品期货路径明确隔离，不允许共享条件路由 |
| **渐进原则** | 不得跳过演化阶段。在未充分掌握 Layer N 经验前，不超前进入 Layer N+1 |

### 10.4 Layer 1 实现路线图（参考）

- 按品种大类建立独立的 Agent prompt 变体（如黑色系侧重供给侧、农产品侧重天气/库存）
- 为不同品种类别设定差异化的技术参数集（通道周期、ATR 平滑、ADX 阈值等）
- 在 `fdt_langgraph/nodes.py` 的 context 构建中加入品种分类标签
- 探索路径：在 `memory/knowledge/` 中为活跃品种建立"品种画像"知识文档

---

## 11. 本规范自身的演进

- 本文件受 G17 纪律约束：如需修改本规范，须按「文档先行」原则先更新本文档再执行
- 检查清单 §2 随 Harness 文档体系的变化同步更新

### D3 Generation 控制规范

解码参数（temperature / max_tokens / top_p）配置原则：

1. **结构化输出优先**：所有 Agent 的 LLM 调用必须使用`response_format={type: "json_object"}` 或 Pydantic Schema 约束，禁止自由文本输出
2. **Temperature 分层**：
   - 生成型任务（辩论论点、反驳）：temperature 0.7-1.0
   - 判断型任务（裁决、评分）：temperature 0.1-0.3
   - 提取型任务（结构化数据）：temperature 0.0-0.1
3. **Max Tokens 预算**：每步必须有明确的 max_tokens 上限（在 Loop Contract 的 per_step_budget 中定义）
4. **采样策略**：高精度场景用 greedy（top_p=1, temperature=0）；创意场景用 nucleus sampling（top_p=0.9, temperature=0.7）
5. **约束传播**：输出 Schema 必须与 contracts/ 目录下的 JSON Schema 一致

### D3 Generation 运行时强制（v9.14.0 新增）

以下机制确保解码控制从"文档定义"落地为"运行时强制"：

1. **`decode_config.yaml` 运行时加载**：`FdtAgentExecutor.__init__()` 自动加载 `config/agents/decode_config.yaml`，用其中的 temperature/max_tokens 覆盖 agents.yaml 默认值。优先级：`decode_config.yaml > agents.yaml > 硬编码默认值`
2. **结构化输出自动校验**：`agent_waiter.py` 的 `wait_for_agent_output()` 在成功读取 Agent 产出后自动调用 `enforce_structured_output()`（非阻断）。校验失败仅记录 `generation_metrics`，不阻断流程。
3. **内容安全过滤**：`quality_inspector.py` 的 `check_report_integrity()` 自动调用 `content_filter.check_sensitive()` 检测敏感内容，结果以 warning 形式加入质检报告。
4. **APM D3 fallback**：`apm_scorecard.py` 在辩论轮次 < 5 时从 `generation_metrics` 读取 `schema_pass_rate` 作为 D3 镇定度的 fallback 评分。`schema_pass_rate < 80%` 标记为 degenerate。

5. **升温重试（Phase 4 反馈闭环）**：`enforce_structured_output.retry_with_temperature_escalation()` 按 `decode_config.yaml` 的 `retry_config.temperature_multiplier` 逐次升温重试。`agent_waiter.py` 校验失败时自动写入 `{output_path}.retry_signal.json` 信号文件，编排层检测后重新 spawn。

| 机制 | 触发点 | 文件 | 阻断性 |
|:-----|:-------|:-----|:------:|
| decode_config 加载 | `FdtAgentExecutor.__init__` | `fdt_langgraph/agents.py` | 否 |
| 结构化输出校验 | `wait_for_agent_output` | `scripts/agent_waiter.py` | 否 |
| 升温重试 | `_validate_agent_output` 校验失败 | `scripts/agent_waiter.py` / `scripts/enforce_structured_output.py` | 否（信号文件） |
| 内容安全过滤 | `check_report_integrity` | `fdt_langgraph/quality_inspector.py` | 否 |
| APM D3 fallback | `apm_scorecard.main` | `scripts/apm_scorecard.py` | 否 |

---

## 11. 一致性元数据

本表维护代码文件与文档章节之间的关键断言关系，用于快速验证文档-代码一致性。每个条目应可通过指定检验方式独立验证。

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `pyproject.toml version` | §5 版本号 | FDT 唯一版本真相源 | `grep "^version" pyproject.toml` |
| `scripts/fdt_paths.py get_fdt_version()` | §5 | 运行时读取版本 | `grep -n "def get_fdt_version"` |
| `fdt_langgraph/agents.py FdtAgentExecutor` | §10 D3 Generation | D3 结构化输出控制 | `grep -n "class FdtAgentExecutor\|response_format\|json_object"` |
| `scripts/enforce_structured_output.py retry_with_temperature_escalation()` | §10 D3 | 温度递增重试 | `grep -n "def retry_with_temperature\|temperature_escalation"` |
| `contracts/` | §3 契约优先 | Pydantic / TypedDict 定义 | `ls contracts/*.py` |
| `scripts/pre_commit_harness_check.py` | §2 检查清单 | 12 项检查自动化 | `grep -n "check\|C0[1-9]\|C1[0-2]" harness-rules.yaml` |
| `docs/harness/` | §1 修改顺序 | 8 维影响面扫描 | `ls docs/harness/0*.md \| wc -l` (应有 10 个) |
| `docs/harness/loop-contracts/` | §3 契约优先 | Loop Contract 规范 | `ls docs/harness/loop-contracts/*.yaml` |

---

*版本 v1.2 | 2026-07-23 | 新增 §11 一致性元数据*
