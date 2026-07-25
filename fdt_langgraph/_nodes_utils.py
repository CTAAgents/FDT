"""共享工具函数 — 正则修复/字段归一化/JSON 操作/辩论协议常量。

本模块位于依赖最底层，不依赖任何业务模块。
"""

from __future__ import annotations

import json
import logging
import os
import re as _re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_ARGS_CHARS = 3000
_TRIM_MAX_ARG_CHARS = 120000

# ── 辩论协议常量 ──
ATTACK_DIMENSIONS = [
    "data_lag",
    "logic_jump",
    "ignore_chain",
    "false_breakout",
    "liquidity_trap",
]

EVIDENCE_WEIGHT_FACTORS = {
    "timeliness": 0.30,
    "reliability": 0.25,
    "historical_winrate": 0.25,
    "regime_match": 0.20,
}

DEBATE_DIVERGENCE_THRESHOLDS = {
    "skip_cross_examination": 0.2,
    "deep_debate": 0.7,
}


def _truncate_arguments_text(text: str, label: str = "") -> str:
    """截断 arguments 拼接文本，避免 context 过大。"""
    if len(text) <= _MAX_ARGS_CHARS:
        return text
    truncated = text[:_MAX_ARGS_CHARS]
    logger.warning(f"[Context] {label} arguments 超长({len(text)} chars)，截断至 {_MAX_ARGS_CHARS}")
    return truncated + f"\n\n[系统截断: {label} 已截断，原始 {len(text)} chars]"

# ── 辩论论据裁剪：单品种内6轮辩论后统一压缩 ──
_TRIM_MAX_ARG_CHARS = 120000  # 总字符阈值

# ── 代码-推理边界: stop_loss/target 精确计算（L0 硬约束） ──
_DEFAULT_RISK_MULTIPLIER = 1.5     # 止损 = ATR × 1.5
_DEFAULT_REWARD_MULTIPLIER = 2.0   # 止盈 = ATR × 2.0
_MAX_SINGLE_POSITION_PCT = 20.0    # 单品种最大仓位 (%)
_ACCOUNT_EQUITY = 1_000_000.0      # 默认账户权益
_MARGIN_RATE = 0.1                 # 默认保证金率




def _trim_arguments(state: dict) -> dict:
    """裁剪辩论论据列表，保留最新内容，丢弃最早超限部分。"""
    import logging as _lg
    for key in ["bullish_arguments", "bearish_arguments",
                "bullish_rebuttal_arguments", "bearish_rebuttal_arguments",
                "bear_final_arguments", "bull_final_arguments"]:
        raw = state.get(key, [])
        if not raw:
            continue
        total = sum(len(str(x)) for x in raw)
        if total <= _TRIM_MAX_ARG_CHARS:
            continue
        trimmed = list(raw)
        while total > _TRIM_MAX_ARG_CHARS and len(trimmed) > 1:
            removed = trimmed.pop(0)
            total -= len(str(removed))
        state[key] = trimmed
        _lg.getLogger(__name__).info(
            f"[TrimArgs] {key}: {len(raw)}\u2192{len(trimmed)} \u9879, {total} chars")
    return state

# ── 辩论协议常量 (G94: 从 debate_protocol_v2.py 内联) ──
ATTACK_DIMENSIONS = [
    "data_lag",        # 数据滞后
    "logic_jump",      # 逻辑跳跃
    "ignore_chain",    # 忽略产业链
    "false_breakout",  # 假突破
    "liquidity_trap",  # 流动性陷阱
]

EVIDENCE_WEIGHT_FACTORS = {
    "timeliness": 0.30,         # 数据时效性
    "reliability": 0.25,        # 数据源可靠性
    "historical_winrate": 0.25, # 指标历史胜率
    "regime_match": 0.20,       # 行情匹配度
}

DEBATE_DIVERGENCE_THRESHOLDS = {
    "skip_cross_examination": 0.2,   # 分歧度<0.2 跳过质证
    "deep_debate": 0.7,              # 分歧度>0.7 追加深度辩论
}



def _ensure_llm_key():
    if not os.environ.get("FDT_LLM_API_KEY"):
        if os.environ.get("OPENAI_API_KEY"):
            os.environ["FDT_LLM_API_KEY"] = os.environ["OPENAI_API_KEY"]
            logger.info("[LLM] Using OPENAI_API_KEY as FDT_LLM_API_KEY")




def _repair_json(text: str) -> str:
    """修复 LLM 输出的残缺 JSON 字符串，提高 json.loads 成功率。

    处理 BOM、markdown code fence、注释、单引号、尾随逗号、
    首尾非 JSON 文本包裹等问题。

    先尝试原始解析（避免 auto_fix_json 的单引号替换误伤撇号），
    失败后再依次应用修复步骤。
    """
    if not text or not text.strip():
        return text
    cleaned = text.strip().lstrip("\ufeff")
    import re as _re

    # Step 0: 尝试原始解析（可能已是合法 JSON，避免误伤撇号）
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # Step 1: 提取 markdown code fence 中的 JSON（如 ```json ... ```）
    fence_match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, _re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    # 查找第一个 { 和最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return text
    cleaned = cleaned[start:end+1]
    # 移除 Python/js 风格的单行注释 // 和 #
    cleaned = _re.sub(r'(?m)^\s*//.*$', '', cleaned)
    cleaned = _re.sub(r'(?m)^\s*#.*$', '', cleaned)
    # 移除尾随逗号（在单引号替换之前，避免逗号干扰）
    cleaned = _re.sub(r',\s*}', '}', cleaned)
    cleaned = _re.sub(r',\s*]', ']', cleaned)
    # 尝试将单引号替换为双引号（但只替换确为 JSON 定界符的单引号）
    # 先尝试解析，如果已经是合法 JSON 则跳过
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass
    cleaned = _re.sub(r"(?<!\\)'(?=[^:,\]\{\}\s])", '"', cleaned)
    cleaned = _re.sub(r"(?<=[:\],\{\}])\s*'\s*", '"', cleaned)
    cleaned = _re.sub(r"'\s*(?=[:\],\{\}])", '"', cleaned)
    return cleaned


# ── 字段别名归一化（方案 B：提高 LLM JSON 字段名容错） ──
FIELD_ALIASES: dict[str, list[str]] = {
    "per_symbol": ["per_symbol", "per-symbol", "persymbol", "perSymbol", "symbols", "symbol_data", "per_symbols", "per-symbols"],
    "summary": ["summary", "sumary", "overview", "conclusion", "summery", "total_summary"],
    "supply_demand": ["supply_demand", "supplydemand", "supply demand", "supply_demand_analysis", "供需"],
    "inventory": ["inventory", "inventry", "库存", "stock"],
    "profit_margin": ["profit_margin", "profitmargin", "profit margin", "利润", "margin"],
    "basis_term": ["basis_term", "basis", "basisterm", "basis term", "基差", "term_structure"],
    "macro_external": ["macro_external", "macro", "macroexternal", "宏观", "external"],
    "leading_signals": ["leading_signals", "leadingsignals", "leading signals", "signals", "领先信号"],
    "trend": ["trend", "trend_judgment", "趋势", "direction"],
    "key_levels": ["key_levels", "keylevels", "key level", "支撑阻力", "levels"],
    "volume_price": ["volume_price", "volumeprice", "volume price", "量价", "vp"],
    "divergence": ["divergence", "背离", "diverge"],
    "pattern": ["pattern", "形态", "formation", "技术形态"],
    "score": ["score", "评分", "total_score", "technical_score"],
}




def _resolve_alias(data: dict, canonical: str):
    """从 dict 中按字段别名表查找规范字段值。"""
    for alias in FIELD_ALIASES.get(canonical, [canonical]):
        if alias in data:
            return data[alias]
    return data.get(canonical)




def _normalize_per_symbol(raw: dict) -> dict:
    """对 per_symbol 中每个品种的字段做别名归一化，替换为规范字段名。"""
    normalized = {}
    for sym, data in raw.items():
        if not isinstance(data, dict):
            normalized[sym] = data
            continue
        nd = {}
        for canonical in FIELD_ALIASES:
            val = _resolve_alias(data, canonical)
            if val is not None:
                nd[canonical] = val
        # 保留不在别名表中的原始字段
        for k, v in data.items():
            if k not in nd:
                already = any(k in aliases for aliases in FIELD_ALIASES.values())
                if not already:
                    nd[k] = v
        normalized[sym] = nd
    return normalized


# ==================== 报告层调度 (v8.8.0) ====================


def _resolve_report_dir() -> Path:
    """解析报告输出目录：用户指定工作空间 > 默认工作空间 > 程序目录 fallback

    优先级：
      1. 环境变量 FDT_REPORT_WORKSPACE 指向的工作空间根目录
      2. 环境变量 FDT_DAILY_WORKSPACE（D:\\FDTWorkspace 之类）
      3. 调用方传入的临时目录（test 场景）

    注意：如果 workspace 已包含日期后缀（如 .../20260723），不再追加日期子目录。
    """
    workspace = os.environ.get("FDT_REPORT_WORKSPACE") or os.environ.get("FDT_DAILY_WORKSPACE")
    if workspace:
        import re as _re
        from datetime import datetime as _dt
        from pathlib import Path as _Path
        ws_path = _Path(workspace)
        today_str = _dt.now().strftime("%Y-%m-%d")
        today_compact = _dt.now().strftime("%Y%m%d")
        # 检查 workspace 是否已包含日期后缀（yyyy-mm-dd 或 yyyymmdd）
        # 使用正则匹配而非仅匹配今日日期，避免跨日运行时生成多余子目录
        _is_date_dir = bool(_re.match(r'^\d{4}-\d{2}-\d{2}$', ws_path.name) or
                            _re.match(r'^\d{8}$', ws_path.name))
        if ws_path.name in (today_str, today_compact) or _is_date_dir:
            report_dir = ws_path
        else:
            report_dir = ws_path / today_str
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir
    return Path(tempfile.gettempdir()) / "fdt_reports"




def _import_from_skill(skill_dir: str, module_path: str, function_name: str):
    # module_path 是 Python 模块路径（如 "scripts.analyze_chain"），需转为 OS 路径
    os_path = module_path.replace(".", "\\").replace("/", "\\")
    full_path = _SKILLS_DIR / skill_dir / (os_path + ".py")
    spec = importlib.util.spec_from_file_location(module_path.replace("/", "."), full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {full_path}")
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = [str(full_path)]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return getattr(mod, function_name)




def _import_skill_module(skill_dir: str, module_path: str):
    """用 importlib 加载技能模块（兼容目录名含连字符的情况）。

    与 _import_from_skill 的区别：返回整个模块对象而非单个函数，
    适用于需要从同一模块加载多个函数/常量的场景。
    """
    # module_path 是 Python 模块路径（如 "scripts.analyze_chain"），需转为 OS 路径
    os_path = module_path.replace(".", "\\").replace("/", "\\")
    full_path = _SKILLS_DIR / skill_dir / (os_path + ".py")
    spec = importlib.util.spec_from_file_location(module_path.replace("/", "."), full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {full_path}")
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = [str(full_path)]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod




def _inject_memory_rules(agent_name: str, context: str) -> str:
    """如果自进化系统激活了规则注入，向 context 追加记忆规则。

    读取 memory/evolution/injection_config.json，
    若 active=true 且 agent_name 在注入列表中，追加规则文本。
    进程内缓存文件状态，避免频繁 I/O。
    """
    import json
    from pathlib import Path

    config_path = Path("memory/evolution/injection_config.json")
    if not config_path.exists():
        return context

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not config.get("active"):
            return context
        if agent_name not in config.get("agents", []):
            return context
    except Exception:
        return context

    # 注入规则
    try:
        from memory.retrieval.rules_injector import get_rules_for_agent
        rules = get_rules_for_agent(agent_name)
        if rules:
            context += "\n\n【记忆规则注入】\n" + rules
    except Exception:
        pass
    return context



