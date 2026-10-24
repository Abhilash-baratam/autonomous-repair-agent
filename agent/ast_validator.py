import ast
from pathlib import Path
from typing import Dict, Any


class ASTValidator:
    """Validates Python syntax and structure before test execution."""

    @staticmethod
    def validate_code_string(code_content: str, filename: str = "<patch>") -> Dict[str, Any]:
        """Parses a Python code string using the AST module to check for syntax errors."""
        try:
            tree = ast.parse(code_content, filename=filename)
            return {
                "valid": True,
                "error": None,
                "line": None,
                "offset": None,
                "tree": tree
            }
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"SyntaxError: {e.msg} at line {e.lineno}, column {e.offset}",
                "line": e.lineno,
                "offset": e.offset,
                "tree": None
            }
        except Exception as e:
            return {
                "valid": False,
                "error": f"ParseError: {str(e)}",
                "line": None,
                "offset": None,
                "tree": None
            }

    @classmethod
    def validate_file(cls, file_path: Path) -> Dict[str, Any]:
        """Validates a physical Python file on disk."""
        if not file_path.exists():
            return {"valid": False, "error": f"File not found: {file_path}", "tree": None}
        content = file_path.read_text(encoding="utf-8")
        return cls.validate_code_string(content, filename=str(file_path))