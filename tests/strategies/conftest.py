"""Strategies 测试路径配置 — 使用 pytest hook。"""
import sys, os


def pytest_load_initial_conftests(early_config, parser, args):
    """在 pytest 加载初始 conftest 时执行，早于任何测试收集。"""
    _add_path()


def pytest_configure(config):
    """在配置阶段执行，早于测试收集。"""
    _add_path()


def _add_path():
    qd = r"C:\Users\yangd\.workbuddy\plugins\marketplaces\my-experts\plugins\futures-debate-team\skills\quant-daily\scripts"
    if qd not in sys.path:
        sys.path.insert(0, qd)
