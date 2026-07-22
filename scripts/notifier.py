"""FDT 告警推送 [INDEPENDENT]。

支持多种推送渠道，不依赖第三方推送。

用法:
    python scripts/notifier.py --channel wecom_bot --msg "辩论完成"
    python scripts/notifier.py --channel smtp --msg "报告已生成" --attach report.html

配置（环境变量）:
    WECOM_BOT_KEY=xxx-xxx           # 企业微信机器人 webhook key
    SMTP_HOST=smtp.qq.com
    SMTP_PORT=465
    SMTP_USER=xxx@qq.com
    SMTP_PASS=xxx                    # 授权码
    SMTP_TO=receiver@example.com     # 收件人
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent.parent


def _load_config() -> dict:
    """从环境变量加载推送配置"""
    return {
        "wecom_bot_key": os.environ.get("WECOM_BOT_KEY", ""),
        "smtp_host": os.environ.get("SMTP_HOST", ""),
        "smtp_port": int(os.environ.get("SMTP_PORT", "465")),
        "smtp_user": os.environ.get("SMTP_USER", ""),
        "smtp_pass": os.environ.get("SMTP_PASS", ""),
        "smtp_to": os.environ.get("SMTP_TO", ""),
    }


def push_wecom_bot(msg: str, config: dict) -> bool:
    """企业微信机器人 webhook 推送"""
    key = config.get("wecom_bot_key", "")
    if not key:
        print("⚠️  [wecom_bot] 未配置 WECOM_BOT_KEY，跳过")
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": msg},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("errcode") == 0:
                print(f"✅ [wecom_bot] 推送成功")
                return True
            else:
                print(f"⚠️  [wecom_bot] 推送返回错误: {result}")
                return False
    except URLError as e:
        print(f"⚠️  [wecom_bot] 网络错误: {e}")
        return False
    except Exception as e:
        print(f"⚠️  [wecom_bot] 推送失败: {e}")
        return False


def push_smtp(msg: str, config: dict, attach_path: str | None = None) -> bool:
    """邮件推送"""
    host = config.get("smtp_host", "")
    user = config.get("smtp_user", "")
    pw = config.get("smtp_pass", "")
    to = config.get("smtp_to", "")
    port = config.get("smtp_port", 465)

    if not all([host, user, pw, to]):
        print("⚠️  [smtp] SMTP 配置不完整，跳过")
        return False

    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        m = MIMEMultipart()
        m["From"] = user
        m["To"] = to
        m["Subject"] = f"FDT 报告 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        m.attach(MIMEText(msg, "plain", "utf-8"))

        if attach_path and os.path.exists(attach_path):
            with open(attach_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition",
                                f"attachment; filename={os.path.basename(attach_path)}")
                m.attach(part)

        with smtplib.SMTP_SSL(host, port, timeout=15) as s:
            s.login(user, pw)
            s.send_message(m)
        print(f"✅ [smtp] 邮件已发送至 {to}")
        return True
    except Exception as e:
        print(f"⚠️  [smtp] 发送失败: {e}")
        return False


def _build_debate_summary(workspace: str) -> str:
    """从辩论结果构建推送摘要"""
    try:
        results_path = Path(workspace) / "debate_results.json"
        if not results_path.exists():
            return f"FDT 辩论报告已生成\n工作空间: {workspace}"

        with open(results_path, encoding="utf-8") as f:
            data = json.load(f)

        verdicts = data.get("verdicts", {})
        lines = [f"## FDT 辩论报告 {datetime.now().strftime('%Y-%m-%d')}"]
        lines.append(f"")
        lines.append(f"> 辩论品种: {len(verdicts)}")

        executable = []
        for sym, v in verdicts.items():
            score = v.get("total_score", 0)
            direction = v.get("direction", "")[:20]
            conf = v.get("confidence", 0)
            action = v.get("action", "?")
            lines.append(f"- **{sym.upper()}**: {direction} (score={score}, conf={conf})")
            if conf >= 0.6:
                executable.append(sym.upper())

        if executable:
            lines.append(f"")
            lines.append(f"**可执行**: {', '.join(executable)}")

        lines.append(f"")
        lines.append(f"[详情](file:///{results_path})")
        return "\n".join(lines)
    except Exception as e:
        return f"FDT 辩论完成\n摘要生成失败: {e}"


# ── CLI ──

def main() -> int:
    ap = argparse.ArgumentParser(description="FDT 告警推送")
    ap.add_argument("--channel", choices=["wecom_bot", "smtp", "all"],
                    default="all", help="推送渠道")
    ap.add_argument("--msg", default=None, help="自定义消息（否则从 debate_results 自动生成）")
    ap.add_argument("--workspace", default=None, help="工作空间（用于自动生成摘要）")
    ap.add_argument("--attach", default=None, help="附件路径（仅 smtp）")
    ap.add_argument("--title", default=None, help="标题（仅 wecom_bot markdown）")
    args = ap.parse_args()

    config = _load_config()

    if args.msg:
        msg = args.msg
    elif args.workspace:
        msg = _build_debate_summary(args.workspace)
    else:
        msg = f"FDT 通知 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # 加标题
    if args.title and args.channel in ("wecom_bot", "all"):
        msg = f"# {args.title}\n\n{msg}"

    results = []
    if args.channel in ("wecom_bot", "all"):
        results.append(("wecom_bot", push_wecom_bot(msg, config)))
    if args.channel in ("smtp", "all"):
        results.append(("smtp", push_smtp(msg, config, args.attach)))

    all_ok = all(ok for _, ok in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
