# FDT 自建品种分析逻辑知识库 — 可行性评估与实施方案

> 生成日期: 2026-07-11 07:16 | 版本: v1.1 | 状态: Phase 1+2 已实施 (2026-07-11)
> - ✅ **Phase 1 基础设施**: memory/knowledge/84品种目录 + extract_knowledge.py + init_knowledge_base.py + memory_writer.py 扩展
> - ✅ **Phase 2 自动化集成**: evolve_agents.py 嵌入式萃取 + 6 Agent 消费端注入 + 每日老化自动化
> - 📋 **Phase 3 待规划**: 向量检索集成 + 仪表盘

---

## 一、结论先行

**可实现，且现有基础设施已覆盖 60% 的工程需求。** FDT 的自进化闭环（validate → calibrate → evolve → ML train）和现有记忆系统（instrument_strategy_matrix、argument_patterns、agent_profiles 等）提供了扎实的底座。缺失的 40% 在于：缺乏一个**结构化、按品种组织、可程序化检索与更新**的品种分析逻辑知识库，以及配套的自动化采集与消费链路。

核心思路：**在现有自循环中嵌入一层"知识萃取"，将每轮辩论产生的品种特异性洞察沉淀为可复用的知识条目**，而非散落在永久的辩论日志中。

---

## 二、可行性评估维度

### 2.1 技术可行性 ✅

| 维度 | 评估 | 依据 |
|:----|:----|:-----|
| 数据源 | ✅ 每轮辩论产出完整的 P1-P6 结构化 JSON | 通道突破信号、研究员快照、证真/慎思论据、闫判官裁决、策执远方案 |
| 存储载体 | ✅ 已有 JSON + Markdown + 向量化记忆 | `instrument_strategy_matrix.json`（EMA在线更新）、`vector_memory.py` |
| 自动化流程 | ✅ 自进化闭环已运行 | validate_verdicts.py → calibrate_weights.py → evolve_agents.py |
| 检索能力 | ✅ Python 文件读取 + 向量检索基础 | `vector_memory.py` 已有向量化记忆实现 |

### 2.2 架构兼容性 ✅

| 现有组件 | 与新知识库的关系 |
|:---------|:----------------|
| `instrument_strategy_matrix.json` | 可作为品种知识库的定量层（F1-F5 适应性权重 + 胜率统计） |
| `argument_patterns.md` | 可作为品种知识库的定性层（有效论证模式，按品种归类） |
| `judgment_revisions.md` | 可作为品种知识库的规则层（R01-R10 等品种特异性规则） |
| `agents/futures-judge.md` | 闫判官可在裁决后自动调用知识萃取 |
| `scripts/memory_writer.py` | 扩展写入目标，增加知识库文件 |
| `scripts/evolve_agents.py` | 扩展演化逻辑，增加知识库参数 |
| `scripts/bootstrap.py` | 可扩展为知识库初始化/重建脚本 |

### 2.3 工程风险

| 风险 | 等级 | 缓解措施 |
|:----|:----:|:---------|
| 知识噪音（无效论证被入库） | 🟡 | 仅在裁决验证通过后才入库（confidence ≥ 0.6） |
| 知识膨胀（无上限积累） | 🟡 | TTL 机制 + 容量上限 + 低效知识自动降级 |
| 辩手跑偏（过度依赖历史知识） | 🟠 | 知识库设计为"参考层"而非"决策层"，优先使用当期数据 |
| 平台规则冲突（plugins/marketplaces 操作限制） | 🔴 | 知识库写入仅在 `memory/` 目录内，不涉及 plugins 目录结构修改 |

---

## 三、方案设计

### 3.1 知识库体系总览

```
memory/knowledge/                          # 品种分析逻辑知识库根目录
├── variety_index.json                     # 品种知识索引（目录）
├── rb/
│   ├── profile.json                      # 品种基础画像（静态）
│   ├── drivers.md                        # 核心驱动因子（动态更新）
│   ├── patterns.json                     # 有效论证模式（辩论萃取）
│   ├── key_levels.json                   # 关键价位（技术积累）
│   └── data_quality.json                 # 数据源质量（降级追踪）
├── sc/
│   ├── profile.json
│   ├── drivers.md
│   ├── patterns.json
│   ├── key_levels.json
│   └── data_quality.json
└── ...                                   # 62品种各一套
```

### 3.2 知识分层

| 层次 | 内容 | 更新频率 | 来源 |
|:----|:-----|:--------|:-----|
| **L1 静态画像** | 品种名称、合约规格、所属产业链、季节性规律、历史波动率区间 | 月/季度 | `varieties.yaml` + 初始化脚本 |
| **L2 驱动因子** | 影响该品种的核心因素（如 RB: 地产开工+限产政策+铁矿成本） | 每轮辩论后增量更新 | 探源研究员产出 + 闫判官裁决提炼 |
| **L3 有效模式** | 该品种上有效的论证结构（如 SC: F4>F1 更有效） | 每轮辩论验证后 | `argument_patterns.md` 按品种拆分 |
| **L4 关键价位** | 品种关键支撑/阻力位、持仓量密集区 | 日线更新 | `technical-analysis/support_resistance.py` |
| **L5 数据质量** | 各数据源在该品种上的可靠性评分、延迟天数、降级记录 | 每次数据采集后 | `data_sources.md` 按品种拆分 |

### 3.3 核心数据模型

#### variety_index.json — 品种知识索引

```json
{
  "version": "1.0",
  "last_updated": "2026-07-11 07:00",
  "varieties": {
    "rb": {
      "name": "螺纹钢",
      "chain": "黑色系",
      "exchange": "SHFE",
      "knowledge_dir": "memory/knowledge/rb/",
      "profile_updated": "2026-07-10",
      "drivers_updated": "2026-07-10",
      "patterns_updated": "2026-07-09",
      "key_levels_updated": "2026-07-11",
      "data_quality_updated": "2026-07-10",
      "total_debates": 5,
      "effective_patterns": 3,
      "avg_confidence": 0.72
    }
  }
}
```

#### rb/profile.json — 品种静态画像

```json
{
  "code": "rb",
  "name": "螺纹钢",
  "exchange": "SHFE",
  "unit": "10t/手",
  "chain": "黑色系",
  "sub_chain": "建材",
  "related_varieties": ["hc", "i", "jm", "j"],
  "seasonality": {
    "strong_months": [3, 4, 9, 10],
    "weak_months": [1, 2, 7, 8],
    "note": "金三银四+金九银十传统旺季"
  },
  "volatility_profile": {
    "average_atr_pct": 2.1,
    "adx_trending_threshold": 25,
    "adx_exhausted_threshold": 65
  },
  "key_drivers": [
    {"driver": "房地产开工", "weight": 0.35, "data_source": "国家统计局"},
    {"driver": "基础设施投资", "weight": 0.25, "data_source": "国家统计局"},
    {"driver": "钢厂限产政策", "weight": 0.20, "data_source": "Mysteel/政策文件"},
    {"driver": "铁矿石成本", "weight": 0.10, "data_source": "普氏62%指数"},
    {"driver": "社会库存", "weight": 0.10, "data_source": "Mysteel周度库存"}
  ]
}
```

#### rb/patterns.json — 品种有效论证模式

```json
{
  "code": "rb",
  "updated": "2026-07-10 15:30",
  "patterns": [
    {
      "pattern_id": "rb-p001",
      "name": "限产驱动型多头",
      "first_observed": "2026-07-04",
      "last_used": "2026-07-09",
      "use_count": 2,
      "win_count": 2,
      "win_rate": 1.0,
      "structure": "限产政策 → 供应收缩 → 库存下降 → 利润扩张 → 价格上行",
      "applicable_conditions": {
        "season": ["3-6月", "9-11月"],
        "adx_range": [20, 50],
        "signal_type": ["channel_breakout"]
      },
      "key_evidence_sources": ["Mysteel产量数据", "政策文件"],
      "derived_from_debates": ["debate_20260704_rb", "debate_20260709_rb"],
      "confidence": 0.75
    }
  ]
}
```

### 3.4 自动化知识萃取流程

**核心思想**: 不创建独立的新流程，而是将知识萃取嵌入 FDT 现有自循环中。

```
                           FDT 现有自循环
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  辩论执行 → 裁决归档 → validate → calibrate → evolve → ML训练   │
│     │                                     │                     │
│     └──→ 知识萃取新步骤 ←─────────────────┘                     │
│           │                                                     │
│           ├── 1. 从 debate_record 提取品种特异性洞察              │
│           │    - 胜方论证结构 → patterns.json                    │
│           │    - 闫判官裁决关键因子 → drivers.json 更新权重       │
│           │    - 策执远入场/止损/目标 → key_levels.json          │
│           │    - 数据源降级记录 → data_quality.json              │
│           │                                                     │
│           ├── 2. 质量门控                                       │
│           │    - 仅 confidence ≥ 0.6 的裁决进入萃取               │
│           │    - 仅有 post-verification (validate) 确认后才入库   │
│           │    - 新模式需 ≥ 2 次验证才标记为 effective            │
│           │                                                     │
│           ├── 3. 增量写入                                        │
│           │    - 使用 `memory_writer.py` 扩展                    │
│           │    - 原子写入: .tmp → rename                         │
│           │    - 更新 variety_index.json 索引                    │
│           │                                                     │
│           └── 4. 知识老化                                       │
│               - 60天未见 used 的模式自动降级 weight               │
│               - 连续 3 次失败的模式标记 deprecated               │
│               - 总量上限: 每品种 ≤ 20 个有效模式                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 知识消费机制

知识在辩论过程中的使用方式：

```
辩论启动
    │
    ├── P1 数技源扫描 → 通道突破信号
    │
    ├── P1.5 链证源 → 读取 knowledge/{variety}/profile.json 产业链定位
    │                        读取 knowledge/{variety}/drivers.md 驱动因子权重
    │
    ├── P2 闫判官决策 → 读取 knowledge/{variety}/patterns.json
    │                    （仅参考：该品种历史有效模式，辅助方向判断）
    │
    ├── P3 研究员供弹 → 观澜/探源读取 knowledge/{variety}/key_levels.json
    │                     （关键价位作为技术分析的输入参考）
    │                    读取 knowledge/{variety}/data_quality.json
    │                     （数据源优先级+降级信息）
    │
    ├── P4 辩论 → 证真/慎思读取 knowledge/{variety}/patterns.json
    │               （历史有效模式作为论证参考，但不作为唯一依据）
    │               **关键规则**: 知识库只提供"模式参考"，严禁直接复制历史论据
    │
    ├── P5 裁决+风控 → 策执远读取 knowledge/{variety}/key_levels.json
    │                    （关键价位辅助止损/目标设定）
    │
    └── P6 汇总 → 触发知识萃取（基于本辩论结果更新知识库）
```

### 3.6 实施方案

#### Phase 1：基础设施搭建（预计 2-3 小时）

| 步骤 | 内容 | 涉及文件 |
|:----|:-----|:---------|
| 1.1 | 创建 `memory/knowledge/` 目录结构 + 品种目录初始化 | 新目录 + `variety_index.json` |
| 1.2 | 编写 `scripts/extract_knowledge.py` — 从 debate_record 中萃取知识 | 新文件 |
| 1.3 | 编写 `scripts/init_knowledge_base.py` — 从现有数据批量初始化 | 新文件 |
| 1.4 | 扩展 `scripts/memory_writer.py` — 增加知识库写入函数 | 修改现有文件 |

#### Phase 2：自动化集成（预计 2-3 小时）

| 步骤 | 内容 | 涉及文件 |
|:----|:-----|:---------|
| 2.1 | 在 `evolve_agents.py` 中嵌入知识萃取步骤 | 修改 `evolve_agents.py` |
| 2.2 | 在闫判官 agent prompt 中增加知识库消费指令 | 修改 `agents/futures-judge.md` |
| 2.3 | 在研究员 prompt 中增加知识库读取指令 | 修改研究员 agents |
| 2.4 | 知识老化机制：`scripts/knowledge_decay.py` | 新文件，定时任务触发 |

#### Phase 3：消费侧优化（预计 2-3 小时）

| 步骤 | 内容 | 涉及文件 |
|:----|:-----|:---------|
| 3.1 | 向量检索集成：使用 `vector_memory.py` 对知识条目做语义检索 | 修改 `vector_memory.py` |
| 3.2 | 在明鉴秋 prompt 中增加知识库注入逻辑 | 修改 team-lead agent |
| 3.3 | 知识库健康度监控：每个品种的模式数量/胜率/时效性 | 新 dashabord 入口 |

**以上总计 6-9 小时，可分 3 个独立波次实施，各波次之间互不阻塞。**

### 3.7 与现有系统的关键接口

```python
# scripts/extract_knowledge.py — 知识萃取入口

def extract_variety_knowledge(
    variety: str,
    debate_record: dict,       # 完整辩论记录
    verdict: dict,             # 闫判官裁决
    technical_data: dict,      # 观澜技术分析产出
    fundamental_data: dict,    # 探源基本面产出
    trading_plan: dict         # 策执远交易方案
) -> dict:
    """
    从一轮辩论中提取品种特异性知识。
    返回增量更新内容，由调用方写入 knowledge/{variety}/ 下对应文件。
    """
    knowledge_delta = {
        "patterns": [],    # 有效论证模式
        "drivers": {},     # 驱动因子权重更新
        "key_levels": {},  # 关键价位
        "data_quality":{}  # 数据源质量
    }
    
    # 1. 提取有效论证模式
    if verdict.get("confidence", 0) >= 0.6:
        winner_side = verdict.get("winner", "")
        winner_args = debate_record.get(f"{winner_side}_args", [])
        pattern = _extract_pattern(variety, winner_args, verdict)
        if pattern:
            knowledge_delta["patterns"] = [pattern]
    
    # 2. 提取关键价位
    if trading_plan:
        knowledge_delta["key_levels"] = {
            "entry": trading_plan.get("entry"),
            "stop_loss": trading_plan.get("stop_loss"),
            "targets": [
                trading_plan.get("target1"),
                trading_plan.get("target2")
            ],
            "extracted_from": verdict.get("round_id", ""),
            "confidence": verdict.get("confidence", 0)
        }
    
    # 3. 更新数据源质量
    # ...
    
    return knowledge_delta


def update_variety_knowledge(
    knowledge_dir: str,
    delta: dict,
    variety_index: dict
) -> bool:
    """
    原子写入品种知识更新。
    写 .tmp → rename 确保一致性。
    """
    # 将 delta.patterns 合并到 patterns.json
    # 将 delta.key_levels 合并到 key_levels.json
    # 更新 variety_index.json 的 updated 时间戳
    pass
```

### 3.8 知识库的消费方式

在辩手 prompt 中新增注入段落：

```
## 【📖 品种分析逻辑知识库参考（知识层·非决策层）】

当前品种 {variety} 的历史知识摘要：

### 有效论证模式
{knowledge_summary}

### 核心驱动因子权重
{drivers_summary}

### 关键价位参考
{key_levels_summary}

**⚠️ 使用规则**：
1. 知识库仅为论证参考，不作为论据主体
2. 论据必须基于当期研究员数据，严禁直接复制历史论据
3. 若当期数据与知识库矛盾，以当期数据为准
```

---

## 四、建设路径建议

### 推荐实施顺序

```
第一波（3h）: Phase 1 — 基础设施搭建
  创建 memory/knowledge/ 目录 + extract_knowledge.py + init_knowledge_base.py
  → 手动验证：跑一次初始化脚本，检查知识库文件生成正确

第二波（2h）: Phase 2 核心集成
  嵌入 evolve_agents.py + 更新 memory_writer.py
  → 跑一轮全量辩论，验证知识自动萃取

第三波（2h）: Phase 2-3 消费端
  更新辩手/研究员/闫判官 agent prompt
  + 知识老化机制
  → 跑一轮消费验证

第四波（2h）: Phase 3 增强
  向量检索 + 监控仪表盘
```

### 不建议当前实施的部分

- ❌ 不要建独立的知识库 API 服务（增加运维负担，与 FDT 独立系统设计理念冲突）
- ❌ 不要建 Web UI（FDT 是 CUI 系统，用 CLI 和文件交互）
- ❌ 不要对已入库知识做 LLM 重写（引入语义漂移风险）

---

## 五、预期效果

### 短期效果（1-2 轮辩论后）

| 指标 | 当前 | 预期 |
|:----|:----:|:----:|
| RB 论证质量 | 每次从零构建 | 可复用历史有效模式 |
| SC 驱动因子识别 | 依赖探源每次搜索 | 知识库预置 + 增量更新 |
| 新辩论品种适应 | 无历史数据可用 | 初始化驱动因子 + 产业链同类推断 |
| 数据源选择 | 固定优先级 | 逐品种 p 数据源质量排序 |

### 中长期效果（10+ 轮辩论后）

- 各品种的知识库积累 5-15 条有效论证模式
- 驱动因子权重趋于稳定，反映品种真实价格驱动结构
- 数据源降级历史可用于数据采集策略的自适应优化
- 跨品种知识迁移：同产业链品种的模式可交叉验证

---

## 六、是否需要先做 PoC 再全量实施？

**建议：直接全量实施，跳过 PoC。**

理由：
1. 基础设施改动范围小（新增 ~3 个 Python 脚本 + 修改 ~2 个现有脚本）
2. 与现有自循环的解耦设计使得回滚极其容易（删除 `memory/knowledge/` 目录 + 回退 2 个脚本的修改）
3. 知识提取是一个"有更好，没有也不影响核心流程"的增强功能，不影响现有辩论质量
4. 现有的 `instrument_strategy_matrix.json` 和 `argument_patterns.md` 可以作为新知识库的 seed data 直接导入

---

## 附录：现有基础设施对照

| 功能 | 现状 | 是否满足新知识库需求 |
|:----|:----|:------------------|
| 品种静态信息 | `varieties.yaml` + `overseas_varieties.yaml` | ✅ 可整表导入 |
| 定量适应性矩阵 | `instrument_strategy_matrix.json` (F1-F5×品种) | ✅ 作为 L1 定量层 |
| 论证模式 | `argument_patterns.md` (按通用类型，非按品种) | ⚠️ 需要按品种拆分 + 结构化 |
| 裁决修正 | `judgment_revisions.md` (R01-R10 全品种规则) | ✅ 作为 L0 全品种规则层 |
| Agent 进化 | `evolve_agents.py` (权重/ATR 乘数等参数) | ✅ 扩展进化范围 |
| 记忆写入 | `memory_writer.py` | ✅ 扩展知识写入函数 |
| 辩论记录 | `debate_journal.json` + `debates/INDEX.md` | ✅ 知识萃取的数据源 |
| 向量记忆 | `vector_memory.py` | ✅ 作为增强检索机制 |
| 自进化闭环 | validate → calibrate → evolve | ✅ 知识萃取嵌入 evolve 阶段 |
