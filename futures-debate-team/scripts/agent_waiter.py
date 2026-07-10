#!/usr/bin/env python3
"""
FDT Agent产出轮询器 v1.0
解决: 辩论Agent后台超时无产出，依赖不可靠的SendMessage通道

S04协议实现:
  1. spawn Agent时在prompt中指定输出文件路径
  2. spawn后轮询文件就绪(poll_file_ready, 15s间隔×60次=15min超时)
  3. 超时→触发D06降级: 返回None, 由协调员基于已有数据裁决

用法(明鉴秋协调员):
  from scripts.agent_waiter import poll_file_ready, build_spawn_file_instruction
  
  # 在spawn prompt中追加文件输出指令
  file_path = "/path/to/p4_zhengzhen.json"
  prompt += build_spawn_file_instruction(file_path, "证真")
  
  # spawn Agent后轮询等待
  result = poll_file_ready(file_path, timeout=900)
  if result:
      with open(file_path) as f:
          output = json.load(f)
  else:
      # D06降级
"""

import os, json, time, sys
from datetime import datetime
from pathlib import Path


def build_spawn_file_instruction(output_path: str, agent_name: str) -> str:
    """生成Agent输出文件指令,追加到spawn prompt末尾"""
    return f"""

## ⚠️ 文件输出要求（必须执行）
完成分析后，将完整产出写入以下文件:
  **文件路径**: `{output_path}`

写入要求:
  1. 先写 `.tmp` 后缀: `{output_path}.tmp`
  2. 写完后 rename 为正式文件名
  3. 文件必须包含有效的JSON(如果是结构化输出)或完整Markdown(如果是文本输出)
  4. 写入完成后,用 SendMessage 发送简短通知给 main: "产出已写入 {output_path}"

注意: 文件路径中的目录可能不存在,请先用 `mkdir -p` 或 `os.makedirs` 创建。
"""


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
