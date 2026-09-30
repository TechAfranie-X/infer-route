"""Test doubles for dependencies Milestone 1 talks to."""


class FakeRedis:
    """In-memory stand-in for the Redis commands the foundation actually calls."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False
        self.pings = 0
        self.values: dict[str, str] = {}
        self.fail_commands = False

    async def ping(self) -> bool:
        self.pings += 1
        if not self.healthy:
            raise ConnectionError("redis down")
        return True

    async def aclose(self) -> None:
        self.closed = True

    async def get(self, key: str) -> str | None:
        if self.fail_commands:
            raise ConnectionError("redis down")
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        del ex
        if self.fail_commands:
            raise ConnectionError("redis down")
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True
