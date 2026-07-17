# 事故与操作日志

> 专家团自有的事件记录系统。记录每次事故、教训、重要操作。
> 格式：日期 → 事件 → 根因 → 改正 → 预防

## 2026-07-11 | ADX角色反转规则未注入spawn prompt → JD辩论ADX主导裁决

**事件**: 周六盘后自动化扫描，JD鸡蛋WATCH(+41)触发完整辩论。闫判官裁决以ADX=17.1为"致命伤"判HOLD，监控条件第一条为"ADX>20"，风控明风险表第一项为"ADX趋势强度高"。三个Agent均以ADX为首要判断依据。

**根因**: judgment_revisions.md已有R11-R18关于ADX角色反转的规则（2026-07-06确立），但fdt-spawn-debate/SKILL.md的spawn prompt模板中没有引用这些规则。Agent通过general-purpose spawn时拿到的只是裸数据（ADX=17.1），自然按传统解读处理。

**改正**:
1. fdt-spawn-debate/SKILL.md: 核心规则表新增#11 ADX角色反转铁律
2. fdt-spawn-debate/SKILL.md: 闫判官spawn模板新增ADX角色反转规则段
3. fdt-spawn-debate/SKILL.md: spawn模板新增监控条件编写规则
4. futures-judge.md: 新增"ADX角色反转铁律"段（P0不可违反）
5. futures-trading-strategist.md: Constraints新增ADX监控约束
6. futures-debate-team-team-lead.md: 新增"ADX角色反转·spawn注入铁律"

**预防**: 每次spawn前，明鉴秋自检prompt是否包含"ADX角色反转"关键词。不包含→拒绝spawn，先修复。
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
| P5 策略方案 | 300s | ATR公式计算 |
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
- `layered_l1l4.py`: 从tech/entry传ATR到SignalResult
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
- 所有辩论团队Agent(观澜/探源/证真/慎思/闫判官/风控明)统一使用`subagent_type: "general-purpose"` spawn
- 不再依赖expert subagent_type的工具加载机制

---

## 2026-07-11 | P6后处理三类布线缺失（知识库回填 / P6报告 / JSON裸引号）

### 事件摘要
2026-07-11 日线盘后扫盘，JD鸡蛋WATCH信号触发完整辩论（v1 08:00 + v2 08:12-08:19两场）。
辩论Agent产物（证真/慎思/闫判官/风控明）全部齐全，但跑完即present JSON结束，缺失三件事：
1. 知识库未更新：knowledge/JD/drivers.md 仍显示"暂无辩论记录"，两场辩论对品种知识库完全不可见
2. P6最终报告缺失：v2辩论未生成HTML辩论报告，只present了JSON（后于08:23人工补齐）
3. JSON数据质量bug：p5_judge_JD_v2.json 的reasoning字段含未转义裸引号 "全市场共振"，致JSON解析失败

### 根因
1. 知识库：extract_knowledge.py有extract_from_debate()方法但无ingest CLI入口；fdt-spawn-debate SKILL Step 8只提phase3_generate_report.py（全量脚本），未钉死单品种报告生成+知识萃取；自动化prompt步骤3仅"FDT记忆→FDT内部"模糊描述，未要求P6汇总/萃取
2. P6报告：phase3_generate_report.py为全量62品种设计，强依赖intermediate_data.json+62/62覆盖铁律，单品种直接套卡在全量依赖；无现成单品种报告生成器被流程强制调用
3. JSON裸引号：spawn prompt要求禁用引号但Agent仍写入英文双引号作中文引号用，无JSON产出校验

### 修复（已执行）
1. extract_knowledge.py：新增 ingest CLI（消费p4证真/p4慎思/p5裁决/p5方案→调extract_from_debate回填知识库）；新增 _normalize_confidence() 兼容字符串型置信度（低0.4/中0.6/高0.8）；回填JD v2辩论→knowledge/JD/ patterns+1 / drivers已更新
2. fdt-spawn-debate SKILL Step 8 强化：P6报告生成（全量调phase3 / 单品种直接Write HTML）+ 知识萃取强制门禁（缺萃取→P6不完成）
3. 自动化prompt步骤3 拆为 3.1汇总 / 3.2报告 / 3.3萃取 / 3.4日志（写死，下次自动执行）
4. p5_judge_JD_v2.json 裸引号 "全市场共振" → 「全市场共振」修复并验证合法

### 预防
- P6强制门禁：知识萃取步骤不可跳过，否则P6不视为完成
- 单品种辩论报告走直接Write HTML（不套全量phase3）
- Agent JSON产出后增加裸引号校验（未来在L1产出校验层加JSON.parse检查）

---

## 2026-07-11（续）| L1产出校验落地 + 知识库质量门控修复

### 问题
前一轮(08:30)诊断出6类问题并修复，但R29(知识萃取JSON校验)仅在事故记录中提及、**未真正落地**。本轮(08:33用户问潜在问题)深挖发现：

1. **L1校验脚本缺失**：`scripts/validate_agent_output.py` 文件根本不存在。系统prompt声称的L1产出校验(JSON schema+禁止模式)是空壳。JD裁决文件裸引号致JSON损坏全程无任何自动检查拦得住——这是必再犯的活断点。
2. **自动化 `--bypass` 废掉质量门控**：自动化prompt写死 `ingest --bypass`，所有辩论(含低置信度噪声)无条件灌入知识库，稀释品种经验质量。

### 修复（已执行）
1. **创建 `validate_agent_output.py`**（真实L1校验器）：
   - json.loads捕获JSONDecodeError，定位错误行列+上下文（专门catch裸引号类损坏）
   - 按phase(P4/P5_JUDGE/P5_PLAN/P5_RISK)校验必需字段 + key_arguments子结构
   - 退出码0=通过 / 1=失败（调用方触发重spawn）
   - 测试：修复后JD裁决→valid=true exit0；裸引号损坏版→valid=false exit1 且定位L10:21
2. **SKILL Step规则12 + 轮询就绪后L1代码块**：每个Agent写文件→poll_file_ready→validate；失败立即重spawn(最多2次)，未校验不得进下一阶段
3. **自动化prompt重写**：步骤3.3移除`--bypass`（让置信度门控生效：低<0.6自然跳过）；新增步骤3.4 L1产出校验强制步

### 验证
- 无bypass时门控：`中`(0.6)/`高`(0.8)/0.7 通过，`低`(0.4) 跳过 → 知识库只积累中高置信度辩论
- JD(中)仍会被摄取，低质噪声被过滤

---

## 2026-07-11（续）| 四设计债修复（#3-#6）

### 根因（用户"全修"指令触发）
上一轮已修复6类问题(L1空壳/--bypass废门控等)，但仍有4项设计债未闭环：
1. **#3 spawn无重试**：402 Insufficient Balance 等瞬时 spawn 错误无自动重试，依赖产物恰好落盘侥幸过关
2. **#4 双入口并存**：futures-trading-analysis SKILL 内含 SendMessage主通道/debate_team.run/Handoff/repair_phase/PhaseGuard 等废弃执行代码，与 fdt-spawn-debate(A01文件通信)冲突，下一轮自动化可能误执行旧模式
3. **#5 confidence类型隐患**：闫判官输出 "高/中/低" 字符串，与系统契约(0-1数值)不一致；validate_agent_output 仅检key存在不检类型
4. **#6 周末跑**：自动化 DAILY 触发，周六期货休市仍扫描+辩论，产出为过期周五数据

### 修复（已执行）
1. **#3**：fdt-spawn-debate 新增规则13 + `spawn_with_retry()` 重试协议（瞬时错误重试2次→降级）
2. **#4**：futures-trading-analysis 顶部插入"执行协议单一来源声明"横幅，列出废弃模式对照表，指明以 fdt-spawn-debate 为唯一权威
3. **#5**：新建 confidence_utils.py（高0.8/中0.6/低0.4/数值直通）；validate_agent_output.py 增 confidence 类型校验+归一回传；闫判官模板改数值0-1+confidence_label；策略Agent按数值映射仓位；extract_knowledge.py 改为 import 别名（调用点不变）
4. **#6**：自动化prompt增步骤0交易日检查（weekday<5才继续，否则跳过）

### 验证
- validate_agent_output 三分支：中→0.6通过 / 0.72→0.72通过 / xyz→exit1拒绝 ✅
- confidence_utils 单测：中→0.6, 0.72→0.72, label(0.72)→高, is_valid(xyz)→False ✅
- extract_knowledge.py / validate_agent_output.py py_compile 通过 ✅

---

## 2026-07-11 20:47 | 周六扫描挂死（✅已修复 v5.12.1·AKShare降级调用无超时）

### 现象
自动化20:47触发scan_monitored.py(34日线监测品种)，进程存活但~50分钟零产出，无落盘。Kill -9 PID1766后恢复。

### 根因（代码核实·已更正）
**不是TDX无超时**（两路TDX均有超时：tdx_bridge urlopen(timeout=15)、tdx_collector urlopen(timeout=10)）。
真正漏洞在**降级链末端的AKShare**：`multi_source_adapter.get_kline` 的 daily 路径在 TDX 离线时降级到 AKShare（`ak.futures_zh_daily_sina` / `ak.futures_main_sina` 等），这些调用**既无 requests timeout，也未被 ThreadPoolExecutor 超时包裹**（而 TqSDK 有 `timeout=10` 包裹、东方财富有 `urlopen(timeout=15)`）。
机制：18:24 轮 TDX 在线→`get_kline` 直接走 TDX 路径返回，**根本不触达 AKShare**→成功；20:47 轮 TDX 离线→降级链触达 AKShare→Sina 端点在收盘后慢/不可达→`ak.*` 无限阻塞→34品种逐个卡死。
属"TDX可用性间歇 + AKShare降级路径无超时守护"双重因素。

### 影响
**每日风险**：盘后自动化每天20:15运行（工作日无周末门控保护），若彼时 TDX 本地客户端未运行（收盘后常关），必触发降级链→AKShare无超时→整轮无限挂起、无产出、进程空占直到手动 kill -9。周末手动重跑同理。

### 修复（2026-07-11 22:07 已实施·掌柜授权"改"）
- **根因修复（v5.12.1, plugins/marketplaces/.../data/multi_source_adapter.py）**：新增 `_safe_akshare(fn, timeout=15)` 方法（线程+超时，对齐 TqSDK 范式），将 3 处 AKShare 调用（`futures_zh_minute_sina` / `futures_zh_daily_sina` / `futures_main_sina`）统一包裹。超时返回 None 走下一降级源（numpy/EastMoney），不再无限阻塞。
- **即时止损（workspace层 scan_monitored.py）**：`subprocess.run(cmd, timeout=1200)`，超时即中止并输出明确原因（退出码124），杜绝无限挂。
- **验证**：py_compile 通过；超时机制单测——模拟30s无响应数据源在3s被拦截返回None（elapsed≈3s）。备份：`C:/Users/yangd/backups_fdt_akshare_timeout_20260711/`
- **版本**：pyproject.toml 5.12.0 → 5.12.1

### 本次处置
复用18:24扫描(同2026-07-10收盘基准)+复用18:24辩论4品种产物，run_debate.py finalize重汇编debate_results.json并再生报告。数据等价，结论一致。

---

## 2026-07-13 09:13 | 信号(scan)与策略(debate)不一致 — 交易系统收到矛盾信号

### 事件
用户指出OI/jd的扫描信号是BULL/WATCH，但辩论裁决是BEAR/观望，最终debate_results.json仍含entry/stop/target/size等完整交易参数。用户原话："最终产生的信号是要推送给交易系统的"。

### 根因分析
两个独立bug：

1. **`assemble()` 盲目填交易参数（run_debate.py）**: 无视裁决语义（NEUTRAL="观望"还是BEAR="可执行"），照抄p5_trading_plan的entry/stop/target/size到顶层输出。交易系统看到entry=4800+target=4650 → 以为有做空信号。

2. **`generate_intermediate_data()` 用扫描信号算decision（intermediate_data.json）**: 第480-484行对每个信号品种硬编码 `direction=="bull" → decision="BUY"`，完全跳过辩论裁决结果。所以即使辩论说"观望"，intermediate_data仍给m输出decision=BUY。

3. **下游 `phase3_generate_report.py` 的confidence类型兼容**: 修正后debate_results的confidence从数值(0.65)变为字符串("中")，phase3的 `if confidence < 0.4` 触发TypeError阻塞报告生成。

### 改正（已执行）

| # | 文件 | 修复 |
|:--|:-----|:-----|
| 1 | `scripts/run_debate.py` | 新增 `_derive_action()` 函数: NEUTRAL→wait / 总分差≤15→wait / 裁决≠扫描方向→wait / grade=WEAK→hold / 全部通过→execute |
| 2 | `scripts/run_debate.py` | `assemble()`: 当action≠execute时，entry_price/stop_loss_price/target_price/position_size/contract全部设为None |
| 3 | `scripts/run_debate.py` | `assemble()`: 顶层输出新增`action`字段（execute/hold/wait），交易系统直接读此字段判断 |
| 4 | `scripts/run_debate.py` | `generate_intermediate_data()`: decision字段从"扫描信号→BUY/SELL"改为"辩论action→HOLD/WATCH/BUY/SELL"。action=wait→HOLD, action=hold→WATCH |
| 5 | `scripts/run_debate.py` | `generate_intermediate_data()`: direction字段用辩论裁决方向覆盖扫描信号方向 |
| 6 | `scripts/run_debate.py` | `report`/`extract`子命令不强制加载scan文件（修复CLI bug: report和extract子parser无需--scan但main()仍尝试打开args.scan） |
| 7 | `skills/futures-trading-analysis/scripts/phase3_generate_report.py` | confidence字符串→float归一化: "高"→0.95, "中"→0.65, "低"→0.35 |

### 验证
修复后重新assemble+report：
- debate_results.json: 5品种全部action=wait, entry/stop/target/size=null ✅
- intermediate_data.json: 5品种全部decision=HOLD ✅  
- report: T1=0, T2=0, T3=0（无可执行信号）✅

### 预防
- 最终输出必须经过action消歧：扫描信号方向 ≠ 交易系统动作。辩论裁决是中间件，不是最终判决
- `generate_intermediate_data()` 中任何`decision`字段必须从辩论裁决读取，禁止从扫描信号直接推导
- `_derive_action()` 逻辑已固化在run_debate.py的assemble流程中，后续新增辩论品种自动适配

## 2026-07-15 20:15 | 盘后自动化扫描双阻塞：TqSDK关闭挂死 + channel_breakout get_strategy 未导入

**事件**: 自动化盘后扫盘（周三 20:15）执行 `fdt_cli.py pipeline --mode no-filter`，扫描阶段失败，无新辩论产物。回退交付早盘 scan_daily_20260715.json(10:45 内盘) + debate_report_20260715.html(11:16)。

**根因（双）**:
1. 环境层：TQ-Local(通达信)实际未吐数据 → FDC 降级到 TqSDK 逐品种拉 K 线 → TqSDK 事件循环关闭 `executor did not finish joining threads within 300 seconds` 挂死（单品种 RB 因 TQ-Local 命中 26s 完成；62 品种批量必挂）。
2. 代码回归：单策略 `channel_breakout` 路径 `scan_all.py:814` 调用 `get_strategy(strategy_name)` 但该名仅在其 pipeline 分支 `except` 内 `from strategies import get_strategy`（L810）导入 → `UnboundLocalError: cannot access local variable 'get_strategy'`。committed G40 v8.1.7（18:53）。pipeline 模式可绕过此 bug 但同样卡在 TqSDK 关闭。

**改正**: 按唯一副本铁律未改 plugins/marketplaces 代码（需掌柜"执行"）。改用今早有效 pipeline 扫描产物作辩论输入交付。

**预防**:
- A. 确保通达信 TQ-Local HTTP 服务稳定吐数（或 FDC 切 web_fallback），避免落 TqSDK 关闭挂死。
- B. `scan_all.py:814` 前补 `from strategies import get_strategy`（与 L810 一致），修单策略路径。
- C. 排查 TqSDK 关闭 300s 挂死（环境/版本），必要时限制 TqSDK 仅做降级源并设关闭超时。
- 自动化扫描失败时应有"回退到当日最近有效扫描"机制，避免整轮空转。

---

## 2026-07-15 22:10 | WebFallbackCollector 东方财富断连 + 新浪键名解析错误（降级链兜底失效）

### 事件
用户质疑降级链中 EastMoney(web) 能否正确取数（"之前无法正确获取"）。实证测试 RB/TA/M/SI/I 五品种：web_fallback 返回 4200+ 根 bar 但日期全空、收盘全 0.0（垃圾数据）。若 TQ-Local 掉线，链落 web_fallback(priority=1) → R24 闸门拒扫 → 整轮辩论流产（潜伏关键故障，对应上条 20:15 事故预防项 A）。

### 根因
1. **东方财富 (`_try_eastmoney`)**：`push2his.eastmoney.com/api/qt/stock/kline/get` 对期货 secid（如 `113.RB0`）返回 `RemoteDisconnected`（服务端直接断连，反爬/区域限制），当前环境取不到任何数据。
2. **新浪 (`_try_sina`)**：原始抓取成功（509KB 合法 JSON，价格正确），但解析用错键名——代码读 `date/open/high/low/close/volume`，新浪实际返回短键 `d/o/h/l/c/v` → 每条 K 线落默认空/0。且未对返回做 `[-days:]` 切片（返回全部历史）。

### 改正（已执行·掌柜授权"执行修复"）
`futures_data_core/collectors/web_fallback.py`：
1. `_try_sina`：改用新浪短键 `d/o/h/l/c/v`；日期 `YYYY-MM-DD` → 归一 `YYYYMMDD`（对齐管线）；补 `open_interest`(p)；加 `records[-days:]` 切片。
2. `get_kline`：改为 **新浪优先、东方财富次之**（避免每次空等 15s EastMoney 超时）。

### 验证
真实 collector 复测 RB/TA/M/SI/I 均返回 120 根有效 bar，日期 `20260715`、收盘为真实盘面价（RB=3115.0 / TA=5752.0 / M=3066.0 / SI=8425.0 / I=762.0），全部 OK。

### 预防
- 降级链 web 兜底层应以新浪为稳定主源；东方财富当前环境断连，仅作 best-effort 二级。
- 任何新增 web 源解析必须先用真实响应校验键名/字段，不能假设与股票 API 一致。

---

## 2026-07-15 22:53 | 信号融合层设计错误（重大生产事故·掌柜认定）

### 事件
掌柜认定：信号融合（无论**跨策略**，还是**同一策略内部子信号**）的思想本身错误，属重大生产事故。当前 `StrategyFusion`（默认 `WEIGHTED_MAX`）在 `scan_all` 管线里把 7 策略 + 各策略内部子信号坍缩成统一 `total`，再喂辩论入口闸门。掌柜明确要求：每个（策略 × 子信号）独立输出，按各自确定性判据筛选后独立进入辩论，**融合层必须删除**。

### 根因
1. **设计哲学错误**：v7.0.0 管线化时为给辩论入口闸门提供统一 `total` 标尺引入 `StrategyFusion`（默认 WEIGHTED_MAX）。该设计隐含"信号层可替下游做取舍"假设，与"信号层只负责产出、裁决交给辩论层"的架构原则冲突。
2. **双层坍缩**：(a) 跨策略同向坍缩（`pipeline.py:274-282` 取最高权重一条，其余塞进 `strategy_breakdown`）；(b) 策略内子信号经同一融合入口被合并——同一策略的 DC20突破 / Supertrend / SAR / 均线排列等子信号被压成一条代表信号。
3. **操作越界**：本会话后台盘后扫描 `scan_pipe_2010` 直接调 `get_pipeline()`（默认 WEIGHTED_MAX），在未经掌柜确认"信号该不该融合"的前提下运行了融合管线，产出融合后的辩论候选。

### 改正（v8.1.8 已执行·2026-07-16 00:17 落地）
1. **去融合（v8.1.8）**：`StrategyFusion` 标记废弃（Phase 3 改为直接 flatten 各策略子信号），docstring 注明"融合思想本身错误"。
2. **mean_reversion 子信号独立**：rsi/cci/bb 各独立 emit `RawSignal`（`mean_reversion.rsi/.cci/.bb`），旧投票合并逻辑已删。
3. **trend_following 子信号独立**：10 子信号各自独立 emit（`trend_following.dc20/.dc55/.bb/.keltner/.supertrend/.sar/.chandelier/.macd/.tsmom/.dual_thrust`），删投票累加 + signal_type 拼接。
4. **逐信号门禁**：`signal_passes_entry_gate()`（grade∈{STRONG,WATCH} 即进候选），替换全局 `|total|≥20`。
5. **reason 字段**：每个 ScoredSignal 新增 `reason`（signal_type+方向+grade+指标+强度），辩论层可识别"为什么选这个信号"。
6. **知识库**：`memory/knowledge/strategies/` 下 7 策略 JSON + `_index.json`，供辩论 Agent 按 signal_type 查阅权威规则交叉验证。
7. **测试覆盖**：187 策略测试全绿 + 421 全量回归通过。
8. **scan_pipe_2010**：已停止（前次会话操作）。

### 预防
- **信号层铁律（P0）**：任何层级（跨策略 / 策略内子信号）一律禁止融合；信号只产出、不裁决。
- `get_pipeline()` 默认不得带融合；如需融合须显式且经掌柜批准。
- 运行任何会产出辩论候选的扫描前，先确认其信号产出逻辑符合"独立输出"原则。
- 掌柜未确认的设计假设，操作方不得自行作为默认执行（本次 `scan_pipe_2010` 越界教训）。
