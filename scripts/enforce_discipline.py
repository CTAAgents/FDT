"""
FDT D4 纪律钳制器 (Discipline Enforcement)
==========================================
在裁决落库前，按 RuleChecker 的仓位上限规则 (R13/R14/R-resonance) 自动钳制
position_pct，消除辩论团自身规则违规（CLQT D4 本职：系统自纠）。

阈值与 apm_scorecard.RuleChecker 完全一致 —— 单一事实来源。

约束修正说明：
  R14(ADX≥60 → ≤3%) 对"高"置信度(基准5%)并非紧约束，真正紧的是 R13(减半=2.5%)。
  原设计 `min(cap, 3.0)` 会让 ADX≥60 品种仍留 R13 违规(3.0 > 2.5)。
  本实现取 R13/R14/R-resonance 三者最紧上限：
    - ADX > 50          → 仓位 ≤ base/2  (同时自动满足 R14 ≤3%)
    - resonance == 0    → 仓位 ≤ base*0.7
  故 ADX≥60 一律走 base/2，R13/R14 双清。

用法：
  python scripts/enforce_discipline.py            # dry-run：打印每条钳制 + 预测 D4
  python scripts/enforce_discipline.py --apply    # 回写 execution_followup.json（先备份）
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
FOLLOWUP_PATH = MEMORY_DIR / "execution_followup.json"


# ── 单一事实来源：与 RuleChecker 一致的仓位上限 ──

def _base_pos(conf: str) -> float:
    return {"高": 5.0, "中": 3.5, "低": 2.0}.get(conf, 3.5)


def capped_position(v: dict) -> float:
    """返回该裁决在 R13/R14/R-resonance 下应取的最紧合规仓位上限。"""
    conf = v.get("confidence", "中")
    base = _base_pos(conf)
    adx = float(v.get("adx", 0))
    res = v.get("resonance", 0)

    cap = base
    # R13 (ADX>50 减半) —— 同时覆盖 R14 (ADX≥60 时减半=2.5% 自动 ≤3%)
    if adx > 50:
        cap = min(cap, base / 2)
    # R-resonance (共振=0 降仓 30%)
    if res == 0:
        cap = min(cap, base * 0.7)

    return round(min(base, cap), 2)


# ── 钳制执行 ──

def clamp_verdicts(followup: dict) -> tuple:
    """遍历所有裁决，计算钳制后仓位。返回 (改动列表, 新followup)。

    仅下调（min(current, cap)），绝不提高仓位。
    遵守纪律 = 不放大风险。
    """
    changes = []
    for rec in followup.get("records", []):
        rid = rec.get("round_id", "?")
        for v in rec.get("verdicts", []):
            cur = float(v.get("position_pct", 3.5))
            cap = capped_position(v)
            new = min(cur, cap)
            if abs(new - cur) > 1e-9:
                changes.append({
                    "round_id": rid,
                    "symbol": v.get("symbol", "?"),
                    "confidence": v.get("confidence", "中"),
                    "adx": float(v.get("adx", 0)),
                    "resonance": v.get("resonance", 0),
                    "old_position": round(cur, 2),
                    "new_position": new,
                })
                v["position_pct"] = new
    return changes, followup


def _estimate_d4(violations_before: int, fixable: int) -> float:
    """粗略预测钳制后 D4：P0 全消、P1 中 R-resonance 部分消。

    与 apm_scorecard.RuleChecker.check_all 口径一致：
      total_checks = n_verdicts * 4
      penalty = P0*1.0 + P1*0.5
      D4 = 1 - penalty / total_checks
    """
    return None  # 占位，真实 D4 由 apm_scorecard.py 复算


def dry_run():
    import copy
    with open(FOLLOWUP_PATH, "r", encoding="utf-8") as f:
        followup = json.load(f)
    orig = copy.deepcopy(followup)
    all_v_before = [v for rec in orig["records"] for v in rec["verdicts"]]
    n = len(all_v_before)

    # 当前违规面（用 capped 反推哪些会被修）
    changes, _ = clamp_verdicts(followup)
    print("=" * 64)
    print("  D4 纪律钳制 — DRY RUN（不写盘）")
    print("=" * 64)
    print(f"  裁决总数: {n}")
    print(f"  预计钳制条数: {len(changes)}")
    print()
    print(f"  {'round':<22}{'symbol':<8}{'conf':<5}{'ADX':>6}{'res':>4}  {'old%':>6}→{'new%':<6}")
    print("  " + "-" * 58)
    for c in changes:
        print(f"  {c['round_id']:<22}{c['symbol']:<8}{c['confidence']:<5}"
              f"{c['adx']:>6.1f}{c['resonance']:>4}  {c['old_position']:>5.2f}→{c['new_position']:<5.2f}")

    # 用 apm_scorecard 的 RuleChecker 模拟钳制前后（before 用原始 deepcopy）
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.apm_scorecard import RuleChecker
    checker = RuleChecker()

    before = checker.check_all(all_v_before)
    clamped_v = [v for rec in followup["records"] for v in rec["verdicts"]]
    after = checker.check_all(clamped_v)
    b_p0 = sum(1 for x in before[1] if x["severity"] == "P0")
    a_p0 = sum(1 for x in after[1] if x["severity"] == "P0")
    b_p1 = sum(1 for x in before[1] if x["severity"] == "P1")
    a_p1 = sum(1 for x in after[1] if x["severity"] == "P1")
    print()
    print(f"  钳制前 D4: {before[0]:.3f}  (P0={b_p0}, P1={b_p1})")
    print(f"  钳制后 D4: {after[0]:.3f}  (P0={a_p0}, P1={a_p1})")
    print(f"  P0 消除: {b_p0 - a_p0}    P1 消除: {b_p1 - a_p1}")
    return before[0], after[0]


def apply():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = FOLLOWUP_PATH.with_suffix(f".json.bak_{ts}")
    shutil.copy2(FOLLOWUP_PATH, bak)
    print(f"  已备份: {bak}")

    with open(FOLLOWUP_PATH, "r", encoding="utf-8") as f:
        followup = json.load(f)
    changes, followup = clamp_verdicts(followup)
    with open(FOLLOWUP_PATH, "w", encoding="utf-8") as f:
        json.dump(followup, f, ensure_ascii=False, indent=2)
    print(f"  已回写 {len(changes)} 条仓位钳制 → {FOLLOWUP_PATH}")
    return len(changes)


if __name__ == "__main__":
    if "--apply" in sys.argv:
        n = apply()
        print("\n  运行 apm_scorecard.py 复算 D4 ...")
        os.system(f"{sys.executable} {PROJECT_ROOT / 'scripts' / 'apm_scorecard.py'}")
    else:
        dry_run()
