"""Inference orchestration.

The router chooses the provider order. This milestone uses the first candidate.
Retries, fallback, and caching are added around the same loop later.
"""

from __future__ import annotations

import logging

from app.core.exceptions import (
    AllProvidersUnavailableError,
    InvalidRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.models.requests import ChatCompletionRequest
from app.models.responses import ChatCompletionResponse
from app.providers.errors import NonRetryableProviderError, RetryableProviderError
from app.providers.registry import ProviderRegistry
from app.routing.health import HealthRegistry
from app.routing.router import Router
from app.utils.timing import elapsed_ms, monotonic_ms

logger = logging.getLogger("inferroute.inference")


class InferenceService:
    def __init__(
        self,
        registry: ProviderRegistry,
        router: Router,
        health: HealthRegistry,
    ) -> None:
        self._registry = registry
        self._router = router
        self._health = health

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
        candidates = await self._router.candidates(self._registry.enabled())
        if not candidates:
            raise AllProvidersUnavailableError(
                "No model endpoint could successfully complete the request.",
                request_id=request_id,
            )

        provider = candidates[0]
        logger.info(
            "provider selected",
            extra={
                "event": "provider_selected",
                "request_id": request_id,
                "provider": provider.config.id,
                "routing_strategy": "round_robin",
            },
        )
        try:
            generation = await provider.generate(request)
        except RetryableProviderError as exc:
            await self._health.record_failure(provider.config.id)
            logger.warning(
                "provider failure",
                extra={
                    "event": "provider_failure",
                    "request_id": request_id,
                    "provider": provider.config.id,
                    "status_code": exc.status_code,
                },
            )
            if "timed out" in exc.message:
                raise ProviderTimeoutError(
                    "The model endpoint timed out.",
                    request_id=request_id,
                ) from exc
            raise AllProvidersUnavailableError(
                "No model endpoint could successfully complete the request.",
                request_id=request_id,
            ) from exc
        except NonRetryableProviderError as exc:
            if exc.status_code in {400, 422}:
                raise InvalidRequestError(
                    "The model endpoint rejected the request.",
                    request_id=request_id,
                ) from exc
            raise ProviderResponseError(
                "The model endpoint rejected the request.",
                request_id=request_id,
            ) from exc

        await self._health.record_success(provider.config.id, generation.latency_ms)
        latency_ms = round(elapsed_ms(started), 2)
        logger.info(
            "inference completed",
            extra={
                "event": "inference_completed",
                "request_id": request_id,
                "provider": provider.config.id,
                "attempts": 1,
                "latency_ms": latency_ms,
            },
        )
        return ChatCompletionResponse(
            id=request_id,
            model=request.model,
            provider=provider.config.id,
            cached=False,
            attempts=1,
            latency_ms=latency_ms,
            content=generation.content,
        )
