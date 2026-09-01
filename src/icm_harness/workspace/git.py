import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from icm_harness.kernel.errors import WorkspaceError


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._/-]+", "-", value).strip("-")[:100]


@dataclass
class GitWorktreeManager:
    repo: Path
    worktree_root: Path

    def __init__(self, repo: str | Path, worktree_root: str | Path = ".harness/worktrees"):
        self.repo = Path(repo).resolve()
        self.worktree_root = (self.repo / worktree_root).resolve()
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def _git(self, *args: str) -> str:
        return self._git_at(self.repo, *args)

    def _git_at(self, directory: str | Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(Path(directory)), *args],
            text=True,
            capture_output=True,
        )
        if proc.returncode:
            raise WorkspaceError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.strip()

    def assert_repo(self):
        if self._git("rev-parse", "--is-inside-work-tree") != "true":
            raise WorkspaceError(f"not a Git work tree: {self.repo}")

    def create(self, round_id: str, stage_name: str, *, base_ref: str = "HEAD") -> Path:
        self.assert_repo()
        name = _slug(f"{round_id}-{stage_name}").replace("/", "-")
        path = self.worktree_root / name
        branch = _slug(f"harness/{round_id}/{stage_name}")
        if path.exists():
            raise WorkspaceError(f"worktree exists: {path}")
        proc = subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", branch, str(path), base_ref],
            text=True,
            capture_output=True,
        )
        if proc.returncode:
            raise WorkspaceError(proc.stderr.strip() or proc.stdout.strip())
        return path

    def remove(self, path: str | Path, *, force: bool = False):
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(Path(path)))
        self._git(*args)

    def status(self, path: str | Path) -> str:
        return self._git_at(path, "status", "--short")

    def diff(self, path: str | Path) -> str:
        worktree = Path(path)
        status = self.status(worktree)
        diff = self._git_at(worktree, "diff", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/")
        cached = self._git_at(
            worktree,
            "diff",
            "--cached",
            "--no-ext-diff",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        )
        sections = []
        if status:
            sections.append("# git status --short\n" + status)
        if diff:
            sections.append("# unstaged diff\n" + diff)
        if cached:
            sections.append("# staged diff\n" + cached)
        return "\n\n".join(sections)

    def promote(self, path: str | Path, *, message: str) -> str:
        worktree = Path(path).resolve()
        root_changes = self._git("status", "--porcelain", "--untracked-files=no")
        if root_changes:
            raise WorkspaceError(
                "base repository has tracked changes; commit or stash them before promotion"
            )

        if self.status(worktree):
            self._git_at(worktree, "add", "-A")
            self._git_at(
                worktree,
                "-c",
                "user.name=ICM Harness",
                "-c",
                "user.email=icm-harness@localhost",
                "commit",
                "-m",
                message,
            )
        branch = self._git_at(worktree, "branch", "--show-current")
        if not branch:
            raise WorkspaceError("round worktree is not on a branch")
        before = self._git("rev-parse", "HEAD")
        proc = subprocess.run(
            ["git", "-C", str(self.repo), "merge", "--no-ff", branch, "-m", message],
            text=True,
            capture_output=True,
        )
        if proc.returncode:
            subprocess.run(
                ["git", "-C", str(self.repo), "merge", "--abort"],
                text=True,
                capture_output=True,
            )
            raise WorkspaceError(proc.stderr.strip() or proc.stdout.strip())
        after = self._git("rev-parse", "HEAD")
        return after if after != before else before
