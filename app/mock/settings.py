"""Environment for one simulated model endpoint."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MockMode = Literal["healthy", "slow", "failing", "offline"]


class MockSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mock_provider_id: str = "provider-a"
    mock_latency_ms: int = Field(default=150, ge=0)
    mock_failure_rate: float = Field(default=0.0, ge=0, le=1)
    mock_slow_latency_ms: int = Field(default=2000, ge=0)
    mock_offline_delay_seconds: float = Field(default=30.0, ge=0)
    mock_mode: MockMode = "healthy"
    host: str = "0.0.0.0"
    mock_port: int = Field(default=8081, ge=1, le=65535)
