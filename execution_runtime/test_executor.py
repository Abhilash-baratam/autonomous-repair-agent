import subprocess
import os
import sys
from pathlib import Path
from typing import Dict, Any


class LocalTestExecutor:
    """Executes verification and test commands in an isolated path."""

    @staticmethod
    def run_tests(workspace_path: Path, test_command: str, timeout_seconds: int = 60) -> Dict[str, Any]:
        """Runs the test suite inside the worktree and captures pass/fail status."""
        try:
            test_env = os.environ.copy()
            test_env["PYTHONDONTWRITEBYTECODE"] = "1"
            python_scripts = str(Path(sys.executable).parent)
            test_env["PATH"] = os.pathsep.join(
                [python_scripts, test_env.get("PATH", "")]
            )
            process = subprocess.run(
                test_command,
                shell=True,
                cwd=str(workspace_path),
                env=test_env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            passed = (process.returncode == 0)
            output = f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"

            return {
                "passed": passed,
                "return_code": process.returncode,
                "output": output.strip(),
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "return_code": -1,
                "output": f"Error: Test execution timed out after {timeout_seconds} seconds.",
            }
        except Exception as e:
            return {
                "passed": False,
                "return_code": -1,
                "output": f"Execution error: {str(e)}",
            }