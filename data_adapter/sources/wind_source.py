"""WindSource — 万得 Wind 金融数据源适配器。

通过 subprocess 调用 Wind MCP CLI，获取可转债估值、ETF 持仓、
宏观 EDB 指标、公告搜索等数据。

调用方式与 WestockSource 的预取缓存模式一致，但 WindSource 按需直调 CLI。

缓存策略：
  - EDB 宏观数据：12 小时（环境变量 FDT_WIND_CACHE_TTL 控制）
  - 可转债/ETF/公告：不缓存（每次最新）

数据源架构：
  data_adapter/sources/wind_source.py  ← 本文件
  data_adapter/__init__.py             ← 注册接口
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Wind CLI 路径 ──
_WIND_SKILL_DIR = (
    "c:/Users/yangd/.trae-cn/plugins/trae-remote-official/"
    "wind-aifin/0.0.2/skills/wind-mcp-skill"
)
_WIND_CLI = "node scripts/cli.mjs"

# ── 缓存配置 ──
_DEFAULT_CACHE_DIR = Path(__file__).parent / ".wind_cache"
_DEFAULT_CACHE_TTL = 43200  # 12 小时（秒）


class WindSource:
    """Wind 万得金融数据源 — 通过 MCP CLI 获取数据。"""

    def __init__(self) -> None:
        self._cache_dir: Path = _resolve_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl: int = _resolve_cache_ttl()
        logger.info(
            "[WindSource] 初始化: cache_dir=%s, cache_ttl=%ds",
            self._cache_dir, self._cache_ttl,
        )

    # ── 公开接口 ─────────────────────────────────────────

    async def get_edb(
        self,
        question: str,
        begin_date: str | None = None,
        end_date: str | None = None,
        observation: str | None = None,
    ) -> dict:
        """获取宏观 EDB 指标数据（12 小时缓存）。

        Args:
            question: 自然语言指标描述，如 "中国GDP"、"CPI同比"
            begin_date: 开始日期 yyyyMMdd，与 observation 互斥
            end_date: 结束日期 yyyyMMdd
            observation: 近 N 期（如 "10"）或 "all"，与 beginDate/endDate 互斥

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": {...}, ...}
        """
        # 检查缓存
        cache_key = f"edb_{question}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.debug("[WindSource] EDB 缓存命中: %s", question)
            return cached

        params: dict[str, str] = {"executionMode": "searchFetch", "question": question}
        if begin_date and end_date:
            params["beginDate"] = begin_date
            params["endDate"] = end_date
        elif observation:
            params["observation"] = observation

        result = await self._call("economic_data", "natural_language_get_edb_data", params)

        if result.get("isError"):
            return _error_result(f"Wind EDB 查询失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind EDB 返回空数据")

        output = {"data_grade": "PRIMARY", "source": "wind", "data": data}
        # 写入缓存
        self._write_cache(cache_key, output)
        return output

    async def get_convertible_bond(self, code: str) -> dict:
        """获取可转债估值/条款数据。

        Args:
            code: 可转债代码，如 "110045.SH"

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": {...}}
        """
        params = {"windcode": code}
        result = await self._call("bond_data", "get_bond_market_data", params)

        if result.get("isError"):
            return _error_result(f"Wind 可转债查询失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind 可转债返回空数据")

        return {"data_grade": "PRIMARY", "source": "wind", "data": data}

    async def get_fund_holdings(self, code: str) -> dict:
        """获取 ETF/基金持仓数据。

        Args:
            code: 基金代码，如 "510050.SH"

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": {...}}
        """
        params = {"windcode": code}
        result = await self._call("fund_data", "get_fund_holdings", params)

        if result.get("isError"):
            return _error_result(f"Wind 基金持仓查询失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind 基金持仓返回空数据")

        return {"data_grade": "PRIMARY", "source": "wind", "data": data}

    async def get_fund_nav(self, code: str) -> dict:
        """获取 ETF 净值/行情快照。

        Args:
            code: 基金代码，如 "588200.SH"

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "nav": float, "iopv": float, ...}
        """
        params = {"windcode": code, "indexes": "中文简称,最新成交价,IOPV,贴水率,最新净值,累计净值"}
        result = await self._call("fund_data", "get_fund_price_indicators", params)

        if result.get("isError"):
            return _error_result(f"Wind 基金净值查询失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind 基金净值返回空数据")

        return {"data_grade": "PRIMARY", "source": "wind", "data": data}

    async def get_announcements(self, query: str, top_k: int = 5) -> dict:
        """搜索上市公司公告/财报。

        Args:
            query: 搜索关键词（不含空格）
            top_k: 返回文档数量

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "announcements": [...]}
        """
        params = {"query": query.replace(" ", ""), "top_k": top_k}
        result = await self._call("financial_docs", "get_company_announcements", params)

        if result.get("isError"):
            return _error_result(f"Wind 公告搜索失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind 公告搜索返回空数据")

        return {"data_grade": "PRIMARY", "source": "wind", "announcements": data}

    async def get_financial_news(self, query: str, top_k: int = 5) -> dict:
        """搜索财经新闻。

        Args:
            query: 搜索关键词（不含空格）
            top_k: 返回文档数量

        Returns:
            dict: {"data_grade": "PRIMARY"/"UNAVAILABLE", "news": [...]}
        """
        params = {"query": query.replace(" ", ""), "top_k": top_k}
        result = await self._call("financial_docs", "get_financial_news", params)

        if result.get("isError"):
            return _error_result(f"Wind 新闻搜索失败: {result.get('error')}")

        data = _extract_content(result)
        if not data:
            return _error_result("Wind 新闻搜索返回空数据")

        return {"data_grade": "PRIMARY", "source": "wind", "news": data}

    # ── 内部方法 ─────────────────────────────────────────

    async def _call(self, server_type: str, tool_name: str, params: dict) -> dict:
        """执行 Wind CLI 调用，返回解析后的 JSON 结果。

        在子线程中同步执行 subprocess，避免阻塞事件循环。
        """
        params_json = json.dumps(params, ensure_ascii=False)

        # cmd.exe (subprocess.run shell=True on Windows) 使用双引号包裹 JSON
        # 内部双引号需要用反斜杠转义
        escaped = params_json.replace('"', '\\"')
        cmd = (
            f'cd /d "{_WIND_SKILL_DIR}" & '
            f'{_WIND_CLI} call {server_type} {tool_name} "{escaped}"'
        )

        loop = asyncio.get_event_loop()
        try:
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    shell=True,
                ),
            )
        except subprocess.TimeoutExpired:
            logger.error("[WindSource] CLI 调用超时: %s %s", server_type, tool_name)
            return {"isError": True, "error": {"code": "TIMEOUT", "message": "CLI 调用超时"}}
        except Exception as e:
            logger.error("[WindSource] CLI 调用异常: %s", e)
            return {"isError": True, "error": {"code": "RUNTIME_ERROR", "message": str(e)}}

        if proc.returncode != 0:
            try:
                err = json.loads(proc.stdout)
            except (json.JSONDecodeError, TypeError):
                err = {"code": "UNKNOWN", "message": proc.stderr or proc.stdout}
            logger.warning(
                "[WindSource] CLI 返回非零: %s %s → %s",
                server_type, tool_name, err,
            )
            return {"isError": True, "error": err}

        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.error("[WindSource] JSON 解析失败: %s", e)
            return {"isError": True, "error": {"code": "JSON_PARSE_ERROR", "message": str(e)}}

    # ── 缓存管理 ─────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        """返回缓存文件路径。"""
        safe = key.replace(" ", "_").replace("/", "_").replace("?", "")
        return self._cache_dir / f"wind_{safe}.json"

    def _read_cache(self, key: str) -> dict | None:
        """读取缓存（未过期返回 dict，过期/不存在返回 None）。"""
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            ts = cached.get("_cached_at", 0)
            if time.time() - ts < self._cache_ttl:
                return cached.get("payload")
            logger.debug("[WindSource] 缓存过期: %s", key)
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("[WindSource] 缓存读取失败: %s", e)
        return None

    def _write_cache(self, key: str, payload: dict) -> None:
        """写入缓存（带时间戳）。"""
        try:
            path = self._cache_path(key)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"_cached_at": time.time(), "payload": payload}, f, ensure_ascii=False)
        except Exception as e:
            logger.debug("[WindSource] 缓存写入失败: %s", e)


# ── 辅助函数 ─────────────────────────────────────────


def _resolve_cache_dir() -> Path:
    """解析缓存目录（环境变量 > 默认值）。"""
    env = os.environ.get("FDT_WIND_CACHE_DIR", "")
    return Path(env) if env else _DEFAULT_CACHE_DIR


def _resolve_cache_ttl() -> int:
    """解析缓存 TTL（环境变量 > 默认值）。"""
    env = os.environ.get("FDT_WIND_CACHE_TTL", "")
    if env and env.isdigit():
        return int(env)
    return _DEFAULT_CACHE_TTL


def _extract_content(result: dict) -> Any:
    """从 Wind CLI 返回的 MCP 结果中提取 content[0].text。"""
    try:
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            if text:
                return json.loads(text) if text.startswith("{") or text.startswith("[") else text
    except (json.JSONDecodeError, TypeError, IndexError, AttributeError):
        pass
    return None


def _error_result(message: str) -> dict:
    """返回统一错误格式。"""
    return {"data_grade": "UNAVAILABLE", "source": "wind", "error": message}
