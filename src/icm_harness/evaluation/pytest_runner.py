"""Local trusted-development pytest adapter; invoke with --report PATH -- ARGS.

This process records native node IDs and execution phases. It shares the caller's
OS identity and does not attest hostile in-process code or replace isolation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


class EventRecorder:
    def __init__(self):
        self.data = {
            "schema_version": 1, "collected": [], "deselected": [],
            "collection_errors": [], "events": [], "exit_code": -1,
        }

    def pytest_collection_finish(self, session):
        self.data["collected"] = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.data["deselected"].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.data["collection_errors"].append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        self.data["events"].append({
            "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
            "wasxfail": hasattr(report, "wasxfail"),
        })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    # Configuration files and conftest files still need captured protected digests.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ.pop("PYTEST_PLUGINS", None)
    import pytest

    recorder = EventRecorder()
    code = int(pytest.main(pytest_args, plugins=[recorder]))
    recorder.data["exit_code"] = code
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(recorder.data), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
