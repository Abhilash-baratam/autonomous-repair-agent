import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from execution_runtime.test_executor import LocalTestExecutor


class LocalTestExecutorTests(unittest.TestCase):
    @patch("execution_runtime.test_executor.subprocess.run")
    def test_adds_selected_python_directory_to_command_path(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        with TemporaryDirectory() as temp_dir:
            LocalTestExecutor.run_tests(Path(temp_dir), "pytest")

        command_path = run.call_args.kwargs["env"]["PATH"].split(os.pathsep)
        self.assertEqual(command_path[0], str(Path(sys.executable).parent))


if __name__ == "__main__":
    unittest.main()
