# FDT 记忆系统重构设计文档

- **版本**: v1.0
- **日期**: 2026-07-24
- **状态**: 设计阶段
- **前置文档**: [01-architecture.md](../harness/01-architecture.md), [02-lifecycle.md](../harness/02-lifecycle.md)

---

## 1. 动机与背景

### 1.1 现状问题

FDT 的 `memory/` 目录经过多次迭代累积，呈现出严重的碎片化和僵尸代码问题：

| 问题 | 严重度 | 说明 |
|:-----|:------:|:-----|
| 散乱直写 | P0 | `nodes.py`/`master_nodes.py` 中约 26 处 `json.dump`/`json.load` 直写 `memory/`，无统一入口 |
| 僵尸代码 | P0 | 6 个完整模块（~1300 行）零生产引用：`memory_writer.py`、`memory_retriever.py`、`memory_enforcer.py`、`memory_cleaner.py`、`debate_archiver.py`、`trading_memory.py` |
| 检索断层 | P1 | `memory_retriever._query_local()` 是 `return []` stub，三层记忆架构只有写没有读 |
| 知识老化停摆 | P1 | `extract_knowledge.run_decay()` 完整实现但从未被任何生产路径调用 |
- 文档缺口 | P1 | `check_memory_gaps.py` 被 `harness-rules.yaml` 引用但从未创建 |
| 版本号鸿沟 | P1 | `changelog.md` 停留在 v8.1.8，但系统实际版本为 v9.23.0 |
| 僵尸目录 | P2 | `evolutions/`（40文件）、`debates/`、`changelog/`、`state/` 已停更或废弃 |
| 双写矛盾 | P2 | `debate_journal.json` 被 `nodes.py`（实际路径）和 `memory_enforcer.py`（僵尸路径）两套逻辑写入 |

### 1.2 重构目标

1. **统一入口**：所有 memory/ 的读写走 `MemoryManager` 单一入口，消灭散落直写
2. **消除僵尸**：删除 6 个零引用脚本，废弃目录归档
3. **接通检索**：修复检索断层，让历史经验实际注入辩论决策
4. **自动化维护**：知识老化、TTL 清理、缺口检查纳入定时调度
5. **Schema 化**：所有写入数据有 `TypedDict` 契约校验

---

## 2. 整体架构

```
                           ┌──────────────────────────┐
                           │   调用方（只改 3 处）      │
                           │  nodes.py / master_nodes  │
                           │  evolve_agents.py         │
                           └────────────┬─────────────┘
                                        │ get_memory()
                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                     MemoryManager (manager/manager.py)            │
│                                                                   │
│  store_journal()       store_knowledge()        store_experience()│
│  store_incident()      store_schedule()                           │
│                                                                   │
│  retrieve_similar()    retrieve_journal()      retrieve_knowledge │
│  retrieve_experience()                                            │
│                                                                   │
│  run_maintenance()     check_gaps()                               │
│  migrate_from_legacy()                                            │
└───────┬─────────────────────┬────────────────────┬───────────────┘
        │                     │                    │
        ▼                     ▼                    ▼
┌───────────────┐   ┌────────────────┐   ┌────────────────┐
│   存储层       │   │   检索层        │   │   维护层        │
│ store/        │   │ retrieval/     │   │ maintenance/   │
│ journal_store │   │ vector_retriever│   │ cleaner        │
│ knowledge_store│   │ knowledge_rtvr │   │ archiver       │
│ experience_str│   │ historical_rtvr│   │ decay          │
│ incident_store│   │                │   │ checker        │
└───────┬───────┘   └───────┬────────┘   └───────┬────────┘
        │                   │                    │
        ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                         FDT memory/ 目录                          │
│  journal/  knowledge/  experience/  schedule_state.json           │
│  incidents/  rules/  revisions/  policies/  performance/         │
│  tech_debt/  archive/                                      │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 数据流变化

```
重构前：
  nodes.py ──json.dump──→ memory/journal/debate_journal.json    (散落，无校验)
  nodes.py ──json.load──→ memory/knowledge/variety_index.json   (散落，每处格式不同)
  nodes.py ──直接调用──→ VectorMemory.query()                    (try/except 包着)

重构后：
  nodes.py ──→ get_memory().store_journal()  ──→ journal_store.py ──→ journal/
  nodes.py ──→ get_memory().retrieve_knowledge() ──→ knowledge_store.py ──→ knowledge/
  nodes.py ──→ get_memory().retrieve_similar() ──→ vector_retriever.py ──→ VectorMemory
```

### 2.2 目录结构变更

```
memory/
├── manager/                    # [新] MemoryManager 核心
│   ├── __init__.py             # global_memory 单例 + get_memory()
│   ├── manager.py              # MemoryManager 主类
│   ├── schemas.py              # 所有 TypedDict 契约
│   └── config.py               # 路径映射 + TTL + 存储限额
├── store/                      # [新] 存储层
│   ├── __init__.py
│   ├── journal_store.py        # 辩论日志
│   ├── knowledge_store.py      # 品种知识
│   ├── experience_store.py     # 经验记录
│   └── incident_store.py       # 事故记录
├── retrieval/                  # [新] 检索层
│   ├── __init__.py
│   ├── vector_retriever.py     # 整合 VectorMemory
│   ├── knowledge_retriever.py  # 品种知识检索
│   └── historical_retriever.py # 历史案例检索
├── maintenance/                # [新] 维护层
│   ├── __init__.py
│   ├── cleaner.py              # TTL + 存储限容
│   ├── archiver.py             # 归档 + 压缩
│   ├── decay.py                # 知识老化
│   └── checker.py              # check_memory_gaps.py
│
├── archive/                    # [新] 历史归档
│   └── 20260724_backup/        # 废弃目录迁入处
│
├── journal/                    # [保] 辩论日志（只读）
├── knowledge/                  # [保] 品种知识（只读）
├── experience/                 # [保] 经验（只读）
├── rules/                      # [保] 铁律（只读）
├── incidents/                  # [保] 事故（只读）
├── revisions/                  # [保] 修正（只读）
├── policies/                   # [保] 风控（只读）
├── performance/                # [保] 性能（只读）
├── tech_debt/                  # [保] 技术债务（只读）
│
├── evolutions/                 # [→archive] 僵尸目录
├── debates/                    # [→archive] 僵尸目录
├── changelog/                  # [→archive] 过时目录
├── state/                      # [→archive] 过期目录
├── 20260713/                   # [→archive] 散落文件
├── debate_20260713_2040/       # [→archive] 散落文件
│
├── index.md                    # [改] 更新为新目录索引
└── ...（保留原有只读文件不变）
```

### 2.3 删除的僵尸脚本

| 原路径 | 行数 | 功能去向 |
|:-------|:----:|:---------|
| `scripts/memory_writer.py` | 535 | 由 `manager/manager.py` + `store/journal_store.py` 接管 |
| `scripts/memory_retriever.py` | 158 | 由 `retrieval/vector_retriever.py` + `retrieval/historical_retriever.py` 接管 |
| `scripts/memory_enforcer.py` | 246 | 由 `manager/manager.py` 的 `store_journal()` + `maintenance/archiver.py` 接管 |
| `scripts/memory_cleaner.py` | 184 | 由 `maintenance/cleaner.py` 接管 |
| `scripts/debate_archiver.py` | 143 | 由 `maintenance/archiver.py` 接管 |
| `skills/.../trading_memory.py` | 180 | 废弃，不再恢复 |

---

## 3. 核心契约（TypedDict  Schema）

### 3.1 JournalEntry

```python
class JournalEntry(TypedDict, total=False):
    trace_id: str                           # 全链路追踪
    timestamp: str                          # ISO 格式
    round_id: str                           # 辩论轮次
    symbol: str                             # 品种代码
    direction: Literal["bull", "bear", "neutral"]
    confidence: float                       # 0-1
    grade: Literal["STRONG", "WATCH"]
    verdict: dict                           # 裁决定性结果
    risk: dict                              # 风控结果（含 risk_color / approved）
    pnl: NotRequired[float]                 # 事后填写
    outcome: NotRequired[str]               # 事后填写
    schema_version: str                     # 版本号
```

### 3.2 KnowledgeEntry

```python
class KnowledgeEntry(TypedDict, total=False):
    symbol: str
    last_updated: str
    total_debates: int
    drivers: list[dict]                     # [{"name":"库存","weight":0.3,"source":"..."}]
    patterns: list[dict]                    # [{"pattern":"...","win_rate":0.6}]
    key_levels: dict                        # {"support":[...],"resistance":[...]}
    data_quality: dict                      # {"tdx":"A","eastmoney":"C"}
```

### 3.3 ExperienceEntry

```python
class ExperienceEntry(TypedDict, total=False):
    symbol: str
    timestamp: str
    signal_quality: Literal["actionable", "skip"]
    signal_detail: dict
    d3_generation: NotRequired[str]
    d4_orchestration: NotRequired[str]
```

### 3.4 IncidentEntry

```python
class IncidentEntry(TypedDict):
    trace_id: str
    timestamp: str
    title: str
    severity: Literal["P0", "P1", "P2"]
    root_cause: str
    fix: str
    prevention: str
```

### 3.5 MaintenanceReport

```python
class MaintenanceReport(TypedDict):
    timestamp: str
    cleaned_journals: int
    archived_items: int
    decayed_patterns: list[str]
    storage_before_mb: float
    storage_after_mb: float
```

### 3.6 GapReport

```python
class GapReport(TypedDict):
    timestamp: str
    missing_sessions: list[str]             # 缺少 session_memory 的日期
    incomplete_learned: list[str]           # learned 字段不完整的记录
    stale_knowledge: list[str]              # 超过 30 天未更新的品种
    unreferenced_files: list[str]           # 可能废弃的文件
```

---

## 4. MemoryManager API 详解

### 4.1 初始化

```python
# memory/manager/__init__.py
from .manager import MemoryManager

_global_memory: MemoryManager | None = None

def get_memory() -> MemoryManager:
    """获取全局单例"""
    assert _global_memory is not None, "MemoryManager not initialized"
    return _global_memory

def init_memory(base_dir: str | None = None) -> MemoryManager:
    """初始化全局单例（在 fdt_cli.py 入口处调用）"""
    global _global_memory
    _global_memory = MemoryManager(base_dir or os.getcwd())
    return _global_memory
```

### 4.2 写入方法

```python
class MemoryManager:
    """memory/ 目录的唯一读写入口"""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.memory_dir = self.base_dir / "memory"

        # 子组件
        self._journal_store = JournalStore(self.memory_dir)
        self._knowledge_store = KnowledgeStore(self.memory_dir)
        self._experience_store = ExperienceStore(self.memory_dir)
        self._incident_store = IncidentStore(self.memory_dir)

        self._vector_retriever = VectorRetriever(self.memory_dir)
        self._knowledge_retriever = KnowledgeRetriever(self.memory_dir)
        self._historical_retriever = HistoricalRetriever(self.memory_dir)

        self._cleaner = Cleaner(self.memory_dir)
        self._archiver = Archiver(self.memory_dir)
        self._decay = Decay(self.memory_dir)
        self._checker = Checker(self.memory_dir)

    def store_journal(self, entry: JournalEntry) -> str:
        """写入辩论日志 → journal/debate_journal.json + SQLite"""
        validate_schema(entry, "JournalEntry")
        return self._journal_store.store(entry)

    def store_knowledge(self, entry: KnowledgeEntry) -> None:
        """写入品种知识 → knowledge/{symbol}/{field}.json"""
        validate_schema(entry, "KnowledgeEntry")
        self._knowledge_store.store(entry)

    def store_experience(self, entry: ExperienceEntry) -> None:
        """写入经验记录 → experience/records/{symbol}.json"""
        validate_schema(entry, "ExperienceEntry")
        self._experience_store.store(entry)

    def store_incident(self, entry: IncidentEntry) -> None:
        """写入事故 → incidents/incidents.md（追加模式）"""
        validate_schema(entry, "IncidentEntry")
        self._incident_store.store(entry)

    def store_schedule(self, task: str, state: dict) -> None:
        """持久化调度状态 → schedule_state.json"""
        self._journal_store.store_schedule(task, state)
```

### 4.3 检索方法

```python
    def retrieve_similar(self, symbol: str, top_k: int = 3,
                         regime: str | None = None) -> list[dict]:
        """基于 VectorMemory 的历史相似案例检索（替代旧 VectorMemory.query()）"""
        return self._vector_retriever.query(symbol, top_k, regime)

    def retrieve_journal(self, symbol: str | None = None,
                         limit: int = 10) -> list[JournalEntry]:
        """查询辩论历史"""
        return self._journal_store.query(symbol, limit)

    def retrieve_knowledge(self, symbol: str) -> KnowledgeEntry | None:
        """查询品种知识"""
        return self._knowledge_retriever.query(symbol)

    def retrieve_experience(self, symbol: str) -> list[ExperienceEntry]:
        """查询经验记录"""
        return self._experience_store.query(symbol)
```

### 4.4 维护方法

```python
    def run_maintenance(self) -> MaintenanceReport:
        """执行一次完整的维护周期"""
        report: MaintenanceReport = {
            "timestamp": datetime.now().isoformat(),
            "cleaned_journals": 0,
            "archived_items": 0,
            "decayed_patterns": [],
            "storage_before_mb": 0.0,
            "storage_after_mb": 0.0,
        }
        report["cleaned_journals"] = self._cleaner.clean(max_age_days=30)
        report["archived_items"] = self._archiver.archive()
        report["decayed_patterns"] = self._decay.run(days_without_update=60)
        report["storage_before_mb"] = self._calc_storage()
        report["storage_after_mb"] = self._calc_storage()
        return report

    def check_gaps(self) -> GapReport:
        """检查记忆系统缺口"""
        return self._checker.run()

    def migrate_from_legacy(self) -> int:
        """从旧格式迁移到新 Schema，返回迁移条目数"""
        count = 0
        count += self._journal_store.migrate_from_legacy()
        count += self._knowledge_store.migrate_from_legacy()
        count += self._experience_store.migrate_from_legacy()
        return count
```

---

## 5. 调用方改造

### 5.1 改动点清单

| 文件 | 改动类型 | 改动数量 | 每处工作 |
|:-----|:---------|:--------:|:---------|
| `fdt_cli.py` | 新增 1 行 | 1 | `init_memory()` |
| `fdt_langgraph/nodes.py` | 替换直写 | ~17 | `json.dump` → `store_journal()` |
| `fdt_langgraph/master_nodes.py` | 替换直写 | ~3 | `json.dump` → `store_schedule()` |
| `scripts/evolve_agents.py` | 替换写入 | 1 | 写入知识萃取结果 → `store_knowledge()` |

### 5.2 典型替换模式

```python
# ── 替换前（nodes.py: 散落 json 直写）──
with open("memory/journal/debate_journal.json", "r") as f:
    entries = json.load(f)
entries.append({
    "symbol": symbol,
    "verdict": verdict,
    "timestamp": datetime.now().isoformat(),
})
with open("memory/journal/debate_journal.json", "w") as f:
    json.dump(entries, f, indent=2)

# ── 替换后 ──
from memory.manager import get_memory
memory = get_memory()
existing = memory.retrieve_journal(symbol, limit=1000)
memory.store_journal(JournalEntry(
    trace_id=trace_id,
    symbol=symbol,
    verdict=verdict,
    ...
))
```

```python
# ── 替换前（nodes.py: 调用 VectorMemory）──
try:
    from scripts.vector_memory import VectorMemory
    vm = VectorMemory()
    results = vm.query(sym, top_k=3)
except Exception:
    results = []

# ── 替换后 ──
from memory.manager import get_memory
results = get_memory().retrieve_similar(sym, top_k=3) or []
```

### 5.3 迁移策略

- 每一处替换独立进行，单次提交
- 替换后运行 `pytest tests/` 全量测试验证
- 不做格式转换，保持输出 JSON 结构与现有下游解析兼容
- `migrate_from_legacy()` 在初始化时可选运行

---

## 6. 维护调度

### 6.1 触发方式

挂载到 `master_graph` 的 `self_optimize` 节点（已有节点，无需新建）：

```python
# master_nodes.py 中原 self_optimize 分支
if self._should_run_maintenance():
    report = get_memory().run_maintenance()
    self._logger.info(f"Memory maintenance complete: {report}")
```

### 6.2 调度条件

| 维护类型 | 触发条件 | 执行内容 |
|:---------|:---------|:---------|
| 日志清理 | 距离上次 > 24h | 删除超过 30 天的 journal 记录，归档到 archive/ |
| 知识老化 | 距离上次 > 24h | 60 天未辩论的品种 win_rate 减半，连续失败 3 次 deprecated |
| 缺口检查 | 距离上次 > 24h | 扫描 session_memory 缺失、learned 不完整、知识过时 |
| 存储限容 | 存储 > 100MB | 自动压缩、归档低价值记录 |

### 6.3 幂等性

`run_maintenance()` 内部使用 `check_last_run("memory_maintenance")` 检查上次执行时间，防止重复执行。

---

## 7. 实施计划

### Phase 1（1h）：目录清理 + 框架搭建

| 步骤 | 产出 |
|:-----|:-----|
| 1. 创建 `memory/manager/`、`memory/store/`、`memory/retrieval/`、`memory/maintenance/` 目录结构 | 4 个子目录 + `__init__.py` |
| 2. 废弃目录迁入 `memory/archive/20260724_backup/` | `evolutions/`、`debates/`、`changelog/`、`state/` 等移走 |
| 3. 更新 `memory/index.md` 目录索引 | 新版目录索引 |

### Phase 2（2h）：核心代码实现

| 步骤 | 产出 |
|:-----|:-----|
| 1. 实现 `schemas.py` — 所有 TypedDict 契约 | Schema 定义 |
| 2. 实现 `config.py` — 路径映射 + TTL + 限额 | 配置类 |
| 3. 实现 `manager.py` — MemoryManager 主类（含 6 个 store + 4 个 retrieve + 3 个 maintenance 方法） | MemoryManager |
| 4. 实现 `journal_store.py` + `knowledge_store.py` + `experience_store.py` + `incident_store.py` | 4 个 Store 实现 |
| 5. 实现 `vector_retriever.py` — 封装 VectorMemory 调用 | VectorRetriever |
| 6. 实现 `cleaner.py` + `archiver.py` + `decay.py` + `checker.py` | 4 个 Maintenance 实现 |

### Phase 3（1.5h）：调用方接入

| 步骤 | 产出 |
|:-----|:-----|
| 1. `fdt_cli.py` 入口注入 `init_memory()` | 1 行改动 |
| 2. `fdt_langgraph/nodes.py` 替换 ~17 处散落直写 | 17 处替换 |
| 3. `fdt_langgraph/master_nodes.py` 替换 ~3 处 | 3 处替换 |
| 4. `scripts/evolve_agents.py` 替换知识写入 | 1 处替换 |

### Phase 4（1h）：维护调度 + 验收

| 步骤 | 产出 |
|:-----|:-----|
| 1. `master_nodes.py` 挂载 `run_maintenance()` | 维护调度上线 |
| 2. 全量测试 | `pytest tests/` 通过 |
| 3. 更新 12 项检查清单 | `docs/harness/` 相关文档同步 |
| 4. 删除废弃脚本 | 删除 6 个僵尸 `.py` 文件 |

### 实施顺序总图

```
Phase 1 (目录清理)
  │
  ▼
Phase 2 (MemoryManager 实现)
  │
  ├─ schemas.py ──→ 契约定义
  ├─ store/* ──→ 存储层 (journal + knowledge + experience + incident)
  ├─ retrieval/* ──→ 检索层 (vector + knowledge + historical)
  ├─ maintenance/* ──→ 维护层 (cleaner + archiver + decay + checker)
  └─ manager.py ──→ 组合以上所有
      │
      ▼
Phase 3 (调用方接入)
  ├─ fdt_cli.py        +1行
  ├─ nodes.py          ~17处替换
  ├─ master_nodes.py   ~3处替换
  └─ evolve_agents.py  ~1处替换
      │
      ▼
Phase 4 (维护调度 + 验收)
  ├─ master_graph 挂载 run_maintenance()
  ├─ 全量测试通过
  ├─ 文档同步
  └─ 删除僵尸脚本
```

---

## 8. 测试策略

### 8.1 单元测试

| 测试目标 | 测试内容 |
|:---------|:---------|
| `JournalStore` | 写入+读取、去重、SQLite 双写 |
| `KnowledgeStore` | 写入+读取、覆盖、索引更新 |
| `VectorRetriever` | 查询+空结果、异常处理 |
| `Cleaner` | TTL 清理、存储限容 |
| `Decay` | 知识老化逻辑、deprecated 判定 |
| `Checker` | 缺口扫描、报告生成 |

### 8.2 集成测试

| 测试目标 | 测试内容 |
|:---------|:---------|
| `MemoryManager` | 全流程：写入→检索→维护 |
| `nodes.py` 替换 | 替换后输出与旧格式兼容 |
| `run_maintenance()` | 完整维护周期 + 幂等性 |

### 8.3 回归测试

- `pytest tests/` 全量通过
- 手动执行一次完整辩论流程（`fdt_cli.py run --symbol CF2609`），验证：
  - journal 正常写入
  - knowledge 正常更新
  - retrieve_similar 返回非空结果（如有历史数据）

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:----:|:---------|
| 替换 json 直写后进程中断导致数据丢失 | 低 | 中 | SQLite 双写保底，journal_store 的 flush 操作原子化 |
| 旧调用方未收敛 | 中 | 低 | grep 全项目搜索 `json.(dump\|load)` 在 `memory/` 路径的使用，确保全部替换 |
| VectorMemory 初始化失败 | 低 | 低 | `retrieve_similar()` 失败时返回 `[]`，保持 try/except 兼容 |
| migrate_from_legacy 破坏旧数据 | 低 | 高 | 迁移前全量备份到 `archive/`，迁移后不做原地删除 |

---

## 10. 版本号与文档同步

### 10.1 版本号

本设计对应 FDT v9.24.0（重构 memory 系统）。完成后执行：

```bash
# 更新 pyproject.toml version
# 更新 docs/harness/07-operations.md 版本历史
```

### 10.2 文档映射

| 变更 | 对应文档 |
|:-----|:---------|
| memory/ 目录结构变更 | `docs/harness/01-architecture.md`（数据流章节） |
| MemoryManager 生命周期 | `docs/harness/02-lifecycle.md`（P0 数据准备阶段） |
| 维护调度配置 | `docs/harness/03-configuration.md`（新增维护间隔配置） |
| 维护降级策略 | `docs/harness/04-resilience.md`（维护失败不影响业务） |
| 维护日志指标 | `docs/harness/05-observability.md`（MaintenanceReport） |
| 测试用例 | `docs/harness/06-testing.md`（新增 memory 测试段） |
| 版本历史 | `docs/harness/07-operations.md`（v9.24.0） |
| 差距清理 | `docs/harness/08-gap-analysis.md`（关闭 memory 相关差距） |

---

## 11. 验收标准

| # | 标准 | 验证方式 |
|:-|:-----|:---------|
| 1 | 6 个僵尸脚本已从文件系统删除 | `ls scripts/memory_*.py` 确认 |
| 2 | 废弃目录已迁入 `memory/archive/` | 目录存在且原始位置无残留 |
| 3 | `memory/manager/` 目录结构完整 | 4 个子模块 `__init__.py` 存在 |
| 4 | `init_memory()` 在 `fdt_cli.py` 入口调用 | grep 确认 |
| 5 | `nodes.py`/`master_nodes.py` 中无 `json.dump` 到 `memory/` 路径 | grep `json\.(dump|load).*memory` 返回空 |
| 6 | `get_memory().retrieve_similar()` 返回非空结果（如有历史数据） | 运行一次完整辩论 |
| 7 | `run_maintenance()` 无报错执行 | 手动触发一次 |
| 8 | `pytest tests/` 全量通过 | CI |

---

## 12. 附录

### 12.1 与现有系统的兼容性

- `journal_store.py` 写入的 JSON 结构与当前 `nodes.py` 写入的格式完全兼容（只增加 `schema_version` 字段）
- `knowledge_store.py` 重读 `knowledge/` 目录现有文件，不做格式转换
- `migrate_from_legacy()` 跳过 `schema_version` 已存在的条目，幂等执行
- 旧调用方（如果有遗漏）直接 json 读 `memory/` 仍可工作，只是不再推荐

### 12.2 核心循环引用

```python
# Manager 子组件组合关系（无循环引用）
MemoryManager
  ├── JournalStore     → journal_store.py (自包含)
  ├── KnowledgeStore   → knowledge_store.py (自包含)
  ├── ExperienceStore  → experience_store.py (自包含)
  ├── IncidentStore    → incident_store.py (自包含)
  ├── VectorRetriever  → vector_retriever.py → VectorMemory (scripts/vector_memory.py)
  ├── KnowledgeRetriever → knowledge_retriever.py (自包含)
  ├── HistoricalRetriever → historical_retriever.py (自包含)
  ├── Cleaner          → cleaner.py (自包含)
  ├── Archiver         → archiver.py (自包含)
  ├── Decay            → decay.py → extract_knowledge.run_decay()
  └── Checker          → checker.py (自包含)
```
