"""Chat completions through the gateway with an in-process provider."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.providers.errors import NonRetryableProviderError, RetryableProviderError
from app.providers.mock_provider import MockProvider
from tests.fakes import FakeRedis


def _provider() -> MockProvider:
    config = ProviderConfig(
        id="provider-a",
        name="Provider A",
        base_url="http://mock",
        model="general",
    )
    return MockProvider(config, content="Distributed systems share work.")


@pytest.fixture
def gateway(settings: Settings) -> Iterator[tuple[TestClient, MockProvider]]:
    provider = _provider()
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    with TestClient(application) as client:
        yield client, provider


def test_completion_returns_the_mock_provider_response(
    gateway: tuple[TestClient, MockProvider],
) -> None:
    client, provider = gateway
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "general",
            "messages": [{"role": "user", "content": "Explain distributed systems simply."}],
            "temperature": 0.7,
            "max_tokens": 200,
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Distributed systems share work."
    assert body["provider"] == "provider-a"
    assert body["model"] == "general"
    assert body["cached"] is False
    assert body["attempts"] == 1
    assert body["id"].startswith("req_")
    assert response.headers["X-InferRoute-Provider"] == "provider-a"
    assert response.headers["X-InferRoute-Cache"] == "BYPASS"
    assert response.headers["X-InferRoute-Attempts"] == "1"
    assert provider.calls == 1


def test_unknown_message_role_is_rejected(gateway: tuple[TestClient, MockProvider]) -> None:
    client, provider = gateway
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "tool", "content": "nope"}]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert provider.calls == 0


def test_no_providers_returns_unavailable(settings: Settings) -> None:
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[])
    with TestClient(application) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "all_providers_unavailable"


def test_retryable_provider_failure_is_a_gateway_error(
    settings: Settings,
) -> None:
    provider = _provider()
    provider.error = RetryableProviderError(
        "provider returned HTTP 500",
        provider_id="provider-a",
        status_code=500,
    )
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    with TestClient(application) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert response.status_code == 503
    assert "500" not in response.text


def test_non_retryable_provider_failure_is_not_hidden(settings: Settings) -> None:
    provider = _provider()
    provider.error = NonRetryableProviderError(
        "provider returned HTTP 400",
        provider_id="provider-a",
        status_code=400,
    )
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    with TestClient(application) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
