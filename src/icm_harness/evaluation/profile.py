"""Versioned owner-supplied acceptance and environment contracts.

Commands are argv arrays, never implicit shell strings. Profiles are captured by
the application before an agent runs; edits in a worktree cannot select new checks.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("expected a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value == ".":
        raise ValueError(f"path must stay within the project: {value}")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("IDs must contain letters, digits, underscore, dot or hyphen")
    return value


@dataclass(frozen=True)
class Check:
    id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 300
    cwd: str = ""
    result_format: str = "exit_code"
    report: str = ""
    allow_skips: bool = False


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
    inherit_environment: tuple[str, ...] = ("PATH", "HOME", "LANG", "TMPDIR")

    def payload(self) -> dict:
        return json.loads(json.dumps(asdict(self)))

    @property
    def digest(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True).encode()).hexdigest()


def _check(data: object) -> Check:
    if not isinstance(data, dict) or set(data) - set(Check.__dataclass_fields__):
        raise ValueError("invalid check fields")
    argv = data.get("argv")
    if (
        not isinstance(argv, (list, tuple))
        or not argv
        or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
    ):
        raise ValueError("check argv must be a non-empty array of non-empty strings")
    timeout = data.get("timeout_seconds", 300)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (float, int))
        or not (math.isfinite(timeout) and 0 < timeout <= 3600)
    ):
        raise ValueError("check timeout must be finite and in (0, 3600]")
    cwd = data.get("cwd", "")
    if not isinstance(cwd, str):
        raise ValueError("check cwd must be a string")
    if cwd:
        relative_path(cwd)
    fmt = data.get("result_format", "exit_code")
    if fmt not in {"exit_code", "junit"}:
        raise ValueError("result_format must be exit_code or junit")
    report = data.get("report", "")
    if fmt == "junit":
        relative_path(report)
    if not isinstance(data.get("allow_skips", False), bool):
        raise ValueError("allow_skips must be boolean")
    return Check(
        _identifier(data.get("id")),
        tuple(argv),
        float(timeout),
        cwd,
        fmt,
        report,
        data.get("allow_skips", False),
    )


def parse_profile(data: object) -> ProjectProfile:
    if not isinstance(data, dict) or set(data) - set(ProjectProfile.__dataclass_fields__):
        raise ValueError("invalid project profile fields")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("project profile schema_version must be 1")
    groups = {}
    for group in ("checks", "setup", "reset", "ready", "teardown"):
        values = data.get(group, [])
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"{group} must be an array")
        groups[group] = tuple(_check(value) for value in values)
    ids = [check.id for checks in groups.values() for check in checks]
    if len(ids) != len(set(ids)) or not groups["checks"]:
        raise ValueError("check IDs must be unique and checks must be non-empty")
    available = {check.id for check in groups["checks"]}
    requirements = []
    values = data.get("requirements")
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("requirements must be a non-empty array")
    for value in values:
        if not isinstance(value, dict) or set(value) != {"id", "description", "checks"}:
            raise ValueError("requirements need id, description and checks")
        description = value["description"]
        refs = value["checks"]
        if not isinstance(description, str) or not description.strip():
            raise ValueError("requirement description must be non-empty")
        if (
            not isinstance(refs, (list, tuple))
            or not refs
            or any(not isinstance(ref, str) or ref not in available for ref in refs)
        ):
            raise ValueError("each requirement must reference existing executable checks")
        requirements.append(Requirement(_identifier(value["id"]), description, tuple(refs)))
    if len({item.id for item in requirements}) != len(requirements):
        raise ValueError("requirement IDs must be unique")
    generated = data.get("generated_paths", [])
    if not isinstance(generated, (list, tuple)):
        raise ValueError("generated_paths must be an array")
    protected = data.get("protected_paths", [])
    if not isinstance(protected, (list, tuple)):
        raise ValueError("protected_paths must be an array")
    env = data.get("inherit_environment", ["PATH", "HOME", "LANG", "TMPDIR"])
    if not isinstance(env, (list, tuple)) or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        for name in env
    ):
        raise ValueError("inherit_environment must contain environment variable names")
    return ProjectProfile(
        1,
        tuple(requirements),
        **groups,
        generated_paths=tuple(relative_path(path) for path in generated),
        protected_paths=tuple(relative_path(path) for path in protected),
        inherit_environment=tuple(env),
    )


def load_profile(root: Path) -> ProjectProfile:
    path = root / ".harness/project.json"
    if not path.is_file():
        raise ValueError("verification requires an owner-supplied .harness/project.json")
    return parse_profile(json.loads(path.read_text(encoding="utf-8")))
