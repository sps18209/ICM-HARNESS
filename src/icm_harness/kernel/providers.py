"""Transport-neutral provider values. Resource locators are strings, not local paths."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class CandidateRef:
    locator: str
    source_digest: str
    revision: str
    generated_paths: tuple[str, ...] = ()
    artifact_digest: str = ""
    deployment_identity: str = ""
    configuration_digest: str = ""


@dataclass(frozen=True, slots=True)
class EnvironmentRef:
    provider: str
    platform: str
    architecture: str
    isolation: str
    capabilities: tuple[str, ...]
    toolchain_digest: str = ""
    image_digest: str = ""
    facts: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    workspace_locator: str
    evidence_locator: str
    environment: Mapping[str, str]
    required_capabilities: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    token: str
    environment: EnvironmentRef


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: str
    argv: tuple[str, ...]
    cwd: str = ""
    timeout_seconds: float = 300
    report: str = ""
    evidence_paths: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.id):
            raise ValueError("command ID must be safe for evidence filenames")
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or any(not isinstance(x, str) or not x or "\x00" in x for x in self.argv)
        ):
            raise ValueError("command argv must contain non-empty strings")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 3600
        ):
            raise ValueError("command timeout must be finite and in (0, 3600]")
        if not isinstance(self.evidence_paths, tuple):
            raise ValueError("evidence paths must be a tuple")
        for name in (self.cwd, self.report, *self.evidence_paths):
            if not isinstance(name, str) or "\\" in name or "\x00" in name:
                raise ValueError("command paths must be POSIX relative paths")
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                raise ValueError("command paths must stay inside the candidate")


@dataclass(frozen=True, slots=True)
class CommandObservation:
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    output_tail: Mapping[str, str] = field(default_factory=dict)
    error: str = ""
    infrastructure_error: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    sha256: str
    size: int
    media_type: str


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    status: str
    reasons: tuple[str, ...]
    requirements: tuple[dict, ...]

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"
