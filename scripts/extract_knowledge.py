#!/usr/bin/env python3
"""
品种知识萃取引擎 v1.0.0
========================
从辩论记录中提取品种特异性知识，写入 memory/knowledge/{variety}/ 目录。

设计原则:
1. 质量门控：仅 confidence ≥ 0.6 且经 post-validate 确认的裁决才能入库
2. 增量更新：每次提取只追加新条目 + 更新统计，不重写全文
3. 原子写入：先写 .tmp → rename，避免并发读写损坏
4. 老化保护：每品种有效模式上限 20 条，超限自动淘汰最低效模式

用法:
    from extract_knowledge import KnowledgeExtractor
    extractor = KnowledgeExtractor()
    extractor.extract_from_debate(variety="rb", debate_record={...}, verdict={...})
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 路径 ──────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_FDT_ROOT = _SCRIPT_DIR.parent
_KNOWLEDGE_DIR = _FDT_ROOT / "memory" / "knowledge"
_INDEX_PATH = _KNOWLEDGE_DIR / "variety_index.json"

# ── 门控参数 ──────────────────────────────────
MIN_CONFIDENCE = 0.6           # 最低置信度

# 置信度归一化统一委托给 confidence_utils（#5修复·单一来源，避免语义漂移）
# 别名保留，历史调用点 _normalize_confidence(...) 无需改动
try:
    from confidence_utils import normalize_confidence as _normalize_confidence
except ImportError:
    CONFIDENCE_LABEL_MAP = {"低": 0.4, "中": 0.6, "高": 0.8, "LOW": 0.4, "MEDIUM": 0.6, "HIGH": 0.8}

    def _normalize_confidence(conf):
        if isinstance(conf, (int, float)):
            return float(conf)
        if isinstance(conf, str):
            return CONFIDENCE_LABEL_MAP.get(conf.upper(), 0.5)
        return 0.5

MAX_PATTERNS_PER_VARIETY = 20  # 每品种有效模式上限
PATTERN_TTL_DAYS = 60          # 模式未使用自动降级天数
DECAY_WIN_THRESHOLD = 3        # 连续失败次数 → deprecated
ATOMIC_WRITE_STABLE_S = 2      # 原子写入稳定等待秒数


class KnowledgeExtractor:
    """品种知识萃取引擎。"""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else _KNOWLEDGE_DIR
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.knowledge_dir / "variety_index.json"
        self._index = self._load_index()

    # ── 索引管理 ──

    def _load_index(self) -> Dict:
        """加载品种知识索引。"""
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass
        return {"meta": {"version": "1.0", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "total_varieties": 0}, "varieties": {}}

    def _save_index(self) -> None:
        """原子写入索引文件。"""
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _update_index_entry(self, variety: str, field: str) -> None:
        """更新品种索引中的时间戳和计数。"""
        idx = self._index.get("varieties", {}).get(variety, {})
        if idx:
            idx[f"{field}_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            idx[field] = True
            self._save_index()

    # ── 文件原子写入 ──

    def _atomic_json_write(self, path: Path, data: Any) -> None:
        """原子写入 JSON：先写 .tmp → 等待 → rename。"""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(ATOMIC_WRITE_STABLE_S)
        tmp.replace(path)

    def _atomic_md_write(self, path: Path, content: str) -> None:
        """原子写入 Markdown。"""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        time.sleep(ATOMIC_WRITE_STABLE_S)
        tmp.replace(path)

    # ── 公共入口 ──

    def extract_from_debate(
        self,
        variety: str,
        debate_record: Dict[str, Any],
        verdict: Dict[str, Any],
        technical_data: Optional[Dict] = None,
        fundamental_data: Optional[Dict] = None,
        trading_plan: Optional[Dict] = None,
        bypass_quality_gate: bool = False,
    ) -> Dict[str, Any]:
        """
        从一轮辩论中提取品种特异性知识。

        Args:
            variety: 品种代码（小写，如 "rb"）
            debate_record: 完整辩论记录（含 pro_args/con_args）
            verdict: 闫判官裁决（含 winner/confidence/reasoning）
            technical_data: 观澜技术分析产出（可选）
            fundamental_data: 探源基本面产出（可选）
            trading_plan: 闫判官交易方案（可选）
            bypass_quality_gate: 是否绕过质量门控（仅用于初始化/回填）

        Returns:
            {"patterns_added": int, "key_levels_added": bool,
             "drivers_updated": bool, "data_quality_updated": bool,
             "skipped_reason": str | None}
        """
        variety = variety.strip().lower()
        confidence = _normalize_confidence(verdict.get("confidence", 0))

        # 质量门控
        if not bypass_quality_gate:
            if confidence < MIN_CONFIDENCE:
                return {"skipped_reason": f"confidence={confidence} < {MIN_CONFIDENCE}"}
            # 检查是否为 seed/reconstructed 记录（历史回填标记）
            if debate_record.get("seed") or debate_record.get("reconstructed"):
                return {"skipped_reason": "seed/reconstructed record - not a live debate"}

        variety_dir = self.knowledge_dir / variety
        variety_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "patterns_added": 0,
            "key_levels_added": False,
            "drivers_updated": False,
            "data_quality_updated": False,
            "skipped_reason": None,
        }

        # 1. 提取有效论证模式
        patterns_added = self._extract_patterns(variety, variety_dir, debate_record, verdict)
        result["patterns_added"] = patterns_added
        if patterns_added > 0:
            self._update_index_entry(variety, "patterns")

        # 2. 提取关键价位
        if trading_plan:
            result["key_levels_added"] = self._extract_key_levels(variety, variety_dir, trading_plan, verdict)
            self._update_index_entry(variety, "key_levels")

        # 3. 更新驱动因子（从裁决推理中提取关键因子提及）
        if verdict.get("reasoning"):
            result["drivers_updated"] = self._update_drivers(variety, variety_dir, verdict)
            self._update_index_entry(variety, "drivers")

        # 4. 更新数据源质量（从技术/基本面数据中提取数据源信息）
        if technical_data or fundamental_data:
            result["data_quality_updated"] = self._update_data_quality(variety, variety_dir, technical_data, fundamental_data)
            self._update_index_entry(variety, "data_quality")

        # 更新索引统计
        self._ensure_variety_in_index(variety)
        var_idx = self._index["varieties"][variety]
        var_idx["total_debates"] = var_idx.get("total_debates", 0) + 1
        var_idx["effective_patterns"] = self._count_effective_patterns(variety_dir)
        self._save_index()

        return result

    # ── 模式提取 ──

    def _extract_patterns(
        self, variety: str, variety_dir: Path, debate_record: Dict, verdict: Dict
    ) -> int:
        """从辩论记录中提取有效论证模式。"""
        patterns_path = variety_dir / "patterns.json"
        existing_patterns = self._load_json(patterns_path, [])

        confidence = _normalize_confidence(verdict.get("confidence", 0))
        winner = verdict.get("winner", "")
        winner_side = "pro" if verdict.get("direction", "").lower() in ("bull", "long", "buy") else "con"
        winner_is_bull = winner_side == "pro"

        # 从辩论记录中提取胜方论据
        pro_args = debate_record.get("pro_args", [])
        con_args = debate_record.get("con_args", [])
        winner_args = pro_args if winner_is_bull else con_args
        loser_args = con_args if winner_is_bull else pro_args

        if not winner_args:
            return 0

        # 从胜方论据中归纳论证结构
        claims = [a.get("claim", "") for a in winner_args if a.get("claim")]
        evidences = [a.get("evidence", "") for a in winner_args if a.get("evidence")]
        sources = list(set(a.get("source", "") for a in winner_args if a.get("source")))

        # 从 reasoning 中提取关键条件
        reasoning = verdict.get("reasoning", "")
        applicable_conditions = self._parse_conditions_from_reasoning(reasoning, debate_record)

        # 构建模式结构总结
        structure_steps = self._infer_structure_from_claims(claims)
        pattern_name = self._generate_pattern_name(variety, winner_args, verdict)

        # 检查是否已有相似模式（按 claims 的前两条判断）
        pattern_key = pattern_name[:30]  # 用模式名前30字符作为去重key
        is_duplicate = any(
            p.get("name", "")[:30] == pattern_key for p in existing_patterns
        )

        matched_pattern = None
        new_pattern = None
        if is_duplicate:
            # 已有相似模式 → 更新统计
            for p in existing_patterns:
                if p.get("name", "")[:30] == pattern_key:
                    p["use_count"] = p.get("use_count", 0) + 1
                    p["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    p["win_count"] = p.get("win_count", 0) + 1  # 仅验证通过后
                    # EMA 更新 win_rate
                    old_win_rate = p.get("win_rate", 0.5)
                    p["win_rate"] = round(old_win_rate + 0.3 * (1.0 - old_win_rate), 3)
                    p["confidence"] = round((p.get("confidence", 0.5) + confidence) / 2, 3)
                    p["consecutive_failures"] = 0  # 验证通过→重置连续失败计数（修复规则B隐患）
                    debate_ids = p.get("derived_from_debates", [])
                    rid = debate_record.get("round_id", verdict.get("round_id", "unknown"))
                    if rid not in debate_ids:
                        debate_ids.append(rid)
                    matched_pattern = p
                    break
        else:
            # 新建模式
            rid = debate_record.get("round_id", verdict.get("round_id", "unknown"))
            new_pattern = {
                "pattern_id": f"{variety}-p{len(existing_patterns) + 1:03d}",
                "name": pattern_name,
                "first_observed": datetime.now().strftime("%Y-%m-%d"),
                "last_used": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "use_count": 1,
                "win_count": 1,
                "win_rate": round(min(1.0, confidence), 3),
                "structure": " → ".join(structure_steps) if structure_steps else "；".join(claims[:3]),
                "applicable_conditions": applicable_conditions,
                "key_evidence_sources": sources[:5],
                "derived_from_debates": [rid],
                "confidence": round(confidence, 3),
                "consecutive_failures": 0,
                "status": "active",
            }
            existing_patterns.append(new_pattern)

        # 老化保护：超限淘汰最低效模式
        if len(existing_patterns) > MAX_PATTERNS_PER_VARIETY:
            existing_patterns.sort(key=lambda p: (
                p.get("status", "active") == "active",
                p.get("win_rate", 0),
                -p.get("use_count", 0)
            ))
            # 标记最低效的为 deprecated，不删除（保留审计线索）
            for p in existing_patterns[MAX_PATTERNS_PER_VARIETY:]:
                if p.get("status") == "active":
                    p["status"] = "deprecated"
                    p["deprecated_reason"] = "自动淘汰：有效模式超上限"

        self._atomic_json_write(patterns_path, existing_patterns)
        return 1 if not is_duplicate else 0

    def _infer_structure_from_claims(self, claims: List[str]) -> List[str]:
        """从论据 claims 中归纳论证步骤链。"""
        if not claims:
            return []
        # 简化的步骤归纳：按 claim 的长度和关键词判断
        steps = []
        for c in claims[:5]:
            c_lower = c.lower()
            if any(kw in c_lower for kw in ["adx", "趋势", "trend", "动量", "momentum"]):
                label = "趋势确认"
            elif any(kw in c_lower for kw in ["库存", "供需", "supply", "demand", "inventory"]):
                label = "基本面验证"
            elif any(kw in c_lower for kw in ["持仓", "oi", "资金", "flow"]):
                label = "资金验证"
            elif any(kw in c_lower for kw in ["基差", "backwardation", "contango", "期限"]):
                label = "期限结构确认"
            elif any(kw in c_lower for kw in ["政策", "限产", "减产", "关税", "制裁"]):
                label = "政策催化"
            elif any(kw in c_lower for kw in ["支撑", "阻力", "突破", "breakout", "pullback"]):
                label = "技术形态确认"
            else:
                label = c[:20] + "..."
            steps.append(label)
        return steps

    def _parse_conditions_from_reasoning(self, reasoning: str, debate_record: Dict) -> Dict:
        """从裁决推理和辩论记录中提取适用条件。"""
        conditions = {}

        # 从 verdict 信号字段提取 ADX 范围
        volatility = debate_record.get("volatility", {})
        adx = volatility.get("adx", 50)
        if isinstance(adx, (int, float)):
            adx_low = max(10, adx - 15)
            adx_high = min(100, adx + 15)
            conditions["adx_range"] = [adx_low, adx_high]

        # 信号类型
        signal_type = debate_record.get("signal_type", "")
        if signal_type:
            conditions["signal_type"] = [signal_type]

        # 方向
        direction = debate_record.get("verdict", {}).get("direction", "")
        if direction:
            conditions["direction"] = direction

        return conditions

    def _generate_pattern_name(self, variety: str, winner_args: List[Dict], verdict: Dict) -> str:
        """根据论据生成模式名称。"""
        claims = [a.get("claim", "") for a in winner_args[:3]]
        claims_text = " ".join(claims)

        # 检测模式类型
        if any(kw in claims_text.lower() for kw in ["趋势", "trend", "动量", "momentum", "adx"]):
            base = "趋势驱动"
        elif any(kw in claims_text.lower() for kw in ["库存", "供需", "supply", "demand"]):
            base = "基本面驱动"
        elif any(kw in claims_text.lower() for kw in ["突破", "breakout"]):
            base = "突破跟随"
        elif any(kw in claims_text.lower() for kw in ["基差", "期限", "backwardation"]):
            base = "期限结构驱动"
        elif any(kw in claims_text.lower() for kw in ["政策", "限产", "关税"]):
            base = "政策驱动"
        else:
            base = "综合驱动"

        direction = verdict.get("direction", verdict.get("winner", ""))
        dir_label = "多头" if direction.lower() in ("bull", "long", "buy") else "空头"
        return f"{dir_label}{base}型"

    # ── 关键价位提取 ──

    def _extract_key_levels(
        self, variety: str, variety_dir: Path, trading_plan: Dict, verdict: Dict
    ) -> bool:
        """提取关键价位。"""
        levels_path = variety_dir / "key_levels.json"
        existing_levels = self._load_json(levels_path, {"levels": []})

        entry = trading_plan.get("entry")
        stop_loss = trading_plan.get("stop_loss")
        target1 = trading_plan.get("target1")
        target2 = trading_plan.get("target2")

        if not entry or not stop_loss:
            return False

        new_level = {
            "entry": entry,
            "stop_loss": stop_loss,
            "targets": [t for t in [target1, target2] if t],
            "direction": verdict.get("direction", ""),
            "confidence": verdict.get("confidence", 0),
            "round_id": verdict.get("round_id", ""),
            "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        # 添加到 levels 列表
        existing_levels.setdefault("levels", [])
        existing_levels["levels"].append(new_level)

        # 保留最近 50 个关键价位记录
        if len(existing_levels["levels"]) > 50:
            existing_levels["levels"] = existing_levels["levels"][-50:]

        # 计算聚合支撑/阻力位
        existing_levels["aggregated"] = self._compute_aggregated_levels(existing_levels["levels"])

        # 更新元数据
        existing_levels["meta"] = {
            "variety": variety,
            "total_records": len(existing_levels["levels"]),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        self._atomic_json_write(levels_path, existing_levels)
        return True

    def _compute_aggregated_levels(self, levels: List[Dict]) -> Dict:
        """从历史关键价位中计算聚合支撑/阻力位。"""
        if not levels:
            return {"support": [], "resistance": []}

        # 提取多头和空头的价格点（兼容 dict 和纯数字两种格式）
        def _to_price(val):
            """entry/target 可能是纯数字或 {"price": 4700, ...} 格式。"""
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, dict) and "price" in val:
                return float(val["price"])
            return None

        bull_entries = [_to_price(l["entry"]) for l in levels if l.get("direction", "").lower() in ("bull", "long", "buy") and l.get("entry")]
        bull_entries = [p for p in bull_entries if p is not None]
        bull_targets = [_to_price(t) for l in levels if l.get("direction", "").lower() in ("bull", "long", "buy") for t in l.get("targets", []) if t]
        bull_targets = [p for p in bull_targets if p is not None]
        bear_entries = [_to_price(l["entry"]) for l in levels if l.get("direction", "").lower() in ("bear", "short", "sell") and l.get("entry")]
        bear_entries = [p for p in bear_entries if p is not None]
        bear_targets = [_to_price(t) for l in levels if l.get("direction", "").lower() in ("bear", "short", "sell") for t in l.get("targets", []) if t]
        bear_targets = [p for p in bear_targets if p is not None]

        # 多头入场价 + 空头目标价 → 支撑区
        support_prices = bull_entries + bear_targets
        # 空头入场价 + 多头目标价 → 阻力区
        resistance_prices = bear_entries + bull_targets

        def cluster_prices(prices: List[float], threshold_pct: float = 0.02) -> List[Dict]:
            """按价格区间聚类。"""
            if not prices:
                return []
            # 防御：所有价格为0，直接归为1个聚类
            if all(p == 0 for p in prices):
                return [{"level": 0.0, "count": len(prices), "min": 0.0, "max": 0.0}]
            sorted_p = sorted(prices)
            clusters = []
            current_cluster = [sorted_p[0]]

            for p in sorted_p[1:]:
                avg = sum(current_cluster) / len(current_cluster)
                if avg == 0:
                    current_cluster.append(p)
                    continue
                if abs(p - avg) / avg <= threshold_pct:
                    current_cluster.append(p)
                else:
                    clusters.append({
                        "level": round(sum(current_cluster) / len(current_cluster), 1),
                        "count": len(current_cluster),
                        "min": min(current_cluster),
                        "max": max(current_cluster),
                    })
                    current_cluster = [p]

            if current_cluster:
                clusters.append({
                    "level": round(sum(current_cluster) / len(current_cluster), 1),
                    "count": len(current_cluster),
                    "min": min(current_cluster),
                    "max": max(current_cluster),
                })

            return sorted(clusters, key=lambda c: -c["count"])[:5]  # 前5个密集区域

        return {
            "support": cluster_prices(support_prices),
            "resistance": cluster_prices(resistance_prices),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ── 驱动因子更新 ──

    def _update_drivers(self, variety: str, variety_dir: Path, verdict: Dict) -> bool:
        """从裁决推理中提取关键驱动因子提及，更新 drivers.md。"""
        # 当前使用 Markdown 格式，方便人工阅读和 Agent 直接调用
        reasoning = verdict.get("reasoning", "")
        round_id = verdict.get("round_id", "unknown")

        if not reasoning:
            return False

        drivers_path = variety_dir / "drivers.md"

        # 从推理中提取关键驱动因子提及
        driver_mentions = []
        driver_patterns = [
            (r"[库|存|inventory|supply|demand|供需|产量|开工|产能|检修]", "供给/库存"),
            (r"[需|求|消费|demand|consumption|开工率|负荷]", "需求"),
            (r"[利润|margin|加工差|价差|spread]", "利润/价差"),
            (r"[政策|限产|减产|关税|制裁|补贴|环保|双碳]", "政策"),
            (r"[地缘|geopolitical|俄乌|中东|制裁|战争|冲突]", "地缘政治"),
            (r"[宏观|macro|GDP|PMI|CPI|PPI|利率|降息|加息|美联储|fed]", "宏观"),
            (r"[季节|season|天气|weather|台风|干旱|洪水|雨季|旱季]", "季节/天气"),
            (r"[基差|basis|backwardation|contango|期限]", "期限结构"),
            (r"[持仓|oi|open interest|资金|flow|投机净多]", "持仓/资金"),
            (r"[进口|出口|export|import|到港|海外|外盘|lme]", "进出口/外盘"),
        ]

        for pattern, label in driver_patterns:
            if re.search(pattern, reasoning, re.IGNORECASE):
                driver_mentions.append(label)

        if not driver_mentions:
            return False

        # 去重
        driver_mentions = list(set(driver_mentions))

        # 追加到 drivers.md
        entry = (
            f"\n## {round_id}\n"
            f"- **裁决方向**: {verdict.get('direction', verdict.get('winner', 'N/A'))}\n"
            f"- **置信度**: {verdict.get('confidence', 'N/A')}\n"
            f"- **识别驱动因子**: {', '.join(driver_mentions)}\n"
            f"- **裁决摘要**: {reasoning[:200]}\n"
        )

        # 原子追加
        tmp = drivers_path.with_suffix(".tmp")
        existing = ""
        if drivers_path.exists():
            existing = drivers_path.read_text(encoding="utf-8")
        new_content = existing + entry
        tmp.write_text(new_content, encoding="utf-8")
        time.sleep(ATOMIC_WRITE_STABLE_S)
        tmp.replace(drivers_path)

        return True

    # ── 数据源质量 ──

    def _update_data_quality(
        self, variety: str, variety_dir: Path,
        technical_data: Optional[Dict], fundamental_data: Optional[Dict]
    ) -> bool:
        """更新数据源质量记录。"""
        dq_path = variety_dir / "data_quality.json"
        existing = self._load_json(dq_path, {"sources": {}})

        today = datetime.now().strftime("%Y-%m-%d")

        # 从 technical_data 提取数据源信息
        if technical_data:
            source_info = technical_data.get("data_source", technical_data.get("source", ""))
            if source_info:
                source_key = source_info.lower().replace(" ", "_")
                src = existing["sources"].setdefault(source_key, {
                    "name": source_info,
                    "first_seen": today,
                    "last_seen": today,
                    "total_calls": 0,
                    "delayed_days": 0,
                    "delayed_count": 0,
                    "priority": self._infer_source_priority(source_info)
                })
                src["last_seen"] = today
                src["total_calls"] += 1

        # 从 fundamental_data 提取
        if fundamental_data:
            for key in ["data_source", "source", "sources"]:
                source_info = fundamental_data.get(key, "")
                if isinstance(source_info, str) and source_info:
                    source_key = source_info.lower().replace(" ", "_")
                    src = existing["sources"].setdefault(source_key, {
                        "name": source_info,
                        "first_seen": today,
                        "last_seen": today,
                        "total_calls": 0,
                        "delayed_days": 0,
                        "delayed_count": 0,
                        "priority": self._infer_source_priority(source_info)
                    })
                    src["last_seen"] = today
                    src["total_calls"] += 1

        existing["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._atomic_json_write(dq_path, existing)
        return True

    def _infer_source_priority(self, source_name: str) -> int:
        """推断数据源优先级（1=最高）。"""
        name = source_name.lower()
        if any(kw in name for kw in ["wh6", "文华", "tdx", "通达信"]):
            return 1
        if any(kw in name for kw in ["tqsdk", "tq"]):
            return 2
        if any(kw in name for kw in ["东方财富", "eastmoney"]):
            return 3
        if any(kw in name for kw in ["交易所", "shfe", "dce", "czce", "ine"]):
            return 4
        if any(kw in name for kw in ["akshare", "akshare"]):
            return 5
        return 6

    # ── 辅助方法 ──

    def _load_json(self, path: Path, default: Any = None) -> Any:
        """安全加载 JSON。"""
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass
        return default if default is not None else {}

    def _ensure_variety_in_index(self, variety: str) -> None:
        """确保品种在索引中。"""
        if "varieties" not in self._index:
            self._index["varieties"] = {}
        if variety not in self._index["varieties"]:
            self._index["varieties"][variety] = {
                "name": variety.upper(),
                "exchange": "",
                "chain": "",
                "profile": False, "drivers": False, "patterns": False,
                "key_levels": False, "data_quality": False,
                "total_debates": 0, "effective_patterns": 0
            }

    def _count_effective_patterns(self, variety_dir: Path) -> int:
        """统计有效模式数量。"""
        patterns_path = variety_dir / "patterns.json"
        if patterns_path.exists():
            try:
                patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
                return len([p for p in patterns if p.get("status", "active") == "active"])
            except (json.JSONDecodeError, IOError):
                pass
        return 0

    # ── 模式失败反馈（规则 B 的写入入口，修复 #consecutive_failures 隐患） ──

    def record_pattern_failure(self, variety: str, pattern_name: str) -> bool:
        """
        记录一次模式验证失败，累加 consecutive_failures。

        当外部流程判定某条模式导致错误决策时调用此方法。
        连续 failure >= DECAY_WIN_THRESHOLD（3次）后，下一次 run_decay 会自动 deprecated。

        Args:
            variety: 品种代码
            pattern_name: 模式名称（前30字符匹配）

        Returns:
            True=累加成功，False=未找到匹配模式
        """
        variety = variety.strip().lower()
        patterns_path = self.knowledge_dir / variety / "patterns.json"
        patterns = self._load_json(patterns_path, [])
        if not patterns:
            return False

        key = pattern_name[:30]
        for p in patterns:
            if p.get("name", "")[:30] == key and p.get("status", "active") == "active":
                p["consecutive_failures"] = p.get("consecutive_failures", 0) + 1
                p["last_failure"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if p["consecutive_failures"] >= DECAY_WIN_THRESHOLD:
                    p["status"] = "deprecated"
                    p["deprecated_reason"] = f"连续{DECAY_WIN_THRESHOLD}次验证失败"
                self._atomic_json_write(patterns_path, patterns)
                return True
        return False

    # ── 知识老化（定时任务调用） ──

    def run_decay(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        知识老化：降级长期未使用的模式。

        规则:
        - 60天未见 used → weight 减半
        - 连续 3 次失败 → deprecated
        - 仅 active 模式参与检查

        Returns:
            {"decayed": int, "deprecated": int, "active_before": int, "active_after": int}
        """
        now = datetime.now()
        result = {"decayed": 0, "deprecated": 0, "active_before": 0, "active_after": 0}

        for variety in os.listdir(self.knowledge_dir):
            patterns_path = self.knowledge_dir / variety / "patterns.json"
            if not patterns_path.exists():
                continue

            patterns = self._load_json(patterns_path, [])
            if not patterns:
                continue

            changed = False
            active_before = sum(1 for p in patterns if p.get("status", "active") == "active")

            for p in patterns:
                if p.get("status") != "active":
                    continue

                last_used_str = p.get("last_used", "")
                if not last_used_str:
                    continue

                try:
                    last_used = datetime.strptime(last_used_str[:10], "%Y-%m-%d")
                    days_since_use = (now - last_used).days

                    # 60天未见使用 → 降级
                    if days_since_use > PATTERN_TTL_DAYS:
                        old_win_rate = p.get("win_rate", 0.5)
                        p["win_rate"] = round(old_win_rate * 0.5, 3)
                        p["decay_reason"] = f"{days_since_use}天未使用，win_rate 减半"
                        p["last_decayed"] = now.strftime("%Y-%m-%d")
                        changed = True
                        if not dry_run:
                            result["decayed"] += 1

                    # 连续失败 → deprecated
                    if p.get("consecutive_failures", 0) >= DECAY_WIN_THRESHOLD:
                        p["status"] = "deprecated"
                        p["deprecated_reason"] = f"连续{DECAY_WIN_THRESHOLD}次失败"
                        changed = True
                        if not dry_run:
                            result["deprecated"] += 1

                except (ValueError, KeyError):
                    continue

            if changed and not dry_run:
                self._atomic_json_write(patterns_path, patterns)

            active_after = sum(1 for p in patterns if p.get("status", "active") == "active")
            result["active_before"] += active_before
            result["active_after"] += active_after

        if not dry_run:
            result["executed_at"] = now.strftime("%Y-%m-%d %H:%M")
        return result


# ── CLI ────────────────────────────────────────

if __name__ == "__main__":
    import sys
    extractor = KnowledgeExtractor()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "decay":
        dry = "--dry-run" in sys.argv
        result = extractor.run_decay(dry_run=dry)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "fail":
        # 记录模式失败：python scripts/extract_knowledge.py fail <variety> <pattern_name>
        if len(sys.argv) < 4:
            print("用法: python scripts/extract_knowledge.py fail <品种> <模式名>")
            sys.exit(1)
        ok = extractor.record_pattern_failure(sys.argv[2], sys.argv[3])
        print(json.dumps({"success": ok, "variety": sys.argv[2], "pattern": sys.argv[3]}, ensure_ascii=False, indent=2))

    elif cmd == "ingest":
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--symbol", required=True)
        ap.add_argument("--pro", required=True)
        ap.add_argument("--con", required=True)
        ap.add_argument("--judge", required=True)
        ap.add_argument("--plan", default=None)
        ap.add_argument("--bypass", action="store_true")
        args = ap.parse_args(sys.argv[2:])
        with open(args.pro, encoding="utf-8") as f:
            pro = json.load(f)
        with open(args.con, encoding="utf-8") as f:
            con = json.load(f)
        with open(args.judge, encoding="utf-8") as f:
            judge = json.load(f)
        plan = None
        if args.plan:
            with open(args.plan, encoding="utf-8") as f:
                plan = json.load(f)
        rec = {
            "symbol": args.symbol,
            "signal_type": judge.get("signal_type"),
            "pro_args": pro.get("key_arguments", []),
            "con_args": con.get("key_arguments", []),
        }
        r = extractor.extract_from_debate(
            variety=args.symbol.lower(),
            debate_record=rec,
            verdict=judge,
            trading_plan=plan,
            bypass_quality_gate=args.bypass,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif cmd == "ingest_from":
        import argparse as _ap
        _a = _ap.ArgumentParser()
        _a.add_argument("--from", dest="from_path", required=True, help="debate_results.json 路径")
        _a.add_argument("--bypass", action="store_true", help="绕过质量门控（仅初始化/回填用）")
        _ns = _a.parse_args(sys.argv[2:])
        with open(_ns.from_path, encoding="utf-8") as f:
            _dr = json.load(f)
        _skipped = 0
        _ingested = 0
        for _sym, _v in _dr.get("verdicts", {}).items():
            # 方向归一：BUY→bull / SELL→bear / HOLD→neutral
            _dir = str(_v.get("direction", _v.get("judge_verdict", {}).get("final_direction", ""))).lower()
            _dir = {"buy": "bull", "sell": "bear", "hold": "neutral"}.get(_dir, _dir)
            # debate_results.json 的 bull_args/bear_args 为字符串列表，
            # extract_from_debate 的 _extract_patterns 需要 dict(claim/evidence/source)，故在此归一
            _pro_args = [a if isinstance(a, dict) else {"claim": str(a), "evidence": "", "source": "debate_results"}
                          for a in _v.get("bull_args", [])]
            _con_args = [a if isinstance(a, dict) else {"claim": str(a), "evidence": "", "source": "debate_results"}
                          for a in _v.get("bear_args", [])]
            _rec = {
                "symbol": _sym,
                "signal_type": _v.get("signal_type", ""),
                "pro_args": _pro_args,
                "con_args": _con_args,
            }
            _verdict = {
                "direction": _dir,
                "confidence": _v.get("confidence",
                                 _v.get("judge_verdict", {}).get("confidence", 0)),
                "winner": _v.get("winner", ""),
                "reasoning": _v.get("judge_verdict", {}).get("reasoning", ""),
            }
            # 复用既有 extract_from_debate（内置 conf<0.6 质量门控，自动跳过）
            _r = extractor.extract_from_debate(
                variety=_sym.lower(),
                debate_record=_rec,
                verdict=_verdict,
                trading_plan=_v.get("trading_plan"),
                bypass_quality_gate=_ns.bypass,
            )
            if _r.get("skipped_reason"):
                _skipped += 1
                print(f"  ⏭️ {_sym}: 跳过（{_r['skipped_reason']}）")
            else:
                _ingested += 1
                print(f"  ✅ {_sym}: 入库成功")
        print(f"\n📚 批量萃取完成：入库 {_ingested} / 跳过 {_skipped}")

    elif cmd == "test":
        # 快速自测
        test_record = {
            "round_id": "test_extract",
            "symbol": "rb",
            "pro_args": [
                {"claim": "ADX=45趋势确认，多头趋势运行顺畅", "evidence": "ADX=45, RSI=62", "source": "技术分析评分/信号"},
                {"claim": "库存连续4周下降，去库加速", "evidence": "库存数据", "source": "Mysteel"},
            ],
            "con_args": [
                {"claim": "RSI接近超买区域", "evidence": "RSI=68", "source": "技术分析评分"},
            ],
            "volatility": {"adx": 45, "atr": 120},
        }
        test_verdict = {
            "round_id": "test_extract",
            "direction": "bull",
            "confidence": 0.72,
            "winner": "pro",
            "reasoning": "ADX=45确认趋势，库存持续下降支撑多头。宏观方面无利空。",
        }
        test_plan = {
            "entry": 3500, "stop_loss": 3420, "target1": 3650, "target2": 3750,
        }
        result = extractor.extract_from_debate(
            variety="rb",
            debate_record=test_record,
            verdict=test_verdict,
            trading_plan=test_plan,
            bypass_quality_gate=True,
        )
        print(f"Extract result: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # 验证写入
        rb_dir = extractor.knowledge_dir / "rb"
        print(f"\nPatterns: {json.dumps(extractor._load_json(rb_dir / 'patterns.json', []), ensure_ascii=False, indent=2)}")
        print(f"\nKey levels keys: {list(extractor._load_json(rb_dir / 'key_levels.json', {}).keys())}")
        print(f"\nDrivers exists: {(rb_dir / 'drivers.md').exists()}")
        print("\n✅ test passed")

    elif cmd == "help":
        print(__doc__)
