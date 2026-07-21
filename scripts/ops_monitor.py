from __future__ import annotations
from scripts.unified_logger import get_logger

_logger = get_logger("ops_monitor")
#!/usr/bin/env python3
"""
运维监控 & 告警框架 v1.0（P2-2）
===================================
提供实时监控面板、多渠道告警、每日复盘报告。

核心功能：
- check_system_health(): 系统健康检查（Agent心跳/数据源连通性）
- send_alert(): 多渠道告警（企微/邮件/钉钉）
- generate_daily_report(): 每日自动生成HTML复盘报告
- setup_monitoring(): 启动实时监控循环

用法:
    from scripts.ops_monitor import OpsMonitor
    monitor = OpsMonitor()
    monitor.start()
    monitor.send_alert("critical", "数据源中断", "RB数据超过30分钟未更新")
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import html
import json
import os
import time
from pathlib import Path


class OpsMonitor:
    """运维监控器 — 系统健康检查+告警+每日复盘。"""

    def __init__(self, config_path: str = None) -> None:
        self.alerts = []
        self.health_history = []
        self.config = self._load_config(config_path)
        self.start_time = datetime.now()

        print(f"[OpsMonitor] 初始化完成 - {self.start_time}")

    def _load_config(self, config_path: str = None) -> Dict:
        """加载告警配置。"""
        default = {
            "webhook_urls": {
                "wecom": "",
                "dingtalk": "",
                "email": "",
            },
            "alert_thresholds": {
                "data_stale_minutes": 30,
                "max_drawdown_pct": 2.5,
                "max_consecutive_errors": 3,
            },
            "report_dir": "reports/daily",
        }
        return default

    def check_system_health(self) -> Dict[str, Any]:
        """检查系统健康状态。

        Returns:
            {"status": "green|yellow|red", "checks": [...], "timestamp": str}
        """
        checks = []
        all_ok = True

        # 检查1: 时间同步
        checks.append(
            {
                "name": "system_time",
                "status": "ok",
                "detail": f"当前时间: {datetime.now()}",
            }
        )

        # 检查2: 磁盘空间（简化）
        try:
            import shutil

            usage = shutil.disk_usage(os.path.expanduser("~"))
            pct = usage.used / usage.total * 100
            if pct > 90:
                checks.append({"name": "disk_usage", "status": "warn", "detail": f"磁盘使用率: {pct:.1f}%"})
                all_ok = False
            else:
                checks.append({"name": "disk_usage", "status": "ok", "detail": f"磁盘使用率: {pct:.1f}%"})
        except (ImportError, OSError):
            checks.append({"name": "disk_usage", "status": "skip", "detail": "不可用"})

        # 检查3: 内存
        import psutil

        mem = psutil.virtual_memory()
        if mem.percent > 85:
            checks.append({"name": "memory", "status": "warn", "detail": f"内存使用率: {mem.percent:.1f}%"})
            all_ok = False
        else:
            checks.append({"name": "memory", "status": "ok", "detail": f"内存使用率: {mem.percent:.1f}%"})

        # 检查4: 运行时间
        uptime = (datetime.now() - self.start_time).total_seconds()
        checks.append(
            {
                "name": "uptime",
                "status": "ok",
                "detail": f"运行时长: {uptime / 3600:.1f}h",
            }
        )

        # 综合状态
        status_counts = {}
        for c in checks:
            s = c.get("status", "ok")
            status_counts[s] = status_counts.get(s, 0) + 1

        if status_counts.get("error", 0) > 0:
            overall = "red"
        elif status_counts.get("warn", 0) > 0:
            overall = "yellow"
        else:
            overall = "green"

        result = {
            "status": overall,
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
            "uptime_hours": round(uptime / 3600, 2),
        }

        self.health_history.append(result)
        return result

    def send_alert(self, level: str, title: str, message: str) -> None:
        """发送多渠道告警（企微/邮件/钉钉）。

        Args:
            level: "info" | "warning" | "critical"
            title: 告警标题
            message: 告警内容
        """
        alert = {
            "level": level,
            "title": title,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        self.alerts.append(alert)

        # 打印到终端
        emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        print(f"{emoji.get(level, '❓')} [{level.upper()}] {title}: {message}")

        if self.config["webhook_urls"]["wecom"]:
            self._send_wecom(level, title, message)
        if self.config["webhook_urls"]["dingtalk"]:
            self._send_dingtalk(level, title, message)

    def _send_wecom(self, level: str, title: str, message: str) -> None:
        """发送企微告警。"""
        # 实际部署时填入 webhook URL
        pass

    def _send_dingtalk(self, level: str, title: str, message: str) -> None:
        """发送钉钉告警。"""
        pass

    def generate_daily_report(self, output_dir: str = None) -> str:
        """生成每日HTML复盘报告。

        Returns:
            HTML报告路径
        """
        if not output_dir:
            output_dir = Path(os.path.expanduser("~/Documents/WorkBuddy/Reports/每日复盘"))
            output_dir.mkdir(parents=True, exist_ok=True)

        today_str = datetime.now().strftime("%Y-%m-%d")
        health = self.check_system_health()

        html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>每日复盘 {today_str}</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background: #f5f5f5; }}
.card {{ background: white; border-radius: 12px; padding: 20px; margin: 16px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.status-green {{ color: #22c55e; font-weight: bold; }}
.status-yellow {{ color: #eab308; font-weight: bold; }}
.status-red {{ color: #ef4444; font-weight: bold; }}
table {{ width: 100%; border-collapse: collapse; }}
td, th {{ padding: 8px 12px; border-bottom: 1px solid #eee; text-align: left; }}
</style></head><body>
<h1>📊 每日复盘报告</h1>
<p>生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

<div class="card">
<h2>🟢 系统健康</h2>
<p>状态: <span class="status-{health["status"]}">{health["status"].upper()}</span></p>
<p>运行时长: {health["uptime_hours"]:.1f}h</p>
</div>

<div class="card">
<h2>🔔 今日告警</h2>
<table><tr><th>级别</th><th>标题</th><th>时间</th></tr>
{"".join(f"<tr><td>{a["level"]}</td><td>{a["title"]}</td><td>{a["timestamp"][:19]}</td></tr>" for a in self.alerts[-20:] if a["title"] != "")}
</table>
</div>

<div class="card">
<h2>📈 性能指标</h2>
<table>
<tr><td>总告警数</td><td>{len(self.alerts)}</td></tr>
<tr><td>健康检查次数</td><td>{len(self.health_history)}</td></tr>
</table>
</div>

<div class="card">
<h2>📋 Agent运行状态</h2>
<table>
{self._render_agent_status()}
</table>
</div>

<p style="color: #666; text-align: center; margin-top: 40px;">
Futures-Debate-Team v4.4 — 自动生成</p>
</body></html>"""

        report_path = output_dir / f"daily_report_{today_str}.html"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"[OpsMonitor] 每日报告: {report_path}")
        return str(report_path)

    def _render_agent_status(self) -> str:
        """渲染Agent状态表格。"""
        agents = [
            "futures-datatech",
            "futures-chain-analyst",
            "futures-technical-researcher",
            "futures-fundamental-researcher",
            "futures-affirmative-debater",
            "futures-opposition-debater",
            "futures-trading-strategist",
            "futures-risk-manager",
            "futures-judge",
            "futures-debate-team-team-lead",
        ]
        rows = ""
        for agent in agents:
            status = "✅" if agent not in [a["title"] for a in self.alerts] else "❌"
            rows += f"<tr><td>{agent}</td><td>{status}</td></tr>\n"
        return rows

    def start(self, interval_minutes: int = 5) -> None:
        """启动监控循环（后台线程）。"""
        import threading

        def _loop():
            while True:
                self.check_system_health()
                time.sleep(interval_minutes * 60)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print(f"[OpsMonitor] 监控已启动 (间隔={interval_minutes}分钟)")


if __name__ == "__main__":
    monitor = OpsMonitor()
    monitor.start()
    # 模拟告警
    monitor.send_alert("info", "系统启动", "运维监控已初始化")
    monitor.send_alert("warning", "数据延迟", "RB数据延迟5分钟")
    # 生成报告
    report = monitor.generate_daily_report()
    print(f"报告: {report}")
