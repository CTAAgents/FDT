"""
Eval 用例全局注册器 — 装饰器注册 + 按 stage/profile 过滤。

用法:
    @eval_registry.register
    class MyEval(EvalCase):
        case_id = "runtime.my_eval"
        ...

    # 列出所有 runtime 阶段的用例
    eval_registry.list(stage="runtime")
"""
from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdt_eval.core.base import EvalCase, EvalStage


class EvalRegistry:
    """全局注册器，管理所有 EvalCase 子类。"""

    def __init__(self):
        self._cases: dict[str, type[EvalCase]] = {}
        self._instances: dict[str, EvalCase] = {}

    def register(self, cls: type[EvalCase]) -> type[EvalCase]:
        """装饰器：注册一个 EvalCase 子类。"""
        if not cls.case_id:
            raise ValueError(f"{cls.__name__} 未定义 case_id")
        if cls.case_id in self._cases:
            raise ValueError(f"case_id 重复: {cls.case_id}")
        self._cases[cls.case_id] = cls
        return cls

    def get(self, case_id: str) -> EvalCase:
        """延迟初始化 + 返回单例。"""
        if case_id not in self._instances:
            cls = self._cases.get(case_id)
            if cls is None:
                raise KeyError(f"未注册的 case_id: {case_id}")
            self._instances[case_id] = cls()
        return self._instances[case_id]

    def list(self, stage: EvalStage | None = None,
             profile: str | None = None) -> list[EvalCase]:
        """按 stage 或 profile 过滤。

        Args:
            stage: 过滤指定阶段的用例
            profile: 暂未实现 Profile 文件解析，预留参数

        Returns:
            匹配的 EvalCase 实例列表
        """
        cases: list[EvalCase] = []
        for case_id in self._cases:
            instance = self.get(case_id)
            if stage and instance.stage != stage:
                continue
            cases.append(instance)
        return cases

    @property
    def all_case_ids(self) -> list[str]:
        return list(self._cases.keys())

    def __len__(self) -> int:
        return len(self._cases)


# 全局单例
eval_registry = EvalRegistry()
