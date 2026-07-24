"""
LLM 适配器层 — OpenAI 兼容协议作为统一标准，厂商差异在适配器内消化。

架构:
  业务层（OpenAI标准格式）
    ↓
  适配器调度层
    ├─ 厂商检测（从 api_base 识别目标厂商）
    ├─ 参数清洗（移除目标模型不支持的字段 → 消灭400）
    ├─ 请求正向转换（标准→厂商格式）
    └─ 响应反向归一化（厂商→OpenAI标准格式）
    ↓
  各厂商原始API

设计原则（2026-07-24）:
  1. 入参统一使用 OpenAI v1 消息格式（行业事实标准）
  2. 尽量零侵入：不改动上层业务代码的 prompt/agent 构建逻辑
  3. 参数白名单机制：每个厂商只保留支持的字段，其余自动过滤
  4. system 角色兼容：不支持 system 的模型自动拼入首条 user 消息
"""

from __future__ import annotations

import logging

logger = logging.getLogger("llm_adapter")

# ──────────────────────────────────────────────
# 1. 厂商检测
# ──────────────────────────────────────────────

VENDOR_PATTERNS: dict[str, list[str]] = {
    "deepseek": ["deepseek"],
    "openai": ["openai"],
    "baidu": ["baidu", "yiyan", "ernie"],
    "qwen": ["qwen", "tongyi", "aliyun", "dashscope"],
    "ollama": ["ollama", "localhost:11434"],
}


def detect_vendor(api_base: str) -> str:
    """从 API base URL 检测目标厂商。

    Args:
        api_base: API 基础 URL，如 ``https://api.deepseek.com/v1``。

    Returns:
        厂商标识：``"deepseek"`` | ``"openai"`` | ``"baidu"`` | ``"qwen"`` | ``"ollama"``
    """
    base_lower = api_base.lower()
    for vendor, patterns in VENDOR_PATTERNS.items():
        if any(p in base_lower for p in patterns):
            return vendor
    return "openai"  # 默认假设与 OpenAI 兼容


# ──────────────────────────────────────────────
# 2. 参数白名单（每个厂商支持的字段集合）
# ──────────────────────────────────────────────

VENDOR_SUPPORTED_PARAMS: dict[str, set[str]] = {
    "deepseek": {
        "model", "messages", "temperature", "max_tokens", "stream",
        "response_format", "top_p", "stop", "frequency_penalty",
        "presence_penalty", "logprobs", "top_logprobs",
    },
    "openai": {
        "model", "messages", "temperature", "max_tokens", "stream",
        "response_format", "top_p", "stop", "frequency_penalty",
        "presence_penalty", "logprobs", "top_logprobs", "n", "seed",
        "user", "tools", "tool_choice",
    },
    "baidu": {
        "model", "messages", "temperature", "max_output_tokens", "stream",
        "top_p", "stop",
        # 注意：百度不支持 system 角色；不支持 response_format
        # penalty_score / user_id 等为百度特有字段，不在统一标准内
    },
    "qwen": {
        "model", "messages", "temperature", "max_tokens", "stream",
        "response_format", "top_p", "stop", "frequency_penalty",
        "presence_penalty",
        # enable_search / result_format 为 qwen 特有，需要时通过 extra 传入
    },
    "ollama": {
        "model", "messages", "temperature", "stream", "top_p", "stop",
        "frequency_penalty", "presence_penalty",
        # Ollama 的 keep_alive / format / options 通过 extra 传入
    },
}


def clean_params(data: dict, vendor: str) -> dict:
    """移除目标模型不支持的参数，避免 400 ``请求体格式错误``。

    这是消灭 400 的关键手段——携带厂商不认识的字段直接返回 400。

    Args:
        data: 原始请求体 dict（OpenAI 兼容格式）。
        vendor: 厂商标识。

    Returns:
        仅保留目标厂商支持字段的请求体 dict。
    """
    supported = VENDOR_SUPPORTED_PARAMS.get(vendor, VENDOR_SUPPORTED_PARAMS["openai"])
    # 始终保留 model 和 messages
    required = {"model", "messages"}
    kept = {}
    for k, v in data.items():
        if k in required or k in supported:
            kept[k] = v
        else:
            logger.debug("[Adapter] 过滤不支持的参数 vendor=%s key=%s", vendor, k)
    return kept


# ──────────────────────────────────────────────
# 3. system 角色兼容
# ──────────────────────────────────────────────

VENDOR_NO_SYSTEM_ROLE: set[str] = {"baidu"}


def handle_system_role(messages: list[dict], vendor: str) -> list[dict]:
    """处理不支持 ``system`` 角色的模型。

    对于百度等不支持 system 的模型，将 system 内容拼接到首条 user 消息前部，
    然后删除 system 消息。

    Args:
        messages: OpenAI 格式消息列表。
        vendor: 厂商标识。

    Returns:
        处理后的消息列表。
    """
    if vendor not in VENDOR_NO_SYSTEM_ROLE:
        return messages

    sys_msg = None
    new_msgs: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            sys_msg = m.get("content", "")
        else:
            new_msgs.append(m)

    if sys_msg and new_msgs:
        new_msgs[0]["content"] = f"{sys_msg}\n\n{new_msgs[0]['content']}"
        logger.debug("[Adapter] 已将 system 角色内容拼入首条 user 消息（vendor=%s）", vendor)
    return new_msgs if new_msgs else messages


# ──────────────────────────────────────────────
# 4. 响应反向归一化
# ──────────────────────────────────────────────

STANDARD_RESPONSE_KEYS = {"choices", "usage", "model", "id", "object", "created"}


def normalize_response(response_data: dict) -> dict:
    """将厂商原始返回归一化为 OpenAI 标准格式。

    OpenAI / DeepSeek / Ollama 等使用兼容格式，直接透传。
    百度等非兼容格式在此处做字段映射。

    Args:
        response_data: 厂商原始返回的 JSON dict。

    Returns:
        OpenAI 标准格式的响应 dict。
    """
    # 对于已经是 OpenAI 兼容格式（含 choices.0.message.content），直接返回
    choices = response_data.get("choices")
    if choices and isinstance(choices, list) and len(choices) > 0:
        msg = choices[0].get("message", {})
        if "content" in msg:
            return response_data

    # ── 百度 ERNIE 格式归一化 ──
    # 百度返回格式: {"result": "...", "usage": {...}}
    result = response_data.get("result")
    if result is not None:
        return {
            "id": response_data.get("id", ""),
            "object": "chat.completion",
            "created": response_data.get("created", 0),
            "model": response_data.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": str(result)},
                    "finish_reason": "stop",
                }
            ],
            "usage": response_data.get("usage", {}),
        }

    # ── 无法识别 → 原样返回 ──
    logger.warning("[Adapter] 无法识别的响应格式: keys=%s", list(response_data.keys()))
    return response_data


# ──────────────────────────────────────────────
# 5. 统一适配器入口
# ──────────────────────────────────────────────


def adapt_request(data: dict, api_base: str) -> dict:
    """适配器主入口：将标准 OpenAI 格式请求转换为目标厂商兼容格式。

    依次执行：
    1. 厂商检测
    2. 参数清洗（白名单过滤）
    3. system 角色兼容

    Args:
        data: OpenAI 标准请求体 dict。
        api_base: API base URL。

    Returns:
        适配后的请求体 dict（可直接发给目标厂商 API）。
    """
    vendor = detect_vendor(api_base)
    adapted = clean_params(data, vendor)
    adapted["messages"] = handle_system_role(adapted.get("messages", []), vendor)

    # ── 厂商特有字段映射 ──
    # 百度: max_tokens → max_output_tokens
    if vendor == "baidu" and "max_tokens" in adapted:
        adapted["max_output_tokens"] = adapted.pop("max_tokens")

    logger.debug("[Adapter] vendor=%s params=%s", vendor, list(adapted.keys()))
    return adapted


def adapt_response(response_data: dict) -> dict:
    """适配器入口：将厂商原始返回归一化为 OpenAI 标准格式。

    Args:
        response_data: 厂商返回的原始 JSON dict。

    Returns:
        OpenAI 标准格式的响应 dict。
    """
    return normalize_response(response_data)


# ──────────────────────────────────────────────
# 6. 前置请求校验器
# ──────────────────────────────────────────────

VALID_ROLES = {"system", "user", "assistant"}


def pre_validate_request(data: dict) -> list[str]:
    """在发送请求前校验请求体结构，提前拦截常见的 400 根因。

    校验项:
      1. model 字段存在且非空
      2. messages 存在且为非空列表
      3. 每条消息 role ∈ {system, user, assistant}
      4. 首条消息 role 只能是 system 或 user
      5. content 非空
      6. 单条 content 不超过 1_000_000 chars（≈250K tokens，DeepSeek 上限约 1M tokens）

    Args:
        data: OpenAI 标准请求体 dict。

    Returns:
        违规列表（空列表表示校验通过）。
    """
    violations: list[str] = []

    if not data.get("model"):
        violations.append("model 字段缺失或为空")

    messages = data.get("messages")
    if not messages or not isinstance(messages, list):
        violations.append("messages 字段缺失或非列表")
        return violations
    if len(messages) == 0:
        violations.append("messages 列表为空")

    for i, m in enumerate(messages):
        role = m.get("role", "")
        if role not in VALID_ROLES:
            violations.append(f"messages[{i}].role='{role}' 非法，允许值: {VALID_ROLES}")
        content = m.get("content", "")
        if not content:
            violations.append(f"messages[{i}].content 为空")
        elif len(content) > 1_000_000:
            violations.append(f"messages[{i}].content 超长 ({len(content)} chars > 1_000_000)")

    if messages:
        first_role = messages[0].get("role", "")
        if first_role not in ("system", "user"):
            violations.append(f"首条消息 role='{first_role}' 非法，必须为 system 或 user")

    return violations


__all__ = [
    "detect_vendor", "clean_params", "handle_system_role",
    "normalize_response", "adapt_request", "adapt_response",
    "pre_validate_request",
]
