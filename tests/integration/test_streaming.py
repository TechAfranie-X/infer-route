"""Token streaming, TTFT, and fallback boundaries."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.provider import ProviderConfig
from app.models.requests import ChatCompletionRequest, ChatMessage
from app.providers.errors import RetryableProviderError
from app.providers.mock_provider import MockProvider
from app.services.inference import InferenceService
from tests.fakes import FakeRedis


def _provider(provider_id: str, content: str = "alpha beta") -> MockProvider:
    return MockProvider(
        ProviderConfig(
            id=provider_id,
            name=provider_id,
            base_url="http://mock",
            model="general",
            timeout_seconds=2,
            max_retries=0,
        ),
        content=content,
    )


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
        temperature=0,
    )


@pytest.mark.asyncio
async def test_first_token_is_available_before_the_stream_finishes(settings: Settings) -> None:
    provider = _provider("provider-a", content="first second")

    class Gated(MockProvider):
        def __init__(self) -> None:
            super().__init__(provider.config, content="ignored")
            self.release = asyncio.Event()
            self.reached_second = False

        async def stream(self, request: ChatCompletionRequest):
            self.calls += 1
            yield "first"
            self.reached_second = True
            await self.release.wait()
            yield " second"

    gated = Gated()
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[gated])
    async with application.router.lifespan_context(application):
        service: InferenceService = application.state.inference_service
        meta, first, rest = await service.open_stream(_request(), "req_streamtest01")
        assert first == "first"
        assert gated.reached_second is False
        assert meta.ttft_ms >= 0
        gated.release.set()
        body = b"".join([chunk async for chunk in rest])
    assert b"second" in body
    assert b"data: [DONE]" in body


@pytest.mark.asyncio
async def test_ttft_includes_provider_delay(settings: Settings) -> None:
    provider = _provider("provider-a", content="token")
    provider.latency_ms = 40
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    async with application.router.lifespan_context(application):
        service: InferenceService = application.state.inference_service
        meta, first, rest = await service.open_stream(_request(), "req_streamtest02")
        assert first == "token"
        assert meta.ttft_ms >= 30
        body = b"".join([chunk async for chunk in rest])
    assert b"[DONE]" in body


@pytest.mark.asyncio
async def test_pre_token_failure_falls_back(settings: Settings) -> None:
    failing = _provider("provider-a")
    failing.error = RetryableProviderError("down", provider_id="provider-a", status_code=500)
    healthy = _provider("provider-b", content="beta")
    application = create_app(
        settings=settings,
        redis_client=FakeRedis(),
        providers=[failing, healthy],
    )
    async with application.router.lifespan_context(application):
        service: InferenceService = application.state.inference_service
        meta, first, rest = await service.open_stream(_request(), "req_streamtest03")
        await rest.aclose()
    assert first == "beta"
    assert meta.provider == "provider-b"
    assert meta.fallback_used is True
    assert meta.attempts == 2
    assert failing.calls == 1
    assert healthy.calls == 1


@pytest.mark.asyncio
async def test_post_token_failure_is_not_replayed(settings: Settings) -> None:
    failing = _provider("provider-a", content="alpha beta")
    failing.stream_error_after = 1
    other = _provider("provider-b", content="should-not-run")
    application = create_app(
        settings=settings,
        redis_client=FakeRedis(),
        providers=[failing, other],
    )
    async with application.router.lifespan_context(application):
        service: InferenceService = application.state.inference_service
        meta, first, rest = await service.open_stream(_request(), "req_streamtest04")
        body = b"".join([chunk async for chunk in rest])
    assert first == "alpha "
    assert meta.provider == "provider-a"
    assert b"stream_interrupted" in body
    assert b"[DONE]" not in body
    assert other.calls == 0


def test_http_stream_is_sse(settings: Settings) -> None:
    provider = _provider("provider-a", content="Distributed systems")
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
        "temperature": 0,
    }
    with TestClient(application) as client:
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-inferroute-provider"] == "provider-a"
    assert "x-inferroute-ttft-ms" in response.headers
    text = response.text
    assert text.startswith("data: ")
    assert '"token":"Distributed "' in text or '"token":"Distributed"' in text
    assert "data: [DONE]" in text


@pytest.mark.asyncio
async def test_closing_the_stream_releases_the_provider(settings: Settings) -> None:
    provider = _provider("provider-a", content="alpha beta gamma")
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[provider])
    async with application.router.lifespan_context(application):
        service: InferenceService = application.state.inference_service
        _meta, _first, rest = await service.open_stream(_request(), "req_streamtest05")
        await rest.aclose()
    assert provider.calls == 1
