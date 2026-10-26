"""Explicit provider composition shared by the optional clients and library callers."""

from icm_harness.application.service import HarnessApplication
from icm_harness.ports import VerificationProviders


def build_application(
    root, *, config=None, agent=None, dry_run=False, providers: VerificationProviders | None = None
) -> HarnessApplication:
    return HarnessApplication(
        root, config=config, agent=agent, dry_run=dry_run, verification_providers=providers
    )
