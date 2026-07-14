"""健康钩子 [INDEPENDENT]。

读最新 ``reports/run_report_{date}.json``，触发告警规则，产出 ``alerts_{date}.json`` 并打印。
告警规则（阈值保守，避免误报）：
    1. 0 信号：n_signals == 0（可能数据层全挂）
    2. 全源 dead：source_health 全部非 closed
    3. 有信号却 0 辩论：n_signals > 0 但 n_triggered_debates == 0
    4. 验证器错误率过高：errors 中含 validator 相关错误
    5. 运行错误非空：errors 列表非空

退出码 0=无告警，1=有告警（供自动化 push_to_wechat 推送）。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

__all__ = ["run_health_check"]


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_health_check(date_str: str | None = None) -> int:
    d = date_str or date.today().strftime("%Y-%m-%d")
    rp = _root() / "reports" / f"run_report_{d}.json"
    alerts: list[dict] = []
    if not rp.exists():
        print(f"⚠️ 无运行报告 {rp}，跳过健康检查")
        return 0
    try:
        report = json.loads(rp.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ 运行报告解析失败: {e}")
        return 0

    n_signals = report.get("n_signals")
    n_debates = report.get("n_triggered_debates")
    source_health = report.get("source_health") or {}
    errors = report.get("errors") or []

    if n_signals is not None and n_signals == 0:
        alerts.append({"level": "warn", "rule": "zero_signals",
                       "msg": "本次扫描 0 信号，可能数据层异常"})
    if source_health and all(v != "closed" for v in source_health.values()):
        alerts.append({"level": "critical", "rule": "all_sources_dead",
                       "msg": f"全部数据源不可用: {source_health}"})
    if n_signals and n_signals > 0 and n_debates == 0:
        alerts.append({"level": "warn", "rule": "signals_no_debate",
                       "msg": f"有 {n_signals} 个信号但未触发辩论"})
    if any("validator" in str(e.get("stage", "")).lower() or "validator" in str(e.get("msg", "")).lower()
           for e in errors):
        alerts.append({"level": "warn", "rule": "validator_errors",
                       "msg": "验证器管道存在错误"})
    if errors:
        alerts.append({"level": "warn", "rule": "run_errors",
                       "msg": f"运行期错误 {len(errors)} 条"})

    out = _root() / "reports" / f"alerts_{d}.json"
    try:
        out.write_text(json.dumps({
            "date": d, "n_alerts": len(alerts), "alerts": alerts,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
    if alerts:
        print(f"🚨 健康告警 {len(alerts)} 条:")
        for a in alerts:
            print(f"  [{a['level']}] {a['rule']}: {a['msg']}")
        return 1
    print(f"✅ 健康检查通过（{d}）")
    return 0


if __name__ == "__main__":
    sys.exit(run_health_check())
