# Agent 通道看门狗（强制版 · 2026-07-07 确立）

> 根治「问题3：Agent spawn 通道卡死」。环境优化，不改变核心 SOP 逻辑。由团队主管(明鉴秋)在 spawn 任何辩论子 Agent 时强制执行。

## 一、根因（已实证 · 2026-07-07 18:45 测试验证）

- **现象**：重跑 LH2609 时，链证源 11min 未覆盖旧文件、P4 双辩手 6min+ 未落盘，远超看门狗 420s。
- **根因**：`commodity-chain-analysis` 的 SKILL.md 要求链证源用 **WebSearch/WebFetch** 做基本面验证（80/95/221/236/239/345/362 行）。辩论管线运行时网络/EastMoney 断开，链证源的 WebSearch 阻塞 → 子 Agent 卡死不落盘。
- **验证**：以「禁止 WebSearch/WebFetch + max_turns=10 + 仅基于既有知识」spawn 链证源(LH)，**秒级返回**并原子写入 1869 字节产物。证明 WebSearch 阻塞是唯一根因，移除后即恢复正常。

## 二、强制规则（spawn 任意辩论子 Agent 必遵）

1. **禁止联网搜索（管线模式）**：spawn 链证源 / 证真 / 慎思 / 闫判官 / 风控明 时，prompt 末尾必须显式写：
   > 「注意：不要使用 WebSearch / WebFetch / 任何联网工具。所有外部数据已由探源(基本面)/观澜(技术面)/数技源(通道信号)在准备期采集并提供。网络不可用。」
   - 链证源：仅做产业链事实描述+景气度，**禁止 WebSearch 验证**（SOP 已规定外部数据走探源）。
   - 证真/慎思：SOP 已禁止辩手自行搜索，prompt 再次强调。
2. **有界 max_turns**：每个 spawn 必须设 `max_turns`（建议 10~15），防止子 Agent 无限轮推理卡死。
3. **早写早退**：prompt 要求子 Agent「先写产物文件(.tmp→rename)再结束」，不闲聊、不二次确认。
4. **轮询 + 硬超时兜底**：
   - 主管 spawn 后调用 `poll_file_ready(path, timeout=agent_watchdog_seconds=420)` 轮询产物。
   - 超时未就绪 → `TaskStop` 终止该子 Agent → 主管直驱兜底（基于已就绪文件 + 首轮论据）。
   - 禁止无界等待（绝不允许 11min 卡死重现）。

## 三、与 fast_track.md 看门狗的关系

- fast_track.md 的 `agent_watchdog_seconds=420` 是**阈值**；本文件是**强制动作**（禁止联网 + 有界 max_turns + poll+TaskStop 兜底），二者互补。
- 旧版仅"主管人工发现超时后直驱"，无自动拦截；现改为 spawn 即带「禁止联网+有界」，从根上消除卡死源。

## 四、回归防护

- 后续若发现某辩论 Agent 的 SKILL.md 新增联网搜索步骤，须在该 Agent 的管线 spawn prompt 中显式禁用（或改为准备期由探源统一采集）。
- 每次 spawn 后若产物未在 420s 内就绪，先查是否该 Agent 又触发了联网调用。
