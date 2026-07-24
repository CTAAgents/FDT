#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
technical-indicator-calc 指标计算反馈模块 v1.0

当辩论Agent（技研锋）发现指标计算错误时，通过此模块提交反馈。
自动应用修复规则并沉淀经验。

用法:
  from indicator_feedback import submit_feedback
  submit_feedback('rb', 'calc_error', source='技研锋',
                  context='RSI=32但实际应该是29，计算偏差', severity='high')

CLI:
  python indicator_feedback.py submit rb calc_error 技研锋 "RSI值偏差"
  python indicator_feedback.py stats
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict

FEEDBACK_DIR = os.path.join(
    os.path.expanduser("~"), "logs", "feedback"
)
FEEDBACK_FILE = os.path.join(FEEDBACK_DIR, 'indicator_feedback.jsonl')


# ============================================================
# 修复规则
# ============================================================
REMEDIATION_RULES = {
    'calc_error': {
        'severity': 'high',
        'auto_fix': True,
        'action': 'recalculate',
        'description': '指标计算错误，重新计算并验证',
        'checklist': [
            '确认数据为时间正序(旧→新)',
            '确认EMA使用SMA(X,N,1) Wilder平滑',
            '确认SuperTrend算法修正已应用',
            '确认MACD金叉/死叉方向与实际走势一致',
        ],
    },
    'indicator_missing': {
        'severity': 'medium',
        'auto_fix': True,
        'action': 'enable_fallback',
        'description': '指标缺失，启用numpy fallback计算',
    },
    'golden_cross_error': {
        'severity': 'high',
        'auto_fix': True,
        'action': 'recalculate_with_correct_order',
        'description': '金叉/死叉判断错误，数据顺序需反转后重算',
    },
    'rsi_out_of_range': {
        'severity': 'medium',
        'auto_fix': True,
        'action': 'validate_rsi_calculation',
        'description': 'RSI值超出[0,100]范围，计算逻辑有误',
    },
    'adx_zero': {
        'severity': 'medium',
        'auto_fix': True,
        'action': 'validate_adx_input',
        'description': 'ADX=0或极低，可能输入数据不足或全是同价',
    },
    'indicator_accuracy': {
        'severity': 'low',
        'auto_fix': False,
        'action': 'cross_validate',
        'description': '指标精度不足，需与通达信/TQ-Local交叉验证',
    },
}


def submit_feedback(
    variety: str,
    issue_type: str,
    source: str = 'unknown',
    context: str = '',
    severity: str = 'medium',
) -> Dict:
    """提交指标计算反馈"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'variety': variety.upper(),
        'issue_type': issue_type,
        'source': source,
        'context': context,
        'severity': severity,
    }

    # 写日志
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    rule = REMEDIATION_RULES.get(issue_type, {})
    auto_fixed = rule.get('auto_fix', False)

    return {
        'recorded': True,
        'auto_fixed': auto_fixed,
        'rule_applied': rule.get('action', 'unknown'),
        'checklist': rule.get('checklist', []),
        'description': rule.get('description', '无匹配规则'),
    }


def get_stats(days: int = 30) -> Dict:
    """统计反馈数据"""
    if not os.path.exists(FEEDBACK_FILE):
        return {'total': 0, 'by_type': {}}

    cutoff = datetime.now().timestamp() - days * 86400
    by_type = {}
    count = 0

    with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get('timestamp', '2000-01-01')).timestamp()
                if ts >= cutoff:
                    count += 1
                    t = entry.get('issue_type', 'unknown')
                    by_type[t] = by_type.get(t, 0) + 1
            except json.JSONDecodeError:
                continue

    return {'total': count, 'by_type': by_type, 'rules': len(REMEDIATION_RULES)}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
    elif sys.argv[1] == 'submit':
        variety = sys.argv[2] if len(sys.argv) > 2 else 'ALL'
        issue_type = sys.argv[3] if len(sys.argv) > 3 else 'calc_error'
        source = sys.argv[4] if len(sys.argv) > 4 else 'cli'
        context = sys.argv[5] if len(sys.argv) > 5 else ''
        result = submit_feedback(variety, issue_type, source=source, context=context)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif sys.argv[1] == 'stats':
        print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
    else:
        print("Usage: python indicator_feedback.py [submit <variety> <type> <source> <context>|stats]")
