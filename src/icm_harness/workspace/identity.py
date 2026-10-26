"""Fingerprint product inputs, including non-ignored untracked files.

Runtime state is excluded. Declared generated paths may exclude untracked output
only: tracked source and tests are always included. This is an integrity check,
not a sandbox against a malicious process with the same user's filesystem access.
"""

from __future__ import annotations

import os
import subprocess
from hashlib import sha256
from pathlib import Path

_RUNTIME = (".harness/runtime/", ".harness/rounds/", ".harness/worktrees/")


def git_revision(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        raise ValueError("verification/promotion requires a Git repository with a commit")
    return proc.stdout.strip()


def candidate_paths(root: Path, generated_paths: tuple[str, ...] = ()) -> tuple[str, ...]:
    root = root.resolve()
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    others = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    tracked_names = {os.fsdecode(name) for name in tracked if name}
    names = tracked_names | {os.fsdecode(name) for name in others if name}
    result = []
    for name in sorted(names):
        if name.startswith(_RUNTIME) or name == "2_Working_State/CURRENT":
            continue
        if name not in tracked_names and any(
            name == prefix.rstrip("/") or name.startswith(prefix.rstrip("/") + "/")
            for prefix in generated_paths
        ):
            continue
        result.append(name)
    return tuple(result)


def candidate_identity(root: Path, generated_paths: tuple[str, ...] = ()) -> str:
    digest = sha256()
    for name in candidate_paths(root, generated_paths):
        path = root / name
        digest.update(os.fsencode(name) + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b"exec\0" if path.stat().st_mode & 0o111 else b"file\0")
            digest.update(sha256(path.read_bytes()).digest())
        elif path.is_dir():
            raise ValueError(f"submodules/directories need an explicit verifier: {name}")
        else:
            digest.update(b"deleted\0")
        digest.update(b"\0")
    return digest.hexdigest()


def protected_identity(root: Path, paths: tuple[str, ...]) -> str:
    digest = sha256()
    for relative in sorted(paths):
        base = root / relative
        files = sorted(base.rglob("*")) if base.is_dir() and not base.is_symlink() else [base]
        for path in files:
            name = path.relative_to(root).as_posix()
            digest.update(name.encode() + b"\0")
            if path.is_symlink():
                raise ValueError(f"protected inputs must not use symlinks: {name}")
            elif path.is_file():
                if not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f"protected path escapes project: {relative}")
                digest.update(path.read_bytes())
                digest.update(str(path.stat().st_mode & 0o111).encode())
            elif path.is_dir():
                digest.update(b"directory")
            else:
                digest.update(b"missing")
            digest.update(b"\0")
    return digest.hexdigest()


def artifact_identity(root: Path, paths: tuple[str, ...]) -> str:
    """Bind explicit built files, including ignored outputs, to content and mode."""
    root = root.resolve()
    digest = sha256()
    if not paths:
        raise ValueError("built artifact identity requires explicit files")
    for name in sorted(paths):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact path must stay inside the candidate")
        path = root / relative
        if any((root / parent).is_symlink() for parent in (relative, *relative.parents)):
            raise ValueError(f"built artifact must not use symlinks: {name}")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"missing built artifact file: {name}")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError(f"built artifact exceeds 32 MiB budget: {name}")
        content = sha256()
        size = 0
        with path.open("rb") as stream:
            while block := stream.read(65536):
                size += len(block)
                if size > 32 * 1024 * 1024:
                    raise ValueError(f"built artifact exceeds 32 MiB budget: {name}")
                content.update(block)
        digest.update(name.encode() + b"\0")
        digest.update(b"exec\0" if path.stat().st_mode & 0o111 else b"file\0")
        digest.update(content.digest())
    return digest.hexdigest()
