from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewerRole:
    name: str
    objective: str


DEFAULT_REVIEWERS = (
    ReviewerRole("architect", "Check system coherence, interfaces, and hidden coupling."),
    ReviewerRole("epistemic", "Check evidence quality, uncertainty, and causal validity."),
    ReviewerRole("reliability", "Check failure propagation, recovery, and testability."),
    ReviewerRole(
        "context-economist", "Check context/token economy and canonical-source discipline."
    ),
    ReviewerRole("operator", "Check human friction, control points, and usability."),
    ReviewerRole("adversary", "Construct the strongest way the proposal can fail."),
)


def select_roles(count: int) -> tuple[ReviewerRole, ...]:
    if count <= 0:
        raise ValueError("reviewer count must be positive")
    return DEFAULT_REVIEWERS[: min(count, len(DEFAULT_REVIEWERS))]
