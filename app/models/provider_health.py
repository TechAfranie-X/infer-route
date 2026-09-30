"""Provider health responses."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.routing.health import HealthStatus


class ProviderHealthView(BaseModel):
    id: str
    status: HealthStatus
    ewma_latency_ms: float
    consecutive_failures: int
    total_requests: int
    total_failures: int
    cooldown_until: datetime | None = None


class ProviderHealthResponse(BaseModel):
    providers: list[ProviderHealthView] = Field(default_factory=list)
