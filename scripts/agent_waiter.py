#!/usr/bin/env python3
"""
FDT Agent产出轮询器 v1.1 — 独立传输层

File Transport Layer v1 实现:
  1. Agent 在 prompt 中指定输出文件路径
  2. Agent 写完文件后，编排层轮询文件就绪 (poll_file_ready)
  3. 超时 → 触发降级

独立模式：不依赖 SendMessage，基于文件轮询。
"""
from __future__ import annotations

import os
import json
import time
import sys
import hashlib
from datetime import datetime
from pathlib import Path


def build_spawn_file_instruction(output_path: str, agent_name: str, trace_id: str = "") -> str:
    """生成 Agent 输出文件指令（File Transport Layer v1，无 SendMessage 依赖）"""
    return f"""

## ⚠️ 文件输出要求（必须执行）
完成分析后，将完整产出写入以下文件:
  **文件路径**: `{output_path}`

写入要求:
  1. 先写 `.tmp` 后缀: `{output_path}.tmp`
  2. 写完后 rename 为正式文件名
  3. 使用标准信封格式包裹输出:
     {{
       "envelope": {{
         "agent": "{agent_name}",
         "version": "3.1",
         "generated_at": "YYYY-MM-DD HH:MM",
         "phase": "p3",
         "status": "completed"
       }},
       "data": {{ ... 实际分析内容 ... }}
     }}
  4. 写入完成后，文件就绪（编排层轮询检测）

注意: 文件路径中的目录可能不存在，请先用 mkdir -p 或 os.makedirs 创建。
"""


def make_envelope(agent: str, data: dict, phase: str = "p3",
                  trace_id: str = "", version: str = "3.1") -> dict:
    """构建标准输出信封"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    env = {
        "envelope": {
            "agent": agent,
            "version": version,
            "generated_at": now,
            "phase": phase,
            "status": "completed",
        },
        "data": data,
    }
    if trace_id:
        env["envelope"]["trace_id"] = trace_id
    # 可选 checksum
    try:
        data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        env["envelope"]["checksum"] = hashlib.sha256(data_str.encode()).hexdigest()[:8]
    except Exception:
        pass
    return env


def atomic_write(path: str, content: str) -> None:
    """原子写入文件"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def from_config(config: dict | None = None) -> dict:
    """
    从 team_config.json 读取 Agent 产出的熔断参数。

    优先级: 传入 config > team_config.json > 硬编码默认值

    Args:
        config: 可选的 team_config 字典，不传则自动读取文件

    Returns:
        {"timeout": int, "poll_interval": int, "stable_seconds": int, "max_retries": int}
    """
    defaults = {"timeout": 900, "poll_interval": 15, "stable_seconds": 5, "max_retries": 2}

    if config is None:
        try:
            root = Path(__file__).resolve().parent.parent
            tc_path = root / "config" / "team_config.json"
            if tc_path.exists():
                with open(tc_path, encoding="utf-8") as f:
                    config = json.load(f)
        except Exception:
            config = {}

    waiter_cfg = config.get("agent_waiter", {}) if config else {}

    return {
        "timeout": waiter_cfg.get("timeout_seconds", defaults["timeout"]),
        "poll_interval": waiter_cfg.get("poll_interval_seconds", defaults["poll_interval"]),
        "stable_seconds": waiter_cfg.get("stable_seconds", defaults["stable_seconds"]),
        "max_retries": waiter_cfg.get("max_retries", defaults["max_retries"]),
    }


def poll_file_ready(
    filepath: str,
    timeout: int = 900,
    stable_seconds: int = 5,
    poll_interval: int = 15,
) -> bool:
    """
    S04: 轮询文件就绪
    
    Args:
        filepath: 目标文件路径（正式文件，非.tmp）
        timeout: 超时秒数，默认900(15分钟)
        stable_seconds: 文件size需稳定秒数，默认5秒
        poll_interval: 轮询间隔秒数，默认15秒
    
    Returns:
        True if file ready, False if timeout
    """
    tmp_path = filepath + ".tmp"
    deadline = time.time() + timeout
    last_size = -1
    stable_since = None

    while time.time() < deadline:
        # 检查.tmp文件是否存在(说明Agent正在写)
        if os.path.exists(tmp_path):
            time.sleep(poll_interval)
            continue
        
        # 检查正式文件
        if os.path.exists(filepath):
            try:
                sz = os.path.getsize(filepath)
            except OSError:
                time.sleep(poll_interval)
                continue
            
            if sz > 0:
                if sz == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stable_seconds:
                        return True
                else:
                    last_size = sz
                    stable_since = None
        
        time.sleep(poll_interval)
    
    return False


def wait_for_agent_output(
    filepath: str,
    agent_name: str,
    timeout: int = 900,
) -> dict | None:
    """
    等待Agent产出文件并返回解析后的内容
    
    D06降级: 超时返回None, 协调员基于已有数据裁决
    D3 Generation: 成功读取后自动调用 enforce_structured_output 校验（非阻断）
    
    Args:
        filepath: 产出文件路径
        agent_name: Agent名称(用于日志)
        timeout: 超时秒数
    
    Returns:
        Parsed JSON dict if success, None if timeout
    """
    print(f"[AgentWaiter] 等待 {agent_name} 产出: {filepath}", file=sys.stderr)
    
    ready = poll_file_ready(filepath, timeout=timeout)
    
    if not ready:
        print(f"[AgentWaiter] {agent_name} 超时({timeout}s), 触发D06降级", file=sys.stderr)
        return None
    
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        
        # ── D3 Generation: 结构化输出校验（非阻断） ──
        _validate_agent_output(content, agent_name)
        
        # 尝试解析JSON fence
        import re
        m = re.search(r'```json\s*(.*?)```', content, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        
        # 尝试直接解析JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 返回原始文本
        return {"raw_text": content, "agent": agent_name}
        
    except Exception as e:
        print(f"[AgentWaiter] 读取{agent_name}产出失败: {e}", file=sys.stderr)
        return None


def _validate_agent_output(content: str, agent_name: str) -> None:
    """D3 Generation: 结构化输出校验。非阻断，失败仅记录 metrics。"""
    try:
        from scripts.enforce_structured_output import enforce_structured_output
        from scripts.generation_metrics import GenerationMetrics

        result = enforce_structured_output(content, agent_name=agent_name)
        if not result.get("success"):
            errors = result.get("errors", [])
            print(f"[DecodeControl] {agent_name} 结构化输出校验失败: {errors[:2]}", file=sys.stderr)
            metrics = GenerationMetrics()
            metrics.record(agent_name, success=False, latency_ms=0, schema_valid=False)
        else:
            metrics = GenerationMetrics()
            metrics.record(agent_name, success=True, latency_ms=0, schema_valid=True)
    except Exception as e:
        print(f"[DecodeControl] {agent_name} 校验异常(非阻断): {e}", file=sys.stderr)
