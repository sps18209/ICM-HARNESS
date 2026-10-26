"""Acceptance exercises for the full requirements -> evidence -> promotion path."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from verification_support import configure_acceptance, git, initialize_verified_repo

from icm_harness.agents.prompting import render_stage_prompt
from icm_harness.application import HarnessApplication
from icm_harness.config import load_config, write_default_config
from icm_harness.evaluation import parse_profile, verify_candidate
from icm_harness.kernel.contracts import StageResult, StageStatus, TaskIntent, TaskProfile
from icm_harness.workspace import candidate_identity


class ProductAgent:
    def __init__(self, *, repair=True, close_edit=False, protected_edit=False, empty=False):
        self.repair = repair
        self.close_edit = close_edit
        self.protected_edit = protected_edit
        self.empty = empty
        self.calls = []

    async def run(self, inv):
        self.calls.append(inv)
        if inv.stage.ref in {"build.writer", "quick.execute"}:
            writers = sum(i.stage.ref == inv.stage.ref for i in self.calls)
            value = "correct" if self.repair and writers > 1 else "wrong"
            (inv.workspace / "product.txt").write_text(value)
            if self.protected_edit:
                (inv.workspace / "acceptance.py").write_text("pass")
        if inv.stage.ref.endswith(".close") and self.close_edit:
            (inv.workspace / "product.txt").write_text("untested edit")
        artifacts = {
            name: ("{}" if name.endswith(".json") else f"# {inv.stage.ref}")
            for name in inv.stage.required_outputs
        }
        if self.empty:
            artifacts = dict.fromkeys(artifacts, "")
        return StageResult(StageStatus.PASS, "claimed success", artifacts=artifacts)


def project(root, agent=None, *, intent=TaskIntent.BUILD, protected=False):
    write_default_config(root / ".harness/config.toml")
    initialize_verified_repo(root)
    profile = configure_acceptance(root, "assert Path('product.txt').read_text() == 'correct'")
    if protected:
        (root / "acceptance.py").write_text("assert True\n")
        profile["protected_paths"] = ["acceptance.py"]
    (root / ".harness/project.json").write_text(json.dumps(profile))
    git(root, "add", ".")
    git(root, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "profile")
    agent = agent or ProductAgent()
    cfg = load_config(root)
    cfg = replace(cfg, runtime=replace(cfg.runtime, max_stage_transitions=10))
    app = HarnessApplication(root, config=cfg, agent=agent)
    task = TaskProfile(
        "Create the correct product",
        intent=intent,
        specification_clarity=0.9,
        epistemic_uncertainty=0.1,
        production_change_required=True,
    )
    rec = app.create_round(task)
    return app, rec, agent


def test_false_success_is_rejected_by_real_command(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(repair=False))
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    evidence = [e.payload for e in app.events(rec.round_id) if e.kind == "candidate_verified"]
    assert evidence and all(not e["passed"] for e in evidence)
    assert evidence[0]["commands"][0]["exit_code"] != 0
    assert evidence[0]["requirements"][0]["status"] == "failed"
    assert not any(e.kind == "merge_approved" for e in app.events(rec.round_id))


def test_repair_gets_original_contract_plan_and_failure_then_promotes_exact_candidate(tmp_path):
    app, rec, agent = project(tmp_path)
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "closed"
    writer_calls = [i for i in agent.calls if i.stage.ref == "build.writer"]
    assert len(writer_calls) == 2
    handoff = render_stage_prompt(writer_calls[1])
    assert "FIXTURE-1" in handoff and "execution-plan.md" in handoff
    assert "AssertionError" in handoff and "wrong" not in (tmp_path / "README.md").read_text()
    assert writer_calls[1].context.tier == 3
    assert not (tmp_path / "product.txt").exists()
    reports = [e.payload for e in app.events(rec.round_id) if e.kind == "candidate_verified"]
    assert [r["passed"] for r in reports] == [False, True]
    app.approve_promotion(rec.round_id)
    app.promote_round(rec.round_id)
    assert (tmp_path / "product.txt").read_text() == "correct"
    assert app.performance.posterior("default", "build.writer", "code", 0.8).observations == 2


def test_empty_current_outputs_cannot_reuse_previous_attempt(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(empty=True))
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    assert "current attempt" in result.last_error


def test_profile_is_captured_before_agents_and_survives_process_restart(tmp_path):
    app, rec, agent = project(tmp_path)
    replacement = json.loads((tmp_path / ".harness/project.json").read_text())
    replacement["checks"][0]["argv"] = [sys.executable, "-c", "pass"]
    (tmp_path / ".harness/project.json").write_text(json.dumps(replacement))
    # A fresh application loads the profile from the original round event, not disk.
    restarted = HarnessApplication(tmp_path, config=app.config, agent=agent)
    result = anyio.run(restarted.run_round, rec.round_id)
    assert result.status == "closed"
    reports = [e.payload for e in restarted.events(rec.round_id) if e.kind == "candidate_verified"]
    assert [r["passed"] for r in reports] == [False, True]


def test_missing_profile_blocks_actual_acceptance(tmp_path):
    app, _, agent = project(tmp_path)
    (tmp_path / ".harness/project.json").unlink()
    rec = app.create_round(
        TaskProfile(
            "build", intent=TaskIntent.BUILD, specification_clarity=0.9, epistemic_uncertainty=0.1
        )
    )
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "blocked"
    assert "No captured acceptance profile" in result.last_error
    assert agent.calls


def test_protected_acceptance_inputs_cannot_be_weakened(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(protected_edit=True), protected=True)
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    assert "protected acceptance inputs changed" in result.last_error


def test_absent_protected_configuration_cannot_be_added_by_writer(tmp_path):
    class ConfigWriter(ProductAgent):
        async def run(self, inv):
            result = await super().run(inv)
            if inv.stage.ref == "build.writer":
                (inv.workspace / "conftest.py").write_text("# alter evaluator collection\n")
            return result

    app, _, _ = project(tmp_path, ConfigWriter())
    path = tmp_path / ".harness/project.json"
    payload = json.loads(path.read_text())
    payload["protected_paths"] = ["conftest.py"]
    path.write_text(json.dumps(payload))
    git(tmp_path, "add", ".harness/project.json")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "guard")
    rec = app.create_round(TaskProfile(
        "build", intent=TaskIntent.BUILD, specification_clarity=0.9, epistemic_uncertainty=0.1
    ))
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    assert "protected acceptance inputs changed" in result.last_error


def test_close_cannot_edit_tested_product(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(close_edit=True))
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    with pytest.raises(ValueError, match="must be closed"):
        app.approve_promotion(rec.round_id)


@pytest.mark.parametrize("after_approval", [False, True])
def test_post_verification_edits_block_approval_and_promotion(tmp_path, after_approval):
    app, rec, _ = project(tmp_path)
    result = anyio.run(app.run_round, rec.round_id)
    if after_approval:
        app.approve_promotion(rec.round_id)
    (Path(result.workspace_path) / "product.txt").write_text("changed")
    with pytest.raises(ValueError, match="candidate changed"):
        (app.promote_round if after_approval else app.approve_promotion)(rec.round_id)
    assert not (tmp_path / "product.txt").exists()


def test_destination_movement_requires_new_verification(tmp_path):
    app, rec, _ = project(tmp_path)
    anyio.run(app.run_round, rec.round_id)
    app.approve_promotion(rec.round_id)
    (tmp_path / "new-base.txt").write_text("destination moved")
    git(tmp_path, "add", "new-base.txt")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "advance")
    with pytest.raises(ValueError, match="destination changed"):
        app.promote_round(rec.round_id)


def test_quick_mode_also_requires_executable_checks(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(repair=False), intent=TaskIntent.QUICK)
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed"
    assert "Executable verification failed" in result.last_error


@pytest.mark.parametrize(
    "xml,allow_skips,expected",
    [
        ('<testsuite/>', False, False),
        ('<testsuite><testcase name="optional"><skipped/></testcase></testsuite>', True, False),
        ('<testsuite><testcase name="required"/>'
         '<testcase name="optional"><skipped/></testcase></testsuite>', False, False),
        ('<testsuite><testcase name="required"/>'
         '<testcase name="optional"><skipped/></testcase></testsuite>', True, True),
        ('<testsuite><testcase name="optional"><failure/></testcase></testsuite>', False, False),
        ('<testsuite errors="1"><testcase name="required"/></testsuite>', False, False),
        ('<testsuite><testcase name="required"/></testsuite>', False, True),
    ],
)
def test_junit_counts_and_skips_are_evidence_not_exit_code_only(
    tmp_path, xml, allow_skips, expected
):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0].update(
        argv=[
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "p=Path('.harness/runtime/result.xml'); p.parent.mkdir(parents=True,exist_ok=True); "
            f"p.write_text({xml!r})",
        ],
        result_format="junit",
        report=".harness/runtime/result.xml",
        expected_tests=[f"::{name}" for name in ("required", "optional") if f'name="{name}"' in xml]
        or ["::required"],
        optional_skips={"::optional": "Optional fixture"} if allow_skips else {},
    )
    report = anyio.run(
        verify_candidate, parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
    )
    assert report["passed"] is expected
    assert "total" in report["commands"][0]["tests"]


def test_stale_junit_cannot_supply_success_for_a_command_that_writes_nothing(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0].update(
        argv=[sys.executable, "-c", "pass"],
        result_format="junit",
        report=".harness/runtime/result.xml",
        expected_tests=["::required"],
    )
    output = tmp_path / ".harness/runtime/result.xml"
    output.parent.mkdir(parents=True)
    output.write_text('<testsuite><testcase name="required"/></testsuite>')
    report = anyio.run(
        verify_candidate, parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
    )
    assert not report["passed"]
    assert "missing" in report["commands"][0]["error"]


def test_check_cannot_modify_candidate_and_certify_it(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0]["argv"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('README.md').write_text('new')",
    ]
    report = anyio.run(
        verify_candidate, parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
    )
    assert not report["passed"] and report["failure_class"] == "candidate_changed"


def test_timeout_kills_descendants_and_runs_teardown(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    child = (
        "import time; from pathlib import Path; time.sleep(.5); Path('escaped').write_text('bad')"
    )
    payload["checks"][0].update(
        argv=[
            sys.executable,
            "-c",
            "import subprocess,time,sys; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)",
        ],
        timeout_seconds=0.1,
    )
    payload["teardown"] = [{"id": "cleanup", "argv": [sys.executable, "-c", "print('cleaned')"]}]

    async def scenario():
        report = await verify_candidate(
            parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
        )
        await anyio.sleep(0.6)
        assert not (tmp_path / "escaped").exists()
        return report

    report = anyio.run(scenario)
    assert not report["passed"]
    assert "TimeoutError" in report["commands"][0]["error"]
    assert report["commands"][-1]["phase"] == "teardown"


def test_environment_failure_is_blocked_and_does_not_repeat_writer(tmp_path):
    app, _, agent = project(tmp_path)
    payload = json.loads((tmp_path / ".harness/project.json").read_text())
    payload["ready"] = [
        {"id": "db-ready", "argv": [sys.executable, "-c", "raise OSError('db down')"]}
    ]
    (tmp_path / ".harness/project.json").write_text(json.dumps(payload))
    git(tmp_path, "add", ".harness/project.json")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "ready")
    rec = app.create_round(
        TaskProfile(
            "build", intent=TaskIntent.BUILD, specification_clarity=0.9, epistemic_uncertainty=0.1
        )
    )
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "blocked"
    assert len([i for i in agent.calls if i.stage.ref == "build.writer"]) == 1


def test_ignored_tracked_files_are_still_fingerprinted(tmp_path):
    initialize_verified_repo(tmp_path)
    before = candidate_identity(tmp_path, ("README.md",))
    (tmp_path / "README.md").write_text("changed")
    assert candidate_identity(tmp_path, ("README.md",)) != before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p["checks"][0].update(argv="python -m pytest"),
        lambda p: p["checks"][0].update(timeout_seconds=float("inf")),
        lambda p: p["requirements"][0].update(checks=["nonexistent"]),
        lambda p: p.update(generated_paths=["../source"]),
    ],
)
def test_invalid_profiles_are_rejected_before_execution(tmp_path, mutate):
    (tmp_path / ".harness").mkdir()
    payload = configure_acceptance(tmp_path)
    mutate(payload)
    with pytest.raises(ValueError):
        parse_profile(payload)


def test_operator_cancellation_stops_verification_and_tears_down(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0]["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
    payload["teardown"] = [{"id": "cleanup", "argv": [sys.executable, "-c", "print('done')"]}]

    async def scenario():
        cancelled = False

        async def request():
            nonlocal cancelled
            await anyio.sleep(0.15)
            cancelled = True

        async with anyio.create_task_group() as group:
            group.start_soon(request)
            report = await verify_candidate(
                parse_profile(payload), tmp_path, tmp_path / ".harness/rounds", lambda: cancelled
            )
        return report

    report = anyio.run(scenario)
    assert not report["passed"] and report["failure_class"] == "cancelled"
    assert report["commands"][-1]["id"] == "cleanup"


def test_total_verification_budget_is_enforced(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0]["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]

    async def scenario():
        return await verify_candidate(
            parse_profile(payload),
            tmp_path,
            tmp_path / ".harness/rounds",
            total_timeout_seconds=0.1,
        )

    report = anyio.run(scenario)
    assert not report["passed"] and "total time budget" in report["error"]


def test_junit_output_cannot_destroy_a_tracked_input(tmp_path):
    initialize_verified_repo(tmp_path)
    payload = configure_acceptance(tmp_path)
    payload["checks"][0].update(
        result_format="junit", report="README.md", expected_tests=["::required"]
    )
    original = (tmp_path / "README.md").read_text()
    report = anyio.run(
        verify_candidate, parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
    )
    assert not report["passed"]
    assert "tracked product input" in report["commands"][0]["error"]
    assert (tmp_path / "README.md").read_text() == original


def test_stale_artifacts_cannot_satisfy_a_new_attempt(tmp_path):
    app, rec, _ = project(tmp_path, ProductAgent(empty=True))
    app.artifacts.write_many(
        rec.round_id,
        "build.planner",
        {
            "execution-plan.md": "old",
            "context-manifest.json": "{}",
        },
    )
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed" and "current attempt" in result.last_error


def test_simulation_is_not_promotable_even_without_the_dry_run_flag(tmp_path):
    from icm_harness.agents import DryRunStageAgent

    app, _, _ = project(tmp_path)
    simulated = HarnessApplication(tmp_path, agent=DryRunStageAgent(), config=app.config)
    rec = simulated.create_round(TaskProfile("simulated", intent=TaskIntent.QUICK))
    result = anyio.run(simulated.run_round, rec.round_id)
    assert result.status == "closed" and simulated.dry_run
    with pytest.raises(ValueError, match="simulated"):
        simulated._accepted_candidate(result)


def test_in_place_tester_mutation_is_detected(tmp_path):
    class EditingTester(ProductAgent):
        async def run(self, inv):
            result = await super().run(inv)
            if inv.stage.ref == "build.tester":
                (inv.workspace / "README.md").write_text(str(len(self.calls)))
            return result

    app, rec, agent = project(tmp_path, EditingTester())
    config = replace(app.config, workspace=replace(app.config.workspace, strategy="in_place"))
    app = HarnessApplication(tmp_path, config=config, agent=agent)
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "failed" and "non-mutating stage" in result.last_error


def test_generated_untracked_outputs_are_not_promoted(tmp_path):
    app, _, agent = project(tmp_path)
    profile_path = tmp_path / ".harness/project.json"
    payload = json.loads(profile_path.read_text())
    payload["generated_paths"] = ["results"]
    payload["checks"][0]["argv"][-1] += (
        "; Path('results').mkdir(exist_ok=True); Path('results/log.txt').write_text('output')"
    )
    profile_path.write_text(json.dumps(payload))
    git(tmp_path, "add", ".harness/project.json")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "outputs")
    rec = app.create_round(
        TaskProfile(
            "product", intent=TaskIntent.BUILD, specification_clarity=0.9, epistemic_uncertainty=0.1
        )
    )
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "closed"
    app.approve_promotion(rec.round_id)
    app.promote_round(rec.round_id)
    assert (tmp_path / "product.txt").read_text() == "correct"
    assert not (tmp_path / "results").exists()
    assert agent.calls
