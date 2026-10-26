"""Versioned owner-supplied acceptance and environment contracts.

Commands are argv arrays, never implicit shell strings. Profiles are captured by
the application before an agent runs; edits in a worktree cannot select new checks.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path, PurePosixPath

from icm_harness.kernel.verification import Check, ProjectProfile, Requirement


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
    if not isinstance(fmt, str) or fmt not in {"exit_code", "junit", "pytest_events"}:
        raise ValueError("result_format must be exit_code, junit or pytest_events")
    report = data.get("report", "")
    if fmt != "exit_code":
        relative_path(report)
    if not isinstance(data.get("allow_skips", False), bool):
        raise ValueError("allow_skips must be boolean")
    if data.get("allow_skips", False):
        raise ValueError(
            "blanket allow_skips is unsafe; use optional_skips with exact IDs and reasons"
        )
    expected = data.get("expected_tests", [])
    optional = data.get("optional_skips", {})
    if (
        not isinstance(expected, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in expected)
        or len(set(expected)) != len(expected)
        or (fmt != "exit_code" and not expected)
    ):
        raise ValueError("report checks require unique, non-empty expected_tests")
    if not isinstance(optional, dict) or any(
        key not in expected or not isinstance(reason, str) or not reason.strip()
        for key, reason in optional.items()
    ):
        raise ValueError("optional_skips must map expected test IDs to non-empty reasons")
    if fmt == "exit_code" and (expected or optional):
        raise ValueError("test identities require a structured report check")
    attachments = data.get("attachments", {})
    if not isinstance(attachments, dict) or len(attachments) > 16:
        raise ValueError("attachments must map at most 16 paths to media types")
    for path, media_type in attachments.items():
        relative_path(path)
        if (
            str(PurePosixPath(path)) != path
            or not isinstance(media_type, str)
            or not re.fullmatch(r"[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+", media_type)
        ):
            raise ValueError("attachments require canonical paths and explicit media types")
    return Check(
        _identifier(data.get("id")),
        tuple(argv),
        float(timeout),
        cwd,
        fmt,
        report,
        False,
        tuple(expected),
        dict(optional),
        dict(attachments),
    )


def parse_profile(data: object) -> ProjectProfile:
    if not isinstance(data, dict) or set(data) - set(ProjectProfile.__dataclass_fields__):
        raise ValueError("invalid project profile fields")
    if type(data.get("schema_version")) is not int or data["schema_version"] not in {1, 2}:
        raise ValueError("project profile schema_version must be 1 or 2")
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
    capabilities = data.get("required_capabilities", [])
    if not isinstance(capabilities, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in capabilities
    ):
        raise ValueError("required_capabilities must contain non-empty strings")
    artifacts = data.get("artifact_paths", [])
    if not isinstance(artifacts, (list, tuple)) or len(artifacts) > 64:
        raise ValueError("artifact_paths must be an array of at most 64 explicit files")
    artifacts = tuple(relative_path(path) for path in artifacts)
    generated = tuple(relative_path(path) for path in generated)
    protected = tuple(relative_path(path) for path in protected)
    if len(set(artifacts)) != len(artifacts) or any(
        str(PurePosixPath(path)) != path for path in artifacts
    ):
        raise ValueError("artifact_paths must contain unique canonical relative paths")
    reports = {
        str(PurePosixPath(check.report))
        for checks in groups.values()
        for check in checks
        if check.report
    }
    for path in artifacts:
        if not any(
            path.startswith(prefix.rstrip("/") + "/") or path == prefix
            for prefix in (*[str(PurePosixPath(p)) for p in generated], ".harness/runtime")
        ):
            raise ValueError("artifacts must be inside generated_paths or .harness/runtime")
        if path in reports or any(
            item == "."
            or path == item
            or path.startswith(item + "/")
            or item.startswith(path + "/")
            for item in (str(PurePosixPath(p)) for p in protected)
        ):
            raise ValueError("artifacts must not overlap protected inputs or check reports")
    for checks in groups.values():
        for check in checks:
            for path in check.attachments:
                if not any(
                    path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
                    for prefix in (*generated, ".harness/runtime")
                ):
                    raise ValueError(
                        "attachments must be inside generated_paths or .harness/runtime"
                    )
                if (
                    path in artifacts
                    or path in reports
                    or any(
                        item == "."
                        or path == item
                        or path.startswith(item + "/")
                        or item.startswith(path + "/")
                        for item in (str(PurePosixPath(p)) for p in protected)
                    )
                ):
                    raise ValueError(
                        "attachments must not overwrite artifacts, reports or protected inputs"
                    )
    return ProjectProfile(
        data["schema_version"],
        tuple(requirements),
        **groups,
        generated_paths=generated,
        protected_paths=protected,
        inherit_environment=tuple(env),
        required_capabilities=tuple(capabilities),
        artifact_paths=artifacts,
    )


def load_profile(root: Path) -> ProjectProfile:
    path = root / ".harness/project.json"
    if not path.is_file():
        raise ValueError("verification requires an owner-supplied .harness/project.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return parse_profile(data)
    protected = data.get("protected_paths", [])
    if not isinstance(protected, (list, tuple)):
        raise ValueError("protected_paths must be an array")
    protected = list(protected)
    for group in ("checks", "setup", "reset", "ready", "teardown"):
        checks = data.get(group, [])
        if not isinstance(checks, (list, tuple)):
            raise ValueError(f"{group} must be an array")
        for check in checks:
            if not isinstance(check, dict) or "test_manifest" not in check:
                continue
            relative = relative_path(check.pop("test_manifest"))
            manifest_path = (root / relative).resolve()
            if not manifest_path.is_relative_to(root.resolve()):
                raise ValueError("test manifest escapes project")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                not isinstance(manifest, dict)
                or set(manifest) != {"schema_version", "tests", "optional_skips"}
                or type(manifest["schema_version"]) is not int
                or manifest["schema_version"] != 1
                or "expected_tests" in check
                or "optional_skips" in check
            ):
                raise ValueError("invalid or conflicting test manifest")
            check["expected_tests"] = manifest["tests"]
            check["optional_skips"] = manifest["optional_skips"]
            protected.append(relative)
    data["protected_paths"] = list(dict.fromkeys(protected))
    return parse_profile(data)
