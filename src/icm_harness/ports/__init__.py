"""Provider contracts. No concrete clients, SDKs or operating-system commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from icm_harness.kernel.providers import (
    CandidateRef,
    CommandObservation,
    CommandSpec,
    EnvironmentRef,
    EnvironmentSpec,
    EvidenceRef,
    ExecutionHandle,
)
from icm_harness.kernel.verification import Check


class ExecutionProvider(Protocol):
    def capabilities(self) -> EnvironmentRef: ...
    async def prepare(self, spec: EnvironmentSpec) -> ExecutionHandle: ...
    async def execute(
        self, handle: ExecutionHandle, command: CommandSpec
    ) -> CommandObservation: ...
    async def cancel(self, handle: ExecutionHandle) -> None: ...
    async def collect(self, handle: ExecutionHandle, relative: str, limit: int) -> bytes: ...
    async def close(self, handle: ExecutionHandle) -> None: ...


class CandidateProvider(Protocol):
    def capture(self, locator: str, generated_paths: tuple[str, ...] = ()) -> CandidateRef: ...
    def fingerprint(self, ref: CandidateRef) -> str: ...
    def protected_identity(self, locator: str, paths: tuple[str, ...]) -> str: ...
    def assert_unchanged(self, ref: CandidateRef) -> None: ...
    def resolve_artifact(self, ref: CandidateRef) -> str: ...
    def artifact_identity(self, locator: str, paths: tuple[str, ...]) -> str: ...


class VerifierProvider(Protocol):
    def evaluate(self, check: Check, source: bytes) -> dict: ...


class EvidenceStore(Protocol):
    def put_blob(self, source: bytes, media_type: str) -> EvidenceRef: ...
    def get_blob(self, reference: EvidenceRef) -> bytes: ...
    def seal_run(self, run_id: str, manifest: bytes) -> EvidenceRef: ...


@dataclass(frozen=True)
class VerificationProviders:
    execution: ExecutionProvider
    candidate: CandidateProvider
    verifiers: dict[str, VerifierProvider]
    evidence: EvidenceStore | None = None
