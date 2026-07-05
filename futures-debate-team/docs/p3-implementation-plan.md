# P3 技术债务实施计划

## 总览

| Phase | 项目 | 预估工时 | 前置依赖 | 状态 |
|:------|:-----|:--------|:---------|:-----|
| **Phase 1** | 事件日历mask + 跨品种联动 | 2h | 无 | ✅ 完成 (event_calendar.py + cross_correlation.py) |
| **Phase 2** | ML模型数据管道 | 4h | Phase 1 | ✅ 完成 (feature_pipeline/feature_engineering.py, 30+维度) |
| **Phase 3** | ML模型训练+验证 | 8h | Phase 2 | ✅ 完成 (ml_models/direction_classifier.py: DirectionClassifier+EnsemblePredictor) |
| **Phase 4** | PnL反馈闭环 | 4h | Phase 3 | ✅ 完成 (feedback/trade_journal.py: record_trade+close_trade+反向标注+replay buffer) |

## Phase 1: 事件日历 + 跨品种联动（即时可建）

### 1.1 事件日历mask - `event_calendar.py`
- 维护已知宏观事件数据库（FOMC/非农/USDA/EIA/CPI/PBOC）
- 函数 `check_event_impact(today, symbol)` → 返回是否在事件日、事件类型、置信度折扣
- 集成到 `special_scenario_override()`

### 1.2 跨品种联动 - `cross_correlation.py`
- 维护品种联动关系表（黑色/有色/化工/农产品各板块内联动）
- 函数 `calc_correlation(symbol1, symbol2, prices1, prices2, window=20)` → 滚动相关系数
- 函数 `get_correlation_peers(symbol)` → 返回关联品种列表及相关系数
- 输出可作为技术Agent的额外输入特征

## Phase 2: ML模型数据管道

### 2.1 特征工程 - `feature_pipeline.py`
- 从quant-daily采集历史K线+OI+成交量+技术指标
- 构建特征集：OI变化率、OI-价背离、展期结构斜率、ATR百分位、跨品种相关系数
- 标签：未来N根K线方向（涨/跌/平）

### 2.2 数据仓库 - `data/feature_store/`
- 按品种分文件存储特征向量
- 每日增量更新（通过quant-daily定时任务）

## Phase 3: ML模型训练

### 3.1 基线模型 - `ml_models/direction_classifier.py`
- LightGBM 二分类（方向概率）
- 滚动窗口6-12个月训练
- 输出 `(方向, 概率, 置信度)` 三元组
- 集成 SHAP 解释性输出

### 3.2 集成到技术Agent
- 技术Agent同时运行规则层 + ML层
- 两层加权输出 `(规则概率 × w1 + ML概率 × w2)`
- 权重根据近期准确率在线调整

## Phase 4: PnL反馈闭环

### 4.1 数据库改造 - `data/trade_journal/`
- Trader下单后记录：入场价/止损价/出场价/PnL
- 关联到技术Agent当时的预测

### 4.2 反向标注 - `feedback/annotate.py`
- 辩论结果 → PnL结算 → 反向标注技术Agent的(方向,概率,置信度)是否正确
- 错例进入 replay buffer
- 定期 finetune

### 4.3 回放训练 - `feedback/replay.py`
- 从 replay buffer 采样错例
- 混合训练（原数据 + 错例 7:3）
