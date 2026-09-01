import pytest

from icm_harness.context.ranking import ContextRanker
from icm_harness.kernel.contracts import ContextItem
from icm_harness.kernel.errors import ContextBudgetExceeded


def item(key, tokens, score, required=False):
    return ContextItem(
        key=key,
        content=key,
        source=key,
        tokens=tokens,
        query_relevance=score,
        stage_relevance=score,
        required=required,
        tier=1,
    )


def test_required_selected_first():
    selected = ContextRanker().select(
        [item("required", 100, 0.1, True), item("optional", 100, 1.0)], 100, 1
    )
    assert [x.key for x in selected] == ["required"]


def test_required_over_budget_fails_closed():
    with pytest.raises(ContextBudgetExceeded):
        ContextRanker().select([item("required", 101, 1, True)], 100, 1)
