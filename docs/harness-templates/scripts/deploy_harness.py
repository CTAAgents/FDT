import os, shutil, subprocess, sys

STARTER_KIT = r"D:\HarnessStarterKit"


def deploy(project_root):
    # 确保 rhi_global_setup.py 也在部署范围内
    _rhi_setup_src = os.path.join(STARTER_KIT, "scripts", "rhi_global_setup.py")
    _rhi_setup_dst = os.path.join(project_root, "scripts", "rhi_global_setup.py")
    if os.path.exists(_rhi_setup_src) and not os.path.exists(_rhi_setup_dst):
        os.makedirs(os.path.join(project_root, "scripts"), exist_ok=True)
        shutil.copy2(_rhi_setup_src, _rhi_setup_dst)
        result.setdefault("deployed_files", []).append("scripts/rhi_global_setup.py")

    result = {"deployed_files": [], "skipped_files": [], "warnings": []}
    
    has_claude = os.path.exists(os.path.join(project_root, "CLAUDE.md"))
    has_harness = os.path.exists(os.path.join(project_root, "docs", "harness"))
    
    if has_claude and has_harness:
        result["warnings"].append("已有规范")
        return result
    
    # 1. CLAUDE.md
    dst = os.path.join(project_root, "CLAUDE.md")
    if not os.path.exists(dst):
        shutil.copy2(os.path.join(STARTER_KIT, "CLAUDE.md"), dst)
        result["deployed_files"].append("CLAUDE.md")
    else:
        result["skipped_files"].append("CLAUDE.md")
    
    # 2. docs/harness/
    hdir = os.path.join(project_root, "docs", "harness")
    os.makedirs(hdir, exist_ok=True)
    for f in ["harness-rules.yaml", "README.md"]:
        src_f = os.path.join(STARTER_KIT, "docs", "harness", f)
        dst_f = os.path.join(hdir, f)
        if not os.path.exists(dst_f):
            shutil.copy2(src_f, dst_f)
            result["deployed_files"].append(f"docs/harness/{f}")
        else:
            result["skipped_files"].append(f"docs/harness/{f}")
    
    # 2b. docs/harness/_data/
    data_dir = os.path.join(hdir, "_data")
    os.makedirs(data_dir, exist_ok=True)
    src_data = os.path.join(STARTER_KIT, "docs", "harness", "_data", "version.yaml")
    dst_data = os.path.join(data_dir, "version.yaml")
    if not os.path.exists(dst_data):
        shutil.copy2(src_data, dst_data)
        result["deployed_files"].append("docs/harness/_data/version.yaml")
    
    # 3. scripts/
    sdir = os.path.join(project_root, "scripts")
    if os.path.isdir(sdir):
        for script_name in ["pre_commit_harness_check.py", "verify_doc_consistency.py"]:
            src_s = os.path.join(STARTER_KIT, "scripts", script_name)
            dst_s = os.path.join(sdir, script_name)
            if os.path.exists(src_s) and not os.path.exists(dst_s):
                shutil.copy2(src_s, dst_s)
                result["deployed_files"].append(f"scripts/{script_name}")
            else:
                result["skipped_files"].append(f"scripts/{script_name}")
    
    return result

def verify(project_root):
    hook = os.path.join(project_root, "scripts", "pre_commit_harness_check.py")
    if not os.path.exists(hook):
        return {"status": "skipped", "message": "no hook"}
    try:
        r = subprocess.run([sys.executable, hook], capture_output=True, text=True, timeout=30)
        return {"status": "ok" if r.returncode == 0 else "warn", "output": r.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    proj = os.getcwd()
    print(f"部署规范到: {proj}\n")
    r = deploy(proj)
    for f in r["deployed_files"]:
        print(f"  [OK] {f}")
    for f in r["skipped_files"]:
        print(f"  [--] {f}")
    for w in r["warnings"]:
        print(f"  [!] {w}")
    print()
    v = verify(proj)
    print(f"验证: {v['status']}")
