# 期货交易分析技能打包完成

## 技能概述

已成功将期货辩论Agent团队打包成独立技能 `futures-trading-analysis`，可在其他工作中复用。

## 技能信息

| 项目 | 内容 |
|------|------|
| **技能名称** | `futures-trading-analysis` |
| **技能路径** | `~/.workbuddy/skills/futures-trading-analysis/` |
| **版本** | v1.0.0 |
| **Agent数量** | 12个 |
| **分析模式** | 单品模式、产业链模式 |
| **工作流** | 5阶段（数据收集→多空辩论→交易决策→风险评估→最终报告） |

## 技能结构

```
futures-trading-analysis/
├── SKILL.md                    # 主技能文档（协调器指令）
├── README.md                   # 技能使用说明
└── agents/                     # 12个期货版Agent
    ├── futures-market-analyst.md
    ├── futures-fundamentals-analyst.md
    ├── futures-news-analyst.md
    ├── futures-sentiment-analyst.md
    ├── futures-bull-researcher.md
    ├── futures-bear-researcher.md
    ├── futures-research-manager.md
    ├── futures-trader.md
    ├── futures-aggressive-risk-analyst.md
    ├── futures-conservative-risk-analyst.md
    ├── futures-neutral-risk-analyst.md
    └── futures-risk-manager.md
```

## 核心功能

### 1. 两种分析模式
- **单品模式**：分析单个期货品种（如螺纹钢RB、豆粕M、原油SC）
- **产业链模式**：分析一组相关品种（如黑色系：RB/I/J/JM，能源链：SC/FU/LU/BU/PG）

### 2. 12个专业Agent

**Phase 1 - 数据收集（4个分析师）**
1. **futures-market-analyst**：期货技术分析，持仓量、期限结构、基差、虚实比
2. **futures-fundamentals-analyst**：期货基本面，供需平衡表、库存周期、产能利用率
3. **futures-news-analyst**：期货新闻，天气/地缘事件、行业政策、产业链动态
4. **futures-sentiment-analyst**：期货情绪，CFTC持仓、仓单变化、虚实比

**Phase 2 - 投资辩论（3个辩论角色）**
5. **futures-bull-researcher**：期货多头研究员，攻击维度：供应收紧、需求复苏、库存利多
6. **futures-bear-researcher**：期货空头研究员，攻击维度：供应宽松、需求走弱、库存利空
7. **futures-research-manager**：期货研究主管，裁决维度：供需平衡表、库存周期、期限结构

**Phase 3 - 交易决策（1个交易员）**
8. **futures-trader**：期货交易员，新增：合约选择、移仓换月、保证金管理、虚实比检查

**Phase 4 - 风险评估（4个风险角色）**
9. **futures-aggressive-risk-analyst**：激进风险，趋势延续论据、错失成本量化
10. **futures-conservative-risk-analyst**：保守风险，期货特有尾部风险（逼仓、政策突变）
11. **futures-neutral-risk-analyst**：中性风险，跨期套利、产业链对冲等温和策略
12. **futures-risk-manager**：风险主管，期货特有风险调整

### 3. 5阶段工作流

```
Phase 1: 数据收集【并行】
  futures-market-analyst + futures-fundamentals-analyst + futures-news-analyst + futures-sentiment-analyst
      ↓
Phase 2: 投资辩论【顺序】
  futures-bull-researcher → futures-bear-researcher → futures-research-manager
      ↓
Phase 3: 交易决策
  futures-trader → FINAL TRANSACTION PROPOSAL
      ↓
Phase 4: 风险评估【并行+顺序】
  futures-aggressive-risk-analyst + futures-conservative-risk-analyst + futures-neutral-risk-analyst → futures-risk-manager
      ↓
Phase 5: 最终报告
  整合所有阶段产出，生成结构化商品期货分析报告
```

## 使用方法

### 触发词
- 期货分析、商品分析、期货交易
- 多空辩论、风险评估、产业链分析
- 期货投资、期货买卖、期货决策
- futures analysis、commodity trading

### 示例请求
```
帮我分析螺纹钢RB的走势
黑色系整体分析
原油SC该不该做多
豆粕M的多空辩论
```

### 执行模式
- **完整模式**（默认）：执行全部5个阶段
- **快速模式**：用户说"快速分析"/"简要分析"时，仅执行Phase 1 → Phase 3 → Phase 5
- **辩论模式**：用户已提供数据，跳过Phase 1，仅执行Phase 2-5

## 数据源

所有金融数据通过 `neodata-financial-search` skill 获取：
- 禁止使用Yahoo Finance、Alpha Vantage、Tushare、Bloomberg等其他数据源
- 所有Agent均使用此数据源

## 输出格式

最终报告包含：
1. **最终建议**：BUY/SELL/HOLD决策、信心水平、风险等级、仓位建议
2. **供需平衡判断**：供应端、需求端、库存周期、期限结构
3. **产业链判断**（产业链模式）：整体趋势、品种位置、共振信号、利润分配
4. **四维分析摘要**：技术面、基本面、新闻面、情绪面
5. **投资辩论结论**：多头/空头核心论点、研究主管裁决
6. **风险评估结论**：三方风险观点、风险主管裁决
7. **操作建议**：入场价、目标价、止损价、仓位、合约选择、移仓策略
8. **关键风险提示**：市场风险、品种风险、宏观风险、期货特有风险

## 与原技能的关系

- 原 `trading-analysis` 技能（股票版）保持不动
- 新技能 `futures-trading-analysis` 独立运行
- 两个技能可以并存，互不干扰

## 使用场景

1. **商品期货单品深度分析**：对单个期货品种进行全面分析
2. **产业链综合分析**：分析一组相关品种的产业链关系
3. **期货交易决策支持**：提供买卖决策和操作建议
4. **期货风险评估**：评估期货交易的风险因素

## 后续优化方向

1. 添加更多产业链分类
2. 集成futures-industry-chain-analysis技能的数据
3. 支持自动化定时分析
4. 添加回测验证模块
5. 优化Agent提示词以提高分析质量

## 验证状态

✅ 技能结构完整
✅ 12个Agent文件就位
✅ SKILL.md文档完整
✅ README.md使用说明完整
✅ 可在其他工作中复用

---

**打包时间**: 2026-06-24 05:45 AM
**技能版本**: v1.0.0
**状态**: 可用
