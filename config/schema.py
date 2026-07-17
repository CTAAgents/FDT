"""
FDT 配置 Schema 校验模块 v1.0
=============================

使用 Pydantic v2 对 settings.json 和 team_config.json 进行严格校验。
非法配置在启动阶段即被拒绝，防止静默降级。

用法:
    from config.schema import validate_settings, validate_team_config

    with open("settings.json") as f:
        settings = validate_settings(json.load(f))
    with open("config/team_config.json") as f:
        team_config = validate_team_config(json.load(f))
"""

from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────
# settings.json 模型
# ─────────────────────────────────────────────

class WebhooksConfig(BaseModel):
    """Webhook 通知配置"""
    wecom: str = Field(default="", description="企业微信 webhook URL")
    dingtalk: str = Field(default="", description="钉钉 webhook URL")
    email: str = Field(default="", description="邮件通知地址")


class BacktestConfig(BaseModel):
    """回测参数配置"""
    min_days: int = Field(default=600, ge=100, le=5000, description="最小回测天数")
    fee_rate: float = Field(default=0.001, ge=0.0, le=0.1, description="手续费率")


class Settings(BaseModel):
    """settings.json 顶层模型"""
    agent: str = Field(default="futures-debate-team-team-lead", description="团队主管 Agent ID")
    seed: Optional[int] = Field(default=None, ge=0, description="随机种子（null=不固定）")
    selection_threshold: float = Field(
        default=0.65, ge=0.0, le=1.0,
        description="辩论品种筛选阈值"
    )
    mode: Literal["dry-run", "production"] = Field(
        default="dry-run",
        description="运行模式: dry-run=模拟, production=实盘"
    )
    webhooks: WebhooksConfig = Field(default_factory=WebhooksConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)

    @model_validator(mode="after")
    def _warn_production_mode(self):
        """dry-run 模式下忽略 webhook 配置的校验"""
        return self  # 全模式不做额外约束


# ─────────────────────────────────────────────
# team_config.json 模型
# ─────────────────────────────────────────────

class SelfEvolutionConfig(BaseModel):
    """自进化控制开关"""
    skip_when_no_pending: bool = Field(default=True, description="无待验证裁决时跳过自进化")
    run_calibrate_when_validated_ge_5: bool = Field(
        default=True, description="已验证 ≥5 条时自动校准权重"
    )
    run_evolve_when_total_samples_ge_5: bool = Field(
        default=True, description="总样本 ≥5 时自动进化 Agent 参数"
    )
    skip_ml_when_feedback_lt_50: bool = Field(
        default=True, description="新辩论样本 <50 时跳过 ML 训练"
    )


class SingleVarietySkipConfig(BaseModel):
    """单品种模式跳过的操作"""
    full_62_scan: bool = Field(default=False, description="跳过全量 62 品种扫描")
    cross_chain_dedup_30plus: bool = Field(
        default=True, description="跳过同链 30+ 品种去重扫描"
    )
    note: str = Field(
        default="",
        description="配置说明"
    )


class AgentWaiterConfig(BaseModel):
    """Agent 产出轮询配置（L2 熔断参数）"""
    timeout_seconds: int = Field(
        default=900, ge=60, le=3600,
        description="单 Agent 产出等待超时（秒）"
    )
    poll_interval_seconds: int = Field(
        default=15, ge=5, le=60,
        description="轮询间隔（秒）"
    )
    stable_seconds: int = Field(
        default=5, ge=1, le=30,
        description="文件 size 稳定判定（秒）"
    )
    max_retries: int = Field(
        default=2, ge=0, le=5,
        description="最大重试次数（0=不重试）"
    )


class VenvConfig(BaseModel):
    """虚拟环境配置"""
    path: str = Field(default="venv/Scripts/python.exe", description="venv Python 路径")
    locked: str = Field(default="requirements.lock", description="依赖锁文件")
    note: str = Field(default="", description="配置说明")


class TeamConfig(BaseModel):
    """team_config.json 顶层模型"""
    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$", description="配置文件版本")
    updated_at: str = Field(default="", description="最后更新时间戳")
    single_variety_fast_track: bool = Field(
        default=True, description="单品种快轨模式"
    )
    agent_watchdog_seconds: int = Field(
        default=420, ge=60, le=3600,
        description="Agent 看门狗超时（秒）"
    )
    self_evolution: SelfEvolutionConfig = Field(default_factory=SelfEvolutionConfig)
    skip_for_single_variety: SingleVarietySkipConfig = Field(
        default_factory=SingleVarietySkipConfig
    )
    agent_waiter: AgentWaiterConfig = Field(default_factory=AgentWaiterConfig)
    venv: VenvConfig = Field(default_factory=VenvConfig)
    note: str = Field(default="", description="配置说明")


# ─────────────────────────────────────────────
# 校验函数
# ─────────────────────────────────────────────

def validate_settings(data: dict) -> Settings:
    """校验 settings.json 数据。

    Args:
        data: JSON 解析后的字典

    Returns:
        通过校验的 Settings 实例

    Raises:
        pydantic.ValidationError: 配置不合法
    """
    return Settings.model_validate(data)


def validate_team_config(data: dict) -> TeamConfig:
    """校验 config/team_config.json 数据。

    Args:
        data: JSON 解析后的字典

    Returns:
        通过校验的 TeamConfig 实例

    Raises:
        pydantic.ValidationError: 配置不合法
    """
    return TeamConfig.model_validate(data)


def safe_validate_settings(data: dict) -> tuple[Optional[Settings], Optional[str]]:
    """安全校验 settings.json，不抛异常。

    Returns:
        (Settings实例, 错误信息) — 成功时错误为 None
    """
    try:
        return Settings.model_validate(data), None
    except Exception as e:
        return None, str(e)


def safe_validate_team_config(data: dict) -> tuple[Optional[TeamConfig], Optional[str]]:
    """安全校验 team_config.json，不抛异常。

    Returns:
        (TeamConfig实例, 错误信息) — 成功时错误为 None
    """
    try:
        return TeamConfig.model_validate(data), None
    except Exception as e:
        return None, str(e)


if __name__ == "__main__":
    import json
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent

    # 测试 settings.json
    settings_path = ROOT / "settings.json"
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        s, err = safe_validate_settings(data)
        if s:
            print(f"✅ settings.json 校验通过 (mode={s.mode})")
        else:
            print(f"❌ settings.json 校验失败: {err}")
    else:
        print("⚠️ settings.json 未找到")

    # 测试 team_config.json
    tc_path = ROOT / "config" / "team_config.json"
    if tc_path.exists():
        data = json.loads(tc_path.read_text(encoding="utf-8"))
        tc, err = safe_validate_team_config(data)
        if tc:
            print(f"✅ team_config.json 校验通过 (version={tc.version})")
        else:
            print(f"❌ team_config.json 校验失败: {err}")
    else:
        print("⚠️ team_config.json 未找到")
