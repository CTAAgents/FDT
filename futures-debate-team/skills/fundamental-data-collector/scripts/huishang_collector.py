"""
恒生期货数据中心(徽商智汇) — 基本面数据采集器

认证方式: JWT (手机号 + 密码 + 图形验证码 -> token)
环境变量:
  HS_PHONE=手机号
  HS_PASSWORD=密码
  HS_BASE_URL=https://hyzx.hsqh.net:5443
"""

import requests
import os
import time
import json
import base64
from datetime import datetime
from pathlib import Path

REQUESTS_AVAILABLE = True
CACHE_DIR = Path(__file__).parent / "huishang_cache"
CACHE_DIR.mkdir(exist_ok=True)


class HuishangAuthError(Exception):
    pass


class HuishangCollector:
    """徽商智汇基本面数据采集器"""

    def __init__(self):
        self.base_url = os.getenv("HS_BASE_URL", "https://hyzx.hsqh.net:5443")
        self.phone = os.getenv("HS_PHONE", "")
        self.password = os.getenv("HS_PASSWORD", "")
        self.token = None
        self.token_file = CACHE_DIR / "token.json"
        self._load_token()

    # ── Token管理 ──

    def _load_token(self):
        if self.token_file.exists():
            try:
                data = json.loads(self.token_file.read_text(encoding="utf-8"))
                if data.get("expires_at", 0) > time.time():
                    self.token = data["token"]
            except Exception:
                pass

    def _save_token(self, token: str, expires_in: int = 86400):
        self.token = token
        data = {"token": token, "expires_at": time.time() + expires_in}
        self.token_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ── 图形验证码 ──

    def _get_captcha(self) -> tuple:
        """获取验证码图片并保存到本地,返回(图片路径, uuid)"""
        r = requests.get(f"{self.base_url}/api/captchaImage", timeout=15, verify=False)
        if r.status_code != 200:
            raise HuishangAuthError(f"获取验证码失败: HTTP {r.status_code}")
        data = r.json()
        # 徽商智汇返回格式: {"msg":"操作成功","img":"base64...","uuid":"xxx"}
        captcha_base64 = data.get("img") or data.get("data", {}).get("img", "")
        uuid = data.get("uuid") or data.get("data", {}).get("uuid", "")
        if not captcha_base64 or not uuid:
            raise HuishangAuthError(f"验证码返回格式异常: {str(data)[:200]}")
        # 保存图片
        img_path = CACHE_DIR / f"captcha_{uuid}.png"
        if "," in captcha_base64:
            captcha_base64 = captcha_base64.split(",")[1]
        img_bytes = base64.b64decode(captcha_base64)
        img_path.write_bytes(img_bytes)
        return str(img_path), uuid

    # ── 登录 ──

    def login(self, captcha_text: str = None, uuid: str = None) -> bool:
        """
        登录获取JWT Token。

        首次登录需要 captcha_text + uuid (由外部输入)。
        Token有效期内自动复用。
        """
        if self.token:
            return True
        if not captcha_text:
            img_path, uuid = self._get_captcha()
            raise HuishangAuthError(
                f"需要人工输入验证码。验证码图片: {img_path}\n"
                f"请打开图片查看验证码后,调用 collector.login(captcha_text='xxx', uuid='{uuid}')"
            )
        r = requests.post(
            f"{self.base_url}/api/login",
            json={
                "phone": self.phone,
                "password": self.password,
                "captcha": captcha_text,
                "uuid": uuid,
            },
            timeout=15,
            verify=False,
        )
        if r.status_code != 200:
            raise HuishangAuthError(f"登录失败: HTTP {r.status_code}")
        data = r.json()
        token = data.get("token") or data.get("data", {}).get("token", "")
        if not token:
            raise HuishangAuthError(f"登录返回无token: {str(data)[:200]}")
        self._save_token(token)
        return True

    # ── 数据获取 ──

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """带token的API请求,自动重登录"""
        if not self.token:
            self.login()
        headers = {"Authorization": f"Bearer {self.token}"}
        headers.update(kwargs.pop("headers", {}))
        r = requests.request(
            method, f"{self.base_url}{path}",
            headers=headers, timeout=30, verify=False, **kwargs
        )
        if r.status_code == 401:
            # Token过期,清理缓存后让上游重新login
            self.token = None
            if self.token_file.exists():
                self.token_file.unlink()
            raise HuishangAuthError("Token已过期,请重新 login()")
        return r.json()

    def get_data(self, endpoint: str, params: dict = None) -> dict:
        """
        通用数据查询接口。

        Args:
            endpoint: API路径,如 /api/v1/inventory
            params: 查询参数,如 {"variety":"RB","start":"2026-01-01","end":"2026-07-07"}

        Returns:
            解析后的JSON数据
        """
        return self._request("GET", endpoint, params=params)


# ── 便捷函数 ──

def probe_endpoints():
    """登录后探测可用API端点"""
    collector = HuishangCollector()
    if not collector.token:
        print("需要先登录")
        return
    # 尝试常见路径
    for path in ["/api/user/info", "/api/variety/list", "/api/v1/variety/list",
                  "/api/data/inventory", "/api/fundamental/list",
                  "/api/v1/fundamental/RB", "/api/v1/inventory/RB"]:
        try:
            r = collector._request("GET", path)
            print(f"[{list(r.keys())[:3]}] {path}")
        except Exception as e:
            print(f"[ERR] {path}: {e}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        probe_endpoints()
    else:
        print("Huishang Collector Module loaded")
        print("用法:")
        print("  首次登录: 运行后查看验证码图片,调用 login(captcha_text, uuid)")
        print("  探测端点: python huishang_collector.py probe")
