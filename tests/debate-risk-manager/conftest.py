"""debate-risk-manager auto-generated conftest"""
import os
import sys

from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__)
"""统一 tests/ 目录版 — debate-risk-manager"""


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "debate-risk-manager")
# FDT unified sys.path
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))  # FDT unified
sys.path.insert(0, PROJECT_ROOT)  # FDT unified
