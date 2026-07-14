# 验证器可插板 + 声明式映射 骨架 — 完整 Diff 对比报告

> 缘起：`technical_debt.md` §5 已确立「信号范式 ↔ 专属验证器」原则（状态：已确立未实施）
> 本报告为**纯架构脚手架**方案，仅迁移现有 P0-4 逻辑 + 建注册表/映射，**不新增任何验证规则**。
> 涉及 `plugins/marketplaces/` → 按铁律先出 Diff 报告，待掌柜说「执行」后再动手。

---

## 一、现状问题（为什么要搭这个骨架）

当前信号验证逻辑碎片化、无统一注册表：

| 机制 | 位置 | 作用 | 调用点 |
|------|------|------|--------|
| P0-4 重校验门禁 | `scan_all.py` L142-201 (`_revalidate_breakouts`) | 伪突破降级（就地改 `signal_type=false_breakout`） | `scan_all.py:546` |
| 稳定性 + 拥挤度 | `validate_signals.py` (`validate_all`) | 全局管道过滤 | `scan_all.py:549-564` |

- 两个机制调用点分散，无「某 signal_type 该走哪个验证器」的声明。
- 新增信号范式（如回归类、均值回归类）时，只能硬接、无针对性保护 → 这正是 §5 原则要解决的。

## 二、目标设计

- **声明式映射（单一真相源）**：`signal_type → [validator_id]` 写在 `config/settings.py` 的 `SIGNAL_VALIDATOR_MAP`。
- **注册表模式**：`signals/validators/` 包自举 `VALIDATOR_REGISTRY`，`register_validator` 注册，`run_signal_validators` 按映射串执行。
- **行为零改变**：P0-4 逻辑逐字迁移，不重写验证规则。
- **两类验证区分**：
  - 逐信号专属验证器（按 `signal_type` 路由）：如 `p0_4_revalidate`
  - 全局管道闸门（对所有活跃信号统一跑）：稳定性/拥挤度 — 本轮**保留**在 `validate_signals.py`，未来可折入注册表作为 `__global__` 类。

## 三、改动清单（Diff）

### 3.1 新建文件

**`scripts/signals/validators/__init__.py`** — 注册表骨架
```python
"""信号验证器注册表 — 信号范式 ↔ 专属验证器的可插板底座。"""
from config.settings import SIGNAL_VALIDATOR_MAP

VALIDATOR_REGISTRY = {}

def register_validator(vid, fn):
    VALIDATOR_REGISTRY[vid] = fn

def get_validator(vid):
    return VALIDATOR_REGISTRY.get(vid)

def get_validators_for(signal_type):
    return [get_validator(v) for v in SIGNAL_VALIDATOR_MAP.get(signal_type, []) if get_validator(v)]

def run_signal_validators(all_ranked, context):
    """按 SIGNAL_VALIDATOR_MAP 收集所有被引用的验证器，逐个对 all_ranked 运行（就地降级）。"""
    used_ids = {v for ids in SIGNAL_VALIDATOR_MAP.values() for v in ids}
    for vid in used_ids:
        fn = get_validator(vid)
        if fn is None:
            print(f"  ⚠️ [validator] 映射引用了未注册的验证器: {vid}（已跳过）")
            continue
        fn(all_ranked, context)
    return all_ranked
```

**`scripts/signals/validators/p0_4_revalidate.py`** — 从 `scan_all._revalidate_breakouts` 整体迁移
```python
"""P0-4 突破类信号重校验门禁 — 从 scan_all._revalidate_breakouts 迁移，逻辑不变。"""
from . import register_validator

_BREAKOUT_SIGNALS = {"channel_breakout", "trend_confirmation", "bb_squeeze_prebreakout"}
_SPIKE_RETURN_CAP_LOCAL = 0.5  # 与 multi_source_adapter._SPIKE_RETURN_CAP 一致

def validate_p0_4(all_ranked, context):
    kline_data = context.get("kline_data", {})
    demoted = 0
    for r in all_ranked:
        sig = r.get("signal_type", "")
        if sig not in _BREAKOUT_SIGNALS:
            continue
        sym = r.get("symbol", "")
        if sym not in kline_data:
            continue
        _, dlist = kline_data[sym]
        if len(dlist) < 21:
            continue
        # —— 以下逐字保留原 _revalidate_breakouts 的回验 + 降级逻辑 ——
        prior = dlist[-21:-1]
        last = dlist[-1]
        try:
            last_high = float(last.get("high", 0))
            last_low  = float(last.get("low", 0))
            last_close = float(last.get("close", 0))
            prior_max_h = max(float(x.get("high", 0)) for x in prior)
            prior_min_l = min(float(x.get("low", 0)) for x in prior)
            prior_max_c = max(float(x.get("close", 0)) for x in prior)
            prior_min_c = min(float(x.get("close", 0)) for x in prior)
        except (ValueError, TypeError):
            continue
        direction = r.get("direction", "")
        forged = False
        reason = ""
        if direction == "bull":
            broke = (last_high > prior_max_h) or (last_close > prior_max_c)
            if not broke:
                forged = True; reason = "末根high/close均未超前20根极值(伪突破)"
            elif prior_max_h > 0 and (last_high / prior_max_h - 1.0) > _SPIKE_RETURN_CAP_LOCAL:
                forged = True; reason = f"末根high超前期{(last_high/prior_max_h-1)*100:.0f}%>50%(疑似spike伪造)"
        elif direction == "bear":
            broke = (last_low < prior_min_l) or (last_close < prior_min_c)
            if not broke:
                forged = True; reason = "末根low/close均未破前20根极值(伪突破)"
            elif prior_min_l > 0 and (prior_min_l / last_low - 1.0) > _SPIKE_RETURN_CAP_LOCAL:
                forged = True; reason = f"末根low破前期{(prior_min_l/last_low-1)*100:.0f}%>50%(疑似spike伪造)"
        if forged:
            demoted += 1
            r["signal_type"] = "false_breakout"
            r["grade"] = "NOISE"
            r["total"] = 0
            r["_breakout_revalidated"] = False
            r["_revalidate_reason"] = reason
            print(f"  ⛔ [P0-4] {sym} 突破信号被重校验拦截: {reason} → 降级NOISE")
    return demoted

register_validator("p0_4_revalidate", validate_p0_4)
```

### 3.2 修改文件

**`scripts/config/settings.py`** — 在 `SIGNAL_GRADE_THRESHOLDS`(L311-316) 之后新增：
```python
# ============================================================
# 信号范式 ↔ 专属验证器 声明式映射（单一真相源）
# signal_type → [validator_id]；新增验证器只需：本表登记 + register_validator
# （2026-07-14 脚手架落地，对应 technical_debt.md §5）
# ============================================================
SIGNAL_VALIDATOR_MAP = {
    "channel_breakout":       ["p0_4_revalidate"],
    "trend_confirmation":     ["p0_4_revalidate"],
    "bb_squeeze_prebreakout": ["p0_4_revalidate"],
}
```

**`scripts/scan_all.py`** — 两处改动：
1. **删除** L137-139（常量 `_BREAKOUT_SIGNALS` / `_SPIKE_RETURN_CAP_LOCAL`）与 L142-201（函数 `_revalidate_breakouts`）→ 已迁移至 `validators/p0_4_revalidate.py`。
2. **L545-548 调用改造**：
   - 顶部补 `from signals.validators import run_signal_validators`（scan_all 已 `from config.settings import clear_param_overrides`，`SIGNAL_VALIDATOR_MAP` 可直接同源 import）
   - 原：
     ```python
     _demoted = _revalidate_breakouts(summary.get("all_ranked", []), kline_data)
     if _demoted:
         print(f"\n  [P0-4] 信号重校验门禁: {_demoted} 个伪突破信号被拦截降级为NOISE")
     ```
   - 改为：
     ```python
     _demoted = run_signal_validators(summary.get("all_ranked", []), {"kline_data": kline_data})
     if _demoted:
         print(f"\n  [P0-4] 信号重校验门禁: {_demoted} 个伪突破信号被拦截降级为NOISE")
     ```
   - 全局 gate `validate_all`（L549-564）**保持不变**，作为管道级闸门。

### 3.3 不变
- `scripts/validate_signals.py`（稳定性/拥挤度）逻辑与调用点均不动。
- `strategies/channel_breakout_strategy.py`：signal_type 产出不变（`channel_breakout`/`trend_confirmation`/`bb_squeeze_prebreakout`/`near_breakout`/`minor_signal`/`none`）。
- `technical_debt.md` §5 状态：落地后由「已确立未实施」→「骨架已落地（实施中）」，待执行后更新。

## 四、风险与缓解

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | 导入副作用：`scan_all` 原不 import `signals` 包，新增 `from signals.validators import ...` 触发 `signals/__init__.py → debate_engine` 导入 | 低 | `debate_engine` 已在 analyze_targets/daily_debate/backtest 中被 import（同代码库，proven safe）；实施时实测无 import-time 副作用即可。若不放心，可把注册表放到 `scripts/validators/`（signals 同级）规避父包 `__init__` |
| 2 | 行为一致性：P0-4 降级结果是否与原函数一致 | 极低 | 逻辑逐字迁移；`run_signal_validators` 对整体 `all_ranked` 跑一次 `validate_p0_4`（内部仍按 `_BREAKOUT_SIGNALS` 跳过非突破信号），结果必一致。回归：用 09:10 扫描的 42 个伪突破拦截数校验 |
| 3 | 映射/注册不一致：`SIGNAL_VALIDATOR_MAP` 引用了未注册 id | 低 | `run_signal_validators` 对缺失 id 打印 warning 并跳过（静默不崩） |
| 4 | 范围失控 | 无 | 本轮仅迁移 P0-4 + 建注册表/映射，不新增验证规则、不动全局 gate、不动评分，符合「纯架构脚手架」 |

## 五、实施步骤（待掌柜说「执行」后）

1. 写 `signals/validators/__init__.py`
2. 写 `signals/validators/p0_4_revalidate.py`（迁移）
3. `settings.py` 加 `SIGNAL_VALIDATOR_MAP`
4. `scan_all.py` 删旧函数 + 改调用 + 加 import
5. 回归：59 品种扫描，伪突破拦截数 == 42（与原 09:10 一致）
6. 更新 `technical_debt.md` §5 状态 + FDT `changelog.md` + `MEMORY.md` 索引

## 六、待确认（请掌柜拍板）

- **A. 落位**：`signals/validators/`（触发 signals 包导入，符合既有命名习惯）vs `scripts/validators/`（规避父包 `__init__`，更隔离）？
- **B. 全局 gate**：稳定性/拥挤度本轮是否一并折入注册表？建议**否**，留作下一步，保持骨架纯粹。
- 以上确认后，回「执行」即动手。
