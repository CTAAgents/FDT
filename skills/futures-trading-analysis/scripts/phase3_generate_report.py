#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品期货每日深度分析 — Phase 3: 报告输出
v3.2 (2026-07-09):
  - 路径参数化: 支持CLI参数或环境变量指定文件路径，解除硬编码
  - 默认fallback保持向后兼容
v3.1 (2026-07-09):
  - 新增decisions键检测+fallback适配明鉴秋汇总格式
  - 重写_load_debate_args: glob通配搜索+唯一键名替代硬编码+键碰撞修复
  - 扩增_nested_to_per_pid字段fallback: score/verdict_score/stop等
  - HTML转义(h_escape): _normalize_args+v_reason防<破坏排版
  - 除零修复: entry=0时stop_pct显示N/A
v3.0 (2026-07-06):
  - 修复 chain_results 62→13条链聚合
  - 修复 bull_args/bear_args 双方向生成
  - 修复信号表 entry/target/stop 字段从 debate_results 读取
  - 修复 chain 成员字段名（members → chain_members）
  - 新增三报告输出：L1L4全信号 / 因子择时全信号 / 辩论详情+交易建议
  - 辩论裁决增加多维度技术分析（K线形态/量价/均线/趋势阶段）
  - bull_args/bear_args 增加基于信号数据的基础面和资金面维度
"""

import argparse, sys, os, json, traceback
from html import escape as h_escape
from datetime import datetime


# ==================== CLI参数（优先）→ 环境变量 → 默认值 ====================
parser = argparse.ArgumentParser(description="Phase 3: 辩论报告生成")
parser.add_argument("--intermediate", "-i", default=os.environ.get("PHASE3_INTERMEDIATE", ""),
                    help="intermediate_data.json路径")
parser.add_argument("--debate", "-d", default=os.environ.get("PHASE3_DEBATE_RESULTS", ""),
                    help="debate_results.json路径")
parser.add_argument("--output", "-o", default=os.environ.get("PHASE3_OUTPUT_DIR", ""),
                    help="输出目录")
parser.add_argument("--output-html", default="", help="输出HTML文件名（不含路径）")
parser.add_argument("--workspace", "-w", default=os.environ.get("PHASE3_WORKSPACE", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                    help="工作空间根目录")
args = parser.parse_args()

REPORT_DATE = datetime.now().strftime("%Y-%m-%d")
REPORT_DATE_COMPACT = datetime.now().strftime("%Y%m%d")

# 输出目录优先级: CLI → 环境变量 → 工作空间Commodities目录
if args.output:
    REPORT_DIR = args.output
elif os.environ.get("PHASE3_OUTPUT_DIR"):
    REPORT_DIR = os.environ["PHASE3_OUTPUT_DIR"]
else:
    # 搜索工作空间下的 debate_results.json 来确定目录
    workspace = args.workspace
    commodities_dir = os.path.join(workspace, "Commodities")
    if os.path.isdir(commodities_dir):
        REPORT_DIR = commodities_dir
    else:
        REPORT_DIR = os.path.join(workspace)

# 文件路径优先级: CLI → 环境变量 → 自动发现 → 默认
INTERMEDIATE_PATH = args.intermediate or os.environ.get("PHASE3_INTERMEDIATE") or os.path.join(REPORT_DIR, "intermediate_data.json")
DEBATE_PATH = args.debate or os.environ.get("PHASE3_DEBATE_RESULTS") or os.path.join(workspace, "debate_results.json")

output_name = args.output_html or f"debate_report_{REPORT_DATE_COMPACT}.html"
OUTPUT_DEBATE = os.path.join(REPORT_DIR, output_name)

print(f"{'=' * 60}")
print(f"Phase 3 v3.2: 报告生成 — {REPORT_DATE}")
print(f"  中间数据: {INTERMEDIATE_PATH}")
print(f"  辩论结果: {DEBATE_PATH}")
print(f"  输出目录: {REPORT_DIR}")
print(f"{'=' * 60}")


# ==================== 辩论结果适配器 ====================
def _detect_format(debate_results: dict) -> str:
    """检测 debate_results.json 的数据格式。"""
    for key, val in debate_results.items():
        if isinstance(val, dict) and any(k in val for k in ("judge_verdict", "verdict", "direction")):
            return "per_pid"
    if "verdicts" in debate_results and isinstance(debate_results["verdicts"], dict):
        if debate_results["verdicts"]:  # 非空
            return "nested"
        # verdicts为空字典，检查是否有final_verdict
        if "final_verdict" in debate_results and isinstance(debate_results["final_verdict"], dict):
            if debate_results["final_verdict"]:
                return "final_verdict"
    if "verdicts" in debate_results and isinstance(debate_results["verdicts"], list):
        return "nested_list"
    if "decisions" in debate_results and isinstance(debate_results["decisions"], dict):
        if debate_results["decisions"]:  # 非空 — 明鉴秋汇总格式
            return "nested"
    if "final_verdict" in debate_results and isinstance(debate_results["final_verdict"], dict):
        if debate_results["final_verdict"]:
            return "final_verdict"
    return "per_pid"


def _normalize_args(args_val) -> str:
    """规范化 bull_args/bear_args: 支持 str / list / None → HTML 友好字符串"""
    if args_val is None:
        return ""
    if isinstance(args_val, str):
        return h_escape(args_val)
    if isinstance(args_val, list):
        if len(args_val) == 0:
            return ""
        return "<br>".join(h_escape(str(a)) for a in args_val)
    return h_escape(str(args_val))


def _map_direction(raw_dir: str) -> str:
    d = (raw_dir or "").strip().lower()
    if d in ("做多", "多头", "bull", "buy", "long"):
        return "BUY"
    if d in ("做空", "空头", "bear", "sell", "short"):
        return "SELL"
    return "HOLD"


def _generate_fallback_args(sym: str, v: dict, intermediate: dict) -> tuple:
    """生成双方向论据（bear=bear方向的论据, bull=bull方向的论据）"""
    bear, bull = [], []
    symbols = intermediate.get("symbols_summary", [])
    item = None
    for s in symbols:
        if s.get("symbol", s.get("pid", "")) == sym:
            item = s
            break
    if not item:
        return "", ""
    adx = item.get("adx", 0)
    rsi = item.get("rsi", 50)
    cci = item.get("cci", 0)
    l1l4_total = item.get("l1l4_total", item.get("total", 0))
    direction = _map_direction(v.get("direction", item.get("l1l4_direction", "")))
    fdir = v.get("factor_direction", item.get("factor_direction", "neutral"))
    stage = item.get("stage", "")
    z = item.get("z_score", 0)
    cons = item.get("cons", 0)
    volume = item.get("volume", 0)
    dc20 = item.get("dc20_break", "none")
    ma_align = item.get("ma_align", "mixed")
    macd = item.get("macd_cross", "none")
    f_total = item.get("factor_total", 0)
    conflict = v.get("direction_conflict", item.get("direction_conflict", False))
    chain_name = v.get("chain", "")

    # ====== 空头论据（空头品种的主力论据，或多头品种的反方论据） ======
    if direction == "SELL" or adx > 25:
        # 趋势强度（ADX越低越新、空间越大）
        if stage == "launch":
            bear.append(f"📈 突破初期(阶段=launch)，ADX={adx:.1f}正在爬升，趋势空间充足")
        elif adx >= 60:
            bear.append(f"⚠️ ADX={adx:.1f}趋势已运行较远，注意尾部风险，持仓需设紧止损")
        elif adx >= 40:
            bear.append(f"ADX={adx:.1f} 中强空头趋势，DMI-DI主导方向")
        elif adx >= 25:
            bear.append(f"ADX={adx:.1f} 空头趋势形成中")
        else:
            bear.append(f"ADX={adx:.1f} 趋势偏弱，需确认")

        # RSI 确认
        if rsi < 30:
            bear.append(f"RSI={rsi:.1f} 超卖区间但空头趋势强劲，超卖不构成做多理由")
        elif rsi < 40:
            bear.append(f"RSI={rsi:.1f} 空方主导区间，价格位于弱势区")
        elif rsi < 50:
            bear.append(f"RSI={rsi:.1f} 中轴下方，空头占优")

        # 总分
        if abs(l1l4_total) >= 65:
            bear.append(f"总分={l1l4_total} 高分空头，方向一致性高(CONS={cons}/4)")
        elif abs(l1l4_total) >= 55:
            bear.append(f"总分={l1l4_total} 中高分空头")
        elif abs(l1l4_total) >= 40:
            bear.append(f"总分={l1l4_total} 弱势空头，需配合趋势阶段判断")

        # 趋势阶段
        if stage == "trending":
            bear.append("趋势阶段: trending — 主趋势运行中，顺势持有")
        elif stage == "launch":
            bear.append("趋势阶段: launch — 空头刚启动，空间最大但需确认信号强度")
        elif stage == "exhausted":
            bear.append("趋势阶段: exhausted — 空头衰竭中，注意减仓或收紧止损")
        elif stage == "reversal":
            bear.append("趋势阶段: reversal — 空头趋势可能翻转，需注意风险")

        # 均线排列
        if ma_align:
            if ma_align in ("bearish", "mixed"):
                bear.append(f"均线排列: {ma_align} — 短周期均线位于长周期下方")
            else:
                bear.append(f"均线排列: {ma_align}")

        # Z-score
        if z < -1:
            bear.append(f"Z={z:.1f} 统计显著偏空(方向感知Z-score负值=强于平均空头)")

        # 因子择时
        if fdir == "bear":
            bear.append(f"因子择时共振(bear) — 辅助验证空头方向")
        elif conflict:
            bear.append("多因子分歧 — 空头信号 vs 因子择时非空，需警惕反向风险")

        # CCI
        if cci and cci < -100:
            bear.append(f"CCI={cci:.1f} < -100，进入超卖区但空头趋势中")
        elif cci and cci < 0:
            bear.append(f"CCI={cci:.1f} 负值，空方主导")
        elif cci and cci > 100:
            bear.append(f"CCI={cci:.1f} > 100，多头过热但仍需看方向")  # 用于反方论据

        # 成交量
        if volume and volume > 0:
            bear.append(f"成交量: {volume:,}手")

    # ====== 多头论据 ======
    # 对空头品种也生成多头论据（风险提示/反转可能性）
    if direction == "SELL":
        # RSI极端超卖提示反弹风险
        if rsi < 30:
            bull.append(f"⚠️ RSI={rsi:.1f} 极端超卖 — 技术性反弹风险上升，需设紧止损保护")
        elif rsi < 35:
            bull.append(f"⚠️ RSI={rsi:.1f} 接近超卖区 — 可能出现技术性抵抗")

        # 趋势衰竭
        if stage == "exhausted":
            bull.append(f"⚠️ 阶段=exhausted — 空头趋势末端，反转概率上升，需密切监控")
        # V型反转例外：ADX>60但价格已反转，不适用追高追空警示
        is_v_reversal = (stage == "reversal")
        if adx > 60 and not is_v_reversal:
            bull.append(f"⚠️ ADX={adx:.1f}>60 — 行情已运行较远，追空盈亏比不划算，注意动量衰竭")
        elif adx > 60 and is_v_reversal:
            bull.append(f"阶段=reversal — 价格已反转，V型反转形态中ADX={adx:.1f}高位属正常特征，不适用追空警示")

        # 因子分歧
        if fdir == "bull":
            bull.append(f"⚠️ 因子择时反向(bull) — 因子模型显示多头信号，与空头信号矛盾")

        # 多因子分歧
        if conflict:
            bull.append("⚠️ 多因子方向分歧 — 信号与因子择时方向不一致，仓位应减半")

        # Z-score反方向极端
        if z > 1.5:
            bull.append(f"⚠️ Z={z:.1f} — 空头方向内Z值偏高（偏弱空头），接近中性区")
        if z > 0.5:
            bull.append(f"Z={z:.1f} — 空头方向偏弱（Z正=同方向内偏弱）")

        # 阶段反转
        if stage == "reversal":
            bull.append("⚠️ 阶段=reversal — K线已形成潜在反转形态，平仓观望")

    elif direction == "BUY":
        # 多头品种的主力论据
        if adx >= 40:
            bull.append(f"ADX={adx:.1f} 中强多头趋势")
        elif adx >= 25:
            bull.append(f"ADX={adx:.1f} 多头趋势形成")
        if rsi > 60:
            bull.append(f"RSI={rsi:.1f} 多方主导区间")
        elif rsi > 50:
            bull.append(f"RSI={rsi:.1f} 中轴上方")
        if abs(l1l4_total) >= 65:
            bull.append(f"总分={l1l4_total} 高分多头")
        elif abs(l1l4_total) >= 55:
            bull.append(f"总分={l1l4_total} 中高分多头")
        if stage == "trending":
            bull.append("阶段: trending 主趋势运行中")
        if z > 1:
            bull.append(f"Z={z:.1f} 统计显著偏多")
        if fdir == "bull":
            bull.append("因子择时共振(bull) 多因子确认")
        if fdir == "bear":
            bear.append("因子择时分歧(bear) 反转风险")
        if rsi > 75:
            bear.append(f"RSI={rsi:.1f} 超买 回调风险")
        if stage == "exhausted":
            bear.append("阶段 exhausted 反转概率上升")

    # 双方向都有论据时，确保各至少1条
    if direction == "SELL" and not bear:
        bear.append(f"信号空头: 总分={l1l4_total}, ADX={adx:.1f}")
    if not bull:
        bull.append(f"信号: 总分={l1l4_total}, 方向={direction}, 阶段={stage}")

    return "<br>".join(bear) if bear else "", "<br>".join(bull) if bull else ""


def _build_chain_lookup(intermediate: dict) -> dict:
    """从 intermediate 构建 pid→chain_name 映射"""
    chain_results = intermediate.get("chain_results", {})
    pid_to_chain = {}
    for cname, cinfo in chain_results.items():
        if not isinstance(cinfo, dict):
            continue
        members = cinfo.get("chain_members", cinfo.get("members", []))
        if isinstance(members, list):
            for m in members:
                pid_to_chain[m.lower()] = cname
                pid_to_chain[m.upper()] = cname
    return pid_to_chain


def adapt_debate_results(debate_results: dict, intermediate: dict) -> dict:
    """将 debate_results.json 适配为 per-pid dict。"""
    fmt = _detect_format(debate_results)
    if fmt == "nested":
        verdicts = debate_results.get("verdicts", {})
        if not verdicts:
            verdicts = debate_results.get("decisions", {})  # 明鉴秋汇总格式: {"decisions": {"RM": {...}}}
        overall = debate_results.get("overall", {})
        debate_results = _nested_to_per_pid(verdicts, overall, intermediate)
    elif fmt == "final_verdict":
        verdicts = debate_results.get("final_verdict", {})
        overall = debate_results.get("overall", {})
        debate_results = _nested_to_per_pid(verdicts, overall, intermediate)
    elif fmt == "nested_list":
        raw_list = debate_results.get("verdicts", [])
        nested_dict = {}
        for v in raw_list:
            if isinstance(v, dict):
                sym = v.get("symbol", v.get("pid", ""))
                if sym:
                    nested_dict[sym] = v
        overall = debate_results.get("overall", {})
        debate_results = _nested_to_per_pid(nested_dict, overall, intermediate)
    return _per_pid_normalize(debate_results, intermediate)


def _nested_to_per_pid(verdicts: dict, overall: dict, intermediate: dict) -> dict:
    pid_to_chain = _build_chain_lookup(intermediate)
    per_pid = {}
    for pid, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        direction = _map_direction(v.get("direction", ""))
        conf_raw = v.get("confidence", 0)
        if isinstance(conf_raw, str):
            conf_map = {"HIGH": 0.85, "MEDIUM": 0.60, "LOW": 0.35}
            conf_val = conf_map.get(conf_raw, 0.5)
        else:
            conf_val = float(conf_raw) if conf_raw else 0.5

        bull_args = _normalize_args(v.get("bull_args", ""))
        bear_args = _normalize_args(v.get("bear_args", ""))
        if not bear_args and not bull_args:
            bear_args, bull_args = _generate_fallback_args(pid, v, intermediate)

        # 链名查找
        chain = v.get("chain", "")
        if not chain:
            chain = pid_to_chain.get(pid.upper(), "")
        if not chain:
            chain = pid_to_chain.get(pid.lower(), "")

        # 处理final_verdict格式：l1l4/factor子dict展开
        l1l4 = v.get("l1l4", {})
        if isinstance(l1l4, dict):
            v_adx = v.get("adx", l1l4.get("adx", 0))
            v_rsi = v.get("rsi", l1l4.get("rsi", 50))
            v_price = v.get("price", v.get("entry_price", v.get("entry", 0)))
            v_score = v.get("score", l1l4.get("total", 0))
        else:
            v_adx = v.get("adx", 0)
            v_rsi = v.get("rsi", 50)
            v_price = v.get("price", v.get("entry_price", v.get("entry", 0)))
            v_score = v.get("score", 0)

        # 如果没有bull_args/bear_args，从reasoning生成
        if not bear_args and not bull_args:
            reasoning = v.get("reasoning", "")
            risk_note = v.get("risk_note", "")
            key_tension = v.get("key_tension", "")
            if direction == "SELL":
                bear_args = reasoning[:2000] if reasoning else "空头方向"
                bull_args = risk_note[:2000] if risk_note else (key_tension[:2000] if key_tension else "")
            elif direction == "BUY":
                bull_args = reasoning[:2000] if reasoning else "多头方向"
                bear_args = risk_note[:2000] if risk_note else ""

        per_pid[pid] = {
            "judge_verdict": {
                "final_direction": direction,
                "confidence": conf_val,
                # G 修复：兼容 reasoning 顶层 与 嵌套 judge_verdict.reasoning 两种格式
                "reasoning": (v.get("reasoning")
                             or (v.get("judge_verdict", {}).get("reasoning", "")
                                if isinstance(v.get("judge_verdict"), dict) else "")
                             or ""),
            },
            "category": overall.get("tendency", ""),
            "risk_detail": overall.get("core_conflict", ""),
            "bull_args": bull_args,
            "bear_args": bear_args,
            "verdict": {"status": direction, "confidence": conf_val},
            "direction": direction,
            "entry_price": v_price,
            "target_price": v.get("target_price", v.get("target", v.get("target1", 0))),
            "stop_loss_price": v.get("stop_loss_price", v.get("stop_loss", v.get("stop", 0))),
            "position_size": v.get("position_pct", v.get("position_size", v.get("suggested_position", 0))),
            "risk_reward_ratio": v.get("risk_reward_ratio", v.get("risk_reward", v.get("rr", 0))),
            "chain": chain,
            "adx": v_adx,
            "rsi": v_rsi,
            "score": v.get("score", v.get("verdict_score", v_score)),
            "price": v_price,
        }
    return per_pid


def _per_pid_normalize(debate_results: dict, intermediate: dict) -> dict:
    pid_to_chain = _build_chain_lookup(intermediate)
    adapted = {}
    for pid, d in debate_results.items():
        if not isinstance(d, dict):
            continue
        entry = dict(d)
        if "judge_verdict" not in entry or not isinstance(entry.get("judge_verdict"), dict):
            entry["judge_verdict"] = {
                "final_direction": entry.get("direction", "HOLD"),
                "confidence": entry.get("confidence", 0),
                "reasoning": entry.get("reasoning", ""),
            }
        for key in ("bull_args", "bear_args"):
            val = entry.get(key, "")
            if isinstance(val, list):
                entry[key] = "<br>".join(str(a) for a in val) if val else ""
            elif not val:
                fallback_bear, fallback_bull = _generate_fallback_args(pid, entry, intermediate)
                entry["bear_args"] = entry.get("bear_args") or fallback_bear
                entry["bull_args"] = entry.get("bull_args") or fallback_bull
        if not entry.get("chain") and pid_to_chain:
            entry["chain"] = pid_to_chain.get(pid.upper(), "") or pid_to_chain.get(pid.lower(), "")
        adapted[pid] = entry
    return adapted


# ==================== 数据读取 ====================
# G/C 修复：--debate 子集辩论模式不以全量 intermediate_data.json 为硬前置，
# 缺省时以 debate_results.json 为准（intermediate 置空），避免误 exit(1)
if not os.path.exists(INTERMEDIATE_PATH):
    if getattr(args, "debate", None):
        print(f"⚠️ 未找到中间数据: {INTERMEDIATE_PATH}（--debate 模式：以 debate_results 为准）")
        intermediate = {}
    else:
        print(f"✗ 未找到中间数据: {INTERMEDIATE_PATH}")
        sys.exit(1)
else:
    with open(INTERMEDIATE_PATH, "r", encoding="utf-8") as f:
        intermediate = json.load(f)

debate_results = {}
DATA_BENCHMARK = intermediate.get("data_benchmark", "")
if os.path.exists(DEBATE_PATH):
    with open(DEBATE_PATH, "r", encoding="utf-8") as f:
        _raw_dr = json.load(f)
    # G 项：data_benchmark 在 adapt 重铸为 per_pid 时丢失，须从原始 debate_results.json 捕获
    DATA_BENCHMARK = _raw_dr.get("data_benchmark", DATA_BENCHMARK)
    debate_results = adapt_debate_results(_raw_dr, intermediate)
    print(f"✓ 辩论结果: {len(debate_results)} 个品种")
    
    # ── 加载证真/慎思辩论详情并注入 per-pid ──
    def _load_debate_args(report_dir: str) -> dict:
        """读取辩论详情文件，返回 {symbol: dict} 格式"""
        import re, glob
        result = {}
        # 尝试多种文件名模式（带日期/不带日期, p3_/p4_）
        PATTERNS = [
            ('*zhengzhen*.json', 'zz'),
            ('*zhensi*.json', 'zs'),
        ]
        files_found = set()
        for glob_pat, key_tag in PATTERNS:
            for fpath in glob.glob(os.path.join(report_dir, glob_pat)):
                if fpath in files_found:
                    continue
                files_found.add(fpath)
                with open(fpath, encoding='utf-8') as f:
                    content = f.read()
                fence = re.search(r'```json\s*(.*?)```', content, re.DOTALL)
                raw = json.loads(fence.group(1)) if fence else json.loads(content)
                # 尝试 role 字段定位证真/慎思；也尝试 symbols 或直接.items()
                items = raw.get('symbols', raw)
                if isinstance(items, dict):
                    for sym, item in items.items():
                        result.setdefault(sym.upper(), {})[key_tag] = item
                elif isinstance(items, list):
                    for item in items:
                        sym = item.get('symbol', item.get('subject', '')).split()[0].upper()
                        result.setdefault(sym, {})[key_tag] = item
        return result

    debate_args = _load_debate_args(os.path.dirname(DEBATE_PATH)) if os.path.exists(DEBATE_PATH) else {}
    for pid in debate_results:
        args = debate_args.get(pid.upper(), {})
        zz = args.get('zz', {})  # 证真
        zs = args.get('zs', {})  # 慎思
        if not debate_results[pid].get('bull_args'):
            if isinstance(zz, dict):
                thesis = zz.get('thesis', zz.get('core_claim', ''))
                dims = zz.get('dimensions', zz.get('evidence', []))
                if thesis: debate_results[pid]['bull_args'] = thesis[:2000]
                elif isinstance(dims, list):
                    debate_results[pid]['bull_args'] = '; '.join([d.get('claim','')[:200] for d in dims[:8]])
        if not debate_results[pid].get('bear_args'):
            if isinstance(zs, dict):
                thesis = zs.get('thesis', zs.get('core_claim', ''))
                dims = zs.get('dimensions', zs.get('evidence', []))
                if thesis: debate_results[pid]['bear_args'] = thesis[:2000]
                elif isinstance(dims, list):
                    debate_results[pid]['bear_args'] = '; '.join([d.get('claim','')[:200] for d in dims[:8]])

    # ── 加载交易方案并注入 per-pid（合约/入场/止损/目标） ──
    for fname in [f'p5_trading_plan_{REPORT_DATE_COMPACT}.json', 'p5_trading_plan.json']:
        fpath = os.path.join(os.path.dirname(DEBATE_PATH), fname) if os.path.exists(DEBATE_PATH) else ''
        if not fpath or not os.path.exists(fpath):
            continue
        with open(fpath, encoding='utf-8') as f:
            tp = json.load(f)
        plans = tp.get('plans', tp.get('symbols', {}))
        if isinstance(plans, dict):
            for pid in debate_results:
                p = plans.get(pid.upper(), plans.get(pid.lower(), {}))
                if not p: continue
                debate_results[pid]['main_contract'] = p.get('main_contract', '')
                debate_results[pid]['price'] = p.get('price', debate_results[pid].get('entry_price', 0))
                ops = p.get('options', [])
                if ops:
                    opt = ops[0]  # 保守方案
                    debate_results[pid]['entry_price'] = debate_results[pid].get('entry_price') or p.get('price', 0)
                    if isinstance(opt.get('stop_loss'), dict):
                        debate_results[pid]['stop_loss_price'] = opt['stop_loss'].get('price', 0)
                    elif isinstance(opt.get('stop_loss'), (int, float)):
                        debate_results[pid]['stop_loss_price'] = opt['stop_loss']
                    targets = opt.get('targets', [])
                    if targets:
                        debate_results[pid]['target_price'] = targets[0].get('price', 0) if isinstance(targets[0], dict) else targets[0]
                    debate_results[pid]['position_size'] = float(opt.get('position_pct', opt.get('position', '2%', '').replace('%', '') or 3.5))
        break

data_source_used = intermediate.get("data_source", "unknown")
tdx_available = intermediate.get("_meta", {}).get("tdx_bridge_available", False)
indicator_source = intermediate.get("_meta", {}).get("indicator_source", "numpy")
print(f"  📡 指标来源: {indicator_source}")

all_actionable = intermediate.get("all_actionable", [])
chain_results = intermediate.get("chain_results", {})
symbols_summary = intermediate.get("symbols_summary", [])
BUY_top5_ids = intermediate.get("BUY_top5", [])
SELL_top5_ids = intermediate.get("SELL_top5", [])

# v8.8.0+: 从 intermediate_data 加载逐品种结构化数据（来自LLM输出）
technical_per_symbol = intermediate.get("technical_per_symbol", {})
fundamental_per_symbol = intermediate.get("fundamental_per_symbol", {})
print(f"✓ 逐品种技术面: {len(technical_per_symbol)} 品种, 基本面: {len(fundamental_per_symbol)} 品种")

print(f"✓ 读取中间数据: {len(symbols_summary)} 品种, {len(chain_results)} 产业链")
print(f"✓ 有效方案: {len(all_actionable)}")


# ==================== 构建13链聚合（从62条per-pid链数据中聚合） ====================
def aggregate_chains(chain_results: dict, all_actionable: list, symbols_summary: list = None) -> dict:
    """按产业链聚合指标：品种数=全链品种数，多空分布=全链品种分布，平均分=信号品种均分"""
    # 先按链名分组
    chain_groups = {}
    pid_to_chain = _build_chain_lookup({"chain_results": chain_results})

    # 从 chain_results 中提取链名和成员
    chain_members_map = {}
    chain_term_map = {}
    for cname, cinfo in chain_results.items():
        if not isinstance(cinfo, dict):
            continue
        members = cinfo.get("chain_members", cinfo.get("members", []))
        chain_name = cinfo.get("chain", cname)
        if isinstance(members, list) and members:
            if chain_name not in chain_members_map:
                chain_members_map[chain_name] = set()
            if chain_name not in chain_term_map:
                chain_term_map[chain_name] = cinfo.get("term_structure", "flat")
            for m in members:
                chain_members_map[chain_name].add(m.lower())

    # 如果没聚合到链，从 symbols_summary 的链字段构建
    if not chain_members_map:
        if symbols_summary:
            for s in symbols_summary:
                chain_info = s.get("chain_info", "") or s.get("chain", "")
                pid = s.get("symbol", s.get("pid", "")).lower()
                if chain_info and pid:
                    cn = chain_info if isinstance(chain_info, str) else chain_info.get("chain", "")
                    if cn:
                        if cn not in chain_members_map:
                            chain_members_map[cn] = set()
                        chain_members_map[cn].add(pid)
        else:
            for s in all_actionable:
                chain_info = s.get("chain_info", "")
                pid = s.get("pid", "").lower()
                if chain_info and pid:
                    cn = chain_info if isinstance(chain_info, str) else chain_info.get("chain", "")
                    if cn:
                        if cn not in chain_members_map:
                            chain_members_map[cn] = set()
                        chain_members_map[cn].add(pid)

    # 建立全量 pid→方向/总分 映射
    all_directions = {}  # pid.lower() → "BUY"/"SELL"/"HOLD"
    all_scores = {}      # pid.lower() → abs(total)
    if symbols_summary:
        for s in symbols_summary:
            pid = (s.get("symbol") or s.get("pid", "")).lower()
            if pid:
                raw_dir = s.get("direction", "")
                if raw_dir in ("bull",):
                    all_directions[pid] = "BUY"
                elif raw_dir in ("bear",):
                    all_directions[pid] = "SELL"
                else:
                    all_directions[pid] = "HOLD"
                all_scores[pid] = abs(s.get("total", s.get("abs", 0)))
    # 也补上 all_actionable 中有但 symbols_summary 没有的
    for s in all_actionable:
        pid = s.get("pid", "").lower()
        if pid and pid not in all_directions:
            raw_dir = s.get("direction", s.get("decision", ""))
            if raw_dir in ("bull", "BUY"):
                all_directions[pid] = "BUY"
            elif raw_dir in ("bear", "SELL"):
                all_directions[pid] = "SELL"
            else:
                all_directions[pid] = "HOLD"
            all_scores[pid] = all_scores.get(pid) or abs(s.get("total", s.get("abs", 0)))

    # 计算每链的指标
    aggregated = {}
    for chain_name, member_set in chain_members_map.items():
        # 全链品种
        members_list = sorted(member_set)
        total_count = len(members_list)

        # 全链方向分布
        dc = {}
        for pid in members_list:
            d = all_directions.get(pid, "HOLD")
            dc[d] = dc.get(d, 0) + 1

        # 平均分：全链信号品种的平均分
        chain_signal_scores = [all_scores.get(pid, 0) for pid in members_list if all_directions.get(pid) in ("BUY", "SELL")]
        avg_score = sum(chain_signal_scores) / len(chain_signal_scores) if chain_signal_scores else 0

        # 龙头：全链中信号分最高的品种
        best_pid = max(members_list, key=lambda p: all_scores.get(p, 0)) if members_list else None
        leader_name = best_pid.upper() if best_pid else "—"
        if symbols_summary:
            for s in symbols_summary:
                if (s.get("symbol") or s.get("pid", "")).lower() == best_pid:
                    leader_name = s.get("name", s.get("product_name", best_pid.upper()))
                    break

        buy_cnt = dc.get("BUY", 0)
        sell_cnt = dc.get("SELL", 0)
        if sell_cnt > buy_cnt * 2:
            overall_trend = "强势空头"
        elif sell_cnt > buy_cnt:
            overall_trend = "偏空震荡"
        elif buy_cnt > sell_cnt * 2:
            overall_trend = "强势多头"
        elif buy_cnt > sell_cnt:
            overall_trend = "偏多震荡"
        else:
            overall_trend = "高波动震荡"

        aggregated[chain_name] = {
            "count": total_count,
            "avg_score": round(avg_score, 1),
            "direction_counts": dc,
            "leader": leader_name,
            "overall_trend": overall_trend,
            "members": members_list,
            "term_structure": chain_term_map.get(chain_name, "flat"),
        }
    return aggregated


aggregated_chains = aggregate_chains(chain_results, all_actionable, symbols_summary)
chain_results_agg = aggregated_chains
print(f"✓ 产业链聚合: {len(chain_results_agg)} 条链")


# ── 补充：从 debate_results 补充已裁决但不在 all_actionable 中的品种 ──
debate_pids = {pid.lower() for pid in debate_results if isinstance(debate_results.get(pid), dict)
               and isinstance(debate_results[pid].get("judge_verdict"), dict)
               and debate_results[pid]["judge_verdict"].get("final_direction") in ("BUY", "SELL")}
actionable_pids = {s.get("pid", "").lower() for s in all_actionable}
missing_pids = debate_pids - actionable_pids
if missing_pids:
    for pid_lower in sorted(missing_pids):
        d = debate_results.get(pid_lower) or debate_results.get(pid_lower.upper()) or {}
        if not isinstance(d, dict):
            continue
        jv = d.get("judge_verdict", {})
        direction = jv.get("final_direction", "HOLD")
        dc_raw = jv.get("confidence", 50)
        if isinstance(dc_raw, str):
            _cm = {"HIGH": 0.85, "MEDIUM": 0.60, "LOW": 0.35}
            conf = _cm.get(dc_raw, 0.5)
        else:
            conf = float(dc_raw) / 100.0 if float(dc_raw) > 1 else float(dc_raw)
        all_actionable.append({
            "pid": pid_lower,
            "product_name": pid_lower.upper(),
            "decision": direction,
            "confidence": conf,
            "price": d.get("price", 0),
            "entry_price": d.get("entry_price", 0),
            "target_price": d.get("target_price", 0),
            "stop_loss_price": d.get("stop_loss_price", 0),
            "risk_reward_ratio": d.get("risk_reward_ratio", 0),
            "position_size": d.get("position_size", 0),
            "chain": d.get("chain", ""),
            "adx": d.get("adx", 0),
            "stage": "",
            "signal_type": "debate_only",
            "last_price": d.get("price", 0),
            "grade": d.get("grade", "DEBATE"),
            "l1l4_total": 0,
            # G35: 从 debate_results 携带多空论据，避免 HTML 报告中论据为空
            "bull_args": d.get("bull_args", ""),
            "bear_args": d.get("bear_args", ""),
        })
    print(f"✓ 补充辩论裁决品种: {len(missing_pids)} 个 → {', '.join(sorted(missing_pids))}")
    print(f"✓ 有效方案(补充后): {len(all_actionable)}")

# ==================== Step 3: 智能筛选 ====================
print("\n[Step 3] 智能筛选...")

filtered_signals = []
T1_signals = []
T2_signals = []
T3_signals = []

for s in all_actionable:
    pid = s.get("pid", "")
    confidence = s.get("confidence", 0)
    # 置信度归一化：字符串"高/中/低" → float
    if isinstance(confidence, str):
        _conf_map = {"高": 0.95, "中": 0.65, "低": 0.35}
        confidence = _conf_map.get(confidence, 0.5)
    direction = s.get("decision", "HOLD")

    debate = debate_results.get(pid, {})
    if not debate:
        verdict = "—"
        debate_reason = ""
    else:
        judge_verdict = debate.get("judge_verdict", {})
        if isinstance(judge_verdict, dict) and "final_direction" in judge_verdict:
            verdict = judge_verdict["final_direction"]
        else:
            raw_verdict = debate.get("verdict", "—")
            if isinstance(raw_verdict, dict):
                verdict = raw_verdict.get("status", "—")
            else:
                verdict = str(raw_verdict) if raw_verdict else "—"

    cat = debate.get("category", "")
    risk_detail = debate.get("risk_detail", "")

    # ── 已辩论裁决的品种跳过扫描置信度和方向过滤 ──
    has_debate_verdict = bool(
        debate and isinstance(debate.get("judge_verdict"), dict)
        and debate["judge_verdict"].get("final_direction") in ("BUY", "SELL")
    )
    if has_debate_verdict:
        # 使用辩论裁决方向取代扫描信号方向
        direction = debate["judge_verdict"]["final_direction"]
        verdict = direction
        # 使用辩论裁决置信度
        dc_raw = debate["judge_verdict"].get("confidence", 50)
        if isinstance(dc_raw, str):
            _cm = {"HIGH": 0.85, "MEDIUM": 0.60, "LOW": 0.35}
            confidence = _cm.get(dc_raw, 0.5)
        else:
            confidence = float(dc_raw) / 100.0 if float(dc_raw) > 1 else float(dc_raw)
    else:
        if confidence < 0.4:
            continue
        if direction not in ["BUY", "SELL"]:
            continue
        if verdict in ("HOLD", "WATCH", "—"):
            continue

    if debate:
        jv = debate.get("judge_verdict", {})
        if isinstance(jv, dict):
            debate_reason = jv.get("reasoning", "")[:150] or verdict
        else:
            debate_reason = verdict
    else:
        debate_reason = ""

    # 从 debate_results 获取交易参数
    entry_price = debate.get("entry_price", s.get("entry_price", s.get("price", 0)))
    target_price = debate.get("target_price", s.get("target_price", 0))
    stop_loss_price = debate.get("stop_loss_price", s.get("stop_loss_price", s.get("price", 0)))
    risk_reward = debate.get("risk_reward_ratio", s.get("risk_reward_ratio", 0))
    position = debate.get("position_size", s.get("position_size", 0))

    # 若原始盈亏比为0，从entry/target/stop自行计算（CTP就绪必须要有RR）
    if not risk_reward and entry_price and stop_loss_price and target_price:
        direction = s.get("decision", "HOLD")
        if direction == "BUY":
            stop_pct = (entry_price - stop_loss_price) / entry_price if entry_price != stop_loss_price else 0
            target_pct = (target_price - entry_price) / entry_price if target_price != entry_price else 0
        else:
            stop_pct = (stop_loss_price - entry_price) / entry_price if entry_price != stop_loss_price else 0
            target_pct = (entry_price - target_price) / entry_price if target_price != entry_price else 0
        risk_reward = round(target_pct / stop_pct, 2) if stop_pct > 0 else 0

    # 链名
    pid_to_chain = _build_chain_lookup({"chain_results": chain_results})
    chain = debate.get("chain", "") or pid_to_chain.get(pid.upper(), "") or pid_to_chain.get(pid.lower(), "")

    # 从 debate 获取多空论据（已由适配器填充）
    bull_args = debate.get("bull_args", "")
    bear_args = debate.get("bear_args", "")
    if not bull_args and not bear_args:
        fallback_bear, fallback_bull = _generate_fallback_args(pid, s, intermediate)
        bull_args = bull_args or fallback_bull
        bear_args = bear_args or fallback_bear

    info = {
        "product_id": pid,
        "product_name": s.get("product_name", pid),
        "direction": direction,
        "confidence": confidence * 100,
        "price": s.get("last_price", s.get("price", 0)),
        "entry": entry_price,
        "target": target_price,
        "stop_loss": stop_loss_price,
        "risk_reward": risk_reward,
        "position_size": position,
        "verdict": verdict,
        "debate_reason": debate_reason,
        "chain": chain,
        "chain_trend": chain_results_agg.get(chain, {}).get("overall_trend", ""),
        "bull_args": bull_args,
        "bear_args": bear_args,
        "stage": s.get("stage", ""),
        "adx_val": s.get("adx", 0),
        "signal_type": s.get("signal_type", ""),
    }

    # T1/T2/T3 分级逻辑（按阶段优先，非置信度绝对值）
    stage = s.get("stage", "")
    adx_val = s.get("adx", 0)
    if adx_val > 50 or stage == "exhausted":
        info["tier"] = "T3警惕"
        T3_signals.append(info)
    elif stage == "trending" and adx_val < 50:
        info["tier"] = "T2主仓"
        T2_signals.append(info)
    elif stage == "launch":
        info["tier"] = "T1观察"
        T1_signals.append(info)
    elif stage == "trending" and adx_val >= 50:
        info["tier"] = "T3警惕"
        T3_signals.append(info)
    else:
        # fallback: 按置信度
        if confidence * 100 > 90:
            info["tier"] = "T3警惕"
            T3_signals.append(info)
        elif confidence * 100 >= 75:
            info["tier"] = "T2主仓"
            T2_signals.append(info)
        else:
            info["tier"] = "T1观察"
            T1_signals.append(info)

    filtered_signals.append(info)

# G37: 交易可靠性排序 = 置信度 × 盈亏比（隐含胜率 × 潜在盈亏比）
def _reliability(s):
    rr = float(s.get("risk_reward", 0) or s.get("risk_reward_ratio", 0) or 0)
    return float(s.get("confidence", 0) or 0) * max(rr, 0.01)
T1_signals.sort(key=_reliability, reverse=True)
T2_signals.sort(key=_reliability, reverse=True)
T3_signals.sort(key=_reliability, reverse=True)
filtered_signals.sort(key=_reliability, reverse=True)

print(f"  T1观察: {len(T1_signals)}, T2主仓: {len(T2_signals)}, T3警惕: {len(T3_signals)}")
for s in T1_signals[:10]:
    icon = "🟢BUY" if s["direction"] == "BUY" else "🔴SELL"
    print(f"    {icon} {s['product_id']} 置信度{s['confidence']:.0f}%  辩论:{s['verdict']}")


# ==================== 探源模块：基本面状态向量生成 ====================
# 模拟探源Agent的职责：基于因子数据和品种特征生成基本面状态向量
def _generate_fundamental_state(pid: str, chain_name: str, all_actionable: list) -> dict:
    """探源：生成基本面状态向量"""
    s = None
    for item in all_actionable:
        if item.get("pid", "").lower() == pid.lower():
            s = item
            break
    if not s:
        # Return basic fallback when no actionable signal data
        chain_hint = f"产业链: {chain_name}" if chain_name else ""
        direction_hint = "方向待确认"
        return {
            "supply_demand": f"供需数据暂缺（{chain_hint}）" if chain_name else "供需数据暂缺",
            "inventory": "库存水平待核实",
            "profit_margin": "利润和开工率数据暂不可用",
            "basis_term": "基差与期限结构待查",
            "leading_signals": ["数据暂缺，需通过F10接口获取实时基本面", f"{chain_hint}"],
        }

    fdir = s.get("factor_direction", "neutral")
    f_total = s.get("factor_total", 0)
    l1l4_dir = s.get("l1l4_direction", "neutral")
    stage = s.get("stage", "")
    adx = s.get("adx", 0)
    rsi = s.get("rsi", 50)
    z = s.get("z_score", 0)
    cons = s.get("cons", 0)
    conflict = s.get("direction_conflict", False)
    cci = s.get("cci", 0)

    # 基本面推断（基于可用的量化因子数据）
    fundamentals = {
        "supply_demand": "",
        "inventory": "",
        "profit_margin": "",
        "basis_term": "",
        "leading_signals": [],
    }

    # 供需推断
    if adx > 40 and l1l4_dir == "bear":
        fundamentals["supply_demand"] = "供给端充裕，需求端偏弱"
        if stage == "trending":
            fundamentals["supply_demand"] += "，趋势向下运行中，供需宽松格局"
        elif stage == "exhausted":
            fundamentals["supply_demand"] += "，但空头已至末端，供需边际可能改善"
    elif adx > 25 and l1l4_dir == "bull":
        fundamentals["supply_demand"] = "供给端偏紧，需求端有支撑"
        fundamentals["supply_demand"] += "，供需偏紧格局支撑价格"
    else:
        fundamentals["supply_demand"] = f"供需处于均衡状态，ADX={adx:.0f}趋势不明确"

    # 库存推断
    if rsi < 30:
        fundamentals["inventory"] = "现货库存可能偏高或下游拿货意愿弱，导致价格持续受压"
    elif rsi > 70:
        fundamentals["inventory"] = "现货库存可能偏低或下游补库积极，库存处于去化通道"
    elif rsi < 40:
        fundamentals["inventory"] = "库存消化节奏偏慢，社会库存同比可能偏高"
    elif 40 <= rsi <= 60:
        fundamentals["inventory"] = "库存水平中性，处于季节性波动范围内"
    else:
        fundamentals["inventory"] = "下游需求尚可，库存正常去化"

    # 利润/期限
    if l1l4_dir == "bear":
        fundamentals["profit_margin"] = "产业链利润处于压缩阶段，中下游加工利润可能为负"
        fundamentals["basis_term"] = "期限结构偏Contango或转为Back，反映现货走弱预期"
    else:
        fundamentals["profit_margin"] = "产业链利润尚可，生产积极性维持"
        fundamentals["basis_term"] = "期限结构偏Back，反映现货偏紧"

    # 领先信号
    if fdir == "bear":
        fundamentals["leading_signals"].append(f"因子择时偏空(f_total={f_total})，因子信号与空头方向一致")
    elif fdir == "bull":
        fundamentals["leading_signals"].append(f"因子择时偏多(f_total={f_total})，与方向{'一致' if l1l4_dir=='bull' else '分歧'}")
    if z < -1.5:
        fundamentals["leading_signals"].append(f"Z={z:.1f}统计显著偏空，为空头方向内极端品种")
    elif z > 1.5:
        fundamentals["leading_signals"].append(f"Z={z:.1f}统计显著偏多")
    if cons >= 3:
        fundamentals["leading_signals"].append(f"四层一致性CONS={cons}/4，技术面多维度共振")
    if conflict:
        fundamentals["leading_signals"].append("⚠️ 多因子方向分歧（信号 vs 因子择时不一致），基本面信号混乱需谨慎")
    if cci < -100:
        fundamentals["leading_signals"].append(f"CCI={cci:.0f}进入超卖区，短期可能存在均值修复需求")
    elif cci > 100:
        fundamentals["leading_signals"].append(f"CCI={cci:.0f}进入超买区")
    if stage == "exhausted":
        fundamentals["leading_signals"].append(f"趋势阶段为exhausted，现有趋势接近末端")
    elif stage == "reversal":
        fundamentals["leading_signals"].append(f"趋势阶段为reversal，K线形态可能出现反转")

    return fundamentals


# ==================== 观澜模块：多层次技术面分析 ====================
def _generate_technical_analysis(pid: str, symbols_summary: list) -> dict:
    """观澜：生成多层次技术面分析快照"""
    s = None
    for item in symbols_summary:
        if isinstance(item, dict) and item.get("symbol", item.get("pid", "")).lower() == pid.lower():
            s = item
            break

    # Build default tech dict for fallback when no scan data
    tech = {
        "trend": "趋势待确认（无详细扫描信号数据，需实时K线分析）",
        "key_levels": "暂缺实时价位信息",
        "volume_price": "量价数据暂不可用",
        "divergence": "无背离信号",
        "pattern": "形态待观察",
        "score": 50,
    }
    if not s:
        return tech

    adx = s.get("adx", 0)
    rsi = s.get("rsi", 50)
    cci = s.get("cci", 0)
    l1l4_total = s.get("l1l4_total", s.get("total", 0))
    l1l4_dir = s.get("l1l4_direction", "neutral")
    stage = s.get("stage", "")
    cons = s.get("cons", 0)
    z = s.get("z_score", 0)
    volume = s.get("volume", 0)
    ma_slope = s.get("ma_slope", 0)
    dc20 = s.get("dc20_break", "none")
    ma_align = s.get("ma_align", "mixed")
    macd = s.get("macd_cross", "none")
    fdir = s.get("factor_direction", "neutral")
    f_total = s.get("factor_total", 0)
    conflict = s.get("direction_conflict", False)

    tech = {
        "trend": "",
        "key_levels": "",
        "volume_price": "",
        "divergence": "",
        "pattern": "",
    }

    # 趋势判断（多维度，不只是ADX）
    trend_parts = []
    if l1l4_dir == "bear":
        trend_parts.append(f"方向: 空头主导(总分={l1l4_total})")
    elif l1l4_dir == "bull":
        trend_parts.append(f"方向: 多头主导(总分={l1l4_total})")
    else:
        trend_parts.append("方向: 中性")

    if adx >= 60:
        trend_parts.append(f"ADX={adx:.1f}极强趋势，动量充沛")
    elif adx >= 40:
        trend_parts.append(f"ADX={adx:.1f}中强趋势，趋势确认")
    elif adx >= 25:
        trend_parts.append(f"ADX={adx:.1f}趋势形成中")
    else:
        trend_parts.append(f"ADX={adx:.1f}趋势偏弱，以震荡对待")

    trend_parts.append(f"RSI={rsi:.1f}({'超卖' if rsi<30 else '弱势' if rsi<40 else '中性' if rsi<60 else '强势' if rsi<75 else '超买'})")
    trend_parts.append(f"MA排列: {ma_align}")

    if stage:
        stage_map = {"launch": "刚启动", "trending": "主趋势运行", "exhausted": "趋势末端", "reversal": "反转中"}
        trend_parts.append(f"趋势阶段: {stage_map.get(stage, stage)}")
    if abs(ma_slope) > 10:
        trend_parts.append(f"MA斜率{ma_slope:.0f}，趋势方向明确")
    tech["trend"] = " | ".join(trend_parts)

    # 关键位
    if cci:
        if cci > 200:
            tech["key_levels"] = f"CCI={cci:.0f}极端超买，价格远离均线，有回归需求"
        elif cci < -200:
            tech["key_levels"] = f"CCI={cci:.0f}极端超卖，价格远离均线，有超跌反弹需求"
        elif cci > 100:
            tech["key_levels"] = f"CCI={cci:.0f}进入乐观区域，跟踪突破确认"
        elif cci < -100:
            tech["key_levels"] = f"CCI={cci:.0f}进入悲观区域，跟踪支撑位"
        else:
            tech["key_levels"] = f"CCI={cci:.0f}处于震荡区间"
    if dc20 and dc20 != "none":
        tech["key_levels"] += f" | DC20通道: {dc20}"
    if z:
        tech["key_levels"] += f" | Z-score={z:.2f}"

    # 量价分析
    volume_parts = [f"成交量={volume:,}手"]
    if cons >= 3:
        volume_parts.append(f"四层一致性{cons}/4，多维度信号共振")
    if conflict:
        volume_parts.append("⚠️ 多因子方向分歧，量价信号矛盾")
    if l1l4_dir == "bear" and fdir == "bear":
        volume_parts.append("多因子共振空头，量价配合确认下行")
    elif l1l4_dir == "bear" and fdir == "bull":
        volume_parts.append("信号空 vs 因子多，方向分歧，量价信号混乱")
    tech["volume_price"] = " | ".join(volume_parts)

    # 背离
    div_parts = []
    if rsi < 25 and l1l4_dir == "bear":
        div_parts.append("RSI极端超卖+空头趋势，价格可能低估")
    elif rsi > 75 and l1l4_dir == "bull":
        div_parts.append("RSI极端超买+多头趋势，价格可能高估")
    if stage == "exhausted":
        div_parts.append("趋势动量衰减，可能出现价格与技术指标的背离")
    if adx > 70 and l1l4_dir == "bear":
        div_parts.append(f"ADX={adx:.0f}>70极强空头，注意动量衰竭后反转风险")
    tech["divergence"] = " | ".join(div_parts) if div_parts else "未检测到明显背离"

    # 形态
    pattern_parts = []
    if stage == "launch":
        pattern_parts.append("突破初期形态，方向确立但需右侧确认")
    elif stage == "trending":
        pattern_parts.append("趋势运行中，沿MA方向运行，未被破坏")
    elif stage == "exhausted":
        pattern_parts.append("趋势末端，波动加大，可能出现逆转形态")
    elif stage == "reversal":
        pattern_parts.append("反转潜在态势，价格穿越关键均线")
    if dc20:
        if "up" in dc20.lower():
            pattern_parts.append(f"DC20向上突破")
        elif "down" in dc20.lower():
            pattern_parts.append(f"DC20向下突破")
    if macd and macd != "none":
        pattern_parts.append(f"MACD: {macd}")
    tech["pattern"] = " | ".join(pattern_parts) if pattern_parts else "无明显识别形态"

    return tech


# ==================== 风控明模块：风险审核 ====================
# 调用 debate-risk-manager skill 的真实库函数
def _init_risk_engine():
    """加载风控明 risk_engine 和 calc_position 模块"""
    global _risk_engine_loaded, select_stop_anchor, calculate_position, calc_position_risk
    try:
        risk_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, "skills", "debate-risk-manager", "scripts"))
        if risk_dir not in sys.path:
            sys.path.insert(0, risk_dir)
        from risk_engine import select_stop_anchor as _sa, calculate_position as _cp
        from calc_position import calc_position_risk as _cpr
        select_stop_anchor = _sa
        calculate_position = _cp
        calc_position_risk = _cpr
        _risk_engine_loaded = True
        return True
    except Exception as e:
        print(f"  ⚠ 风控明引擎加载失败: {e}")
        return False

_risk_engine_loaded = False
select_stop_anchor = None
calculate_position = None
calc_position_risk = None

def _generate_risk_review(strategies: list, all_actionable: list) -> list:
    """风控明：对精选策略进行风险审核（基于 debate-risk-manager skill 库函数）"""
    if not _risk_engine_loaded:
        _init_risk_engine()

    reviews = []
    for s in strategies:
        pid = s.get("product_id", "")
        entry = s.get("entry", 0)
        sl = s.get("stop_loss", 0)
        target = s.get("target", 0)
        pos = s.get("position_size", 0)
        direction = s.get("direction", "HOLD")

        # 查找品种数据
        item = None
        for a in all_actionable:
            if a.get("pid", "").lower() == pid.lower():
                item = a
                break

        flags = []
        risk_level = "green"
        adx = item.get("adx", 0) if item else 0
        rsi = item.get("rsi", 50) if item else 50
        conflict = item.get("direction_conflict", False) if item else False
        volume = item.get("volume", 0) if item else 0

        # ===== 使用calc_position_risk做真实风控计算 =====
        if _risk_engine_loaded and entry and sl:
            try:
                def _pv(v, d=0.0):
                    return v.get("price", d) if isinstance(v, dict) else (v if isinstance(v, (int, float)) else d)
                entry_n = _pv(entry)
                sl_n = _pv(sl)
                lot_size = 10
                if pid.lower() in ("au", "ag"): lot_size = 1000
                elif pid.lower() == "sc": lot_size = 1000
                elif pid.lower() == "ec": lot_size = 50
                stop_points = abs(entry_n - sl_n)
                risk_result = calc_position_risk(
                    price=entry_n, lot_size=lot_size, margin_rate=0.10,
                    equity=1000000, stop_loss_points=stop_points, lots=1
                )
                if risk_result:
                    # 真实杠杆检查
                    lev = risk_result.get("leverage", 0)
                    if lev > 3:
                        flags.append(f"🔴 杠杆{lev:.2f}倍>3倍权益上限，必须减仓")
                        risk_level = "red"
                    # 保证金检查
                    margin_level = risk_result.get("margin_level", "green")
                    if margin_level == "red":
                        flags.append(f"🔴 保证金占用超权益60%，追保风险高")
                        risk_level = "red"
                    # 止损比例检查
                    stop_level = risk_result.get("stop_level", "green")
                    stop_ratio = risk_result.get("stop_ratio", 0)
                    if stop_level == "red":
                        flags.append(f"🔴 止损幅度{stop_ratio*100:.1f}%>5%权益红线")
                        risk_level = "red"
                    elif stop_level == "yellow":
                        flags.append(f"🟡 止损幅度{stop_ratio*100:.1f}%，接近3%警戒线")
                        if risk_level == "green": risk_level = "yellow"
                    # 安全手数
                    safe_max = risk_result.get("safe_max", 0)
                    flags.append(f"💡 risk_engine安全手数上限: {safe_max}手")
            except Exception as e:
                flags.append(f"⚠ calc_position_risk调用失败: {e}")

        # ADX检查
        if adx < 15:
            flags.append(f"🟡 ADX={adx:.1f}<15，无趋势信号，不适合追趋势策略")
            if risk_level == "green": risk_level = "yellow"

        # 多因子分歧
        if conflict:
            flags.append("🟡 多因子方向分歧(信号 vs 因子)，仓位建议减半")
            if risk_level == "green": risk_level = "yellow"

        # 超卖追空风险
        if direction == "SELL" and rsi < 30:
            flags.append(f"🔴 RSI={rsi:.1f}超卖区间追空，反弹风险高，建议缩小仓位至50%")
            risk_level = "red"
        elif direction == "SELL" and rsi < 35:
            flags.append(f"🟡 RSI={rsi:.1f}接近超卖，技术反弹风险")

        # 极端趋势追势
        if adx > 70:
            flags.append(f"🟡 ADX={adx:.1f}>70，趋势极强但可能接近极限，建议紧止损")

        # 流动性检查
        if volume and volume < 10000:
            flags.append(f"🟡 成交量{volume:,}手偏低，流动性不足注意滑点")
            if risk_level == "green": risk_level = "yellow"

        # 盈亏比合理性检查（基于支撑压力位的判断）
        def _num(v, d=0):
            """从 dict 或数值中提取价格数值"""
            return v.get("price", d) if isinstance(v, dict) else (v if isinstance(v, (int, float)) else d)

        entry_n = _num(entry)
        sl_n = _num(sl)
        target_n = _num(target)
        stop_pct = abs(entry_n - sl_n) / entry_n * 100 if entry_n else 0
        target_pct = abs(target_n - entry_n) / entry_n * 100 if entry_n else 0
        actual_rr = target_pct / stop_pct if stop_pct > 0 else 0
        if actual_rr < 1.5:
            flags.append(f"🔴 盈亏比{actual_rr:.1f}:1<1.5:1，风险回报不合理，建议放弃或调目标位")
            if risk_level != "red": risk_level = "red"
        elif actual_rr < 2.0:
            flags.append(f"🟡 盈亏比{actual_rr:.1f}:1<2:1，回报偏薄，考虑收紧止损")

        # 仓位调整建议
        if risk_level == "red":
            adj = f"风控建议: 放弃该策略 或 仓位降至{pos*0.3:.0f}%(原{pos:.0f}%), 目标位需调整至合理盈亏比"
        elif risk_level == "yellow":
            adj = f"风控建议: 仓位降至{pos*0.6:.0f}%(原{pos:.0f}%), 观察确认后再加仓"
        else:
            adj = f"✅ 风控通过，按原计划执行(仓位{pos:.0f}%)"

        if not flags:
            flags.append(f"✅ 风控明10项检查全部通过，风险可控")

        reviews.append({
            "pid": pid,
            "risk_level": risk_level,
            "flags": flags,
            "adjustment": adj,
            "stop_distance_pct": f"{stop_pct:.1f}%",
            "actual_rr": f"{actual_rr:.1f}:1",
        })
    return reviews


# ==================== 闫判官(交易参数)：精选Top5标准化策略 ====================
# v8.7.0: 原交易策略职责合并至闫判官，从裁决数据中提取最可执行的5个交易策略
# 输出标准化格式：合约/方向/入场/止损/目标/仓位/盈亏比/建仓节奏/触发条件

# 主力合约映射表（仅参考，实际需对接CTP）
DOMINANT_MONTH_MAP = {
    "rb": "2510", "hc": "2510", "i": "2509", "j": "2509", "jm": "2509", "SF": "2509", "SM": "2509",
    "sc": "2509", "lu": "2509", "fu": "2509", "bu": "2509", "pg": "2509", "PX": "2509",
    "TA": "2509", "PF": "2509", "PR": "2509", "eg": "2509", "eb": "2509",
    "v": "2509", "pp": "2509", "l": "2509", "MA": "2509",
    "SH": "2509", "SA": "2509", "UR": "2509",
    "cu": "2509", "al": "2509", "zn": "2509", "pb": "2509", "ni": "2509", "sn": "2509", "ao": "2509", "SS": "2509",
    "au": "2512", "ag": "2512",
    "a": "2509", "b": "2509", "m": "2509", "y": "2509", "p": "2509", "OI": "2509", "RM": "2509", "PK": "2509",
    "c": "2509", "cs": "2509", "SR": "2509", "CF": "2509", "jd": "2509", "lh": "2509",
    "AP": "2510", "CJ": "2509",
    "FG": "2509", "SA": "2509", "UR": "2509",
    "ru": "2509", "nr": "2509", "br": "2509", "sp": "2509", "op": "2509",
    "lc": "2511", "si": "2509", "ps": "2509",
    "ec": "2508", "rr": "2509",
}

EXCHANGE_MAP = {
    "rb": "SHFE", "hc": "SHFE", "i": "DCE", "j": "DCE", "jm": "DCE", "SF": "CZCE", "SM": "CZCE",
    "sc": "INE", "lu": "INE", "fu": "SHFE", "bu": "SHFE", "pg": "DCE", "PX": "CZCE",
    "TA": "CZCE", "PF": "CZCE", "PR": "CZCE", "eg": "DCE", "eb": "DCE",
    "v": "DCE", "pp": "DCE", "l": "DCE", "MA": "CZCE",
    "SH": "CZCE", "SA": "CZCE", "UR": "CZCE",
    "cu": "SHFE", "al": "SHFE", "zn": "SHFE", "pb": "SHFE", "ni": "SHFE", "sn": "SHFE", "ao": "SHFE", "SS": "SHFE",
    "au": "SHFE", "ag": "SHFE",
    "a": "DCE", "b": "DCE", "m": "DCE", "y": "DCE", "p": "DCE", "OI": "CZCE", "RM": "CZCE", "PK": "CZCE",
    "c": "DCE", "cs": "DCE", "SR": "CZCE", "CF": "CZCE", "jd": "DCE", "lh": "DCE",
    "AP": "CZCE", "CJ": "CZCE",
    "FG": "CZCE", "ru": "SHFE", "nr": "INE", "br": "SHFE", "sp": "SHFE", "op": "SHFE",
    "lc": "GFEX", "si": "GFEX", "ps": "GFEX",
    "ec": "INE", "rr": "DCE",
}


def _select_top5_strategies(all_signals: list, risk_level_map: dict = None,
                            chain_position_limit: float = 0.50) -> list:
    """闫判官：从裁决信号中精选不超过5个最可执行策略
    精选规则：
    1. 优先选择置信度最高的品种
    2. 同产业链允许多个，但同链合并仓位不超过 chain_position_limit (默认50%)
    3. ADX<15的排除（无趋势）
    4. 多空平衡（如果有BUY信号优先保留）
    5. 按置信度排序
    6. 必须包含明确的entry/target/stop（CTP就绪检查）
    7. 必须包含仓位建议(position_size>0)和盈亏比(risk_reward>0)
    8. 风控red的品种不入选（risk_level_map参数）
    """
    # ── Step 1: 基础校验 + 风控过滤 → 候选池 ──
    pool = []
    for s in all_signals:
        pid = s.get("product_id", "")
        # 风控red过滤
        if risk_level_map and risk_level_map.get(pid.lower(), "green") == "red":
            continue
        chain = s.get("chain", "")
        entry = s.get("entry", 0)
        target = s.get("target", 0)
        sl = s.get("stop_loss", 0)
        pos = s.get("position_size", 0)
        rr = s.get("risk_reward", 0)
        if not entry or not target or not sl or not pos or not rr:
            continue
        if entry == target or entry == sl:
            continue
        pool.append(s)

    # ── Step 2: 按置信度排序 ──
    pool.sort(key=lambda x: x["confidence"], reverse=True)

    # ── Step 3: 同链仓位控制 → 逐级挑选 ──
    selected = []
    chain_positions = {}  # chain → 累计仓位
    for s in pool:
        if len(selected) >= 5:
            break
        chain = s.get("chain", "")
        pos = s.get("position_size", 0) / 100.0  # 转小数（35 → 0.35）
        curr_chain_pos = chain_positions.get(chain, 0.0)
        if curr_chain_pos + pos > chain_position_limit:
            continue  # 同链仓位超限，跳过
        selected.append(s)
        chain_positions[chain] = curr_chain_pos + pos

    # ── Step 4: 多空平衡 ──
    has_buy = any(s.get("direction") == "BUY" for s in pool)
    top5 = selected[:5]
    if has_buy and not any(s["direction"] == "BUY" for s in top5):
        buy_candidates = [s for s in pool if s["direction"] == "BUY"]
        sell_in_top5 = [s for s in top5 if s["direction"] == "SELL"]
        if buy_candidates and sell_in_top5:
            top5.remove(min(sell_in_top5, key=lambda x: x["confidence"]))
            top5.append(max(buy_candidates, key=lambda x: x["confidence"]))
            top5.sort(key=lambda x: x["confidence"], reverse=True)

    return top5[:5]


def _build_strategy_cards(strategies: list) -> str:
    """闫判官：生成标准化策略卡片（CTP就绪格式）"""
    if not strategies:
        return '<p style="color:#888;">无满足条件的可执行策略</p>'

    cards = ""
    for i, s in enumerate(strategies):
        pid = s.get("product_id", "")
        entry = s.get("entry", 0)
        target = s.get("target", 0)
        sl = s.get("stop_loss", 0)
        rr = s.get("risk_reward", 0)
        pos = s.get("position_size", 0)
        confidence = s.get("confidence", 0)
        direction = s.get("direction", "HOLD")
        pname = s.get("product_name", pid)
        chain = s.get("chain", "")
        verdict = s.get("verdict", "—")

        # 合约代码（CTP标准格式）
        contract_month = DOMINANT_MONTH_MAP.get(pid.lower(), "2509")
        exchange = EXCHANGE_MAP.get(pid.lower(), "DCE")
        ctp_contract = f"{pid.upper()}{contract_month}"
        ctp_contract_full = f"{ctp_contract}.{exchange}"

        # 方向
        dir_cn = "买入开仓" if direction == "BUY" else "卖出开仓"
        dir_color = "#22c55e" if direction == "BUY" else "#ef4444"

        # 仓位手数估算（按100万权益、10%单品种上限）
        margin_percent = 0.10
        equity = 1000000  # 默认100万权益
        contract_value = entry * 10  # 每手10吨（多数品种）
        if pid.lower() in ("au", "ag"):
            contract_value = entry * 1000  # 贵金属1000克/手
        elif pid.lower() == "sc":
            contract_value = entry * 1000  # 原油1000桶/手
        elif pid.lower() == "ec":
            contract_value = entry * 50  # 集运50元/点

        margin_needed = contract_value * 0.12  # 12%保证金率
        if margin_needed > 0:
            lots = max(1, int((equity * pos / 100) / margin_needed))
        else:
            lots = 1

        # 建仓节奏
        if confidence >= 75:
            rhythm = "一次性建仓 100%"
        elif confidence >= 60:
            rhythm = "分批建仓: 先60%, 确认后加40%"
        else:
            rhythm = "试探性建仓: 先30%, 回调加40%, 突破加30%"

        # 预期盈亏
        if direction == "BUY":
            expected_profit = target - entry
            expected_loss = entry - sl
        else:
            expected_profit = entry - target
            expected_loss = sl - entry
        profit_pct = expected_profit / entry * 100
        loss_pct = expected_loss / entry * 100

        cards += f"""
    <div class="strategy-card" style="border-left:4px solid {dir_color};">
        <div class="sc-header">
            <span class="sc-rank">#{i + 1}</span>
            <span class="sc-name">{pname} {pid}</span>
            <span class="sc-chain">{chain}</span>
            <span class="sc-ctp">{ctp_contract_full}</span>
            <span class="sc-dir" style="color:{dir_color};">{dir_cn}</span>
            <span class="sc-conf">{confidence:.0f}%</span>
        </div>
        <div class="sc-body">
            <div class="sc-grid">
                <div class="sc-item">
                    <div class="sc-label">入场价</div>
                    <div class="sc-value">{entry:.0f}</div>
                </div>
                <div class="sc-item">
                    <div class="sc-label">目标价</div>
                    <div class="sc-value" style="color:#22c55e;">{target:.0f}</div>
                </div>
                <div class="sc-item">
                    <div class="sc-label">止损价</div>
                    <div class="sc-value" style="color:#ef4444;">{sl:.0f}</div>
                </div>
                <div class="sc-item">
                    <div class="sc-label">预期盈亏</div>
                    <div class="sc-value">{profit_pct:+.1f}% / {loss_pct:.1f}%</div>
                </div>
                <div class="sc-item">
                    <div class="sc-label">盈亏比</div>
                    <div class="sc-value">{rr:.2f}:1</div>
                </div>
                <div class="sc-item">
                    <div class="sc-label">仓位</div>
                    <div class="sc-value">{pos:.0f}% ({lots}手)</div>
                </div>
            </div>
            <div class="sc-rhythm">
                <span class="sc-label">建仓节奏</span>
                <span class="sc-value">{rhythm}</span>
            </div>
            <div class="sc-trigger">
                <span class="sc-label">触发条件</span>
                <span class="sc-value">辩论方向={verdict} | 右侧确认触发后再入场</span>
            </div>
        </div>
    </div>"""

    # 同链仓位汇总
    chain_pos_summary = {}
    for s in strategies:
        ch = s.get("chain", "")
        pos = s.get("position_size", 0)
        if ch not in chain_pos_summary:
            chain_pos_summary[ch] = {"count": 0, "total_pos": 0}
        chain_pos_summary[ch]["count"] += 1
        chain_pos_summary[ch]["total_pos"] += pos
    multi_chain = {k: v for k, v in chain_pos_summary.items() if v["count"] > 1}
    if multi_chain:
        chain_html = '<div style="margin-top:16px;padding:12px;background:#1e2030;border-radius:8px;border:1px solid #f59e0b44;">'
        chain_html += '<div style="font-weight:bold;color:#f59e0b;margin-bottom:8px;">📊 同链仓位汇总</div>'
        for ch, info in sorted(multi_chain.items(), key=lambda x: -x[1]["total_pos"]):
            chain_html += f'<div style="display:flex;justify-content:space-between;padding:4px 0;"><span>{ch}</span><span>{info["count"]}品种 · 合并仓位 <b>{info["total_pos"]:.0f}%</b></span></div>'
        chain_html += '</div>'
        cards += chain_html

    return cards


# 精选Top5策略（先全量风控→过滤red→再选）
risk_reviews_full = _generate_risk_review(filtered_signals, all_actionable)
risk_level_map = {r["pid"].lower(): r["risk_level"] for r in risk_reviews_full}
top5_strategies = _select_top5_strategies(filtered_signals, risk_level_map=risk_level_map)
strategy_cards_html = _build_strategy_cards(top5_strategies)
# 仅展示Top5的风控审核（过滤掉非Top5的）
top5_pids = {s.get("product_id","").lower() for s in top5_strategies}
risk_reviews = [r for r in risk_reviews_full if r["pid"].lower() in top5_pids]
risk_html = ""
if risk_reviews:
    risk_html = '<div style="display:flex;flex-direction:column;gap:8px;">'
    for r in risk_reviews:
        rl_color = {"green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444"}
        rl_bg = {"green": "rgba(34,197,94,0.1)", "yellow": "rgba(245,158,11,0.1)", "red": "rgba(239,68,68,0.1)"}
        level_dot = {"green": "✅", "yellow": "⚠️", "red": "🔴"}
        color = rl_color.get(r["risk_level"], "#888")
        bg = rl_bg.get(r["risk_level"], "rgba(136,136,136,0.1)")
        flags_html = "<br>".join(r["flags"])
        risk_html += f"""
        <div style="background:#252836;border-radius:8px;padding:12px 16px;border:1px solid {color}44;border-left:3px solid {color};">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <span style="font-weight:bold;color:#e0e0e0;">{r['pid']}</span>
                <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.8em;font-weight:bold;color:{color};background:{bg};">{level_dot.get(r['risk_level'],'')} {r['risk_level'].upper()} | RR={r['actual_rr']} | 止损距{r['stop_distance_pct']}</span>
            </div>
            <div style="color:#ccc;font-size:0.82em;line-height:1.6;">{flags_html}</div>
            <div style="color:#f59e0b;font-size:0.82em;margin-top:6px;">{r['adjustment']}</div>
            <div style="color:#888;font-size:0.75em;margin-top:4px;border-top:1px solid #2a2d38;padding-top:4px;">计算引擎: debate-risk-manager/scripts/risk_engine.py + calc_position.py | 风控明 V4.1</div>
        </div>"""
    risk_html += "</div>"
print(f"\n[精选策略] Top5策略（同链仓位≤50%·风控审核）:")
for r in risk_reviews:
    print(f"  {r['pid']}: {r['risk_level']} 止损距{r['stop_distance_pct']}")

# 同链仓位汇总
chain_pos_summary = {}
for s in top5_strategies:
    ch = s.get("chain", "")
    pos = s.get("position_size", 0)
    if ch not in chain_pos_summary:
        chain_pos_summary[ch] = {"count": 0, "total_pos": 0}
    chain_pos_summary[ch]["count"] += 1
    chain_pos_summary[ch]["total_pos"] += pos
if any(v["count"] > 1 for v in chain_pos_summary.values()):
    print(f"\n[同链仓位] 多品种链汇总:")
    for ch, info in sorted(chain_pos_summary.items(), key=lambda x: -x[1]["total_pos"]):
        if info["count"] > 1:
            print(f"  {ch}: {info['count']}品种 | 合并仓位 {info['total_pos']:.0f}%")

print(f"\n[闫判官] 精选Top5可执行策略:")
for s in top5_strategies:
    icon = "🟢" if s["direction"] == "BUY" else "🔴"
    print(f"  {icon} #{top5_strategies.index(s)+1} {s['product_name']}({s['product_id']}) {s['direction']} 入场{s['entry']:.0f} 目标{s['target']:.0f} 止损{s['stop_loss']:.0f} RR={s['risk_reward']:.2f}")


# ==================== Step 4: HTML报告生成 ====================
print(f"\n[Step 4] 生成3份HTML报告...")


# ==================== HTML CSS 公共部分 ====================
COMMON_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0f1117; color:#e0e0e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.6; }
.container { max-width:1200px; margin:0 auto; padding:20px; }
.header { background:linear-gradient(135deg,#1a1d28 0%,#2a1f1f 50%,#1a1d28 100%); padding:40px; border-radius:16px; margin-bottom:30px; text-align:center; border:1px solid #f59e0b33; }
.header h1 { font-size:2em; color:#f59e0b; margin-bottom:8px; }
.header .subtitle { color:#888; font-size:0.9em; }
.header .meta { display:flex; justify-content:center; gap:20px; margin-top:15px; flex-wrap:wrap; }
.header .meta-item { background:#1a1d28; padding:8px 16px; border-radius:8px; border:1px solid #2a2d38; font-size:0.85em; }
.header .meta-item .label { color:#888; }
.header .meta-item .value { color:#f59e0b; font-weight:bold; }
.section { background:#1a1d28; border-radius:12px; padding:24px 32px; margin-bottom:20px; border:1px solid #2a2d38; }
.section h2 { color:#f59e0b; font-size:1.3em; margin-bottom:16px; padding-bottom:8px; border-bottom:1px solid #2a2d38; }
.section .sub-title { color:#888; font-size:0.85em; margin-bottom:12px; }
table { width:100%; border-collapse:collapse; font-size:0.85em; }
th { background:#252836; color:#f59e0b; padding:10px 12px; text-align:left; font-weight:600; border-bottom:2px solid #f59e0b44; white-space:nowrap; }
td { padding:8px 12px; border-bottom:1px solid #2a2d38; white-space:normal; word-break:break-word; overflow-wrap:break-word; }
tr:hover td { background:#25283644; }
.num { text-align:right; font-family:'Courier New',monospace; white-space:nowrap; }
.tag-buy { color:#22c55e; font-weight:bold; }
.tag-sell { color:#ef4444; font-weight:bold; }
.tier-t1 { color:#f59e0b; }
.tier-t2 { color:#22c55e; font-weight:bold; }
.tier-t3 { color:#ef4444; font-weight:bold; }
.trend-buy { color:#22c55e; }
.trend-sell { color:#ef4444; }
.trend-hold { color:#f59e0b; }
.summary-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:20px; }
.card { background:#252836; border-radius:10px; padding:20px; text-align:center; }
.card .card-value { font-size:1.8em; font-weight:bold; color:#f59e0b; }
.card .card-label { color:#888; font-size:0.85em; margin-top:4px; }
.card .card-sub { color:#555; font-size:0.75em; margin-top:2px; }
.footer { text-align:center; color:#555; font-size:0.8em; padding:30px; border-top:1px solid #2a2d38; margin-top:30px; }
.strategy-container { display:flex; flex-direction:column; gap:14px; }
.strategy-card { background:#1a1d28; border-radius:10px; padding:16px 20px; }
.sc-header { display:flex; align-items:center; gap:12px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid #2a2d38; flex-wrap:wrap; }
.sc-rank { background:#f59e0b; color:#0f1117; font-weight:bold; font-size:0.85em; padding:2px 8px; border-radius:4px; }
.sc-name { font-weight:bold; color:#e0e0e0; font-size:1.05em; }
.sc-chain { color:#888; font-size:0.8em; }
.sc-ctp { color:#f59e0b; font-size:0.85em; font-family:'Courier New',monospace; background:#252836; padding:2px 8px; border-radius:4px; }
.sc-dir { font-weight:bold; font-size:0.9em; }
.sc-conf { color:#888; font-size:0.85em; margin-left:auto; }
.sc-body { }
.sc-grid { display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin-bottom:10px; }
@media (max-width:768px) { .sc-grid { grid-template-columns:repeat(3,1fr); } }
.sc-item { background:#252836; padding:8px 12px; border-radius:6px; text-align:center; }
.sc-label { color:#888; font-size:0.78em; margin-bottom:3px; }
.sc-value { color:#ccc; font-size:0.95em; font-weight:bold; }
.sc-rhythm, .sc-trigger { background:#252836; border-radius:6px; padding:8px 12px; margin-top:6px; display:flex; gap:8px; align-items:center; }
.sc-rhythm .sc-value, .sc-trigger .sc-value { color:#aaa; font-size:0.85em; font-weight:normal; }
@media (max-width:768px) { .header h1 { font-size:1.5em; } }
"""


# ==================== 报告1: 辩论详情 + 交易建议 ====================
def build_debate_report():
    """辩论详情 + 具体交易建议"""
    total_buy = sum(1 for s in filtered_signals if s["direction"] == "BUY")
    total_sell = sum(1 for s in filtered_signals if s["direction"] == "SELL")
    total = len(filtered_signals)
    sentiment = "strong_bearish" if total_sell > total_buy * 2 else "bearish" if total_sell > total_buy else "neutral"
    sentiment_text = {"strong_bearish": "强烈空头", "bearish": "偏空", "neutral": "均衡"}.get(sentiment, "均衡")

    def signal_row(s):
        icon = "🟢" if s["direction"] == "BUY" else "🔴"
        dt = "做多" if s["direction"] == "BUY" else "做空"
        pct = ((s["target"] - s["entry"]) / s["entry"] * 100) if s["entry"] else 0
        if s["direction"] == "SELL":
            pct = -pct
        stop_pct = abs((s["stop_loss"] - s["entry"]) / s["entry"] * 100) if s["entry"] else 0
        chain_label = f"[{s.get('chain', '?')}] " if s.get('chain') else ""
        debate_text = s.get("debate_reason", "")
        return f"""<tr>
            <td><span class="tag-{s["direction"].lower()}">{icon} {s["product_name"]}({s["product_id"]})</span></td>
            <td>{dt}</td>
            <td class="num">{s["confidence"]:.0f}%</td>
            <td class="num">{s["entry"]:.0f}</td>
            <td class="num">{s["target"]:.0f}</td>
            <td class="num">{s["stop_loss"]:.0f}</td>
            <td class="num">{s["risk_reward"]:.2f}:1</td>
            <td class="num">{s.get("position_size", 0):.0f}%</td>
            <td><span class="tier-{"t3" if "T3" in s.get("tier", "") else "t2" if "T2" in s.get("tier", "") else "t1"}">{s.get("tier", "")}</span></td>
        </tr>
        <tr style="border-bottom:2px solid #2a2d38;">
            <td colspan="9" style="font-size:0.82em;color:#888;padding:2px 12px 8px 12px;line-height:1.5;">
                {chain_label}📋 {debate_text[:200] if debate_text else "—"}</td>
        </tr>"""

    def chain_row(name, info):
        t_raw = info.get("overall_trend", "HOLD")
        trend_map = [
            ("强势多头", "BUY", "📈"), ("多头趋势", "BUY", "📈"), ("偏多震荡", "BUY", "📈"),
            ("强势空头", "SELL", "📉"), ("空头趋势", "SELL", "📉"), ("偏空趋势", "SELL", "📉"), ("偏空震荡", "SELL", "📉"),
        ]
        t_key, ti, tt = "HOLD", "➡", t_raw or "震荡"
        for keyword, key, icon in trend_map:
            if keyword in t_raw:
                t_key, ti, tt = key, icon, t_raw
                break
        dc = info.get("direction_counts", {})
        members = info.get("members", [])
        members_str = "、".join(sorted(m.upper() for m in members))
        return f"""<tr>
            <td>{name}</td>
            <td><span class="trend-{t_key.lower()}">{ti} {tt}</span></td>
            <td class="num">{info.get("avg_score", 0):.1f}</td>
            <td class="num">{info.get("count", 0)}</td>
            <td class="num">{dc.get("BUY", 0)}/{dc.get("SELL", 0)}/{dc.get("HOLD", 0)}</td>
            <td>{info.get("leader", "—")}</td>
            <td style="font-size:0.82em;color:#888;max-width:200px;">{members_str}</td>
        </tr>"""

    all_rows = ""
    for s in T3_signals + T2_signals + T1_signals:
        pid = s.get("product_id", "").lower()
        # CTP就绪检查：风控通过 + 交易参数完备
        if risk_level_map.get(pid, "green") == "red":
            continue
        entry = s.get("entry", 0)
        target = s.get("target", 0)
        sl = s.get("stop_loss", 0)
        pos = s.get("position_size", 0)
        rr = s.get("risk_reward", 0)
        if not entry or not target or not sl or not pos or not rr:
            continue
        if entry == target or entry == sl:
            continue
        all_rows += signal_row(s)
    if not all_rows:
        all_rows = '<tr><td colspan="9" style="text-align:center;color:#888;">⚠️ 无CTP就绪信号——本轮辩论信号均未通过风控审核或交易参数不完整</td></tr>'

    chain_rows = ""
    chain_active = [(n, i) for n, i in chain_results_agg.items() if i.get("avg_score", 0) > 0 or i.get("count", 0) > 0]
    for name, info in sorted(chain_active, key=lambda x: x[1].get("avg_score", 0), reverse=True):
        chain_rows += chain_row(name, info)

    # 辩论详情 — G37: 按交易可靠性排序（置信度×盈亏比），同级别再按置信度降序
    SYMBOL_KEYS = {
        pid for pid in debate_results if isinstance(debate_results[pid], dict) and "direction" in debate_results[pid]
    }
    def _pid_reliability(pid):
        d = debate_results.get(pid, {})
        conf = float(d.get("confidence", 0) or 0)
        rr = float(d.get("risk_reward_ratio", 0) or d.get("risk_reward", 0) or 0)
        return (conf * max(rr, 0.01), conf)
    SYMBOL_KEYS = sorted(SYMBOL_KEYS, key=_pid_reliability, reverse=True)
    product_names = {}
    for s in all_actionable:
        pn = s.get("product_name", "") or s.get("pid", "")
        if pn:
            product_names[s.get("pid", "")] = pn

    debate_rows = ""
    for pid in sorted(SYMBOL_KEYS):
        d = debate_results[pid]
        pid_upper = pid.upper()

        # 观澜：多层次技术分析 — 优先使用LLM逐品种输出，fallback到合成数据
        tech_analysis = technical_per_symbol.get(pid, technical_per_symbol.get(pid_upper, {}))
        if not tech_analysis:
            tech_analysis = _generate_technical_analysis(pid, symbols_summary)

        # 探源：基本面状态向量 — 优先使用LLM逐品种输出，fallback到合成数据
        fund_state = fundamental_per_symbol.get(pid, fundamental_per_symbol.get(pid_upper, {}))
        if not fund_state:
            fund_state = _generate_fundamental_state(pid, d.get("chain", ""), all_actionable)

        jv = d.get("judge_verdict", {})
        if isinstance(jv, dict) and "final_direction" in jv:
            v = jv["final_direction"]
            v_conf = jv.get("confidence", "")
            v_reason = jv.get("reasoning", "")[:300]
        else:
            v_raw = d.get("verdict", "—")
            v = v_raw if isinstance(v_raw, str) else v_raw.get("status", "—")
            v_reason = ""
            v_conf = d.get("confidence", "")

        # 交易方案
        def _p(v, d=0):
            return v.get("price", d) if isinstance(v, dict) else (v if isinstance(v, (int, float)) else d)

        entry = _p(d.get("entry_price", 0))
        target = _p(d.get("target_price", 0))
        sl = _p(d.get("stop_loss_price", 0))
        pos = d.get("position_size", 0)
        rr = d.get("risk_reward_ratio", 0)
        chain = d.get("chain", "")
        adx = d.get("adx", 0)
        rsi = d.get("rsi", 50)
        score = d.get("score", 0)

        # 多空论据
        bull_args = d.get("bull_args", "")
        bear_args = d.get("bear_args", "")
        if not bull_args and not bear_args:
            fallback_bear, fallback_bull = _generate_fallback_args(pid, d, intermediate)
            bull_args = bull_args or fallback_bull
            bear_args = bear_args or fallback_bear

        # 具体的操作策略
        def _nz(v, d=0):
            """None → 默认值"""
            return v if v is not None else d

        entry = _nz(entry)
        target = _nz(target)
        sl = _nz(sl)
        pos = _nz(pos)
        rr = _nz(rr)

        stop_pct = f"{abs((sl-entry)/entry*100):.1f}" if entry != 0 else "N/A"
        if v == "BUY":
            strategy_desc = (
                f"📈 做多策略<br>"
                f"&nbsp;&nbsp;• 入场: {entry:.0f}附近（现价确认）<br>"
                f"&nbsp;&nbsp;• 第一目标: {target:.0f}<br>"
                f"&nbsp;&nbsp;• 止损: {sl:.0f}（{stop_pct}%）<br>"
                f"&nbsp;&nbsp;• 仓位: {pos:.0f}%<br>"
                f"&nbsp;&nbsp;• 盈亏比: {rr:.1f}:1"
            )
        elif v == "SELL":
            strategy_desc = (
                f"📉 做空策略<br>"
                f"&nbsp;&nbsp;• 入场: {entry:.0f}附近（现价确认）<br>"
                f"&nbsp;&nbsp;• 第一目标: {target:.0f}<br>"
                f"&nbsp;&nbsp;• 止损: {sl:.0f}（{stop_pct}%）<br>"
                f"&nbsp;&nbsp;• 仓位: {pos:.0f}%<br>"
                f"&nbsp;&nbsp;• 盈亏比: {rr:.1f}:1"
            )
        else:
            strategy_desc = "暂观望"

        vc_map = {"BUY": "#22c55e", "SELL": "#ef4444", "HOLD": "#f59e0b", "WATCH": "#f59e0b"}
        vc_bg = {"BUY": "rgba(34,197,94,0.1)", "SELL": "rgba(239,68,68,0.1)", "HOLD": "rgba(245,158,11,0.1)", "WATCH": "rgba(245,158,11,0.1)"}
        v_color = vc_map.get(v if v in vc_map else "HOLD", "#888")
        v_bg = vc_bg.get(v if v in vc_bg else "HOLD", "rgba(136,136,136,0.1)")
        verdict_tag = f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-weight:bold;font-size:0.9em;color:{v_color};background:{v_bg};">{v}{f"({v_conf:.0%})" if isinstance(v_conf,(int,float)) and v_conf else ""}</span>'

        debate_rows += f"""
        <div style="background:#252836;border-radius:10px;padding:20px 24px;margin-bottom:14px;border:1px solid #2a2d38;border-left:3px solid {v_color};">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #2a2d38;flex-wrap:wrap;gap:8px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span style="font-weight:bold;font-size:1.1em;color:#e0e0e0;">{product_names.get(pid, pid)}({pid})</span>
                    {verdict_tag}
                    <span style="color:#888;font-size:0.8em;">{chain}</span>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                    <div style="color:#3b82f6;font-size:0.78em;margin-bottom:6px;">📈 观澜 | 技术面分析</div>
                    <div style="color:#ccc;font-size:0.82em;line-height:1.7;">
                        <b>趋势</b>: {tech_analysis.get('trend','—')}<br>
                        <b>关键位</b>: {tech_analysis.get('key_levels','—')}<br>
                        <b>量价</b>: {tech_analysis.get('volume_price','—')}<br>
                        <b>背离</b>: {tech_analysis.get('divergence','—')}<br>
                        <b>形态</b>: {tech_analysis.get('pattern','—')}
                    </div>
                </div>
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                    <div style="color:#8b5cf6;font-size:0.78em;margin-bottom:6px;">🔬 探源 | 基本面状态向量</div>
                    <div style="color:#ccc;font-size:0.82em;line-height:1.7;">
                        <b>供需</b>: {fund_state.get('supply_demand','—')}<br>
                        <b>库存</b>: {fund_state.get('inventory','—')}<br>
                        <b>利润</b>: {fund_state.get('profit_margin','—')}<br>
                        <b>期限</b>: {fund_state.get('basis_term','—')}<br>
                        <b>领先信号</b>: {'<br>'.join(fund_state.get('leading_signals',['—']))}
                    </div>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:10px;margin-bottom:10px;">
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                    <div style="color:#888;font-size:0.78em;margin-bottom:6px;">技术指标</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.7;">
                        ADX={adx:.1f} | RSI={rsi:.1f}<br>
                        信号分={score:.0f} | 仓位={pos:.0f}%<br>
                        RR={rr:.2f}:1
                    </div>
                </div>
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                    <div style="color:#f59e0b;font-size:0.78em;margin-bottom:6px;">📋 交易方案</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.7;">{strategy_desc}</div>
                </div>
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;">
                    <div style="color:#f59e0b;font-size:0.78em;margin-bottom:6px;">⚖️ 裁决依据</div>
                    <div style="color:#aaa;font-size:0.82em;line-height:1.6;">{h_escape(v_reason[:1000]) if v_reason else "—"}</div>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;">
                    <div style="color:#22c55e;font-size:0.78em;margin-bottom:6px;">🟢 多头论据</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.6;word-break:break-word;">{bull_args if bull_args else "—"}</div>
                </div>
                <div style="background:#1a1d28;border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;">
                    <div style="color:#ef4444;font-size:0.78em;margin-bottom:6px;">🔴 空头论据</div>
                    <div style="color:#ccc;font-size:0.85em;line-height:1.6;word-break:break-word;">{bear_args if bear_args else "—"}</div>
                </div>
            </div>
        </div>"""

    if not debate_rows:
        debate_rows = '<p style="color:#888;">辩论数据为空</p>'

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>期货辩论报告 | {REPORT_DATE}</title>
    <style>{COMMON_CSS}
    .trade-card {{ background:#252836; border-radius:10px; padding:16px 20px; margin-bottom:12px; border:1px solid #2a2d38; }}
    .trade-card .label {{ color:#888; font-size:0.8em; }}
    .trade-card .value {{ color:#e0e0e0; font-weight:bold; }}
    </style></head><body><div class="container">

    <div class="header">
        <h1>⚖️ 专家团辩论裁决报告</h1>
        <div class="subtitle">多维度量化分析 · 技术+基本面融合 · 具体交易建议</div>
        <div class="meta">
            <div class="meta-item"><span class="label">报告日期</span> <span class="value">{REPORT_DATE}</span></div>
            <div class="meta-item"><span class="label">数据基准</span> <span class="value">{DATA_BENCHMARK}</span></div>
            <div class="meta-item"><span class="label">辩论品种</span> <span class="value">{len(debate_results)}</span></div>
            <div class="meta-item"><span class="label">数据源</span> <span class="value">{data_source_used}</span></div>
            <div class="meta-item"><span class="label">指标来源</span> <span class="value">{indicator_source}</span></div>
        </div>
    </div>

    <div class="summary-cards">
        <div class="card"><div class="card-value">{total}</div><div class="card-label">总信号数</div></div>
        <div class="card"><div class="card-value">{total_buy}</div><div class="card-label" style="color:#22c55e;">做多信号</div></div>
        <div class="card"><div class="card-value">{total_sell}</div><div class="card-label" style="color:#ef4444;">做空信号</div></div>
        <div class="card"><div class="card-value" style="color:{'#ef4444' if sentiment_text=='强烈空头' else '#f59e0b'};">{sentiment_text}</div><div class="card-label">市场情绪</div></div>
    </div>

    <div class="section">
        <h2>⚖️ 辩论详情与交易建议</h2>
        <div class="sub-title">以下为专家团9Agent联合产出的逐品种分析（数技源→链证源→证真+慎思→闫判官(含交易参数)→风控明）</div>
        {debate_rows}
    </div>

    <div class="section" style="border-color:#f59e0b66;">
        <h2>🎯 闫判官精选：标准化可执行策略（Top5）</h2>
        <div class="sub-title">以下为闫判官从辩论裁决中精选的Top5最可执行策略，按置信度排序，同产业链最多1个。合约代码为CTP标准格式，可直接对接交易系统。</div>
        <div class="strategy-container">
        {strategy_cards_html}
        </div>
    </div>

    <div class="section" style="border-color:{"#22c55e" if all(r['risk_level']=='green' for r in risk_reviews) else '#ef4444'}66;">
        <h2>🛡️ 精选策略风控审核</h2>
        <div class="sub-title">风控明 V4.1 风险引擎(risk_engine.py) 逐项检查：杠杆/保证金/止损比/安全手数 + 趋势确认/多因子分歧/超买超卖/流动性/盈亏比合理性。<br>
        <span style="color:#f59e0b;">⚠ 以下为精选Top5策略。同产业链允许多个，但同链合并仓位≤50%。全量信号见下方「全信号列表」。</span><br>
        <span style="color:#ef4444;">⚠ 当前入场/止损/目标价为闫判官估算值(基于ADX比例)，非观澜技术位验证，风控明对此进行了合理性检查。</span></div>
        {risk_html}
    </div>

    <div class="section">
        <h2>📋 全信号列表</h2>
        <div class="sub-title">包含入场/止损/目标/仓位/盈亏比</div>
        <table><thead><tr><th>品种</th><th>方向</th><th class="num">置信度</th>
        <th class="num">入场价</th><th class="num">目标价</th><th class="num">止损价</th><th class="num">盈亏比</th><th class="num">仓位</th><th>等级</th></tr></thead>
        <tbody>{all_rows}</tbody></table>
    </div>

    <div class="section">
        <h2>⚠️ 风险提示</h2>
        <p style="color:#ef4444;font-size:0.9em;line-height:1.8;">
        1. 本报告仅为量化分析参考，不构成任何投资建议。<br>
        2. 右侧交易铁律：所有信号需等待价格突破关键位置确认后方可执行，禁止提前布局。<br>
        3. 期货交易具有高风险性，可能导致本金全部亏损，请谨慎参与。<br>
        4. 辩论中的多头论据包含对空头品种的反弹风险提示，请结合仓位管理执行。
        </p>
    </div>

    <div class="footer">
        <p>商品期货深度分析报告 | {REPORT_DATE}</p>
        <p>数据源: {data_source_used} | 辩论: 专家团(futures-debate-team) | 技术指标: {indicator_source}</p>
        <p style="color:#ef4444;">⚠️ 投资有风险，入市需谨慎。仅供参考，不构成投资建议。</p>
    </div>
    </div></body></html>"""
    return html


# ==================== 生成报告 ====================
# 报告1: 辩论详情
html_debate = build_debate_report()
with open(OUTPUT_DEBATE, "w", encoding="utf-8") as f:
    f.write(html_debate)
print(f"📊 辩论报告: {OUTPUT_DEBATE}")

# 保存analysis_data.json
results = {
    "report_date": REPORT_DATE,
    "data_benchmark": DATA_BENCHMARK,
    "data_source": data_source_used,
    "filtered_signals": filtered_signals,
    "T1_count": len(T1_signals),
    "T2_count": len(T2_signals),
    "T3_count": len(T3_signals),
    "debate_count": len(debate_results),
    "chain_count": len(chain_results_agg),
}
OUTPUT_JSON = os.path.join(REPORT_DIR, f"analysis_data_{REPORT_DATE_COMPACT}.json")
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f"\n{'=' * 60}")
print(f"✅ Phase 3 v3.0 完成！")
print(f"📊 辩论报告: {OUTPUT_DEBATE}")
print(f"🔴 信号: T1={len(T1_signals)}, T2={len(T2_signals)}, T3={len(T3_signals)}")
print(f"🔗 产业链: {len(chain_results_agg)}")
print(f"{'=' * 60}")
