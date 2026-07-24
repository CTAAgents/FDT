"""futures-debate-team 子 skill 间通信契约，所有 schema 版本 3.0

覆盖9角色全链路(v8.7.0)：数技源→链证源→闫判官(含交易参数)→探源/观澜→证真/慎思→风控明→明鉴秋
"""

from .base import *
from .chain_analysis import *
from .data_collection import *
from .debate import *
from .evidence_brief import *
from .fundamental_state import *
from .judge import *
from .migrations import *
from .risk import *
from .sentiment_state import *
from .team_decision import *
from .technical import *
from .trading_plan import *

__version__ = "3.0.0"
