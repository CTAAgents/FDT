# FDT 记忆系统目录结构

> 结构化存储规范 v2.0 (2026-07-24) · MemoryManager 统一管理 · 禁止在 `memory/` 根目录直接存放文件

## 架构全景

```
memory/
├── manager/         ← MemoryManager 核心（唯一入口，单例模式）
├── store/           ← 存储层（Journal / Knowledge / Experience / Incident）
├── retrieval/       ← 检索层（Vector / Knowledge / Historical）
├── maintenance/     ← 维护层（Cleaner / Archiver / Decay / Checker）
├── archive/         ← 历史归档（废弃目录 / 过期数据）
│
├── journal/         ★ 辩论日志（只读，由 MemoryManager 写入）
├── knowledge/       ★ 品种知识库（只读，由 MemoryManager 写入）
├── experience/      ★ 经验记录（只读，由 MemoryManager 写入）
├── rules/           ★ 铁律规范（手动维护）
├── incidents/       ★ 事故教训（手动维护）
├── revisions/       ★ 裁决修正（手动维护）
├── policies/        ★ 风控策略（手动维护）
├── performance/     ★ 性能质量（手动维护）
└── tech_debt/       ★ 技术债务（手动维护）
```

## 目录分类

### 🆕 管理层（MemoryManager 子系统）
| 目录 | 内容 | 读写方式 |
|:-----|:-----|:---------|
| `manager/` | `__init__.py`（单例）、`manager.py`（主类）、`schemas.py`（契约）、`config.py`（配置） | 初始化时加载 |
| `store/` | `journal_store.py` / `knowledge_store.py` / `experience_store.py` / `incident_store.py` | 由 MemoryManager 调用 |
| `retrieval/` | `vector_retriever.py` / `knowledge_retriever.py` / `historical_retriever.py` | 由 MemoryManager 调用 |
| `maintenance/` | `cleaner.py` / `archiver.py` / `decay.py` / `checker.py` | 由 master_graph 调度 |

### ★ 数据目录（只读，不可直接写入）
| 目录 | 内容分类 | 维护方式 |
|:-----|:---------|:---------|
| `journal/` | 辩论日志（debate_journal.json / index.json） | MemoryManager.store_journal() |
| `knowledge/` | 84 品种知识库（variety_index.json / 品种子目录） | MemoryManager.store_knowledge() |
| `experience/` | 经验记录（records/ / patterns/ / adaptation_log/） | MemoryManager.store_experience() |
| `rules/` | 铁律/规范（MEMORY.md / session_rules.md / data_sources.md 等） | 手动维护 |
| `incidents/` | 事故与教训（incidents.md / failure_clusters.json） | 手动维护 |
| `revisions/` | 裁决修正/校准/辩手画像（judgment_revisions.md / calibration.json 等） | 手动维护 |
| `policies/` | 风控策略（veto_policies.md / stop_loss_policy.md / weighting_history.md） | 手动维护 |
| `performance/` | 性能/质量/自进化数据（apm_scorecard.json / validation_stats.json 等） | 手动维护 |
| `tech_debt/` | 技术债务/问题追踪（technical_debt.md / fast_track.md 等） | 手动维护 |

### 📦 历史归档
| 目录 | 内容 | 归档时间 |
|:-----|:-----|:---------|
| `archive/20260724_backup/evolutions/` | 废弃的 10 Agent × 4 策略演化文件（40文件） | 2026-07-24 |
| `archive/20260724_backup/debates/` | 已停更的辩论索引（INDEX 最后更新 2026-07-16） | 2026-07-24 |
| `archive/20260724_backup/changelog/` | 版本号停滞在 v8.1.8 的变更日志 | 2026-07-24 |
| `archive/20260724_backup/20260713/` | 散落顶层的夜盘扫描记录 | 2026-07-24 |
| `archive/20260724_backup/debate_20260713_2040/` | 散落顶层的辩论数据 | 2026-07-24 |

## 根目录零容忍规则

- **禁止**在 `memory/` 根目录下存放任何文件（仅允许 `index.md`）
- `MEMORY.md` 已移至 `rules/` 目录
- 新文件必须先确定属于哪个分类目录，再创建
- 无合适目录时，先在 `rules/` 中补充分类定义，再存放

## 文件索引

| 文件 | 当前位置 | 说明 |
|:----|:---------|:-----|
| `manager/__init__.py` | `manager/` | MemoryManager 单例 + get_memory() / init_memory() |
| `manager/manager.py` | `manager/` | MemoryManager 主类 |
| `manager/schemas.py` | `manager/` | 所有 TypedDict 契约 |
| `manager/config.py` | `manager/` | 路径映射 + TTL + 存储限额 |
| `store/journal_store.py` | `store/` | 辩论日志存储 |
| `store/knowledge_store.py` | `store/` | 品种知识存储 |
| `store/experience_store.py` | `store/` | 经验记录存储 |
| `store/incident_store.py` | `store/` | 事故记录存储 |
| `retrieval/vector_retriever.py` | `retrieval/` | VectorMemory 封装 + 历史相似案例检索 |
| `retrieval/knowledge_retriever.py` | `retrieval/` | 品种知识检索 |
| `retrieval/historical_retriever.py` | `retrieval/` | 历史案例检索 |
| `maintenance/cleaner.py` | `maintenance/` | TTL + 存储限容 |
| `maintenance/archiver.py` | `maintenance/` | 归档 + 压缩 |
| `maintenance/decay.py` | `maintenance/` | 知识老化 |
| `maintenance/checker.py` | `maintenance/` | check_memory_gaps.py |
| `MEMORY.md` | `rules/` | 记忆系统入口·铁律/用户偏好/长期事实 |
| `session_rules.md` | `rules/` | 铁律/规范 — 顶层规则入口 |
| `data_sources.md` | `rules/` | 铁律/规范 — 顶层规则入口 |
| `program.md` | `rules/` | 铁律/规范 — 顶层规则入口 |
| `info_portals.md` | `rules/` | 铁律/规范 — 顶层规则入口 |
| `incidents.md` | `incidents/` | 事故与教训 |
| `failure_clusters.json` | `incidents/` | 事故与教训 |
| `judgment_revisions.md` | `revisions/` | 裁决修正/辩手画像 |
| `calibration.json` | `revisions/` | 裁决修正/辩手画像 |
| `debater_profiles.md` | `revisions/` | 裁决修正/辩手画像 |
| `argument_patterns.md` | `revisions/` | 裁决修正/辩手画像 |
| `agent_profiles.json` | `charters/` | Agent 角色档案 |
| `agent_watchdog.md` | `charters/` | Agent 角色档案 |
| `apm_scorecard.json` | `performance/` | 性能/质量/自进化数据 |
| `self_improve_log.json` | `performance/` | 性能/质量/自进化数据 |
| `evolution_log.json` | `performance/` | 性能/质量/自进化数据 |
| `execution_followup.json` | `performance/` | 性能/质量/自进化数据 |
| `feedback_entries.json` | `performance/` | 性能/质量/自进化数据 |
| `validation_stats.json` | `performance/` | 性能/质量/自进化数据 |
| `evaluation_production_readiness_20260714.md` | `performance/` | 性能/质量/自进化数据 |
| `debate_weights.json` | `performance/` | 性能/质量/自进化数据 |
| `technical_debt.md` | `tech_debt/` | 技术债务/问题追踪 |
| `run_issues_LH_rerun_20260707.md` | `tech_debt/` | 技术债务/问题追踪 |
| `fast_track.md` | `tech_debt/` | 技术债务/问题追踪 |
| `instrument_strategy_matrix.json` | `strategies/` | 策略配置/品种矩阵 |
| `stop_loss_policy.md` | `policies/` | 风控策略 |
| `veto_policies.md` | `policies/` | 风控策略 |
| `weighting_history.md` | `policies/` | 风控策略 |

---
*索引更新于 2026-07-24 · v2.0 · MemoryManager 统一管理*
