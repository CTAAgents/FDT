#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDT Agent 统一输出入口 (方案D · 2026-07-14)
=============================================

设计意图：
  Agent 不碰 JSON 字符串，只传 Python dict → write() 负责 schema 校验 + 序列化 + 写文件。
  从源头消灭 F05 JSON引号冲突+三类不同 schema 输出不一致问题。

用法（Agent spawn prompt 结尾直接调用）：
  import sys; sys.path.insert(0, r"FDT_ROOT/scripts")
  from agent_output import write

  write("p5_judge", "pb", {
      "symbol": "pb",
      "verdict": "bear",
      "confidence": "高",
      "bull_score": 25,
      "bear_score": 75,
      "winner": "bearish",
      "reasoning": "...",
      "score_breakdown": {"technical": {"bull":20,"bear":80}},
  })

退出码：0=成功，1=校验失败
"""

import json
import os
import re
import sys
from pathlib import Path, PureWindowsPath

# ── 工作空间推导 ──
# 优先级：FDT_WORKSPACE 环境变量 > 当前目录含 scan/信号文件 > 未设置(由下游拼接)
_FDT_WORKSPACE_ENV = os.environ.get("FDT_WORKSPACE", "")

_WIN_DRIVE_RE = re.compile(r"^/([a-zA-Z])/")  # 匹配 /d/foo/bar


def _to_win_path(p: str) -> str:
    """Git Bash /d/foo → D:\\foo。"""
    if sys.platform != "win32":
        return p
    m = _WIN_DRIVE_RE.match(p)
    if m:
        return m.group(1).upper() + ":\\" + p[3:].replace("/", "\\")
    if ":" in p:
        return str(PureWindowsPath(p))
    return p


def _resolve_workspace() -> str:
    """优先 env，其次自动探测，最后返回空（由调用方拼路径）。"""
    if _FDT_WORKSPACE_ENV:
        return _to_win_path(_FDT_WORKSPACE_ENV)
    return ""


WORKSPACE = _resolve_workspace()


# ─────────────────────────────────────────────
# Schema 定义：字段名 → (type, 约束规则)
# 约束规则：
#   - None / 缺失: 只做类型检查
#   - tuple/list: 枚举（值必须在集合内）
#   - range: 数值范围
# ─────────────────────────────────────────────
SCHEMAS: dict[str, dict[str, tuple]] = {
    "p3_technical": {
        "agent": (str, ("technical_researcher",)),
        "symbol": (str,),
        "generated_at": (str,),
        "support_levels": (list,),
        "resistance_levels": (list,),
        "poc": (dict,),
    },
    "p4_bullish": {
        "agent": (str, ("bullish_analyst",)),
        "symbol": (str,),
        "direction": (str, ("bull", "bear")),
        "generated_at": (str,),
        "key_arguments": (list,),
    },
    "p4_bearish": {
        "agent": (str, ("bearish_analyst",)),
        "symbol": (str,),
        "direction": (str, ("bull", "bear")),
        "generated_at": (str,),
        "key_arguments": (list,),
    },
    "p5_judge": {
        "agent": (str, ("judge",)),
        "symbol": (str,),
        "generated_at": (str,),
        "verdict": (str, ("bull", "bear", "neutral")),
        "confidence": (str, ("高", "中", "低")),
        "bull_score": (int, range(0, 101)),
        "bear_score": (int, range(0, 101)),
        "winner": (str, ("bullish", "bearish")),
        "reasoning": (str,),
        "score_breakdown": (dict,),
    },
    "p5_coherence": {
        "agent": (str, ("coherence_auditor",)),
        "symbol": (str,),
        "coherence_score": (int, range(0, 101)),
        "rationale": (str,),
    },
    "p5_trading_plan": {
        "agent": (str, ("trading_planner",)),
        "symbol": (str,),
        "generated_at": (str,),
        "direction": (str, ("bull", "bear")),
        "action": (str, ("buy_long", "sell_short")),
        "timeframe": (str,),
        "contract": (str,),
        "entry": (dict,),
        "stop_loss": (dict,),
        "targets": (list,),
        "position_pct": (float, range(0, 101)),
        "risk_reward_ratio": (float,),
    },
    "p5_risk_review": {
        "agent": (str, ("risk_manager",)),
        "symbol": (str,),
        "generated_at": (str,),
        "risk_level": (str, ("高", "中", "低")),
        "veto": (bool,),
        "risk_items": (list,),
        "recommendation": (str,),
    },
    "p0_judge_directive": {
        "agent": (str, ("judge_initial",)),
        "generated_at": (str,),
        "chains_to_analyze": (list,),
        "debate_symbols": (list,),
        "reasoning": (str,),
    },
}

# 阶段→文件名映射
PHASE_FILENAME = {
    "p3_technical": "p3_technical_{symbol}.json",
    "p4_bullish": "p4_bullish_{symbol}.json",
    "p4_bearish": "p4_bearish_{symbol}.json",
    "p5_judge": "p5_judge_{symbol}.json",
    "p5_coherence": "p5_coherence_{symbol}.json",
    "p5_trading_plan": "p5_trading_plan_{symbol}.json",
    "p5_risk_review": "p5_risk_review_{symbol}.json",
    "p0_judge_directive": "p0_judge_directive.json",
}


# ── key_arguments 子项校验 ──
_P4_ARG_REQUIRED = ["id", "claim", "evidence", "reasoning", "family", "confidence"]


def _validate_schema(phase: str, params: dict) -> list[str]:
    """返回校验错误列表，空列表=通过。"""
    schema = SCHEMAS.get(phase)
    if not schema:
        return [f"未知阶段: {phase}"]

    errors: list[str] = []
    for field, spec in schema.items():
        typ = spec[0]
        constraint = spec[1] if len(spec) > 1 else None

        if field not in params:
            errors.append(f"缺少必需字段: {field}")
            continue

        val = params[field]
        if not isinstance(val, typ):
            errors.append(f"{field} 应为 {typ.__name__}，实际 {type(val).__name__}")
            continue

        if constraint is not None:
            if isinstance(constraint, (list, tuple)):
                # 枚举约束
                if val not in constraint:
                    errors.append(f"{field} 值 {val!r} 不在允许列表 {constraint} 中")
            elif isinstance(constraint, range):
                lo, hi = constraint.start, constraint.stop
                if not (lo <= val < hi):
                    errors.append(f"{field} 值 {val} 超出范围 [{lo}, {hi})")

    # key_arguments 结构校验（仅 p4_bullish / p4_bearish 阶段）
    if phase in ("p4_bullish", "p4_bearish"):
        args = params.get("key_arguments", [])
        if not isinstance(args, list) or len(args) == 0:
            errors.append("key_arguments 必须为非空列表")
        else:
            for i, a in enumerate(args):
                miss = [k for k in _P4_ARG_REQUIRED if k not in a]
                if miss:
                    errors.append(f"key_arguments[{i}] 缺少字段: {miss}")

    # targets 结构校验（p5_trading_plan）
    if phase == "p5_trading_plan":
        targets = params.get("targets", [])
        if not isinstance(targets, list) or len(targets) == 0:
            errors.append("targets 必须为非空列表")

    # score_breakdown 结构校验（p5_judge）
    if phase == "p5_judge":
        sd = params.get("score_breakdown", {})
        if not isinstance(sd, dict):
            errors.append("score_breakdown 必须为 dict")

    return errors


def write(phase: str, symbol: str, params: dict, workspace: str = "") -> str:
    """Agent 唯一输出入口。校验 schema → 确认路径 → json.dump → 返回路径。

    Args:
        phase: 阶段标识，如 "p5_judge"
        symbol: 品种代码，如 "pb"
        params: 待写入的 Python dict（由 Agent 拼好传入）
        workspace: 工作空间路径。为空则从 FDT_WORKSPACE env 取，仍为空则抛错。

    Returns:
        写入文件的绝对路径（Windows 风格）
    """
    # 1. schema 校验
    errors = _validate_schema(phase, params)
    if errors:
        msg = "\n  ".join(errors)
        sys.stderr.write(f"[agent_output] ❌ {phase}/{symbol} 校验失败:\n  {msg}\n")
        sys.exit(1)

    # 2. 组装路径
    ws = workspace or WORKSPACE
    if not ws:
        raise RuntimeError(
            "agent_output.write() 缺少 workspace 参数且 $FDT_WORKSPACE 未设置"
        )
    ws = _to_win_path(ws)
    ws_path = Path(ws)

    fmt = PHASE_FILENAME.get(phase)
    if not fmt:
        raise RuntimeError(f"未知阶段 phase={phase}")
    filename = fmt.format(symbol=symbol)

    out_path = ws_path / filename

    # 3. 序列化 + 写入（json.dump 负责转义，永不出现裸引号）
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)

    sys.stderr.write(f"[agent_output] ✅ {phase}/{symbol} → {out_path}\n")
    return str(out_path)


# ─────────────────────────────────────────────
# 生成 spawn prompt 片段（供 run_debate.py plan 调用）
# import agent_output; write("p5_judge", "{symbol}", {...})
# ─────────────────────────────────────────────
def make_write_code(phase: str, symbol: str) -> str:
    """生成 Agent 可直接执行的 Python 代码片段。

    用法：在 spawn prompt 末尾追加此片段，Agent 只需填充 params dict。
    """
    schema = SCHEMAS.get(phase, {})
    # 提取必需字段名列表
    required_fields = list(schema.keys())
    # 排除自动填充字段
    auto_fields = {"agent", "symbol", "generated_at"}
    manual_fields = [f for f in required_fields if f not in auto_fields]

    lines = [
        "# ── 使用统一输出入口（方案D）──",
        "import sys; sys.path.insert(0, r'{}')".format(
            str(Path(__file__).resolve().parent)
        ),
        "from agent_output import write as _fdt_write",
        "",
        f"_fdt_write({phase!r}, {symbol!r}, {{",
    ]

    for f in manual_fields:
        schema_spec = schema.get(f, (object,))
        typ = schema_spec[0]
        constraint = schema_spec[1] if len(schema_spec) > 1 else None

        if typ == str and constraint:
            if isinstance(constraint, (list, tuple)):
                lines.append(f"    {f!r}: '',  # 可选值: {'/'.join(constraint)}")
            else:
                lines.append(f"    {f!r}: '',  # str")
        elif typ == int:
            if isinstance(constraint, range):
                lines.append(f"    {f!r}: 0,  # int ({constraint.start}-{constraint.stop-1})")
            else:
                lines.append(f"    {f!r}: 0,  # int")
        elif typ == float:
            lines.append(f"    {f!r}: 0.0,  # float")
        elif typ == bool:
            lines.append(f"    {f!r}: False,  # bool")
        elif typ == list:
            lines.append(f"    {f!r}: [],  # list")
        elif typ == dict:
            lines.append(f"    {f!r}: {{}},  # dict")
        else:
            lines.append(f"    {f!r}: None,  # {typ.__name__}")

    lines.append("})")
    lines.append("# ──")
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI 用法：python agent_output.py write p5_judge pb '{"symbol":"pb",...}'
    if len(sys.argv) >= 4 and sys.argv[1] == "write":
        phase = sys.argv[2]
        symbol = sys.argv[3]
        params = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        workspace = sys.argv[5] if len(sys.argv) > 5 else ""
        write(phase, symbol, params, workspace)
    else:
        print(__doc__)
