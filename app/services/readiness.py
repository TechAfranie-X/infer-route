"""Dependency probes used by health and readiness endpoints."""

from __future__ import annotations

import logging
from typing import Protocol


class RedisProbe(Protocol):
    """The Redis operations the readiness check is allowed to call."""

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


logger = logging.getLogger("inferroute.readiness")


async def redis_is_reachable(client: RedisProbe) -> bool:
    """Return whether Redis answers PING.

    A failed probe is a dependency outage, not an application crash. Callers
    decide whether that means "degraded" or "not ready".
    """

    try:
        return bool(await client.ping())
    except Exception:
        logger.warning("redis ping failed", extra={"event": "redis_unavailable"}, exc_info=True)
        return False
