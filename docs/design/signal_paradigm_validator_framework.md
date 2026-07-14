# 信号计算范式 ↔ 伪信号过滤验证器 框架设计（落地 Diff v1）

> 范围升级：从「仅 P0-4 脚手架」扩展为「完整框架」——总结范式 + 验证器类型，设计成具体模块塞入系统。
> 设计哲学（掌柜指示）：**只用公开主流因子，不挖不可解释的新因子**；未来工作只聚焦「范式具体实现 + 验证器合理性」。
> 落地依据：`technical_debt.md` §5「信号范式 ↔ 专属验证器」原则。
> ⚠️ 本报告涉及 `plugins/marketplaces/` → 按铁律先出方案，待掌柜说「执行」后再写文件。

---

## 0. 设计哲学（约束未来工作边界）

| 原则 | 含义 |
|------|------|
| 主流因子优先 | 验证器/范式一律用公开、可解释因子（Donchian / Bollinger / ATR / Volume / MA / Z-Score / 实体比例），禁止引入黑盒新因子 |
| 范式↔专属验证器 | 每个 signal_type 显式声明它该走哪些验证器（`SIGNAL_VALIDATOR_MAP`） |
| 未来聚焦两点 | (1) 范式的具体实现（调主流因子权重/阈值）；(2) 验证器的合理性（是否真能拦伪信号） |
| 行为可回归 | 框架迁移不改现有信号产出与降级结果，用 09:10 扫描 42 伪突破拦截数校验 |

---

## 1. 信号计算范式分类（Paradigms）

> 范式 = 「一类信号怎么算」的模板。FDT 当前主力是 P1，其余为扩展位。

| 范式 | 主流因子（实现用） | 现有 signal_type | 天然该配的验证器 |
|------|-------------------|------------------|------------------|
| **P1 通道突破** Channel Breakout | Donchian DC20/DC55、Bollinger Bands、ATR 带宽 | `channel_breakout` / `trend_confirmation` / `bb_squeeze_prebreakout` / `near_breakout` | V1 原始K线重校验、V2 成交量确认、V3 ATR择时、V4 趋势方向 |
| **P2 趋势确认** Trend Confirmation | MA 多空排列(MA20/60)、Donchian 方向、斜率 | `trend_confirmation` | V4 趋势方向、V6 稳定性 |
| **P3 均值回归** Mean Reversion | Bollinger %B 极值、价格 Z-Score、RSI 极值（**谨慎：RSI 阈值=过拟合陷阱，仅作辅助**） | `minor_signal` / `bb_squeeze_prebreakout`(部分) | V5 实体质量、V3 ATR择时、V6 稳定性 |
| **P4 回归类** Regression-based | 滚动 OLS 残差、协整残差、Kalman 价差 | （未来扩展位，当前无） | V6 稳定性、V7 拥挤度、残差平稳性（未来） |
| P5 动量 Momentum（备注） | 绝对/截面动量(50日收益) | 由 `a-share-etf-momentum` 侧负责，FDT 期货侧暂不涉及 | V6 稳定性 |

**现状落点**：P1 的计算实体 = `strategies/channel_breakout_strategy.py`（已存在）。本框架把它**注册**为范式，不重写其计算；P3/P4 给骨架，未来填主流因子实现。

---

## 2. 伪信号过滤验证器分类（Validators）

> 全部基于 `breakout_factor_research.md` 的期货实证排序（趋势方向零参数 > ATR择时 > 成交量 > ATR幅度 > 实体/时间质量）。

| ID | 验证器 | 类型 | 主流因子 | 期货实证依据 | 触发/降级 |
|----|--------|------|----------|--------------|-----------|
| **V1** | `p0_4_raw_kline` 原始K线重校验 | 幅度门禁 | 末根 high/close vs 前20根极值；spike>50% 拦截 | 防御伪造突破最后闸门（已有） | 伪突破→`false_breakout`/NOISE |
| **V2** | `volume_confirm` 成交量确认 | 确认过滤 | 末根量 / 前20根均量（ratio） | 成交量过滤器期货实证正向 | 突破无量(ratio<1.2)→降级 NOISE |
| **V3** | `atr_vol_timing` ATR波动率择时 | 择时过滤 | ATR% = atr/price | +91% 收益 / -79% 回撤（择时有效） | 低波动震荡(atr%<0.5)突破→降级 |
| **V4** | `trend_direction` 趋势方向(零参数) | 方向过滤 | 高周期 Donchian / MA 排列 | +53% profit-to-drawdown（零参数最优） | 逆高周期趋势的突破→降级 |
| **V5** | `entity_quality` 实体质量 | 质量过滤 | 实体/振幅比 = \|close-open\|/(high-low) | 实体质量属中低优先级但便宜 | 长影线十字(比<0.3)→降级 |
| **V6** | `stability` 信号稳定性 | 历史一致性 | 当前方向 vs 近 N 次扫描一致率 | 已有逻辑（validate_signals） | 一致率<40%→降级 NOISE |
| **V7** | `crowding` 拥挤度压制 | 全局闸门 | 活跃信号数上限/保留前 K | 已有逻辑（validate_signals） | 超阈值→靠后 weak 压制 NOISE |

**V4 数据源说明**：需高周期方向，由 `context["higher_tf"]` 提供（扫描时预计算或读 `ma_align`/`ma_slope` 作代理）。框架预留 provider 接口，不硬算。

---

## 3. 范式 ↔ 验证器 声明式映射（`SIGNAL_VALIDATOR_MAP`）

```python
SIGNAL_VALIDATOR_MAP = {
    # P1 通道突破 — 全装伪突破防护
    "channel_breakout":       ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing", "trend_direction"],
    "trend_confirmation":     ["p0_4_raw_kline", "trend_direction", "stability"],
    "bb_squeeze_prebreakout": ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing"],
    "near_breakout":          ["volume_confirm", "atr_vol_timing"],   # 未实质突破，轻量确认
    # P3 均值回归
    "minor_signal":           ["entity_quality", "atr_vol_timing", "stability"],
    # 全局闸门（对所有活跃信号统一跑，不按 signal_type 路由）
    "__global__":             ["stability", "crowding"],
}
```

> 规则：普通 key 按 signal_type 路由；`__global__` 对所有活跃信号跑一次（稳定性/拥挤属此类）。

---

## 4. 模块结构（具体模块 + 代码骨架）

```
scripts/signals/
  validators/
    __init__.py        # 注册表 + run_signal_validators（编排）
    base.py            # ValidationContext 数据类 + 降级辅助
    p0_4_raw_kline.py  # V1（从 scan_all._revalidate_breakouts 迁移，逐字）
    volume_confirm.py  # V2（主流因子：量比）
    atr_vol_timing.py  # V3（主流因子：ATR%）
    trend_direction.py # V4（主流因子：高周期方向）
    entity_quality.py  # V5（主流因子：实体比）
    stability.py       # V6（从 validate_signals 迁移）
    crowding.py        # V7（从 validate_signals 迁移）
  paradigms/
    __init__.py        # PARADIGM_REGISTRY + register_paradigm
    breakout.py        # P1（包装 channel_breakout_strategy，注册为范式）
    mean_reversion.py  # P3（骨架：BB %B / Z-Score 主流因子）
    regression.py      # P4（骨架：OLS 残差主流因子）
```

### 4.1 `validators/__init__.py`（注册表 + 编排）
```python
from config.settings import SIGNAL_VALIDATOR_MAP
from .base import ValidationContext, demote

VALIDATOR_REGISTRY = {}

def register_validator(vid, fn):
    VALIDATOR_REGISTRY[vid] = fn

def get_validator(vid):
    return VALIDATOR_REGISTRY.get(vid)

def run_signal_validators(all_ranked, context: ValidationContext):
    """按映射串验证器：普通 key 按 signal_type 路由；__global__ 对所有活跃信号跑一次。"""
    # 1) 逐 signal_type 路由
    for r in all_ranked:
        st = r.get("signal_type", "")
        for vid in SIGNAL_VALIDATOR_MAP.get(st, []):
            fn = get_validator(vid)
            if fn is None:
                print(f"  ⚠️ [validator] 未注册: {vid}（跳过）"); continue
            fn(r, context)
    # 2) 全局闸门
    for vid in SIGNAL_VALIDATOR_MAP.get("__global__", []):
        fn = get_validator(vid)
        if fn is None:
            print(f"  ⚠️ [validator] 未注册: {vid}（跳过）"); continue
        fn(all_ranked, context)
    return all_ranked

# 导入即注册（确保注册表填充）
from . import p0_4_raw_kline, volume_confirm, atr_vol_timing, trend_direction, entity_quality, stability, crowding
```

### 4.2 `validators/base.py`
```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ValidationContext:
    kline_data: dict = field(default_factory=dict)   # sym -> (meta, dlist)
    higher_tf: dict = field(default_factory=dict)     # sym -> "bull"/"bear"/"neutral"
    extra: dict = field(default_factory=dict)

def demote(r: dict, reason: str, new_type: str = "false_breakout"):
    r["signal_type"] = new_type
    r["grade"] = "NOISE"
    r["total"] = 0
    r["_validator_demoted"] = True
    r["_validator_reason"] = reason
```

### 4.3 V2 `volume_confirm.py`（主流因子：量比，实现就绪）
```python
from . import register_validator
from .base import demote
VOL_EXPLOSIVE_RATIO = 1.2   # 突破至少需 1.2× 均量（来自 CHANNEL_BREAKOUT_CONFIG.volume）

def validate_volume_confirm(r, context):
    if r.get("signal_type") not in ("channel_breakout", "bb_squeeze_prebreakout"):
        return
    sym = r.get("symbol", "")
    _, dlist = context.kline_data.get(sym, (None, []))
    if len(dlist) < 21:
        return
    last = dlist[-1]; prior = dlist[-21:-1]
    try:
        last_vol = float(last.get("volume", 0))
        prior_avg = sum(float(x.get("volume", 0)) for x in prior) / len(prior)
    except (ValueError, TypeError):
        return
    if prior_avg > 0 and last_vol / prior_avg < VOL_EXPLOSIVE_RATIO:
        demote(r, f"突破无量(量比{last_vol/prior_avg:.2f}<{VOL_EXPLOSIVE_RATIO})疑似假突破")

register_validator("volume_confirm", validate_volume_confirm)
```

### 4.4 V3 `atr_vol_timing.py`（主流因子：ATR%，实现就绪）
```python
from . import register_validator
from .base import demote
ATR_PCT_LOW = 0.5   # 低波动阈值（%），低于则震荡市突破易假
ATR_PCT_HIGH = 4.0  # 高波动阈值（%），高于则失控（仅降权不拦）

def validate_atr_vol_timing(r, context):
    if r.get("signal_type") not in ("channel_breakout", "bb_squeeze_prebreakout", "near_breakout", "minor_signal"):
        return
    atr = r.get("atr", 0); price = r.get("price", 0)
    if not (atr and price):
        return
    atr_pct = atr / price * 100
    if atr_pct < ATR_PCT_LOW:
        demote(r, f"低波动震荡(atr%={atr_pct:.2f}<{ATR_PCT_LOW})突破可靠性低")
    # 高波动不拦（趋势市可能真突破），仅标记供下游参考
    elif atr_pct > ATR_PCT_HIGH:
        r["_atr_hot"] = True

register_validator("atr_vol_timing", validate_atr_vol_timing)
```

### 4.5 V4 `trend_direction.py`（主流因子：高周期方向，实现就绪）
```python
from . import register_validator
from .base import demote

def validate_trend_direction(r, context):
    if r.get("signal_type") not in ("channel_breakout", "trend_confirmation"):
        return
    sym = r.get("symbol", "")
    ht = context.higher_tf.get(sym, "neutral")   # "bull"/"bear"/"neutral"
    if ht == "neutral":
        return
    if ht != r.get("direction", ""):
        demote(r, f"逆高周期趋势(ht={ht})突破疑似假")

register_validator("trend_direction", validate_trend_direction)
```

### 4.6 V5 `entity_quality.py`（主流因子：实体比，实现就绪）
```python
from . import register_validator
from .base import demote
BODY_RATIO_MIN = 0.3   # 实体/振幅 < 0.3 视为长影线十字，突破不可靠

def validate_entity_quality(r, context):
    if r.get("signal_type") not in ("minor_signal",):
        return
    sym = r.get("symbol", "")
    _, dlist = context.kline_data.get(sym, (None, []))
    if not dlist:
        return
    last = dlist[-1]
    try:
        o, h, l, c = (float(last.get(k, 0)) for k in ("open", "high", "low", "close"))
    except (ValueError, TypeError):
        return
    rng = h - l
    if rng > 0 and abs(c - o) / rng < BODY_RATIO_MIN:
        demote(r, f"长影线十字(实体比{abs(c-o)/rng:.2f}<{BODY_RATIO_MIN})信号不可靠")

register_validator("entity_quality", validate_entity_quality)
```

### 4.7 V6 `stability.py` / V4.8 V7 `crowding.py`（从 validate_signals 迁移，签名改为 `(r_or_list, context)`）
> 迁移时把 `check_signal_stability` / `crowding_filter` 改为接收 `context`（读 `context.extra["training_data"]` 代替原 `_load_training_data()`），逻辑不变。注册 id 分别为 `stability` / `crowding`。

### 4.9 `paradigms/__init__.py`
```python
PARADIGM_REGISTRY = {}
def register_paradigm(pid, cls):
    PARADIGM_REGISTRY[pid] = cls
# 导入即注册
from . import breakout, mean_reversion, regression
```

### 4.10 `paradigms/breakout.py`（P1，包装既有策略，注册为范式）
```python
from . import register_paradigm
from strategies.channel_breakout_strategy import ChannelBreakoutStrategy

class BreakoutParadigm:
    """P1 通道突破范式 — 计算实体 = 既有 ChannelBreakoutStrategy，此处仅做范式注册与元信息。"""
    id = "breakout"
    signal_types = ["channel_breakout", "trend_confirmation", "bb_squeeze_prebreakout", "near_breakout"]
    engine = ChannelBreakoutStrategy()

register_paradigm("breakout", BreakoutParadigm)
```

> `mean_reversion.py` / `regression.py` 给同结构骨架，未来填 BB %B / OLS 残差主流因子实现，本框架不实现其计算逻辑（留作「范式具体实现」的聚焦位）。

---

## 5. 接入交易系统（wiring）

| 文件 | 改动 |
|------|------|
| `config/settings.py` | 新增 `SIGNAL_VALIDATOR_MAP`（§3）与 `PARADIGM_REGISTRY` 引用点；阈值常量（`VOL_EXPLOSIVE_RATIO` 等）可复用 `CHANNEL_BREAKOUT_CONFIG.volume` 或独立定义 |
| `scan_all.py` | 删 L142-201 `_revalidate_breakouts`；L546 改为 `run_signal_validators(summary["all_ranked"], ctx)`；原 `validate_all` 调用（L549-564）移除（已折入 V6/V7 + `__global__`）；顶部 `from signals.validators import run_signal_validators`；构建 `ValidationContext(kline_data=..., higher_tf=...)` |
| `strategies/channel_breakout_strategy.py` | 不改动计算；仅作为 P1 范式实体被 `paradigms/breakout.py` 引用 |
| `validate_signals.py` | 逻辑迁至 `validators/stability.py` + `validators/crowding.py` 后，本文件可保留为兼容壳或直接删除（建议保留壳，标注 deprecated） |

> **导入副作用提示（低）**：`from signals.validators import ...` 触发 `signals/__init__.py → debate_engine` 导入；`debate_engine` 已在 analyze_targets/daily_debate/backtest 中被 import，同库已验证安全。若仍不放心，注册表可置于 `scripts/validators/`（signals 同级）规避父包 `__init__`。

---

## 6. 实施计划（分阶段，待「执行」）

| 阶段 | 内容 | 文件 |
|------|------|------|
| **Phase 0** | 注册表 + V1(P0-4)迁移（即前次 Diff 报告） | validators/__init__.py, base.py, p0_4_raw_kline.py, settings MAP, scan_all 改调用 |
| **Phase 1** | 主流验证器 V2/V3/V4/V5（本次新增，代码已就绪） | volume_confirm.py, atr_vol_timing.py, trend_direction.py, entity_quality.py |
| **Phase 2** | V6/V7 从 validate_signals 迁移 + `__global__` 闸门 | stability.py, crowding.py, scan_all 去 validate_all |
| **Phase 3** | 范式包 P1 注册 + P3/P4 骨架 | paradigms/* |
| **回归** | 59 品种扫描，伪突破拦截数 == 42（与原 09:10 一致）；验证 V2-V5 不误伤真实突破 | 全量扫描对比 |

---

## 7. 铁律闸门

- 本报告为**扩展版完整 Diff**（取代前次仅 P0-4 的 Diff），覆盖范式 + 验证器全框架。
- 涉及 `plugins/marketplaces/` → **未做任何文件改动**，待掌柜说「**执行**」后按 Phase 0→3 落地。
- 落地后更新 `technical_debt.md` §5（已确立未实施 → 已落地）、FDT `changelog.md`、`MEMORY.md` 索引。
