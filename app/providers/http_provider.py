"""HTTP provider for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.models.provider import ProviderConfig
from app.models.requests import ChatCompletionRequest
from app.providers.base import GenerationResult, LLMProvider
from app.providers.errors import (
    NonRetryableProviderError,
    RetryableProviderError,
    StreamInterruptedError,
)
from app.utils.timing import elapsed_ms, monotonic_ms

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class HTTPProvider(LLMProvider):
    def __init__(
        self,
        config: ProviderConfig,
        client: httpx.AsyncClient,
        *,
        connect_timeout_seconds: float,
    ) -> None:
        super().__init__(config)
        self._client = client
        self._connect_timeout_seconds = connect_timeout_seconds

    async def generate(self, request: ChatCompletionRequest) -> GenerationResult:
        started = monotonic_ms()
        try:
            response = await self._client.post(
                self._completions_url(),
                json=self._payload(request, stream=False),
                timeout=self._timeout(),
            )
        except httpx.TimeoutException as exc:
            raise RetryableProviderError(
                "provider timed out",
                provider_id=self.config.id,
            ) from exc
        except httpx.RequestError as exc:
            raise RetryableProviderError(
                "provider connection failed",
                provider_id=self.config.id,
            ) from exc
        self._raise_for_status(response)
        content = _content_from_body(response.json(), self.config.id)
        return GenerationResult(
            content=content,
            provider_id=self.config.id,
            latency_ms=elapsed_ms(started),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[str]:
        tokens_sent = 0
        try:
            async with self._client.stream(
                "POST",
                self._completions_url(),
                json=self._payload(request, stream=True),
                timeout=self._timeout(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status_code(response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    token = token_from_sse_line(line)
                    if token is None:
                        continue
                    tokens_sent += 1
                    yield token
        except httpx.TimeoutException as exc:
            raise StreamInterruptedError(
                "provider stream timed out",
                provider_id=self.config.id,
                tokens_sent=tokens_sent,
            ) from exc
        except httpx.RequestError as exc:
            raise StreamInterruptedError(
                "provider stream failed",
                provider_id=self.config.id,
                tokens_sent=tokens_sent,
            ) from exc

    async def healthcheck(self) -> bool:
        try:
            response = await self._client.get(
                f"{self.config.base_url.rstrip('/')}/health",
                timeout=httpx.Timeout(self._connect_timeout_seconds),
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _completions_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/v1/chat/completions"

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._connect_timeout_seconds,
            read=self.config.timeout_seconds,
            write=self._connect_timeout_seconds,
            pool=self._connect_timeout_seconds,
        )

    def _payload(self, request: ChatCompletionRequest, *, stream: bool) -> dict[str, object]:
        return {
            "model": self.config.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        self._raise_for_status_code(response.status_code)

    def _raise_for_status_code(self, status_code: int) -> None:
        message = f"provider returned HTTP {status_code}"
        if status_code in RETRYABLE_STATUS_CODES:
            raise RetryableProviderError(
                message,
                provider_id=self.config.id,
                status_code=status_code,
            )
        raise NonRetryableProviderError(
            message,
            provider_id=self.config.id,
            status_code=status_code,
        )


def token_from_sse_line(line: str) -> str | None:
    """Extract one text chunk from an OpenAI-style or gateway SSE line."""

    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    if isinstance(token, str) and token:
        return token
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    delta = choice.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        content = delta["content"]
        return content or None
    return None


def _content_from_body(payload: object, provider_id: str) -> str:
    if not isinstance(payload, dict):
        raise RetryableProviderError("provider returned a malformed body", provider_id=provider_id)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RetryableProviderError("provider returned no choices", provider_id=provider_id)
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise RetryableProviderError(
            "provider returned no message content",
            provider_id=provider_id,
        )
    return message["content"]
