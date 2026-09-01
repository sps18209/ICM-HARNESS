from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from icm_harness.execution.local import LocalExecutor
from icm_harness.execution.run_store import SQLiteRunStore

T = TypeVar("T")


@dataclass
class ManagedStageExecutor:
    executor: LocalExecutor
    runs: SQLiteRunStore

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        round_id: str,
        stage_ref: str,
        resource_key: str,
        owner: str,
        timeout_seconds: float,
        max_attempts: int = 3,
        attempt: int = 1,
        concurrency_limit: int = 1,
    ) -> T:
        deadline = (datetime.now(UTC) + timedelta(seconds=timeout_seconds)).isoformat()
        run = self.runs.start(
            round_id,
            stage_ref,
            owner,
            deadline,
            max_attempts=max_attempts,
            attempt=attempt,
        )
        try:
            result = await self.executor.run(
                fn,
                resource_key=resource_key,
                owner=owner,
                timeout_seconds=timeout_seconds,
                concurrency_limit=concurrency_limit,
            )
        except Exception as exc:
            self.runs.finish(run.run_id, "failed", f"{type(exc).__name__}: {exc}")
            raise
        self.runs.finish(run.run_id, "passed")
        return result
