"""fundamental-data-collector auto-generated conftest"""
import pytest, os, sys
from fdt_test_helpers import add_fdt_paths

add_fdt_paths(__file__, ['skills/fundamental-data-collector/scripts'])
"""统一 tests/ 目录版 — fundamental-data-collector"""

import sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "fundamental-data-collector")
# FDT unified sys.path
sys.path.insert(0, 'C:\\Users\\yangd\\.workbuddy\\plugins\\marketplaces\\my-experts\\plugins\\futures-debate-team\\skills/fundamental-data-collector/scripts')  # FDT unified
sys.path.insert(0, 'C:\\Users\\yangd\\.workbuddy\\plugins\\marketplaces\\my-experts\\plugins\\futures-debate-team')  # FDT unified
