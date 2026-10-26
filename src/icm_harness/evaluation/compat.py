"""Legacy local verification composition boundary; orchestration stays provider-neutral."""

from icm_harness.adapters.candidates.git_source import GitCandidateProvider
from icm_harness.adapters.execution.local import LocalExecutionProvider
from icm_harness.adapters.storage.filesystem import FilesystemEvidenceStore
from icm_harness.adapters.verifiers.junit import JUnitVerifier
from icm_harness.adapters.verifiers.pytest_events import PytestEventVerifier
from icm_harness.evaluation.runner import verify_with_providers
from icm_harness.ports import VerificationProviders


def local_verification_providers(evidence_root=None) -> VerificationProviders:
    return VerificationProviders(
        LocalExecutionProvider(),
        GitCandidateProvider(),
        {
            "junit": JUnitVerifier(),
            "pytest_events": PytestEventVerifier(),
        },
        FilesystemEvidenceStore(evidence_root / "store") if evidence_root is not None else None,
    )


async def verify_candidate(
    profile,
    root,
    evidence_root,
    cancel_requested=lambda: False,
    total_timeout_seconds=1800,
    *,
    providers=None,
):
    return await verify_with_providers(
        profile,
        root,
        evidence_root,
        cancel_requested,
        total_timeout_seconds,
        providers=providers
        if providers is not None
        else local_verification_providers(evidence_root),
    )
