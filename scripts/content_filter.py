#!/usr/bin/env python3
"""
content_filter.py — 内容安全与合规过滤 (D3 Generation Phase 3)
=========================================================
功能:
  1. 敏感词过滤 (市场操纵、内幕交易等金融领域敏感词)
  2. 合规审查 (广告法、金融合规)
  3. 输出脱敏 (价格区间替换)
  4. 金融合规检查

用法:
  from scripts.content_filter import ContentFilter
  filter = ContentFilter()
  result = filter.filter("这是一个测试文本")
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# 金融领域敏感词分类
SENSITIVE_WORDS = {
    "market_manipulation": [
        "坐庄", "操盘", "拉升", "打压", "对倒", "对敲",
        "老鼠仓", "抬轿子", "出货", "洗盘", "诱多", "诱空",
        "拉高出货", "砸盘", "封板", "打板",
    ],
    "insider_trading": [
        "内幕", "内幕消息", "内线", "提前获知",
        "泄露消息", "未公开信息", "内部人",
        "消息提前走漏", "内部资料",
    ],
    "guaranteed_return": [
        "包赚", "稳赚", "保证收益", "保本保息", "稳赢",
        "100%盈利", "保证不亏", "零风险", "绝对安全",
        "稳赚不赔", "必然上涨", "肯定跌", "百分百",
    ],
    "illegal_finance": [
        "非法集资", "配资", "虚拟盘", "对赌",
        "场外配资", "非法期货", "地下钱庄",
        "跨境非法资金", "洗钱",
    ],
    "overclaim": [
        "全网第一", "最佳", "最好", "最优", "最牛",
        "唯一", "必然盈利", "绝对正确", "无敌",
        "一夜暴富", "短期翻倍",
    ],
}

# 合规替换映射
SENSITIVE_REPLACEMENTS = {
    # 市场操纵
    "坐庄": "主力行为",
    "操盘": "交易执行",
    "拉升": "价格上涨",
    "打压": "价格下跌",
    # 夸大承诺
    "包赚": "可能存在机会",
    "稳赚": "概率偏多",
    "保证收益": "预期收益",
    "100%盈利": "胜率较高",
    # 过度主张
    "全网第一": "业内领先",
    "最佳": "较优",
    "最好": "较好",
    "最优": "较优",
    "唯一": "之一",
}


class ContentFilter:
    """内容安全过滤器"""

    def __init__(self, custom_words: Optional[list[str]] = None):
        self.sensitive_word_map: dict[str, str] = {}
        self.sensitive_category_map: dict[str, list[str]] = {}
        self.custom_blocklist: list[str] = custom_words or []

        self._build_patterns()

    def _build_patterns(self):
        """构建敏感词模式"""
        for category, words in SENSITIVE_WORDS.items():
            self.sensitive_category_map[category] = words
            for word in words:
                # 如果替换映射中有，则记录替换值
                replacement = SENSITIVE_REPLACEMENTS.get(word, None)
                if replacement:
                    self.sensitive_word_map[word] = replacement

    def check_sensitive(self, text: str) -> dict:
        """
        检查文本中的敏感词

        Returns:
            dict: {"has_sensitive": bool, "matches": list[dict],
                   "categories": list[str]}
        """
        result = {
            "has_sensitive": False,
            "matches": [],
            "categories": set(),
        }

        for word in self.sensitive_word_map:
            if word in text:
                result["matches"].append({
                    "word": word,
                    "position": text.index(word),
                })
                result["has_sensitive"] = True

        # 检查分类
        for category, words in self.sensitive_category_map.items():
            for word in words:
                if word in text:
                    result["categories"].add(category)

        result["categories"] = sorted(result["categories"])
        return result

    def sanitize(self, text: str, mask_char: str = "**") -> str:
        """
        脱敏处理 — 替换敏感词

        Args:
            text: 输入文本
            mask_char: 替换字符

        Returns:
            脱敏后的文本
        """
        result = text

        # 1. 替换有映射的词
        for word, replacement in self.sensitive_word_map.items():
            result = result.replace(word, replacement)

        # 2. 脱敏无映射的敏感词
        for word in self.custom_blocklist:
            result = result.replace(word, mask_char * 2)

        return result

    def check_compliance(self, text: str) -> list[dict]:
        """
        合规审查

        Returns:
            list[dict]: 合规问题列表 [{rule, severity, detail}]
        """
        issues = []

        # Rule 1: 禁止保证收益
        guarantee_patterns = [
            r"保证.*[赚利收益]",
            r"100%[%].*[赚盈]",
            r"稳[赚赢]",
            r"包[赚赢]",
        ]
        for pattern in guarantee_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                issues.append({
                    "rule": "no_guaranteed_return",
                    "severity": "high",
                    "detail": f"发现保证收益表述: {match}",
                })

        # Rule 2: 禁止预测绝对价格
        absolute_patterns = [
            r"必然[上涨跌]",
            r"一定[涨跌]",
            r"肯定[涨跌]",
            r"绝对会[涨跌]",
        ]
        for pattern in absolute_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                issues.append({
                    "rule": "no_absolute_prediction",
                    "severity": "medium",
                    "detail": f"发现绝对预测表述: {match}",
                })

        # Rule 3: 价格建议必须带风险提示
        if re.search(r"\d{2,5}[元点]", text) or re.search(r"[买卖][入出].*[价格]", text):
            if "风险" not in text and "谨慎" not in text:
                issues.append({
                    "rule": "risk_disclaimer_required",
                    "severity": "medium",
                    "detail": "价格建议需要附带风险提示",
                })

        # Rule 4: 禁止内幕交易暗示
        for keyword in ["内幕", "提前知道", "内部消息", "内线消息"]:
            if keyword in text:
                issues.append({
                    "rule": "no_insider_trading",
                    "severity": "critical",
                    "detail": f"发现内幕交易暗示: {keyword}",
                })

        return issues

    def filter(
        self,
        text: str,
        strict: bool = True,
    ) -> dict:
        """
        综合过滤

        Args:
            text: 输入文本
            strict: 严格模式 (阻断敏感内容)

        Returns:
            dict: {
                "original": str,
                "sanitized": str,
                "has_sensitive": bool,
                "compliance_issues": list[dict],
                "blocked": bool
            }
        """
        # 敏感词检查
        sensitive_check = self.check_sensitive(text)

        # 合规审查
        compliance_issues = self.check_compliance(text)

        # 脱敏
        sanitized = self.sanitize(text)

        # 判定是否阻断
        critical_issues = [i for i in compliance_issues if i["severity"] == "critical"]
        blocked = strict and (
            sensitive_check["has_sensitive"]
            or len(critical_issues) > 0
        )

        return {
            "original": text,
            "sanitized": sanitized,
            "has_sensitive": sensitive_check["has_sensitive"],
            "sensitive_matches": sensitive_check["matches"],
            "sensitive_categories": sensitive_check["categories"],
            "compliance_issues": compliance_issues,
            "blocked": blocked,
        }


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="内容安全过滤工具")
    parser.add_argument("input", nargs="?", help="输入的文本或文件路径")
    parser.add_argument("--file", "-f", action="store_true", help="从文件读取输入")
    parser.add_argument("--check-only", "-c", action="store_true", help="仅检查不替换")
    parser.add_argument("--relaxed", "-r", action="store_true", help="宽松模式 (不阻断)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    if args.file:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.input:
        text = args.input
    else:
        import sys
        text = sys.stdin.read()

    filter = ContentFilter()

    if args.check_only:
        result = {
            "sensitive": filter.check_sensitive(text),
            "compliance": filter.check_compliance(text),
        }
    else:
        result = filter.filter(text, strict=not args.relaxed)

    if args.verbose:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        sensitive = isinstance(result, dict) and result.get("has_sensitive", False)
        blocked = isinstance(result, dict) and result.get("blocked", False)
        issues = isinstance(result, dict) and result.get("compliance_issues", [])

        if isinstance(result, dict) and "sanitized" in result:
            print(f"原文本: {text[:80]}{'...' if len(text) > 80 else ''}")
            print(f"脱敏后: {result['sanitized'][:80]}{'...' if len(result['sanitized']) > 80 else ''}")

        print(f"敏感词: {'⚠️ 发现' if sensitive else '✅ 未发现'}")
        if blocked:
            print("❌ 已阻断 (请修改后重试)")
        if issues:
            for issue in issues:
                print(f"  {'🔴' if issue['severity'] == 'critical' else '🟡'} [{issue['severity']}] {issue['detail']}")


if __name__ == "__main__":
    main()
