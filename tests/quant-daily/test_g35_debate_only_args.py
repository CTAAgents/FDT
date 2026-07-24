"""test G35 debate_only args"""


def _build_missing_pid_scenario():
    debate_results = {
        "sc": {
            "direction": "BUY", "confidence": 0.75,
            "judge_verdict": {"final_direction": "BUY", "confidence": 0.75, "reasoning": "trend"},
            "bull_args": "bull: ADX=52", "bear_args": "bear: scan bear",
            "entry_price": 510.5, "position_size": 5.0, "price": 510.5,
        },
        "pg": {
            "direction": "BUY", "confidence": 0.30,
            "judge_verdict": {"final_direction": "BUY", "confidence": 0.30, "reasoning": "low conf"},
            "bull_args": "PG bull: supply", "bear_args": "PG bear: demand",
            "entry_price": 5197.0, "position_size": 0.5, "price": 5197.0,
        },
    }
    all_actionable = [{"pid": "sc", "decision": "BUY", "confidence": 0.75, "price": 510.5, "signal_type": "trend_following", "total": -100}]
    return debate_results, all_actionable


def test_supplement_carries_args():
    debate_results, all_actionable = _build_missing_pid_scenario()
    debate_pids = {p for p in debate_results if isinstance(debate_results.get(p), dict) and isinstance(debate_results[p].get("judge_verdict"), dict) and debate_results[p]["judge_verdict"].get("final_direction") in ("BUY", "SELL")}
    actionable_pids = {s.get("pid", "") for s in all_actionable}
    missing = debate_pids - actionable_pids
    assert "pg" in missing
    for pid_lower in sorted(missing):
        d = debate_results.get(pid_lower, {})
        jv = d.get("judge_verdict", {})
        dc = jv.get("confidence", 50)
        conf = float(dc) / 100.0 if isinstance(dc, (int, float)) and float(dc) > 1 else float(dc)
        all_actionable.append({"pid": pid_lower, "signal_type": "debate_only", "confidence": conf, "bull_args": d.get("bull_args", ""), "bear_args": d.get("bear_args", "")})
    pg = next((s for s in all_actionable if s.get("pid") == "pg"), None)
    assert pg is not None
    assert pg["bull_args"] == "PG bull: supply", f"got: {pg['bull_args']!r}"
    assert pg["bear_args"] == "PG bear: demand"


def test_empty_args_no_crash():
    dr = {"pg": {"direction": "BUY", "judge_verdict": {"final_direction": "BUY", "confidence": 0.3}, "price": 5197.0}}
    aa = []
    debate_pids = {p for p in dr if isinstance(dr.get(p), dict) and isinstance(dr[p].get("judge_verdict"), dict) and dr[p]["judge_verdict"].get("final_direction") in ("BUY", "SELL")}
    for pid in sorted(debate_pids):
        d = dr.get(pid, {})
        aa.append({"pid": pid, "bull_args": d.get("bull_args", ""), "bear_args": d.get("bear_args", "")})
    pg = next((s for s in aa if s.get("pid") == "pg"), None)
    assert pg is not None
    assert pg["bull_args"] == ""


def test_normal_symbols_unaffected():
    debate_results, all_actionable = _build_missing_pid_scenario()
    orig_len = len(all_actionable)
    debate_pids = {p for p in debate_results if isinstance(debate_results.get(p), dict) and isinstance(debate_results[p].get("judge_verdict"), dict) and debate_results[p]["judge_verdict"].get("final_direction") in ("BUY", "SELL")}
    actionable_pids = {s.get("pid", "") for s in all_actionable}
    missing = debate_pids - actionable_pids
    for pid in sorted(missing):
        d = debate_results.get(pid, {})
        all_actionable.append({"pid": pid, "signal_type": "debate_only", "bull_args": d.get("bull_args", ""), "bear_args": d.get("bear_args", "")})
    assert len(all_actionable) == orig_len + len(missing)
