# FDT 辩论报告排版规范（唯一合格模板）

> 创建时间：2026-07-22 | 最终确认：2026-07-22
> 来源：掌柜确认的 fdt-debate-pta-cf-l-2609.html 排版风格
> **⚠️ 本文件为 FDT 全量扫描/批量/单品种辩论报告唯一合格排版规范。其他任何报告排版模板均已作废。**

---

## 一、排版原则

FDT 辩论分析报告输出（HTML）遵循以下设计原则：

1. **深色页眉 + 白色内容区**的明暗对比
2. **粘性导航栏**便于长报告跳转
3. **阶段标签（Phase Badge）**：P1红色 / P1.5深蓝绿 / P2金黄 / P3墨绿 / P4红色 / P5金黄
4. **三列指标体系**：品种关键价格用三列并排展示，含涨跌色标（涨绿/跌红/平黄）
5. **info-grid 网格布局**：2-3列自适应网格展示技术/基本面维度
6. **六级辩论轮次（debate-round）**：白色卡片+圆角标题，按①~⑥逐轮排列
7. **判决框（Verdict Box）**：深色渐变背景+白色文字+评级标签+交易参数网格
8. **风控框（Risk Box）**：绿/黄/红三种左边框等级
9. **最终汇总表格**：品种、方向、置信度、入场、止损、目标、盈亏比、仓位、持仓周期

## 二、色彩系统

- bg: #f4f2ed（暖灰背景）
- bg2: #ffffff（纯白内容区）
- ink: #1a1a1e（深黑灰正文）
- muted: #6b6b72（中灰次要文字）
- rule: #d8d6d0（浅灰分割线）
- accent: #c44536（砖红强调色/空头色/做多标签）
- accent2: #2b6c7e（深蓝绿次要强调/多头色/做空标签）
- green: #2d7d4f（墨绿涨/通过）
- red: #c44536（砖红跌/警告）
- yellow: #c49a2b（金黄观望/关注）
- shadow: 0 1px 3px rgba(0,0,0,0.08)（卡片阴影）

## 三、排版组件

| 组件 | 用途 |
|:-----|:-----|
| report-header | 深色渐变 #1a1a2e→#2b6c7e + 白字 报告标题区 |
| nav-bar | 白底 sticky 粘性导航 章节跳转 |
| phase-badge | 彩色背景圆角标签 阶段标识 |
| metrics-summary | 三列 grid 卡片 品种价格速览 |
| metric-card | 单品种行情卡片（symbol/price/detail） |
| info-grid | auto-fit 自适应网格 技术/基本面维度展示 |
| info-card | 维度卡片（h4标题 + value + sub描述） |
| debate-round | 白色圆角卡片，含 round-title + content 辩论轮次 |
| verdict-box | 深色渐变 + 白字 + tag评级标签 + params交易参数网格 |
| risk-box | 左边框三色（绿/黄/红）风控审核结果 |
| callout | 左accent2边框渐变背景 核心矛盾小结 |
| sentiment-tag | 置信度标签（strong/weak/caution） |
| table-wrap | 水平+垂直滚动容器 最终汇总表格 |

## 四、完整章节顺序（全量扫描/批量报告）

每个品种在报告中按以下章节组织，品种间用 <hr> 分隔：

P1  — 数据总览（数技源扫描，三列metrics-summary + 核心矛盾callout）
P1.5 — 链证源产业链分析（三列info-grid）
P1.5 — 读心新闻情绪观测（每个品种4列info-grid + 综合评估callout）
P2   — 观澜技术面分析（每个品种4列info-grid）
P3   — 探源基本面分析（每个品种4列info-grid）
P3   — 多空头六阶段攻防辩论（debate-round × 6）:
        (1) 多头立论 bullish_v1
        (2) 空头立论 bearish_v1
        (3) 空头反驳 bearish_rebuttal
        (4) 多头反驳 bullish_rebuttal
        (5) 空头最终陈述 bear_final
        (6) 多头最终陈述 bull_final
P4   — 闫判官终裁（verdict-box，含方向/入场/止损/目标/盈亏比/持仓周期）
P5   — 风控明审核（risk-box，含红线列表+仓位建议）

最终汇总：明鉴秋汇总表格（table-wrap + callout总评优先级）

## 五、多空颜色规范

| 元素 | 多头 | 空头 | 观望 |
|:-----|:-----|:-----|:-----|
| 辩论标题色 | accent 砖红 | accent2 深蓝绿 | — |
| 辩论左边框 | accent 砖红 | accent2 深蓝绿 | — |
| 裁决标签 | tag.bull 砖红底 | tag.bear 深蓝绿底 | tag.neutral 金黄底 |
| 做多/做空文字 | green 墨绿 | accent2 深蓝绿 | yellow 金黄 |

## 六、响应式规则

- 768px 断点：所有 grid 降为单列
- 字体：Noto Sans SC，正文15px，移动端14px
- 表格：table-wrap 设置 overflow-x: auto + overflow-y: auto + max-height: 600px
- 导航栏：移动端横向滚动

## 七、字体与外部依赖

- 字体：Google Fonts Noto Sans SC（CDN加载，font-display: swap）
- 图表（可选）：ECharts SVG 渲染，颜色引用 CSS 变量
- 零其他外部依赖：无 CDN JS、无外部图片、纯 HTML+CSS

## 八、使用说明

本模板适用于 FDT 辩论专家团三种输出模式：
1. 全量扫描 — 62品种全覆盖，每品种按上述章节组织，品种间分隔
2. 批量指定 — 指定品种按上述完整辩论流程
3. 单品种 — 单品种深度分析

> **禁止使用任何其他报告排版格式。所有 FDT 辩论报告输出必须严格按照本规范执行。**
