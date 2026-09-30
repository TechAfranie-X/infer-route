"""Response cache behavior through the chat endpoint."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.providers.mock_provider import MockProvider
from tests.fakes import FakeRedis

_DETERMINISTIC = {
    "model": "general",
    "messages": [{"role": "user", "content": "Explain distributed systems simply."}],
    "temperature": 0,
    "max_tokens": 200,
}


def _app(settings: Settings, redis: FakeRedis, provider: MockProvider) -> TestClient:
    application = create_app(settings=settings, redis_client=redis, providers=[provider])
    return TestClient(application)


def _provider() -> MockProvider:
    return MockProvider(
        ProviderConfig(id="provider-a", name="A", base_url="http://mock", model="general"),
        content="cached-body",
    )


def test_second_deterministic_request_is_a_cache_hit(settings: Settings) -> None:
    redis = FakeRedis()
    provider = _provider()
    with _app(settings, redis, provider) as client:
        first = client.post("/v1/chat/completions", json=_DETERMINISTIC)
        second = client.post("/v1/chat/completions", json=_DETERMINISTIC)
    assert first.status_code == 200
    assert first.headers["X-InferRoute-Cache"] == "MISS"
    assert first.json()["cached"] is False
    assert second.headers["X-InferRoute-Cache"] == "HIT"
    assert second.json()["cached"] is True
    assert second.json()["content"] == "cached-body"
    assert second.json()["provider"] == "provider-a"
    assert provider.calls == 1
    assert second.json()["latency_ms"] <= first.json()["latency_ms"] + 50


def test_positive_temperature_bypasses_the_cache(settings: Settings) -> None:
    provider = _provider()
    payload = {**_DETERMINISTIC, "temperature": 0.7}
    with _app(settings, FakeRedis(), provider) as client:
        first = client.post("/v1/chat/completions", json=payload)
        second = client.post("/v1/chat/completions", json=payload)
    assert first.headers["X-InferRoute-Cache"] == "BYPASS"
    assert second.headers["X-InferRoute-Cache"] == "BYPASS"
    assert provider.calls == 2


def test_redis_errors_do_not_fail_inference(settings: Settings) -> None:
    redis = FakeRedis()
    redis.fail_commands = True
    provider = _provider()
    with _app(settings, redis, provider) as client:
        response = client.post("/v1/chat/completions", json=_DETERMINISTIC)
    assert response.status_code == 200
    assert response.json()["content"] == "cached-body"
    assert response.headers["X-InferRoute-Cache"] == "MISS"
    assert provider.calls == 1
