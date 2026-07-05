from scripts.unified_logger import get_logger
_logger = get_logger("debate_engine")
# -*- coding: utf-8 -*-
"""辩论流程并行化引擎 v1.0 — DAG调度器（P1-3）。

分析10角色的依赖图，并行化独立角色，总耗时降至串行的30-50%。

依赖图：
```
Level 0: 数技源, 链证源, 事件日历  (互相独立，可并行)
Level 1: 探源, 观澜              (独立，依赖数技源数据)
Level 2: 闫判官准备期            (综合Level 0+1)
Level 3: 证真, 慎思             (依赖闫判官方向，可并行)
Level 4: 策执远, 风控明          (策执远→风控明，串行)
Level 5: 闫判官最终裁决           (依赖风控)
Level 6: 明鉴秋汇总              (最终)
```
"""

from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import threading, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed


class DAGNode:
    """DAG节点 — 代表一个Agent阶段。"""

    def __init__(self, name: str, level: int, deps: List[str],
                 action: Optional[Callable] = None,
                 timeout: int = 120):
        self.name = name
        self.level = level          # 拓扑层级 (0=最前)
        self.deps = deps            # 依赖的节点名列表
        self.action = action        # 要执行的函数
        self.timeout = timeout      # 超时秒数
        self.result = None
        self.error = None
        self.duration = 0.0
        self.status = "pending"     # pending/running/done/failed/skipped


class DebateEngine:
    """辩论流程DAG调度器。

    用法:
        engine = DebateEngine()
        engine.add_node(DAGNode("数技源", 0, [], run_scan))
        engine.add_node(DAGNode("探源", 1, ["数技源"], run_fundamental))
        engine.run()  # 按拓扑排序自动并行
    """

    def __init__(self, max_workers: int = 4):
        self.nodes: Dict[str, DAGNode] = {}
        self.max_workers = max_workers
        self.trace_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._level_map: Dict[int, List[str]] = {}

    def add_node(self, node: DAGNode):
        """添加一个DAG节点。"""
        self.nodes[node.name] = node

    def _build_level_map(self):
        """按拓扑层级分组。"""
        self._level_map = {}
        for name, node in self.nodes.items():
            level = node.level
            if level not in self._level_map:
                self._level_map[level] = []
            self._level_map[level].append(name)

    def _can_run(self, node_name: str) -> bool:
        """检查节点是否可以执行（所有依赖已完成）。"""
        node = self.nodes[node_name]
        for dep in node.deps:
            dep_node = self.nodes.get(dep)
            if dep_node and dep_node.status != "done" and dep_node.status != "skipped":
                return False
        return True

    def _get_ready_nodes(self, level: int) -> List[str]:
        """获取某层中可执行的节点。"""
        ready = []
        for name in self._level_map.get(level, []):
            if self.nodes[name].status == "pending" and self._can_run(name):
                ready.append(name)
        return ready

    def run(self, verbose: bool = True) -> Dict[str, Any]:
        """按DAG拓扑执行全流程。

        Returns:
            {"trace_id": str, "nodes": Dict[str, Dict],
             "total_duration": float, "status": str,
             "sequential_est": float, "parallel_gain": float}
        """
        self._build_level_map()
        max_level = max(self._level_map.keys()) if self._level_map else 0
        total_start = time.time()
        sequential_duration = 0.0
        results = {}

        if verbose:
            _log(f"辩论DAG引擎启动 | 共{len(self.nodes)}节点, {max_level+1}层级, "
                 f"最大并行数{self.max_workers}")

        for level in sorted(self._level_map.keys()):
            ready = self._get_ready_nodes(level)
            if not ready:
                if verbose:
                    _log(f"Level {level}: 无待执行节点")
                continue

            if verbose:
                _log(f"Level {level}: 并行执行 {ready}")

            level_start = time.time()

            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(ready))) as executor:
                futures = {}
                for name in ready:
                    node = self.nodes[name]
                    node.status = "running"
                    fut = executor.submit(self._execute_node, name)
                    futures[fut] = name

                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        result = future.result(timeout=self.nodes[name].timeout)
                        self.nodes[name].status = "done"
                        self.nodes[name].result = result
                        results[name] = result
                        if verbose:
                            _log(f"  ✅ {name} 完成 ({self.nodes[name].duration:.1f}s)")
                    except Exception as e:
                        self.nodes[name].status = "failed"
                        self.nodes[name].error = str(e)
                        results[name] = {"error": str(e)}
                        if verbose:
                            _log(f"  ❌ {name} 失败: {e}")

            level_duration = time.time() - level_start
            sequential_duration += level_duration

        total_duration = time.time() - total_start
        nodes_status = {n: {"status": node.status, "duration": node.duration,
                            "error": node.error} for n, node in self.nodes.items()}

        parallel_gain = 1.0
        if total_duration > 0 and sequential_duration > 0:
            max_parallel = max(len(v) for v in self._level_map.values())
            parallel_gain = max_parallel / 1.0 if max_parallel >= 1 else 1.0

        if verbose:
            _log(f"DAG完成 | 耗时{total_duration:.1f}s (串行估计{sequential_duration:.1f}s)")

        report = {
            "trace_id": self.trace_id,
            "nodes": nodes_status,
            "total_duration": round(total_duration, 2),
            "sequential_est": round(sequential_duration, 2),
            "parallel_gain": round(parallel_gain, 2),
            "status": "success" if all(n.status == "done" for n in self.nodes.values()) else "partial",
            "results": results,
        }

        return report

    def _execute_node(self, name: str) -> Any:
        """执行单个节点（带重试和降级）。"""
        node = self.nodes[name]
        node.status = "running"
        max_retries = 3  # 初始执行 + 2次重试
        last_error = None
        
        for attempt in range(max_retries):
            start = time.time()
            try:
                if node.action:
                    result = node.action()
                else:
                    result = {"skipped": True, "reason": "无action"}
                node.duration = time.time() - start
                node.status = "done"
                return result
            except Exception as e:
                node.duration = time.time() - start
                last_error = str(e)
                if attempt < max_retries - 1:
                    _log(f"  ⚠️ {name} 第{attempt+1}次失败 ({e})，重试中...")
                    time.sleep(min(5, 2 ** attempt))  # 指数退避
                else:
                    node.status = "failed"
                    node.error = last_error
                    _log(f"  ❌ {name} 第{attempt+1}次失败 ({e})，启动降级...")
                    # 降级兜底：复用昨日缓存
                    fallback = self._get_fallback(name)
                    if fallback:
                        _log(f"  ↔️ {name} 降级: 复用昨日缓存")
                        node.status = "skipped"
                        return fallback
                    raise
    
    def _get_fallback(self, name: str) -> Optional[Dict]:
        """降级兜底：尝试从昨日缓存读取数据。"""
        import glob as _glob
        from datetime import timedelta as _td
        
        # 昨日日期
        yesterday = (datetime.now() - _td(days=1)).strftime("%Y%m%d")
        # 搜索可能的昨日缓存文件
        patterns = [
            f"**/{yesterday}**/full_scan*.json",
            f"**/{yesterday}**/*{name.lower()}*.json",
            f"**/memory/{yesterday}/debate_results.json",
            f"**/{yesterday}*/**/*.json",
        ]
        
        for pattern in patterns:
            matches = _glob.glob(os.path.expanduser(f"~/Documents/WorkBuddy/**/{pattern}"), recursive=True)
            if matches:
                try:
                    with open(matches[0], 'r', encoding='utf-8') as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    continue
        
        return None

    def get_report(self) -> Dict:
        """获取执行报告摘要。"""
        success = sum(1 for n in self.nodes.values() if n.status == "done")
        failed = sum(1 for n in self.nodes.values() if n.status == "failed")
        total = len(self.nodes)
        return {
            "trace_id": self.trace_id,
            "summary": f"{success}/{total} 成功, {failed} 失败",
            "nodes": {n: node.status for n, node in self.nodes.items()},
        }


def _log(msg: str):
    """DAG日志。"""
    print(f"[DAG {datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── 内置流水线工厂 ──

def build_default_pipeline(data_funcs: Dict[str, Callable]) -> DebateEngine:
    """构建默认辩论流水线。

    Args:
        data_funcs: {"scan": func, "chain": func, "event": func,
                     "fundamental": func, "technical": func,
                     "judge_prep": func, "bull": func, "bear": func,
                     "strategist": func, "risk": func, "judge_final": func,
                     "lead": func}

    Returns:
        配置好的 DebateEngine 实例
    """
    engine = DebateEngine(max_workers=4)

    # Level 0: 独立并行
    engine.add_node(DAGNode("数技源", 0, [], data_funcs.get("scan"), timeout=180))
    engine.add_node(DAGNode("链证源", 0, [], data_funcs.get("chain"), timeout=60))
    engine.add_node(DAGNode("事件日历", 0, [], data_funcs.get("event"), timeout=30))

    # Level 1: 研究员
    engine.add_node(DAGNode("探源", 1, ["数技源"], data_funcs.get("fundamental"), timeout=120))
    engine.add_node(DAGNode("观澜", 1, ["数技源"], data_funcs.get("technical"), timeout=120))

    # Level 2: 闫判官准备
    engine.add_node(DAGNode("闫判官准备期", 2, ["数技源", "链证源", "探源", "观澜", "事件日历"],
                            data_funcs.get("judge_prep"), timeout=60))

    # Level 3: 辩论双方（并行）
    engine.add_node(DAGNode("证真", 3, ["闫判官准备期"], data_funcs.get("bull"), timeout=120))
    engine.add_node(DAGNode("慎思", 3, ["闫判官准备期"], data_funcs.get("bear"), timeout=120))

    # Level 4: 策略+风控（策执远→风控明串行）
    engine.add_node(DAGNode("策执远", 4, ["证真", "慎思", "闫判官准备期"],
                            data_funcs.get("strategist"), timeout=60))
    engine.add_node(DAGNode("风控明", 4, ["策执远"], data_funcs.get("risk"), timeout=60))

    # Level 5-6: 裁决和汇总
    engine.add_node(DAGNode("闫判官裁决", 5, ["风控明", "证真", "慎思"],
                            data_funcs.get("judge_final"), timeout=60))
    engine.add_node(DAGNode("明鉴秋汇总", 6, ["闫判官裁决", "数技源", "链证源"],
                            data_funcs.get("lead"), timeout=30))

    return engine


def run_pipeline(data_funcs: Dict[str, Callable], verbose: bool = True) -> Dict:
    """一键运行完整辩论流水线。

    Args:
        data_funcs: 各阶段的函数（见 build_default_pipeline）
        verbose: 是否打印日志

    Returns:
        DAG执行报告
    """
    engine = build_default_pipeline(data_funcs)
    return engine.run(verbose=verbose)


# ════════════════════════════════════════════════
# P3-4: 多周期分层辩论（日线宏观 + 小时短线 + 信号共振）
# ════════════════════════════════════════════════


class MultiTimeframeDebate:
    """多周期辩论调度器 — 分层处理不同时间框架。"""

    def __init__(self):
        self.timeframes = {
            "daily": {
                "resolution": "1d",
                "role": "宏观趋势判断、产业链定位",
                "weight": 1.0,
            },
            "hourly": {
                "resolution": "1h",
                "role": "入场时机、支撑阻力精细调整",
                "weight": 0.6,
            },
        }

    def build_multi_tf_pipeline(self, data_funcs: Dict[str, Callable],
                                 symbols: List[str] = None) -> DebateEngine:
        """构建多周期辩论流水线。

        日线级: 全流程辩论（宏观方向）
        小时线: 简版辩论（入场时机）

        Args:
            data_funcs: 各阶段函数字典
            symbols: 品种列表

        Returns:
            多周期DAG引擎
        """
        engine = DebateEngine(max_workers=4)

        # Level 0: 多周期数据扫描
        engine.add_node(DAGNode("daily_data", 0, [],
                                data_funcs.get("daily_scan"), timeout=300))
        engine.add_node(DAGNode("hourly_data", 0, [],
                                data_funcs.get("hourly_scan"), timeout=300))

        # Level 1: 日线宏观分析
        engine.add_node(DAGNode("daily_technical", 1, ["daily_data"],
                                data_funcs.get("technical"), timeout=120))
        engine.add_node(DAGNode("daily_fundamental", 1, ["daily_data"],
                                data_funcs.get("fundamental"), timeout=120))

        # Level 2: 小时线技术分析
        engine.add_node(DAGNode("hourly_technical", 2, ["hourly_data", "daily_technical"],
                                data_funcs.get("technical"), timeout=120))

        # Level 3: 多周期辩论（以日线方向为准）
        engine.add_node(DAGNode("debaters", 3, ["daily_technical", "daily_fundamental", "hourly_technical"],
                                data_funcs.get("debate"), timeout=300))

        # Level 4: 策执远+风控
        engine.add_node(DAGNode("strategist", 4, ["debaters"],
                                data_funcs.get("strategy"), timeout=120))
        engine.add_node(DAGNode("risk", 4, ["strategist"],
                                data_funcs.get("risk"), timeout=60))

        return engine

    def resolve_conflict(self, daily_direction: int, hourly_direction: int,
                         daily_confidence: float, hourly_confidence: float) -> Dict[str, Any]:
        """解决多周期方向冲突。

        规则：
        - 日线方向优先（权重1.0）
        - 小时线仅用于入场时机精细调整
        - 方向不一致时，以日线为准，降低仓位

        Args:
            daily_direction: 日线方向（1/-1/0）
            hourly_direction: 小时线方向
            daily_confidence: 日线置信度
            hourly_confidence: 小时线置信度

        Returns:
            {"direction": int, "confidence": float, "adjustment": str}
        """
        if daily_direction == hourly_direction or daily_direction == 0:
            # 一致或日线不明确，使用小时线
            return {
                "direction": daily_direction or hourly_direction,
                "confidence": max(daily_confidence, hourly_confidence),
                "adjustment": "无冲突",
            }

        # 冲突：以日线为准，降低仓位
        return {
            "direction": daily_direction,
            "confidence": daily_confidence * 0.7,
            "adjustment": "多周期冲突，仓位降至70%",
        }
