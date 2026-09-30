"""Settings loading."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

_SETTINGS_ENV_VARS = (
    "APP_ENV",
    "HOST",
    "PORT",
    "LOG_LEVEL",
    "REDIS_URL",
    "REDIS_SOCKET_TIMEOUT_SECONDS",
    "PROVIDERS_CONFIG_PATH",
    "HTTP_CONNECT_TIMEOUT_SECONDS",
    "HTTP_READ_TIMEOUT_SECONDS",
    "EWMA_ALPHA",
    "PROVIDER_FAILURE_THRESHOLD_DEGRADED",
    "PROVIDER_FAILURE_THRESHOLD_UNHEALTHY",
    "PROVIDER_COOLDOWN_SECONDS",
    "HEALTH_CHECK_INTERVAL_SECONDS",
    "ROUTING_STRATEGY",
    "RETRY_BASE_DELAY_SECONDS",
    "RETRY_JITTER_SECONDS",
    "INFERENCE_TIMEOUT_SECONDS",
    "CACHE_ENABLED",
    "CACHE_TTL_SECONDS",
)


@pytest.fixture
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_local_development(isolated_settings_env: None) -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.port == 8000
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.redis_socket_timeout_seconds == 2.0


def test_log_level_is_case_insensitive(isolated_settings_env: None) -> None:
    settings = Settings.model_validate({"log_level": "info"})
    assert settings.log_level == "INFO"


def test_redis_url_must_use_redis_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, redis_url="http://localhost:6379/0")


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("REDIS_URL", "rediss://cache.internal:6380/1")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.app_env == "production"
    assert settings.port == 9000
    assert settings.redis_url == "rediss://cache.internal:6380/1"
    get_settings.cache_clear()
