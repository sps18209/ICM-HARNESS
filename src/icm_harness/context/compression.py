from typing import Protocol


class Compressor(Protocol):
    def compress(self, text: str, target_tokens: int) -> str: ...


class NoOpCompressor:
    def compress(self, text: str, target_tokens: int) -> str:
        return text
