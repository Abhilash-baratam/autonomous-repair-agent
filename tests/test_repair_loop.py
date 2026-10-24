from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent.repair_loop import CoreRepairEngine


class _Prompt:
    def __or__(self, llm):
        return llm


class CoreRepairEngineTests(unittest.TestCase):
    def _engine(self, worktree_path):
        engine = CoreRepairEngine.__new__(CoreRepairEngine)
        engine.repo_path = worktree_path
        engine.workspace_mgr = Mock()
        engine.workspace_mgr.create_worktree.return_value = worktree_path
        engine.workspace_mgr.active_branch = "ai-fix/bug"
        engine.publisher = Mock()
        engine.publisher.generate_pr_summary.return_value = {"title": "Fix", "body": "Verified"}
        engine.publisher.publish_pull_request.return_value = {"created": False, "reason": "gh unavailable"}
        engine.prompt = _Prompt()
        engine.llm = Mock()
        engine._extract_diff = CoreRepairEngine._extract_diff.__get__(engine)
        return engine

    def test_extracts_diff_from_unlabeled_code_fence(self):
        engine = self._engine(Path("."))
        response = (
            "Here is the fix:\n```text\n"
            "--- a/target.py\n+++ b/target.py\n"
            "@@ -1 +1 @@\n-value = 1\n+value = 2\n```"
        )

        self.assertEqual(
            engine._extract_diff(response),
            "--- a/target.py\n+++ b/target.py\n@@ -1 +1 @@\n-value = 1\n+value = 2",
        )

    def test_extracts_raw_diff_after_model_preamble(self):
        engine = self._engine(Path("."))
        response = (
            "This patch fixes the bug.\n"
            "--- a/target.py\n+++ b/target.py\n"
            "@@ -1 +1 @@\n-value = 1\n+value = 2"
        )

        self.assertEqual(
            engine._extract_diff(response),
            "--- a/target.py\n+++ b/target.py\n@@ -1 +1 @@\n-value = 1\n+value = 2",
        )

    def test_includes_git_apply_diagnostic_in_next_attempt(self):
        with TemporaryDirectory() as temp_dir:
            worktree_path = Path(temp_dir)
            (worktree_path / "target.py").write_text("value = 1\n", encoding="utf-8")
            engine = self._engine(worktree_path)
            engine.workspace_mgr.apply_patch.return_value = False
            engine.workspace_mgr.last_patch_error = "corrupt patch at line 2"
            engine.llm.invoke.return_value = SimpleNamespace(
                content="```diff\n--- a/target.py\n+++ b/target.py\n"
                "@@ -1 +1 @@\n-value = 1\n+value = 2\n```"
            )

            with (
                patch("agent.repair_loop.LogAndCodeAnalyzer") as analyzer,
                patch("agent.repair_loop.DependencyResolver") as resolver,
            ):
                analyzer.return_value.get_focused_context.return_value = "target context"
                resolver.return_value.find_local_dependencies.return_value = {}
                result = engine.execute_repair(
                    bug_id="bug",
                    error_log="failure",
                    target_test_command="pytest target",
                    target_file_rel="target.py",
                    max_retries=2,
                )

            self.assertFalse(result["success"])
            self.assertIn("corrupt patch at line 2", result["history"][0]["reason"])
            next_attempt = engine.llm.invoke.call_args_list[1].args[0]["previous_failure"]
            self.assertIn("corrupt patch at line 2", next_attempt)
            engine.workspace_mgr.cleanup.assert_called_once_with()

    def test_quota_error_stops_without_retries_and_cleans_worktree(self):
        with TemporaryDirectory() as temp_dir:
            worktree_path = Path(temp_dir)
            (worktree_path / "target.py").write_text("value = 1\n", encoding="utf-8")
            engine = self._engine(worktree_path)
            engine.llm.invoke.side_effect = RuntimeError(
                "429 RESOURCE_EXHAUSTED: quota exceeded"
            )

            with patch("agent.repair_loop.LogAndCodeAnalyzer") as analyzer:
                result = engine.execute_repair(
                    bug_id="bug",
                    error_log="failure",
                    target_test_command="pytest target",
                    regression_test_command="pytest",
                    target_file_rel="target.py",
                    max_retries=3,
                )

            self.assertFalse(result["success"])
            self.assertIn("quota is exhausted", result["error"])
            self.assertEqual(result["attempts"], 1)
            engine.llm.invoke.assert_called_once()
            engine.workspace_mgr.cleanup.assert_called_once_with()
            analyzer.return_value.get_focused_context.assert_called_once_with("target.py")

    def test_preserves_worktree_when_repair_succeeds(self):
        with TemporaryDirectory() as temp_dir:
            worktree_path = Path(temp_dir)
            (worktree_path / "target.py").write_text("value = 1\n", encoding="utf-8")
            engine = self._engine(worktree_path)
            engine.llm.invoke.return_value = SimpleNamespace(
                content="```diff\n--- a/target.py\n+++ b/target.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```"
            )
            engine.workspace_mgr.apply_patch.return_value = True
            engine.workspace_mgr.commit_fix.return_value = True

            with (
                patch("agent.repair_loop.LogAndCodeAnalyzer"),
                patch("agent.repair_loop.DependencyResolver"),
                patch(
                    "agent.repair_loop.LocalTestExecutor.run_tests",
                    return_value={"passed": True, "output": "Tests passed"},
                ),
            ):
                result = engine.execute_repair(
                    bug_id="bug",
                    error_log="failure",
                    target_test_command="pytest target",
                    regression_test_command="pytest",
                    target_file_rel="target.py",
                    max_retries=1,
                )

            self.assertTrue(result["success"])
            self.assertFalse(result["pr_result"]["created"])
            engine.workspace_mgr.cleanup.assert_not_called()
            engine.workspace_mgr.commit_fix.assert_called_once()
            engine.workspace_mgr.export_patch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
