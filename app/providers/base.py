"""Provider interface used by routing and inference.

Callers depend on this abstraction. Concrete HTTP and mock providers live beside it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.models.provider import ProviderConfig
from app.models.requests import ChatCompletionRequest


@dataclass(frozen=True)
class GenerationResult:
    content: str
    provider_id: str
    latency_ms: float


class LLMProvider(ABC):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def generate(self, request: ChatCompletionRequest) -> GenerationResult:
        """Return one complete completion."""

    @abstractmethod
    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[str]:
        """Yield text chunks as the provider produces them."""

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Return whether the endpoint is able to accept traffic."""
