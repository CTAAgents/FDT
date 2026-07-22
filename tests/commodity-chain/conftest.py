"""commodity-chain auto-generated conftest"""
import pytest, os, sys

# 直接添加路径，不依赖 fdt_test_helpers（避免命名空间冲突）
_FDT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SKILL_SCRIPTS = os.path.join(_FDT_ROOT, "skills", "commodity-chain-analysis")
for p in [_SKILL_SCRIPTS]:
    if p not in sys.path:
        sys.path.insert(0, p)

