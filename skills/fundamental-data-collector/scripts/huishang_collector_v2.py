"""
徽商智汇(恒生期货数据中心) — 基本面数据采集器 v2

API端点:
  POST /api/topicCharts/list  — 搜索数据主题(按名称关键词)
  GET  /api/topicCharts/{id}  — 获取主题详情(含ECharts数据)

Token管理:
  从浏览器F12→Application→LocalStorage→tokenKey复制,
  设置环境变量 HS_TOKEN,或保存到 huishang_cache/token.txt
  失效后重新从浏览器复制
"""

import requests, json, os, re, base64, time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

CACHE_DIR = Path(__file__).parent / "huishang_cache"
CACHE_DIR.mkdir(exist_ok=True)
TOKEN_FILE = CACHE_DIR / "token.txt"

BASE_URL = os.getenv("HS_BASE_URL", "https://hyzx.hsqh.net:5443")


class HuishangCollector:
    """徽商智汇基本面数据采集器"""

    def __init__(self):
        self.token = self._load_token()

    def _load_token(self) -> Optional[str]:
        t = os.getenv("HS_TOKEN", "")
        if t:
            return t
        if TOKEN_FILE.exists():
            return TOKEN_FILE.read_text(encoding="utf-8").strip()
        return None

    def save_token(self, token: str):
        TOKEN_FILE.write_text(token, encoding="utf-8")
        self.token = token

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/DataCenter",
        }

    # ── 搜索数据主题 ──

    def search(self, keyword: str, page: int = 1, size: int = 50) -> List[Dict]:
        """按关键词搜索数据主题

        Args:
            keyword: 搜索关键词,如"螺纹钢""库存""产量"
            page: 页码(默认1)
            size: 每页条数(默认50)

        Returns:
            [{"id": int, "name": str, "queryIds": str, "source": str, ...}, ...]
        """
        r = requests.post(
            f"{BASE_URL}/api/topicCharts/list",
            headers=self._headers,
            json={"pageNum": page, "pageSize": size, "name": keyword},
            timeout=15, verify=False,
        )
        d = r.json()
        return d.get("rows", [])

    def get_all_categories(self) -> List[str]:
        """获取所有二级分类(库名)列表"""
        r = requests.post(
            f"{BASE_URL}/api/topicCharts/list",
            headers=self._headers,
            json={"pageNum": 1, "pageSize": 1},
            timeout=15, verify=False,
        )
        rows = r.json().get("rows", [])
        libs = set()
        for row in rows:
            lib = row.get("libName", "")
            if lib:
                libs.update(l.split() for l in lib.split(","))
        # 实际需要更完整的分类列表,此处做个示例
        return sorted(libs)

    # ── 获取数据详情 ──

    def get_detail(self, topic_id: int) -> Optional[Dict]:
        """获取数据主题详情(含实际数值)

        Args:
            topic_id: 主题ID

        Returns:
            {name, source, queryIds, options(包含series和xAxis数据)}
        """
        r = requests.get(
            f"{BASE_URL}/api/topicCharts/{topic_id}",
            headers=self._headers,
            timeout=15, verify=False,
        )
        d = r.json()
        tc = d.get("topicChart")
        if tc:
            return tc
        return None

    def parse_echart_data(self, topic: Dict) -> Optional[Dict]:
        """将ECharts options解析为结构化数据

        Args:
            topic: get_detail() 返回的主题

        Returns:
            {name, source, data: [{year, date, value}]}
        """
        opts_str = topic.get("options", "{}")
        if not opts_str:
            return None
        try:
            opts = json.loads(opts_str) if isinstance(opts_str, str) else opts_str
        except json.JSONDecodeError:
            return None

        series = opts.get("series", [])
        xaxis = opts.get("xAxis", [{}])
        xdata = xaxis[0].get("data", []) if xaxis else []

        result = {
            "name": topic.get("name", ""),
            "source": topic.get("source", ""),
            "query_ids": topic.get("queryIds", ""),
            "id": topic.get("id"),
            "data_points": [],
        }

        for s in series:
            sname = s.get("name", "")
            sdata = s.get("data", [])
            for i, val in enumerate(sdata):
                if val is not None:
                    xval = xdata[i] if i < len(xdata) else f"index{i}"
                    result["data_points"].append({
                        "series": sname,
                        "date": xval,
                        "value": val,
                    })
        return result

    # ── 按品种批量获取基本面数据 ──

    def get_fundamentals(self, variety: str) -> Dict:
        """获取某品种的所有基本面数据

        Args:
            variety: 品种名称(中文),如"螺纹钢""纯碱""甲醇"

        Returns:
            {variety, topics: [{name, source, data_points}]}
        """
        topics = self.search(variety)
        result = {"variety": variety, "topics": []}
        for t in topics:
            detail = self.get_detail(t["id"])
            if detail:
                parsed = self.parse_echart_data(detail)
                if parsed:
                    result["topics"].append(parsed)
        return result


# ── 便捷函数 ──

def probe_variety(variety: str):
    """探测某品种的可用数据"""
    c = HuishangCollector()
    if not c.token:
        print("❌ 无Token,请先设置 HS_TOKEN 环境变量")
        return
    topics = c.search(variety)
    print(f"\n【{variety}】找到 {len(topics)} 个数据主题:")
    for t in topics:
        print(f"  ID={t['id']:5d}  {t['name']}  (来源:{t.get('source','?')})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        probe_variety(sys.argv[1])
    else:
        print("用法: python huishang_collector_v2.py <品种名称>")
        print("示例: python huishang_collector_v2.py 螺纹钢")
