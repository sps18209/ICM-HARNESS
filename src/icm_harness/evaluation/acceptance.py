"""One deterministic acceptance policy, shared by all execution providers."""

from dataclasses import asdict

from icm_harness.kernel.providers import AcceptanceDecision
from icm_harness.kernel.verification import ProjectProfile


def decide_acceptance(profile: ProjectProfile, commands: list[dict], failure: str | None):
    outcomes = {item["id"]: item["passed"] for item in commands if item["phase"] == "checks"}
    requirements = tuple(
        {
            **asdict(req),
            "status": "verified"
            if all(outcomes.get(c) for c in req.checks)
            else "failed"
            if any(c in outcomes and not outcomes[c] for c in req.checks)
            else "untested",
        }
        for req in profile.requirements
    )
    if failure in {"environment", "cancelled", "unsupported_capability"}:
        status = "blocked"
    elif failure or any(item["status"] != "verified" for item in requirements):
        status = "rejected"
    else:
        status = "accepted"
    reasons = (failure,) if failure else (() if status == "accepted" else ("requirements_unmet",))
    return AcceptanceDecision(status, reasons, requirements)
