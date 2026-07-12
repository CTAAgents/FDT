"""futures-debate-team 子 skill 间通信契约，所有 schema 版本 3.0

覆盖10角色全链路：数技源→链证源→闫判官→探源/观澜→证真/慎思→策执远→风控明→明鉴秋
"""

from .base import *
from .data_collection import *
from .technical import *
from .chain_analysis import *
from .fundamental_state import *
from .debate import *
from .risk import *
from .evidence_brief import *
from .judge import *
from .trading_plan import *
from .team_decision import *
from .migrations import *

__version__ = "3.0.0"
