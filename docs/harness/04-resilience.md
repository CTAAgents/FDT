# 04 — 错误恢复与鲁棒性

## 1. L1-L5 五层防线总览

FDT 的鲁棒性架构由 5 层防线组成，确保辩论流程在任何异常情况下不静默断裂：

```
请求进入
    │
    ▼
┌─────────────────────────────────────────────┐
│  L5 健康自检 (selfcheck.py)                  │ ← 辩论启动前
│  检查: 数据源/路径/脚本/Agent定义             │
└───────────────────┬─────────────────────────┘
                    │ pass
                    ▼
┌─────────────────────────────────────────────┐
│  L3 信号门 (daily_debate.py)                 │ ← P1扫描后
│  检查: debate_trigger.json 存在?             │
│  检查: all_ranked 有 STRONG 信号?            │
└───────────────────┬─────────────────────────┘
                    │ pass
                    ▼
┌─────────────────────────────────────────────┐
│  spawn Agent (P2-P5)                         │
│  │                                          │
│  ├─ L1 产出校验 (validate_agent_output.py)   │ ← 每个 spawn 后
│  │  检查: JSON schema + 禁止模式             │
│  │                                          │
│  ├─ L2 熔断降级 (debate_orchestrator.py)     │ ← L1失败后
│  │  retry 最多 2 次 → D06 降级               │
│  │                                          │
│  └─ S04 轮询等待 (agent_waiter.py)           │ ← spawn 后
│     poll_file_ready (15s间隔, 15min超时)     │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  L4 路径自发现 (phase3_generate_report.py)   │ ← 报告生成时
│  CLI参数 → 环境变量 → 自动发现 (三级 fallback)│
└───────────────────┬─────────────────────────┘
                    │
                    ▼
              报告输出
```

## 2. 各层详解

### 2.1 L1 — 产出校验

| 项 | 内容 |
|:---|:-----|
| **脚本** | `validate_agent_output.py` (在各 skill 内) |
| **触发时机** | 每个 Agent spawn 完成后 |
| **校验内容** | JSON Schema 合规性 + 必填字段非空 + 禁止模式检查 |
| **失败动作** | 标记产出无效 → 触发 L2 重试 |
| **代码位置** | 各 skill 的 `scripts/validate_agent_output.py` |

**校验规则**:
```python
# 校验清单 (docs/agent-protocol.md §5)
□ schema.model_validate(data) 不抛异常
□ required fields 不空
□ confidence ∈ [0, 1] 或 [0, 100]
□ 无 verdict 字段 (研究员输出红线)
□ meta.agent_name 与产出方一致
```

### 2.2 L2 — 熔断降级

| 项 | 内容 |
|:---|:-----|
| **脚本** | `debate_orchestrator.py` (编排器) |
| **触发时机** | L1 校验失败后 |
| **重试策略** | 最多 retry 2 次 |
| **降级机制** | D06: 闫判官 2 次 spawn 失败 → 明鉴秋基于 P2(四源)+P3(辩论) 论据独立裁决 |
| **降级约束** | 裁决必须基于辩论论据交叉质询，不得凭空生成 |

**D06 降级流程**:
```
spawn 闫判官 (第1次)
    │
    ├─ 产出有效 → 正常裁决
    │
    └─ 失败/超时 → retry
                    │
                    ├─ spawn 闫判官 (第2次)
                    │   │
                    │   ├─ 产出有效 → 正常裁决
                    │   │
                    │   └─ 失败/超时 → D06 降级
                    │                   │
                    │                   └─ 明鉴秋基于 P3(研究员) + P4(辩手) 论据
                    │                      独立完成裁决
                    │                      (严基于辩论论据交叉质询)
```

### 2.3 L3 — 信号门

| 项 | 内容 |
|:---|:-----|
| **脚本** | `scripts/run_debate.py` + `pipeline/runner.py step_scan()`（v6.3.0 数技源信号+分析师能力） |
| **触发时机** | P1 扫描完成后 |
| **检查内容** | `debate_trigger.json` 文件存在 + `all_ranked` 有 `abs(total) >= DEBATE_ENTRY_MIN_ABS` 的候选品种（阈值见 `config/settings.py`，当前=20，已过滤 NOISE 级） |
| **失败动作** | **提前终止整个流程**，向用户汇报"当天无通道突破信号" |
| **意义** | 避免无信号时浪费 Agent spawn 资源 |

**信号检查逻辑**:
```python
# 读取 full_scan_summary_{date}.json（数技源信号，channel_breakout 产出）
# 阈值唯一真相源 = skills/quant-daily/scripts/config/settings.py:DEBATE_ENTRY_MIN_ABS（当前=20，经 run_debate.py 读取）
# candidates = [s for s in all_ranked if abs(s.total) >= DEBATE_ENTRY_MIN_ABS]
# 有候选 → 继续流程
# 无候选 → 提前终止
```

### 2.4 L4 — 路径自发现

| 项 | 内容 |
|:---|:-----|
| **脚本** | `phase3_generate_report.py` v3.2 |
| **触发时机** | P6 报告生成时 |
| **发现策略** | CLI参数 → 环境变量 → 自动发现 (三级 fallback) |
| **意义** | 避免硬编码路径导致跨环境部署失败 |

**路径发现优先级**:
```
1. CLI 参数: --workspace /path/to/output
2. 环境变量: FDT_REPORT_DIR
3. 自动发现: 扫描 Commodities/Reports/商品期货深度分析/{date}/
```

### 2.5 L5 — 健康自检

| 项 | 内容 |
|:---|:-----|
| **脚本** | `selfcheck.py` (在各 skill 内) |
| **触发时机** | 辩论启动前 |
| **检查内容** | 数据源连通性 / 文件路径存在 / 脚本可执行 / Agent 定义文件完整 |
| **失败动作** | 输出诊断报告，标记不健康项 |
| **代码位置** | 各 skill 的 `scripts/selfcheck.py` |

## 3. S04 轮询协议

### 3.1 协议设计

S04 解决了"Agent 后台 spawn 后如何知道产出就绪"的问题：

```
明鉴秋
    │
    ├─ 1. build_spawn_file_instruction(output_path, agent_name)
    │     → 生成文件输出指令，追加到 spawn prompt
    │     → 指令包含: 文件路径 + .tmp写入要求 + SendMessage通知要求
    │
    ├─ 2. Agent tool spawn (subagent_type: "general-purpose")
    │     → Agent 执行任务
    │     → Agent 先写 {output_path}.tmp
    │     → Agent 完成后 rename 为 {output_path}
    │     → Agent SendMessage 通知 main (非阻塞)
    │
    ├─ 3. poll_file_ready(filepath, timeout=900)
    │     → 每 15s 检查:
    │        a. .tmp 文件存在? → Agent 正在写, 继续等
    │        b. 正式文件存在 + size > 0?
    │        c. size 稳定 ≥5s? → 返回 True
    │     → 超时 (15min) → 返回 False → 触发 D06
    │
    └─ 4. wait_for_agent_output(filepath, agent_name, timeout)
          → poll_file_ready 成功: 读取 JSON → 返回解析结果
          → poll_file_ready 超时: 返回 None → D06 降级
```

### 3.2 参数规格

| 参数 | 默认值 | 可配置 | 说明 |
|:-----|:-------|:-------|:-----|
| `timeout` | 900s (15min) | 是 | 轮询超时时间 |
| `stable_seconds` | 5s | 是 | 文件 size 稳定时间 |
| `poll_interval` | 15s | 是 | 轮询间隔 |
| `max_retries` (L2) | 2 | 是 | L2 熔断重试次数 |
| `numpy_timeout` | 60s | 否（代码硬编码） | scan_all.py 品种级 numpy 指标计算超时，超时则跳过该品种（ThreadPoolExecutor+60s），防止单品种卡死全盘扫描 |

### 3.3 代码位置

| 组件 | 文件 | 函数 |
|:-----|:-----|:-----|
| 文件指令生成 | `scripts/agent_waiter.py` | `build_spawn_file_instruction()` L32 |
| 轮询函数 | `scripts/agent_waiter.py` | `poll_file_ready()` L50 |
| 等待+解析 | `scripts/agent_waiter.py` | `wait_for_agent_output()` L102 |

## 4. 通信时序铁律

### 4.1 S01-S04 协议

| 规则 | 内容 | 实现方式 |
|:-----|:-----|:---------|
| **S01 数据就绪** | spawn 下游前，上游文件必须已稳定 ≥5s | `poll_file_ready(path, timeout=900)` |
| **S02 禁止串线** | Agent 不得互相 SendMessage，统一写文件由明鉴秋传递 | spawn prompt 末尾加禁止指令 |
| **S03 原子写入** | Agent 写文件先写 `.tmp`，完成后 rename | `write_temp → os.rename(src, dst)` |
| **S04 轮询等待** | 用轮询文件代替 TaskOutput.block | `while not ready: sleep(15)` |

### 4.2 事故根源

> 2026-07-07 凌晨事故: 探源写文件只过半，证真就读 → 7 品种标"研究员未覆盖"。同时 Agent 之间直接 SendMessage (闫判官→证真)，绕过了明鉴秋的控制流。
>
> **修正**: 明鉴秋全程调度每一步，Agent 之间禁止直接通信 (S02)。每个 Agent 只完成自己的分析 → 写文件 → 通知 main。

## 5. 辩论完整性铁律

### 5.1 D01-D06 规则

| 规则 | 内容 | spawn 方式 |
|:-----|:-----|:-----------|
| **D01 禁止代写论据** | P3 辩论阶段，明鉴秋不得自行撰写证真/慎思论据 | 必须 spawn 对应 Agent |
| **D02 禁止代写裁决** | P4+P5 裁决阶段，明鉴秋不得自行撰写裁决结论 | 必须 spawn 闫判官 |
| **D03 Phase 门禁** | P6 汇总前检查: 缺少 p4/p5 产出文件则拒绝生成报告 | 文件存在性检查 |
| **D04 Agent 通信** | 辩论 Agent 产出通过 SendMessage→main 回传 | 明鉴秋转写入文件 |
| **D05 Spawn 类型** | 辩论 Agent 必须用 `general-purpose` spawn | 禁止 expert subagent_type |
| **D06 P5 降级** | 闫判官 spawn 2 次无产出 → 明鉴秋基于 P2(四源)+P3(辩论) 独立裁决 | 严基于辩论论据 |

### 5.2 D05 根因

> 2026-07-09 Bug 确认: expert subagent_type spawn 时 Write 工具不可用 (5 次失败)。
>
> **修正**: 所有辩论 Agent 使用 `subagent_type: "general-purpose"` + prompt 手动注入角色定义。

## 6. 异常处理流程

### 6.1 风控连续两次 Red

```
风控 Red → 策略师修改方案 → 风控再次 Red
    │
    ▼
闫判官暂停辩论流程
    │
    ▼
明鉴秋召集三方会议 (策略师 + 风控 + 闫判官)
    │
    ▼
明鉴秋行使最终决策权:
    ├─ 降级: 降仓位后直接通过
    ├─ 搁置: 本轮不执行，等新信号
    └─ 打回重辩: 裁判认为双方论证质量不够
```

### 6.2 Agent 超时/离线

```
poll_file_ready 超时 (15min)
    │
    ▼
标记为"弃权"，辩论继续
    │
    ▼
弃权方该阶段得分为 0
    │
    ▼
D06 降级: 明鉴秋基于已有数据裁决
```

### 6.3 守护进程崩溃

```
daemon_watchdog.py 检测 (每30分钟)
    │
    ├─ 检查 memory/daemon.pid 存在?
    ├─ 检查 memory/schedule_state.json 心跳 <3min?
    │
    ├─ 存活 → 正常
    │
    └─ 挂了 → 自动重启
              ├─ 清理旧 PID 文件
              ├─ 重新 bootstrap.py daemon
              └─ 记录重启事件
```

## 7. 看门狗 (Watchdog)

### 7.1 守护进程看门狗

| 项 | 内容 |
|:---|:-----|
| **脚本** | `scripts/daemon_watchdog.py` |
| **触发** | 定时任务每 30 分钟 |
| **检查** | PID 存活 + 心跳日志 3 分钟内更新 |
| **恢复** | 自动重启守护进程 |

### 7.2 Agent 看门狗

| 项 | 内容 |
|:---|:-----|
| **配置** | `team_config.json` → `agent_watchdog_seconds: 420` (7分钟) |
| **作用** | 超过 7 分钟无产出的 Agent 标记为超时 |
| **恢复** | D06 降级 |

## 8. 多因子增强降级

### 8.1 100ppi 现期表不可用

| 场景 | 现象 | 降级路径 |
|:-----|:-----|:---------|
| 100ppi.com/sf/ 被 HW_CHECK 拦截 | `_collect_basis_data_sync()` 返回空 dict | **自动降级到 TdxCollector 近月合约代理（v8.8.7）**，`_collect_basis_via_nearmonth()` 使用近月合约价作为现货代理 |
| 100ppi 页面结构变化 | `_parse_100ppi_sf_page()` 解析器返回空 | 同上；自动降级到近月代理 |
| TDX 本地也不可用 | TdxCollector.is_available=False | V3 基差+低波联合增强静默跳过，退化为纯 ATR% 判断 |
| **影响** | 基差来源变为近月代理（标注 `data_source=near_month_proxy`，`unit=元/吨(近月代理)`），方向信号可靠但幅度为近似值 | 跨品种配对（pair spread）不受影响（仅用期货价） |
| **恢复** | 100ppi 恢复后自动切回真实现货价；下次扫描自动重试 |

#### 8.1.1 近月代理降级原理

当 100ppi 不可用时，`_collect_basis_data_sync()` 自动调用 `_collect_basis_via_nearmonth()` 降级函数：

1. 通过 TdxCollector.get_term_structure(symbol) 获取品种的**全部合约期限结构**
2. 取**近月合约价格**（最靠近交割月）作为现货价格的代理
3. 计算 `basis = near_price - main_contract_price`（信号中的主力合约价）
4. 返回格式与真实基差同构，但 `unit` 标注为 `"元/吨(近月代理)"`，新增 `data_source: "near_month_proxy"`

**金融逻辑支撑**：期货近月合约临近交割时通过期现套利收敛于现货。用近月价 vs 主力价的价差方向与真实基差一致（Backwardation->basis>0, Contango->basis<0），可用于信号验证器的方向性判断。

**下游标注要求**：消费方（`atr_vol_timing.py` / `p0_4_raw_kline.py`）读取 `basis_pct` 时，各阈值判断逻辑不变，但认知上应视为方向性参考而非精确基差幅度。

**适用边界**：
- 有实物交割的黑色/有色/能化/农产品 -- 收敛机制可靠
- 现金结算品种（如 ec 集运指数）-- 无实物交割，跳过降级
- 近月流动性差的品种 -- TdxCollector 返回空合约列表则跳过

### 8.2 OI 数据不可用

| 场景 | 降级 |
|:-----|:------|
| TDX 不返回 `oi` 字段 | `_collect_oi_data_sync()` 返回空 dict → V2 OI 量比联合跳过 → 退化为纯量比判断 |
| **恢复** | 下次 TDX 查询自动恢复 |

## 9. LangGraph 并行节点降级策略 (v8.3.0+)

### 9.1 降级架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                    LangGraph 降级体系                                │
├────────────────────┬────────────────────┬───────────────────────────┤
│   P2 四源并行降级  │   P3 辩论降级       │   P4+P5 裁决链降级         │
├────────────────────┼────────────────────┼───────────────────────────┤
│  单源失败不影响其他 │ 单辩手失败继续辩论   │ 闫判官(含交易参数)失败→D06 降级 │
│ 超时自动跳过       │ 超时自动跳过        │ 闫判官失败→风控明降级      │
│ 部分结果继续流程   │ 部分论据继续裁决     │ 风控明失败→明鉴秋兜底      │
└────────────────────┴────────────────────┴───────────────────────────┘
```

### 9.2 P2 四源并行降级

| 数据源 | 超时时间 | 降级行为 | 影响 |
|:-------|:---------|:---------|:-----|
| 链证源 | 300s | 自动跳过，标记 `chain_analysis=null` | 缺少产业链视角 |
| 观澜 | 300s | 自动跳过，标记 `technical_data={}` | 缺少技术面视角 |
| 探源 | 300s | 自动跳过，标记 `fundamental_data={}` | 缺少基本面视角 |
| 读心 | 300s | 自动跳过，标记 `sentiment_data={}` | 缺少新闻情绪视角 |

**P2 降级流程**:
```
闫判官调度决策 → 并行触发四源（链证源/观澜/探源/读心）
                    │
        ┌───────────┼───────────┬───────────┐
        ▼           ▼           ▼           ▼
    [chain:链证源] [technical:观澜] [fundamental:探源] [sentiment:读心]
        │           │           │           │
        ├─ 成功 ───┼── 成功 ───┼─ 成功 ───┼─ 成功 → merge_research (完整)
        │           │           │           │
        ├─ 失败 ───┼── 成功 ───┼─ 成功 ───┼─ 成功 → merge_research (缺少产业链)
        │           │           │           │
        ├─ 失败 ───┼── 失败 ───┼─ 成功 ───┼─ 成功 → merge_research (仅基本面+情绪)
        │           │           │           │
        └─ 失败 ───┴── 失败 ───┴─ 失败 ───┴─ 失败 → 触发 P3 降级告警，继续辩论（无研究员资料）
```

### 9.3 P3 六阶段辩论降级 (v9.0.0)

| 辩论阶段 | 节点 | 超时时间 | 降级行为 | 影响 |
|:---------|:-----|:---------|:---------|:-----|
| 多头初论 P3_1 | `node_bullish_v1` | 600s | 自动跳过，`bullish_arguments=[]` | 缺少多头初论 |
| 空头初论 P3_2 | `node_bearish_v1` | 600s | 自动跳过，`bearish_arguments=[]` | 缺少空头初论 |
| 空头驳论 P3_3 | `node_bearish_rebuttal` | 600s | 自动跳过，`bearish_rebuttal_arguments=[]` | 缺少空头反驳 |
| 多头驳论 P3_4 | `node_bullish_rebuttal` | 600s | 自动跳过，`bullish_rebuttal_arguments=[]` | 缺少多头反驳 |
| 空头结辩 P3_5 | `node_bear_final` | 600s | 自动跳过，`bear_final_arguments=[]` | 缺少空头结辩 |
| 多头结辩 P3_6 | `node_bull_final` | 600s | 自动跳过，`bull_final_arguments=[]` | 缺少多头结辩 |

### 9.4 P4 闫判官终裁降级 + P5 风控明降级

```
闫判官 (verdict，含完整交易参数)
    │
    ├─ 成功 → 风控明 (risk_check，直接基于闫判官 verdict 审核)
    │              │
    │              ├─ 成功 → 报告生成
    │              │              │
    │              │              ├─ 成功 → CTP 信号输出 (v8.7.0 新增)
    │              │              │              │
    │              │              │              ├─ risk_color=green → 输出 CTP 交易信号
    │              │              │              ├─ risk_color=yellow → 按阈值决定
    │              │              │              └─ risk_color=red → 信号阻断
    │              │              │
    │              │              └─ 失败 → 明鉴秋兜底（记录风险警告）
    │              │
    │              └─ 失败 → 明鉴秋兜底（简化风控审核）
    │
    └─ 失败 → D06 降级: 明鉴秋基于 P2(四源)+P3(辩论) 论据独立裁决
              ├─ 生成简化 verdict（含默认交易参数）
              ├─ 生成简化 risk_check
              └─ CTP 信号输出节点继续按 risk_color 决定
```

### 9.5 节点超时配置

| 节点 | 默认超时 | 可配置 |
|:-----|:---------|:-------|
| `node_scan` | 180s | 是 |
| `node_judge_direction` | 120s | 是 |
| `node_chain` | 300s | 是 |
| `node_technical` | 300s | 是 |
| `node_fundamental` | 300s | 是 |
| `node_merge_research` | 60s | 是 |
| `node_debate` | 600s | 是 |
| `node_verdict` | 300s | 是 |
| `node_risk_check` | 120s | 是 |
| `node_report` | 180s | 是 |
| `node_signal_output` (v8.7.0 新增) | 60s | 是 |

### 9.5.1 报告层降级 (v8.8.0+)

明鉴秋负责 P1/P3/P5/P6/P6a 五个阶段报告生成。各阶段报告均具备降级策略：

| 阶段 | 节点 | 失败降级 | 用户感知 |
|:-----|:-----|:---------|:---------|
| P1 | `node_scan` | 写日志 warning，状态 `scan_report_path=None`，主流程继续 | 无扫描报告，不影响后续阶段 |
| P3 | `node_merge_research` | 写日志 warning，状态 `research_report_path=None` | 无研究报告，不影响辩论 |
| P5 | `node_risk_check` | 写日志 warning，状态 `verdict_report_path=None` | 无裁决报告，信号输出正常 |
| P6 | `node_report` | fallback 写入工作空间下 `debate_report_{trace_id}.html`（使用 `_render_html()` 模板），保证 `report_path` 永远有效 | 报告内容简化但不丢失 |
| P6a | `node_signal_output` | 写日志 warning，状态 `signal_report_path=None`，CTP 信号正常输出 | 无信号扫描报告，CTP 正常 |

**环境变量降级**：
- `FDT_REPORT_WORKSPACE` 不可用（路径不可写）→ 回退到 `FDT_DAILY_WORKSPACE`
- 两者皆不可用 → 回退到 `tempfile.gettempdir()/fdt_reports`（永远可写）

### 9.6 PostgreSQL 降级

| 场景 | 降级行为 | 恢复策略 |
|:-----|:---------|:---------|
| 连接池耗尽 | 使用 SQLite 内存模式缓存 | 连接池恢复后自动同步 |
| OLAP 查询超时 | 跳过 OLAP 查询，使用 OLTP 数据 | 下次查询自动恢复 |
| 数据库不可用 | 仅内存运行，结果不持久化 | 数据库恢复后手动同步 |

### 9.7 LangGraph 检查点恢复

```
Checkpointer (PostgreSQL)
    │
    ├─ 正常: 每次节点执行后保存状态
    │
    ├─ 中断恢复:
    │   ├─ graph.get_state(trace_id) 获取最近状态
    │   ├─ 从失败节点重新执行
    │   └─ 自动跳过已完成节点
    │
    └─ 断点续跑:
        ├─ graph.continue_execution(trace_id)
        └─ 从上次检查点继续执行
```

### 9.8 与原有降级体系的映射

| 原有机制 | LangGraph 对应 | 状态 |
|:---------|:--------------|:-----|
| S04 轮询 | Checkpointer + 状态传递 | 已替代 |
| D06 降级 | `node_verdict` 失败 → 明鉴秋兜底 | 已迁移 |
| Agent 超时 | 节点超时配置 + 自动跳过 | 已迁移 |
| 守护进程看门狗 | `fdt_cli.py daemon` + APScheduler | 已替代 |
| 外部心跳 | `fdt_api.py /health` + 进程监控 | 已替代 |

### 9.9 LangGraph 降级策略 (v8.4.0+ — G52-G55)

> 本节登记 LangGraph 生产集成（G52-G55）的降级路径。

#### 9.9.1 Checkpointer 降级路径

| 降级场景 | 触发条件 | 降级行为 | 影响 | 恢复 |
|:---------|:---------|:---------|:-----|:-----|
| **PG Checkpointer 连接失败** | `FDT_CHECKPOINTER=pg` 时 PostgreSQL 连接超时/拒绝 | `_get_checkpointer()` 自动降级到 SQLite Checkpointer（内存/本地文件） | 检查点持久化从 PG 退化为 SQLite，单机可用 | PG 恢复后重启进程切换回 PG |

## 10. Data-Core / FDC 降级 (v9.4.0+)

### 10.1 降级架构

FDT 的 F10 数据模块通过 `_datacore_bridge.py`（`futures_data_core/core/_datacore_bridge.py`）实现 Data-Core 优先的降级链：

```
F10 模块入口 (term_structure / spread / basis / warrant / fundamental / position)
    │
    ├─ _try_datacore_first("func_name", symbol)
    │   │
    │   ├─ datacore.fdc_compat 可导入 → 返回 Data-Core 数据 (dict)
    │   │                                   │
    │   │                                   └─ 数据有效 → 包装为 A2APayload 返回
    │   │                                   │
    │   │                                   └─ 数据为空 → 回退原有实现 (fallthrough)
    │   │
    │   └─ datacore 不可导入 (ImportError) ─→ 回退原有实现 (fallthrough)
    │
    └─ 原有实现 (TDX/QMT/TqSDK 等直连)
```

### 10.2 F10 桥接函数映射

| F10 模块 | 桥接函数 | Data-Core 接口 | 降级行为 |
|:---------|:---------|:---------------|:---------|
| `term_structure.py` | `get_term_structure` | `dc.get_term_structure(symbol)` | Data-Core 返回空时走 TDX/QMT |
| `spread.py` | `get_spread` | `dc.get_spread(symbol)` | Data-Core 返回空时走 TDX |
| `basis.py` | `get_basis` | `dc.get_basis(symbol)` | Data-Core 返回空时走生意社+QMT |
| `warrant.py` | `get_warrant` | `dc.get_warrant(symbol)` | Data-Core 返回空时走交易所直连 |
| `fundamentals.py` | `get_fundamental` | `dc.get_fundamental(symbol)` | Data-Core 返回空时走缓存+爬虫 |
| `position.py` | `get_position_ranking` | `dc.get_position_ranking(symbol)` | Data-Core 返回空时走交易所直连 |

### 10.3 降级判定标准

Data-Core 的结果被视为"有效"的条件（任一满足）：
- 返回的 dict 非空 (`bool(result) == True`)
- 包含预期字段（如 `basis` 有 `basis` 或 `basis_pct`，`term_structure` 有 `structure` 或 `contracts`）
- 未抛出任何异常（ImportError / TimeoutError / Exception 均视为不可用）

### 10.4 数据源标注

当 Data-Core 提供数据时：
- `A2APayload.meta.sources` 中包含 `"datacore"` 标记
- `A2APayload.data_grade` 沿用 Data-Core 返回中的 `data_grade`；无标注时设为 `"STALE"`
- 当回退到原有实现时，`sources` 中不包含 `"datacore"` 标记
