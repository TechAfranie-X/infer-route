"""Routing strategies return providers in the order they should be tried."""

from __future__ import annotations

import asyncio

from app.providers.base import LLMProvider


class RoundRobinStrategy:
    """Rotate the first choice across enabled providers: A, B, C, A, B, C."""

    def __init__(self) -> None:
        self._index = 0
        self._lock = asyncio.Lock()

    async def order(self, providers: list[LLMProvider]) -> list[LLMProvider]:
        if not providers:
            return []
        async with self._lock:
            start = self._index % len(providers)
            self._index += 1
        return providers[start:] + providers[:start]
