"""Capture reviewed pytest IDs before writer changes, never during acceptance.

Usage: python scripts/capture_test_manifest.py --output .harness/tests.json
       --optional tests/test_live.py::test_live 'Requires an account' -- tests
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--optional", action="append", nargs=2, default=[], metavar=("ID", "REASON")
    )
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    with tempfile.TemporaryDirectory(prefix="icm-collection-") as directory:
        report = Path(directory) / "collection.json"
        subprocess.run(
            [sys.executable, "-m", "icm_harness.evaluation.pytest_runner", "--report",
             str(report), "--", "--collect-only", *pytest_args], check=True,
        )
        data = json.loads(report.read_text(encoding="utf-8"))
    ids = data["collected"]
    if not ids or len(ids) != len(set(ids)) or data["collection_errors"] or data["deselected"]:
        parser.error("collection must be non-empty, complete and unambiguous")
    optional = {}
    for identity, reason in args.optional:
        if identity not in ids or not reason.strip() or identity in optional:
            parser.error("optional skips require a unique collected ID and non-empty reason")
        optional[identity] = reason
    # Exclusive creation prevents accidental replacement of the acceptance baseline.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "tests": sorted(ids), "optional_skips": optional},
                  handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
