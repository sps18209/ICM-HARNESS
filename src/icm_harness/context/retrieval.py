from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from icm_harness.context.budgets import estimate_tokens
from icm_harness.kernel.contracts import ContextItem


class ContextProvider(Protocol):
    def retrieve(self, query: str, tier: int, stage_ref: str) -> Sequence[ContextItem]: ...


class FilesystemWikiProvider:
    def __init__(self, wiki_root: str | Path):
        self.root = Path(wiki_root)

    def retrieve(self, query: str, tier: int, stage_ref: str) -> Sequence[ContextItem]:
        if tier < 1 or not self.root.exists():
            return ()
        q_terms = {term.lower() for term in query.split() if len(term) > 2}
        items = []
        for path in sorted(self.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            lower = text.lower()
            hits = sum(1 for term in q_terms if term in lower)
            relevance = min(1.0, hits / max(1, len(q_terms)))
            if relevance == 0 and tier < 3:
                continue
            items.append(
                ContextItem(
                    key=str(path.relative_to(self.root)),
                    content=text,
                    source=str(path),
                    tokens=estimate_tokens(text),
                    query_relevance=relevance,
                    stage_relevance=0.5,
                    authority=1.0,
                    tier=1,
                )
            )
        return items
