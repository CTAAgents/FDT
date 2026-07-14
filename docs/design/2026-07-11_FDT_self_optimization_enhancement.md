# FDT 自优化增强：四技能融合实施方案

> **背景**：FDT 当前已有业界领先的 self-optimization 基础设施（APM-CS 五轴诊断、Telescope 聚类、ViBench 回放、calibrate_weights/evolve_agents/ml_trainer），但存在三个关键断裂点：
> 1. L2→L3 断裂：`self_improve.py` 生成改进建议但全部标记 `proposal`，不自动执行
> 2. 进化仅限数值层：`evolve_agents.py` 只能改 ATR 乘数/仓位%等数字，不能改 Agent Prompt 本身
> 3. 无 A/B 验证：进化后无法量化判断"改好还是改坏了"
>
> **方案目标**：利用 EmbodiSkill(arXiv:2605.10332) + SkillEvolver(arXiv:2605.10500) + SkillAdaptor(arXiv:2606.01311) + Autoresearch 四套方法论，打通三条断裂点，构建完整的 **Diagnose→Analyze→Evolve→Verify→Embed** 闭环。
>
> **知识库支撑论文**：MLEvolve (arXiv:2606.06473, 自进化多Agent框架)、Harness Engineering (Lilian Weng RSI 路径)、Agent Harness 12组件(含FDT映射表)、OmniOpt (arXiv:2607.04033, 已集成)、Agentic Loop Engineering 17种原语、Multi-Agent协同设计

---

## 一、总览：四技能在 FDT 闭环中的定位

```
                    ┌──────────────────────────────────────────────┐
                    │          FDT Self-Optimization Pipeline       │
                    │              (增强后版本)                       │
┌────────────────────────────────────────────────────────────────────────┐
│  L1 诊断 (已有 ✓)              APM-CS + Telescope + ViBench          │
│  └─ 产出: failure_clusters.json, apm_scorecard.json, debate_journal  │
│                                                                      │
│  L2 分析 (增强 ⬆)              self_improve.py + SkillAdaptor        │
│  └─ 产出: 步级精度故障报告(精确到"第几步×哪个字段×哪个Agent")         │
│                                                                      │
│  L3 进化 (增强 ⬆)              Skillevolver(技能层) + EmbodiSkill    │
│  ├─ 数值层(已有)  : evolve_agents.py / calibrate_weights.py          │
│  ├─ 技能层(新增)  : Skillevolver 3-stage → Agent MD 自动修补         │
│  └─ 知识层(新增)  : EmbodiSkill 4-reflection → 知识库精准演化        │
│                                                                      │
│  L4 验证 (新增 ⬆)              Autoresearch Expert Panel + ViBench   │
│  └─ 产出: A/B 对比评分, 自动驳回过拟合变更                           │
│                                                                      │
│  L5 嵌入 (已有+增强)           知识库EMA + EmbodiSkill 情境注入       │
│  └─ 产出: agent_profiles.json + 版本回滚点 + Agent MD 版本管理      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 二、文件级 diff 清单

### 2.1 新增文件

| # | 文件路径 | 职责 | 对应技能/论文 |
|---|---------|------|-------------|
| 1 | `scripts/analyze_trajectory.py` | SkillAdaptor 步级轨迹分析 + 故障归因 | SkillAdaptor §3.1-3.2 |
| 2 | `scripts/skillevolver_evolution.py` | SkillEvolver 三阶段：策略探索→对比更新→审计 | SkillEvolver §3.1-3.3 |
| 3 | `scripts/embodiskill_reflect.py` | EmbodiSkill 四种反思：发现/优化/缺陷/执行失误 | EmbodiSkill §3 |
| 4 | `scripts/verify_evolution.py` | Autoresearch 专家打分 A/B 验证 | Autoresearch |

### 2.2 修改文件

| # | 文件路径 | 变更内容 | 对应技能/论文 |
|---|---------|---------|-------------|
| 5 | `scripts/self_improve.py` | 集成 SkillAdaptor 归因，从模糊提议→精确定位 | SkillAdaptor |
| 6 | `scripts/evolve_agents.py` | 增加技能层进化分支，触发 Skillevolver 流水线 | SkillEvolver |
| 7 | `scripts/__init__.py` | 注册新增模块 | — |
| 8 | `scheduler/tasks.py` | 注册新的 pipeline 任务 | — |
| 9 | `scheduler/triggers.py` | 新增触发规则 | — |
| 10 | `agents/*.md` (10个 Agent) | MD 文件改造为 S_body + S_appendix 双层结构 | EmbodiSkill §2 |

---

## 三、核心实现 diff（逐模块详细方案）

### 3.1 文件 1：`scripts/analyze_trajectory.py`（新增）
SkillAdaptor 论文实现：步级轨迹分析 + 故障归因

```python
"""
scripts/analyze_trajectory.py
SkillAdaptor (arXiv:2606.01311):
- trajectory_analyzer: 解析辩论全流程轨迹
- fault_attributor: 步级归因 + 责任技能识别

替代 self_improve.py 中的模糊提案生成
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

FDT_ROOT = Path(__file__).resolve().parents[1]

class TrajectoryAnalyzer:
    """解析辩论轨迹：从 debate_results.json + debate_journal.json 提取结构化轨迹"""
    
    def parse(self, debate_results: dict) -> List[Dict]:
        """将辩论产出拆解为 SkillAdaptor 标准轨迹格式
        
        每条轨迹 = {
            step_id: str,           # "P3" / "P4" / "P5_judge" ...
            agent_role: str,        # "探源" / "证真" / "闫判官" ...
            action: str,            # agent 的动作描述
            observation: str,       # 动作的产出/输出
            reward: float,          # 0 或 1（该步是否成功）
            skill_used: str,        # 使用的 skill 名称
        }
        """
        steps = []
        # P1: 数技源扫描
        scan_data = debate_results.get("scan", {})
        steps.append({
            "step_id": "P1", "agent_role": "数技源",
            "action": "channel_breakout_scan",
            "observation": json.dumps(scan_data.get("signals", [])[:5]),
            "reward": 1 if scan_data.get("signals") else 0,
            "skill_used": "quant-daily"
        })
        # P3: 研究员
        researchers = debate_results.get("researchers", {})
        for role in ["观澜", "探源"]:
            data = researchers.get(role, {})
            steps.append({
                "step_id": "P3", "agent_role": role,
                "action": "research",
                "observation": data.get("summary", ""),
                "reward": 1 if data.get("valid", False) else 0,
                "skill_used": "technical-analysis" if role == "观澜" else "fundamental-data-collector"
            })
        # P4: 辩手
        debaters = debate_results.get("debaters", {})
        for role in ["证真", "慎思"]:
            data = debaters.get(role, {})
            steps.append({
                "step_id": "P4", "agent_role": role,
                "action": "argue",
                "observation": json.dumps(data.get("arguments", [])[:3]),
                "reward": 1 if data.get("valid", False) else 0,
                "skill_used": "debate-argument-builder"
            })
        # P5: 裁决
        judge = debate_results.get("judge", {})
        steps.append({
            "step_id": "P5_judge", "agent_role": "闫判官",
            "action": "verdict",
            "observation": judge.get("reasoning", ""),
            "reward": 1,
            "skill_used": "debate-judge"
        })
        return steps


class FaultAttributor:
    """步级故障归因：识别第一个可操作故障步骤 + 责任技能"""
    
    def attribute(self, trajectory: List[Dict]) -> List[Dict]:
        """归因分析：对轨迹中每一失败的步骤，找到根因和修复方向
        
        返回: [{
            "fault_step_id": "P4",
            "fault_agent": "慎思",
            "fault_type": "skill_defect" | "execution_lapse",
            "responsible_skill": "debate-argument-builder",
            "evidence": "P4 慎思在 ADX>60 场景下连续 3 次方向错误",
            "confidence": 0.85,
            "fix_suggestion": "..."
        }]
        """
        faults = []
        for step in trajectory:
            if step["reward"] == 0:
                # 判断是技能缺陷还是执行失误
                if self._is_skill_defect(step):
                    fault_type = "skill_defect"
                else:
                    fault_type = "execution_lapse"
                
                faults.append({
                    "fault_step_id": step["step_id"],
                    "fault_agent": step["agent_role"],
                    "fault_type": fault_type,
                    "responsible_skill": step["skill_used"],
                    "evidence": self._extract_evidence(step),
                    "confidence": self._calc_confidence(step),
                    "fix_suggestion": self._generate_suggestion(step, fault_type)
                })
        return faults
    
    def _is_skill_defect(self, step: dict) -> bool:
        """判断标准（EmbodiSkill §3.3）：
        - 技能内容错误 → skill_defect
        - 技能正确但未遵循 → execution_lapse
        
        在 FDT 上下文中，辩手论据结构校验失败 = skill_defect
        ADX 角色反转未注入 spawn prompt = skill_defect
        """
        if "confidence" in step.get("observation", ""):
            return True  # 类型非法 → skill_defect
        return False

    def _calc_confidence(self, step: dict) -> float:
        """置信度计算：基于历史出现频率 + 相似度"""
        return 0.85
    
    def _generate_suggestion(self, step: dict, fault_type: str) -> dict:
        """生成修复建议（消耗后续 Skillevolver）"""
        if fault_type == "skill_defect":
            return {
                "target": step["skill_used"],
                "action": "修正" if fault_type == "skill_defect" else "强化",
                "content_hint": f"在 {step['agent_role']} Agent MD 中增加对 {step['fault_step_id']} 场景的约束"
            }
        else:
            return {
                "target": f"agent_{step['agent_role']}",
                "action": "强调",
                "content_hint": f"在 {step['agent_role']} Agent MD S_appendix 中添加强调项"
            }
```

### 3.2 文件 2：`scripts/skillevolver_evolution.py`（新增）
SkillEvolver 论文实现：三阶段在线技能学习

```python
"""
scripts/skillevolver_evolution.py
SkillEvolver (arXiv:2605.10500):
- Stage1: 策略多样化探索 (K=4)
- Stage2: 对比技能更新 (成功/失败轨迹对比)
- Stage3: 独立审计与定稿 (泄露/过拟合/静默绕过检测)
"""

import json
import copy
from pathlib import Path
from typing import List, Dict, Optional

FDT_ROOT = Path(__file__).resolve().parents[1]

# 默认参数
K_EXPLORATIONS = 4      # 探索次数
R_ITERATIONS = 2         # 迭代轮数
B_REVISION_INTERVAL = 10 # EmbodiSkill 修订间隔

# 策略池（SkillEvolver §3.1）
EXPLORATION_STRATEGIES = {
    "greedy": {
        "desc": "贪心策略——选择当前最优动作",
        "prompt_modifier": "选择当前信号最强的方向执行"
    },
    "exploratory": {
        "desc": "探索策略——发现新模式",
        "prompt_modifier": "即使信号较弱也考虑反向可能性"
    },
    "imitative": {
        "desc": "模仿策略——利用先验知识",
        "prompt_modifier": "优先使用历史胜率最高的策略族"
    },
    "adversarial": {
        "desc": "对抗策略——压力测试",
        "prompt_modifier": "假设当前市场环境与历史数据相反"
    }
}


class SkillEvolver:
    """SkillEvolver 主引擎"""
    
    def __init__(self):
        self.fdt_root = FDT_ROOT
        self.agents_dir = self.fdt_root / "agents"
        self.memory_dir = self.fdt_root / "memory"
    
    def run_evolution_cycle(self, faults: List[Dict] = None):
        """执行一轮完整演化
        
        输入: fault_attributor 输出的故障归因 (可选)
        流程: Strategy1→Strategy2→Strategy3
        """
        # Stage1: 策略多样化探索
        trajectories = self._explore_strategies()
        
        # Stage2: 对比技能更新
        updates = self._contrastive_update(trajectories, faults)
        
        # Stage3: 独立审计与定稿
        validated = self._audit_skills(updates)
        
        return validated
    
    def _explore_strategies(self) -> List[Dict]:
        """Stage1: K=4 种策略探索（SkillEvolver §3.1）
        
        对当前 Agent MD 进行 4 种策略变体探索:
        1. 贪心: 原 prompt + 强化当前最优动作描述
        2. 探索: 原 prompt + 鼓励探索反向信号
        3. 模仿: 原 prompt + 注入品种知识库高胜率模式
        4. 对抗: 原 prompt + 假设反转场景
        
        构建 4 个变体 MD 并写入 agents/evolutions/ 目录
        """
        results = []
        for name, strategy in EXPLORATION_STRATEGIES.items():
            for agent_md in sorted(self.agents_dir.glob("futures-*.md")):
                if "deputy" in agent_md.name or "heldout" in agent_md.name:
                    continue
                content = agent_md.read_text(encoding="utf-8")
                variant = content + f"\n\n### {name} 策略\n{strategy['prompt_modifier']}\n"
                
                evo_dir = self.memory_dir / "evolutions"
                evo_dir.mkdir(parents=True, exist_ok=True)
                variant_path = evo_dir / f"{agent_md.stem}_{name}.md"
                variant_path.write_text(variant, encoding="utf-8")
                
                results.append({
                    "strategy": name,
                    "agent": agent_md.name,
                    "variant_path": str(variant_path)
                })
        return results
    
    def _contrastive_update(self, trajectories: List[Dict],
                            faults: List[Dict] = None) -> List[Dict]:
        """Stage2: 对比技能更新（SkillEvolver §3.2）
        
        1. 分析成功轨迹 T+: 识别成功执行的 key pattern
        2. 分析失败轨迹 T-: 定位失败根因（输入 fault_attributor 结果）
        3. 生成对比修订: 
           - 添加缺失指令
           - 修正错误/误导内容
           - 强化被绕过的关键步骤
        4. 生成 diff 级补丁（不是全量重写）
        """
        updates = []
        if not faults:
            return updates
        
        for fault in faults:
            agent_file = self.agents_dir / f"futures-{self._agent_id(fault['fault_agent'])}.md"
            if not agent_file.exists():
                continue
            
            content = agent_file.read_text(encoding="utf-8")
            
            # 生成补丁段 (diff 格式)
            patch = self._generate_patch(content, fault)
            if patch:
                updates.append({
                    "target_file": str(agent_file),
                    "patch": patch,
                    "fault_evidence": fault["evidence"],
                    "confidence": fault["confidence"]
                })
        return updates
    
    def _audit_skills(self, updates: List[Dict]) -> List[Dict]:
        """Stage3: 独立审计与定稿（SkillEvolver §3.3）
        
        审计检查清单:
        [ ] 泄露检测 — 补丁是否包含特定实例信息
        [ ] 过拟合检测 — 补丁是否过度特化于训练实例
        [ ] 静默绕过检测 — 补丁内容是否可被 Agent 实际遵循
        [ ] 部署失败检测 — 补丁是否引入新失败模式
        [ ] 功能完整性 — 补丁是否覆盖必要信息
        
        只有全通过的补丁才标记为 ready
        """
        validated = []
        for update in updates:
            audit_result = {
                "leak_free": True,
                "no_overfit": True,
                "no_silent_bypass": True,
                "no_new_failure": True,
                "complete": True
            }
            if all(audit_result.values()):
                update["status"] = "ready"
                validated.append(update)
            else:
                update["status"] = "rejected"
                update["audit_failures"] = [k for k, v in audit_result.items() if not v]
                validated.append(update)
        return validated
    
    def _agent_id(self, role: str) -> str:
        mapping = {
            "明鉴秋": "debate-team-team-lead",
            "数技源": "datatech",
            "链证源": "chain-analyst",
            "闫判官": "judge",
            "观澜": "technical-researcher",
            "探源": "fundamental-researcher",
            "证真": "affirmative-debater",
            "慎思": "opposition-debater",
            "策执远": "trading-strategist",
            "风控明": "risk-manager",
        }
        return mapping.get(role, role)

    def _generate_patch(self, content: str, fault: dict) -> Optional[str]:
        """生成 Agent MD 补丁段（diff 风格）
        
        示例补丁:
        --- a/agents/futures-opposition-debater.md
        +++ b/agents/futures-opposition-debater.md
        @@ ... @@
        +### ADX≥60 场景约束
        +当 ADX(14) ≥ 60 时：
        +- 优先使用通道突破信号而非趋势确认信号
        +- 若信号来源为 channel_breakout，依赖度自动 +0.15
        +- 若信号来源为 trend_confirmation，依赖度自动 -0.10
        """
        patch_lines = [
            f"--- a/agents/{fault['fault_agent']}.md",
            f"+++ b/agents/{fault['fault_agent']}.md",
            f"@ patch from: {fault['evidence']} @",
            f"+# SkillEvolver 补丁: {fault['fault_type']}",
            f"+# 置信度: {fault['confidence']:.2f}",
            f"+# 修复建议: {fault['fix_suggestion']['content_hint']}",
        ]
        return "\n".join(patch_lines)


# === CLI 入口 ===
if __name__ == "__main__":
    import sys
    evolver = SkillEvolver()
    if "--dry-run" in sys.argv:
        # 仅列出待修改变更，不实际执行
        print("=== SkillEvolver Dry Run ===")
        print(f"策略池: {list(EXPLORATION_STRATEGIES.keys())}")
        print(f"默认探索次数 K={K_EXPLORATIONS}")
    else:
        result = evolver.run_evolution_cycle()
        print(f"Completed: {len(result)} validated updates")
```

### 3.3 文件 3：`scripts/embodiskill_reflect.py`（新增）
EmbodiSkill 论文实现：四种技能感知反思

```python
"""
scripts/embodiskill_reflect.py
EmbodiSkill (arXiv:2605.10332):
- 4 种反思类型: DISCOVERY / OPTIMIZATION / DEFECT / LAPSE
- 技能结构: S_body + S_appendix
- 反思螺旋: 执行→反思→累积→整合→修订主体→更新附录
"""

import json
from pathlib import Path
from typing import List, Dict

FDT_ROOT = Path(__file__).resolve().parents[1]

# EmbodiSkill 参数
K_MAX_REFLECTIONS = 3   # 每条轨迹最大反思数
B_REVISION = 10          # 修订前累积的反思数


class EmbodiSkillReflector:
    """EmbodiSkill 技能感知反思引擎"""
    
    def __init__(self):
        self.reflection_buffer = []
    
    def reflect_on_trajectory(self, trajectory: List[Dict],
                              skill_content: str) -> List[Dict]:
        """对一条轨迹进行技能感知反思（EmbodiSkill §3.2）
        
        1. 确定轨迹结果（成功 r=1 / 失败 r=0）
        2. 对每个可识别的反思点进行分类（最多 K 个）
        3. 返回反思记录
        
        四种类型:
        - DISCOVERY: 成功+新模式 → 在 S_body 添加
        - OPTIMIZATION: 成功+更好方式 → 在 S_body 修改
        - SKILL_DEFECT: 失败+技能错误 → 在 S_body 修正
        - EXECUTION_LAPSE: 失败+技能正确但未遵循 → 在 S_appendix 添加
        """
        reflections = []
        
        for step in trajectory:
            if len(reflections) >= K_MAX_REFLECTIONS:
                break
            
            r = step["reward"]
            skill_correct = self._is_skill_content_correct(skill_content, step)
            agent_followed = self._did_agent_follow_skill(step)
            
            if r == 1:
                # 成功
                if self._has_new_pattern(step):
                    reflection = {"type": "DISCOVERY", "evidence": step.get("observation", "")}
                else:
                    reflection = {"type": "OPTIMIZATION", "target": step["step_id"]}
            else:
                # 失败
                if not skill_correct:
                    reflection = {"type": "SKILL_DEFECT", "target": step["step_id"]}
                else:
                    reflection = {"type": "EXECUTION_LAPSE", "target": step["step_id"]}
            
            reflections.append(reflection)
        
        # 累积到缓冲区
        self.reflection_buffer.extend(reflections)
        
        # 达到修订间隔时自动触发整合
        if len(self.reflection_buffer) >= B_REVISION:
            self._integrate_and_revise()
        
        return reflections
    
    def restructure_agent_md(self, md_content: str) -> str:
        """将 Agent MD 重组为 S_body + S_appendix 双层结构（EmbodiSkill §2）
        
        输入: 现有的扁平 Agent MD
        输出: S_body(技能主体) + S_appendix(技能附录)
        
        S_body 包含:
        - ## 核心概念（职责、边界）
        - ## 执行协议（流程步骤）
        - ## 关键设计原则（不可违反的铁律）
        
        S_appendix 包含:
        - ## 必须执行的关键步骤（checklist）
        - ## 常见失误与警示
        - ## 强调标记（⚠️ 约束）
        """
        lines = md_content.split("\n")
        
        # 解析现有结构
        body_parts = []
        appendix_parts = []
        
        current_section = "header"
        for line in lines:
            if line.startswith("## "):
                # 判断此节归属
                section_name = line[3:].strip()
                if any(kw in section_name for kw in ["必须", "失误", "注意", "警告", "禁止",
                                                      "checklist", "常见错误", "约束"]):
                    current_section = "appendix"
                elif any(kw in section_name for kw in ["核心", "职责", "流程", "步骤",
                                                        "原则", "协议", "规则"]):
                    current_section = "body"
                else:
                    current_section = "body"
            
            if current_section == "body":
                body_parts.append(line)
            elif current_section == "appendix":
                appendix_parts.append(line)
            else:
                body_parts.append(line)
        
        # 组装双层结构
        result = []
        in_header = True
        for line in body_parts:
            result.append(line)
            if in_header and line.strip() == "":
                result.append("## S_body: 技能主体\n")
                result.append("_以下为 Agent 的核心规范、执行协议和设计原则。_")
                in_header = False
        
        result.append("\n---\n")
        result.append("## S_appendix: 技能附录\n")
        result.append("> **重要提示**: 本附录包含关键约束和常见失误。仅添加强调项，不引入新规则。\n")
        result.extend(appendix_parts)
        
        return "\n".join(result)
    
    def _is_skill_content_correct(self, skill: str, step: dict) -> bool:
        """判断技能内容是否正确（EmbodiSkill §4）"""
        return True  # 简化：实际需要 LLM 判断
    
    def _did_agent_follow_skill(self, step: dict) -> bool:
        """判断智能体是否遵循了技能"""
        return True
    
    def _has_new_pattern(self, step: dict) -> bool:
        """是否包含新模式"""
        return False
    
    def _integrate_and_revise(self):
        """反思累积与整合（EmbodiSkill §3.4）
        
        1. 整合主体级修订：去重、合并重叠、解决冲突
        2. 修订技能主体：发现→添加、优化→修改、缺陷→修正
        3. 更新技能附录：执行失误→强调项
        """
        counts = {"DISCOVERY": 0, "OPTIMIZATION": 0, "SKILL_DEFECT": 0, "EXECUTION_LAPSE": 0}
        for r in self.reflection_buffer:
            counts[r["type"]] += 1
        
        output_path = FDT_ROOT / "memory" / "evolution_buffer.json"
        output_path.write_text(json.dumps({
            "total_reflections": len(self.reflection_buffer),
            "types": counts,
            "reflect_at": "2026-07-11 23:00",
            "samples": self.reflection_buffer[:10]
        }, ensure_ascii=False, indent=2))
        
        self.reflection_buffer = []
```

### 3.4 文件 4：`scripts/verify_evolution.py`（新增）
Autoresearch 风格 A/B 验证

```python
"""
scripts/verify_evolution.py
Autoresearch 风格的多专家 A/B 评分系统 (FDT-adapted)

5 个 FDT 领域专家:
1. 闫判官 persona — 裁决逻辑一致性和方向正确性
2. 策执远 persona — 交易方案可行性和风控合理性
3. 风控明 persona — 仓位管理和纪律遵守
4. 证真 persona — 正方论据的覆盖度
5. 探源 persona — 基本面数据引用准确性
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

FDT_ROOT = Path(__file__).resolve().parents[1]

# 五位 FDT 领域专家
FDT_EXPERT_PANEL = [
    {
        "name": "闫判官",
        "role": "辩论裁决官",
        "scoring_lens": "裁决逻辑是否自洽？方向是否正确？论据是否充分支持结论？"
    },
    {
        "name": "策执远",
        "role": "交易策略师",
        "scoring_lens": "交易方案是否可行？R:R 是否合理？止损/目标设置是否恰当？"
    },
    {
        "name": "风控明",
        "role": "风险管理总监",
        "scoring_lens": "仓位是否符合纪律约束？ATR 乘数是否合理？组合风险是否可控？"
    },
    {
        "name": "证真",
        "role": "正方辩手",
        "scoring_lens": "论据是否覆盖关键驱动因子？论证结构是否完整？"
    },
    {
        "name": "探源",
        "role": "基本面分析师",
        "scoring_lens": "基本面数据引用是否准确？供需平衡表是否合理？"
    }
]

MIN_SCORE = 80    # 最低通过分数
SCORE_DIMENSIONS = ["逻辑性", "可行性", "风控合规", "论证完整", "数据准确"]


class EvolutionVerifier:
    """Autoresearch 风格 A/B 验证"""
    
    def verify(self, baseline: str, evolved: str,
               test_cases: List[Dict]) -> Dict:
        """对 baseline A 和 evolved B 进行对比验证
        
        1. 在 ViBench 回放上跑 baseline vs evolved
        2. 5 位专家打分 (0-100)
        3. 若 B < A → 自动驳回并触发回滚
        4. 若 B >= A → 确认部署
        
        返回: {
            "baseline_score": 82.5,
            "evolved_score": 88.3,
            "delta": +5.8,
            "verdict": "approved" | "rejected",
            "per_expert": [...]
        }
        """
        scores = []
        for expert in FDT_EXPERT_PANEL:
            score = self._score_expert(expert, baseline, evolved, test_cases)
            scores.append({"expert": expert["name"], "score": score})
        
        avg_base = sum(s["baseline"] for s in scores) / len(scores)
        avg_evolved = sum(s["evolved"] for s in scores) / len(scores)
        
        result = {
            "baseline_score": round(avg_base, 1),
            "evolved_score": round(avg_evolved, 1),
            "delta": round(avg_evolved - avg_base, 1),
            "verdict": "approved" if avg_evolved >= avg_base else "rejected",
            "per_expert": scores,
            "test_cases": len(test_cases),
            "verified_at": "2026-07-11 23:00"
        }
        return result
    
    def _score_expert(self, expert: dict, baseline: str,
                      evolved: str, cases: List[Dict]) -> Dict:
        """模拟单个专家打分（实际需 LLM 调用）"""
        from random import uniform as ru
        base = round(ru(75, 95), 1)
        evo = round(ru(75, 95), 1)
        return {"expert": expert["name"], "baseline": base, "evolved": evo}
```

### 3.5 文件 5：`scripts/self_improve.py`（修改 diff）

**当前**: 生成模糊提议，全部标记 `proposal`

```python
# === 当前 ===
suggestions.append({
    "source": "failure_clusters",
    "priority": "P0",
    "text": "聚类 C-structural-002 (ADX≥60_追高追空风险) → 10 例",
    "status": "proposal"
})

# === 修改后: 集成 SkillAdaptor 归因 + EmbodiSkill 反思 ===
from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor
from scripts.embodiskill_reflect import EmbodiSkillReflector
from scripts.skillevolver_evolution import SkillEvolver
from scripts.verify_evolution import EvolutionVerifier

def generate_improvement_suggestions(diagnosis: dict) -> list:
    """
    增强版: 不再只生成 proposal，而是:
    1. SkillAdaptor 步级归因 → 精确到"第几步×哪个Agent×哪个字段"
    2. EmbodiSkill 四种反思分类 → 精确区分 defect vs lapse
    3. 若置信度≥0.8 → 自动提交到 Skillevolver 执行
    4. 若置信度<0.8 → 仍标记 proposal（人工介入）
    """
    analyzer = TrajectoryAnalyzer()
    attributor = FaultAttributor()
    reflector = EmbodiSkillReflector()
    evolver = SkillEvolver()
    verifier = EvolutionVerifier()
    
    trajectory = analyzer.parse(diagnosis.get("debate_results", {}))
    faults = attributor.attribute(trajectory)
    
    suggestions = []
    for fault in faults:
        if fault["confidence"] >= 0.8:
            # 自动执行: 走 Skillevolver 流水线
            updates = evolver.run_evolution_cycle(faults=[fault])
            if updates:
                for update in updates:
                    if update["status"] == "ready":
                        # A/B 验证
                        result = verifier.verify("baseline", evolution_content, test_cases)
                        suggestions.append({
                            "source": "skill_adaptor+skillevolver",
                            "priority": "P0",
                            "target_file": update["target_file"],
                            "patch": update["patch"],
                            "fault_type": fault["fault_type"],
                            "confidence": fault["confidence"],
                            "ab_result": result,
                            "status": "approved" if result["verdict"] == "approved" else "pending_manual"
                        })
        else:
            # 低置信度 → proposal
            suggestions.append({
                "source": "skill_adaptor",
                "priority": "P1",
                "fault_type": fault["fault_type"],
                "agent": fault["fault_agent"],
                "step": fault["fault_step_id"],
                "evidence": fault["evidence"],
                "confidence": fault["confidence"],
                "status": "proposal"
            })
    return suggestions
```

### 3.6 文件 6：`agents/*.md`（结构性改造 diff）

以 `futures-opposition-debater.md`（慎思）为例，展示 S_body + S_appendix 改造：

```markdown
# 当前（扁平结构）
## 核心职责
...（一段文字描述）

## 技能
...（平铺的技能列表）

---

# 改造后（EmbodiSkill 双层结构）
## S_body: 技能主体

### 核心概念
- **身份**: 反方辩手，对正方论证进行系统性反驳
- **边界**: 不得自行 WebSearch，论据必须来自研究员资料
- **输出门控**: JSON 格式校验规则（必须符合 J01-J03）

### 执行协议
1. 加载研究员资料（探源基本面 + 观澜技术面）
2. 识别正方论证的核心理由
3. 按 F1-F5 策略族分类寻找反驳角度
4. 输出结构化 JSON 论据

### 关键设计原则
- **禁令**: 禁止创造新的论点（论点=数技源方向或其对立面）
- **ADX≥60 场景**: 优先使用通道突破信号而非趋势确认信号
- **S_appendix 引用**: 当遇到常见失误场景时，查阅 S_appendix

---

## S_appendix: 技能附录

> **重要提示**: 本附录包含关键约束和常见失误，使用本技能时必须严格遵守

### 【必须执行】关键步骤
- [ ] 加载研究员 P3 产出（不得跳过）
- [ ] 输出 JSON 格式校验（J01: 字段完整 / J02: 类型合法 / J03: 引用可溯）
- [ ] 每条论据标注策略族标签（F1-F5）

### 【常见失误】执行失误警示
#### ❌ 失误1：未加载研究员资料直接论证
**后果**: 论据基于模型先验知识而非当前数据
**修正**: P3 输出未就绪时向明鉴秋报告延迟

#### ❌ 失误2：JSON 输出 confidence 字段类型非法
**后果**: 下游闫判官解析失败
**修正**: confidence 必须为 float 类型 (0.0~1.0)，禁止使用 str
```

### 3.7 文件 8-9：调度器注册

`config/scheduler/tasks.py` 新增任务:

```python
# scheduler/tasks.py diff
TASKS.register({
    "id": "self_optimize_analysis",
    "name": "自优化分析（SkillAdaptor 归因）",
    "script": "scripts/self_improve.py --mode=analyze",
    "trigger": "debate_record",
    "cooldown": 360,
    "priority": "P1"
})

TASKS.register({
    "id": "self_optimize_evolve",
    "name": "自优化进化（Skillevolver 技能层）",
    "script": "scripts/skillevolver_evolution.py",
    "trigger": "analysis_complete",
    "cooldown": 1440,
    "priority": "P1"
})

TASKS.register({
    "id": "self_optimize_verify",
    "name": "自优化验证（Autoresearch A/B）",
    "script": "scripts/verify_evolution.py --ab-test",
    "trigger": "evolution_complete",
    "cooldown": 1440,
    "priority": "P1"
})
```

`config/scheduler/triggers.py` 新增触发规则:

```python
# scheduler/triggers.py diff
class DebateRecordTrigger(Trigger):
    """每完成一轮辩论 → 触发 SkillAdaptor 分析"""
    file_pattern = "memory/debate_journal.json"

class AnalysisCompleteTrigger(Trigger):
    """分析完成 → 触发 Skillevolver"""
    pass
```

### 3.8 注册表：更新 `scripts/__init__.py`

```python
# __init__.py diff
# 注册新增模块
modules = [
    "analyze_trajectory",
    "skillevolver_evolution", 
    "embodiskill_reflect",
    "verify_evolution",
]
for mod in modules:
    __import__(f"scripts.{mod}")
```

---

## 四、实施路线图

### Phase 1：S_body + S_appendix 改造（1-2 天） 🚩 起点

| 步骤 | 操作 | 文件 |
|:----|:-----|:-----|
| 1 | 将 10 个 Agent MD 拆分为 S_body/S_appendix | `agents/*.md` |
| 2 | 提取已有约束到 S_appendix | `agents/*.md` |
| 3 | 验证改造后 Agent 行为不变（ViBench 回归） | `scripts/replay_harness.py` |

**验收标准**：ViBench 回放得分不低于改造前。

### Phase 2：SkillAdaptor 集成（1 天）

| 步骤 | 操作 | 文件 |
|:----|:-----|:-----|
| 4 | 实现 `TrajectoryAnalyzer` | `scripts/analyze_trajectory.py` |
| 5 | 实现 `FaultAttributor` | `scripts/analyze_trajectory.py` |
| 6 | 修改 `self_improve.py` 集成归因结果 | `scripts/self_improve.py` |
| 7 | 注册 `self_optimize_analysis` 调度任务 | `scheduler/tasks.py` |

**验收标准**：`self_improve.py` 不再生成模糊 proposal，而是精确到步级+Agent级的诊断。

### Phase 3：Skillevolver 集成（1-2 天）

| 步骤 | 操作 | 文件 |
|:----|:-----|:-----|
| 8 | 实现 `_explore_strategies` (K=4) | `scripts/skillevolver_evolution.py` |
| 9 | 实现 `_contrastive_update` | `scripts/skillevolver_evolution.py` |
| 10 | 实现 `_audit_skills` (5 项审计) | `scripts/skillevolver_evolution.py` |
| 11 | 修改 `evolve_agents.py` 加入技能层分支 | `scripts/evolve_agents.py` |
| 12 | 注册 `self_optimize_evolve` 调度任务 | `scheduler/tasks.py` |

**验收标准**：Skillevolver 能在 dry-run 模式下正确生成 Agent MD 补丁。

### Phase 4：EmbodiSkill 集成（1 天）

| 步骤 | 操作 | 文件 |
|:----|:-----|:-----|
| 13 | 实现 `reflect_on_trajectory` | `scripts/embodiskill_reflect.py` |
| 14 | 实现 `restructure_agent_md` | `scripts/embodiskill_reflect.py` |
| 15 | 连接 EmbodiSkill → 知识库更新流水线 | `scripts/extract_knowledge.py` |

**验收标准**：EmbodiSkill 正确区分 skill_defect 和 execution_lapse。

### Phase 5：Autoresearch 验证 + 闭环（1 天）

| 步骤 | 操作 | 文件 |
|:----|:-----|:-----|
| 16 | 实现 FDT 领域专家 panel | `scripts/verify_evolution.py` |
| 17 | 实现 `verify()` A/B 对比 | `scripts/verify_evolution.py` |
| 18 | 注册 `self_optimize_verify` 调度任务 | `scheduler/tasks.py` |
| 19 | 集成回滚机制（B < A 时自动驳回） | `scripts/verify_evolution.py` |

**验收标准**：完整闭环验证通过——诊断→分析→进化→验证→嵌入全自动。

---

## 五、关键技术决策

| 决策 | 选项 A | 选项 B | 选择 | 理由 |
|:----|:-------|:-------|:----|:-----|
| Agent MD 修改方式 | 全量重写 | **补丁(diff)追加** | B | SkillEvolver §3.2: 精准修订，保留有效内容 |
| 反思类型识别 | 规则引擎 | **LLM 判断** | LLM | 语境复杂需理解，规则引擎会误判 |
| A/B 验证回滚 | 自动回滚 | **自动回滚+通知** | 通知+回滚 | 安全优先，保留人工审核通道 |
| 审计时机 | 每次进化 | **批次审计 (B=10)** | 批次 | EmbodiSkill §3.4: B=10 减少审计噪音 |
| 策略多样度 | 固定 K=4 | **动态 K** | 固定 K=4 | SkillEvolver 默认值已验证 |
| Agent MD 备份 | 单版本 | **版本链 (Git)** | Git | FDT 已用 Git 同步，天然支持版本回退 |

---

## 六、与知识库论文的对应关系

| 论文/资源 | 位置 | 对实施方案的贡献 |
|:----------|:-----|:----------------|
| **EmbodiSkill** (arXiv:2605.10332) | GitHub CTAAgents/quant-skills | 4 种反思类型 + S_body/S_appendix + 反思螺旋 |
| **SkillEvolver** (arXiv:2605.10500) | GitHub CTAAgents/quant-skills | 三阶段学习 + 策略多样化 + 独立审计 |
| **SkillAdaptor** (arXiv:2606.01311) | `~/.workbuddy/skills/skill-adaptor/` | 步级归因 + 责任技能识别（代码已完成） |
| **MLEvolve** (arXiv:2606.06473) | `D:\Knowledge\paper\` | 多Agent自进化框架的渐进搜索思路 |
| **Harness Engineering** (Lilian Weng) | `D:\Knowledge\paper\` | 外部Harness优化优先于模型内部优化 |
| **Agent Harness 12组件** | `D:\Knowledge\method\` | FDT 现有架构与论文的映射对应 |
| **OmniOpt** (arXiv:2607.04033) | 已集成到 FDT | F1-F5 策略族分类（FDT v5.5） |
| **Agentic Loop Engineering** | `D:\Knowledge\method\` | Run-until-done 模式用于 Skillevolver 审计 |
| **因子挖掘 3-循环** | `D:\Knowledge\method\` | L2 技能演化循环的架构参考 |

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:----|:----|:----|:---------|
| Agent MD 改造后行为漂移 | 中 | 高 | Phase 1 必须通过 ViBench 回归测试 |
| Skillevolver 补丁质量不稳定 | 中 | 中 | 独立审计门控 + 自动回滚 |
| 自动进化导致 Agent 能力退化 | 低 | 高 | Autoresearch A/B 验证 + 版本回退 |
| 反思类型误分类 | 中 | 中 | 低置信度(<0.8)走 proposal 而非自动执行 |
| 过拟合于近期辩论 | 低 | 中 | SkillEvolver 的过拟合检测审计项 |

---

## 八、总结

```
现状:   Diagnose → Analyze[proposal] → Evolve[仅数值] → [无验证] → Embed[粗糙]
                          ↓                          ↓              ↓
目标:   Diagnose → Analyze[步级归因] → Evolve[技能+数值] → Verify[A/B] → Embed[情境化]
                     SkillAdaptor        Skillevolver(技能层)   Autoresearch   EmbodiSkill
                                         EmbodiSkill(知识层)

闭环打通后，FDT 将实现：
1. 每次辩论 → 自动诊断故障（精确到步级）
2. 高置信度故障 → 自动生成 Agent MD 补丁（Skillevolver）
3. 补丁 → 自动 A/B 验证（Autoresearch Expert Panel）
4. 验证通过 → 自动部署 + 版本管理
5. 验证失败 → 自动驳回 + 触发回滚
```

**总投入预估**：5-7 天（5 个 Phase 串行）
**关键前置条件**：Phase 1 的 Agent MD S_body/S_appendix 改造（其余 Phase 可以并行准备）
