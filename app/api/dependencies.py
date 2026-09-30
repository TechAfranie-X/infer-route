"""FastAPI dependencies for shared application services."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.routing.health import HealthRegistry
from app.services.inference import InferenceService
from app.services.metrics import MetricsService
from app.services.readiness import RedisProbe


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request) -> RedisProbe:
    return request.app.state.redis


def get_inference_service(request: Request) -> InferenceService:
    return request.app.state.inference_service


def get_health_registry(request: Request) -> HealthRegistry:
    return request.app.state.health


def get_metrics(request: Request) -> MetricsService:
    return request.app.state.metrics


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[RedisProbe, Depends(get_redis)]
InferenceDep = Annotated[InferenceService, Depends(get_inference_service)]
HealthDep = Annotated[HealthRegistry, Depends(get_health_registry)]
MetricsDep = Annotated[MetricsService, Depends(get_metrics)]
