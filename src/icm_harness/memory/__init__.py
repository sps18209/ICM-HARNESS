"""Public interface (barrel) for the ``memory`` module.

Other modules must import these symbols from ``icm_harness.memory`` — never from
this module's private submodules. The boundary is enforced in CI by
``scripts/validate_architecture.py``. Imports are resolved lazily (PEP 562) so
declaring the barrel never triggers eager submodule import cycles.
"""
from __future__ import annotations

import importlib
from typing import Any

_PUBLIC: dict[str, str] = {
    "MemoryRecord": "store",
    "SQLiteMemoryStore": "store",
}

__all__ = sorted(_PUBLIC)


def __getattr__(name: str) -> Any:
    module = _PUBLIC.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"icm_harness.memory.{module}"), name)


def __dir__() -> list[str]:
    return list(__all__)
