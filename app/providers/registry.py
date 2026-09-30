"""Ordered collection of configured providers."""

from __future__ import annotations

from collections.abc import Sequence

from app.providers.base import LLMProvider


class ProviderRegistry:
    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        self._providers = list(providers)

    def enabled(self) -> list[LLMProvider]:
        return [provider for provider in self._providers if provider.config.enabled]

    def get(self, provider_id: str) -> LLMProvider:
        for provider in self._providers:
            if provider.config.id == provider_id:
                return provider
        raise KeyError(provider_id)
