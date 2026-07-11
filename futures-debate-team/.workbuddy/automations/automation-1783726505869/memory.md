# FDT 品种知识库老化维护 · 执行记录

## 2026-07-11 (首次执行)
- 命令：`python scripts/extract_knowledge.py decay`（系统 Python 3.12.10）
- 扫描 8 品种 (au/i/jd/rb/rm/sc/ta/zn)，共 8 条 active 模式
- 结果：decayed=0, deprecated=0，active 8→8，未触发任何文件写入
- 原因：全部模式 last_used 均为当日(0天)，远低于 60 天阈值；无 consecutive_failures 记录(默认0)
- 生产前已全量备份至 `C:/Users/yangd/AppData/Local/Temp/fdt_knowledge_backup_20260711_215648/`
- 报告输出：`reports/knowledge_decay_2026-07-11.md`
- 观察：consecutive_failures 字段当前未被写入，规则B(连续3次失败弃用)实际不会触发，已记入报告建议项
