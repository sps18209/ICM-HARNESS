"""Exercise the same acceptance policy on an actual compiled TypeScript HTTP API."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import anyio

from icm_harness.evaluation import load_profile, verify_candidate


def main():
    repository = Path(__file__).resolve().parents[1]
    fixture = repository / "fixtures/typescript_api"
    dependencies = fixture / "node_modules"
    if not (dependencies / "typescript/bin/tsc").is_file():
        raise SystemExit("Install fixture dependencies: npm ci --prefix fixtures/typescript_api")
    with tempfile.TemporaryDirectory(prefix="icm-typescript-") as directory:
        root = Path(directory) / "target"
        shutil.copytree(fixture, root, ignore=shutil.ignore_patterns("node_modules", "runtime"))
        (root / "node_modules").symlink_to(dependencies, target_is_directory=True)
        for args in (
            ["init", "-q"],
            ["add", "."],
            [
                "-c",
                "user.name=ICM fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "Reviewed synthetic TypeScript fixture",
            ],
        ):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        profile = load_profile(root)
        evidence = repository / ".harness/runtime/typescript-validation"
        passed = anyio.run(verify_candidate, profile, root, evidence)
        if not passed["passed"]:
            print(json.dumps(passed, indent=2))
            raise SystemExit("correct TypeScript fixture failed acceptance")
        server = root / "src/server.ts"
        original = server.read_text(encoding="utf-8")
        changed = original.replace("response.writeHead(401)", "response.writeHead(200)")
        assert changed != original
        server.write_text(changed, encoding="utf-8")
        rejected = anyio.run(verify_candidate, profile, root, evidence)
        if rejected["passed"] or rejected["failure_class"] != "implementation":
            print(json.dumps(rejected, indent=2))
            raise SystemExit("unauthorized-write regression was not rejected")
        print(
            json.dumps(
                {
                    "target_language": "TypeScript",
                    "native_tests": passed["commands"][-1]["tests"]["total"],
                    "correct_candidate": "accepted",
                    "authorization_regression": "rejected",
                    "evidence_runs": [passed["run_id"], rejected["run_id"]],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
