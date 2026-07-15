# 2026-07-15 自动化执行摘要（10:47 二轮）

## 执行时间
2026-07-15 10:47 - 11:15 (28分钟)

## 扫描
- 模式: no-filter + 6策略管线 → 7策略（MultiFactor已合并）
- 触发品种（|total|≥20）: lu(+596), fu(+514), eg(+488), eb(+291), l(+270), pb(-220), PF(-66×2)
- STRONG级别: 5多1空

## 辩论
- **初判**: 6品种进辩论（lu/fu/eg/eb/l/pb），PF WATCH排除
- **终裁**: lu BULL(82%), fu BEAR(35%→与扫描方向相反!), eg BULL(72%), eb BULL(55%), l BULL(65%), pb BEAR(85%)
- 一致性得分: lu(72)/fu(78)/eg(20)/eb(90)/l(72)/pb(95)
- 风控: 全部通过，无否决

## 精选策略
- 🟢 #1 eg BUY 4615→4700 RR=2.07
- 🟢 #2 l BUY 7930→8149 RR=1.99

## 资源消耗
- 内存 84-86%（红色），强制降并发至2-3
- Agent 超时: 部分 Agent 因资源限制未产出，使用 Python fallback
- 总用时: ~28分钟（含 Agent 等待时间）

## 产出文件
- scan_daily_ranking_20260715.html
- debate_report_20260715.html
- debate_results.json + a2a_results.json + intermediate_data.json + repair_plan.json
