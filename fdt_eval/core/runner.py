"""
Eval 统一运行器 — Profile → Case 列表 → 增量判断 → 执行 → 聚合 → 闭环。

用法:
    runner = EvalRunner()
    report = runner.run(profile="ci", context=EvalContext(trace_id="..."))

    # 单 case
    result = runner.run_single("runtime.quality_inspector.p3_5", context)
"""
from __future__ import annotations

import time
from typing import Any

from fdt_eval.core.base import EvalCase, EvalContext, EvalReport, EvalResult, EvalMetric
from fdt_eval.core.registry import eval_registry
from fdt_eval.core.store import EvalStore
from fdt_eval.core.cache import check_cache, update_cache
from fdt_eval.core.action import execute_action
from fdt_eval.profiles.loader import resolve_case_ids, get_profile_options


class EvalRunner:
    """统一运行器。"""

    def __init__(self, store: EvalStore | None = None):
        self.store = store or EvalStore()

    # ── 核心入口 ──

    def run(
        self,
        profile: str = "dev",
        context: EvalContext | None = None,
        cases: list[str] | None = None,
        stage: str | None = None,
        force: bool = False,
    ) -> EvalReport:
        """执行一批评估用例。

        Args:
            profile: Profile 名称 (dev/ci/nightly/release)
            context: 评估上下文（trace_id 必填）
            cases:   指定 case_id 子集（覆盖 profile 过滤）
            stage:   过滤指定阶段
            force:   强制不缓存

        Returns:
            EvalReport
        """
        ctx = context or EvalContext(trace_id="unknown")
        t0 = time.time()

        # 1. 确定 case 列表
        case_ids = self._resolve_cases(profile, cases, stage)

        # 2. 获取 profile 选项
        opts = get_profile_options(profile)

        # 3. 执行（按 profile 选项顺序）
        results: list[EvalResult] = []
        for case_id in case_ids:
            # 缓存检查
            if not force and not opts.get("force", False):
                try:
                    instance = eval_registry.get(case_id)
                    if check_cache(instance):
                        results.append(EvalResult(
                            case_id=case_id, trace_id=ctx.trace_id,
                            stage=instance.stage,
                            status="PASS", score=instance.threshold,
                            metrics=[], detail="(缓存命中)",
                            cache_hit=True,
                        ))
                        continue
                except KeyError:
                    pass

            result = self.run_single(case_id, ctx, force=force or opts.get("force", False))
            results.append(result)

            # fail_fast: 有 FAIL 立即停止
            if opts.get("fail_fast", False) and result.status == "FAIL":
                break

        duration = (time.time() - t0) * 1000

        # 4. 聚合
        agg = self._aggregate(results)

        return EvalReport(
            profile=profile, context=ctx, results=results,
            duration_ms=duration,
            aggregate=agg,
        )

    def run_single(
        self,
        case_id: str,
        context: EvalContext,
        force: bool = False,
    ) -> EvalResult:
        """执行单个评估用例。"""
        try:
            instance = eval_registry.get(case_id)
        except KeyError:
            return EvalResult(
                case_id=case_id, trace_id=context.trace_id, stage="runtime",
                status="ERROR", score=0.0, metrics=[],
                detail=f"未注册的 case_id: {case_id}",
            )

        # 缓存检查
        if not force and check_cache(instance):
            return EvalResult(
                case_id=case_id, trace_id=context.trace_id,
                stage=instance.stage,
                status="PASS", score=instance.threshold,
                metrics=[], detail="(缓存命中)",
                cache_hit=True,
            )

        t0 = time.time()
        try:
            result = instance.run(context)
            result.duration_ms = (time.time() - t0) * 1000
        except Exception as e:
            result = EvalResult(
                case_id=case_id, trace_id=context.trace_id, stage=instance.stage,
                status="ERROR", score=0.0, metrics=[],
                detail=f"执行异常: {e}",
            )
            result.duration_ms = (time.time() - t0) * 1000

        # 更新缓存
        update_cache(instance)

        # 持久化
        self.store.save(result, profile="")

        # 闭环动作
        if result.action and result.status == "FAIL":
            execute_action(result)

        return result

    # ── 聚合记分 (§6 ARCHITECTURE.md) ──

    def _aggregate(self, results: list[EvalResult]) -> dict[str, Any]:
        """聚合记分公式:

        EvalScore = (Σ wi·si·1(si≥ti) / Σ wi·1(si≥ti)) × (1 - |failures|/|total|)
        """
        total = len(results)
        if total == 0:
            return {"score": 1.0, "passed": 0, "failed": 0, "blockers": []}

        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        failures = failed
        blockers = [
            r for r in results
            if r.status == "FAIL" and r.action and r.action.severity == "block"
        ]

        # 分子: Σ wi·si·1(si≥ti)
        numerator = 0.0
        # 分母: Σ wi·1(si≥ti)
        denominator = 0.0
        for r in results:
            wi = 1.0
            ti = 0.0
            try:
                instance = eval_registry.get(r.case_id)
                wi = instance.weight
                ti = instance.threshold
            except KeyError:
                pass

            above_threshold = 1.0 if r.score >= ti else 0.0
            numerator += wi * r.score * above_threshold
            denominator += wi * above_threshold

        # 失败惩罚
        penalty = 1.0 - (failures / total)
        score = (numerator / denominator * penalty) if denominator > 0 else (penalty * 0.9)

        # 按 stage 分解
        stage_breakdown = {}
        for r in results:
            st = r.stage
            if st not in stage_breakdown:
                stage_breakdown[st] = {"passed": 0, "failed": 0, "total": 0}
            stage_breakdown[st]["total"] += 1
            if r.status == "PASS":
                stage_breakdown[st]["passed"] += 1
            elif r.status == "FAIL":
                stage_breakdown[st]["failed"] += 1

        return {
            "score": round(score, 4),
            "total": total,
            "passed": passed,
            "failed": failed,
            "blockers": [{"case_id": b.case_id, "detail": b.detail} for b in blockers],
            "stage_breakdown": stage_breakdown,
        }

    # ── Case 解析 ──

    def _resolve_cases(
        self,
        profile: str,
        cases: list[str] | None,
        stage: str | None,
    ) -> list[str]:
        """解析最终要执行的 case_id 列表。

        优先级: cases 显式指定 → stage 过滤 → profile YAML 解析
        """
        if cases:
            return cases

        if stage:
            return [c.case_id for c in eval_registry.list(stage=stage)]

        # 从 Profile YAML 加载
        all_ids = eval_registry.all_case_ids
        resolved = resolve_case_ids(profile, all_ids)
        if resolved is not None:
            return resolved

        # 兜底: 无匹配 profile 时，dev 模式只跑 runtime.*
        if profile == "dev":
            import fnmatch
            return sorted(fnmatch.filter(all_ids, "runtime.*"))
        return sorted(all_ids)
