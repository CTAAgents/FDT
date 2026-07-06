# FDT 专家团变更日志

> 记录所有代码/配置/机制的变更。按时间逆序排列。

---

## 2026-07-06 20:00 — feedback闭环 + 辩论权重可配置+进化

**文件改动**:
- `scripts/validate_verdicts.py` — 新增 `save_feedback_entries()`，验证后自动写 `feedback_entries.json`（匹配 risk_engine 的 `build_feedback_entry` 格式），对接 `aggregate_feedback` 的假破统计
- `skills/quant-daily/scripts/signals/debate_brief.py` — 五维权重改为从 `memory/debate_weights.json` 动态加载，`compute_debate_score` 新增 `weights` 参数，评分逻辑改为按权重百分比计算
- `memory/debate_weights.json` — 创建默认权重文件（40/25/20/10/5），供 evolve_agents 调节
- `scripts/evolve_agents.py` — 新增 `evolve_debate_weights()`，按各维度得分与 correct 的相关性调整权重→写回 `debate_weights.json`。加入主循环，名"训辩权重"

---

## 2026-07-06 19:57 — risk_engine BUG修复 + debate_brief硬编码修复

**文件改动**:
- `skills/debate-risk-manager/scripts/risk_engine.py`
  - BUG-1: `calc_transaction_cost` 定义两次→重名覆盖→摩擦降仓静默失效。删除重复定义，重命名统一为 `calc_friction_entry`，修复 `calculate_position` 调用签名
  - BUG-2: `_pattern_risk_override` 中 `return 0.7` 后紧跟 `return 1.0` 死代码。修复为正常控制流

- `skills/quant-daily/scripts/signals/debate_brief.py`
  - chain_score: 从硬编码集 → 按链内品种数动态计算（≤3=3分, ≥4=4分, ≥6=5分）
  - base_confidence: 修复 `f_conf` 可能0-100溢出被cap的问题，归一化到0-1
  - ATR fallback: 从通用2% → 按价格区间分级（≤5000≈3%, 中价2%, ≥50000≈1.5%）
  - `compute_debate_score` 新增 `chain_count` 参数

---

## 2026-07-06 19:51 — FDT机制层问题修复（对照审计清单）

### 背景
掌柜提交9条FDT机制层问题清单（P0×2, P1×2, P2×5），逐条源码验证后确认8条，1条待核实→升级为实际BUG。

### 文件改动

**`scripts/validate_verdicts.py`** (P0/P1根修复)
- 数据获取从单点close → K线序列（8根日K线）
- 验证逻辑从"收盘价判方向"→"bar high/low检测stop/target触发"
- 新增：跳空扫损检测(`gap_stop`)、真实实现盈亏(`realized_pnl_pct`)
- 旧版验证保留为降级路径

**`pipeline/runner.py`** (P2数据流缺口修复)
- `step_record_history` 末尾追加 `record_verdicts.py` 调用
- 查找 REPORT_DIR 下的 `debate_results.json` 同步到 `execution_followup.json`
- 从此 `evolve_agents.py` 能读到数据，自进化闭环接通

**`scripts/evolve_agents.py`** (P0/P1进化指标修复)
- `get_validated_verdicts` 提取 `hit_stop`/`hit_target`/`realized_pnl_pct`
- `evolve_risk_manager`：用真实止损触发率替代 `avg_stop_dist` 代理
- `evolve_strategist`：用真实T1达标率替代 `change_pct>3%` 代理
- 所有Agent改用 `realized_pnl_pct` 替代方向振幅 `pnl_pct`

### 影响范围
| 问题 | 等级 | 状态 |
|:-----|:----:|:-----|
| 验证标签与止损脱节 | P0 | 已修复：K线序列 stop/target检测 |
| 自进化优化方向而非盈亏 | P0 | 已修复：所有Agent改用 realized_pnl_pct |
| 风控参数进化代理指标失真 | P1 | 已修复：真实 stop_hit_rate |
| 验证窗口T+1收盘价 | P1 | 已修复：gap_stop 跳空检测 |
| LLM判LLM裁判循环 | P2 | 设计层局限，缓解措施足够 |
| 进化依赖间接代理 | P2 | 已修复：真实指标替代代理 |
| 无执行层 | P2 | 待修：摩擦成本未完全注入验证结果 |
| 数据流衔接缺口 | P2→**确认BUG** | 已修复：runner调record_verdicts |
