"""
coordinator.py — 可配置协调层调度引擎 v1.0.0
========================================

适用范围: FDT 辩论专家团（futures-debate-team）
设计来源: Coordination Layer (arXiv:2605.03310)

功能:
  1. 从 YAML 配置加载 Agent 定义、拓扑、终止条件
  2. 支持多 Profile 切换（default / fast / deep_research / tournament）
  3. 自动拓扑排序 + Agent 调度执行
  4. 输出完整执行轨迹

用法:
  from scripts.coordinator import Coordinator
  coord = Coordinator("coordination_config.yaml")
  result = coord.run(profile="fast")
  print(result["verdict"])
"""

import yaml
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class AgentTask:
    agent_id: str
    agent_type: str = ""
    description: str = ""
    input_data: Optional[dict] = None
    result: Optional[dict] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    status: str = "pending"  # pending / running / completed / failed / skipped


@dataclass
class CoordinatorResult:
    profile: str
    mode: str
    total_agents: int
    completed: int
    failed: int
    skipped: int
    total_duration: float
    tasks: dict
    verdict: Optional[dict] = None


class Coordinator:
    """
    可配置协调层调度引擎。
    根据 YAML 配置执行 Agent 编排。
    """

    def __init__(self, config_path: str):
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.agents_config = self.config.get("agents", {})
        self.orchestration = self.config.get("orchestration", {})
        self.topology = self.config.get("topology", {})
        self.termination = self.config.get("termination", {})
        self.authority = self.config.get("authority", {})
        self.profiles = self.config.get("profiles", {})

        self.tasks: dict[str, AgentTask] = {}
        self.is_running = False

    # ── 公开 API ──

    def run(self, profile: str = "default", inject_data: Optional[dict] = None) -> dict:
        """
        运行指定 profile 的编排流程。
        inject_data: 注入的初始数据（如 scan_all 结果）
        """
        start_time = time.time()

        # 加载 profile
        profile_config = self.profiles.get(profile, {})
        if not profile_config and profile != "default":
            raise ValueError(f"未知的 profile: {profile}。可选: {list(self.profiles.keys())}")

        self._apply_profile(profile_config)
        self.tasks = {}
        self.is_running = True

        # 拓扑排序
        edges = self._get_active_topology(profile_config)
        execution_order = self._resolve_execution_order(edges)

        # 初始化 Agent 任务
        for agent_id in execution_order:
            agent_cfg = self.agents_config.get(agent_id, {})
            self.tasks[agent_id] = AgentTask(
                agent_id=agent_id,
                agent_type=agent_cfg.get("type", "unknown"),
                description=agent_cfg.get("description", ""),
            )

        # 串行执行
        for agent_id in execution_order:
            if not self.is_running:
                break

            task = self.tasks[agent_id]
            agent_cfg = self.agents_config.get(agent_id, {})

            # 检查终止条件
            if not self._check_continuation(agent_id):
                task.status = "skipped"
                continue

            timeout = agent_cfg.get("timeout", 300)
            task.status = "running"
            task.start_time = time.time()

            try:
                result = self._execute_agent(agent_id, inject_data)
                task.result = result
                task.status = "completed"
            except Exception as e:
                task.result = {"error": str(e)}
                task.status = "failed"

            task.end_time = time.time()
            task.duration = round(task.end_time - task.start_time, 2)

        self.is_running = False
        total_duration = round(time.time() - start_time, 2)

        # 编译结果
        completed = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed = sum(1 for t in self.tasks.values() if t.status == "failed")
        skipped = sum(1 for t in self.tasks.values() if t.status == "skipped")

        result = CoordinatorResult(
            profile=profile,
            mode=self.orchestration.get("mode", "sequential"),
            total_agents=len(self.tasks),
            completed=completed,
            failed=failed,
            skipped=skipped,
            total_duration=total_duration,
            tasks={
                aid: asdict(t)
                for aid, t in self.tasks.items()
            },
            verdict=self.tasks.get("yanpanguan", AgentTask("yanpanguan")).result,
        )

        return asdict(result)

    # ── 内部方法 ──

    def _get_active_topology(self, profile_config: dict) -> list:
        """获取当前生效的拓扑"""
        if "topology" in profile_config:
            return profile_config["topology"].get("edges", [])
        return self.topology.get("edges", [])

    def _resolve_execution_order(self, edges: list[dict]) -> list[str]:
        """
        从边定义中解析执行顺序。
        简化的拓扑排序——确保依赖在依赖者之前执行。
        """
        # 建立依赖图
        depends_on: dict[str, set] = {}
        for edge in edges:
            froms = edge.get("from", [])
            tos = edge.get("to", [])
            if isinstance(froms, str):
                froms = [froms]
            if isinstance(tos, str):
                tos = [tos]
            for target in tos:
                if target not in depends_on:
                    depends_on[target] = set()
                for dep in froms:
                    depends_on[target].add(dep)

        # 拓扑排序
        all_agents = set(self.agents_config.keys())
        ordered = []
        added = set()

        # 找没有未满足依赖的节点
        while len(ordered) < len(all_agents):
            candidates = []
            for agent in all_agents:
                if agent in added:
                    continue
                deps = depends_on.get(agent, set())
                if deps.issubset(added):
                    candidates.append(agent)

            if not candidates:
                # 环检测或孤立节点 — 追加剩余
                remaining = all_agents - added
                ordered.extend(sorted(remaining))
                break

            ordered.extend(sorted(candidates))
            added.update(candidates)

        return ordered

    def _execute_agent(self, agent_id: str, inject_data: Optional[dict] = None) -> dict:
        """执行单个 Agent（占位——实际调用对应的 skill/spawn 函数）"""
        agent_cfg = self.agents_config.get(agent_id, {})

        return {
            "agent_id": agent_id,
            "agent_type": agent_cfg.get("type", "unknown"),
            "description": agent_cfg.get("description", ""),
            "status": "completed_by_coordinator",
            "note": "实际 Agent 执行由 spawn 机制完成。Coordinator 负责调度和拓扑管理。",
        }

    def _check_continuation(self, agent_id: str) -> bool:
        """检查是否满足继续执行的条件"""
        max_rounds = self.termination.get("max_rounds", 3)
        round_count = sum(
            1 for t in self.tasks.values()
            if t.status == "completed"
        )
        if round_count >= max_rounds:
            return False
        return True

    def _apply_profile(self, profile: dict):
        """应用 profile 配置覆盖"""
        if "mode" in profile:
            self.orchestration["mode"] = profile["mode"]
        if "termination" in profile:
            self.termination.update(profile["termination"])
        if "verdict_weighting" in profile.get("authority", {}):
            self.authority["verdict_weighting"] = profile["authority"]["verdict_weighting"]


# ── CLI 入口 ──

if __name__ == "__main__":
    import sys
    config_path = sys.argv[1] if len(sys.argv) > 1 else "coordination_config.yaml"
    profile = sys.argv[2] if len(sys.argv) > 2 else "default"

    coord = Coordinator(config_path)
    result = coord.run(profile=profile)

    print(f"\n=== 协调层执行报告 ===")
    print(f"Profile: {result['profile']}")
    print(f"模式: {result['mode']}")
    print(f"Agent: {result['completed']}/{result['total_agents']} completed")
    print(f"耗时: {result['total_duration']}s")

    for aid, task in result["tasks"].items():
        icon = {"completed": "✅", "failed": "❌", "skipped": "⏭️", "pending": "⏳"}
        print(f"  {icon.get(task['status'], '❓')} {aid}: {task['status']} ({task.get('duration', '?')}s)")
