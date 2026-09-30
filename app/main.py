"""FastAPI application factory and process lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis

from app import __version__
from app.api.errors import (
    inferroute_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.middleware import RequestContextMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.inference import router as inference_router
from app.core.config import Settings, get_settings
from app.core.exceptions import InferRouteError
from app.core.logging import configure_logging, redact_url
from app.providers.base import LLMProvider
from app.providers.loading import build_http_providers
from app.providers.registry import ProviderRegistry
from app.services.inference import InferenceService
from app.services.readiness import RedisProbe, redis_is_reachable

logger = logging.getLogger("inferroute.lifecycle")


def create_redis_client(settings: Settings) -> Redis:
    """Build a shared async Redis client. Connections are opened lazily on first use."""

    return Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        decode_responses=True,
    )


def create_app(
    settings: Settings | None = None,
    redis_client: RedisProbe | None = None,
    providers: Sequence[LLMProvider] | None = None,
) -> FastAPI:
    """Build the gateway application.

    ``redis_client`` lets tests inject a fake without opening a network connection.
    Production and ``uvicorn app.main:app`` leave it unset and connect from settings.
    """

    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        client = redis_client
        if client is None:
            client = create_redis_client(resolved_settings)
        app.state.redis = client
        app.state.settings = resolved_settings
        http_client: httpx.AsyncClient | None = None
        resolved_providers: Sequence[LLMProvider]
        if providers is None:
            http_client = httpx.AsyncClient()
            resolved_providers = build_http_providers(resolved_settings, http_client)
        else:
            resolved_providers = providers
        app.state.http_client = http_client
        app.state.registry = ProviderRegistry(resolved_providers)
        app.state.inference_service = InferenceService(app.state.registry)
        if await redis_is_reachable(client):
            logger.info(
                "redis connection established",
                extra={
                    "event": "redis_connected",
                    "redis_url": redact_url(resolved_settings.redis_url),
                },
            )
        else:
            logger.warning(
                "redis unavailable at startup",
                extra={
                    "event": "redis_unavailable",
                    "redis_url": redact_url(resolved_settings.redis_url),
                },
            )
        try:
            yield
        finally:
            if http_client is not None:
                await http_client.aclose()
            await client.aclose()
            logger.info("redis connection closed", extra={"event": "redis_closed"})

    app = FastAPI(
        title="InferRoute",
        version=__version__,
        summary="LLM inference gateway",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(InferRouteError, inferroute_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(health_router)
    app.include_router(inference_router)
    return app


app = create_app()
