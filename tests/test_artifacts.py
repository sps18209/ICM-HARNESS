import pytest

from icm_harness.application.artifacts import ArtifactStore
from icm_harness.kernel.state import SQLiteStateStore


def test_artifact_names_cannot_escape_round_store(tmp_path):
    state = SQLiteStateStore(tmp_path / ".harness/runtime/state.sqlite3")
    store = ArtifactStore(tmp_path, state)
    with pytest.raises(ValueError):
        store.write_many("r-safe", "build.planner", {"../escape.md": "no"})


def test_json_artifacts_must_be_valid_json(tmp_path):
    state = SQLiteStateStore(tmp_path / ".harness/runtime/state.sqlite3")
    store = ArtifactStore(tmp_path, state)
    with pytest.raises(ValueError):
        store.write_many("r-safe", "build.planner", {"manifest.json": "not-json"})
