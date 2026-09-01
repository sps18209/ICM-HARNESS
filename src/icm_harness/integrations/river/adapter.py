"""Online-learning routing adapter (River).

Wraps River's Thompson-sampling bandit as an alternative exploration policy for
model routing. The in-tree :class:`BayesianPerformanceStore` remains the default;
this adapter is opt-in and raises :class:`IntegrationUnavailable` when River is
not installed.
"""

from __future__ import annotations


def make_thompson_policy():
    try:
        from river import bandit
    except ImportError as exc:
        from icm_harness.kernel.errors import IntegrationUnavailable

        raise IntegrationUnavailable(
            "Install extras: pip install 'icm-production-harness[ml]'"
        ) from exc
    return bandit.ThompsonSampling()


class RiverBanditPolicy:
    """Pick and reward model arms with a River bandit."""

    def __init__(self, arms: list[str], policy=None):
        if not arms:
            raise ValueError("at least one arm is required")
        self.arms = list(arms)
        self._policy = policy or make_thompson_policy()

    def choose(self) -> str:
        arm = self._policy.pull(self.arms)
        return arm if isinstance(arm, str) else self.arms[int(arm)]

    def update(self, arm: str, reward: float) -> None:
        self._policy.update(arm, reward)
