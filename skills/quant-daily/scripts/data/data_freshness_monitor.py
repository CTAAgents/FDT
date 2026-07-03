#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
futures-data-search 数据新鲜度 SLA 监控模块 v1.0

核心功能：
1. 跟踪每个品种在每个数据源的最后成功采集时间和状态
2. 定义 SLA 窗口（收盘后 30 分钟内必须刷新）
3. 失败自动重试（最多 3 次，间隔 5 分钟）
4. 每日数据新鲜度报告（哪些品种在 SLA 内，哪些超出）
5. 周期扫描模式（开盘前预热、收盘后强制刷新）

用法：
    from data_freshness_monitor import DataFreshnessMonitor
    
    monitor = DataFreshnessMonitor()
    
    # 记录采集成功
    monitor.record_collection('CU', 'eastmoney', success=True, count=120)
    
    # 记录采集失败
    monitor.record_collection('RB', 'tdx_local', success=False, error='HTTP 502')
    
    # 检查品种是否在 SLA 内
    status = monitor.check_sla('CU')
    
    # 生成今日 SLA 报告
    report = monitor.generate_daily_report()
    
    # 扫描需要重试的品种
    retries = monitor.get_pending_retries()
    
    # 每日新鲜度评分
    score = monitor.get_freshness_score()  # 0.0 ~ 1.0

CLI:
    python data_freshness_monitor.py report        # 今日 SLA 报告
    python data_freshness_monitor.py status <variety>  # 品种 SLA 状态
    python data_freshness_monitor.py score         # 新鲜度评分
    python data_freshness_monitor.py retry         # 待重试列表
    python data_freshness_monitor.py history       # 最近 7 天 SLA 历史
"""

import json
import os
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path


# ============================================================
# 配置常量
# ============================================================

SLA_DEADLINE_MINUTES = 30  # 收盘后 30 分钟内必须刷新
MAX_RETRIES = 3             # 最大重试次数
RETRY_INTERVAL_MINUTES = 5  # 重试间隔（分钟）
MARKET_CLOSE_HOUR = 15      # 收盘时间（日盘）
MARKET_CLOSE_MINUTE = 0     # 收盘分钟
NIGHT_CLOSE_HOUR = 23       # 夜盘收盘
NIGHT_CLOSE_MINUTE = 0

# 所有活跃主力品种（futures-data-search 覆盖的 67 个活跃品种）
ACTIVE_VARIETIES = [
    # SHFE（上期所）19
    'CU', 'AL', 'ZN', 'PB', 'NI', 'SN', 'AU', 'AG', 'RB', 'HC',
    'SS', 'RU', 'BR', 'FU', 'BU', 'SP', 'AO', 'AD', 'OP',
    # DCE（大商所）19
    'A', 'B', 'M', 'Y', 'P', 'C', 'CS', 'I', 'J', 'JM',
    'L', 'V', 'PP', 'EG', 'EB', 'PG', 'JD', 'LH', 'RR',
    # CZCE（郑商所）18
    'AP', 'CF', 'FG', 'SA', 'MA', 'TA', 'UR', 'PF', 'PR', 'PX',
    'PK', 'OI', 'RM', 'SR', 'SM', 'SF', 'SH', 'ZC',
    # GFEX（广期所）5
    'SI', 'LC', 'PS', 'PT', 'PD',
    # INE（上期能源）4
    'SC', 'LU', 'NR', 'BC',
    # CFFEX（中金所，仅商品相关活跃品种）2
    'TS', 'TF',
]

_FRESHNESS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "WorkBuddy", ".workbuddy", "feedback"
)


class FreshnessRecord:
    """单个品种的新鲜度记录"""

    def __init__(
        self,
        variety: str,
        last_success: Optional[str] = None,
        last_attempt: Optional[str] = None,
        data_source: str = 'none',
        status: str = 'pending',  # pending / fresh / stale / failed
        success_count: int = 0,
        failure_count: int = 0,
        consecutive_failures: int = 0,
        retry_count: int = 0,
        data_count: int = 0,
        last_error: str = '',
        sla_deadline: Optional[str] = None,
    ):
        self.variety = variety.upper()
        self.last_success = last_success
        self.last_attempt = last_attempt
        self.data_source = data_source
        self.status = status
        self.success_count = success_count
        self.failure_count = failure_count
        self.consecutive_failures = consecutive_failures
        self.retry_count = retry_count
        self.data_count = data_count
        self.last_error = last_error
        self.sla_deadline = sla_deadline

    def to_dict(self) -> Dict:
        return {
            'variety': self.variety,
            'last_success': self.last_success,
            'last_attempt': self.last_attempt,
            'data_source': self.data_source,
            'status': self.status,
            'success_count': self.success_count,
            'failure_count': self.failure_count,
            'consecutive_failures': self.consecutive_failures,
            'retry_count': self.retry_count,
            'data_count': self.data_count,
            'last_error': self.last_error,
            'sla_deadline': self.sla_deadline,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'FreshnessRecord':
        return cls(**{k: d.get(k, v) for k, v in cls.__annotations__.items()})

    def __repr__(self) -> str:
        return (f"<FreshnessRecord {self.variety}: status={self.status}, "
                f"last_success={self.last_success}, source={self.data_source}>")


class DataFreshnessMonitor:
    """数据新鲜度 SLA 监控器

    跟踪每个品种的数据刷新状态，确保在 SLA 窗口内完成全品种采集。
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or _FRESHNESS_DIR
        os.makedirs(self.data_dir, exist_ok=True)

        # 当前会话的状态快照（内存中）
        self._records: Dict[str, FreshnessRecord] = {}

        # 今天的记录文件
        today = date.today()
        self._today_file = os.path.join(
            self.data_dir, f'freshness_{today.isoformat()}.json'
        )

        # 历史文件（保留 30 天）
        self._history_dir = os.path.join(self.data_dir, 'freshness_history')
        os.makedirs(self._history_dir, exist_ok=True)

        # 加载今天的已有记录
        self._load_today()

    # ==================== 状态查询 ====================

    @staticmethod
    def get_sla_deadline() -> datetime:
        """计算今天的 SLA 截止时间（收盘后 30 分钟）"""
        now = datetime.now()
        # 日盘收盘 15:00
        close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
        # 如果是周末，SLA 不适用（返回 None）
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return close + timedelta(minutes=SLA_DEADLINE_MINUTES)
        # 如果当前时间已过收盘，deadline 是今天收盘后 30 分钟
        if now >= close:
            return close + timedelta(minutes=SLA_DEADLINE_MINUTES)
        # 如果当前还没收盘，deadline 仍然是今天收盘后 30 分钟（用于预热检查）
        return close + timedelta(minutes=SLA_DEADLINE_MINUTES)

    @staticmethod
    def is_trading_day() -> bool:
        """判断今天是否是交易日（周一至周五）"""
        return datetime.now().weekday() < 5

    @staticmethod
    def is_after_close() -> bool:
        """判断是否已收盘（日盘 15:00 后）"""
        now = datetime.now()
        return now.hour >= MARKET_CLOSE_HOUR

    def get_variety_status(self, variety: str) -> Dict:
        """获取单个品种的新鲜度状态"""
        sla = self.get_sla_deadline()
        record = self._records.get(variety.upper())
        if not record:
            return {
                'variety': variety.upper(),
                'status': 'pending',
                'last_success': None,
                'data_source': 'none',
                'data_count': 0,
                'retry_count': 0,
                'failure_count': 0,
                'last_error': '',
                'sla_deadline': sla.isoformat(),
                'is_within_sla': True,
                'message': '今日尚未采集',
            }

        now = datetime.now()

        # 计算状态
        if record.status == 'failed' and record.retry_count < MAX_RETRIES:
            status = 'pending_retry'
            remaining_retries = MAX_RETRIES - record.retry_count
        elif record.last_success:
            last_success_dt = datetime.fromisoformat(record.last_success)
            if now > sla and last_success_dt < sla:
                status = 'stale'  # 过了 SLA 窗口才更新
            elif now > sla and last_success_dt >= sla:
                status = 'fresh'
            elif now <= sla:
                status = 'pending'  # 还没到截止时间
            else:
                status = 'fresh'
        elif record.status == 'failed':
            status = 'failed'
        else:
            status = 'pending'

        return {
            'variety': variety.upper(),
            'status': status,
            'last_success': record.last_success,
            'data_source': record.data_source,
            'data_count': record.data_count,
            'retry_count': record.retry_count,
            'failure_count': record.failure_count,
            'last_error': record.last_error,
            'sla_deadline': sla.isoformat(),
            'is_within_sla': status in ('fresh', 'pending'),
        }

    def check_sla(self, variety: str) -> bool:
        """检查特定品种是否在 SLA 内"""
        status = self.get_variety_status(variety)
        return status.get('is_within_sla', False)

    # ==================== 记录采集 ====================

    def record_collection(
        self,
        variety: str,
        data_source: str = 'unknown',
        success: bool = True,
        count: int = 0,
        error: str = '',
        force_override: bool = False,
    ):
        """记录一次品种数据采集的结果

        Args:
            variety: 品种代码
            data_source: 数据来源
            success: 是否成功
            count: 获取的数据条数
            error: 错误信息（失败时）
            force_override: 是否强制覆盖已有记录（用于预热/重试覆盖旧数据）
        """
        v = variety.upper()
        now = datetime.now().isoformat()

        if v not in self._records:
            self._records[v] = FreshnessRecord(variety=v)

        record = self._records[v]
        record.last_attempt = now
        record.data_source = data_source

        if success:
            record.last_success = now
            record.success_count += 1
            record.consecutive_failures = 0
            record.data_count = count
            record.last_error = ''
            # 如果今天已收盘 → 状态标记为 fresh（在 SLA 内）
            if self.is_after_close() and self.is_trading_day():
                record.status = 'fresh'
            else:
                record.status = 'pending'
        else:
            record.failure_count += 1
            record.consecutive_failures += 1
            record.last_error = error[:200]
            if record.consecutive_failures >= MAX_RETRIES:
                record.status = 'failed'
            else:
                record.status = 'pending_retry'

        # 保存到磁盘
        self._save_today()

    def record_batch_collection(
        self,
        results: Dict[str, Dict],
    ):
        """批量记录多个品种的采集结果

        Args:
            results: {variety: {'success': bool, 'data_source': str, 'count': int, 'error': str}}
        """
        for variety, result in results.items():
            self.record_collection(
                variety=variety,
                data_source=result.get('data_source', 'unknown'),
                success=result.get('success', False),
                count=result.get('count', 0),
                error=result.get('error', ''),
            )

    # ==================== 重试管理 ====================

    def get_pending_retries(self) -> List[Dict]:
        """获取需要重试的品种列表（失败但未达最大重试次数）"""
        now = datetime.now()

        # 只在工作日收盘后检查重试
        if not self.is_trading_day() or not self.is_after_close():
            return []

        retries = []
        for record in self._records.values():
            if record.status == 'pending_retry' and record.retry_count < MAX_RETRIES:
                # 检查间隔是否足够
                if record.last_attempt:
                    last_attempt_dt = datetime.fromisoformat(record.last_attempt)
                    elapsed = (now - last_attempt_dt).total_seconds() / 60
                    if elapsed < RETRY_INTERVAL_MINUTES:
                        continue
                retries.append({
                    'variety': record.variety,
                    'retry_count': record.retry_count,
                    'remaining_retries': MAX_RETRIES - record.retry_count,
                    'last_error': record.last_error,
                    'data_source': record.data_source,
                })

        return retries

    def mark_retry(self, variety: str):
        """标记一次重试（增加重试计数）"""
        v = variety.upper()
        if v in self._records:
            self._records[v].retry_count += 1
            self._save_today()

    def reset_retries(self, variety: str):
        """重置重试计数（用于人工干预后）"""
        v = variety.upper()
        if v in self._records:
            self._records[v].retry_count = 0
            self._records[v].consecutive_failures = 0
            self._records[v].status = 'pending'
            self._save_today()

    # ==================== SLA 报告 ====================

    def generate_daily_report(self) -> Dict:
        """生成今日数据新鲜度报告"""
        if not self.is_trading_day():
            return {
                'date': date.today().isoformat(),
                'is_trading_day': False,
                'message': '今天不是交易日，无 SLA 检查',
            }

        sla_deadline = self.get_sla_deadline()
        now = datetime.now()

        # 检查所有活跃品种
        all_statuses = {}
        for v in ACTIVE_VARIETIES:
            all_statuses[v] = self.get_variety_status(v)

        # 统计
        total = len(ACTIVE_VARIETIES)
        fresh = sum(1 for s in all_statuses.values() if s['status'] == 'fresh')
        pending = sum(1 for s in all_statuses.values() if s['status'] == 'pending')
        pending_retry = sum(1 for s in all_statuses.values() if s['status'] == 'pending_retry')
        failed = sum(1 for s in all_statuses.values() if s['status'] == 'failed')
        stale = sum(1 for s in all_statuses.values() if s['status'] == 'stale')
        not_checked = sum(1 for s in all_statuses.values() if s['status'] == 'pending' and not s.get('last_success'))

        # SLA 合规率
        sla_compliant = fresh
        sla_coverage = sla_compliant / total * 100 if total > 0 else 0

        # 找出超出 SLA 的品种
        sla_outages = [v for v in ACTIVE_VARIETIES if all_statuses[v]['status'] == 'failed']
        stale_varieties = [v for v in ACTIVE_VARIETIES if all_statuses[v]['status'] == 'stale']

        # 是否已过 SLA 截止时间
        deadline_passed = now > sla_deadline

        return {
            'date': date.today().isoformat(),
            'is_trading_day': True,
            'deadline_passed': deadline_passed,
            'sla_deadline': sla_deadline.isoformat(),
            'now': now.isoformat(),
            'total_varieties': total,
            'fresh': fresh,
            'pending': pending,
            'pending_retry': pending_retry,
            'failed': failed,
            'stale': stale,
            'not_checked': not_checked,
            'sla_compliant': sla_compliant,
            'sla_coverage_pct': round(sla_coverage, 2),
            'sla_outages': sla_outages,
            'stale_varieties': stale_varieties,
            'all_statuses': all_statuses,
        }

    def get_freshness_score(self) -> float:
        """计算今日数据新鲜度评分 (0.0 ~ 1.0)"""
        report = self.generate_daily_report()
        if not report.get('is_trading_day'):
            return 1.0  # 非交易日满分

        total = report['total_varieties']
        if total == 0:
            return 1.0

        # 评分算法：
        # - fresh: 1.0 分
        # - pending (未到截止时间): 1.0 分
        # - pending_retry: 0.5 分（还有重试机会）
        # - stale (迟到但已更新): 0.7 分
        # - failed: 0.0 分
        weights = {
            'fresh': 1.0,
            'pending': 1.0,
            'pending_retry': 0.5,
            'stale': 0.7,
            'failed': 0.0,
        }

        score_sum = 0
        for s in report.get('all_statuses', {}).values():
            score_sum += weights.get(s['status'], 0.3)

        return round(score_sum / total, 4)

    def get_history(self, days: int = 7) -> List[Dict]:
        """获取最近 N 天的 SLA 报告历史"""
        history = []
        now = date.today()
        for i in range(days):
            d = now - timedelta(days=i)
            f = os.path.join(self._history_dir, f'freshness_{d.isoformat()}.json')
            if os.path.exists(f):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        history.append(json.load(fh))
                except (json.JSONDecodeError, Exception):
                    continue
        return history

    def get_sla_history_point(self, days: int = 7) -> Dict:
        """获取 SLA 合规率历史用于趋势分析"""
        reports = self.get_history(days)
        # 加上今日报告
        today_report = self.generate_daily_report()
        if today_report.get('is_trading_day'):
            reports.insert(0, today_report)

        points = []
        for r in reports:
            points.append({
                'date': r['date'],
                'sla_coverage_pct': r.get('sla_coverage_pct', 0),
                'freshness_score': r.get('freshness_score', 
                    self._calc_score_from_report(r)),
                'failed': len(r.get('sla_outages', [])),
            })

        return {
            'points': points,
            'avg_coverage': round(sum(p['sla_coverage_pct'] for p in points) / len(points), 2) if points else 0,
            'trend': 'up' if len(points) >= 2 and points[0]['sla_coverage_pct'] > points[-1]['sla_coverage_pct'] else 'stable',
        }

    def _calc_score_from_report(self, report: Dict) -> float:
        """从报告中计算评分"""
        weights = {'fresh': 1.0, 'pending': 1.0, 'pending_retry': 0.5, 'stale': 0.7, 'failed': 0.0}
        total = report.get('total_varieties', 1)
        if total == 0:
            return 1.0
        score = 0
        for status, weight in weights.items():
            score += report.get(status, 0) * weight
        return round(score / total, 4)

    # ==================== 持久化 ====================

    def _load_today(self):
        """加载今天的记录"""
        if os.path.exists(self._today_file):
            try:
                with open(self._today_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item in data:
                    if 'variety' in item:
                        record = FreshnessRecord(
                            variety=item['variety'],
                            last_success=item.get('last_success'),
                            last_attempt=item.get('last_attempt'),
                            data_source=item.get('data_source', 'none'),
                            status=item.get('status', 'pending'),
                            success_count=item.get('success_count', 0),
                            failure_count=item.get('failure_count', 0),
                            consecutive_failures=item.get('consecutive_failures', 0),
                            retry_count=item.get('retry_count', 0),
                            data_count=item.get('data_count', 0),
                            last_error=item.get('last_error', ''),
                            sla_deadline=item.get('sla_deadline'),
                        )
                        self._records[item['variety']] = record
            except (json.JSONDecodeError, Exception) as e:
                print(f"[FreshnessMonitor] 加载今日记录失败: {e}")

    def _save_today(self):
        """将今日记录保存到磁盘"""
        try:
            data = [r.to_dict() for r in self._records.values()]
            with open(self._today_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[FreshnessMonitor] 保存今日记录失败: {e}")

    def save_daily_report(self) -> str:
        """生成并保存今日 SLA 报告到 history 目录"""
        report = self.generate_daily_report()
        report['freshness_score'] = self.get_freshness_score()

        fpath = os.path.join(self._history_dir, f'freshness_{date.today().isoformat()}.json')
        try:
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[FreshnessMonitor] 保存历史报告失败: {e}")

        return fpath

    # ==================== 清理 ====================

    def clean_old_history(self, keep_days: int = 30):
        """清理超过 keep_days 天的历史记录"""
        if not os.path.exists(self._history_dir):
            return
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for fname in os.listdir(self._history_dir):
            fpath = os.path.join(self._history_dir, fname)
            if os.path.isfile(fpath) and fname.startswith('freshness_'):
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
        if removed:
            print(f"[FreshnessMonitor] 已清理 {removed} 条过期历史记录")


# ============================================================
# 集成入口 — 与 MultiSourceAdapter 连接
# ============================================================

_freshness_monitor_instance: Optional[DataFreshnessMonitor] = None


def get_monitor() -> DataFreshnessMonitor:
    """获取全局 DataFreshnessMonitor 单例"""
    global _freshness_monitor_instance
    if _freshness_monitor_instance is None:
        _freshness_monitor_instance = DataFreshnessMonitor()
        # 自动连接告警系统：生成SLA报告时检测违规并推送
        try:
            from scripts.alert_manager import get_alert_manager
            _am = get_alert_manager()
            _original_generate = _freshness_monitor_instance.generate_daily_report
            def _generate_with_alerts():
                report = _original_generate()
                if report.get('is_trading_day') and report.get('deadline_passed'):
                    outages = report.get('sla_outages', [])
                    for v in outages[:5]:  # 最多报5个，避免刷屏
                        _am.alert_sla_violation(v, 'freshness',
                            f'SLA 截止{report.get("sla_deadline","?")} 后仍未采集')
                    stale = report.get('stale_varieties', [])
                    for v in stale[:3]:
                        _am.alert_sla_violation(v, 'stale_data', '迟到但已更新')
                return report
            _freshness_monitor_instance.generate_daily_report = _generate_with_alerts
        except ImportError:
            pass
    return _freshness_monitor_instance


def record_data_fetch(variety: str, data_source: str = 'unknown',
                      success: bool = True, count: int = 0, error: str = ''):
    """供 MultiSourceAdapter 调用的便捷入口——每次数据获取后调用"""
    monitor = get_monitor()
    monitor.record_collection(variety, data_source, success, count, error)


def get_sla_report() -> Dict:
    """获取 SLA 报告"""
    return get_monitor().generate_daily_report()


def get_freshness_score() -> float:
    """获取新鲜度评分"""
    return get_monitor().get_freshness_score()


def get_pending_retries() -> List[Dict]:
    """获取待重试品种"""
    return get_monitor().get_pending_retries()


# ============================================================
# 命令行入口
# ============================================================

def main():
    import sys
    monitor = get_monitor()

    if len(sys.argv) < 2:
        # 默认：今日 SLA 报告
        report = monitor.generate_daily_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    cmd = sys.argv[1]

    if cmd == 'report':
        report = monitor.generate_daily_report()
        score = monitor.get_freshness_score()
        report['freshness_score'] = score

        print("=" * 60)
        print(f"  📊 数据新鲜度 SLA 报告 — {report['date']}")
        print("=" * 60)
        print(f"  交易日: {'是' if report['is_trading_day'] else '否'}")
        if report['is_trading_day']:
            print(f"  SLA 截止: {report['sla_deadline']}")
            print(f"  当前时间: {report['now']}")
            print(f"  SLA 已过期: {'是' if report['deadline_passed'] else '否'}")
            print(f"  活跃品种数: {report['total_varieties']}")
            print(f"  ✅ 新鲜 (SLA内): {report['fresh']}")
            print(f"  ⏳ 待采集: {report['pending']}")
            print(f"  🔄 待重试: {report['pending_retry']}")
            print(f"  ⚠️ 迟到但已更新: {report['stale']}")
            print(f"  ❌ 失败: {report['failed']}")
            print(f"  📊 SLA 合规率: {report['sla_coverage_pct']}%")
            print(f"  🏆 新鲜度评分: {score}")
            if report['sla_outages']:
                print(f"\n  ❌ SLA 违规品种 ({len(report['sla_outages'])}个):")
                for v in report['sla_outages'][:10]:
                    s = report['all_statuses'].get(v, {})
                    print(f"    - {v}: {s.get('last_error', '未知错误')}")
            if report['stale_varieties']:
                print(f"\n  ⚠️ 迟到品种 ({len(report['stale_varieties'])}个):")
                for v in report['stale_varieties'][:10]:
                    print(f"    - {v}")
        print("=" * 60)

        # 保存报告
        monitor.save_daily_report()

    elif cmd == 'score':
        score = monitor.get_freshness_score()
        report = monitor.generate_daily_report()
        print(f"今日新鲜度评分: {score}")
        print(f"SLA 合规率: {report['sla_coverage_pct']}%")
        print(f"✅ 新鲜: {report['fresh']}/{report['total_varieties']} | "
              f"❌ 失败: {report['failed']}/{report['total_varieties']} | "
              f"⏳ 待采集: {report['not_checked']}/{report['total_varieties']}")

    elif cmd == 'status':
        if len(sys.argv) < 3:
            print("Usage: python data_freshness_monitor.py status <variety>")
            return
        variety = sys.argv[2].upper()
        status = monitor.get_variety_status(variety)
        print(json.dumps(status, indent=2, ensure_ascii=False))

    elif cmd == 'retry':
        retries = monitor.get_pending_retries()
        if not retries:
            print("✅ 没有需要重试的品种")
        else:
            print(f"🔄 {len(retries)} 个品种需要重试:")
            for r in retries:
                print(f"  - {r['variety']}: {r['last_error'][:60]} (已重试 {r['retry_count']}/{r['remaining_retries']})")

    elif cmd == 'history':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        history = monitor.get_sla_history_point(days)
        print(json.dumps(history, indent=2, ensure_ascii=False))

    elif cmd == 'clean':
        keep_days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        monitor.clean_old_history(keep_days)

    else:
        print("Usage: python data_freshness_monitor.py [report|score|status <variety>|retry|history [days]|clean [days]]")


if __name__ == '__main__':
    main()
