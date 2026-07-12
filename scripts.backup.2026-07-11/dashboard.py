#!/usr/bin/env python3
"""
FDT 实时监控看板 — G11
======================

生成自刷新 HTML 看板，展示 APM-CS 五轴评分、Agent 状态、最近辩论记录。

用法:
    python scripts/dashboard.py                     # 生成 dashboard.html
    python scripts/dashboard.py --watch             # 生成 + 后台监听文件变更
    python scripts/dashboard.py --output report.html  # 指定输出路径
"""

import json
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default or {}


def build_dashboard_data() -> dict:
    """读所有数据源，组装看板 JSON payload"""
    # APM 评分
    apm = _read_json(ROOT / "memory" / "apm_scorecard.json", {"axes": {}})

    # Agent 配置
    agents = []
    for md in sorted((ROOT / "agents").glob("*.md")):
        agents.append({"name": md.stem, "size_kb": round(md.stat().st_size / 1024, 1)})

    # 辩论记录
    journal = _read_json(ROOT / "memory" / "debate_journal.json", {"entries": []})
    recent = journal.get("entries", [])[-10:]

    # 调度器状态
    pid_file = ROOT / "memory" / "daemon.pid"
    scheduler_alive = False
    if pid_file.exists():
        try:
            import os
            os.kill(int(pid_file.read_text().strip()), 0)
            scheduler_alive = True
        except Exception:
            pass

    # 最近裁决
    followup = _read_json(ROOT / "memory" / "execution_followup.json", {"records": []})

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "apm": apm.get("axes", apm),
        "agents": agents,
        "agent_count": len(agents),
        "recent_debates": recent[-5:] if isinstance(recent, list) else [],
        "scheduler": "running" if scheduler_alive else "stopped",
        "followup_count": len(followup.get("records", [])),
    }


def render_html(data: dict) -> str:
    """渲染自刷新 HTML"""
    payload = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FDT 监控看板</title>
<style>
:root{{--bg:#0f1117;--card:#1a1d28;--text:#e0e0e0;--muted:#8890a4;--accent:#f59e0b;--green:#22c55e;--red:#ef4444;--blue:#3b82f6}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font:13px/1.6 system-ui,sans-serif;background:var(--bg);color:var(--text);padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:20px}}
.card{{background:var(--card);border-radius:12px;padding:16px}}
.card h2{{font-size:14px;font-weight:500;color:var(--accent);margin-bottom:12px}}
.row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)}}
.row:last-child{{border-bottom:none}}
.label{{color:var(--muted)}}.value{{font-weight:500}}
.bar-wrap{{height:6px;background:rgba(255,255,255,0.08);border-radius:3px;margin-top:4px}}
.bar{{height:6px;border-radius:3px;transition:width .3s}}
.ok{{color:var(--green)}}.warn{{color:var(--red)}}.info{{color:var(--blue)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:4px}}
.badge-ok{{background:rgba(34,197,94,.15);color:var(--green)}}
.badge-stopped{{background:rgba(239,68,68,.15);color:var(--red)}}
.footer{{margin-top:20px;color:var(--muted);font-size:11px}}
@keyframes pulse{{50%{{opacity:.6}}}}.live{{animation:pulse 2s infinite}}
</style></head><body>
<h1>FDT 期货辩论专家团 <span class="live" style="color:var(--accent)">◉</span></h1>
<div style="color:var(--muted);font-size:11px">数据刷新: <span id="ts">{data["generated_at"]}</span></div>
<div class="grid">
<div class="card"><h2>调度器</h2>
<div class="row"><span class="label">状态</span>
<span class="value {'ok' if data['scheduler']=='running' else 'warn'}">{'运行中' if data['scheduler']=='running' else '已停止'}</span></div>
<div class="row"><span class="label">Agent 定义</span><span class="value">{data['agent_count']} 个</span></div>
<div class="row"><span class="label">待验证裁决</span><span class="value">{data['followup_count']} 条</span></div>
</div>
<div class="card"><h2>APM-CS 五轴</h2>
{_render_apm(data['apm'])}
</div>
<div class="card" style="grid-column:1/-1"><h2>最近辩论记录</h2>
{_render_debates(data['recent_debates'])}
</div>
</div>
<div class="footer">FDT v5.6.0 · Harness Engineering G11 · 每 30 秒自动刷新</div>
<script>
setInterval(function(){{fetch('?json').then(r=>r.json()).then(d=>{{
document.getElementById('ts').textContent=d.generated_at;
}}).catch(function(){{}});}},30000);
</script>
</body></html>"""


def _render_apm(apm: dict) -> str:
    axes = [
        ("D1 一致性", "coherence", apm.get("d1_coherence", apm.get("coherence", 0))),
        ("D2 辨识力", "discrimination", apm.get("d2_discrimination", apm.get("discrimination", 0))),
        ("D3 镇定度", "composure", apm.get("d3_composure", apm.get("composure", 0))),
        ("D4 纪律", "discipline", apm.get("d4_discipline", apm.get("discipline", 0))),
        ("D5 可靠性", "reliability", apm.get("d5_reliability", apm.get("reliability", 0))),
    ]
    rows = []
    for label, key, val in axes:
        pct = min(max(round(val * 100 if isinstance(val, float) and val <= 1 else val, 1), 0), 100)
        color = "#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444"
        rows.append(f'<div class="row"><span class="label">{label}</span><span class="value">{pct}%</span></div>'
                    f'<div class="bar-wrap"><div class="bar" style="width:{pct}%;background:{color}"></div></div>')
    return "\n".join(rows)


def _render_debates(debates: list) -> str:
    if not debates:
        return '<div style="color:var(--muted)">暂无辩论记录</div>'
    rows = []
    for d in debates[-8:]:
        action = d.get("action", d.get("type", "?"))
        ts = d.get("timestamp", d.get("ts", ""))[:19]
        rows.append(f'<div class="row"><span class="label">{ts}</span><span>{action}</span></div>')
    return "\n".join(rows) or '<div style="color:var(--muted)">暂无记录</div>'


def main(output="dashboard.html"):
    data = build_dashboard_data()
    html = render_html(data)

    out_path = Path(output)
    out_path.write_text(html, encoding="utf-8")
    print(f"📊 看板已生成: {out_path.resolve()}")
    print(f"   数据时间: {data['generated_at']}")
    print(f"   调度器:   {data['scheduler']}")
    print(f"   Agent:    {data['agent_count']} 个")
    print(f"   未决裁决: {data['followup_count']} 条")


if __name__ == "__main__":
    import sys
    output = "dashboard.html"
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--output" and i + 2 < len(sys.argv):
            output = sys.argv[i + 2]
        elif arg == "--watch":
            print("🔁 看板 watch 模式（按 Ctrl+C 停止）")
            try:
                while True:
                    main(output)
                    time.sleep(30)
            except KeyboardInterrupt:
                print("\n🛑 停止监视")
                sys.exit(0)
    main(output)
