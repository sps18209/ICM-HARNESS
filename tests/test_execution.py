import anyio
import pytest

from icm_harness.execution.concurrency import KeyedLimiter
from icm_harness.execution.local import LocalExecutor
from icm_harness.kernel.state import SQLiteStateStore


def test_local_executor_releases_lease(tmp_path):
    async def scenario():
        state = SQLiteStateStore(tmp_path / "s.db")
        executor = LocalExecutor(state, KeyedLimiter())

        async def work():
            await anyio.sleep(0.01)
            return 42

        value = await executor.run(
            work,
            resource_key="r",
            owner="w",
            timeout_seconds=2,
            lease_ttl_seconds=2,
            heartbeat_seconds=1,
        )
        assert value == 42
        assert state.lease_owner("r") is None

    anyio.run(scenario)


def test_local_executor_releases_lease_on_failure(tmp_path):
    """A stage that raises must still release its lease so a retry can re-enter.

    Regression: a real-agent run raised out of the wrapped call while the lease
    heartbeat task group was torn down, and the lease was left held by the dead
    owner. The next attempt (a fresh owner) was then refused with
    LeaseUnavailable.
    """

    async def scenario():
        state = SQLiteStateStore(tmp_path / "s.db")
        executor = LocalExecutor(state, KeyedLimiter())

        async def boom():
            await anyio.sleep(0.01)
            raise RuntimeError("stage exploded")

        with pytest.raises(RuntimeError, match="stage exploded"):
            await executor.run(
                boom,
                resource_key="r",
                owner="owner-1",
                timeout_seconds=2,
                lease_ttl_seconds=2,
                heartbeat_seconds=1,
            )
        # Lease must be free even though the wrapped call failed.
        assert state.lease_owner("r") is None

        # A retry with a *different* owner must be able to acquire the lease.
        async def work():
            return 42

        value = await executor.run(
            work,
            resource_key="r",
            owner="owner-2",
            timeout_seconds=2,
            lease_ttl_seconds=2,
            heartbeat_seconds=1,
        )
        assert value == 42

    anyio.run(scenario)
