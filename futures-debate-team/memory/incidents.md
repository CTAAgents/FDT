# 事故与操作日志

> 专家团自有的事件记录系统。记录每次事故、教训、重要操作。
> 格式：日期 → 事件 → 根因 → 改正 → 预防

---

## 2026-07-06 | 专家团独立化中期战略确立

### 决定
专家团未来发展方向：**从平台寄生 → 独立多Agent系统**
所有优化任务、功能调整、自进化迭代，均围绕此方向进行。

### 四阶段路线
- **Phase 1 — 行为独立**（1~2周）：内建调度器，删除平台automation，自主决策"什么时候做什么"
- **Phase 2 — 运行时独立**（1个月）：自启动进程(`bootstrap.py`)，自身Agent通信协议
- **Phase 3 — 数据独立**（1~2个月）：内建全量数据管道，不依赖平台skill
- **Phase 4 — 部署独立**（3个月）：微服务+docker+API

### 已完成的独立化工作（2026-07-06）
| 领域 | 状态 |
|:-----|:----:|
| 记忆系统独立（自有memory/目录，平台目录已删除） | ✅ |
| 反馈闭环自触发（validate→calibrate→evolve→ML自循环） | ✅ |
| ML训练检查内建（删除平台cron `automation-1783298232958`） | ✅ |
| 用户反馈主动归档（自动注入Agent MD，无需平台） | ✅ |
| ATR计算修复（SignalResult自有字段，不依赖平台计算） | ✅ |

### 详细路线图
见 `docs/independence_roadmap.md`

### 事件
用户指出专家团的validate→calibrate→evolve反馈管道是纯手动的，只在模式一里存在，从未触发过。要求升级为内建自循环系统。

### 根因
- P0（验证→校准→进化）只绑定在模式一的SOP里，模式二/三不含
- 没有任何自动触发条件，execution_followup.json仅1条未验证记录
- agent_profiles.json全部是出厂默认值（total_samples=0, _evolution_log=[])

### 改正
- "自进化前置"从模式一专属提升为**所有模式强制全局步骤**
- 三种模式入口前统一插入触发逻辑：检测未验证→validate→达标后calibrate+evolve→加载参数
- 禁止行为表新增"跳过自进化前置步骤"
- 语义：从"P0步骤"变为"系统心跳"——不需要用户命令，每次分析请求自动执行

### 自循环路径
```
本轮辩论 → record_verdicts.py
     ↓
下次请求 → 检测未验证裁决 → validate_verdicts.py
     ↓
验证≥5条 → calibrate_weights.py → evolve_agents.py
     ↓
参数注入Agent MD"自进化参数"段 → 下次spawn自动生效
```

---

## 2026-07-06 | LH单品种辩论数据质量事故（P0）

### 事件摘要
用户（掌柜）执行生猪(LH)单品种辩论分析，报告产生后逐一指出4处数据引用错误。

### 具体错误
1. LH2607数据：引用7月1日"-2.62%暴跌" → 实际7月6日+5.96%大涨（数据过期5天，方向完全相反）
2. Q1屠宰量：+18.1%被当"供应过剩"利空 → 实际高屠宰=去库存=远期利多（因果倒置）
3. 远月Contango 35%：系统已标记为异常并过滤 → 仍被用作论据
4. 数据源：5个网页来源均未在报告中标注出处

### 根因分析
1. **确认偏误**：辩论预设空方胜 → 选择性引用支持空头的证据 → 忽略矛盾数据
2. **数据时效缺失**：WebSearch结果未检查日期，5天前的文章当"当前"
3. **逻辑审查缺位**：论据未经因果方向测试
4. **异常值盲信**：绕过系统过滤标记直接使用

### 改正措施
- 提炼R06-R10五条新规则，写入 `judgment_revisions.md` v2.0
- 注入闫判官/证真/慎思/探源/观澜/明鉴秋共6个Agent的MD定义文件
- 建立用户反馈自动归档机制（明鉴秋MD新增P0铁律段）
- 建立记忆写入路由规则（三层：角色MD → 规则文件 → 用户MEMORY）
- 确立路径边界：专家团记忆只写自身`memory/`目录，不依赖任何平台

### 预防
- 所有Agent下次spawn时自动加载R06-R10约束
- 闫判官v2.0核验流程新增"反向证据检索"步骤
- 辩手每个论据必须通过"因果方向测试"才能提交
- 明鉴秋检测到用户反馈信号 → 先归档到专家团memory → 再回复

### 关联文件
- `memory/judgment_revisions.md` — R06-R10完整定义
- `agents/futures-judge.md` — v1.0→v2.0
- `agents/futures-affirmative-debater.md` — 新增"论据质量铁律"
- `agents/futures-opposition-debater.md` — 新增"论据质量铁律"
- `agents/futures-fundamental-researcher.md` — 新增"数据质量铁律"
- `agents/futures-technical-researcher.md` — 新增"数据质量铁律"
- `agents/futures-debate-team-team-lead.md` — 新增"反馈自动归档"+"记忆路由"

---

## 2026-07-06 | ATR计算Bug修复

### 事件
用户发现scan输出ATR=10，通达信/文华显示~230，偏差23倍。

### 根因
1. `SignalResult`类无atr字段 → TDX算出的ATR在策略层丢失
2. `debate_brief.py` fallback: `max(abs(total)*0.15, 10)` — 信号总分当ATR算
3. `_extract_l1l4` 摘要函数不输出atr

### 修复
- `base.py`: SignalResult新增`atr`字段 + to_dict()输出
- `layered_l1l4.py`/`factor_timing.py`: 从tech/entry传ATR到SignalResult
- `debate_brief.py`: fallback改为`price*0.02` / `_extract_l1l4`新增atr

### 验证
LH扫描 atr=239.3（vs通达信~230，偏差<4%）✅
