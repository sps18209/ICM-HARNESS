"""Model gateway adapter (Portkey).

Builds provider-agnostic chat-completion requests and routes them through a
Portkey gateway. Payload construction is pure and testable; the network call
raises :class:`IntegrationUnavailable` when no HTTP client is available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PortkeyGatewayConfig:
    base_url: str = "http://localhost:8787/v1"
    timeout_seconds: float = 60.0
    max_retries: int = 3


class PortkeyGateway:
    def __init__(self, config: PortkeyGatewayConfig | None = None, *, api_key: str | None = None):
        self.config = config or PortkeyGatewayConfig()
        self.api_key = api_key

    def build_request(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        return body

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-portkey-api-key"] = self.api_key
        return headers

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:
            from icm_harness.kernel.errors import IntegrationUnavailable

            raise IntegrationUnavailable("Install httpx to call the Portkey gateway") from exc
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        response = httpx.post(
            url,
            headers=self._headers(),
            content=json.dumps(request),
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
