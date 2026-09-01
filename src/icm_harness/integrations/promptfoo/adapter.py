"""Evaluation adapter (promptfoo).

Runs promptfoo eval configs and reduces the result to a pass/fail gate the
evaluation layer can consume. Raises :class:`IntegrationUnavailable` when the
``promptfoo`` executable is not on PATH.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from icm_harness.kernel.errors import IntegrationUnavailable


@dataclass(frozen=True, slots=True)
class PromptfooResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class PromptfooGateReport:
    passed: bool
    total: int
    failures: int
    detail: str


def run_eval(config_path: str, timeout_seconds: int = 900) -> PromptfooResult:
    try:
        proc = subprocess.run(
            ["promptfoo", "eval", "-c", config_path],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise IntegrationUnavailable("promptfoo executable not found") from exc
    return PromptfooResult(proc.returncode, proc.stdout, proc.stderr)


def evaluate_gate(config_path: str, output_json: str, timeout_seconds: int = 900) -> (
    PromptfooGateReport
):
    """Run an eval that writes JSON results and reduce it to a gate report."""
    try:
        proc = subprocess.run(
            ["promptfoo", "eval", "-c", config_path, "-o", output_json],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise IntegrationUnavailable("promptfoo executable not found") from exc
    return summarize_output(output_json, proc.returncode)


def summarize_output(output_json: str, returncode: int = 0) -> PromptfooGateReport:
    """Pure reduction of a promptfoo results file into a gate report."""
    try:
        with open(output_json, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return PromptfooGateReport(False, 0, 0, "no parseable promptfoo output")
    stats = (data.get("results", {}) or {}).get("stats", {}) or {}
    successes = int(stats.get("successes", 0))
    failures = int(stats.get("failures", 0))
    total = successes + failures
    passed = returncode == 0 and failures == 0 and total > 0
    return PromptfooGateReport(passed, total, failures, f"{successes}/{total} passed")
