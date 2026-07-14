"""P4 回归类范式（骨架）— 未来聚焦位：填滚动 OLS 残差 / 协整残差公开主流因子实现。

当前 FDT 无回归类信号产出，此为预留位。一旦接入（如价差/基差回归），只需：
  1) 在 ChannelBreakoutStrategy 或新引擎中产出 signal_type；
  2) 在 config.settings.SIGNAL_VALIDATOR_MAP 登记该 signal_type → [验证器]；
  3) 在此注册范式元信息。
框架无需改动扫描主链。
"""

from . import register_paradigm


class RegressionParadigm:
    id = "regression"
    label = "回归类 (滚动 OLS 残差 / 协整残差)"
    signal_types = []  # 当前无产出，预留
    validators = ["stability", "crowding"]
    note = "骨架：当前 FDT 无回归类信号产出，预留位。"


register_paradigm("regression", RegressionParadigm)
