import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import anyio

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_fraction: float = 0.2

    def __post_init__(self):
        if self.attempts < 1:
            raise ValueError("attempts must be >= 1")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last = None
    for attempt in range(policy.attempts):
        try:
            return await fn()
        except retry_on as exc:
            last = exc
            if attempt == policy.attempts - 1:
                break
            delay = min(policy.max_delay_seconds, policy.base_delay_seconds * (2**attempt))
            await anyio.sleep(delay + delay * policy.jitter_fraction * random.random())
    assert last is not None
    raise last
