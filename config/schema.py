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

from typing import Any, Literal, Optional

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


# ─────────────────────────────────────────────
# data_sources.yaml 模型
# ─────────────────────────────────────────────

class SourceDetectionConfig(BaseModel):
    """数据源检测配置"""
    kind: Literal["import", "http_probe", "always_available", "env_and_import"] = Field(...)
    import_: Optional[str] = Field(default=None, alias="import")
    url: Optional[str] = Field(default=None)
    env: Optional[list[str]] = Field(default=None)


class SourceConfig(BaseModel):
    """单个数据源配置"""
    name: str = Field(..., min_length=1)
    priority: int = Field(..., ge=0, le=99)
    type: str = Field(default="independent")
    enabled: bool = Field(default=True)
    description: str = Field(default="")
    detection: SourceDetectionConfig
    config: dict = Field(default_factory=dict)


class DegradeConfig(BaseModel):
    """降级触发条件"""
    sub_daily_max_age_days: int = Field(default=7, ge=1, le=90)
    daily_max_age_sessions: int = Field(default=5, ge=1, le=60)
    max_consecutive_failures: int = Field(default=3, ge=1, le=20)


class FreshnessConfig(BaseModel):
    """新鲜度断路器阈值"""
    min_scan_success_rate: float = Field(default=0.90, ge=0.0, le=1.0)
    min_bars_per_symbol: int = Field(default=30, ge=1)
    max_daily_age_sessions: int = Field(default=5, ge=1, le=60)
    max_subdaily_age_days: int = Field(default=7, ge=1, le=90)
    min_positive_volume_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    max_scan_duration_seconds: int = Field(default=120, ge=10, le=600)
    max_output_json_mb: int = Field(default=5, ge=1, le=100)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval_minutes: int = Field(default=5, ge=1, le=60)


class DataSourcesConfig(BaseModel):
    """data_sources.yaml 顶层模型"""
    sources: list[SourceConfig] = Field(..., min_length=1)
    degrade: DegradeConfig = Field(default_factory=DegradeConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)

    @model_validator(mode="after")
    def _unique_source_names(self):
        names = [s.name for s in self.sources]
        if len(names) != len(set(names)):
            raise ValueError(f"数据源名称重复: {[n for n in names if names.count(n) > 1]}")
        # 校验调度数据源 priority ≤ 局部数据源
        return self


# ─────────────────────────────────────────────
# agent_profiles.json 模型
# ─────────────────────────────────────────────

class EvolutionLogEntry(BaseModel):
    """进化日志条目"""
    time: str = Field(default="")
    action: str = Field(default="")
    from_: Any = Field(default=None, alias="from")
    to: Any = Field(default=None)
    reason: str = Field(default="")


class AgentStats(BaseModel):
    """Agent 统计数据（自由格式）"""
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_fields(cls, data: Any) -> dict:
        if isinstance(data, dict):
            return {"extra": data}
        return data


class RiskManagerProfile(BaseModel):
    """风控明配置"""
    atr_multiplier: float = Field(default=1.5, ge=0.1, le=10.0)
    max_position_pct_high: float = Field(default=5.0, ge=0.0, le=100.0)
    last_updated: Optional[str] = Field(default=None, alias="_last_updated")
    evolution_log: list[EvolutionLogEntry] = Field(default_factory=list, alias="_evolution_log")
    stats: AgentStats = Field(default_factory=AgentStats, alias="_stats")

    model_config = {"populate_by_name": True}


class DebaterSubProfile(BaseModel):
    """辩手续约配置"""
    role: str = Field(default="")
    strategy: str = Field(default="")
    confidence_boost: float = Field(default=0.0, ge=-1.0, le=1.0)
    samples: int = Field(default=0, ge=0, alias="_samples")
    note: str = Field(default="")
    win_rate: Optional[float] = Field(default=None, ge=0.0, le=100.0, alias="_win_rate")
    realized_pnl: Optional[float] = Field(default=None, alias="_realized_pnl")

    model_config = {"populate_by_name": True}


class AgentProfilesMeta(BaseModel):
    """_meta 元信息"""
    created_at: str = Field(default="")
    version: str = Field(default="", pattern=r"^\d+\.\d+$")
    last_evolved_at: str = Field(default="")
    total_samples: int = Field(default=0, ge=0)
    note: str = Field(default="")

    model_config = {"populate_by_name": True}


class AgentProfilesData(BaseModel):
    """agent_profiles.json 顶层 — 用 model_validator 处理动态 key"""
    meta: AgentProfilesMeta = Field(default_factory=AgentProfilesMeta, alias="_meta")
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_meta(cls, data: Any) -> dict:
        if not isinstance(data, dict):
            return data
        meta = data.pop("_meta", {})
        result = {"meta": meta, "extra": data}
        # 校验风控明参数
        if "风控明" in data:
            RiskManagerProfile.model_validate(data["风控明"])
        # 校验辩手 confidence_boost
        if "辩手" in data:
            debaters = data["辩手"]
            for name in ("证真", "慎思"):
                if name in debaters:
                    DebaterSubProfile.model_validate(debaters[name])
        return result


def validate_data_sources(data: dict) -> DataSourcesConfig:
    """校验 data_sources.yaml 数据。"""
    return DataSourcesConfig.model_validate(data)


def safe_validate_data_sources(data: dict) -> tuple[Optional[DataSourcesConfig], Optional[str]]:
    try:
        return DataSourcesConfig.model_validate(data), None
    except Exception as e:
        return None, str(e)


def validate_agent_profiles(data: dict) -> AgentProfilesData:
    """校验 agent_profiles.json 数据。"""
    return AgentProfilesData.model_validate(data)


def safe_validate_agent_profiles(data: dict) -> tuple[Optional[AgentProfilesData], Optional[str]]:
    try:
        return AgentProfilesData.model_validate(data), None
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

    # FDC 已退役，data_sources.yaml 不再使用
    print("ℹ️ FDC 已退役，data_sources.yaml 跳过")

    # 测试 agent_profiles.json
    ap_path = ROOT / "memory" / "agent_profiles.json"
    if ap_path.exists():
        data = json.loads(ap_path.read_text(encoding="utf-8"))
        ap, err = safe_validate_agent_profiles(data)
        if ap:
            print(f"✅ agent_profiles.json 校验通过 (version={ap.meta.version})")
        else:
            print(f"❌ agent_profiles.json 校验失败: {err}")
    else:
        print("⚠️ agent_profiles.json 未找到")
