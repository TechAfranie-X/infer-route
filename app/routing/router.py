"""The only component that chooses a provider order."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.providers.base import LLMProvider
from app.routing.health import ProviderHealth


class RoutingStrategy(Protocol):
    async def order(
        self,
        providers: list[LLMProvider],
        health: Mapping[str, ProviderHealth],
    ) -> list[LLMProvider]:
        """Return eligible providers, best candidate first."""


class Router:
    def __init__(self, strategy: RoutingStrategy) -> None:
        self._strategy = strategy
        self.strategy_name = strategy.__class__.__name__

    async def candidates(
        self,
        providers: list[LLMProvider],
        health: Mapping[str, ProviderHealth],
    ) -> list[LLMProvider]:
        return await self._strategy.order(providers, health)
