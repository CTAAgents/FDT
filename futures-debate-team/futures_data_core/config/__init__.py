"""配置包：数据源、运行参数与静态缓存路径。

所有配置以声明式 YAML（``data_sources.yaml``）为主，环境变量为覆盖层，
确保同一份代码在本地、CI 与生产环境可通过环境变量无缝切换。
"""

from futures_data_core.config.settings import (
    Settings,
    get_settings,
    reload_settings,
)

__all__ = ["Settings", "get_settings", "reload_settings"]
