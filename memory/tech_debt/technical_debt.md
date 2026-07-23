# 技术债务（2026-07-06 掌柜确立）

以下为架构层面的技术债务，当前已用data_interface桥接，后续需要迁移以保持架构优雅。

## 1. 指标计算核心独立（高优先级）— ✅ 已落地 2026-07-14

**原目标（已修正）**: 抽取为独立的 `futures-data-engine` skill。
**修正（掌柜架构质疑触发）**: 不新建 skill。`futures_data_core`（即 FDC）本就是数据网关包，其 `futures_data_core.indicators` 子模块已是 FDC 体系内的指标计算层（且为公开 API）。独立 skill 会与 FDC 命名混淆、违反"简单优先"。

**最终方案（A'，已落地）**: 收编进 `futures_data_core/indicators/`（FDC 体系内，单一真相源），quant-daily 侧改为 re-export shim。

**落地动作**:
- `calc_core.py`（2065 行真引擎，TDX 100% 对齐，45 字段）→ `futures_data_core/indicators/tdx_compat.py`（整份搬运 + 显式 `__all__`，指标逻辑零变更）
- `indicators_legacy.py` 的 `_compute_indicators_numpy` + `safe_float` → `futures_data_core/indicators/legacy_numpy.py`
- `assess_trend_maturity` 双副本（core.py:98 / indicators_legacy.py:21）合并：经 byte-diff 发现 legacy 版为功能超集（多返回 `bb_squeeze`/`bb_width_pct`/`dc55_trend`），采用 legacy 版为权威 → `futures_data_core/indicators/trend_maturity.py`
- `futures_data_core/indicators/__init__.py` 统一 re-export 全部公共 API（44 个公开名）
- quant-daily 的 `calc_core.py` / `core.py` / `indicators_legacy.py` 改为 re-export shim；`tdx_bridge.py` 本就依赖 FDC（仅 import `compute_indicators`），无需改动
- 约 20 个 importer 不动，透明转发

**验证**: py_compile 全过 + 四路导入冒烟（FDC 直连 / quant-daily shim 两路，符号 `is` 同源）+ 数值回归单测（calculate_tdx_compatible 45 字段确定性、assess_trend_maturity 超集键、_compute_indicators_numpy 65 字段）+ 全 17 importer 结构回归 + 实跑 PK/RB/B/UR 指标管线正常。

**原 §1 误述修正**: 所谓"双 core 循环依赖"实测为代码重复 + 命名混乱（quant-daily 冗余一份真引擎 + legacy + 双同名 core.py），无运行期硬循环。

**设计文档**: `docs/design/tech_debt_s1_indicator_extraction_plan.md`（v0.3，含 byte-diff 与数值回归单测步骤）。

## 2. 策略打分迁移 — ✅ 已落地 2026-07-14

**当前状态**: `layered_l1l4` 已在 v8.7.0 中完全删除。L1-L4 评分模块（run_l1l4_scan.py、l1l4_scoring.py、layered_l1l4.py）及整个 technical-analysis skill 的 L1-L4 部分已移除。观澜技术面分析现由 LLM 推理直接生成 TechnicalOutput。

**目标达成**: 模块已删除，无需进一步操作。

## 3. 因子择时策略打分迁移 — ✅ 已落地 2026-07-14

**当前状态**: `factor_timing` 已在 v8.7.0 中完全删除。factor_timing.py、run_factor_timing_scan.py 已移除。探源基本面分析现由 LLM 推理直接生成 FundamentalStateVector。

**目标达成**: 模块已删除，无需进一步操作。

## 4. 删除不必要的环节（2026-07-06 已完成）

## 5. 信号层架构规范：信号范式 ↔ 专属验证器（2026-07-14 确立）

**原则**：信号计算逻辑与验证器应是**范式专属配对**（`signal_type → [validator_ids]` 声明式映射），**而非一个通用验证器验证所有信号**。

**逻辑依据**：
- 伪信号的成因因范式而异：突破类=末根没真穿极值（毛刺/spike/流动性扫荡）；回归类（RSRS）=斜率被单根极端K线拉歪、R²低；横截面=离群值/zscore失真/低流动性；均值回复=趋势市假反转；订单流=扫止损后回流。验证器必须先懂信号语义才能判断"真"。
- 通用验证器会退化为"最小公倍数"浅层检查（如只查 `total>0`），对谁都不够好，等于没验证。
- 符合开放封闭原则：新增范式只加"信号+验证器"一对，不改现有验证器。

**映射示例**：
| 信号范式 | 专属验证器 | 验证逻辑 |
|:-------|:----------|:--------|
| 通道突破（Donchian/BB） | `P0-4` 原始K线复算 | 末根 high/close 超前20根极值；spike>50%拦截 |
| 回归斜率（RSRS类） | `R²稳定性` + `残差zscore` | R²>阈值且残差不过度偏离 |
| 横截面相对强度 | `zscore异常` + `流动性门禁` | 剔除离群、成交量过滤 |
| 均值回复（布林带内回归） | `regime过滤`（ADX<25才放行） | 震荡市才信回复信号 |
| 订单流/微观结构 | `影线/返回结构` | 长上影+返回区间内=陷阱 |
| 动量突破 | `ATR幅度` + `时间维持` | 突破幅度>0.5×ATR且维持N根 |

**FDT 当前状态（2026-07-14 已落地）**：
- ✅ 验证器可插板库：`signals/validators/`（注册表 `VALIDATOR_REGISTRY` + `run_signal_validators` 编排）
- ✅ 7 个验证器全部就位：V1 `p0_4_raw_kline`（从 scan_all 迁移）、V2 `volume_confirm`、V3 `atr_vol_timing`、V4 `trend_direction`、V5 `entity_quality`、V6 `stability`（从 validate_signals 迁移）、V7 `crowding`（从 validate_signals 迁移）
- ✅ 声明式映射：`config/settings.py.SIGNAL_VALIDATOR_MAP`（`signal_type → [validator_ids]`，含 `__global__` 全局闸门）
- ✅ 范式包：`signals/paradigms/`（PARADIGM_REGISTRY：P1 breakout 已登记 / P3 mean_reversion / P4 regression 骨架）
- ✅ `scan_all.py` 已改为按映射路由（删硬编码 `_revalidate_breakouts`，旧 `validate_all` 调用折入 V6/V7 + `__global__`）
- ⚠️ V4 趋势方向需 `context.higher_tf` 高周期方向输入（当前未预计算 → 自动跳过，预留 provider 接口，不误伤）

**目标架构**（对称可插板）：
```
strategies/           → 信号计算（可插板，registry）
signals/validators/   → 验证器库（可插板）：p0_4_revalidate / r2_stability / zscore_anomaly / regime_filter ...
config/               → signal_type → [validator_ids]  声明式映射
scan_all              → 按映射串验证器（策略无关）
```

**缘起**：`early_signal.py` 因"突破判定散落多处"诱发重复定义（已收掉）；本原则防止未来多范式信号层再次诱发"每类信号各写一套校验"的重复。与 P0-4 定位（突破类专属数据验证器，非判定器）一致。

**落地状态**：已落地（2026-07-14）。验证器库 + 声明式映射 + 范式包均建成，全用公开主流因子，无黑盒。设计见 `automations/automation-1783403060853/signal_paradigm_validator_framework.md`（框架 Diff v1）。后续加范式/验证器 = 注册 + 在 `SIGNAL_VALIDATOR_MAP` 登记一行，不改扫描主链。

- ✅ 独立策略注册 → 取消
- ✅ 因子择时独立策略注册 → 取消
- ✅ quant-daily中双通道辩论筛选(debate_brief) → 不再使用
- ✅ 固定多空辩手 → 改为动态正反方（根据signal_type）
- ✅ scan_all.py --dual 模式 → 已删除（2026-07-14 Phase C）；三类信号改由独立生产者产出：scan_all.py(channel_breakout)→full_scan_summary
