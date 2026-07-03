#!/usr/bin/env python3
"""
数据源配置加载器
从 data_sources.yaml 读取数据源注册表，提供类型安全的访问接口

用法：
    config = DataSourceConfig()
    sources = config.get_priority_list(is_trading_hour=True)
    # → [DataSource.TQSDK(pri=1), DataSource.EXCHANGE_API(pri=2), ...]

    if config.is_enabled('akshare'):
        print('AKShare 可用')
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class DataSource(Enum):
    """数据源枚举（与 data_sources.yaml 的 name 字段对齐）"""
    TQSDK = "tqsdk"
    EXCHANGE_API = "exchange_api"
    EASTMONEY = "eastmoney"
    AKSHARE = "akshare"
    WEBSEARCH = "websearch"
    CACHE = "cache"
    JIN10 = "jin10"
    TDX = "tdx"
    TDX_LOCAL = "tdx_local"
    IWENCAI = "iwencai"
    NONE = "none"


@dataclass
class DataSourceEntry:
    """单个数据源的配置条目"""
    name: str
    display_name: str
    enabled: bool
    priority_intraday: int
    priority_afternoon: int
    description: str
    category: str = "price"  # price=行情数据, news=资讯数据, comprehensive=综合数据源, skillhub=问财数据源
    params: Dict[str, Any] = field(default_factory=dict)


class DataSourceConfig:
    """
    数据源配置加载器

    加载 references/data_sources.yaml 并缓存。
    提供按场景（盘中/盘后）排序的可用数据源列表。
    """

    _instance = None
    _config: Dict[str, DataSourceEntry] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        """加载 YAML 配置文件"""
        config_path = Path(__file__).parent.parent / "references" / "data_sources.yaml"
        if not config_path.exists():
            print(f"[Warning] 数据源配置文件不存在: {config_path}")
            self._config = {}
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        self._config = {}
        for entry in raw.get('sources', []):
            name = entry.get('name', '')
            if not name:
                continue
            self._config[name] = DataSourceEntry(
                name=name,
                display_name=entry.get('display_name', name),
                category=entry.get('type', 'price'),  # type 字段映射为 category
                enabled=entry.get('enabled', True),
                priority_intraday=entry.get('priority_intraday', 99),
                priority_afternoon=entry.get('priority_afternoon', 99),
                description=entry.get('description', ''),
                params=entry.get('params', {}),
            )

    def is_enabled(self, name: str) -> bool:
        """检查数据源是否启用"""
        entry = self._config.get(name)
        return entry.enabled if entry else False

    def get_entry(self, name: str) -> Optional[DataSourceEntry]:
        """获取数据源配置条目"""
        return self._config.get(name)

    def get_priority_list(self, is_trading_hour: bool = True) -> List[DataSource]:
        """
        获取按优先级排序的可用的数据源列表

        Args:
            is_trading_hour: 是否为盘中交易时段

        Returns:
            按优先级排序的 DataSource 枚举列表
        """
        priority_key = 'priority_intraday' if is_trading_hour else 'priority_afternoon'

        # 过滤启用且类型为 price 的，按优先级排序
        sorted_entries = sorted(
            [e for e in self._config.values() if e.enabled and e.category == 'price'],
            key=lambda e: getattr(e, priority_key, 99)
        )

        result = []
        for entry in sorted_entries:
            try:
                result.append(DataSource(entry.name))
            except ValueError:
                # 配置中的名称不在枚举中，跳过
                continue

        return result

    def get_sources_by_category(self, category: str) -> List[DataSourceEntry]:
        """
        按类型获取数据源列表

        Args:
            category: 数据源类型（price / news）

        Returns:
            该类型下所有启用的数据源条目
        """
        return [e for e in self._config.values() if e.enabled and e.category == category]

    def get_all_sources(self) -> List[DataSourceEntry]:
        """获取所有已注册的数据源（含禁用）"""
        return list(self._config.values())

    def get_enabled_sources(self) -> List[DataSourceEntry]:
        """获取所有启用的数据源"""
        return [e for e in self._config.values() if e.enabled]

    def get_param(self, name: str, key: str, default: Any = None) -> Any:
        """获取数据源的参数"""
        entry = self._config.get(name)
        if entry:
            return entry.params.get(key, default)
        return default

    def reload(self):
        """重新加载配置文件（运行时热加载）"""
        self._load()

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（用于调试/状态显示）"""
        return {
            name: {
                "display_name": entry.display_name,
                "category": entry.category,
                "enabled": entry.enabled,
                "priority_intraday": entry.priority_intraday,
                "priority_afternoon": entry.priority_afternoon,
            }
            for name, entry in self._config.items()
        }


# ==================== 快捷接口 ====================

def get_priority_sources(is_trading_hour: bool = True) -> List[DataSource]:
    """获取按优先级排序的数据源列表（快捷方式）"""
    return DataSourceConfig().get_priority_list(is_trading_hour)


def is_source_enabled(name: str) -> bool:
    """检查数据源是否启用（快捷方式）"""
    return DataSourceConfig().is_enabled(name)


if __name__ == "__main__":
    # 测试
    config = DataSourceConfig()
    print("=== 数据源配置 ===")
    for name, info in config.to_dict().items():
        status = "✓" if info["enabled"] else "✗"
        cat = info["category"]
        print(f"  {status} [{cat:5s}] {name:20s} 盘中={info['priority_intraday']} 盘后={info['priority_afternoon']}")

    print("\n=== 盘中优先级（仅 price 类型） ===")
    for s in get_priority_sources(is_trading_hour=True):
        print(f"  → {s.value}")

    print("\n=== 盘后优先级（仅 price 类型） ===")
    for s in get_priority_sources(is_trading_hour=False):
        print(f"  → {s.value}")

    print("\n=== 资讯数据源（news 类型） ===")
    for e in config.get_sources_by_category('news'):
        print(f"  → {e.name} ({e.display_name})")

    print("\n=== 综合数据源（comprehensive 类型） ===")
    for e in config.get_sources_by_category('comprehensive'):
        print(f"  → {e.name} ({e.display_name})")

    print("\n=== 问财数据源（skillhub 类型） ===")
    for e in config.get_sources_by_category('skillhub'):
        print(f"  → {e.name} ({e.display_name})")
