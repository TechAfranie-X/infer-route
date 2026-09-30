"""In-process provider for tests and local experiments.

Behavior is set on the instance so a test can force a timeout, an HTTP-style
failure, or a stream interruption without sleeping for a configured failure rate.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.models.provider import ProviderConfig
from app.models.requests import ChatCompletionRequest
from app.providers.base import GenerationResult, LLMProvider
from app.providers.errors import (
    ProviderCallError,
    RetryableProviderError,
    StreamInterruptedError,
)
from app.utils.timing import elapsed_ms, monotonic_ms


class MockProvider(LLMProvider):
    def __init__(
        self,
        config: ProviderConfig,
        *,
        content: str = "mock response",
        latency_ms: float = 0,
    ) -> None:
        super().__init__(config)
        self.content = content
        self.latency_ms = latency_ms
        self.error: ProviderCallError | None = None
        self.fail_times = 0
        self.stream_error_after: int | None = None
        self.calls = 0
        self.healthy = True
        self.last_request: ChatCompletionRequest | None = None

    async def generate(self, request: ChatCompletionRequest) -> GenerationResult:
        self.calls += 1
        self.last_request = request
        started = monotonic_ms()
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RetryableProviderError(
                "temporary provider failure",
                provider_id=self.config.id,
                status_code=500,
            )
        if self.error is not None:
            raise self.error
        return GenerationResult(
            content=self.content,
            provider_id=self.config.id,
            latency_ms=elapsed_ms(started),
        )

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[str]:
        self.calls += 1
        self.last_request = request
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)
        if self.error is not None and self.stream_error_after is None:
            raise self.error
        tokens = _tokens(self.content)
        for index, token in enumerate(tokens):
            if self.stream_error_after is not None and index >= self.stream_error_after:
                raise StreamInterruptedError(
                    "mock stream interrupted",
                    provider_id=self.config.id,
                    tokens_sent=index,
                )
            yield token

    async def healthcheck(self) -> bool:
        return self.healthy


def _tokens(content: str) -> list[str]:
    if not content:
        return []
    parts = content.split(" ")
    tokens: list[str] = []
    for index, part in enumerate(parts):
        tokens.append(part if index == len(parts) - 1 else f"{part} ")
    return tokens
