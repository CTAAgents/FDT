# Golden Tasks — 经验库适配验证

## 用途

5 个已知品种的辩论案例，用于四步上线评估中 Shadow 模式和 Golden Tasks 阶段验证。

## 使用方法

### Shadow 模式验证
```bash
cd d:\Programs\FDT
python scripts/run_golden_tasks.py --mode shadow --tasks-dir benchmarks/golden_adaptation/
```

### Golden Tasks 对比
```bash
python scripts/run_golden_tasks.py --mode compare --tasks-dir benchmarks/golden_adaptation/
```

## 案例覆盖

| ID | 品种 | ADX 环境 | 波动率 | 数据新鲜度 | 验证重点 |
|:--|:--|:--|:--|:--|:--|
| GT-001 | RB2601 螺纹钢 | low | normal | fresh | 低趋势强度适配 |
| GT-002 | CU2601 沪铜 | medium | normal | fresh | 中等环境基准 |
| GT-003 | AU2612 沪金 | high | high | fresh | 强趋势保守适配 |
| GT-004 | SC2609 烧碱 | medium | normal | stale | 数据陈旧降级 |
| GT-005 | IF2609 股指 | medium | high | fresh | 高波动宽松适配 |
