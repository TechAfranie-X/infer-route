"""Prometheus metrics move when traffic passes through the gateway."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.providers.errors import RetryableProviderError
from app.providers.mock_provider import MockProvider
from tests.fakes import FakeRedis


def _provider(provider_id: str, content: str = "ok") -> MockProvider:
    return MockProvider(
        ProviderConfig(
            id=provider_id,
            name=provider_id,
            base_url="http://mock",
            model="general",
            max_retries=0,
        ),
        content=content,
    )


def test_metrics_count_requests_cache_and_fallback(settings: Settings) -> None:
    failing = _provider("provider-a")
    failing.error = RetryableProviderError("down", provider_id="provider-a", status_code=500)
    healthy = _provider("provider-b", content="from-b")
    application = create_app(
        settings=settings,
        redis_client=FakeRedis(),
        providers=[failing, healthy],
    )
    deterministic = {
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0,
        "max_tokens": 32,
    }
    with TestClient(application) as client:
        first = client.post("/v1/chat/completions", json=deterministic)
        second = client.post("/v1/chat/completions", json=deterministic)
        body = client.get("/metrics").text
    assert first.headers["X-InferRoute-Cache"] == "MISS"
    assert first.json()["fallback_used"] is True
    assert second.headers["X-InferRoute-Cache"] == "HIT"
    assert "inferroute_requests_total" in body
    assert 'strategy="round_robin"' in body
    assert "inferroute_cache_misses_total" in body
    assert "inferroute_cache_hits_total" in body
    assert "inferroute_fallbacks_total" in body
    assert "inferroute_provider_errors_total" in body
    assert "inferroute_request_duration_seconds" in body
