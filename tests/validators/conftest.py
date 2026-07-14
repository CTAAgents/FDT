"""Validators 测试统一配置。"""
import sys, os

# FDT 路径自举
test_dir = os.path.dirname(os.path.abspath(__file__))
fdt_root = os.path.dirname(os.path.dirname(test_dir))
if fdt_root not in sys.path:
    sys.path.insert(0, fdt_root)

# quant-daily scripts/ 路径
qd_scripts = os.path.join(fdt_root, "skills", "quant-daily", "scripts")
if qd_scripts not in sys.path:
    sys.path.insert(0, qd_scripts)
# FDT scripts/ 路径（run_debate.py 等）
scripts_dir = os.path.join(fdt_root, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
