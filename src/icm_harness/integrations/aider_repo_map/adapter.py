"""Repo-map context provider.

Implements the core ``ContextProvider`` contract
(:mod:`icm_harness.context.retrieval`). The ranking design follows Aider's
repo-map (mention / changed-file / test-neighbor boosts); no Aider package is
required — it is a design reference, not a runtime dependency.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from icm_harness.context import estimate_tokens
from icm_harness.kernel.contracts import ContextItem

SOURCE_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".c", ".h", ".cpp"}
)
IGNORED_PARTS = frozenset({".git", ".harness", "__pycache__", "node_modules", ".venv", "out"})
_PY_SYMBOL = re.compile(r"^(?:async def|def|class)\s+[A-Za-z_]", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RepoMapPolicy:
    max_tokens: int = 4096
    mention_boost: float = 10.0
    changed_file_boost: float = 8.0
    test_neighbor_boost: float = 5.0
    activation_tier: int = 2


@dataclass
class RepoMapContextProvider:
    """Rank repository files into a token-bounded context map."""

    root: str | Path
    policy: RepoMapPolicy = field(default_factory=RepoMapPolicy)
    changed_files: frozenset[str] = frozenset()

    def retrieve(self, query: str, tier: int, stage_ref: str) -> Sequence[ContextItem]:
        root = Path(self.root)
        if tier < self.policy.activation_tier or not root.exists():
            return ()
        changed_stems = {Path(name).stem for name in self.changed_files}
        query_terms = {term.lower() for term in re.split(r"\W+", query) if len(term) > 2}

        scored: list[tuple[float, ContextItem]] = []
        for path in sorted(root.rglob("*")):
            if not self._is_source(path, root):
                continue
            rel = path.relative_to(root).as_posix()
            score = self._score(path, rel, query_terms, changed_stems)
            if score <= 1.0:
                continue
            content = self._map_file(path)
            scored.append(
                (
                    score,
                    ContextItem(
                        key=rel,
                        content=content,
                        source=str(path),
                        tokens=estimate_tokens(content),
                        graph_relevance=min(1.0, score / self._max_score()),
                        stage_relevance=0.4,
                        authority=0.5,
                        tier=self.policy.activation_tier,
                        metadata={"repo_map_score": score},
                    ),
                )
            )

        scored.sort(key=lambda pair: pair[0], reverse=True)
        chosen: list[ContextItem] = []
        used = 0
        for _, item in scored:
            if used + item.tokens > self.policy.max_tokens:
                continue
            chosen.append(item)
            used += item.tokens
        return tuple(chosen)

    def _is_source(self, path: Path, root: Path) -> bool:
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            return False
        return not any(part in IGNORED_PARTS for part in path.relative_to(root).parts)

    def _score(
        self,
        path: Path,
        rel: str,
        query_terms: set[str],
        changed_stems: set[str],
    ) -> float:
        score = 1.0
        stem = path.stem.lower()
        if any(term in stem or term in rel.lower() for term in query_terms):
            score += self.policy.mention_boost
        if rel in self.changed_files:
            score += self.policy.changed_file_boost
        if self._is_test(path) and changed_stems:
            target = stem.removeprefix("test_").removesuffix("_test")
            if target in changed_stems:
                score += self.policy.test_neighbor_boost
        return score

    @staticmethod
    def _is_test(path: Path) -> bool:
        name = path.stem.lower()
        return name.startswith("test_") or name.endswith("_test") or "tests" in path.parts

    def _map_file(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".py":
            symbols = [line.strip() for line in text.splitlines() if _PY_SYMBOL.match(line)]
            if symbols:
                return f"# {path.name}\n" + "\n".join(symbols[:40]) + "\n"
        head = "\n".join(text.splitlines()[:20])
        return f"# {path.name}\n{head}\n"

    def _max_score(self) -> float:
        return (
            1.0
            + self.policy.mention_boost
            + self.policy.changed_file_boost
            + self.policy.test_neighbor_boost
        )
