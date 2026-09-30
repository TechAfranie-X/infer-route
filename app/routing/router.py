"""The only component that chooses a provider order."""

from __future__ import annotations

from app.providers.base import LLMProvider
from app.routing.strategies import RoundRobinStrategy


class Router:
    def __init__(self, strategy: RoundRobinStrategy) -> None:
        self._strategy = strategy

    async def candidates(self, providers: list[LLMProvider]) -> list[LLMProvider]:
        return await self._strategy.order(providers)
