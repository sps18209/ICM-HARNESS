"""Per-role least-privilege write scope.

Worktree isolation (ADR-0005) keeps concurrent Writers from sharing a mutable
tree — it bounds *where* mutation happens. It says nothing about *which paths* a
given role may touch inside that tree. This module adds that second bound: a role
declares an allow-list of path globs (and optional deny globs), and a pure check
reports whether a set of changed paths stays within it.

Harvested from the Bounded Agent Organization pattern (see ADR-0010): "read
broadly; write narrowly." The scope is advisory data — enforcement is the
caller's decision — but the check itself is total and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath


def _normalize(path: str) -> str:
    """Collapse a path to a comparable POSIX-relative form.

    Backslashes become forward slashes, a leading ``./`` or ``/`` is stripped,
    and ``.``/``..`` segments are rejected so a scope cannot be escaped by
    traversal. Returns the cleaned path.
    """
    text = path.replace("\\", "/").strip()
    if not text:
        raise ValueError("path must be non-empty")
    pure = PurePosixPath(text)
    parts = [p for p in pure.parts if p not in ("", "/")]
    if any(p == ".." for p in parts):
        raise ValueError(f"path escapes scope via '..': {path!r}")
    return "/".join(p for p in parts if p != ".")


@dataclass(frozen=True, slots=True)
class WriteScope:
    """A role's declared writable surface.

    ``allowed_paths`` and ``denied_paths`` are ``fnmatch`` globs matched against
    normalized POSIX-relative paths (``**`` is treated as ``*`` by ``fnmatch``,
    so it also spans directory separators). A path is in scope when it matches at
    least one allow glob and no deny glob. Deny wins over allow.
    """

    role: str
    allowed_paths: tuple[str, ...] = ()
    denied_paths: tuple[str, ...] = field(default=())

    def permits(self, path: str) -> bool:
        """Return whether a single path is writable under this scope."""
        candidate = _normalize(path)
        if any(fnmatch(candidate, deny) for deny in self.denied_paths):
            return False
        return any(fnmatch(candidate, allow) for allow in self.allowed_paths)

    def violations(self, paths: object) -> tuple[str, ...]:
        """Return the normalized paths that fall outside this scope.

        Accepts any iterable of path strings. An empty result means every path
        is permitted. Results are order-preserving and de-duplicated.
        """
        if isinstance(paths, str):
            raise TypeError("pass an iterable of paths, not a single string")
        seen: set[str] = set()
        out: list[str] = []
        for raw in paths:
            candidate = _normalize(raw)
            if candidate in seen:
                continue
            seen.add(candidate)
            if not self.permits(candidate):
                out.append(candidate)
        return tuple(out)

    def check(self, paths: object) -> "WriteScopeCheck":
        """Evaluate a change set against this scope."""
        offending = self.violations(paths)
        return WriteScopeCheck(role=self.role, in_scope=not offending, violations=offending)


@dataclass(frozen=True, slots=True)
class WriteScopeCheck:
    """The verdict of evaluating a change set against a :class:`WriteScope`."""

    role: str
    in_scope: bool
    violations: tuple[str, ...]
