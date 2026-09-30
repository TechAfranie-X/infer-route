"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import FakeRedis


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        log_level="WARNING",
        redis_url="redis://localhost:6379/0",
        routing_strategy="round_robin",
        retry_base_delay_seconds=0,
        retry_jitter_seconds=0,
    )


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def client(settings: Settings, fake_redis: FakeRedis) -> Iterator[TestClient]:
    application = create_app(settings=settings, redis_client=fake_redis, providers=[])
    with TestClient(application) as test_client:
        yield test_client
