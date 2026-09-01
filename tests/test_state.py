import pytest

from icm_harness.kernel.errors import InvalidTransition, LeaseUnavailable
from icm_harness.kernel.state import SQLiteStateStore


def test_optimistic_versioning(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.db")
    rec = state.create_round("r1", "x", ["build"], ["build.planner", "build.writer"])
    nxt = state.advance("r1", rec.version)
    assert nxt.current_stage == "build.writer"
    with pytest.raises(InvalidTransition):
        state.advance("r1", rec.version)


def test_lease_exclusion(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.db")
    state.acquire_lease("repo:x:write", "a", 60)
    with pytest.raises(LeaseUnavailable):
        state.acquire_lease("repo:x:write", "b", 60)
    state.release_lease("repo:x:write", "a")
    state.acquire_lease("repo:x:write", "b", 60)
    assert state.lease_owner("repo:x:write") == "b"
