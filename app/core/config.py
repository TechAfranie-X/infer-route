"""Environment-driven application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment and an optional .env file.

    Later milestones extend this object with routing, cache, and provider settings.
    Only values the running process actually reads belong here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0)
    providers_config_path: str = "config/providers.json"
    http_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    http_read_timeout_seconds: float = Field(default=20.0, gt=0)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide settings object.

    Tests that change environment variables must call ``get_settings.cache_clear()``.
    """

    return Settings()
