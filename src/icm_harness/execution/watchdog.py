from dataclasses import dataclass

import anyio

from icm_harness.kernel.errors import LeaseLost
from icm_harness.kernel.state import SQLiteStateStore


@dataclass
class LeaseHeartbeat:
    state: SQLiteStateStore
    resource_key: str
    owner: str
    ttl_seconds: int = 90
    heartbeat_seconds: int = 20

    def __post_init__(self):
        if self.heartbeat_seconds >= self.ttl_seconds:
            raise ValueError("heartbeat must be more frequent than TTL")
        self._lost = False
        self._tg = None

    async def __aenter__(self):
        self.state.acquire_lease(self.resource_key, self.owner, self.ttl_seconds)
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._tg.start_soon(self._beat)
        return self

    async def _beat(self):
        while True:
            await anyio.sleep(self.heartbeat_seconds)
            try:
                self.state.heartbeat(self.resource_key, self.owner, self.ttl_seconds)
            except LeaseLost:
                self._lost = True
                return

    def assert_alive(self):
        if self._lost:
            raise LeaseLost(f"lease lost: {self.resource_key}")

    async def __aexit__(self, exc_type, exc, tb):
        # The lease must be released on every exit path. Two rules make this
        # safe under cancellation and stage failures:
        #   1. Close the heartbeat task group on its own terms — pass (None,
        #      None, None), not the body's exception. Feeding the body's error
        #      into the task group makes anyio re-raise it wrapped in an
        #      ExceptionGroup (losing the real type) and, before this fix,
        #      skipped the release below entirely, leaking the lease so a retry
        #      was refused with LeaseUnavailable.
        #   2. release_lease runs in `finally`, so it happens even if closing
        #      the heartbeat group raises.
        try:
            if self._tg is not None:
                self._tg.cancel_scope.cancel()
                await self._tg.__aexit__(None, None, None)
        finally:
            self.state.release_lease(self.resource_key, self.owner)
        return False
