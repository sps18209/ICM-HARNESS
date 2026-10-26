"""Existing Git source identity behind the candidate port."""

from pathlib import Path

from icm_harness.kernel.providers import CandidateRef
from icm_harness.workspace import candidate_identity, git_revision, protected_identity


class GitCandidateProvider:
    def capture(self, locator: str, generated_paths: tuple[str, ...] = ()) -> CandidateRef:
        root = Path(locator).resolve()
        return CandidateRef(
            str(root),
            candidate_identity(root, generated_paths),
            git_revision(root),
            generated_paths,
        )

    def fingerprint(self, ref: CandidateRef) -> str:
        return candidate_identity(Path(ref.locator), ref.generated_paths)

    def protected_identity(self, locator: str, paths: tuple[str, ...]) -> str:
        return protected_identity(Path(locator), paths)

    def assert_unchanged(self, ref: CandidateRef) -> None:
        if self.fingerprint(ref) != ref.source_digest:
            raise ValueError("candidate changed after capture")

    def resolve_artifact(self, ref: CandidateRef) -> str:
        raise ValueError("Git source identity does not establish a built artifact")
