"""测试配置 — 统一 tests/ 目录版"""

import sys, os

# 从 tests/commodity-chain/ → 项目根 → skills/commodity-chain-analysis/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "commodity-chain-analysis")
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")

if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
if SCRIPTS_DIR in sys.path:
    sys.path.remove(SCRIPTS_DIR)
