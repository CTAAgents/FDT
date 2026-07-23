"""FDT Web Dashboard [INDEPENDENT]。

独立 Web 界面，不依赖外部工具即可查看扫描结果和辩论报告。

启动:
    python scripts/webui.py                          # 开发模式 localhost:8765
    python scripts/webui.py --port 8080 --host 0.0.0.0  # 生产模式
    
    # 作为 fdt_cli.py 子命令
    python fdt_cli.py serve
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# FastAPI 导入
from fastapi import FastAPI, Request, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

ROOT = Path(__file__).resolve().parent.parent

# ── 版本号（单一真相源：pyproject.toml） ──
def _get_version() -> str:
    import re
    pp = ROOT / "pyproject.toml"
    if pp.exists():
        m = re.search(r'version\s*=\s*"([^"]+)"', pp.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "?"

FDT_VERSION = _get_version()
app = FastAPI(title="FDT Web Dashboard", version="0.1")

# ── WebSocket 实时推送 ──

class ConnectionManager:
    """管理 WebSocket 连接"""
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, msg: str):
        dead = []
        for conn in self.connections:
            try:
                await conn.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


ws_manager = ConnectionManager()


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # 发送最近日志
        log_file = ROOT / "memory" / "logs" / "scheduler.log"
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-20:]:
                await websocket.send_text(line)
        # 保持连接（等待后续推送）
        while True:
            await websocket.receive_text()  # 保持心跳
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ── 工具函数 ──

def _list_workspaces(base: str | None = None) -> list[dict]:
    """列出所有工作空间（按日期目录）"""
    scan_dirs = []
    # 检查多个候选路径
    candidates = [base] if base else []
    # FDT 默认 data/ 目录
    candidates.append(str(ROOT / "data"))
    # 用环境变量 FDT_WORKSPACE
    env_ws = os.environ.get("FDT_WORKSPACE")
    if env_ws:
        candidates.insert(0, env_ws)
    # Windows 下常见路径
    for common_path in [
        "D:/FDT/FDT",
        "C:/FDT/FDT",
        str(Path.home() / "FDT" / "FDT"),
    ]:
        if Path(common_path).exists() and common_path not in candidates:
            candidates.append(common_path)
    for candidate in candidates:
        if not candidate:
            continue
        base_path = Path(candidate)
        if not base_path.exists():
            continue
        # 查找日期子目录（YYYY-MM-DD 或 scan_YYYYMMDD）
        for d in sorted(base_path.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            date_str = ""
            if d.name.startswith("scan_"):
                date_str = d.name.replace("scan_", "")
            elif "-" in d.name and len(d.name) == 10:
                date_str = d.name.replace("-", "")
            else:
                continue
            # 避免重复
            if any(existing["date"] == date_str for existing in scan_dirs):
                continue
            json_files = list(d.glob("*.json"))
            html_files = list(d.glob("*.html"))
            scan_dirs.append({
                "date": date_str,
                "path": str(d),
                "json_count": len(json_files),
                "html_count": len(html_files),
                "has_debate": any("debate" in f.name for f in json_files),
                "has_scan": any("scan" in f.name or "full_scan" in f.name for f in json_files),
            })
    return scan_dirs


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _format_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
        if size > 1024 * 1024:
            return f"{size / 1024 / 1024:.1f}MB"
        return f"{size / 1024:.0f}KB"
    except Exception:
        return "?"


# ── HTML 模板 ──

HTML_HEADER = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FDT Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0f1117; color:#e0e0e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
.container { max-width:1200px; margin:0 auto; padding:20px; }
.header { background:linear-gradient(135deg,#1a1d28,#2a1f1f); padding:24px 32px; border-radius:12px; margin-bottom:20px; border:1px solid #f59e0b33; }
.header h1 { color:#f59e0b; font-size:1.5em; }
.header .sub { color:#888; font-size:0.85em; margin-top:4px; }
.nav { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
.nav a { color:#f59e0b; text-decoration:none; padding:6px 14px; border:1px solid #f59e0b44; border-radius:6px; font-size:0.85em; }
.nav a:hover { background:#f59e0b22; }
.card { background:#1a1d28; border-radius:10px; padding:16px 20px; margin-bottom:12px; border:1px solid #2a2d38; }
.card h3 { color:#f59e0b; font-size:1em; margin-bottom:8px; }
table { width:100%; border-collapse:collapse; font-size:0.85em; }
th { background:#252836; color:#f59e0b; padding:8px 10px; text-align:left; border-bottom:2px solid #f59e0b44; }
td { padding:6px 10px; border-bottom:1px solid #2a2d38; }
tr:hover td { background:#25283644; }
.bull { color:#22c55e; font-weight:bold; }
.bear { color:#ef4444; font-weight:bold; }
.wait { color:#f59e0b; }
.num { text-align:right; font-family:monospace; }
a { color:#60a5fa; }
pre { background:#252836; padding:12px; border-radius:6px; overflow:auto; font-size:0.8em; max-height:600px; }
</style>
</head>
<body><div class="container">
<div class="header">
<h1>FDT Web Dashboard</h1>
<div class="sub">独立运行，不依赖外部工具</div>
</div>
<div class="nav">
<a href="/">工作空间</a>
<a href="/health">健康检查</a>
<a href="/api/workspaces">API: 工作空间</a>
</div>
"""

HTML_FOOTER = "</div></body></html>"


# ── 路由 ──


@app.get("/", response_class=HTMLResponse)
async def index():
    """主页：工作空间列表"""
    workspaces = _list_workspaces()
    html = HTML_HEADER
    html += '<div class="card"><h3>工作空间</h3><table><tr><th>日期</th><th>路径</th><th>JSON</th><th>HTML</th><th>辩论</th></tr>'
    for ws in workspaces:
        has_debate = "有" if ws["has_debate"] else ""
        has_scan = "有" if ws["has_scan"] else ""
        html += f'<tr><td><a href="/workspace?path={ws["path"]}">{ws["date"]}</a></td>'
        html += f'<td style="color:#666">{ws["path"]}</td>'
        html += f'<td class="num">{ws["json_count"]}</td>'
        html += f'<td class="num">{ws["html_count"]}</td>'
        html += f'<td>{has_debate}</td></tr>'
    html += "</table></div>"

    # 最近的辩论结果
    latest_debate = None
    for ws in workspaces:
        dr_path = Path(ws["path"]) / "debate_results.json"
        if dr_path.exists():
            latest_debate = _read_json(str(dr_path))
            if latest_debate:
                html += f'<div class="card"><h3>最新辩论: {ws["date"]}</h3>'
                html += _render_verdicts(latest_debate)
                html += "</div>"
                break

    html += HTML_FOOTER
    return HTMLResponse(html)


@app.get("/workspace", response_class=HTMLResponse)
async def workspace(path: str = Query(...)):
    """工作空间详情"""
    ws_path = Path(path)
    if not ws_path.exists():
        return HTMLResponse(HTML_HEADER + "<p>路径不存在</p>" + HTML_FOOTER)

    html = HTML_HEADER
    html += f'<div class="card"><h3>工作空间: {ws_path.name}</h3>'
    html += f'<p style="color:#666">{ws_path.resolve()}</p></div>'

    # JSON 文件列表
    json_files = sorted(ws_path.glob("*.json"), key=os.path.getmtime, reverse=True)
    html += '<div class="card"><h3>JSON 文件</h3><table><tr><th>文件</th><th>大小</th><th>修改时间</th></tr>'
    for f in json_files[:20]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M")
        html += f'<tr><td><a href="/view?path={f}">{f.name}</a></td>'
        html += f'<td class="num">{_format_size(str(f))}</td>'
        html += f'<td style="color:#666">{mtime}</td></tr>'
    html += "</table></div>"

    # HTML 报告
    html_files = sorted(ws_path.glob("*.html"), key=os.path.getmtime, reverse=True)
    if html_files:
        html += '<div class="card"><h3>HTML 报告</h3><ul>'
        for f in html_files:
            html += f'<li><a href="/view?path={f}">{f.name}</a></li>'
        html += "</ul></div>"

    # 辩论结果
    dr_path = ws_path / "debate_results.json"
    if dr_path.exists():
        data = _read_json(str(dr_path))
        if data:
            html += f'<div class="card"><h3>辩论裁决</h3>{_render_verdicts(data)}</div>'

    html += HTML_FOOTER
    return HTMLResponse(html)


@app.get("/view", response_class=HTMLResponse)
async def view(path: str = Query(...)):
    """查看文件内容（仅限项目目录内）"""
    fpath = Path(path).resolve()
    if not str(fpath).startswith(str(ROOT.resolve())):
        return HTMLResponse(HTML_HEADER + "<p>不允许访问项目目录外的文件</p>" + HTML_FOOTER)
    if not fpath.exists():
        return HTMLResponse(HTML_HEADER + "<p>文件不存在</p>" + HTML_FOOTER)

    html = HTML_HEADER
    html += f'<div class="card"><h3>{fpath.name}</h3>'

    if fpath.suffix == ".html":
        # 内嵌 HTML 报告
        try:
            content = fpath.read_text(encoding="utf-8")
            html += f'<iframe srcdoc="{content.replace(chr(34),"&quot;")}" style="width:100%;height:800px;border:none;background:white;"></iframe>'
        except Exception:
            html += "<p>读取失败</p>"
    else:
        # JSON 高亮
        data = _read_json(str(fpath))
        if data:
            import json as _json
            pretty = _json.dumps(data, ensure_ascii=False, indent=2)
            html += f"<pre>{pretty}</pre>"
        else:
            try:
                content = fpath.read_text(encoding="utf-8")
                html += f"<pre>{content[:5000]}</pre>"
            except Exception:
                html += "<p>读取失败</p>"

    html += "</div>" + HTML_FOOTER
    return HTMLResponse(html)


@app.get("/health", response_class=HTMLResponse)
async def health_page():
    """健康检查页面"""
    html = HTML_HEADER
    html += '<div class="card"><h3>系统健康</h3><table>'

    # LLM 状态
    try:
        from scripts.fdt_llm import FdtLlm
        llm = FdtLlm()
        llm_ok = llm.check_available()
        html += f'<tr><td>LLM 后端</td><td>{"✅ 可用" if llm_ok else "❌ 未配置"}</td></tr>'
        if llm.api_key:
            html += f'<tr><td>LLM 模型</td><td>{llm.config["model"]}</td></tr>'
    except Exception:
        html += '<tr><td>LLM 后端</td><td>❌ 加载失败</td></tr>'

    # 数据源
    html += '<tr><td>TQ-Local</td><td>未检测</td></tr>'
    html += f'<tr><td>FDT 版本</td><td>v{FDT_VERSION}</td></tr>'

    html += '</table></div>'
    html += HTML_FOOTER
    return HTMLResponse(html)


@app.get("/logs", response_class=HTMLResponse)
async def logs_page():
    """运行日志查看"""
    log_file = ROOT / "memory" / "logs" / "scheduler.log"
    lines = []
    if log_file.exists():
        all_lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        lines = all_lines[-100:]

    html = HTML_HEADER
    html += '<div class="nav"><a href="/">首页</a><a href="/logs">日志</a></div>'
    html += '<div class="card"><h3>运行日志</h3>'
    html += f'<p style="color:#666;margin-bottom:8px;">共 {len(lines)} 条 (最近100条) | 每10秒自动刷新</p>'
    html += '<div style="background:#111;border-radius:6px;padding:12px;max-height:600px;overflow:auto;">'
    html += '<pre style="color:#0f0;font-size:0.75em;line-height:1.5;font-family:monospace;">'
    for line in lines:
        html += f"{line}\n"
    html += "</pre></div></div>"
    html += "<script>setTimeout(function(){location.reload()},10000)</script>"
    html += HTML_FOOTER
    return HTMLResponse(html)


# ── REST API ──


@app.get("/api/workspaces")
async def api_workspaces():
    """获取工作空间列表"""
    return JSONResponse(_list_workspaces())


@app.get("/api/workspace/{date}")
async def api_workspace(date: str):
    """获取指定日期的扫描和辩论数据"""
    # 搜索多个候选路径
    base = None
    for ws in _list_workspaces():
        if ws["date"] == date or ws["date"].replace("-", "") == date:
            base = Path(ws["path"])
            break
    if not base or not base.exists():
        return JSONResponse({"error": f"工作空间 {date} 不存在"}, status_code=404)

    result = {"date": date, "path": str(base), "files": []}
    for f in sorted(base.iterdir()):
        if f.is_file():
            result["files"].append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    # 辩论结果
    dr = base / "debate_results.json"
    if dr.exists():
        result["debate"] = _read_json(str(dr))

    # 扫描结果
    scan = _read_json(str(base / f"scan_{date}.json"))
    if not scan:
        scan_files = list(base.glob("scan_*.json"))
        if scan_files:
            scan = _read_json(str(scan_files[0]))
    if scan:
        ranked = scan.get("all_ranked", [])
        result["scan"] = {
            "total": len(ranked),
            "strong": len([s for s in ranked if s.get("grade") == "STRONG"]),
            "watch": len([s for s in ranked if s.get("grade") == "WATCH"]),
        }

    return JSONResponse(result)


@app.get("/api/health")
async def api_health():
    """API 健康检查"""
    try:
        from scripts.fdt_llm import FdtLlm
        llm = FdtLlm()
        llm_ok = llm.check_available()
    except Exception:
        llm_ok = False

    return JSONResponse({
        "status": "ok",
        "fdt_version": FDT_VERSION,
        "llm": llm_ok,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


# ── 辅助渲染 ──

def _render_verdicts(data: dict) -> str:
    """渲染辩论结果表格"""
    verdicts = data.get("verdicts", {})
    if not verdicts:
        return "<p>无裁决数据</p>"

    rows = ""
    for sym, v in verdicts.items():
        direction = v.get("direction", "")[:30]
        score = v.get("total_score", 0)
        conf = v.get("confidence", 0)
        action = v.get("action", "?")
        adx = v.get("adx", 0)
        rsi = v.get("rsi", 0)

        dir_class = "bull" if score > 0 else "bear" if score < 0 else ""
        conf_pct = f"{conf * 100:.0f}%" if isinstance(conf, (int, float)) and conf <= 1 else str(conf)
        rows += f'<tr><td class="{dir_class}">{sym.upper()}</td>'
        rows += f'<td>{direction}</td>'
        rows += f'<td class="num">{score}</td>'
        rows += f'<td class="num">{conf_pct}</td>'
        rows += f'<td class="wait">{action}</td>'
        rows += f'<td class="num">{adx}</td><td class="num">{rsi}</td></tr>'

    return f"""<table>
<tr><th>品种</th><th>方向</th><th>总分</th><th>置信</th><th>建议</th><th>ADX</th><th>RSI</th></tr>
{rows}
</table>"""


# ── 入口 ──

def main() -> None:
    ap = argparse.ArgumentParser(description="FDT Web Dashboard")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    ap.add_argument("--port", type=int, default=8765, help="监听端口")
    args = ap.parse_args()

    print(f"🌐 FDT Dashboard: http://{args.host}:{args.port}")
    print(f"   API: http://{args.host}:{args.port}/api/workspaces")
    print(f"   停止: Ctrl+C")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
