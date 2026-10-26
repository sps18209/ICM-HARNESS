"""Run the captured local project contract and retain machine-readable evidence."""

from __future__ import annotations

import json
from pathlib import Path

import anyio

from icm_harness.evaluation import load_profile, verify_candidate


def main():
    root = Path.cwd()
    profile = load_profile(root)
    destination = root / ".harness/runtime/verification"
    report = anyio.run(verify_candidate, profile, root, destination)
    output = destination / report["run_id"] / "verification.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for check in report["commands"]:
        print(f"{check['id']}: {'PASS' if check['passed'] else 'FAIL'}")
        if not check["passed"]:
            print(json.dumps(check, indent=2))
    print(f"evidence: {output}")
    print(f"acceptance: {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
