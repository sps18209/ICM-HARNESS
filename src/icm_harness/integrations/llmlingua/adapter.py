"""Prompt compression adapter.

Provides a ``Compressor`` (:mod:`icm_harness.context.compression`) backed by
Microsoft LLMLingua. The ``should_compress`` policy is pure and testable; the
model-backed ``compress`` raises :class:`IntegrationUnavailable` when the
LLMLingua package is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from icm_harness.context import estimate_tokens
from icm_harness.kernel.errors import IntegrationUnavailable


@dataclass(frozen=True, slots=True)
class LLMLinguaPolicy:
    enabled: bool = False
    minimum_source_tokens: int = 12000
    target_ratio: float = 0.5

    def should_compress(self, text: str) -> bool:
        return self.enabled and estimate_tokens(text) >= self.minimum_source_tokens


class LLMLinguaCompressor:
    """Compressor backed by LLMLingua's PromptCompressor."""

    def __init__(self, policy: LLMLinguaPolicy | None = None, *, model_name: str | None = None):
        self.policy = policy or LLMLinguaPolicy()
        self.model_name = model_name
        self._compressor = None

    def _ensure(self):
        if self._compressor is not None:
            return self._compressor
        try:
            from llmlingua import PromptCompressor
        except ImportError as exc:
            raise IntegrationUnavailable(
                "Install LLMLingua: pip install llmlingua"
            ) from exc
        kwargs = {"model_name": self.model_name} if self.model_name else {}
        self._compressor = PromptCompressor(**kwargs)
        return self._compressor

    def compress(self, text: str, target_tokens: int) -> str:
        if not self.policy.should_compress(text):
            return text
        compressor = self._ensure()
        result = compressor.compress_prompt(text, target_token=target_tokens)
        if isinstance(result, dict):
            return result.get("compressed_prompt", text)
        return str(result)
