"""Redis response cache.

Only temperature 0 is eligible. Warmer sampling bypasses the cache so stochastic
generations are not replayed as if they were deterministic. Redis errors are
logged and ignored: a cache outage must not fail inference.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from app.models.requests import ChatCompletionRequest
from app.utils.hashing import lock_cache_key, response_cache_key

logger = logging.getLogger("inferroute.cache")

CacheHeader = Literal["HIT", "MISS", "BYPASS"]


class CacheStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None: ...


@dataclass(frozen=True)
class CacheEntry:
    provider: str
    content: str
    created_at: str


@dataclass(frozen=True)
class CacheLookup:
    header: CacheHeader
    entry: CacheEntry | None = None


class ResponseCache:
    def __init__(
        self,
        store: CacheStore,
        *,
        enabled: bool,
        ttl_seconds: int,
        lock_ttl_seconds: int = 10,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._ttl_seconds = ttl_seconds
        self._lock_ttl_seconds = lock_ttl_seconds

    async def lookup(self, request: ChatCompletionRequest) -> CacheLookup:
        if not self._enabled or not is_cache_eligible(request):
            return CacheLookup(header="BYPASS")

        key = response_cache_key(request)
        entry = await self._read(key)
        if entry is not None:
            return CacheLookup(header="HIT", entry=entry)

        acquired = await self._acquire_lock(lock_cache_key(request))
        if not acquired:
            for _ in range(5):
                await asyncio.sleep(0.02)
                entry = await self._read(key)
                if entry is not None:
                    return CacheLookup(header="HIT", entry=entry)
        logger.info("cache miss", extra={"event": "cache_miss"})
        return CacheLookup(header="MISS")

    async def store(self, request: ChatCompletionRequest, *, provider: str, content: str) -> None:
        if not self._enabled or not is_cache_eligible(request):
            return
        payload = json.dumps(
            {
                "provider": provider,
                "content": content,
                "created_at": datetime.now(UTC).isoformat(),
                "metadata": {},
            },
            separators=(",", ":"),
        )
        try:
            await self._store.set(response_cache_key(request), payload, ex=self._ttl_seconds)
        except Exception:
            logger.warning("cache write failed", extra={"event": "cache_error"}, exc_info=True)

    async def _read(self, key: str) -> CacheEntry | None:
        try:
            raw = await self._store.get(key)
        except Exception:
            logger.warning("cache read failed", extra={"event": "cache_error"}, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cache entry is malformed", extra={"event": "cache_error"})
            return None
        if not isinstance(payload, dict):
            return None
        provider = payload.get("provider")
        content = payload.get("content")
        created_at = payload.get("created_at")
        if not all(isinstance(value, str) for value in (provider, content, created_at)):
            return None
        return CacheEntry(provider=provider, content=content, created_at=created_at)

    async def _acquire_lock(self, key: str) -> bool:
        try:
            acquired = await self._store.set(key, "1", ex=self._lock_ttl_seconds, nx=True)
        except Exception:
            logger.warning("cache lock failed", extra={"event": "cache_error"}, exc_info=True)
            return True
        return bool(acquired)


def is_cache_eligible(request: ChatCompletionRequest) -> bool:
    """Temperature 0 is treated as deterministic. Streaming is not cached."""

    return request.temperature == 0 and not request.stream
