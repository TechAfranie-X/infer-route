"""Runtime provider health.

Static provider config stays on ``ProviderConfig``. This registry only stores what
traffic and probes observe: EWMA latency, consecutive failures, and cooldown.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.core.config import Settings
from app.providers.base import LLMProvider

logger = logging.getLogger("inferroute.health")


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ProviderHealth:
    status: HealthStatus = HealthStatus.HEALTHY
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    ewma_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    has_latency_sample: bool = False


def update_ewma(previous: float, sample: float, alpha: float, *, has_sample: bool) -> float:
    """Fold one latency sample into an exponentially weighted moving average.

    The first sample becomes the average. After that, ``alpha`` is the weight of
    the new sample, so recent latency moves the score more than old history.
    """

    if not has_sample:
        return sample
    return (alpha * sample) + ((1 - alpha) * previous)


class HealthRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._states: dict[str, ProviderHealth] = {}
        self._lock = asyncio.Lock()

    async def snapshot(self, provider_id: str) -> ProviderHealth:
        async with self._lock:
            return replace(self._states.get(provider_id, ProviderHealth()))

    async def snapshots(self) -> dict[str, ProviderHealth]:
        async with self._lock:
            return {provider_id: replace(state) for provider_id, state in self._states.items()}

    async def record_success(
        self,
        provider_id: str,
        latency_ms: float,
        *,
        now: datetime | None = None,
    ) -> ProviderHealth:
        current = now or datetime.now(UTC)
        async with self._lock:
            state = self._states.setdefault(provider_id, ProviderHealth())
            state.ewma_latency_ms = update_ewma(
                state.ewma_latency_ms,
                latency_ms,
                self._settings.ewma_alpha,
                has_sample=state.has_latency_sample,
            )
            state.has_latency_sample = True
            state.last_latency_ms = latency_ms
            state.total_requests += 1
            state.consecutive_failures = 0
            state.last_success_at = current
            state.cooldown_until = None
            state.status = HealthStatus.HEALTHY
            return replace(state)

    async def record_failure(
        self,
        provider_id: str,
        *,
        now: datetime | None = None,
    ) -> ProviderHealth:
        current = now or datetime.now(UTC)
        async with self._lock:
            state = self._states.setdefault(provider_id, ProviderHealth())
            previous = state.status
            state.total_requests += 1
            state.total_failures += 1
            state.consecutive_failures += 1
            state.last_failure_at = current
            state.status = self._status_for(state.consecutive_failures)
            if state.status is HealthStatus.UNHEALTHY:
                state.cooldown_until = current + timedelta(
                    seconds=self._settings.provider_cooldown_seconds
                )
            self._log_transition(provider_id, previous, state)
            return replace(state)

    async def restore(self, provider_id: str, *, now: datetime | None = None) -> ProviderHealth:
        """Return a provider to the healthy pool after a successful probe.

        A health check is not an inference sample, so EWMA is left unchanged.
        """

        current = now or datetime.now(UTC)
        async with self._lock:
            state = self._states.setdefault(provider_id, ProviderHealth())
            state.status = HealthStatus.HEALTHY
            state.consecutive_failures = 0
            state.cooldown_until = None
            state.last_success_at = current
            logger.info(
                "provider recovered",
                extra={"event": "provider_recovered", "provider": provider_id},
            )
            return replace(state)

    def _status_for(self, consecutive_failures: int) -> HealthStatus:
        if consecutive_failures >= self._settings.provider_failure_threshold_unhealthy:
            return HealthStatus.UNHEALTHY
        if consecutive_failures >= self._settings.provider_failure_threshold_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def _log_transition(
        self,
        provider_id: str,
        previous: HealthStatus,
        state: ProviderHealth,
    ) -> None:
        if state.status is previous:
            return
        event = {
            HealthStatus.DEGRADED: "provider_degraded",
            HealthStatus.UNHEALTHY: "provider_unhealthy",
            HealthStatus.HEALTHY: "provider_recovered",
        }[state.status]
        logger.warning(
            event.replace("_", " "),
            extra={
                "event": event,
                "provider": provider_id,
                "consecutive_failures": state.consecutive_failures,
                "status": state.status.value,
            },
        )


class HealthChecker:
    """Probe unhealthy providers after cooldown instead of sending them user traffic."""

    def __init__(
        self,
        registry: HealthRegistry,
        providers: list[LLMProvider],
        settings: Settings,
    ) -> None:
        self._registry = registry
        self._providers = providers
        self._settings = settings

    async def probe_due(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for provider in self._providers:
            state = await self._registry.snapshot(provider.config.id)
            if state.status is not HealthStatus.UNHEALTHY:
                continue
            if state.cooldown_until is not None and current < state.cooldown_until:
                continue
            try:
                healthy = await provider.healthcheck()
            except Exception:
                logger.warning(
                    "provider probe failed",
                    extra={"event": "provider_probe_failed", "provider": provider.config.id},
                    exc_info=True,
                )
                healthy = False
            if healthy:
                await self._registry.restore(provider.config.id, now=current)
            else:
                await self._registry.record_failure(provider.config.id, now=current)

    async def run(self, stop: asyncio.Event) -> None:
        interval = self._settings.health_check_interval_seconds
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                try:
                    await self.probe_due()
                except Exception:
                    logger.exception(
                        "health check loop failed",
                        extra={"event": "health_check_failed"},
                    )
