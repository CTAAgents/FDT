# L0 人类设定 — 每周量化生产计划

> 最后更新: 2026-07-18 | 版本: 8.10.0
> 维护者: 人类

---

## 市场环境评估

```yaml
market_regime: 震荡偏多
# 可选: 趋势多头 / 趋势空头 / 震荡偏多 / 震荡偏空 / 高波 / 低波
```

## 因子偏好

```yaml
factor_preference:
  priority_1: 低波因子
  priority_2: 期限结构因子
  avoid: 趋势动量因子
 # 可选优先级: 动量/反转/波动率/持仓量/基差/期限结构/低波/宏观
```

## Agent LLM 配置

```yaml
agent_llm:
  default: deepseek-chat
  # 各 Agent 可独立配置:
  # bullish_analyst: claude-sonnet-4
  # bearish_analyst: claude-sonnet-4
  # judge: deepseek-chat
```

## Token 预算

```yaml
budget:
  daily_tokens: 50000        # L1 每日感知预算
  nightly_tokens: 200000     # L2 每夜演化预算
  weekly_portfolio: 100000   # L3 每周组合预算
  max_per_factor: 10000      # 单因子最大 token
```

## 风险约束

```yaml
risk_constraints:
  max_drawdown: 0.20
  max_turnover_per_month: 0.50
  min_sharpe: 1.5
  min_economic_logic_score: 3
```

## 熔断恢复确认

- [ ] L1 熔断已审查（原因: ________）
- [ ] L2 熔断已审查（原因: ________）
- [ ] L3 熔断已审查（原因: ________）
- [ ] program.md 已更新
- [ ] 确认恢复运行

---

*此文件由人类维护，每周更新一次。超过 14 天未更新时系统应发出告警。*
