"""Health and readiness response models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ServiceStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class DependencyStatus(StrEnum):
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


class HealthResponse(BaseModel):
    status: ServiceStatus
    service: str = "inferroute"
    version: str
    redis: DependencyStatus
    environment: str = Field(description="Deployment environment, not a secret.")
