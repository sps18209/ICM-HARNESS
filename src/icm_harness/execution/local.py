from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import anyio

from icm_harness.execution.concurrency import KeyedLimiter
from icm_harness.execution.watchdog import LeaseHeartbeat
from icm_harness.kernel.state import SQLiteStateStore

T = TypeVar("T")


@dataclass
class LocalExecutor:
    state: SQLiteStateStore
    limiter: KeyedLimiter

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        resource_key: str,
        owner: str,
        timeout_seconds: float,
        concurrency_limit: int = 1,
        lease_ttl_seconds: int = 90,
        heartbeat_seconds: int = 20,
    ) -> T:
        async with (
            self.limiter.slot(resource_key, concurrency_limit),
            LeaseHeartbeat(
                self.state, resource_key, owner, lease_ttl_seconds, heartbeat_seconds
            ) as lease,
        ):
            with anyio.fail_after(timeout_seconds):
                result = await fn()
                lease.assert_alive()
                return result
