# 技术债务（2026-07-06 掌柜确立）

以下为架构层面的技术债务，当前已用data_interface桥接，后续需要迁移以保持架构优雅。

## 1. 指标计算核心独立（高优先级）

**当前状态**: `quant-daily/scripts/indicators/core.py`、`tdx_bridge.py` 仍在quant-daily中，technical-analysis和three_signal策略通过import引用。

**目标**: 抽取为独立的 `futures-data-engine` skill。
- 包含：`indicators/core.py`、`indicators/tdx_bridge.py`、`indicators/indicators_legacy.py`
- 所有策略（three_signal、layered_l1l4等）和研究员（观澜）统一从此skill加载指标函数
- 消除循环依赖风险，单一数据源

## 2. L1-L4策略打分迁移（低优先级）

**当前状态**: `strategies/layered_l1l4.py` 留在 quant-daily 中，已取消信号注册，仅作为数据导出用途。

**目标**: 迁移到 `technical-analysis` skill。
- 物理移动到 `technical-analysis/scripts/strategies/layered_l1l4.py`
- 作为观澜的技术分析工具箱的一部分，不提供独立交易信号

## 3. factor_timing策略打分迁移（低优先级）

**当前状态**: `strategies/factor_timing.py` 留在 quant-daily 中，已取消信号注册。

**目标**: 迁移到 `fundamental-data-collector` skill。
- 物理移动到 `fundamental-data-collector/scripts/strategies/factor_timing.py`
- 作为探源的基本面分析工具箱的一部分
- 因子数据归基本面分析师管

## 4. 删除不必要的环节（2026-07-06 已完成）

- ✅ L1-L4独立策略注册 → 取消
- ✅ factor_timing独立策略注册 → 取消
- ✅ quant-daily中双通道辩论筛选(debate_brief) → 不再使用
- ✅ 固定多空辩手 → 改为动态正反方（根据signal_type）
- ✅ scan_all.py --dual 模式 → 三层信号 + 研究员原始数据输出
