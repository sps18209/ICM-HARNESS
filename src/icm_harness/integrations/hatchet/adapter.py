"""Durable execution adapter.

Provides a ``DurableExecutor`` (:mod:`icm_harness.execution.durable`) backed by
Hatchet. Construction raises :class:`IntegrationUnavailable` when the Hatchet
SDK is not installed/configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HatchetConfig:
    namespace: str = "icm"
    default_concurrency: int = 8


def require_hatchet():
    try:
        import hatchet_sdk
    except ImportError as exc:
        from icm_harness.kernel.errors import IntegrationUnavailable

        raise IntegrationUnavailable("Hatchet SDK is not installed/configured") from exc
    return hatchet_sdk


class HatchetDurableExecutor:
    """Submit/cancel/status against Hatchet workflows.

    Satisfies the async ``DurableExecutor`` protocol. The Hatchet client is
    created lazily so importing this module never requires the SDK.
    """

    def __init__(self, config: HatchetConfig | None = None, *, client: Any | None = None):
        self.config = config or HatchetConfig()
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        sdk = require_hatchet()
        self._client = sdk.Hatchet()
        return self._client

    async def submit(self, workflow: str, payload: dict[str, Any]) -> str:
        client = self._ensure_client()
        ref = await client.admin.aio_run_workflow(workflow, payload)
        return getattr(ref, "workflow_run_id", str(ref))

    async def cancel(self, run_id: str) -> None:
        client = self._ensure_client()
        await client.admin.aio_cancel(run_id)

    async def status(self, run_id: str) -> str:
        client = self._ensure_client()
        state = await client.admin.aio_get_workflow_run(run_id)
        return str(getattr(state, "status", state))
