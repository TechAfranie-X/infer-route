"""Round-robin candidate order."""

import pytest

from app.models.provider import ProviderConfig
from app.providers.mock_provider import MockProvider
from app.routing.router import Router
from app.routing.strategies import RoundRobinStrategy


def _provider(provider_id: str, *, enabled: bool = True) -> MockProvider:
    return MockProvider(
        ProviderConfig(
            id=provider_id,
            name=provider_id,
            base_url="http://mock",
            model="general",
            enabled=enabled,
        )
    )


@pytest.mark.asyncio
async def test_round_robin_rotates_the_first_candidate() -> None:
    providers = [_provider("provider-a"), _provider("provider-b"), _provider("provider-c")]
    router = Router(RoundRobinStrategy())
    firsts = []
    for _ in range(6):
        ordered = await router.candidates(providers, {})
        firsts.append(ordered[0].config.id)
    assert firsts == [
        "provider-a",
        "provider-b",
        "provider-c",
        "provider-a",
        "provider-b",
        "provider-c",
    ]


@pytest.mark.asyncio
async def test_round_robin_keeps_the_remaining_providers_as_later_candidates() -> None:
    providers = [_provider("provider-a"), _provider("provider-b"), _provider("provider-c")]
    router = Router(RoundRobinStrategy())
    await router.candidates(providers, {})
    ordered = await router.candidates(providers, {})
    assert [provider.config.id for provider in ordered] == [
        "provider-b",
        "provider-c",
        "provider-a",
    ]
