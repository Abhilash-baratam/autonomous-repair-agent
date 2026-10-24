from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent.analyzer import LogAndCodeAnalyzer


class LogAndCodeAnalyzerTests(unittest.TestCase):
    def test_prefers_source_file_over_pytest_test_file(self):
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "billing.py").write_text("def calculate_total(): pass\n", encoding="utf-8")
            (workspace / "test_billing.py").write_text("def test_calculate_total(): pass\n", encoding="utf-8")
            error_log = (
                "test_billing.py:5: AssertionError\n"
                'File "billing.py", line 4, in calculate_total\n'
            )

            result = LogAndCodeAnalyzer(workspace).parse_stack_trace(error_log)

            self.assertEqual(result["primary_target"]["file_path"], "billing.py")

    def test_resolves_test_target_to_matching_imported_source_file(self):
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "billing.py").write_text("def calculate_total(): pass\n", encoding="utf-8")
            (workspace / "test_billing.py").write_text(
                "from billing import calculate_total\n"
                "def test_calculate_total():\n"
                "    assert calculate_total() == 1\n",
                encoding="utf-8",
            )

            result = LogAndCodeAnalyzer(workspace).parse_stack_trace(
                "test_billing.py:3: AssertionError"
            )

            self.assertEqual(result["primary_target"]["file_path"], "billing.py")


if __name__ == "__main__":
    unittest.main()
