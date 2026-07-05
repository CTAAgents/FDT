# -*- coding: utf-8 -*-
"""fundamental-data-collector — 基本面数据采集模块 v1.1.0"""

from .supply import query_supply
from .demand import query_demand
from .inventory import query_inventory
from .margin import query_margin
from .term_basis import query_term, query_basis
from .macro_link import query_macro
from .chain_balance import query_chain_balance
from .web_collector import query_web
