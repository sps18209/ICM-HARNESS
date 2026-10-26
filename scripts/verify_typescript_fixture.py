"""Exercise the same acceptance policy on an actual compiled TypeScript HTTP API."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import anyio

from icm_harness.adapters.storage.filesystem import FilesystemEvidenceStore
from icm_harness.evaluation import load_profile, verify_candidate
from icm_harness.kernel.providers import EvidenceRef


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
        store = FilesystemEvidenceStore(evidence / "store")
        screenshots = repository / ".harness/runtime/browser-qa"
        screenshots.mkdir(parents=True, exist_ok=True)
        for command in passed["commands"]:
            for attachment in command.get("attachments", []):
                reference = EvidenceRef(**attachment["blob"])
                if reference.media_type == "image/png":
                    (screenshots / Path(attachment["path"]).name).write_bytes(
                        store.get_blob(reference)
                    )
        server = root / "src/server.ts"
        original = server.read_text(encoding="utf-8")
        changed = original.replace("response.writeHead(401)", "response.writeHead(200)")
        assert changed != original
        server.write_text(changed, encoding="utf-8")
        rejected = anyio.run(verify_candidate, profile, root, evidence)
        if rejected["passed"] or rejected["failure_class"] != "implementation":
            print(json.dumps(rejected, indent=2))
            raise SystemExit("unauthorized-write regression was not rejected")
        server.write_text(original, encoding="utf-8")
        ui = root / "src/ui.ts"
        original_ui = ui.read_text(encoding="utf-8")
        broken_ui = original_ui.replace(
            "status.textContent = 'Saved';", "status.textContent = 'Saving';"
        )
        assert broken_ui != original_ui
        ui.write_text(broken_ui, encoding="utf-8")
        browser_rejected = anyio.run(verify_candidate, profile, root, evidence)
        browser_check = next(c for c in browser_rejected["commands"] if c["id"] == "browser-tests")
        api_check = next(c for c in browser_rejected["commands"] if c["id"] == "api-tests")
        if browser_rejected["passed"] or browser_check["passed"] or not api_check["passed"]:
            print(json.dumps(browser_rejected, indent=2))
            raise SystemExit("browser-only regression was not independently rejected")
        print(
            json.dumps(
                {
                    "target_language": "TypeScript",
                    "api_tests": next(c for c in passed["commands"] if c["id"] == "api-tests")[
                        "tests"
                    ]["total"],
                    "browser_tests": next(
                        c for c in passed["commands"] if c["id"] == "browser-tests"
                    )["tests"]["total"],
                    "correct_candidate": "accepted",
                    "authorization_regression": "rejected",
                    "browser_only_regression": "rejected",
                    "artifact_digest": passed["artifact_digest"],
                    "evidence_runs": [
                        passed["run_id"],
                        rejected["run_id"],
                        browser_rejected["run_id"],
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
