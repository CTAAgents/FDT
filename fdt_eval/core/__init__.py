"""
fdt_eval.core — 框架核心，不含业务逻辑。

提供:
    base.py:     EvalCase 基类 + EvalResult TypedDict
    registry.py: 全局注册器
    runner.py:   统一运行器
    store.py:    SQLite 持久化
    action.py:   闭环动作
"""
