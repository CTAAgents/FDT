#!/usr/bin/env python3
"""
记忆写入器 — 竞态安全的Agent日志管理（P0-4）
================================================
解决DAG并行调度下10个Agent共用 debate_journal.json 的读写竞态问题。

设计原则：
1. 每个Agent写入独立文件：memory/{agent_id}_{round}.json
2. 明鉴秋汇总阶段统一 merge 到 debate_results.json
3. 过渡期使用 SQLite 本地时序库，支持并发写入
4. 每日自动校验日志完整性

用法:
    from memory_writer import MemoryWriter
    writer = MemoryWriter(round_id="RB_20260705")
    writer.write(agent_id="futures-technical-researcher", data={...})
    
    # 汇总
    merged = writer.merge_all()
    writer.validate()
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from scripts.unified_logger import get_logger

_logger = get_logger("memory_writer")


class MemoryWriter:
    """竞态安全的记忆写入器，每个Agent独立文件 + SQLite 备份。"""

    def __init__(self, round_id: str, base_dir: str = None):
        """
        Args:
            round_id: 本轮辩论唯一ID（如 "RB_20260705"）
            base_dir: 记忆根目录（默认 ~/.workbuddy/plugins/.../memory/）
        """
        self.round_id = round_id
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            # 自动定位到项目 memory/ 目录
            self.base_dir = Path(__file__).parent.parent / "memory"

        self.round_dir = self.base_dir / round_id
        self.round_dir.mkdir(parents=True, exist_ok=True)

        # SQLite 数据库路径
        self.db_path = self.round_dir / "debate_journal.db"
        self._init_sqlite()

    def _init_sqlite(self):
        """初始化SQLite表结构。"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(round_id, agent_id, data_type)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_round_agent 
                ON agent_logs(round_id, agent_id)
            """)
            conn.commit()

    def write(self, agent_id: str, data: Dict[str, Any], data_type: str = "output") -> str:
        """
        写入Agent日志（文件 + SQLite双写）。

        Args:
            agent_id: Agent标识（如 "futures-technical-researcher"）
            data: 结构化数据字典
            data_type: 数据类型（output/analysis/decision）

        Returns:
            写入的文件路径
        """
        timestamp = datetime.now().isoformat()

        # 1. 写入独立JSON文件（每个Agent一个文件）
        file_name = f"{agent_id}_{data_type}.json"
        file_path = self.round_dir / file_name

        record = {
            "round_id": self.round_id,
            "agent_id": agent_id,
            "data_type": data_type,
            "timestamp": timestamp,
            "data": data,
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 2. 写入SQLite（支持并发写入）
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_logs (round_id, agent_id, timestamp, data_type, data_json)
                VALUES (?, ?, ?, ?, ?)
            """,
                (self.round_id, agent_id, timestamp, data_type, json.dumps(data, ensure_ascii=False)),
            )
            conn.commit()

        return str(file_path)

    def read(self, agent_id: str, data_type: str = "output") -> Optional[Dict[str, Any]]:
        """读取指定Agent的日志。"""
        file_path = self.round_dir / f"{agent_id}_{data_type}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def merge_all(self) -> Dict[str, Any]:
        """
        汇总所有Agent日志，合并为 debate_results.json 格式。

        Returns:
            {"round_id": str, "agents": {agent_id: data}, "metadata": {...}}
        """
        result = {
            "round_id": self.round_id,
            "agents": {},
            "metadata": {
                "merged_at": datetime.now().isoformat(),
                "agent_count": 0,
            },
        }

        # 从SQLite读取（更可靠，支持并发）
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT agent_id, data_type, data_json FROM agent_logs WHERE round_id = ?", (self.round_id,)
            )
            for row in cursor.fetchall():
                agent_id, data_type, data_json = row
                if agent_id not in result["agents"]:
                    result["agents"][agent_id] = {}
                result["agents"][agent_id][data_type] = json.loads(data_json)

        # 补充从文件读取（SQLite可能缺失的）
        for json_file in self.round_dir.glob("*_*.json"):
            if json_file.name == "debate_results.json":
                continue
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    record = json.load(f)
                agent_id = record.get("agent_id", "")
                data_type = record.get("data_type", "output")
                if agent_id and agent_id not in result["agents"]:
                    result["agents"][agent_id] = {}
                if agent_id:
                    result["agents"][agent_id][data_type] = record.get("data", {})
            except (json.JSONDecodeError, KeyError):
                pass

        result["metadata"]["agent_count"] = len(result["agents"])

        # 保存汇总结果
        result_path = self.round_dir / "debate_results.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def validate(self) -> Dict[str, Any]:
        """
        校验日志完整性：检查缺失、重复、损坏。

        Returns:
            {"is_valid": bool, "missing": [str], "duplicates": [str], "corrupted": [str]}
        """
        expected_agents = [
            "futures-datatech",
            "futures-technical-researcher",
            "futures-fundamental-researcher",
            "futures-chain-analyst",
            "futures-affirmative-debater",
            "futures-opposition-debater",
            "futures-trading-strategist",
            "futures-risk-manager",
            "futures-judge",
        ]

        missing = []
        duplicates = []
        corrupted = []

        for agent_id in expected_agents:
            file_path = self.round_dir / f"{agent_id}_output.json"
            if not file_path.exists():
                missing.append(agent_id)
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 检查重复（同一Agent多个文件）
                matching = list(self.round_dir.glob(f"{agent_id}_*.json"))
                if len(matching) > 2:  # 正常只有 _output.json + 可能的手动文件
                    duplicates.append(f"{agent_id} ({len(matching)} files)")
            except json.JSONDecodeError:
                corrupted.append(agent_id)

        is_valid = len(missing) == 0 and len(corrupted) == 0

        result = {
            "is_valid": is_valid,
            "missing": missing,
            "duplicates": duplicates,
            "corrupted": corrupted,
            "checked_at": datetime.now().isoformat(),
        }

        # 保存校验报告
        report_path = self.round_dir / "validation_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result


# ── 兼容旧API ──
def append_debate_journal(agent_id: str, data_type: str, data: Dict[str, Any], round_id: str = None):
    """兼容旧版 debate_journal 写入接口。"""
    if round_id is None:
        round_id = datetime.now().strftime("%Y%m%d")
    writer = MemoryWriter(round_id=round_id)
    return writer.write(agent_id, data, data_type)


def append_debate_index(round_id: str, symbols: List[str], direction: str):
    """兼容旧版 debate_index 写入接口。"""
    writer = MemoryWriter(round_id=round_id)
    return writer.write("team-lead", {"symbols": symbols, "direction": direction}, "index")


# ── D1 解锁：debate_record 写入 + held-out judge 一致性 ──
# canonical = memory/debate_journal.json；skills/memory/ 副本同步写入（不删除）
_MEMORY_JOURNAL = Path(__file__).parent.parent / "memory" / "debate_journal.json"
_SKILLS_JOURNAL = Path(__file__).parent.parent / "skills" / "memory" / "debate_journal.json"
_journal_lock = None  # 延迟初始化的线程锁


def _append_journal_entry(path: Path, record: Dict[str, Any]):
    """向指定 journal 的 entries 追加一条记录（带锁，先读后写）。"""
    global _journal_lock
    if _journal_lock is None:
        import threading
        _journal_lock = threading.Lock()
    with _journal_lock:
        data = {"entries": []}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {"entries": []}
        if "entries" not in data:
            data["entries"] = []
        data["entries"].append(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def compute_heldout_coherence(pro_args: List[Dict], con_args: List[Dict], verdict: Dict) -> Dict[str, Any]:
    """确定性 held-out judge 一致性 rubric（无 LLM 时的可重放实现）。

    真实 held-out judge（agents/futures-judge-heldout.md）会写出自己的
    held_out_judge JSON；本函数作为种子回填/回退实现，保证 D1 可计算。
    评分维度（满分 1.0）：
      +0.4 胜方论据有≥2条带 evidence
      +0.1 败方论据被显式记录（说明 judge 看见了反方）
      +0.2 胜方论据 evidence 数 ≥ 败方（论据质量偏向裁决方向）
      +0.1 全部论据均带 evidence（完整性）
    """
    pro = pro_args or []
    con = con_args or []
    direction = str(verdict.get("direction", "")).lower()
    winner_is_pro = direction in ("bull", "long", "buy") or str(verdict.get("winner", "")).startswith(("pro", "bull", "证真", "long"))
    winner_side = pro if winner_is_pro else con
    loser_side = con if winner_is_pro else pro

    score = 0.0
    notes = []
    pro_ev = [a for a in pro if a.get("evidence")]
    con_ev = [a for a in con if a.get("evidence")]
    if len(pro_ev) >= 2 or (winner_is_pro and len(pro_ev) >= 1):
        score += 0.4
        notes.append("胜方论据有证据支撑")
    elif len(pro) >= 1:
        score += 0.2
    if loser_side:
        score += 0.1
        notes.append("反方论据被记录")
    if len(pro_ev) >= len(con_ev):
        score += 0.2
        notes.append("论据质量偏向裁决方向")
    if pro and con and all(a.get("evidence") for a in pro + con):
        score += 0.1
        notes.append("论据完整")
    return {
        "coherence_score": round(min(1.0, score), 3),
        "rubric": "deterministic-seed",
        "notes": notes,
    }


def append_debate_record(record: Dict[str, Any], round_id: str = None) -> Dict[str, Any]:
    """写入升级后的 debate_record 条目（含 pro_args/con_args/verdict/held_out_judge）。

    canonical = memory/debate_journal.json；skills/memory/ 副本同步写入（不删除旧副本）。
    """
    rec = dict(record)
    rec.setdefault("action", "debate_record")
    rec.setdefault("agent", "futures-debate-team-team-lead")
    rec.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if round_id:
        rec.setdefault("round_id", round_id)
    _append_journal_entry(_MEMORY_JOURNAL, rec)
    if _SKILLS_JOURNAL.exists():
        _append_journal_entry(_SKILLS_JOURNAL, rec)
    return rec


def build_seed_debate_record_from_verdict(verdict_entry: Dict, followup: Dict = None) -> Dict[str, Any]:
    """从 journal 的 verdict 条目重建 seed debate_record（历史回填用）。

    仅用 verdict_entry 中真实存在的信号字段重建 pro/con 论据，绝不虚构价格/数据。
    标记 seed=True / reconstructed=True，供下游透明识别。
    """
    sym = verdict_entry.get("symbol", "?")
    direction = "bull" if str(verdict_entry.get("direction", "")).upper() in ("BUY", "BULL", "LONG") else "bear"
    adx = verdict_entry.get("adx", 0)
    atr = verdict_entry.get("atr", 0)
    l1l4_dir = verdict_entry.get("l1l4_direction", "")
    l1l4_cons = verdict_entry.get("l1l4_cons", 0)
    factor_dir = verdict_entry.get("factor_direction", "")
    reasoning = verdict_entry.get("reasoning", "")

    pro_args, con_args = [], []
    if direction == "bear":
        pro_args.append({"id": f"{sym}-pro1", "claim": f"ADX={adx} 极强趋势，趋势运行顺畅", "evidence": f"ADX={adx}", "source": "技术分析评分/信号"})
        if l1l4_cons:
            pro_args.append({"id": f"{sym}-pro2", "claim": f"技术分析评分 CONS={l1l4_cons} 全层一致看空", "evidence": f"l1l4_cons={l1l4_cons}, l1l4_dir={l1l4_dir}", "source": "技术分析评分"})
        con_args.append({"id": f"{sym}-con1", "claim": f"Factor 中性({factor_dir})，无因子共振确认", "evidence": f"factor_direction={factor_dir}", "source": "因子择时"})
        con_args.append({"id": f"{sym}-con2", "claim": f"ADX={adx} 趋势运行过远，追空末端风险", "evidence": f"ADX={adx}", "source": "技术分析评分"})
    else:
        pro_args.append({"id": f"{sym}-pro1", "claim": f"ADX={adx} 强势多头趋势", "evidence": f"ADX={adx}", "source": "技术分析评分/信号"})
        if l1l4_cons:
            pro_args.append({"id": f"{sym}-pro2", "claim": f"技术分析评分 CONS={l1l4_cons} 全层一致看多", "evidence": f"l1l4_cons={l1l4_cons}", "source": "技术分析评分"})
        con_args.append({"id": f"{sym}-con1", "claim": f"Factor 中性({factor_dir})，无因子共振确认", "evidence": f"factor_direction={factor_dir}", "source": "因子择时"})

    verdict = {
        "direction": direction,
        "confidence": verdict_entry.get("confidence", "中"),
        "winner": verdict_entry.get("winner", "short_win" if direction == "bear" else "long_win"),
        "reasoning": reasoning,
    }
    held = compute_heldout_coherence(pro_args, con_args, verdict)

    return {
        "round_id": verdict_entry.get("round", f"seed_{sym}"),
        "symbol": sym,
        "variety": sym.split(".")[0].upper(),
        "signal_type": verdict_entry.get("signal_type", "channel_breakout"),
        "pro_args": pro_args,
        "con_args": con_args,
        "verdict": verdict,
        "held_out_judge": held,
        "volatility": {"adx": adx, "atr": atr},
        "seed": True,
        "reconstructed": True,
        "inferred_fields": ["signal_type"] if "signal_type" not in verdict_entry else [],
        "note": "历史回填：论据由 verdict 条目的真实信号字段重建，held_out_judge 为确定性种子rubric（非 live LLM judge）",
    }


def backfill_debate_records_from_history() -> int:
    """扫描 journal 中 action=='verdict' 条目，回填缺失的 debate_record。

    返回新增条数。幂等：已存在同 (round_id, symbol) 的 debate_record 则跳过。
    """
    if not _MEMORY_JOURNAL.exists():
        return 0
    journal = json.loads(_MEMORY_JOURNAL.read_text(encoding="utf-8"))
    entries = journal.get("entries", [])
    existing = {(e.get("round_id"), e.get("symbol")) for e in entries if e.get("action") == "debate_record"}
    followup = None
    fp = _MEMORY_JOURNAL.parent / "execution_followup.json"
    if fp.exists():
        try:
            followup = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            followup = None

    added = 0
    for e in entries:
        if e.get("action") != "verdict":
            continue
        key = (e.get("round"), e.get("symbol"))
        if key in existing:
            continue
        rec = build_seed_debate_record_from_verdict(e, followup)
        append_debate_record(rec, round_id=e.get("round"))
        existing.add((rec.get("round_id"), rec.get("symbol")))
        added += 1
    return added


# ── 知识库集成 ─────────────────────────────────
# 从辩论记录中自动提取品种知识并写入 knowledge/ 目录

def append_knowledge_extraction(
    variety: str,
    debate_record: Dict[str, Any],
    verdict: Dict[str, Any],
    technical_data: Optional[Dict] = None,
    fundamental_data: Optional[Dict] = None,
    trading_plan: Optional[Dict] = None,
) -> Dict[str, Any]:
    """从辩论记录中提取品种知识并写入 knowledge/ 目录。

    由明鉴秋在 P6 汇总后自动调用。
    质量门控由 extract_knowledge.py 内部管理。

    Args:
        variety: 品种代码（小写）
        debate_record: 完整辩论记录（含 pro_args/con_args）
        verdict: 闫判官裁决
        technical_data: 观澜产出（可选）
        fundamental_data: 探源产出（可选）
        trading_plan: 闫判官方案（可选）

    Returns:
        extract_knowledge.py 的返回 dict（含 patterns_added 等）
    """
    try:
        from scripts.extract_knowledge import KnowledgeExtractor
        extractor = KnowledgeExtractor()
        return extractor.extract_from_debate(
            variety=variety,
            debate_record=debate_record,
            verdict=verdict,
            technical_data=technical_data,
            fundamental_data=fundamental_data,
            trading_plan=trading_plan,
        )
    except Exception as e:
        _logger.warning(f"知识萃取失败 {variety}: {e}")
        return {"skipped_reason": str(e), "error": True}


def batch_knowledge_extraction(
    debate_results: Dict[str, Any],
) -> Dict[str, List[Dict]]:
    """从辩论结果中批量提取知识。

    由明鉴秋在 P6 汇总后调用，遍历所有裁决品种。

    Args:
        debate_results: P6 汇总的 debate_results.json 内容

    Returns:
        {variety: [result_dict, ...]}
    """
    from scripts.extract_knowledge import KnowledgeExtractor
    extractor = KnowledgeExtractor()
    results: Dict[str, List[Dict]] = {}

    verdicts = debate_results.get("verdicts", {})
    for variety, v_data in verdicts.items():
        debate_record = v_data.get("debate_record", {})
        verdict = v_data.get("verdict", {})
        tech = v_data.get("technical", {})
        fund = v_data.get("fundamental", {})
        plan = v_data.get("trading_plan", {})

        r = extractor.extract_from_debate(
            variety=variety,
            debate_record=debate_record,
            verdict=verdict,
            technical_data=tech,
            fundamental_data=fund,
            trading_plan=plan,
        )
        results.setdefault(variety, []).append(r)

    return results


if __name__ == "__main__":
    # 测试
    writer = MemoryWriter(round_id="TEST_20260705")
    writer.write("futures-technical-researcher", {"adx": 25, "trend": "bull"})
    writer.write("futures-risk-manager", {"verdict": "green"})
    merged = writer.merge_all()
    print(f"Merged: {json.dumps(merged, ensure_ascii=False, indent=2)}")
    validation = writer.validate()
    print(f"Validation: {json.dumps(validation, ensure_ascii=False, indent=2)}")

    # 测试知识萃取
    from scripts.memory_writer import append_knowledge_extraction
    test_record = {
        "round_id": "test_mw",
        "pro_args": [{"claim": "ADX=45趋势确认", "evidence": "ADX=45", "source": "signal"}],
        "con_args": [{"claim": "RSI接近超买", "evidence": "RSI=68", "source": "signal"}],
        "volatility": {"adx": 45, "atr": 120},
    }
    test_verdict = {
        "direction": "bull",
        "confidence": 0.72,
        "reasoning": "ADX趋势确认+库存下降",
    }
    test_plan = {"entry": 3500, "stop_loss": 3420, "target1": 3650, "target2": 3750}
    r = append_knowledge_extraction("rb", test_record, test_verdict, trading_plan=test_plan)
    print(f"Knowledge extraction: {json.dumps(r, ensure_ascii=False, indent=2)}")
