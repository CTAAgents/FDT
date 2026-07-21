import os, shutil, subprocess, sys

STARTER_KIT = r"d:\Programs\FDT\harness-starter-kit"

def deploy(project_root):
    result = {"deployed_files": [], "skipped_files": [], "warnings": []}
    
    has_claude = os.path.exists(os.path.join(project_root, "CLAUDE.md"))
    has_harness = os.path.exists(os.path.join(project_root, "docs", "harness"))
    
    if has_claude and has_harness:
        result["warnings"].append("已有规范")
        return result
    
    src = os.path.join(STARTER_KIT, "CLAUDE.md")
    dst = os.path.join(project_root, "CLAUDE.md")
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
        result["deployed_files"].append("CLAUDE.md")
    else:
        result["skipped_files"].append("CLAUDE.md")
    
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
    
    sdir = os.path.join(project_root, "scripts")
    if os.path.isdir(sdir):
        src_h = os.path.join(STARTER_KIT, "scripts", "pre_commit_harness_check.py")
        dst_h = os.path.join(sdir, "pre_commit_harness_check.py")
        if not os.path.exists(dst_h):
            shutil.copy2(src_h, dst_h)
            result["deployed_files"].append("scripts/pre_commit_harness_check.py")
        else:
            result["skipped_files"].append("scripts/pre_commit_harness_check.py")
    
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
