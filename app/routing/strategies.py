"""Routing strategies return providers in the order they should be tried.

Unhealthy providers are left out of both strategies. A provider stays unhealthy
until a probe restores it, including during its cooldown window.

Latency-aware score, lower is better::

    normalized_latency = ewma_latency_ms / 1000
    score = 1.0 * normalized_latency
            + 0.5 * consecutive_failures
            + health_penalty

``health_penalty`` is 0 for healthy and 1 for degraded. One degraded penalty is
therefore worth 1000 ms of EWMA latency. Providers with no samples use a 500 ms
prior so a brand-new endpoint does not look instantaneously faster than everyone
else. Equal scores rotate, which keeps identical providers sharing traffic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from app.providers.base import LLMProvider
from app.routing.health import HealthStatus, ProviderHealth

LATENCY_WEIGHT = 1.0
FAILURE_WEIGHT = 0.5
DEGRADED_HEALTH_PENALTY = 1.0
UNSAMPLED_LATENCY_MS = 500.0


def is_excluded(state: ProviderHealth | None) -> bool:
    """Unhealthy providers are out of normal routing until a probe restores them."""

    if state is None:
        return False
    return state.status is HealthStatus.UNHEALTHY


def latency_score(state: ProviderHealth | None) -> float:
    if state is None or not state.has_latency_sample:
        normalized = UNSAMPLED_LATENCY_MS / 1000
        failures = 0
        penalty = 0.0
    else:
        normalized = state.ewma_latency_ms / 1000
        failures = state.consecutive_failures
        penalty = DEGRADED_HEALTH_PENALTY if state.status is HealthStatus.DEGRADED else 0.0
    return (LATENCY_WEIGHT * normalized) + (FAILURE_WEIGHT * failures) + penalty


class RoundRobinStrategy:
    """Rotate the first choice across eligible providers: A, B, C, A, B, C."""

    name = "round_robin"

    def __init__(self) -> None:
        self._index = 0
        self._lock = asyncio.Lock()

    async def order(
        self,
        providers: list[LLMProvider],
        health: Mapping[str, ProviderHealth],
    ) -> list[LLMProvider]:
        eligible = [
            provider for provider in providers if not is_excluded(health.get(provider.config.id))
        ]
        if not eligible:
            return []
        async with self._lock:
            start = self._index % len(eligible)
            self._index += 1
        return eligible[start:] + eligible[:start]


class LatencyAwareStrategy:
    """Prefer lower score, then rotate providers that share the best score."""

    name = "latency_aware"

    def __init__(self) -> None:
        self._index = 0
        self._lock = asyncio.Lock()

    async def order(
        self,
        providers: list[LLMProvider],
        health: Mapping[str, ProviderHealth],
    ) -> list[LLMProvider]:
        eligible = [
            provider for provider in providers if not is_excluded(health.get(provider.config.id))
        ]
        if not eligible:
            return []
        ranked = sorted(
            eligible,
            key=lambda provider: (
                latency_score(health.get(provider.config.id)),
                provider.config.id,
            ),
        )
        best = latency_score(health.get(ranked[0].config.id))
        tied = [
            provider for provider in ranked if latency_score(health.get(provider.config.id)) == best
        ]
        rest = [provider for provider in ranked if provider not in tied]
        async with self._lock:
            start = self._index % len(tied)
            self._index += 1
        rotated = tied[start:] + tied[:start]
        return rotated + rest
