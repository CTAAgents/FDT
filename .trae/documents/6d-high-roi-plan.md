# D1/D3 高 ROI 提升计划 — v9.23.0

> **trace_id**: `plan-6d-high-roi-20260723`
> **目标**: D1 Context 4★→5★ + D3 Generation 4★→5★，共 4 项高 ROI 改动
> **总工作量**: ~3.5 天 | **版本**: v9.23.0

---

## 0. 当前状态（代码实测）

| 维度 | 当前成熟度 | 本次目标 | 高 ROI 项 |
|:-----|:--------:|:--------:|:----------|
| D1 Context | 4★ | 5★ | C01 Token 预算 + C03 去重 |
| D3 Generation | 4★ | 5★ | G01 差异化路由 + G02 Schema 约束 |
| D2 Tool | 4★ | 4★ | 不做（ROI 低） |

---

## 1. 实施原则（Harness 规范强制）

1. **文档先行** — 每项代码变更前先更新 `01-architecture.md` 对应描述
2. **外科手术式** — 只动必须动的行，不改周围注释/格式
3. **逐项验证** — 每项完成后独立验证，不累积
4. **版本号纪律** — 全部完成统一 bump 到 v9.23.0

---

## 2. 实施步骤

---

### Step 1: D3-G02 — Schema 硬件约束（0.5d）

**问题**: `decode_config.yaml` 中 10 个 Agent 都声明了 `response_format`，但 `agents.py` 的 `_apply_decode_config()` 只读取 `temperature` 和 `max_tokens`，忽略了 `response_format`。LLM 请求的 httpx payload 中完全没有 `response_format` 字段。

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D3 Generation：说明 `response_format` 从 YAML 注入 httpx payload 的链路

#### 代码变更

**文件 1**: `fdt_langgraph/agents.py` — `_apply_decode_config()` 方法（~L48-62）

追加 `response_format` 读取：

```python
def _apply_decode_config(self):
    if not self.agent_name:
        return
    cfg = _get_decode_config().get("agents", {}).get(self.agent_name, {})
    if not cfg:
        return
    if "temperature" in cfg:
        self.temperature = cfg["temperature"]
    if "max_tokens" in cfg:
        self.max_tokens = cfg["max_tokens"]
    # v9.23.0: 注入 response_format
    if "response_format" in cfg:
        self.response_format = cfg["response_format"]
```

**文件 2**: `fdt_langgraph/agents.py` — 在 `FdtAgentExecutor.__init__()` 中初始化 `self.response_format = None`

**文件 3**: `fdt_langgraph/agents.py` — `_call_llm()` 方法（~L171-176），构建 httpx payload 时追加：

```python
data = {
    "model": model,
    "messages": messages,
    "max_tokens": self.max_tokens,
    "temperature": self.temperature,
}
# v9.23.0: 注入 response_format 硬件约束
if getattr(self, "response_format", None):
    data["response_format"] = {"type": "json_object"}
```

**注意**: 使用 `{"type": "json_object"}` 而非直接传入 YAML 中的 `response_format` 结构（因为不同 LLM 的 `response_format` 格式不同，`json_object` 是大多数 LLM API 都支持的最低公共接口）。

#### 验证
- `grep -n "response_format" fdt_langgraph/agents.py` → 3 处匹配（`__init__` 初始化 + `_apply_decode_config` 读取 + `_call_llm` 注入）
- 可选：mock LLM 调用，确认 payload 中包含 `"response_format": {"type": "json_object"}`

---

### Step 2: D3-G01 — 模型差异化路由（1d）

**问题**: `decode_config.yaml` 中所有 Agent 配了 `model` 字段，但 `_apply_decode_config()` 完全忽略它。实际模型选择仅靠环境变量链，YAML 配置是死配置。

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D3 Generation：说明模型选择链路 YAML → 环境变量 → 硬编码默认值

#### 代码变更

**文件 1**: `fdt_langgraph/agents.py` — `_apply_decode_config()` 方法追加 `model` 读取：

```python
# v9.23.0: 注入 model（优先级: YAML > 环境变量 > 硬编码默认值）
if "model" in cfg:
    self.model = cfg["model"]
```

**文件 2**: `fdt_langgraph/agents.py` — `_call_llm()` 方法中模型选择逻辑（~L146-148）改为使用 self.model：

```python
# 原代码
api_key = self._resolve_llm_config("API_KEY", os.environ.get("FDT_LLM_API_KEY"))
api_base = self._resolve_llm_config("API_BASE", os.environ.get("FDT_LLM_API_BASE", "https://api.deepseek.com/v1"))
model = self._resolve_llm_config("MODEL", os.environ.get("FDT_LLM_MODEL", "deepseek-chat"))

# 改为
model = getattr(self, "model", "") or self._resolve_llm_config(
    "MODEL", os.environ.get("FDT_LLM_MODEL", "deepseek-chat"))
```

**注意**: `self.model` 优先（来自 YAML），然后环境变量，最后硬编码默认值。这是"YAML > 环境变量 > 硬编码"的优先级倒置——因为 `_apply_decode_config()` 的语义是"YAML 配置以最高优先级覆盖"，所以这里应该是 YAML 最先检查。

**文件 3**: `config/agents/decode_config.yaml` — 调整模型差异化：

保留 judge/judge_deputy/judge_heldout/risk_manager 使用 `deepseek-v4-flash`（高质量模型用于关键决策），将 bull/bear 分析员、技术/基本面研究员、chain_analyst 降低到 `deepseek-chat`（低成本模型，他们仅需中等质量）。

具体分配建议：

| Agent | 模型 | 理由 |
|:------|:-----|:------|
| judge | deepseek-v4-flash | 关键裁决需要最高质量 |
| judge_deputy | deepseek-v4-flash | 副判官独立裁决 |
| judge_heldout | deepseek-v4-flash | 审计一致性需要准确 |
| risk_manager | deepseek-v4-flash | 风控决策不可降级 |
| bullish_analyst | deepseek-chat | 辩论供弹，中等质量即可 |
| bearish_analyst | deepseek-chat | 同左 |
| chain_analyst | deepseek-chat | 产业链分析，不需要实时推理 |
| technical_researcher | deepseek-chat | 技术分析有 FDC 数据辅助 |
| fundamental_researcher | deepseek-chat | 基本面分析有结构化数据 |

#### 验证
- `grep -n "model: deepseek-chat" config/agents/decode_config.yaml` → 5 个 Agent 使用低成本模型
- `grep -n "model: deepseek-v4-flash" config/agents/decode_config.yaml` → 4 个 Agent 使用高质量模型
- mock 创建 `FdtAgentExecutor("bullish_analyst")`，确认 `self.model == "deepseek-chat"`
- mock 创建 `FdtAgentExecutor("judge")`，确认 `self.model == "deepseek-v4-flash"`

---

### Step 3: D1-C01 — Token 预算控制（1d）

**问题**: `_build_debate_context()` 生成的 context 无长度限制。`scripts/llm/token_budget.py` 存在 `TokenBudget.estimate()` 方法但从未被使用。

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D1 Context：说明 context 构建有 token 预算控制

#### 代码变更

**文件**: `fdt_langgraph/nodes.py` — `_build_debate_context()` 函数末尾

在 `return` 前追加 token 预算控制：

```python
# v9.23.0: Token 预算控制
import os
_MAX_CONTEXT_TOKENS = int(os.environ.get("FDT_CONTEXT_MAX_TOKENS", "8000"))
raw_context = "\n".join(lines)  # 先拼合
try:
    try:
        from scripts.llm.token_budget import TokenBudget
        estimated = TokenBudget.estimate(raw_context)
    except ImportError:
        # fallback: 粗略估计
        estimated = len(raw_context) // 2
    if estimated > _MAX_CONTEXT_TOKENS:
        ratio = _MAX_CONTEXT_TOKENS / max(estimated, 1)
        cutoff = int(len(raw_context) * ratio)
        raw_context = raw_context[:cutoff]
        raw_context += f"\n\n[系统截断: context 预估 {estimated} tokens > 上限 {_MAX_CONTEXT_TOKENS}, 已截断至约 {_MAX_CONTEXT_TOKENS} tokens]"
        logger.warning(f"[Context] context token 预算超限: {estimated} > {_MAX_CONTEXT_TOKENS}, 已截断")
except Exception:
    pass

return raw_context
```

**FDT_CONTEXT_MAX_TOKENS 环境变量**: 默认 8000，可通过环境变量调整，覆盖 `03-configuration.md` 需同步更新。

#### 验证
- 构造超大 state，调用 `_build_debate_context(state)`，确认返回内容不含截断标记
- 构造极端超大 state（> 8000 tokens），确认返回包含 `[系统截断]` 标记
- `FDT_CONTEXT_MAX_TOKENS=500` 时，确认更早截断

---

### Step 4: D1-C03 — 四源 context 去重（1d）

**问题**: `_build_fdc_technical_context()` (L936-L958) 和 `_build_fdc_fundamental_context()` (L1037-L1059) 各有 ~20 行完全相同的"数技源扫描信号对照表"代码，唯一差异是标题文本。

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D1 Context：说明扫描信号对照表已提取为共享函数

#### 契约先行
先定义共享函数签名：

```python
def _build_scan_signal_table(all_ranked: list, symbols: list, header_suffix: str = "") -> list:
    """生成数技源扫描信号对照表的格式化行列表。
    
    Args:
        all_ranked: scan_results 中的 all_ranked 列表
        symbols: 当前品种列表
        header_suffix: 标题后缀（如 "— 仅供参考"）
    
    Returns:
        格式化后的文本行列表
    """
```

#### 代码变更

**文件**: `fdt_langgraph/nodes.py`

1. **新增共享函数**，从两个函数的重复代码中提取：

```python
def _build_scan_signal_table(all_ranked: list, symbols: list, header_suffix: str = "") -> list:
    """生成数技源扫描信号对照表的格式化行列表。"""
    lines = []
    lines.append(f"\n\n【数技源扫描信号对照（TDX数据源）{header_suffix}】")
    lines.append("品种 | 方向 | 总分 | 等级 | RSI | ADX | 均线排列 | 子策略一致性")
    lines.append("-" * 80)
    for item in all_ranked:
        sym = item.get("symbol", "").upper()
        if sym not in [s.upper() for s in symbols]:
            continue
        dir_map = {"bull": "多头", "bear": "空头", "neutral": "中性"}
        dir_str = dir_map.get(item.get("direction", ""), item.get("direction", ""))
        total = item.get("total", 0)
        grade = item.get("grade", "N/A")
        rsi = item.get("rsi", "N/A")
        adx = item.get("adx", "N/A")
        ma = item.get("ma_align", "N/A")
        sub_sigs = item.get("sub_signals", [])
        sub_bear = sum(1 for s in sub_sigs if s.get("direction") in ("bear", "SELL"))
        sub_bull = sum(1 for s in sub_sigs if s.get("direction") in ("bull", "BUY"))
        sub_total = len(sub_sigs)
        consistency = f"空{sub_bear}/多{sub_bull}/共{sub_total}" if sub_total else "N/A"
        lines.append(f"{sym} | {dir_str} | {total} | {grade} | {rsi} | {adx} | {ma} | {consistency}")
    return lines
```

2. **替换 `_build_fdc_technical_context()` 中的重复代码**（原 L936-L958）：

```python
# ── 追加数技源扫描对照（让观澜同时看到两套数据，做交叉验证） ──
if scan_results:
    all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
    if all_ranked:
        lines.extend(_build_scan_signal_table(all_ranked, symbols, "— 仅供参考"))
```

3. **替换 `_build_fdc_fundamental_context()` 中的重复代码**（原 L1037-L1059）：

```python
# ── 追加数技源扫描对照 ──
if scan_results:
    all_ranked = scan_results.get("all_ranked", []) if isinstance(scan_results, dict) else []
    if all_ranked:
        lines.extend(_build_scan_signal_table(all_ranked, symbols))
```

#### 验证
- `grep -n "_build_scan_signal_table" fdt_langgraph/nodes.py` → 3 处匹配（定义 + 2 处调用）
- 检查 technical context 输出标题含"— 仅供参考"，fundamental context 不含
- 检查两个 context 的信号表格内容一致

---

## 3. 实施顺序

```
Step 1 (G02 Schema约束)    Step 2 (G01 差异路由)     Step 3 (C01 Token预算)
  0.5d, agents.py            1d, agents.py + YAML      1d, nodes.py
  文档: 01-architecture.md    文档: 01-architecture.md   文档: 01-architecture.md

Step 4 (C03 去重)
  1d, nodes.py
  文档: 01-architecture.md
```

**依赖**: 无外部依赖，4 项可并行（修改不同文件/不同函数）。

---

## 4. 文档更新清单

| 文档 | 变更内容 | 对应 Step |
|:-----|:---------|:---------:|
| `01-architecture.md` §5.2 D3 | `response_format` 注入链路 + 模型差异化路由 | 1,2 |
| `01-architecture.md` §5.2 D1 | Token 预算控制 + 扫描信号表共享函数 | 3,4 |
| `03-configuration.md` | `FDT_CONTEXT_MAX_TOKENS` 环境变量 | 3 |
| `07-operations.md` | v9.23.0 版本历史 | 全部 |

---

## 5. Harness 合规

每 Step 完成后运行：
```bash
python scripts/pre_commit_harness_check.py
python scripts/verify_doc_consistency.py
```

---

## 6. 完成标准

| 检查项 | 方法 | 期望结果 |
|:-------|:-----|:---------|
| G02 | `grep "response_format" agents.py` | 3 处匹配 |
| G02 | httpx payload 含 `response_format` | mock 验证 |
| G01 | `grep "model:" decode_config.yaml` | 4 个 flash + 5 个 chat |
| G01 | `FdtAgentExecutor("bullish_analyst").model` | `"deepseek-chat"` |
| C01 | context 超限时含 `[系统截断]` | 极端大 state 验证 |
| C01 | `grep "TokenBudget" nodes.py` | ≥1 处调用 |
| C03 | `grep "_build_scan_signal_table" nodes.py` | 3 处匹配 |
| 预提交 | `python scripts/pre_commit_harness_check.py` | 全部通过 |
| 版本 | `grep "^version" pyproject.toml` | `v9.23.0` |
