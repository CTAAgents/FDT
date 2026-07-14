# 信号范式 ↔ 验证器 框架 — 落地总结（2026-07-14）

> 按 `signal_paradigm_validator_framework.md`（Diff v1）落地。铁律闸门已开（掌柜说"执行"）。
> 设计哲学：只用公开主流因子，不挖不可解释的新因子；未来只聚焦「范式实现 + 验证器合理性」。

## 1. 新建模块（FDT 生产代码 `plugins/marketplaces/.../skills/quant-daily/scripts/`）

### `signals/validators/`（验证器可插板库）
| 文件 | 验证器 | 因子 | 来源 |
|------|--------|------|------|
| `__init__.py` | 注册表 `VALIDATOR_REGISTRY` + `run_signal_validators` 编排 | — | 新增 |
| `base.py` | `ValidationContext` + `demote()` 降级契约 | — | 新增 |
| `p0_4_raw_kline.py` | **V1** 原始K线重校验（P0-4） | 末根 high/close vs 前20根极值；spike>50%拦截 | 从 scan_all 逐字迁移 |
| `volume_confirm.py` | **V2** 成交量确认 | 量比 = 末根量/前20根均量（<0.8 拦） | 新增（主流因子） |
| `atr_vol_timing.py` | **V3** ATR波动率择时 | ATR% = atr/price（<0.5% 拦） | 新增（主流因子） |
| `trend_direction.py` | **V4** 趋势方向零参数 | 高周期 Donchian/MA 方向（逆趋势拦） | 新增（主流因子） |
| `entity_quality.py` | **V5** 实体质量 | 实体/振幅比（<0.3 拦） | 新增（主流因子） |
| `stability.py` | **V6** 信号稳定性 | 历史方向一致率 | 从 validate_signals 迁移 |
| `crowding.py` | **V7** 拥挤度压制 | 活跃信号数上限（全局闸门） | 从 validate_signals 迁移 |

### `signals/paradigms/`（范式注册包）
| 文件 | 范式 | 说明 |
|------|------|------|
| `__init__.py` | `PARADIGM_REGISTRY` + `register_paradigm` | 新增 |
| `breakout.py` | **P1** 通道突破 | 登记既有 `ChannelBreakoutStrategy`（不重写） |
| `mean_reversion.py` | **P3** 均值回归 | 骨架（BB %B / Z-Score 聚焦位） |
| `regression.py` | **P4** 回归类 | 骨架（OLS/协整残差 聚焦位） |

## 2. 接线改动
- **`config/settings.py`**：新增 `SIGNAL_VALIDATOR_MAP`（`signal_type → [validator_ids]`，含 `__global__` 全局闸门）。单一真相源。
- **`scan_all.py`**：删除硬编码 `_revalidate_breakouts`（原 L142-201）；调用改为 `run_signal_validators(summary["all_ranked"], ValidationContext)`；旧 `validate_all` 调用折入 V6/V7 + `__global__`。
- **`validate_signals.py`**：标 `DEPRECATED`（逻辑已迁至 validators/），保留兼容壳。

## 3. 调用约定（自文档化）
- 普通 key（如 `channel_breakout`）下的验证器 → 单记录 `fn(r, ctx)`（按记录逐条调用）
- `__global__` 下的验证器（V6/V7 列表级） → `fn(all_ranked, ctx)`（跑一次）
- 加新验证器 = 写模块 + `register_validator` + 在 `SIGNAL_VALIDATOR_MAP` 登记一行，**不改扫描主链**。

## 4. 验证结果
- ✅ `py_compile` 全过（scan_all / settings / 13 个新模块）
- ✅ 合成自测：V1 真拦伪突破（`FAKE → false_breakout / NOISE`），保留真突破（`TEST channel_breakout` 不变）
- ✅ 注册表 7 验证器 + 3 范式齐全；`SIGNAL_VALIDATOR_MAP` 正常加载
- ✅ 生产等效路径（`sys.path` 含 root + scripts）导入无 `debate_engine` 副作用

## 5. 待办 / 注意
- **全量实时重扫复核**：09:10 扫描的 42 伪突破拦截数应不变（P0-4 逻辑逐字保留；V2-V5 阈值保守，不误伤真实突破）。建议下次盘前扫盘后对比。
- **V4 趋势方向**：需 `context.higher_tf` 高周期方向输入，当前未预计算 → 自动跳过（不误伤）；预留 provider 接口，未来接高周期方向即可启用。
- **下一阶段聚焦**：范式具体实现（调主流因子权重/阈值）+ 验证器合理性（是否真拦伪信号），无需再挖新因子。

## 6. FDT 记忆已更新
- `MEMORY.md` §信号层架构原则 → 标注「已落地」
- `technical_debt.md` §5 → 「落地状态」改为已落地 + FDT 当前状态更新
- `changelog.md` → 新增 2026-07-14 10:44 条目
