# 技术债 §1 落地方案：指标计算核心收编（v0.3 修订）

> **落地状态：✅ 已落地（2026-07-14 13:00）。执行结果见 `memory/changelog.md` 同时间条目 + `memory/technical_debt.md` §1（已标记已落地）。验证全过：py_compile + 四路导入冒烟 + 数值回归单测 + 17 importer 结构回归 + 实跑 PK/RB/B/UR 指标管线正常。零信号逻辑变更。**
> 关联：`memory/technical_debt.md` §1（高优先级核心债）
> 规范依据：`CODING_STANDARDS.md`（Ruff / 外科手术式修改 / 简单优先）、`CLAUDE.md`（四原则）

## 0. 方向修正记录（2026-07-14 掌柜架构质疑）

掌柜指出：已存在 FDC（`futures_data_core` 包，含 cache_store + postgres/redis + txn_store），
那独立 `futures-data-engine` skill 是否必要？经核查：

- **FDC = `futures_data_core` 包本身**；指标计算层 `futures_data_core/indicators/` **已是 FDC 体系内的子模块**，且 `futures_data_core/__init__.py` 已公开导出 `compute_indicators` / `INDICATOR_NAMES`。
- **独立 `futures-data-engine` skill 无存在必要**：新建顶层 skill 属画蛇添足、命名混淆、违反"简单优先"。
- **正确方向 = 收编进 `futures_data_core/indicators/`**（FDC 体系内，已在 sys.path），不新建任何 skill、不碰 FDC 存储后端层。

→ 原方案 A（新建 futures-data-engine skill）废弃，改为方案 A'（收编进 futures_data_core.indicators）。
→ 另修正：原 §1 所述"双 core 循环依赖"实测为**代码重复 + 命名混乱**，无运行期硬循环（见 §2）。
→ 2026-07-14 review（掌柜采纳建议）：v0.3 修正 §2 行数/双 core 误述、术语"反向依赖"矛盾，补"双定义函数合并前 byte-diff"与"数值回归单测"两步（见 §2 表注 + §6 步 1.5 / 5.5）。

---

## 1. 目标

把分散在 `quant-daily` 内的指标计算核心（真引擎 `calc_core.py`、遗留 `indicators_legacy.py`、`assess_trend_maturity`、TDX 桥接）**收编进 FDC 体系内的 `futures_data_core/indicators/`**，作为所有策略/研究员的**单一指标真相源**，消除 quant-daily 侧的代码冗余与双 `core.py` 命名混乱。

---

## 2. 范围校正（重要 — 原文低估了工作量）

`technical_debt.md §1` 只列 3 文件，实测真实涉及 **4 个文件 + 双同名 `core.py` 命名混乱**（非循环依赖）：

| 文件 | 行数 | 角色 |
|------|------|------|
| `quant-daily/scripts/indicators/calc_core.py` | 2065 | **真正引擎**（numpy 向量化，TDX 100% 对齐，52 个 `calculate_*` 函数）。§1 原文漏列。 |
| `quant-daily/scripts/indicators/core.py` | 250 | **非纯薄壳**：顶部 `from .calc_core import *` 重导出，但 **L98 另定义自己的 `assess_trend_maturity`**（与 indicators_legacy.py:21 双副本，见 §4 步3） |
| `quant-daily/scripts/indicators/tdx_bridge.py` | 513 | TDX 桥接；L230 `from futures_data_core.indicators.core import compute_indicators`（**quant-daily→FDC 单向依赖**，非反向） |
| `quant-daily/scripts/indicators/indicators_legacy.py` | 1621 | 遗留 numpy 实现；**L21 也定义 `assess_trend_maturity`**（与 core.py:98 双副本）；L861/L882 为 **quant-daily 内部 import**（`indicators.tdx_bridge` / `indicators.calc_core`），与 FDC 无关 |
| `futures_data_core/indicators/core.py` | 421 | **FDC 真引擎**（与 quant-daily 同名不同包），含 ~16 基础指标（sma/ema/rsi/macd/boll/kdj/atr/cci/williams_r/obv/adx/bias/roc/momentum/stddev/volume_ma）+ `compute_indicators` + `INDICATOR_NAMES`；`futures_data_core/__init__.py:58` 与 `indicators/__init__.py` 引用 |

**循环依赖核查（修正）**：实测**无运行期硬循环**。
- `futures_data_core/indicators/core.py` 是干净纯 numpy（不 import quant-daily）。
- quant-daily 的 `tdx_bridge.py` / `multi_source_adapter.py` 单向 `import futures_data_core.indicators.core`（依赖 FDC，非循环）。
- `calc_core.py` 完全自包含（不 import futures_data_core）。
→ 真实债务是**代码重复 + 命名混乱**（quant-daily 冗余一份 2065 行真引擎 + 1621 行 legacy + 两个同名 `core.py`），非循环依赖。收编后 quant-daily 侧 4 文件变 shim，冗余消除。

---

## 3. 真实 importer 清单（~20 处，决定 blast radius）

直接 `from indicators.X import ...`：
- `scan_all.py`（3 处：core / indicators_legacy / tdx_bridge）
- `signals/signal_screener.py`（2 处 core）
- `signals/scoring_system.py`（core）
- `analyze_targets.py`（core / indicators_legacy / calc_core）
- `assemble_intermediate_data.py`（tdx_bridge）
- `120m_resampler.py`（calc_core）
- `optimizer/backtest_optimizer.py`（calc_core）
- `optimizer/regime.py`（calc_core，懒加载）
- `layered_l1l4.py`（docstring 引用 core）
- backtest/* 共 9 个：`_compute_indicators_numpy`（indicators_legacy）
- 另有 `futures_data_core/__init__.py`、`futures_data_core/indicators/__init__.py` 引用第二个 core

---

## 4. 落地方案（A' — 收编进 FDC 体系内，推荐 ★）

不新建任何 skill，收编进已在 FDC 体系内的 `futures_data_core/indicators/`（已在 sys.path，bootstrap 现成）。

1. 在 `futures_data_core/indicators/` 下新增 `tdx_compat.py`，物理搬入 `calc_core.py` 的 52 个 `calculate_*` TDX 兼容函数（保留命名，与现有 ~16 基础指标无命名冲突）+ `calculate_tdx_compatible` + `analyze_metal` + K线形态检测。
2. 把 `indicators_legacy.py` 的 `_compute_indicators_numpy`（被 11+ 处 backtest/scan_all import）搬为 `futures_data_core/indicators/legacy_numpy.py`，保留函数名。
3. **合并双副本** `assess_trend_maturity` 搬入 `futures_data_core/indicators/`（指标衍生分析）。该函数有 **2 份副本**：`quant-daily/scripts/indicators/core.py:98` 与 `indicators_legacy.py:21`（均为 v2.17修正版，前 80 行已比对一致）。搬前须全量 byte-diff（见 §6 步 1.5）：一致则搬一份到 FDC、两处 shim 都 re-export；不一致则人工裁决。
4. 更新 `futures_data_core/indicators/__init__.py` re-export 全部公共 API（`compute_indicators` / `INDICATOR_NAMES` / `calculate_tdx_compatible` / `assess_trend_maturity` / `_compute_indicators_numpy` 等）。
5. 原 `quant-daily/scripts/indicators/{calc_core,core,indicators_legacy,tdx_bridge}.py` 改为 **re-export shim** 指向 `futures_data_core.indicators.*`（`tdx_bridge.py` 保留自身 TDX 桥接逻辑，底层指标改为 import FDC）。
6. **~20 个 importer 不动** —— 仍 `from indicators.core / indicators_legacy / calc_core import ...`，由 shim 透明转发。

优点：
- **不新建顶层 skill**，不碰 FDC 存储后端（cache_store/backends 职责不变），sys.path 零改动（`futures_data_core` 已在 path）。
- 单一真相源本就在 FDC 体系内（`futures_data_core.indicators`），完全消除 quant-daily 冗余副本。
- blast radius 最小（quant-daily 改 4 文件 shim + FDC 内新增 2 文件），符合"外科手术式/简单优先"，可灰度回滚。

> 原"方案 B（纯重构直连）"仍可选但非推荐：需改 ~20 importer，违反"简单优先"，暂不采用。

---

## 5. 关键设计决策：无需新建 skill / 无需改 sys.path

- `futures_data_core` 已在 `sys.path`（bootstrap.py 注入 FDT 根 + pipeline/runner.py 注入 quant-daily/scripts；`futures_data_core` 作为顶层包可直接 import，现状 `from futures_data_core.indicators.core import ...` 已通）。
- 收编目标是 `futures_data_core/indicators/`（FDC 包内子模块），**不涉及跨 skill 解析**，因此**无需新增 sys.path 注入、无需注册新包名**。
- 唯一新增文件在 `futures_data_core/indicators/` 内（`tdx_compat.py` / `legacy_numpy.py`），同包内可见，零路径改动。

---

## 6. 实施步骤（分阶段 + 验证门）

1. **读现状确认**：核对 `futures_data_core/indicators/core.py`（~16 基础指标）与 `calc_core.py`（52 个 `calculate_*`）的函数边界，列出需保留的双重命名（如 `rsi` vs `calculate_rsi`）确保 importer 透明。
1.5. **双定义函数合并前 byte-diff**（必做）：对 `assess_trend_maturity`（core.py:98 vs indicators_legacy.py:21）等任何多副本函数执行 `diff`——一致则搬一份到 FDC + 两处 shim 都 re-export；不一致则**暂停并人工裁决**，不得静默选一份。
2. **收编进 FDC**：在 `futures_data_core/indicators/` 新增 `tdx_compat.py`（搬 calc_core 的 calculate_* + calculate_tdx_compatible + analyze_metal + K线形态）、`legacy_numpy.py`（搬 `_compute_indicators_numpy`）、搬入合并后的 `assess_trend_maturity`；更新 `__init__.py` re-export。
3. **改 shim**（方案 A'）：`quant-daily/scripts/indicators/{calc_core,core,indicators_legacy,tdx_bridge}.py` 改为 re-export 指向 `futures_data_core.indicators.*`（`core.py` 的 `assess_trend_maturity` 改由 FDC re-export 提供；`indicators_legacy.py` 同）。
4. **验证门 1**：全量 `py_compile` 新文件 + shim。
5. **验证门 2**：导入冒烟 —— `python -c "from futures_data_core.indicators.core import compute_indicators; from futures_data_core.indicators import calculate_tdx_compatible, assess_trend_maturity, _compute_indicators_numpy; from indicators.core import assess_trend_maturity; from indicators.indicators_legacy import _compute_indicators_numpy"` 四路均通（FDC 直连 / quant-daily shim 两路透明）。
5.5. **验证门 2.5（数值回归单测）**：固定样本分别走旧 `indicators.calc_core` 路径与新 `futures_data_core.indicators.tdx_compat` 路径，断言 `rsi` / `atr` 等数值在容差（1e-6）内相等，捕捉搬移中的静默数值漂移。
6. **验证门 3**：实扫回归 —— 跑一次盘前扫盘，对比 09:10 那次 **42 伪突破拦截数**不变（指标层零行为变更，理论上不变）。
7. **记忆归档**：`technical_debt.md §1` 标「已落地」+ `changelog.md` 加条目（按 FDT 铁律，全记 FDT 自身 memory/）。

---

## 7. 风险与回滚

- 风险：收编时函数命名双重导出（`rsi`/`calculate_rsi`）若漏导，importer 报 AttributeError → 验证门 2 必拦。
- 回滚：shim 方案下，若收编出问题，把 4 个 shim 文件还原为原内容即回退（原文件内容已知，备份可恢复）。
- 不引入新信号逻辑、不动验证器/P0-4（与本次 A+B+C 一致）。

---

## 8. 待掌柜决策

- [x] **方向修正**：废弃方案 A（新建 futures-data-engine skill），确立方案 A'（收编进 `futures_data_core.indicators`，FDC 体系内，不新建 skill）。（2026-07-14 掌柜架构质疑触发）
- [x] **方案 A' 已确认 + v0.3 修正采纳**（2026-07-14 掌柜 review 后采纳五项修正：行数/双 core 误述、术语矛盾、补 byte-diff 与数值回归单测）。
- [ ] 授权"执行" → 触发上面第 1–7 步（含 1.5 byte-diff / 5.5 数值回归单测 / 收编进 futures_data_core.indicators / 改 4 处 shim / 实扫回归 42 拦截数对比）
