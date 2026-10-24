"""Real, local acceptance fixtures for adapter/lifecycle integration tests."""

import json
import subprocess
import sys


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def configure_acceptance(root, assertion="assert Path('README.md').is_file()"):
    (root / ".harness").mkdir(exist_ok=True)
    profile = {
        "schema_version": 1,
        "requirements": [
            {"id": "FIXTURE-1", "description": "Fixture remains valid", "checks": ["fixture"]}
        ],
        "checks": [
            {
                "id": "fixture",
                "argv": [sys.executable, "-c", "from pathlib import Path; " + assertion],
            }
        ],
    }
    (root / ".harness/project.json").write_text(json.dumps(profile), encoding="utf-8")
    return profile


def initialize_verified_repo(root):
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        ".harness/runtime/\n.harness/worktrees/\n.harness/rounds/\n2_Working_State/\n",
        encoding="utf-8",
    )
    configure_acceptance(root)
    git(root, "init")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "base")
