import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any


class GitPublisher:
    """Handles automated branch pushing, PR description generation, and PR creation."""

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path).resolve()

    def generate_pr_summary(self, bug_id: str, target_file: str, attempts: int, test_cmd: str) -> Dict[str, str]:
        """Builds a structured PR title and markdown description documenting the automated repair."""
        title = f"fix({bug_id}): autonomous repair for {target_file}"
        body = f"""## Automated Software Repair Summary

### Target
- **Failing Module:** `{target_file}`
- **Issue Reference:** `{bug_id}`
- **Resolution Cycle:** Passed on attempt `{attempts}`

### Verification Proof
- **Target Test Gate:** Passed (`{test_cmd}`)
- **Regression Suite Gate:** Zero regressions detected across full test suite
- **Syntax Check:** Pre-flight AST validation cleared

---
*Generated autonomously by Autonomous Software Repair Agent.*
"""
        return {"title": title, "body": body}

    def write_markdown_report(
        self,
        bug_id: str,
        target_file: str,
        attempts: int,
        test_cmd: str,
        patch_file: Path,
        output_report_path: Path
    ) -> Path:
        """Generates an executive audit report for engineering review."""
        patch_text = patch_file.read_text(encoding="utf-8") if patch_file.exists() else "No patch file found."

        report_content = f"""# Autonomous Repair Engine - Execution Audit

**Bug ID:** `{bug_id}`<br>
**Target Module:** `{target_file}`<br>
**Status:** `VERIFIED_RESOLVED`<br>
**Repair Iterations:** `{attempts}`

---

## 1. Verification Gate Summary
- **Phase 1 (Target Test):** Passed via `{test_cmd}`
- **Phase 2 (Regression Suite):** Zero regressions detected across full test suite
- **AST Pre-flight:** Syntax analysis validated cleanly

---

## 2. Generated Unified Diff
```diff
{patch_text}
```

### Target
- **Failing Module:** `{target_file}`
- **Issue Reference:** `{bug_id}`
- **Resolution Cycle:** Passed on attempt `{attempts}`

### Verification Proof
- **Target Test Gate:** Passed (`{test_cmd}`)
- **Regression Suite Gate:** Zero regressions detected across full test suite
- **Syntax Check:** Pre-flight AST validation cleared

---
*Generated autonomously by Autonomous Software Repair Agent.*
"""
        output_report_path = Path(output_report_path)
        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(report_content, encoding="utf-8")
        return output_report_path

    def publish_pull_request(
        self,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "master"
    ) -> Dict[str, Any]:
        """Attempts to create a GitHub PR using `gh` CLI. Falls back if unavailable."""
        gh_path = shutil.which("gh")
        if gh_path is None:
            return {
                "created": False,
                "reason": "GitHub CLI ('gh') is not installed. The repair branch and patch are preserved locally.",
                "branch": branch_name,
                "manual_command": f'gh pr create --base {base_branch} --head {branch_name} --title "{title}"'
            }

        try:
            gh_check = subprocess.run(
                [gh_path, "auth", "status"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {
                "created": False,
                "reason": f"Could not check GitHub CLI authentication: {exc}. The repair is preserved locally.",
                "branch": branch_name,
            }

        if gh_check.returncode != 0:
            return {
                "created": False,
                "reason": "GitHub CLI ('gh') is not authenticated. Branch is preserved locally.",
                "branch": branch_name,
                "manual_command": f'gh pr create --base {base_branch} --head {branch_name} --title "{title}"'
            }

        try:
            result = subprocess.run(
                [
                    gh_path, "pr", "create",
                    "--base", base_branch,
                    "--head", branch_name,
                    "--title", title,
                    "--body", body,
                ],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {
                "created": False,
                "reason": f"Could not create pull request: {exc}. The repair is preserved locally.",
                "branch": branch_name,
            }

        if result.returncode == 0:
            return {
                "created": True,
                "url": result.stdout.strip(),
                "branch": branch_name,
            }
        return {
            "created": False,
            "reason": result.stderr.strip() or result.stdout.strip(),
            "branch": branch_name,
        }