import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class WorkspaceManager:
    """Manages ephemeral Git worktrees for safe, isolated code patch execution."""

    def __init__(self, repo_path: str, scratch_dir: Optional[str] = None):
        self.repo_path = Path(repo_path).resolve()
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Target path '{self.repo_path}' is not a valid Git repository.")

        self.scratch_dir = (
            Path(scratch_dir).resolve()
            if scratch_dir
            else self.repo_path.parent / ".agent_worktrees"
        )
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

        self.active_branch: Optional[str] = None
        self.worktree_path: Optional[Path] = None
        self.last_patch_error: Optional[str] = None

    def create_worktree(self, bug_id: str) -> Path:
        """Creates an isolated git worktree checked out to a unique fix branch."""
        clean_bug_id = bug_id.replace("/", "-").replace(" ", "_")
        self.active_branch = f"ai-fix/{clean_bug_id}"
        self.worktree_path = self.scratch_dir / f"worktree_{clean_bug_id}"

        if self.worktree_path.exists():
            self.cleanup()

        # Delete stale branch if exists
        subprocess.run(
            ["git", "branch", "-D", self.active_branch],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

        result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-f",
                "-b",
                self.active_branch,
                str(self.worktree_path),
                "HEAD",
            ],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to create Git worktree:\n{result.stderr}")

        return self.worktree_path

    def apply_patch(self, patch_diff: str) -> bool:
        """Applies a standard unified git diff inside the isolated worktree."""
        if not self.worktree_path or not self.worktree_path.exists():
            raise RuntimeError("Worktree does not exist. Call create_worktree first.")

        self.last_patch_error = None
        patch_file = self.worktree_path / ".patch.diff"
        patch_file.write_text(patch_diff.rstrip("\r\n") + "\n", encoding="utf-8")

        try:
            check = subprocess.run(
                ["git", "apply", "--recount", "--check", str(patch_file)],
                cwd=str(self.worktree_path),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )

            if check.returncode != 0:
                self.last_patch_error = (check.stderr or check.stdout).strip() or "git apply --check failed."
                return False

            apply_res = subprocess.run(
                ["git", "apply", "--recount", str(patch_file)],
                cwd=str(self.worktree_path),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )

            if apply_res.returncode != 0:
                self.last_patch_error = (apply_res.stderr or apply_res.stdout).strip() or "git apply failed."
                return False
            return True
        finally:
            if patch_file.exists():
                patch_file.unlink()

    def commit_fix(self, commit_message: str) -> bool:
        """Commits all staged and unstaged fixes inside the isolated worktree."""
        if not self.worktree_path or not self.worktree_path.exists():
            return False

        subprocess.run(
            ["git", "add", "."],
            cwd=str(self.worktree_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

        commit_res = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=str(self.worktree_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

        return commit_res.returncode == 0

    def export_patch(self, output_path: Path) -> Path:
        """Exports the committed fix as a standard unified patch file."""
        if not self.worktree_path or not self.worktree_path.exists():
            raise RuntimeError("Worktree does not exist.")

        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        res = subprocess.run(
            ["git", "format-patch", "-1", "HEAD", "--stdout"],
            cwd=str(self.worktree_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )

        output_path.write_text(res.stdout, encoding="utf-8")
        return output_path

    def cleanup(self) -> None:
        """Safely tears down and deletes the temporary Git worktree."""
        if self.worktree_path and self.worktree_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.worktree_path)],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if self.worktree_path.exists():
                shutil.rmtree(self.worktree_path, ignore_errors=True)

        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )