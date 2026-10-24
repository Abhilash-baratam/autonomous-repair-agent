import ast
from pathlib import Path
from typing import Dict, List, Set


class DependencyResolver:
    """Extracts imported local module signatures using AST traversal."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path).resolve()

    def find_local_dependencies(self, rel_source_file: str) -> Dict[str, str]:
        """Finds all local files imported by the target file and extracts signatures."""
        source_path = self.workspace_path / rel_source_file
        if not source_path.exists():
            return {}

        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        imported_modules: Set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        dependency_contexts: Dict[str, str] = {}

        for mod_name in imported_modules:
            rel_mod_file = f"{mod_name.replace('.', '/')}.py"
            mod_file_path = self.workspace_path / rel_mod_file

            if mod_file_path.exists() and mod_file_path != source_path:
                summary = self._extract_public_signatures(mod_file_path)
                if summary:
                    dependency_contexts[rel_mod_file] = summary

        return dependency_contexts

    def _extract_public_signatures(self, file_path: Path) -> str:
        """Parses a local dependency and returns function signatures and docstrings."""
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

        signatures: List[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                args = [arg.arg for arg in node.args.args]
                sig = f"def {node.name}({', '.join(args)}):"
                doc = ast.get_docstring(node)
                if doc:
                    sig += f' """{doc.strip()}"""'
                signatures.append(sig)
            elif isinstance(node, ast.ClassDef):
                signatures.append(f"class {node.name}:")
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        sub_args = [arg.arg for arg in sub.args.args]
                        signatures.append(f"    def {sub.name}({', '.join(sub_args)}): ...")

        if not signatures:
            return file_path.read_text(encoding="utf-8")[:1000]

        return "\n".join(signatures)