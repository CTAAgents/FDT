"""测试配置 — 确保相对导入正确"""
import sys, os

# 正确方式：将scripts的父目录加入path，然后以 scripts.xxx 方式导入
SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SCRIPTS_DIR = os.path.join(SKILL_DIR, 'scripts')

# 父目录优先，scripts作为包导入
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
if SCRIPTS_DIR in sys.path:
    sys.path.remove(SCRIPTS_DIR)  # 如果直接添加了scripts，去掉它（防止包冲突）
