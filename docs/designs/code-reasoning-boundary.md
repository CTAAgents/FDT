# 代码-推理边界硬切割 —— 改进实施方案

## 致因

当前 FDT 系统中，部分本应由代码精确计算的逻辑被交由 LLM 处理，导致：
- **entry_price 偏离市价** — LLM 可能微调价格，违反"市价单"铁律
- **stop_loss/target 不一致** — LLM 估算的止损位缺乏一致性规则
- **仓位超限** — LLM 可能输出超出风控上限的仓位
- **技术评分不精确** — LLM 打分的 benchmark 不可靠（同一品种重复跑可能不同）

## 总则

> 能用数学公式精确计算的，绝不丢给 LLM。
> 代码负责精确计算（指标/参数/约束），LLM 只负责需要语义理解的推理判断（趋势/矛盾/权衡/裁决）。

## 边界分类

| 级别 | 定义 | 责任方 |
|:-----|:------|:-------|
| **L0 — 代码硬约束** | 计算结果直接输出，LLM 不可修改 | `nodes.py` Python 代码 |
| **L1 — 代码计算 + LLM 赋意** | 代码计算精确值，注入 prompt 供 LLM 引用解释 | `_build_xxx_context()` 格式化 |
| **L2 — 纯 LLM 推理** | 无数学公式，依赖语义理解 | Agent prompt |

## 待切割的 4 个边界

### 边界 1: `node_technical` — 技术评分代码化

**问题**：当前观澜 Agent 输出的 score（0-100）由 LLM 生成，不精确不可复现。

**方案（L1）**：代码从技术指标计算基准分，注入 prompt 供 LLM 调整。

```python
def compute_technical_score(per_symbol_indicators: dict) -> dict[str, int]:
    """从技术指标精确计算基准评分（0-100）。
    
    评分规则：
    - 趋势分 40%：均线排列（多头+20, 空头-20, 粘合0）+ 斜率
    - 动量分 30%：RSI 位置（30-70 中性, <30 超卖+10, >70 超买-10）
    - 成交量分 20%：量价配合（放量上涨+15, 缩量下跌-15）
    - 波动率分 10%：ATR 相对位置
    """
    ...
```

修改位置：[node_technical](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) — LLM prompt 中 score 字段改为引用代码计算的基准分

### 边界 2: `node_verdict` — entry_price 代码硬约束

**问题**：当前只通过 prompt 约束"entry_price 必须等于收盘价"，LLM 仍可能输出微调价格。

**方案（L0）**：LLM 输出解析后，代码强制覆写 entry_price。

```python
# 在 node_verdict 解析 LLM 输出后，强制覆写 entry_price
for sym in symbols:
    sp = sym_prices.get(sym.upper(), {})
    market_price = sp.get("price")
    if market_price and sym in per_symbol:
        per_symbol[sym]["entry_price"] = float(market_price)
```

修改位置：[node_verdict](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) — LLM 输出解析 + 信号构建之间

### 边界 3: `node_verdict` — stop_loss/target 代码精确计算

**问题**：当前 stop_loss 和 target_price 由 LLM 基于 ATR 估算，不同次跑可能不同。

**方案（L0）**：代码按统一规则计算，LLM 只选择方向，不计算价格。

```python
def compute_stop_target(
    direction: str, entry_price: float, atr: float,
    risk_multiplier: float = 1.5, reward_multiplier: float = 2.0,
) -> tuple[float, float]:
    """精确计算止损和止盈价格。
    
    多头: stop = entry - atr * risk_multiplier, target = entry + atr * reward_multiplier
    空头: stop = entry + atr * risk_multiplier, target = entry - atr * reward_multiplier
    """
    if direction == "bullish":
        stop = entry_price - atr * risk_multiplier
        target = entry_price + atr * reward_multiplier
    elif direction == "bearish":
        stop = entry_price + atr * risk_multiplier
        target = entry_price - atr * reward_multiplier
    else:
        return 0.0, 0.0
    return round(float(stop), 2), round(float(target), 2)
```

LLM 输出只需 `direction` 字段，`stop_loss_price` 和 `target_price` 由代码从 state 中的 ATR 计算后填充。

修改位置：[node_verdict](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) — LLM prompt 中移除 stop/target 计算要求 + 解析后代码填充

### 边界 4: `node_risk_check` — 仓位约束代码硬校验

**问题**：当前风控 Agent 根据规则判断仓位，可能输出超出风控上限的值。

**方案（L0）**：代码先计算最大允许仓位（基于账户权益、品种保证金、集中度限制），然后：

1. 注入 prompt 作为约束告诉 LLM
2. LLM 输出后代码做二次校验，超限则钳制

```python
def compute_max_position(
    symbol: str, entry_price: float, account_equity: float,
    margin_rate: float = 0.1, max_single_pct: float = 0.2,
) -> float:
    """计算最大允许仓位百分比。
    
    - 基于保证金：position = equity * max_single_pct / (price * contract_multiplier * margin_rate)
    - 基于集中度：单品种不超过总权益的 max_single_pct
    """
    return round(max_single_pct * 100, 1)  # 简化：返回 % 值
```

修改位置：[node_risk_check](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) — 风控输出解析后做 `min(llm_pct, max_pct)` 钳制

## 实施阶段

### Phase 1: entry_price 硬约束（最小改动，最大收益）

| 步骤 | 文件 | 内容 |
|:-----|:-----|:------|
| 1.1 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | `node_verdict` 中 LLM 解析后，遍历 per_symbol 强制覆写 `entry_price = sym_prices[sym].price` |
| 1.2 | 测试 | 验证 mock LLM 输出不同 entry_price 时均被覆写 |

### Phase 2: stop_loss/target 代码精确计算

| 步骤 | 文件 | 内容 |
|:-----|:-----|:------|
| 2.1 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | 新增 `_compute_stop_target()` 函数 |
| 2.2 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | `node_verdict` LLM prompt 中移除 stop/target 计算要求（LLM 只需输出 direction） |
| 2.3 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | `node_verdict` 解析后根据 direction 调用 `_compute_stop_target()` 填充 stop_loss/target |
| 2.4 | 测试 | 测试不同方向/ATR 下的 stop/target 计算 |

### Phase 3: 仓位代码硬校验

| 步骤 | 文件 | 内容 |
|:-----|:-----|:------|
| 3.1 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | 新增 `_clamp_position()` 函数 |
| 3.2 | [node_risk_check](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | 风控输出解析后做 `position_pct = min(llm_value, max_pct)` |
| 3.3 | 测试 | 验证超限仓位被钳制 |

### Phase 4: 技术评分代码化

| 步骤 | 文件 | 内容 |
|:-----|:-----|:------|
| 4.1 | `data_adapter/factors/technical_score.py` | 新增 `compute_technical_score()` — 从已有技术指标计算基准分 |
| 4.2 | [nodes.py](file:///d:/Programs/FDT/fdt_langgraph/nodes.py) | `node_technical` prompt 中注入基准分，LLM 只在 ±10 范围内调整 |
| 4.3 | 测试 | 验证不同行情条件下评分的可复现性 |

## 降级策略

| 边界 | 数据缺失时 | 兜底 |
|:-----|:-----------|:-----|
| entry_price hardcode | sym_prices 中无该品种 | 保持 LLM 输出值，记录 warning |
| stop_loss/target 计算 | ATR 不可用 | 使用固定百分比（1%） |
| 仓位钳制 | 账户权益/保证金率不可知 | 跳过钳制，仅记录 warning |
| 技术基准分 | 指标不足时 | 保持 LLM 评分 |

## 优先级

| 边界 | 影响面 | 收益 | 工作量 | 优先级 |
|:-----|:------|:----|:------:|:------:|
| entry_price 硬约束 | 所有信号 | 消除市价偏离 P0 违规 | 3 行代码 | **P0 — 立即** |
| stop_loss/target 精确计算 | 所有交易参数 | 参数一致性 + 可审计 | ~30 行代码 | **P1 — 本轮** |
| 仓位代码硬校验 | 风控审核 | 防止仓位超限 | ~20 行代码 | **P1 — 本轮** |
| 技术评分代码化 | 观澜输出 | 评分可复现 | ~50 行代码 + 新模块 | P2 — 下轮 |
