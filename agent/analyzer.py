import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


class LogAndCodeAnalyzer:
    """Parses stack traces, extracts failing files, and retrieves surrounding code context."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path).resolve()

    def parse_stack_trace(self, error_log: str) -> Dict[str, Any]:
        """Extracts candidate source files and line numbers from Python or JS/TS traces."""
        python_trace_pattern = r'File\s+"([^"]+\.py)",\s+line\s+(\d+)'
        pytest_pattern = r'([\w\/\.\-]+\.py):(\d+):'
        js_pattern = r'at\s+.*?\((.*?):(\d+):\d+\)'

        candidates: List[Dict[str, Any]] = []

        for pattern in [python_trace_pattern, pytest_pattern, js_pattern]:
            matches = re.findall(pattern, error_log)
            for file_str, line_str in matches:
                file_path = Path(file_str)
                rel_path = None

                if file_path.is_absolute():
                    try:
                        rel_path = file_path.relative_to(self.workspace_path)
                    except ValueError:
                        continue
                else:
                    rel_path = file_path

                if (self.workspace_path / rel_path).exists():
                    candidates.append({
                        "file_path": str(rel_path).replace("\\", "/"),
                        "line_number": int(line_str)
                    })

        # Deduplicate while preserving order
        unique_targets = []
        seen = set()
        for item in candidates:
            key = (item["file_path"], item["line_number"])
            if key not in seen:
                seen.add(key)
                unique_targets.append(item)

        # Prioritize implementation source files over test suites
        source_candidates = [c for c in unique_targets if not Path(c["file_path"]).name.startswith("test_")]
        test_candidates = [c for c in unique_targets if Path(c["file_path"]).name.startswith("test_")]

        if not source_candidates:
            for test_candidate in reversed(test_candidates):
                test_path = self.workspace_path / test_candidate["file_path"]
                try:
                    test_tree = ast.parse(test_path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError, UnicodeError):
                    continue

                imported_modules = []
                for node in ast.walk(test_tree):
                    if isinstance(node, ast.Import):
                        imported_modules.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_modules.append(node.module)

                test_stem = test_path.stem.removeprefix("test_")
                imported_modules.sort(
                    key=lambda name: (Path(name.replace(".", "/")).stem != test_stem, name)
                )
                for module_name in imported_modules:
                    module_path = Path(module_name.replace(".", "/") + ".py")
                    if (self.workspace_path / module_path).is_file():
                        source_candidates.append({
                            "file_path": module_path.as_posix(),
                            "line_number": test_candidate["line_number"],
                        })
                        break

        primary = source_candidates[-1] if source_candidates else (test_candidates[-1] if test_candidates else None)

        return {
            "targets": unique_targets,
            "primary_target": primary
        }

    def get_focused_context(self, rel_file_path: str, focus_line: Optional[int] = None, window: int = 25) -> str:
        """Retrieves file code, optionally focusing on lines around the failure point."""
        target_path = self.workspace_path / rel_file_path
        if not target_path.exists():
            return f"Error: Target file {rel_file_path} does not exist."

        lines = target_path.read_text(encoding="utf-8").splitlines()

        if focus_line is None or len(lines) <= window * 2:
            return f"--- Start of {rel_file_path} ---\n" + "\n".join(lines) + f"\n--- End of {rel_file_path} ---"

        start_line = max(0, focus_line - window)
        end_line = min(len(lines), focus_line + window)

        snippet = [
            f"{i+1:4d} | {lines[i]}" if i + 1 != focus_line else f"{i+1:4d} > {lines[i]}"
            for i in range(start_line, end_line)
        ]

        return (
            f"--- Snippet from {rel_file_path} (Lines {start_line+1} to {end_line}) ---\n"
            + "\n".join(snippet)
            + f"\n--- End of Snippet ---"
        )
