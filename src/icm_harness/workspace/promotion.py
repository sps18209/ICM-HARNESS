from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    destination: str
    content: str
    evidence_ref: str
    verified: bool


class ContextPromoter:
    def __init__(self, wiki_root: str | Path):
        self.root = Path(wiki_root)

    def promote(
        self,
        candidate: PromotionCandidate,
        *,
        duplicate_check: Callable[[str, str], bool] | None = None,
    ) -> Path:
        if not candidate.verified:
            raise ValueError("unverified content cannot enter durable context")
        target = self.root / candidate.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if duplicate_check and duplicate_check(existing, candidate.content):
            return target
        with target.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(candidate.content.rstrip() + "\n")
            handle.write(f"\nSource round/evidence: {candidate.evidence_ref}\n")
        return target
