"""Retry and fallback across providers."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.providers.errors import NonRetryableProviderError, RetryableProviderError
from app.providers.mock_provider import MockProvider
from tests.fakes import FakeRedis

_PAYLOAD = {"messages": [{"role": "user", "content": "Hello"}]}


def _provider(
    provider_id: str,
    *,
    content: str = "ok",
    timeout: float = 2,
    retries: int = 0,
) -> MockProvider:
    return MockProvider(
        ProviderConfig(
            id=provider_id,
            name=provider_id,
            base_url="http://mock",
            model="general",
            timeout_seconds=timeout,
            max_retries=retries,
        ),
        content=content,
    )


def _client(settings: Settings, providers: list[MockProvider]) -> TestClient:
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=providers)
    return TestClient(application)


def test_retryable_failure_falls_back_to_the_next_provider(settings: Settings) -> None:
    failing = _provider("provider-a")
    failing.error = RetryableProviderError("down", provider_id="provider-a", status_code=500)
    healthy = _provider("provider-b", content="from-b")
    with _client(settings, [failing, healthy]) as client:
        response = client.post("/v1/chat/completions", json=_PAYLOAD)
    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "provider-b"
    assert body["fallback_used"] is True
    assert body["attempts"] == 2
    assert body["content"] == "from-b"
    assert response.headers["X-InferRoute-Fallback"] == "true"
    assert failing.calls == 1
    assert healthy.calls == 1


def test_local_retry_stays_on_the_same_provider(settings: Settings) -> None:
    flaky = _provider("provider-a", content="recovered", retries=1)
    flaky.fail_times = 1
    with _client(settings, [flaky]) as client:
        response = client.post("/v1/chat/completions", json=_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["provider"] == "provider-a"
    assert response.json()["attempts"] == 2
    assert response.json()["fallback_used"] is False
    assert flaky.calls == 2


def test_non_retryable_failure_does_not_try_another_provider(settings: Settings) -> None:
    rejected = _provider("provider-a", retries=1)
    rejected.error = NonRetryableProviderError(
        "bad request",
        provider_id="provider-a",
        status_code=400,
    )
    other = _provider("provider-b")
    with _client(settings, [rejected, other]) as client:
        response = client.post("/v1/chat/completions", json=_PAYLOAD)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert rejected.calls == 1
    assert other.calls == 0


def test_timeout_falls_back_to_a_healthy_provider(settings: Settings) -> None:
    slow = _provider("provider-a", timeout=0.05)
    slow.latency_ms = 500
    healthy = _provider("provider-b", content="fast")
    with _client(settings, [slow, healthy]) as client:
        response = client.post("/v1/chat/completions", json=_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["provider"] == "provider-b"
    assert response.json()["fallback_used"] is True
    assert slow.calls == 1
    assert healthy.calls == 1
