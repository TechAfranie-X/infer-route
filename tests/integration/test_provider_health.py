"""Health observed through the gateway after real inference calls."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.providers.errors import RetryableProviderError
from app.providers.mock_provider import MockProvider
from tests.fakes import FakeRedis


def test_repeated_failures_are_visible_on_the_health_endpoint(settings: Settings) -> None:
    provider = MockProvider(
        ProviderConfig(id="provider-a", name="A", base_url="http://mock", model="general"),
        content="ok",
        latency_ms=0,
    )
    provider.error = RetryableProviderError(
        "provider returned HTTP 500",
        provider_id="provider-a",
        status_code=500,
    )
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    with TestClient(application) as client:
        for _ in range(3):
            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 503
        health = client.get("/health/providers")
    assert health.status_code == 200
    body = health.json()["providers"]
    assert body[0]["id"] == "provider-a"
    assert body[0]["status"] == "unhealthy"
    assert body[0]["consecutive_failures"] == 3
    assert body[0]["cooldown_until"] is not None


def test_a_success_after_failures_returns_the_provider_to_healthy(settings: Settings) -> None:
    provider = MockProvider(
        ProviderConfig(id="provider-a", name="A", base_url="http://mock", model="general"),
        content="ok",
    )
    provider.error = RetryableProviderError("down", provider_id="provider-a", status_code=500)
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    with TestClient(application) as client:
        client.post("/v1/chat/completions", json=payload)
        client.post("/v1/chat/completions", json=payload)
        provider.error = None
        ok = client.post("/v1/chat/completions", json=payload)
        health = client.get("/health/providers").json()["providers"][0]
    assert ok.status_code == 200
    assert health["status"] == "healthy"
    assert health["consecutive_failures"] == 0
    assert health["ewma_latency_ms"] >= 0
