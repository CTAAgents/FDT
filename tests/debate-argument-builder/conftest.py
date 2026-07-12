"""统一 tests/ 目录版 — debate-argument-builder"""

import sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "debate-argument-builder")
sys.path.insert(0, SKILL_DIR)
