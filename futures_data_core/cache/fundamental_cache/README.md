# F10 静态基本面缓存

本目录存放**预采集的基本面快照**，作为 `get_fundamental(use_llm=False)` 的
第 1 层（静态缓存）数据源。

## 文件结构

- `supply.json` —— 供给（产量 / 开工率 等）
- `demand.json` —— 需求
- `inventory.json` —— 库存
- `margin.json` —— 利润 / 加工费

每个文件采用「按品种聚合」结构：

```json
{
  "CU": {"production": 95.2, "unit": "万吨", "cached_at": "2026-07-04"},
  "RB": {"production": 2600.0, "unit": "万吨", "cached_at": "2026-07-04"}
}
```

## 重要说明

- 这些数值为**参考级快照**，并非实时数据。真实生产环境应通过以下方式更新：
  1. 手动替换为最新行业数据；
  2. 在 `get_fundamental(use_llm=True)` 时叠加 LLM WebSearch 实时采集（需 LLM 环境）。
- 所有条目必须带 `cached_at` 字段，调用方可据此判断时效。
- 本目录数据缺失时，`get_fundamental` 会优雅降级到爬虫 / LLM 层或标记为
  `UNAVAILABLE`，不影响其他独立功能。

> 当前文件中的数值为占位示例，部署前应替换为权威来源数据。
