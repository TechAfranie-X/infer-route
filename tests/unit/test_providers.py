"""Provider implementations."""

import httpx
import pytest

from app.mock.server import create_mock_app
from app.mock.settings import MockSettings
from app.models.provider import ProviderConfig
from app.models.requests import ChatCompletionRequest, ChatMessage
from app.providers.errors import RetryableProviderError
from app.providers.http_provider import HTTPProvider, token_from_sse_line
from app.providers.mock_provider import MockProvider


def _config() -> ProviderConfig:
    return ProviderConfig(
        id="provider-a",
        name="Provider A",
        base_url="http://mock",
        model="general",
        timeout_seconds=2,
    )


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="Explain distributed systems simply.")],
    )


@pytest.mark.asyncio
async def test_mock_provider_returns_configured_content() -> None:
    provider = MockProvider(_config(), content="hello from mock")
    result = await provider.generate(_request())
    assert result.content == "hello from mock"
    assert result.provider_id == "provider-a"
    assert provider.calls == 1
    assert await provider.healthcheck() is True


@pytest.mark.asyncio
async def test_mock_provider_raises_injected_error() -> None:
    provider = MockProvider(_config())
    provider.error = RetryableProviderError(
        "provider returned HTTP 500",
        provider_id="provider-a",
        status_code=500,
    )
    with pytest.raises(RetryableProviderError):
        await provider.generate(_request())


def test_sse_line_parser_reads_openai_deltas() -> None:
    line = 'data: {"choices":[{"delta":{"content":"Distributed"}}]}'
    assert token_from_sse_line(line) == "Distributed"
    assert token_from_sse_line("data: [DONE]") is None


@pytest.mark.asyncio
async def test_http_provider_completes_against_mock_server() -> None:
    mock = create_mock_app(
        MockSettings(
            _env_file=None,
            mock_provider_id="provider-a",
            mock_latency_ms=0,
            mock_failure_rate=0,
        )
    )
    transport = httpx.ASGITransport(app=mock)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        provider = HTTPProvider(_config(), client, connect_timeout_seconds=1)
        result = await provider.generate(_request())
        assert result.content.startswith("[provider-a]")
        assert await provider.healthcheck() is True

        await client.post("http://mock/mock/mode", json={"mode": "failing"})
        with pytest.raises(RetryableProviderError) as exc_info:
            await provider.generate(_request())
        assert exc_info.value.status_code == 500
