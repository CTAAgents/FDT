#!/usr/bin/env python3
"""
FDT 健康检查服务器 — G12
========================

提供 HTTP /health 和 /metrics 端点，用于外部监控系统探测。

用法:
    python scripts/health_server.py              # 默认 127.0.0.1:8910
    python scripts/health_server.py --port 9000  # 指定端口

端点:
    GET /health   — 200 {"status":"ok","uptime_s":1234} 或 503
    GET /metrics  — 200 {"apm_d1_coherence":0.85,...}
    GET /         — 302 重定向到 /health
"""

import json
import os
import time
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).resolve().parent.parent
START_TIME = time.time()


# ── 健康检查逻辑 ─────────────────────────────────────

def _check_components() -> dict:
    """检查 FDT 各组件健康状态"""
    status = {"scheduler": "unknown", "pipeline": "unknown", "data_source": "unknown"}

    # 调度器 PID 文件
    pid_file = ROOT / "memory" / "daemon.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # 不发送信号，仅检查进程存在
            status["scheduler"] = "running"
        except (OSError, ValueError):
            status["scheduler"] = "stopped"

    # Pipeline 最近日志
    log_dir = Path(os.path.expanduser("~/Documents/WorkBuddy/Logs"))
    today_logs = list(log_dir.glob("fdb_*.log"))
    if today_logs:
        status["pipeline"] = "active"

    # 数据源通达信
    try:
        import requests
        r = requests.get("http://127.0.0.1:7700/", timeout=2)
        if r.status_code < 500:
            status["data_source"] = "available"
    except Exception:
        status["data_source"] = "unreachable"

    return status


def _read_apm_scores() -> dict:
    """读取最新 APM-CS 五轴评分"""
    apm_file = ROOT / "memory" / "apm_scorecard.json"
    if apm_file.exists():
        try:
            return json.loads(apm_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"note": "APM scorecard not yet generated"}


def _read_test_stats() -> dict:
    """读取测试统计"""
    tests_dir = ROOT / "tests"
    test_count = len(list(tests_dir.rglob("test_*.py")))
    return {"test_files": test_count}


# ── HTTP 处理器 ──────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):

    def _json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/health"):
            comps = _check_components()
            # P3修复（2026-07-11）：仅 "running"/"active"/"available" 视为健康；
            # "unknown"/"stopped"/"unreachable"/"unavailable" 一律判为降级 → 返回 503，
            # 使外部监控系统能真实感知组件不可用（此前 "unknown" 被误判为健康 → 恒返回 200）。
            all_ok = all(v in ("running", "active", "available")
                        for v in comps.values())
            self._json(200 if all_ok else 503, {
                "status": "ok" if all_ok else "degraded",
                "uptime_s": round(time.time() - START_TIME, 1),
                "components": comps,
            })

        elif self.path == "/metrics":
            self._json(200, {
                "uptime_s": round(time.time() - START_TIME, 1),
                "apm_scores": _read_apm_scores(),
                "tests": _read_test_stats(),
                "_server": {
                    "version": "G12-v1.0",
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(START_TIME)),
                },
            })

        else:
            self._json(404, {"error": "not found", "path": self.path})

    def log_message(self, format, *args):
        pass  # 静默，避免污染输出


# ── 主入口 ──────────────────────────────────────────

def main(port=8910):
    print(f"🏥 FDT 健康检查服务器启动: http://127.0.0.1:{port}")
    print(f"   /health  — 存活检查 + 组件状态")
    print(f"   /metrics — APM 评分 + 测试统计")
    server = HTTPServer(("127.0.0.1", port), HealthHandler)

    stop_event = threading.Event()

    def _serve():
        while not stop_event.is_set():
            server.handle_request()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🛑 停止健康服务器")
        stop_event.set()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8910
    main(port)
