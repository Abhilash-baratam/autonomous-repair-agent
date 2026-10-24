from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from execution_runtime.git_publisher import GitPublisher


class GitPublisherTests(unittest.TestCase):
    def test_generate_pr_summary_returns_summary(self):
        publisher = GitPublisher(Path.cwd())

        result = publisher.generate_pr_summary(
            bug_id="BUG-123",
            target_file="billing.py",
            attempts=2,
            test_cmd="pytest test_billing.py",
        )

        self.assertEqual(result["title"], "fix(BUG-123): autonomous repair for billing.py")
        self.assertIn("Passed on attempt `2`", result["body"])
        self.assertIn("pytest test_billing.py", result["body"])

    def test_write_markdown_report_writes_audit_file(self):
        publisher = GitPublisher(Path.cwd())

        with TemporaryDirectory() as temp_dir:
            patch_file = Path(temp_dir) / "fix.patch"
            report_file = Path(temp_dir) / "reports" / "audit.md"
            patch_file.write_text("diff --git a/billing.py b/billing.py", encoding="utf-8")

            result = publisher.write_markdown_report(
                bug_id="BUG-123",
                target_file="billing.py",
                attempts=2,
                test_cmd="pytest test_billing.py",
                patch_file=patch_file,
                output_report_path=report_file,
            )

            self.assertEqual(result, report_file)
            self.assertTrue(report_file.is_file())
            report_content = report_file.read_text(encoding="utf-8")
            self.assertIn("BUG-123", report_content)
            self.assertIn("diff --git a/billing.py b/billing.py", report_content)

    def test_missing_gh_cli_returns_local_repair_status(self):
        publisher = GitPublisher(Path.cwd())

        with (
            patch("execution_runtime.git_publisher.shutil.which", return_value=None),
            patch("execution_runtime.git_publisher.subprocess.run") as run,
        ):
            result = publisher.publish_pull_request(
                branch_name="ai-fix/example",
                title="Fix example",
                body="Verified repair",
            )

        self.assertFalse(result["created"])
        self.assertIn("not installed", result["reason"])
        self.assertEqual(result["branch"], "ai-fix/example")
        self.assertIn("gh pr create", result["manual_command"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
