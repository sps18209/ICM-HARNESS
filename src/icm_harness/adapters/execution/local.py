"""Local POSIX execution adapter. Trusted development, not a sandbox."""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import anyio

from icm_harness.kernel.providers import (
    CommandObservation,
    CommandSpec,
    EnvironmentRef,
    EnvironmentSpec,
    ExecutionHandle,
)


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"verification path escapes worktree: {relative}")
    return path


class LocalExecutionProvider:
    def __init__(self):
        self._sessions: dict[str, EnvironmentSpec] = {}
        self._active: dict[str, anyio.abc.Process] = {}
        self._busy: set[str] = set()

    def capabilities(self) -> EnvironmentRef:
        facts = {
            "harness_python_version": sys.version,
            "harness_python_executable": str(Path(sys.executable).resolve()),
            "harness_python_implementation": platform.python_implementation(),
        }
        return EnvironmentRef(
            "local",
            platform.system(),
            platform.machine(),
            "trusted-development",
            ("process", "filesystem", "posix-process-groups", "fresh-artifacts")
            if os.name == "posix"
            else (),
            sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
            facts=facts,
        )

    async def prepare(self, spec: EnvironmentSpec) -> ExecutionHandle:
        environment = self.capabilities()
        missing = set(spec.required_capabilities) - set(environment.capabilities)
        if missing:
            raise ValueError("unsupported capabilities: " + ", ".join(sorted(missing)))
        if os.name != "posix":
            raise OSError("local verification requires POSIX process groups")
        if not Path(spec.workspace_locator).is_dir():
            raise OSError("workspace must be an existing directory")
        facts = dict(environment.facts)
        for name in ("requirements/dev.lock", "package-lock.json", "uv.lock", "poetry.lock"):
            lock = inside(Path(spec.workspace_locator), name)
            if lock.is_file():
                if lock.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("declared dependency lock exceeds fingerprint budget")
                facts[f"declared_lock_sha256:{name}"] = sha256(lock.read_bytes()).hexdigest()
        environment = replace(
            environment,
            facts=facts,
            toolchain_digest=sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(),
        )
        root = Path(spec.workspace_locator).resolve()
        for name in spec.artifact_paths:
            relative = Path(name)
            if any((root / parent).is_symlink() for parent in (relative, *relative.parents)):
                raise ValueError(f"artifact output must not use symlinks: {name}")
            self._prepare_report(root, name)
        Path(spec.evidence_locator).mkdir(parents=True, exist_ok=True)
        handle = ExecutionHandle(uuid.uuid4().hex, environment)
        self._sessions[handle.token] = EnvironmentSpec(
            str(Path(spec.workspace_locator).resolve()),
            str(Path(spec.evidence_locator).resolve()),
            dict(spec.environment),
            tuple(spec.required_capabilities),
            tuple(spec.artifact_paths),
        )
        return handle

    def _spec(self, handle: ExecutionHandle) -> EnvironmentSpec:
        if handle.token not in self._sessions:
            raise ValueError("unknown or closed execution handle")
        return self._sessions[handle.token]

    def _prepare_report(self, root: Path, relative: str) -> None:
        name = Path(relative)
        if any((root / parent).is_symlink() for parent in (name, *name.parents)):
            raise ValueError(f"verification outputs must not use symlinks: {relative}")
        path = inside(root, relative)
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                path.relative_to(root.resolve()).as_posix(),
            ],
            capture_output=True,
        )
        if tracked.returncode == 0:
            raise ValueError("report output must not overwrite a tracked product input")
        if path.exists():
            path.unlink()

    async def execute(self, handle: ExecutionHandle, command: CommandSpec) -> CommandObservation:
        self._spec(handle)
        if handle.token in self._busy:
            raise ValueError("execution handle already has an active command")
        self._busy.add(handle.token)
        try:
            return await self._execute(handle, command)
        finally:
            self._busy.discard(handle.token)

    async def _execute(self, handle: ExecutionHandle, command: CommandSpec) -> CommandObservation:
        spec = self._spec(handle)
        root, evidence = Path(spec.workspace_locator), Path(spec.evidence_locator)
        stdout, stderr = (
            evidence / f"{command.id}.{stream}.log" for stream in ("stdout", "stderr")
        )
        started = time.monotonic()
        code, error, infrastructure = None, "", False
        try:
            if command.report:
                self._prepare_report(root, command.report)
            for name in command.evidence_paths:
                self._prepare_report(root, name)
            env = dict(spec.environment)
            env["ICM_VERIFICATION_DIR"] = str(evidence)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            with stdout.open("wb") as out, stderr.open("wb") as err:
                process = await anyio.open_process(
                    list(command.argv),
                    cwd=inside(root, command.cwd),
                    env=env,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                )
                self._active[handle.token] = process
                try:
                    with anyio.fail_after(command.timeout_seconds):
                        while process.returncode is None:
                            with anyio.move_on_after(0.1):
                                await process.wait()
                            if stdout.stat().st_size + stderr.stat().st_size > 16 * 1024 * 1024:
                                raise ValueError("command exceeded the 16 MiB log budget")
                        code = process.returncode
                finally:
                    with anyio.CancelScope(shield=True):
                        await self.cancel(handle)
                        await process.aclose()
                        self._active.pop(handle.token, None)
            if stdout.stat().st_size + stderr.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("command exceeded the 16 MiB log budget")
        except (OSError, ValueError, TimeoutError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            infrastructure = isinstance(exc, (OSError, TimeoutError))
        tails = {}
        for name, path in (("stdout", stdout), ("stderr", stderr)):
            if path.exists():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 8000))
                    tails[name] = stream.read().decode("utf-8", errors="replace")
        return CommandObservation(
            code,
            round(time.monotonic() - started, 4),
            str(stdout),
            str(stderr),
            tails,
            error,
            infrastructure,
        )

    async def cancel(self, handle: ExecutionHandle) -> None:
        process = self._active.get(handle.token)
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await anyio.sleep(0.05)
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def collect(self, handle: ExecutionHandle, relative: str, limit: int) -> bytes:
        path = inside(Path(self._spec(handle).workspace_locator), relative)
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError("missing or oversized verification report")
        with path.open("rb") as stream:
            source = stream.read(limit + 1)
        if len(source) > limit:
            raise ValueError("oversized verification report")
        return source

    async def close(self, handle: ExecutionHandle) -> None:
        await self.cancel(handle)
        self._sessions.pop(handle.token, None)
