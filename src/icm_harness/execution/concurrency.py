from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio


@dataclass
class KeyedLimiter:
    default_limit: int = 1
    _limiters: dict[str, anyio.CapacityLimiter] = field(default_factory=dict)

    def _get(self, key: str, limit: int | None) -> anyio.CapacityLimiter:
        actual = limit or self.default_limit
        limiter = self._limiters.get(key)
        if limiter is None:
            limiter = anyio.CapacityLimiter(actual)
            self._limiters[key] = limiter
        return limiter

    @asynccontextmanager
    async def slot(self, key: str, limit: int | None = None):
        async with self._get(key, limit):
            yield
