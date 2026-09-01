import pytest

from icm_harness.workspace.promotion import ContextPromoter, PromotionCandidate


def test_unverified_context_cannot_be_promoted(tmp_path):
    with pytest.raises(ValueError):
        ContextPromoter(tmp_path).promote(PromotionCandidate("architecture.md", "x", "r1", False))
