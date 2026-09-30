"""Inference orchestration.

The router orders providers. This service applies a per-provider timeout, a
bounded local retry, then fallback to the next candidate. A non-retryable
provider error stops the loop: another endpoint cannot fix a bad request.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.core.exceptions import (
    AllProvidersUnavailableError,
    InvalidRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.models.requests import ChatCompletionRequest
from app.models.responses import ChatCompletionResponse
from app.providers.base import GenerationResult, LLMProvider
from app.providers.errors import NonRetryableProviderError, RetryableProviderError
from app.providers.registry import ProviderRegistry
from app.routing.health import HealthRegistry
from app.routing.router import Router
from app.services.backoff import backoff_seconds
from app.services.cache import CacheHeader, ResponseCache
from app.utils.timing import elapsed_ms, monotonic_ms

logger = logging.getLogger("inferroute.inference")


class InferenceService:
    def __init__(
        self,
        registry: ProviderRegistry,
        router: Router,
        health: HealthRegistry,
        settings: Settings,
        cache: ResponseCache,
    ) -> None:
        self._registry = registry
        self._router = router
        self._health = health
        self._settings = settings
        self._cache = cache

    async def complete(
        self,
        request: ChatCompletionRequest,
        request_id: str,
    ) -> ChatCompletionResponse:
        if request.stream:
            raise InvalidRequestError(
                "Streaming is not available on this gateway build.",
                request_id=request_id,
            )

        started = monotonic_ms()
        lookup = await self._cache.lookup(request)
        if lookup.header == "HIT" and lookup.entry is not None:
            latency_ms = round(elapsed_ms(started), 2)
            logger.info(
                "cache hit",
                extra={"event": "cache_hit", "request_id": request_id, "latency_ms": latency_ms},
            )
            return ChatCompletionResponse(
                id=request_id,
                model=request.model,
                provider=lookup.entry.provider,
                cached=True,
                attempts=1,
                latency_ms=latency_ms,
                cache_status="HIT",
                content=lookup.entry.content,
            )

        health = await self._health.snapshots()
        candidates = await self._router.candidates(self._registry.enabled(), health)
        if not candidates:
            raise AllProvidersUnavailableError(
                "No model endpoint could successfully complete the request.",
                request_id=request_id,
            )

        initial_provider = candidates[0].config.id
        attempts = 0
        saw_timeout = False
        saw_other_retryable = False

        for index, provider in enumerate(candidates):
            if index > 0:
                logger.warning(
                    "fallback started",
                    extra={
                        "event": "fallback_started",
                        "request_id": request_id,
                        "provider": provider.config.id,
                        "initial_provider": initial_provider,
                    },
                )
            logger.info(
                "provider selected",
                extra={
                    "event": "provider_selected",
                    "request_id": request_id,
                    "provider": provider.config.id,
                    "routing_strategy": self._router.strategy_name,
                },
            )
            local_try = 0
            while True:
                if self._over_budget(started):
                    break
                attempts += 1
                try:
                    generation = await asyncio.wait_for(
                        provider.generate(request),
                        timeout=provider.config.timeout_seconds,
                    )
                except NonRetryableProviderError as exc:
                    self._raise_non_retryable(exc, request_id)
                except (TimeoutError, RetryableProviderError) as exc:
                    timeout = _is_timeout(exc)
                    saw_timeout = saw_timeout or timeout
                    saw_other_retryable = saw_other_retryable or not timeout
                    await self._health.record_failure(provider.config.id)
                    logger.warning(
                        "provider failure",
                        extra={
                            "event": "provider_failure",
                            "request_id": request_id,
                            "provider": provider.config.id,
                            "status_code": getattr(exc, "status_code", None),
                            "attempt": attempts,
                        },
                    )
                    if local_try < provider.config.max_retries and not self._over_budget(started):
                        local_try += 1
                        logger.info(
                            "provider retry",
                            extra={
                                "event": "provider_retry",
                                "request_id": request_id,
                                "provider": provider.config.id,
                                "retry": local_try,
                            },
                        )
                        await self._pause(local_try)
                        continue
                    break
                else:
                    await self._health.record_success(provider.config.id, generation.latency_ms)
                    response = self._success(
                        request,
                        request_id,
                        generation,
                        provider,
                        attempts=attempts,
                        started=started,
                        initial_provider=initial_provider,
                        cache_status=lookup.header,
                    )
                    await self._cache.store(
                        request,
                        provider=provider.config.id,
                        content=generation.content,
                    )
                    return response
            if self._over_budget(started):
                break

        if saw_timeout and not saw_other_retryable:
            raise ProviderTimeoutError(
                "The model endpoint timed out.",
                request_id=request_id,
            )
        raise AllProvidersUnavailableError(
            "No model endpoint could successfully complete the request.",
            request_id=request_id,
        )

    def _success(
        self,
        request: ChatCompletionRequest,
        request_id: str,
        generation: GenerationResult,
        provider: LLMProvider,
        *,
        attempts: int,
        started: float,
        initial_provider: str,
        cache_status: CacheHeader,
    ) -> ChatCompletionResponse:
        latency_ms = round(elapsed_ms(started), 2)
        fallback_used = provider.config.id != initial_provider
        logger.info(
            "inference completed",
            extra={
                "event": "inference_completed",
                "request_id": request_id,
                "provider": provider.config.id,
                "initial_provider": initial_provider,
                "attempts": attempts,
                "fallback_used": fallback_used,
                "latency_ms": latency_ms,
            },
        )
        return ChatCompletionResponse(
            id=request_id,
            model=request.model,
            provider=provider.config.id,
            cached=False,
            attempts=attempts,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            cache_status=cache_status,
            content=generation.content,
        )

    def _over_budget(self, started: float) -> bool:
        limit_ms = self._settings.inference_timeout_seconds * 1000
        return elapsed_ms(started) >= limit_ms

    async def _pause(self, retry_number: int) -> None:
        delay = backoff_seconds(
            retry_number,
            base_seconds=self._settings.retry_base_delay_seconds,
            jitter_seconds=self._settings.retry_jitter_seconds,
        )
        if delay > 0:
            await asyncio.sleep(delay)

    def _raise_non_retryable(self, exc: NonRetryableProviderError, request_id: str) -> None:
        logger.warning(
            "provider rejected request",
            extra={
                "event": "provider_failure",
                "request_id": request_id,
                "provider": exc.provider_id,
                "status_code": exc.status_code,
                "retryable": False,
            },
        )
        if exc.status_code in {400, 422}:
            raise InvalidRequestError(
                "The model endpoint rejected the request.",
                request_id=request_id,
            ) from exc
        raise ProviderResponseError(
            "The model endpoint rejected the request.",
            request_id=request_id,
        ) from exc


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = getattr(exc, "message", "")
    return isinstance(message, str) and "timed out" in message
