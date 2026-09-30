"""Latency-aware candidate order."""

import pytest

from app.models.provider import ProviderConfig
from app.providers.mock_provider import MockProvider
from app.routing.health import HealthRegistry, HealthStatus, ProviderHealth
from app.routing.router import Router
from app.routing.strategies import LatencyAwareStrategy


def _provider(provider_id: str) -> MockProvider:
    return MockProvider(
        ProviderConfig(id=provider_id, name=provider_id, base_url="http://mock", model="general")
    )


def _health(
    *,
    status: HealthStatus = HealthStatus.HEALTHY,
    ewma: float = 100,
    failures: int = 0,
) -> ProviderHealth:
    return ProviderHealth(
        status=status,
        ewma_latency_ms=ewma,
        consecutive_failures=failures,
        has_latency_sample=True,
    )


@pytest.mark.asyncio
async def test_lower_latency_provider_is_preferred() -> None:
    providers = [_provider("provider-a"), _provider("provider-b")]
    health = {
        "provider-a": _health(ewma=400),
        "provider-b": _health(ewma=120),
    }
    ordered = await LatencyAwareStrategy().order(providers, health)
    assert ordered[0].config.id == "provider-b"


@pytest.mark.asyncio
async def test_degraded_provider_ranks_below_a_healthy_one() -> None:
    providers = [_provider("provider-a"), _provider("provider-b")]
    health = {
        "provider-a": _health(status=HealthStatus.DEGRADED, ewma=50),
        "provider-b": _health(status=HealthStatus.HEALTHY, ewma=200),
    }
    ordered = await LatencyAwareStrategy().order(providers, health)
    assert [provider.config.id for provider in ordered] == ["provider-b", "provider-a"]


@pytest.mark.asyncio
async def test_unhealthy_provider_is_excluded() -> None:
    providers = [_provider("provider-a"), _provider("provider-b")]
    health = {
        "provider-a": _health(status=HealthStatus.UNHEALTHY, ewma=10),
        "provider-b": _health(ewma=300),
    }
    ordered = await Router(LatencyAwareStrategy()).candidates(providers, health)
    assert [provider.config.id for provider in ordered] == ["provider-b"]


@pytest.mark.asyncio
async def test_recent_failures_add_a_penalty() -> None:
    providers = [_provider("provider-a"), _provider("provider-b")]
    health = {
        "provider-a": _health(ewma=100, failures=2),
        "provider-b": _health(ewma=150, failures=0),
    }
    ordered = await LatencyAwareStrategy().order(providers, health)
    assert ordered[0].config.id == "provider-b"


@pytest.mark.asyncio
async def test_gateway_skips_an_unhealthy_provider(settings) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.fakes import FakeRedis

    slow = _provider("provider-a")
    healthy = _provider("provider-b")
    healthy.content = "from-b"
    application = create_app(
        settings=settings.model_copy(update={"routing_strategy": "latency_aware"}),
        redis_client=FakeRedis(),
        providers=[slow, healthy],
    )
    with TestClient(application) as client:
        registry: HealthRegistry = application.state.health
        await registry.record_failure("provider-a")
        await registry.record_failure("provider-a")
        await registry.record_failure("provider-a")
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert response.status_code == 200
    assert response.json()["provider"] == "provider-b"
    assert slow.calls == 0
    assert healthy.calls == 1
