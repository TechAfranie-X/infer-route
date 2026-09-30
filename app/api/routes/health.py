"""Liveness and readiness routes.

``GET /health`` reports that the process can serve HTTP. Redis is described in
the body, but a cache outage does not fail liveness: later milestones still
need to complete inference when Redis is down.

``GET /ready`` fails when Redis cannot be reached, so orchestrators can hold
traffic until the dependency the development stack expects is actually up.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import __version__
from app.api.dependencies import HealthDep, RedisDep, SettingsDep
from app.models.health import DependencyStatus, HealthResponse, ServiceStatus
from app.models.provider_health import ProviderHealthResponse, ProviderHealthView
from app.services.readiness import redis_is_reachable

router = APIRouter(tags=["health"])


async def _health_body(settings: SettingsDep, redis: RedisDep) -> HealthResponse:
    reachable = await redis_is_reachable(redis)
    return HealthResponse(
        status=ServiceStatus.OK if reachable else ServiceStatus.DEGRADED,
        version=__version__,
        redis=DependencyStatus.CONNECTED if reachable else DependencyStatus.UNAVAILABLE,
        environment=settings.app_env,
    )


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep, redis: RedisDep) -> HealthResponse:
    return await _health_body(settings, redis)


@router.get("/health/providers", response_model=ProviderHealthResponse)
async def provider_health(health: HealthDep) -> ProviderHealthResponse:
    snapshots = await health.snapshots()
    return ProviderHealthResponse(
        providers=[
            ProviderHealthView(
                id=provider_id,
                status=state.status,
                ewma_latency_ms=round(state.ewma_latency_ms, 3),
                consecutive_failures=state.consecutive_failures,
                total_requests=state.total_requests,
                total_failures=state.total_failures,
                cooldown_until=state.cooldown_until,
            )
            for provider_id, state in snapshots.items()
        ]
    )


@router.get("/ready", response_model=HealthResponse)
async def ready(settings: SettingsDep, redis: RedisDep) -> HealthResponse | JSONResponse:
    body = await _health_body(settings, redis)
    if body.redis is DependencyStatus.UNAVAILABLE:
        return JSONResponse(status_code=503, content=body.model_dump())
    return body
