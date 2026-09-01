from datetime import UTC, datetime, timedelta

from icm_harness.execution.run_store import SQLiteRunStore


def test_expired_final_attempt_dead_letters(tmp_path):
    store = SQLiteRunStore(tmp_path / "runs.db")
    deadline = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    rec = store.start("r1", "build.writer", "w", deadline, max_attempts=1)
    recovered = store.recover_expired(datetime.now(UTC).isoformat())
    assert recovered[0].run_id == rec.run_id
    assert recovered[0].status == "dead_letter"
