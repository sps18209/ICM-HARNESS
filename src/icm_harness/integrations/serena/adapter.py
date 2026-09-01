"""Symbolic code retrieval adapter (Serena).

Provides a ``ContextProvider`` (:mod:`icm_harness.context.retrieval`) backed by
Serena's language-server-driven symbol search, exposed over MCP. Raises
:class:`IntegrationUnavailable` when the MCP client stack is not installed.
Planner stages use it read-only; the writer may use symbolic editing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from icm_harness.context.budgets import estimate_tokens
from icm_harness.kernel.contracts import ContextItem


@dataclass(frozen=True, slots=True)
class SerenaConfig:
    command: tuple[str, ...] = ("serena", "start-mcp-server")
    planner_read_only: bool = True
    writer_symbolic_editing: bool = True
    activation_tier: int = 2


@dataclass
class SerenaContextProvider:
    config: SerenaConfig = field(default_factory=SerenaConfig)
    session: object | None = None

    def _ensure_session(self):
        if self.session is not None:
            return self.session
        try:
            import mcp  # noqa: F401
        except ImportError as exc:
            from icm_harness.kernel.errors import IntegrationUnavailable

            raise IntegrationUnavailable(
                "Serena retrieval requires the MCP client: pip install mcp"
            ) from exc
        raise IntegrationUnavailable(
            "Serena MCP session is not connected; inject a live session"
        )

    def retrieve(self, query: str, tier: int, stage_ref: str) -> Sequence[ContextItem]:
        if tier < self.config.activation_tier:
            return ()
        session = self._ensure_session()
        symbols = session.find_symbols(query)  # type: ignore[attr-defined]
        return tuple(
            ContextItem(
                key=symbol["name"],
                content=symbol.get("body", ""),
                source=symbol.get("path", "serena"),
                tokens=estimate_tokens(symbol.get("body", "")),
                graph_relevance=float(symbol.get("relevance", 0.6)),
                stage_relevance=0.5,
                authority=0.7,
                tier=self.config.activation_tier,
            )
            for symbol in symbols
        )
