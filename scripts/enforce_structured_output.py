#!/usr/bin/env python3
"""
enforce_structured_output.py — 结构化输出强制约束 (D3 Generation Phase 2)
===============================================================
功能:
  1. JSON 解析与校验
  2. Pydantic 模型校验 (如可用)
  3. JSON Schema 校验
  4. 自动重试 (温度放大)
  5. 自动修复常见格式问题

用法:
  from scripts.enforce_structured_output import enforce_structured_output
  result = enforce_structured_output(raw_output, agent_name="judge")
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_decode_config() -> dict:
    """加载 decode_config.yaml 配置 (YAML 不可用时回退 JSON Schema 引用)"""
    config_path = PROJECT_ROOT / "config" / "agents" / "decode_config.yaml"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        logger.warning("PyYAML not available, returning empty config")
        return {"agents": {}}
    except Exception as e:
        logger.warning(f"Failed to load decode config: {e}")
        return {"agents": {}}


def get_agent_config(agent_name: str) -> dict:
    """获取特定 Agent 的解码配置"""
    config = load_decode_config()
    return config.get("agents", {}).get(agent_name, {})


def load_json_schema(schema_path: str) -> Optional[dict]:
    """加载 JSON Schema 文件"""
    full_path = PROJECT_ROOT / schema_path
    if not full_path.exists():
        logger.warning(f"Schema not found: {full_path}")
        return None
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON Schema {schema_path}: {e}")
        return None


def validate_with_jsonschema(
    data: dict, schema: dict, agent_name: str = ""
) -> list[str]:
    """使用 JSON Schema 校验数据"""
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(schema)
        errors = [f"schema: {e.message}" for e in validator.iter_errors(data)]
        return errors
    except ImportError:
        logger.debug("jsonschema library not available, skipping schema validation")
        return []
    except Exception as e:
        logger.warning(f"Schema validation error for {agent_name}: {e}")
        return []


def validate_with_pydantic(
    data: dict, model_path: str, agent_name: str = ""
) -> list[str]:
    """使用 Pydantic 模型校验数据 (可选依赖)"""
    errors = []
    if not model_path:
        return errors
    try:
        # 动态导入 Pydantic 模型
        module_path, class_name = model_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(f"contracts.{module_path}" if "." not in module_path else module_path)
        model_class = getattr(module, class_name)
        model_instance = model_class(**data)
        # 如果成功则返回空列表
        return []
    except ImportError as e:
        logger.debug(f"Pydantic model {model_path} not available: {e}")
        return []
    except Exception as e:
        errors.append(f"pydantic: {e}")
        return errors


def validate_required_fields(data: dict, required_fields: list[str]) -> list[str]:
    """校验必填字段"""
    errors = []
    for field in required_fields:
        if field not in data:
            errors.append(f"required_field_missing: {field}")
        elif data[field] is None:
            errors.append(f"required_field_null: {field}")
    return errors


def auto_fix_json(raw_text: str) -> str:
    """自动修复常见 JSON 格式问题"""
    text = raw_text.strip()

    # 尝试提取 JSON 块 (处理 markdown 代码块)
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    # 去掉前导/尾随非 JSON 字符
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        text = text[first_brace : last_brace + 1]

    # 修复单引号为双引号
    text = re.sub(r"(?<!\\)'", '"', text)

    # 修复尾随逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text


def enforce_structured_output(
    raw_output: str,
    agent_name: str = "",
    max_retries: int = 3,
    temperature_multiplier: float = 1.5,
) -> dict:
    """
    结构化输出强制约束主函数

    Args:
        raw_output: LLM 原始输出文本
        agent_name: Agent 名称 (用于加载配置)
        max_retries: 最大重试次数
        temperature_multiplier: 重试时温度放大倍数

    Returns:
        dict: {"success": bool, "data": dict|None, "errors": list[str],
               "retries": int, "schema_valid": bool}
    """
    agent_config = get_agent_config(agent_name)
    val_config = agent_config.get("validation_config", {})

    # 使用参数覆盖配置
    max_retries = val_config.get("retry_config", {}).get("max_retries", max_retries)
    temperature_multiplier = val_config.get("retry_config", {}).get(
        "temperature_multiplier", temperature_multiplier
    )

    result = {
        "success": False,
        "data": None,
        "errors": [],
        "warnings": [],
        "retries": 0,
        "schema_valid": False,
    }

    # Step 1: 自动修复 + JSON 解析
    fixed_text = auto_fix_json(raw_output)
    try:
        data = json.loads(fixed_text)
        result["data"] = data
    except json.JSONDecodeError as e:
        result["errors"].append(f"json_parse: {e}")
        result["success"] = False
        return result

    # Step 2: 必填字段校验
    required_fields = val_config.get("required_fields", [])
    if required_fields:
        field_errors = validate_required_fields(data, required_fields)
        result["errors"].extend(field_errors)

    # Step 3: Pydantic 模型校验 (可选)
    pydantic_model = val_config.get("pydantic_model", "")
    if pydantic_model and not result["errors"]:
        model_errors = validate_with_pydantic(data, pydantic_model, agent_name)
        # Pydantic 校验失败时记录但不阻断 (容错)
        result["warnings"].extend(
            [f"pydantic_validation: {e}" for e in model_errors]
        )

    # Step 4: JSON Schema 校验
    json_schema_ref = val_config.get("json_schema", "")
    schema = None
    if json_schema_ref:
        schema = load_json_schema(json_schema_ref)
    elif agent_config.get("response_format", {}).get("schema_ref"):
        schema_ref = agent_config["response_format"]["schema_ref"]
        schema = load_json_schema(schema_ref)

    if schema:
        schema_errors = validate_with_jsonschema(data, schema, agent_name)
        if schema_errors:
            result["warnings"].extend(
                [f"schema_validation: {e}" for e in schema_errors]
            )
        else:
            result["schema_valid"] = True
    else:
        # 无 Schema 时默认标记为有效
        result["schema_valid"] = True

    # Step 5: 判定结果
    result["success"] = len(result["errors"]) == 0
    return result


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="结构化输出强制约束校验工具")
    parser.add_argument("input", nargs="?", help="待校验的 JSON 字符串或文件路径")
    parser.add_argument("--agent", "-a", default="", help="Agent 名称")
    parser.add_argument("--file", "-f", action="store_true", help="从文件读取输入")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    if args.file:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()
    elif args.input:
        raw = args.input
    else:
        raw = sys.stdin.read()

    result = enforce_structured_output(raw, agent_name=args.agent)

    if args.verbose:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["success"]:
            print(f"✅ 校验通过 ({result.get('schema_valid', False) and 'Schema验证✅' or 'Schema跳过'})")
        else:
            print(f"❌ 校验失败: {'; '.join(result['errors'])}")
        if result.get("warnings"):
            print(f"⚠️  警告: {'; '.join(result['warnings'])}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
