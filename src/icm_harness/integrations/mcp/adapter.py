"""Model Context Protocol adapter.

Thin wrapper over the official MCP Python SDK for connecting to tool servers and
listing/invoking their tools. Raises :class:`IntegrationUnavailable` when the
SDK is not installed. Tool authorization stays with the policies layer; this
adapter only transports.
"""

from __future__ import annotations

from dataclasses import dataclass


def require_mcp_sdk():
    try:
        import mcp
    except ImportError as exc:
        from icm_harness.kernel.errors import IntegrationUnavailable

        raise IntegrationUnavailable("Official MCP Python SDK is not installed") from exc
    return mcp


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    command: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


class MCPToolProvider:
    """Connect to a stdio MCP server and enumerate its tools."""

    def __init__(self, config: MCPServerConfig, *, session: object | None = None):
        self.config = config
        self._session = session

    async def list_tools(self) -> list[dict]:
        session = self._session
        if session is None:
            require_mcp_sdk()
            from icm_harness.kernel.errors import IntegrationUnavailable

            raise IntegrationUnavailable(
                "MCP session is not connected; inject a live ClientSession"
            )
        result = await session.list_tools()  # type: ignore[attr-defined]
        tools = getattr(result, "tools", result)
        return [{"name": t.name, "description": getattr(t, "description", "")} for t in tools]
