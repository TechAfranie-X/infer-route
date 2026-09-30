"""Test doubles for dependencies Milestone 1 talks to."""


class FakeRedis:
    """In-memory stand-in for the Redis commands the foundation actually calls."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        if not self.healthy:
            raise ConnectionError("redis down")
        return True

    async def aclose(self) -> None:
        self.closed = True
