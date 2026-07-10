# 事故与操作日志

> 专家团自有的事件记录系统。记录每次事故、教训、重要操作。
> 格式：日期 → 事件 → 根因 → 改正 → 预防

---

## 2026-07-10 20:10 | Agent SendMessage在自动化中路由失效（第2次）

### 事件
日线盘后自动化(20:10)中，spawn了3个研究员Agent(链证源/观澜/探源)，全部成功启动但SendMessage产出均未送达。明鉴秋降级为WebSearch→直接执行→完成辩论。

上午(16:25)同问题导致5次spawn失败。

### 根因（2026-07-10 20:56 掌柜要求一次性修好→诊断确认）
**自动化context中，main agent处于单次执行模式，没有持续的消息监听循环。**
流程: Agent完成分析→调用SendMessage(recipient="main")→消息入队→main不在监听状态→消息永不送达→Agent静默结束。

这不是Agent能力问题（Agent都能WebSearch+Write），是平台自动化环境的消息路由架构限制。

### 改正（v3.7.1 永久修复）

**A01铁律：文件优先通信协议**
- Agent产出**只写文件，不使用SendMessage**
- 明鉴秋只用 `poll_file_ready()` 轮询文件就绪后读取
- 所有spawn prompt末尾加：「完成後用Write直接寫入文件，不使用SendMessage」

**tiered降级机制**
| 阶段 | 超时 | 降级动作 |
|:-----|:----|:--------|
| P1.5 链证源 | 600s | 明鉴秋WebSearch自行完成 |
| P3 观澜/探源 | 600s | 明鉴秋WebSearch自行完成 |
| P4 证真/慎思 | 600s | 明鉴秋基于数据构建论据 |
| P5 闫判官 | 300s | D06降级→独立裁决 |
| P5 策执远 | 300s | ATR公式计算 |
| P5 风控明 | 300s | 基于规则审核 |

**修改文件**：
1. `skills/fdt-spawn-debate/SKILL.md`: 新增规则10(A01)+自动化环境特殊处理+Spawn prompt全量更新
2. `skills/futures-trading-analysis/SKILL.md`: v3.7.0→v3.7.1 changelog

### 预防
下次自动化执行时，Agent产出路径=文件轮询而非消息监听。如果Agent不写文件→超时→明鉴秋降级直行。不会再有"等待Agent消息→永远等不到"的死锁。

---

## 2026-07-10 10:30 | 辩论Agent超时+胶水代码+记忆越界

### 事件
120m辩论中，证真/慎思/闫判官三个后台Agent超时无产出，明鉴秋自行撰写辩论论据+裁决结论，并写了`build_debate_report.py`胶水脚本生成报告。

### 根因
1. **Agent通信失败**: 使用`run_in_background=true` spawn后依赖SendMessage回传，但Agent长时间无响应。未按S04轮询文件就绪。
2. **胶水代码**: `build_debate_report.py`为一次性报告生成脚本，违反零胶水代码铁律。正确做法应使用`phase3_generate_report.py`。
3. **记忆越界**: 辩论执行记录写入了工作空间`.workbuddy/memory/`而非FDT自有`memory/`目录，违反专家团记忆独立铁律。

### 改正
- 删除`build_debate_report.py`胶水脚本
- 辩论记录归档到FDT `memory/debate_journal.json`
- 事故记录写入本文件
- D06降级规则触发: 三个Agent无产出→明鉴秋基于研究员产出完成裁决(合规)

### 预防
- P4辩论Agent spawn必须使用S04轮询等待（poll_file_ready），不能依赖background+SendMessage
- 辩论Agent产出文件路径需在spawn prompt中明确指定
- 明鉴秋汇总时必须检查是否有agent产出文件(`p4_zhengzhen.json`/`p4_zhensi.json`/`p5_judge.json`)，缺失则标注降级

---

## 2026-07-10 | 子周期K线会话划分规范确立 + TDX对齐修正 + 降级链净化

### 事件链
1. **DC20 REF式偏差**: SP从4690跳空至4798, DC20U因包含当前bar膨胀至4816, 判定none→WEAK
2. **掌柜提供TDX唐奇安通道公式**: 发现REF(HHV,1)+HIGH/LOW检测+初次突破标记三处差异
3. **子周期会话划分**: 掌柜提供交易所K线周期规范, 确认TDX/AKShare/东方财富为会话感知, TqSDK为纯时钟

### 根因分析
- DC20通道计算含当前bar → 价格涨通道跟着涨, "突破"越来越难
- dc20_break使用CLOSE而非HIGH/LOW → 盘中突破被无视
- TqSDK对子周期使用7200秒固定窗口 → 跨夜盘收盘/午休边界
- resample_60m_to_120m简单两两合并 → 跨会话幽灵bar

### 改正措施
| # | 改正 | 文件 |
|---|------|------|
| 1 | DC20 REF式通道: max(highs[-21:-1]) + high/low检测 | `120m_resampler.py`, `analyze_targets.py`, `channel_breakout_strategy.py` |
| 2 | 动量逼近识别: bar振幅≥1.2×ATR → near_breakout分 | `channel_breakout_strategy.py` |
| 3 | 会话感知resample: gap>120min=新会话 | `120m_resampler.py`, `optimizer/run_120m_wf.py` |
| 4 | TqSDK子周期排除(R25) | `multi_source_adapter.py` |
| 5 | FDT记忆固化: session_rules.md, data_sources.md R25 | `memory/session_rules.md`, `memory/data_sources.md` |

### SP评分轨迹
原始 +28 WEAK → +动量识别 +43 WATCH → +TDX对齐 **+63 STRONG**

### 影响范围
- 新增STRONG信号: SP(+63), RM(+61), SN(+56)
- FG WATCH不变(-43)
- 无品种退化
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

---

## 2026-07-08 | SC 60m 小时线分析3重数据管道Bug（P0）

### 事件摘要
用户对原油SC做60m小时周期分析，系统连续出现3个数据层错误：
1. TDX 60m K线数据过期（停在2025-12-29，距今191天）→ 指标基于半年前数据
2. 无数据源可提供新鲜60m数据 → TqSDK挂起、东财不通
3. `_compute_indicators_numpy` 的TDX桥接无视period→用日线指标覆盖60m正确值

### 三连bug链路

```
用户请求: scan_all.py --symbols sc --period 60m
    ↓
Bug① multi_source_adapter.get_kline(period='60m')
   → TDX返回170条60m(2025-12-29) → 无新鲜度检查 → 标记confidence=1.0
   → 下游获取半年前数据 → 指标全部过期
    ↓
Bug② TDX数据被Bug①用掉 → 降级链不触发
   修正后TDX生效 → 但TqSDK挂起、东财RemoteDisconnected
   → 无数据源能提供当前60m数据
    ↓
Bug③ 终于拿到60m数据(AKShare分钟,1022根)
   → numpy计算出正确60m指标(RSI=71.1, ATR=3.4)
   → 但bridge.patch_indicators(tech, symbol) → TDX日线指标覆盖
   → scan输出ADX=81.7(日线), RSI=28.8(日线), ATR=17.0(日线)
   → 用户指出的"小时线指标用了日线值"被证实
```

### 根因

| Bug | 根因 | 何时引入 |
|:----|:-----|:---------|
| ① 新鲜度缺失 | `multi_source_adapter.py` TDX返回路径只检查`len≥20`，不检查最后K线日期 | v1.0 |
| ② 无子周期降级 | AKShare `futures_zh_daily_sina` 无视period返回日线；E联不通；TqSDK挂起 | v2.5.0 |
| ③ 桥接覆盖 | `indicators_legacy.py` 第848行TDX bridge硬编码无条件覆盖；`_compute_indicators_numpy` 不知period | v1.0 |

### 修复 (quant-daily v2.9.1)

| 文件 | 修复 |
|:----|:-----|
| `multi_source_adapter.py` | ② `get_kline`新增AKShare分钟降级(`futures_zh_minute_sina`, period=60/120/240) + 时间过滤(排除未来数据) |
| `multi_source_adapter.py` | ① TDX返回后加新鲜度检查: 子周期>7天→跳过→降级链 |
| `scan_all.py` | ② 非TTY/`TQ_SKIP_DISCLAIMER`→跳过TqSDK |
| `scan_all.py` + `indicators_legacy.py` | ③ 传period参数; `period!="daily"`时跳过桥接与日线覆盖 |

### 验证
```
修正前: ADX=81.7(日线), RSI=28.8(日线), ATR=17.0(日线)
修正后: ADX=23.8(60m), RSI=71.1(60m), ATR=3.4(60m) ✅ 方向多头, 贴合用户看盘值
```

### 预防
- 子周期扫描必须经过新鲜度检查 → 已加固
- 数据源需配齐子周期降级链(TDX→TqSDK→东财→AKShare分钟→AKShare日线) → 已补AKShare分钟
- 任何 `_compute_indicators_numpy` 必须知period，不得无条件调TDX桥接 → 已加period参数

### 关联文件
- `skills/quant-daily/SKILL.md` — v2.9.1 版本记录
- `skills/quant-daily/scripts/data/multi_source_adapter.py` — 新鲜度检查 + AKShare分钟降级
- `skills/quant-daily/scripts/scan_all.py` — TqSDK跳过 + period参数传透
- `skills/quant-daily/scripts/indicators/indicators_legacy.py` — period感知的桥接跳过

---

## 2026-07-09 | 闫判官spawn Write工具不可用Bug（P0）

### 事件摘要
BU+EC完整辩论中，闫判官连续spawn 5次均无法写入p5_judge.json：
- v1(subagent_type: futures-judge): 55s后卡死，未写文件
- v2(subagent_type: futures-judge精简): 27s后卡死
- v3(subagent_type: futures-judge独立阅卷): 45s后卡死
- v4(subagent_type: futures-judge数据全覆盖): 27s后卡死
- v5(subagent_type: general-purpose长prompt): 被手动停止

### 诊断
- ✅ general-purpose + 最小prompt测试: Write工具正常工作 → 写入p5_judge_test.json成功
- ❌ subagent_type: futures-judge: 连续4次全部失败

### 根因
`subagent_type: "futures-judge"` 作为expert agent spawn时，MD frontmatter中声明的`allowed-tools`可能未被平台正确加载，导致Write工具不可用。与"expert-manager铁律"吻合：自定义专家spawn时Tools为空。

### 修复（P0·立即生效）
1. **闫判官Agent MD** (`agents/futures-judge.md`): 新增"Spawn方式"段，标注必须用general-purpose
2. **团队主管MD** (`agents/futures-debate-team-team-lead.md`): 更新D01-D04辩论铁律，所有辩论Agent统一用general-purpose spawn
3. **辩论流程铁律D05新增**: "辩论Agent必须spawn为general-purpose，不得使用expert subagent_type。角色prompt注入替代expert自动加载。"

### 预防
- 所有辩论团队Agent(观澜/探源/证真/慎思/闫判官/策执远/风控明)统一使用`subagent_type: "general-purpose"` spawn
- 不再依赖expert subagent_type的工具加载机制
