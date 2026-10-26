"""Regression attacks against required-test identity and execution evidence."""

from __future__ import annotations

import json
import sys

import anyio
import pytest
from verification_support import configure_acceptance, initialize_verified_repo

from icm_harness.evaluation import load_profile, parse_profile, verify_candidate
from icm_harness.evaluation.test_evidence import validate_outcomes
from icm_harness.workspace import protected_identity


def pytest_project(root):
    initialize_verified_repo(root)
    (root / "test_acceptance.py").write_text(
        "def test_required():\n    assert False\n\ndef test_other():\n    assert True\n"
    )
    payload = configure_acceptance(root)
    payload["schema_version"] = 2
    payload["inherit_environment"] = ["PATH", "HOME", "PYTHONPATH"]
    payload["checks"][0].update(
        argv=[sys.executable, "-m", "icm_harness.evaluation.pytest_runner",
              "--report", ".harness/runtime/events.json", "--", "test_acceptance.py", "-q"],
        result_format="pytest_events",
        report=".harness/runtime/events.json",
        expected_tests=["test_acceptance.py::test_required", "test_acceptance.py::test_other"],
    )
    return payload


def verify(root, payload):
    return anyio.run(verify_candidate, parse_profile(payload), root, root / ".harness/rounds")


@pytest.mark.parametrize("attack", ["skip", "deselect", "replace", "xfail", "xfail_norun"])
def test_collection_hook_cannot_hide_a_required_failure(tmp_path, attack):
    payload = pytest_project(tmp_path)
    baseline = verify(tmp_path, payload)
    assert not baseline["passed"]
    original = (tmp_path / "test_acceptance.py").read_bytes()
    if attack == "deselect":
        hook = (
            "def pytest_collection_modifyitems(config, items):\n"
            "    gone = [i for i in items if i.name == 'test_required']\n"
            "    items[:] = [i for i in items if i not in gone]\n"
            "    config.hook.pytest_deselected(items=gone)\n"
        )
    elif attack == "replace":
        hook = (
            "def pytest_collection_modifyitems(items):\n"
            "    items[:] = [i for i in items if i.name != 'test_required']\n"
        )
    else:
        marker = {
            "skip": "pytest.mark.skip(reason='hide failure')",
            "xfail": "pytest.mark.xfail(reason='hide failure')",
            "xfail_norun": "pytest.mark.xfail(reason='hide failure', run=False)",
        }[attack]
        hook = (
            "import pytest\n"
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            f"        if item.name == 'test_required': item.add_marker({marker})\n"
        )
    (tmp_path / "conftest.py").write_text(hook)
    report = verify(tmp_path, payload)
    assert not report["passed"]
    assert report["requirements"][0]["status"] == "failed"
    assert (tmp_path / "test_acceptance.py").read_bytes() == original
    assert report["commands"][0]["tests"]["errors"]


def test_only_named_optional_skip_is_accepted(tmp_path):
    payload = pytest_project(tmp_path)
    (tmp_path / "test_acceptance.py").write_text(
        "import pytest\n"
        "@pytest.mark.skip(reason='requires account')\n"
        "def test_required(): pass\n"
        "def test_other(): assert True\n"
    )
    assert not verify(tmp_path, payload)["passed"]
    payload["checks"][0]["optional_skips"] = {
        "test_acceptance.py::test_required": "Owner-approved account smoke test"
    }
    report = verify(tmp_path, payload)
    assert report["passed"]
    assert report["commands"][0]["tests"]["optional_skips"][0]["reason"].startswith("Owner")


def test_ambient_pytest_options_and_plugins_cannot_change_collection(tmp_path, monkeypatch):
    payload = pytest_project(tmp_path)
    payload["inherit_environment"] += ["PYTEST_ADDOPTS", "PYTEST_PLUGINS"]
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k test_other")
    monkeypatch.setenv("PYTEST_PLUGINS", "nonexistent_plugin")
    report = verify(tmp_path, payload)
    assert report["commands"][0]["tests"]["total"] == 2
    assert not report["passed"]
    (tmp_path / "test_acceptance.py").write_text(
        "def test_required(): assert True\ndef test_other(): assert True\n"
    )
    assert verify(tmp_path, payload)["passed"]


def phase_data():
    return {
        "schema_version": 1, "collected": ["required"], "deselected": [],
        "collection_errors": [], "exit_code": 0,
        "events": [{"nodeid": "required", "when": phase, "outcome": "passed", "wasxfail": False}
                   for phase in ("setup", "call", "teardown")],
    }


@pytest.mark.parametrize("attack", ["missing_call", "duplicate", "xfail", "teardown", "unknown"])
def test_phase_omissions_and_ambiguous_reports_fail_closed(attack):
    data = phase_data()
    assert validate_outcomes(("required",), {}, data)["passed"]
    if attack == "missing_call":
        data["events"].pop(1)
    elif attack == "duplicate":
        data["events"].append(dict(data["events"][1]))
    elif attack == "xfail":
        data["events"][1]["wasxfail"] = True
    elif attack == "teardown":
        data["events"][2]["outcome"] = "skipped"
    else:
        data["events"][1]["nodeid"] = "uncollected"
    assert not validate_outcomes(("required",), {}, data)["passed"]


def test_manifest_is_expanded_and_frozen_before_writer_runs(tmp_path):
    payload = pytest_project(tmp_path)
    check = payload["checks"][0]
    manifest = {"schema_version": 1, "tests": check.pop("expected_tests"), "optional_skips": {}}
    check["test_manifest"] = ".harness/tests.json"
    (tmp_path / ".harness/tests.json").write_text(json.dumps(manifest))
    (tmp_path / ".harness/project.json").write_text(json.dumps(payload))
    captured = load_profile(tmp_path)
    assert ".harness/tests.json" in captured.protected_paths
    manifest["tests"] = ["replacement"]
    (tmp_path / ".harness/tests.json").write_text(json.dumps(manifest))
    assert parse_profile(captured.payload()).checks[0].expected_tests == (
        "test_acceptance.py::test_required", "test_acceptance.py::test_other"
    )


def test_ignored_protected_input_mutation_invalidates_verification(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    protected = tmp_path / ".harness/runtime/evaluator.cfg"
    protected.parent.mkdir(parents=True)
    protected.write_text("baseline")
    payload["protected_paths"] = [".harness/runtime/evaluator.cfg"]
    payload["checks"][0]["argv"] = [
        sys.executable, "-c",
        "from pathlib import Path; Path('.harness/runtime/evaluator.cfg').write_text('changed')",
    ]
    report = verify(tmp_path, payload)
    assert not report["passed"]
    assert report["failure_class"] == "evaluator_changed"


def test_protected_symlink_cannot_hide_target_changes(tmp_path):
    (tmp_path / "actual").write_text("trusted")
    (tmp_path / "alias").symlink_to("actual")
    with pytest.raises(ValueError, match="must not use symlinks"):
        protected_identity(tmp_path, ("alias",))


@pytest.mark.parametrize(
    "attack", ["blanket", "empty", "duplicate", "unknown_optional", "no_reason"]
)
def test_unsafe_report_profiles_are_rejected(tmp_path, attack):
    payload = pytest_project(tmp_path)
    check = payload["checks"][0]
    if attack == "blanket":
        check["allow_skips"] = True
    elif attack == "empty":
        check["expected_tests"] = []
    elif attack == "duplicate":
        check["expected_tests"] *= 2
    elif attack == "unknown_optional":
        check["optional_skips"] = {"unknown": "reason"}
    else:
        check["optional_skips"] = {check["expected_tests"][0]: ""}
    with pytest.raises(ValueError):
        parse_profile(payload)
