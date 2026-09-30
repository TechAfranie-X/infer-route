"""Provider health transitions and EWMA."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.models.provider import ProviderConfig
from app.providers.mock_provider import MockProvider
from app.routing.health import HealthChecker, HealthRegistry, HealthStatus


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


def _provider() -> MockProvider:
    return MockProvider(
        ProviderConfig(id="provider-a", name="A", base_url="http://mock", model="general")
    )


@pytest.mark.asyncio
async def test_ewma_weights_the_latest_sample_more_than_history() -> None:
    registry = HealthRegistry(_settings())
    await registry.record_success("provider-a", 100)
    state = await registry.record_success("provider-a", 200)
    assert state.ewma_latency_ms == pytest.approx(120)
    assert state.last_latency_ms == 200


@pytest.mark.asyncio
async def test_success_resets_consecutive_failures() -> None:
    registry = HealthRegistry(_settings())
    await registry.record_failure("provider-a")
    await registry.record_failure("provider-a")
    state = await registry.record_success("provider-a", 50)
    assert state.consecutive_failures == 0
    assert state.status is HealthStatus.HEALTHY
    assert state.cooldown_until is None


@pytest.mark.asyncio
async def test_failure_thresholds_move_from_degraded_to_unhealthy() -> None:
    registry = HealthRegistry(_settings())
    now = datetime(2026, 1, 1, tzinfo=UTC)
    once = await registry.record_failure("provider-a", now=now)
    degraded = await registry.record_failure("provider-a", now=now)
    unhealthy = await registry.record_failure("provider-a", now=now)
    assert once.status is HealthStatus.HEALTHY
    assert degraded.status is HealthStatus.DEGRADED
    assert unhealthy.status is HealthStatus.UNHEALTHY
    assert unhealthy.consecutive_failures == 3
    assert unhealthy.total_failures == 3
    assert unhealthy.cooldown_until == now + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_probe_waits_for_cooldown_then_restores_the_provider() -> None:
    settings = _settings()
    registry = HealthRegistry(settings)
    provider = _provider()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(3):
        await registry.record_failure(provider.config.id, now=now)
    checker = HealthChecker(registry, [provider], settings)

    await checker.probe_due(now=now + timedelta(seconds=1))
    during_cooldown = await registry.snapshot(provider.config.id)
    assert during_cooldown.status is HealthStatus.UNHEALTHY

    provider.healthy = True
    await checker.probe_due(now=now + timedelta(seconds=31))
    restored = await registry.snapshot(provider.config.id)
    assert restored.status is HealthStatus.HEALTHY
    assert restored.consecutive_failures == 0
    assert restored.ewma_latency_ms == 0
