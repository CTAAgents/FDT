#!/usr/bin/env python3
"""
主力合约映射算法实现
每日更新主力/次主力合约映射表
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# 配置路径
SKILL_DIR = Path(__file__).parent.parent
DOMINANT_MAP_DIR = SKILL_DIR / "data" / "dominant_maps"

# 最大保留历史天数（超过自动清理）
MAX_HISTORY_DAYS = 90


@dataclass
class ContractInfo:
    """合约信息"""

    code: str  # 合约代码，如 CU2609
    volume: int  # 成交量
    open_interest: int  # 持仓量
    last_trade_date: str  # 最后交易日 YYYY-MM-DD
    close_price: float  # 收盘价
    delivery_month: str  # 交割月 YYMM


class DominantMappingCalculator:
    """
    主力合约映射计算器

    算法说明：
    - 商品期货：盯持仓量最大 + 1.1倍阈值 + 远月约束 + 最后交易日前3日剔除
    - 金融期货（中金所）：改为盯成交量最大，其余规则相同
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or DOMINANT_MAP_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def calculate_dominant(
        self,
        variety: str,
        contracts: List[ContractInfo],
        current_main: Optional[str] = None,
        trade_date: str = None,
        is_financial: bool = False,
    ) -> Dict[str, Any]:
        """
        计算主力/次主力合约

        Args:
            variety: 品种代码
            contracts: 当日所有合约信息
            current_main: 当前主力合约代码
            trade_date: 交易日 YYYY-MM-DD
            is_financial: 是否为金融期货（中金所）

        Returns:
            主力映射结果
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")

        # Step 1: 剔除最后交易日 ≤ T+3 的合约
        valid_contracts = []
        for c in contracts:
            ltd = datetime.strptime(c.last_trade_date, "%Y-%m-%d")
            if ltd > trade_dt + timedelta(days=3):
                valid_contracts.append(c)

        if not valid_contracts:
            # 如果所有合约都临近交割，返回空结果
            return {
                "variety": variety,
                "main": None,
                "next_main": None,
                "index": None,
                "prev_main": current_main,
                "switched": False,
                "switch_date": None,
                "gap": None,
                "updated_at": datetime.now().isoformat(),
                "error": "所有合约临近交割，无法确定主力",
            }

        # Step 2: 按持仓量（金融期货按成交量）降序排列
        if is_financial:
            valid_contracts.sort(key=lambda x: x.volume, reverse=True)
        else:
            valid_contracts.sort(key=lambda x: x.open_interest, reverse=True)

        # Step 3: 确定主力合约
        new_main = None
        switched = False
        gap = None
        switch_date = None
        prev_main = current_main

        if len(valid_contracts) >= 2:
            o1 = valid_contracts[0]  # 持仓量最大的合约
            o2 = valid_contracts[1]  # 持仓量第二的合约

            # 获取指标值
            o1_metric = o1.open_interest if not is_financial else o1.volume
            o2_metric = o2.open_interest if not is_financial else o2.volume

            # 如果当前主力存在且仍是持仓量最大的，维持不变
            if current_main and o1.code == current_main:
                new_main = o1.code
            # 如果持仓量最大的合约不是当前主力，判断是否切换
            elif current_main and o1.code != current_main:
                # 找到当前主力的持仓量
                current_main_contract = next((c for c in valid_contracts if c.code == current_main), None)
                if current_main_contract:
                    current_metric = (
                        current_main_contract.open_interest if not is_financial else current_main_contract.volume
                    )
                    # 切换条件：新主力持仓量 ≥ 当前主力 × 1.1 且新主力是远月
                    if o1_metric >= current_metric * 1.1 and int(o1.delivery_month) > int(
                        current_main_contract.delivery_month
                    ):
                        new_main = o1.code
                        switched = True
                        switch_date = trade_date
                        gap = o1.close_price - current_main_contract.close_price
                    else:
                        # 不满足切换条件，维持当前主力
                        new_main = current_main
                else:
                    # 当前主力不在有效合约列表中，切换到持仓量最大的
                    new_main = o1.code
                    switched = True
                    switch_date = trade_date
            else:
                # 没有当前主力，选择持仓量最大的
                new_main = o1.code
        elif valid_contracts:
            new_main = valid_contracts[0].code

        # Step 4: 确定次主力
        next_main = None
        if len(valid_contracts) >= 2:
            for c in valid_contracts:
                if c.code != new_main:
                    next_main = c.code
                    break

        # Step 5: 计算指数连续（加权平均）
        total_oi = sum(c.open_interest for c in valid_contracts)
        if total_oi > 0:
            index_price = sum(c.open_interest * c.close_price for c in valid_contracts) / total_oi
        else:
            index_price = None

        return {
            "variety": variety,
            "main": new_main,
            "next_main": next_main,
            "index": f"{variety}99",  # 指数连续合约代码
            "index_price": index_price,
            "prev_main": prev_main,
            "switched": switched,
            "switch_date": switch_date,
            "prev_close": next((c.close_price for c in contracts if c.code == prev_main), None) if prev_main else None,
            "new_open": None,  # 需要在T+1开盘时填入
            "gap": gap,
            "updated_at": datetime.now().isoformat(),
        }

    def update_all_varieties(
        self,
        all_contracts: Dict[str, List[ContractInfo]],
        current_mappings: Dict[str, Dict],
        trade_date: str,
        financial_varieties: List[str] = None,
    ) -> Dict[str, Dict]:
        """
        更新所有品种的主力映射

        Args:
            all_contracts: 所有品种的合约信息 {variety: [ContractInfo]}
            current_mappings: 当前映射表
            trade_date: 交易日
            financial_varieties: 金融期货品种列表（中金所）

        Returns:
            更新后的映射表
        """
        if financial_varieties is None:
            financial_varieties = ["IF", "IC", "IM", "IH", "TS", "TF", "T", "TL"]

        new_mappings = {}

        for variety, contracts in all_contracts.items():
            current_main = current_mappings.get(variety, {}).get("main")
            is_financial = variety in financial_varieties

            new_mappings[variety] = self.calculate_dominant(
                variety=variety,
                contracts=contracts,
                current_main=current_main,
                trade_date=trade_date,
                is_financial=is_financial,
            )

        return new_mappings

    def save_mapping(self, mappings: Dict[str, Dict], trade_date: str) -> Path:
        """
        保存映射表到文件

        Args:
            mappings: 映射表
            trade_date: 交易日

        Returns:
            保存的文件路径
        """
        # 保存带日期的文件
        date_str = trade_date.replace("-", "")
        filename = f"dominant_map_{date_str}.json"
        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(mappings, f, ensure_ascii=False, indent=2)

        # 同时更新 latest 文件
        latest_filepath = self.output_dir / "dominant_map_latest.json"
        with open(latest_filepath, "w", encoding="utf-8") as f:
            json.dump(mappings, f, ensure_ascii=False, indent=2)

        return filepath

    def get_switch_report(self, old_mappings: Dict, new_mappings: Dict) -> List[Dict]:
        """
        生成换月报告

        Args:
            old_mappings: 旧映射表
            new_mappings: 新映射表

        Returns:
            换月事件列表
        """
        switches = []

        for variety, new_info in new_mappings.items():
            if new_info.get("switched"):
                old_info = old_mappings.get(variety, {})
                switches.append(
                    {
                        "variety": variety,
                        "prev_main": old_info.get("main"),
                        "new_main": new_info.get("main"),
                        "switch_date": new_info.get("switch_date"),
                        "gap": new_info.get("gap"),
                        "prev_close": new_info.get("prev_close"),
                    }
                )

        return switches


class DominantMappingArchive:
    """
    主力映射历史归档

    提供：
    - 按日期检索历史映射
    - 查询特定品种的历史主力变迁
    - 自动清理过期文件
    """

    def __init__(self, archive_dir: Optional[Path] = None):
        self.archive_dir = archive_dir or DOMINANT_MAP_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def list_available_dates(self) -> List[str]:
        """返回所有可用的历史归档日期（已排序）"""
        dates = []
        for f in self.archive_dir.glob("dominant_map_*.json"):
            if f.name == "dominant_map_latest.json":
                continue
            # 格式: dominant_map_YYYYMMDD.json
            date_str = f.stem.replace("dominant_map_", "")
            if date_str.isdigit() and len(date_str) == 8:
                dates.append(date_str)
        return sorted(dates, reverse=True)

    def get_by_date(self, date_str: str) -> Dict[str, Any]:
        """
        获取指定日期的映射数据

        Args:
            date_str: YYYYMMDD 或 YYYY-MM-DD

        Returns:
            映射表
        """
        date_clean = date_str.replace("-", "")
        filepath = self.archive_dir / f"dominant_map_{date_clean}.json"
        if not filepath.exists():
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def get_variety_history(self, variety: str, max_dates: int = 30) -> List[Dict]:
        """
        查询特定品种的历史主力变迁

        Args:
            variety: 品种代码
            max_dates: 查询最近多少个交易日

        Returns:
            [{"date": "20260626", "main": "CU2609", "index_price": 78780, ...}, ...]
        """
        dates = self.list_available_dates()[:max_dates]
        history = []
        for date_str in dates:
            mapping = self.get_by_date(date_str)
            if variety in mapping:
                entry = mapping[variety]
                entry["_date"] = date_str
                history.append(entry)
        return history

    def get_switch_timeline(self, variety: str, max_dates: int = 90) -> List[Dict]:
        """
        获取品种的换月事件时间线

        Returns:
            [{"date": "20260627", "prev_main": "CU2608", "new_main": "CU2609", "gap": 580}, ...]
        """
        dates = self.list_available_dates()[:max_dates]
        switches = []
        prev_main = None

        for date_str in reversed(dates):
            mapping = self.get_by_date(date_str)
            if variety not in mapping:
                continue
            info = mapping[variety]
            current_main = info.get("main")
            if current_main and prev_main and current_main != prev_main:
                switches.append(
                    {
                        "date": date_str,
                        "prev_main": prev_main,
                        "new_main": current_main,
                        "gap": info.get("gap"),
                        "switch_date": info.get("switch_date"),
                    }
                )
            prev_main = current_main

        return list(reversed(switches))

    def clean_expired(self, max_days: int = MAX_HISTORY_DAYS):
        """清理超过 max_days 的历史文件"""
        now = datetime.now()
        cleaned = 0
        for f in self.archive_dir.glob("dominant_map_*.json"):
            if f.name == "dominant_map_latest.json":
                continue
            # 从文件名解析日期
            date_str = f.stem.replace("dominant_map_", "")
            if not (date_str.isdigit() and len(date_str) == 8):
                continue
            try:
                file_date = datetime.strptime(date_str, "%Y%m%d")
                if (now - file_date).days > max_days:
                    f.unlink()
                    cleaned += 1
            except ValueError:
                continue
        if cleaned:
            print(f"[Archive] 已清理 {cleaned} 个过期归档文件（超过 {max_days} 天）")

    def save_mapping(self, mappings: Dict[str, Dict], trade_date: str) -> Path:
        """
        保存映射并清理过期文件
        继承 DominantMappingCalculator.save_mapping 的功能

        Args:
            mappings: 映射表
            trade_date: YYYY-MM-DD

        Returns:
            文件路径
        """
        calculator = DominantMappingCalculator(self.archive_dir)
        path = calculator.save_mapping(mappings, trade_date)
        self.clean_expired()
        return path


def main():
    """测试函数"""
    calculator = DominantMappingCalculator()

    # 模拟数据
    contracts = [
        ContractInfo(
            code="CU2607",
            volume=50000,
            open_interest=80000,
            last_trade_date="2026-07-15",
            close_price=78200,
            delivery_month="2607",
        ),
        ContractInfo(
            code="CU2608",
            volume=100000,
            open_interest=150000,
            last_trade_date="2026-08-15",
            close_price=78450,
            delivery_month="2608",
        ),
        ContractInfo(
            code="CU2609",
            volume=120000,
            open_interest=180000,
            last_trade_date="2026-09-15",
            close_price=78780,
            delivery_month="2609",
        ),
        ContractInfo(
            code="CU2610",
            volume=80000,
            open_interest=120000,
            last_trade_date="2026-10-15",
            close_price=79010,
            delivery_month="2610",
        ),
    ]

    result = calculator.calculate_dominant(
        variety="CU", contracts=contracts, current_main="CU2608", trade_date="2026-06-27"
    )

    print("主力映射结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
