"""Inference orchestration.

The router orders providers. This service applies a per-provider timeout, a
bounded local retry, then fallback to the next candidate. A non-retryable
provider error stops the loop: another endpoint cannot fix a bad request.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

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
from app.services.metrics import MetricsService
from app.services.sse import sse_done, sse_error, sse_token
from app.utils.timing import elapsed_ms, monotonic_ms

logger = logging.getLogger("inferroute.inference")

_STREAM_INTERRUPTED = "The model stream ended before completion."


@dataclass
class StreamMeta:
    provider: str
    ttft_ms: float
    attempts: int
    fallback_used: bool
    cache_status: CacheHeader
    initial_provider: str


class InferenceService:
    def __init__(
        self,
        registry: ProviderRegistry,
        router: Router,
        health: HealthRegistry,
        settings: Settings,
        cache: ResponseCache,
        metrics: MetricsService,
    ) -> None:
        self._registry = registry
        self._router = router
        self._health = health
        self._settings = settings
        self._cache = cache
        self._metrics = metrics

    async def complete(
        self,
        request: ChatCompletionRequest,
        request_id: str,
    ) -> ChatCompletionResponse:
        if request.stream:
            raise InvalidRequestError(
                "Streaming responses are returned by the stream API.",
                request_id=request_id,
            )

        started = monotonic_ms()
        lookup = await self._cache.lookup(request)
        self._record_cache(lookup.header)
        if lookup.header == "HIT" and lookup.entry is not None:
            latency_ms = round(elapsed_ms(started), 2)
            logger.info(
                "cache hit",
                extra={"event": "cache_hit", "request_id": request_id, "latency_ms": latency_ms},
            )
            self._record_request(
                status="success",
                provider=lookup.entry.provider,
                latency_ms=latency_ms,
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
                self._metrics.fallbacks.labels(provider=provider.config.id).inc()
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
                    self._metrics.provider_errors.labels(provider=provider.config.id).inc()
                    self._metrics.provider_requests.labels(
                        provider=provider.config.id,
                        status="error",
                    ).inc()
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
                        self._metrics.retries.labels(provider=provider.config.id).inc()
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
                    self._metrics.provider_requests.labels(
                        provider=provider.config.id,
                        status="success",
                    ).inc()
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

        latency_ms = elapsed_ms(started)
        if saw_timeout and not saw_other_retryable:
            self._record_request(
                status="error",
                provider=initial_provider,
                latency_ms=latency_ms,
            )
            raise ProviderTimeoutError(
                "The model endpoint timed out.",
                request_id=request_id,
            )
        self._record_request(status="error", provider=initial_provider, latency_ms=latency_ms)
        raise AllProvidersUnavailableError(
            "No model endpoint could successfully complete the request.",
            request_id=request_id,
        )

    async def open_stream(
        self,
        request: ChatCompletionRequest,
        request_id: str,
    ) -> tuple[StreamMeta, str, AsyncIterator[bytes]]:
        """Return the first token and an iterator for the rest.

        Fallback is allowed only until that first token. After the caller has
        the first token, a later provider failure is reported on the stream and
        is not replayed from another endpoint.
        """

        started = monotonic_ms()
        lookup = await self._cache.lookup(request)
        self._record_cache(lookup.header)
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
                self._metrics.fallbacks.labels(provider=provider.config.id).inc()
                logger.warning(
                    "fallback started",
                    extra={
                        "event": "fallback_started",
                        "request_id": request_id,
                        "provider": provider.config.id,
                        "initial_provider": initial_provider,
                    },
                )
            local_try = 0
            while True:
                if self._over_budget(started):
                    break
                attempts += 1
                iterator = provider.stream(request)
                try:
                    first_token = await asyncio.wait_for(
                        anext(iterator),
                        timeout=provider.config.timeout_seconds,
                    )
                except StopAsyncIteration:
                    await _close_iterator(iterator)
                    saw_other_retryable = True
                    await self._health.record_failure(provider.config.id)
                    break
                except NonRetryableProviderError as exc:
                    await _close_iterator(iterator)
                    self._raise_non_retryable(exc, request_id)
                except (TimeoutError, RetryableProviderError) as exc:
                    await _close_iterator(iterator)
                    timeout = _is_timeout(exc)
                    saw_timeout = saw_timeout or timeout
                    saw_other_retryable = saw_other_retryable or not timeout
                    await self._health.record_failure(provider.config.id)
                    self._metrics.provider_errors.labels(provider=provider.config.id).inc()
                    self._metrics.provider_requests.labels(
                        provider=provider.config.id,
                        status="error",
                    ).inc()
                    logger.warning(
                        "provider failure",
                        extra={
                            "event": "provider_failure",
                            "request_id": request_id,
                            "provider": provider.config.id,
                            "attempt": attempts,
                        },
                    )
                    if local_try < provider.config.max_retries and not self._over_budget(started):
                        local_try += 1
                        self._metrics.retries.labels(provider=provider.config.id).inc()
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
                    ttft_ms = round(elapsed_ms(started), 2)
                    meta = StreamMeta(
                        provider=provider.config.id,
                        ttft_ms=ttft_ms,
                        attempts=attempts,
                        fallback_used=provider.config.id != initial_provider,
                        cache_status=lookup.header,
                        initial_provider=initial_provider,
                    )
                    self._metrics.ttft.labels(provider=provider.config.id).observe(ttft_ms / 1000)
                    self._metrics.provider_requests.labels(
                        provider=provider.config.id,
                        status="success",
                    ).inc()
                    logger.info(
                        "stream started",
                        extra={
                            "event": "stream_started",
                            "request_id": request_id,
                            "provider": provider.config.id,
                            "ttft_ms": ttft_ms,
                            "attempts": attempts,
                            "fallback_used": meta.fallback_used,
                        },
                    )
                    rest = self._remaining_stream(
                        iterator,
                        provider_id=provider.config.id,
                        request_id=request_id,
                        ttft_ms=ttft_ms,
                    )
                    return meta, first_token, rest
            if self._over_budget(started):
                break

        latency_ms = elapsed_ms(started)
        if saw_timeout and not saw_other_retryable:
            self._record_request(status="error", provider=initial_provider, latency_ms=latency_ms)
            raise ProviderTimeoutError("The model endpoint timed out.", request_id=request_id)
        self._record_request(status="error", provider=initial_provider, latency_ms=latency_ms)
        raise AllProvidersUnavailableError(
            "No model endpoint could successfully complete the request.",
            request_id=request_id,
        )

    async def _remaining_stream(
        self,
        iterator: AsyncIterator[str],
        *,
        provider_id: str,
        request_id: str,
        ttft_ms: float,
    ) -> AsyncIterator[bytes]:
        started = monotonic_ms()
        chunks = 1
        try:
            async for token in iterator:
                chunks += 1
                yield sse_token(token)
        except (TimeoutError, RetryableProviderError) as exc:
            await self._health.record_failure(provider_id)
            self._metrics.provider_errors.labels(provider=provider_id).inc()
            self._record_request(status="error", provider=provider_id, latency_ms=ttft_ms)
            logger.warning(
                "stream failed",
                extra={
                    "event": "stream_failed",
                    "request_id": request_id,
                    "provider": provider_id,
                    "tokens_sent": getattr(exc, "tokens_sent", chunks),
                },
            )
            yield sse_error(_STREAM_INTERRUPTED)
            return
        finally:
            await _close_iterator(iterator)

        duration_ms = round(elapsed_ms(started), 2)
        await self._health.record_success(provider_id, ttft_ms)
        self._record_request(status="success", provider=provider_id, latency_ms=ttft_ms)
        logger.info(
            "stream completed",
            extra={
                "event": "stream_completed",
                "request_id": request_id,
                "provider": provider_id,
                "ttft_ms": ttft_ms,
                "stream_duration_ms": duration_ms,
                "chunks": chunks,
            },
        )
        yield sse_done()

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
        self._record_request(status="success", provider=provider.config.id, latency_ms=latency_ms)
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

    def _record_cache(self, header: CacheHeader) -> None:
        if header == "HIT":
            self._metrics.cache_hits.inc()
        elif header == "MISS":
            self._metrics.cache_misses.inc()

    def _record_request(self, *, status: str, provider: str, latency_ms: float) -> None:
        self._metrics.requests.labels(status=status, strategy=self._router.strategy_name).inc()
        self._metrics.request_duration.labels(provider=provider, status=status).observe(
            max(latency_ms, 0) / 1000
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


async def _close_iterator(iterator: AsyncIterator[str]) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        logger.warning("provider stream close failed", extra={"event": "stream_failed"})


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = getattr(exc, "message", "")
    return isinstance(message, str) and "timed out" in message
