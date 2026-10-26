"""Versioned acceptance contracts, independent of transports and execution providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256


@dataclass(frozen=True)
class Check:
    id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 300
    cwd: str = ""
    result_format: str = "exit_code"
    report: str = ""
    allow_skips: bool = False
    expected_tests: tuple[str, ...] = ()
    optional_skips: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Requirement:
    id: str
    description: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class ProjectProfile:
    schema_version: int
    requirements: tuple[Requirement, ...]
    checks: tuple[Check, ...]
    setup: tuple[Check, ...] = ()
    reset: tuple[Check, ...] = ()
    ready: tuple[Check, ...] = ()
    teardown: tuple[Check, ...] = ()
    generated_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    inherit_environment: tuple[str, ...] = ("PATH", "HOME", "LANG", "TMPDIR")

    def payload(self) -> dict:
        payload = json.loads(json.dumps(asdict(self)))
        if not self.required_capabilities:
            # Preserve digests for captured profiles created before capability negotiation.
            payload.pop("required_capabilities")
        return payload

    @property
    def digest(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True).encode()).hexdigest()
