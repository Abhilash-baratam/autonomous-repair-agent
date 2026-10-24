import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from execution_runtime.workspace import WorkspaceManager
from execution_runtime.test_executor import LocalTestExecutor
from execution_runtime.git_publisher import GitPublisher
from agent.analyzer import LogAndCodeAnalyzer
from agent.ast_validator import ASTValidator
from agent.dependency_resolver import DependencyResolver

load_dotenv()

SYSTEM_PROMPT = """You are an expert autonomous software engineer specializing in automated debugging and minimal patch repair.
Your task is to fix the bug reported in the error log while keeping changes minimal.

CRITICAL RULES:
1. Return ONLY a valid unified git diff inside a markdown codeblock using ```diff ... ```.
2. The diff paths MUST be relative to the repository root (e.g., a/path/to/file.py and b/path/to/file.py).
3. Do not rewrite unrelated code or introduce unneeded refactoring.
4. Ensure the fix does NOT cause regressions in other parts of the codebase.
5. If this is a subsequent attempt, analyze why the previous test or regression suite failed and address the root cause.
"""

USER_TEMPLATE = """Target Repository File Context:
{code_context}

Imported Local Dependencies:
{dependencies_context}

Original Error / Stack Trace:
{error_log}

Previous Test / Regression Failure (if any):
{previous_failure}

Generate the minimal unified diff to fix this error:"""


class CoreRepairEngine:
    def __init__(self, repo_path: str, model_name: str = "gemini-flash-lite-latest"):
        self.repo_path = repo_path
        self.workspace_mgr = WorkspaceManager(repo_path)
        self.publisher = GitPublisher(Path(repo_path))

        api_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables or .env file.")

        print(f"[*] Initializing model: {model_name}...")
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0,
            google_api_key=api_key,
            timeout=45.0,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", USER_TEMPLATE)
        ])

    def _extract_diff(self, response_content: Any) -> Optional[str]:
        if isinstance(response_content, list):
            text_blocks = []
            for item in response_content:
                if isinstance(item, str):
                    text_blocks.append(item)
                elif isinstance(item, dict) and "text" in item:
                    text_blocks.append(item["text"])
                elif hasattr(item, "text"):
                    text_blocks.append(item.text)
            response_text = "\n".join(text_blocks)
        else:
            response_text = str(response_content)

        fenced_blocks = re.findall(r"```[^\r\n]*\r?\n(.*?)```", response_text, re.DOTALL)
        for block in fenced_blocks:
            if re.search(r"^(?:diff --git .+|--- .+\n\+\+\+ .+)", block.strip(), re.MULTILINE):
                return block.strip()

        diff_start = re.search(r"^(?:diff --git .+|--- .+\n\+\+\+ .+)", response_text, re.MULTILINE)
        if diff_start:
            return response_text[diff_start.start():].strip()
        return None

    def execute_repair(
        self,
        bug_id: str,
        error_log: str,
        target_test_command: str,
        regression_test_command: Optional[str] = "pytest -q",
        target_file_rel: Optional[str] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Executes autonomous repair with a Dual-Phase Verification Gate,
        patch artifact export, and markdown report generation.
        """
        print(f"[*] Creating isolated scratch Git worktree for '{bug_id}'...")
        worktree_path = self.workspace_mgr.create_worktree(bug_id)
        analyzer = LogAndCodeAnalyzer(worktree_path)
        resolver = DependencyResolver(worktree_path)

        # 1. Automatic Root File Identification
        if not target_file_rel:
            print("[*] Parsing error stack trace...")
            trace_analysis = analyzer.parse_stack_trace(error_log)
            if trace_analysis["primary_target"]:
                target_file_rel = trace_analysis["primary_target"]["file_path"]
                print(f"[✓] Trace Analysis identified root target: {target_file_rel}")
            else:
                self.workspace_mgr.cleanup()
                return {
                    "success": False,
                    "error": "Could not identify target file from the stack trace."
                }

        file_to_repair = worktree_path / target_file_rel
        if not file_to_repair.exists():
            self.workspace_mgr.cleanup()
            return {"success": False, "error": f"Target file '{target_file_rel}' not found in repo."}

        # 2. Extract Cross-File Dependencies
        deps = resolver.find_local_dependencies(target_file_rel)
        if deps:
            deps_summary = "\n\n".join([f"--- File: {k} ---\n{v}" for k, v in deps.items()])
            print(f"[✓] AST Resolver assembled context for {len(deps)} local dependencies.")
        else:
            deps_summary = "No local dependencies imported."

        previous_failure = "None. First attempt."
        attempt_history: List[Dict[str, Any]] = []

        # 3. Autonomous Repair Loop
        for attempt in range(1, max_retries + 1):
            print(f"\n[Attempt {attempt}/{max_retries}] Requesting patch from {self.llm.model}...")
            code_context = analyzer.get_focused_context(target_file_rel)

            chain = self.prompt | self.llm
            try:
                response = chain.invoke({
                    "code_context": code_context,
                    "dependencies_context": deps_summary,
                    "error_log": error_log,
                    "previous_failure": previous_failure
                })
            except Exception as e:
                print(f"[!] Model API error: {e}")
                previous_failure = f"Attempt {attempt} API error: {str(e)}"
                attempt_history.append({"attempt": attempt, "patch_applied": False, "reason": str(e)})
                error_text = str(e).upper()
                if (
                    "RESOURCE_EXHAUSTED" in error_text
                    or "QUOTA EXCEEDED" in error_text
                    or "429" in error_text
                ):
                    message = (
                        "Gemini API quota is exhausted for the configured model. "
                        "Wait for quota reset, choose a model with available quota, "
                        "or review Gemini API billing and rate limits."
                    )
                    print(f"[!] {message}")
                    self.workspace_mgr.cleanup()
                    return {
                        "success": False,
                        "attempts": attempt,
                        "error": message,
                        "history": attempt_history,
                    }
                continue

            diff = self._extract_diff(response.content)
            if not diff:
                print("[!] LLM did not generate a valid unified diff.")
                previous_failure = f"Attempt {attempt} failed: Model did not produce a valid unified git diff."
                attempt_history.append({"attempt": attempt, "patch_applied": False, "reason": "No diff extracted"})
                continue

            print("[*] Applying patch into Git worktree...")
            applied = self.workspace_mgr.apply_patch(diff)
            if not applied:
                apply_error = self.workspace_mgr.last_patch_error or "No diagnostic provided by git apply."
                print(f"[!] 'git apply' rejected the patch: {apply_error}")
                previous_failure = (
                    f"Attempt {attempt} failed: git apply rejected the generated patch.\n"
                    f"Git diagnostic: {apply_error}\n"
                    "Return a corrected, valid unified git diff with paths relative to the repository root."
                )
                attempt_history.append({
                    "attempt": attempt,
                    "patch_applied": False,
                    "reason": f"Git apply failed: {apply_error}",
                })
                continue

            # AST Pre-flight syntax validation
            ast_check = ASTValidator.validate_file(file_to_repair)
            if not ast_check["valid"]:
                print(f"[!] AST Syntax Check failed: {ast_check['error']}")
                previous_failure = f"Attempt {attempt} introduced syntax errors:\n{ast_check['error']}"
                attempt_history.append({
                    "attempt": attempt,
                    "patch_applied": True,
                    "syntax_valid": False,
                    "reason": ast_check["error"]
                })
                continue

            # Phase 1: Target Test Gate
            print(f"[*] [Phase 1 Gate] Running target test: `{target_test_command}`...")
            target_res = LocalTestExecutor.run_tests(worktree_path, target_test_command)

            if not target_res["passed"]:
                print("[x] [Phase 1 Gate] Target test failed.")
                previous_failure = (
                    f"Attempt {attempt} Target Test Failure:\n"
                    f"Command: {target_test_command}\n"
                    f"{target_res['output']}"
                )
                attempt_history.append({
                    "attempt": attempt,
                    "patch_applied": True,
                    "syntax_valid": True,
                    "phase_1_target_passed": False,
                    "phase_2_regression_passed": None,
                    "output": target_res["output"]
                })
                continue

            print("[✓] [Phase 1 Gate] Target test passed!")

            # Phase 2: Full Regression Gate
            regression_passed = True
            reg_output = ""
            if regression_test_command:
                print(f"[*] [Phase 2 Gate] Running full regression suite: `{regression_test_command}`...")
                reg_res = LocalTestExecutor.run_tests(worktree_path, regression_test_command)
                regression_passed = reg_res["passed"]
                reg_output = reg_res["output"]

                if not regression_passed:
                    print("[!] [Phase 2 Gate] Regression detected in wider test suite!")
                    previous_failure = (
                        f"Attempt {attempt} caused a REGRESSION in the wider test suite:\n"
                        f"Target test passed, but `{regression_test_command}` failed with:\n"
                        f"{reg_output}\n"
                        "Please adjust the patch to fix the original bug WITHOUT breaking existing tests."
                    )
                    attempt_history.append({
                        "attempt": attempt,
                        "patch_applied": True,
                        "syntax_valid": True,
                        "phase_1_target_passed": True,
                        "phase_2_regression_passed": False,
                        "output": reg_output
                    })
                    continue

                print("[✓] [Phase 2 Gate] Zero regressions confirmed across the full suite.")

            attempt_history.append({
                "attempt": attempt,
                "patch_applied": True,
                "syntax_valid": True,
                "phase_1_target_passed": True,
                "phase_2_regression_passed": True,
                "output": "All gates passed successfully."
            })

            print("[✓] All verification gates PASSED! Autonomous repair confirmed.")

            # Commit fix
            commit_msg = (
                f"fix({bug_id}): autonomous repair for {target_file_rel}\n\n"
                f"- Phase 1 (Target): `{target_test_command}` (PASSED)\n"
                f"- Phase 2 (Regression): `{regression_test_command}` (PASSED)\n"
                f"- Total Iterations: {attempt}/{max_retries}"
            )
            print(f"[*] Committing fix to branch '{self.workspace_mgr.active_branch}'...")
            self.workspace_mgr.commit_fix(commit_msg)

            # Export patch artifact
            patches_dir = Path(self.repo_path) / "exported_patches"
            patch_file = patches_dir / f"{bug_id}.patch"
            print(f"[*] Exporting patch artifact to: {patch_file.name}...")
            self.workspace_mgr.export_patch(patch_file)

            # Generate markdown audit report
            report_file = patches_dir / f"{bug_id}_REPORT.md"
            self.publisher.write_markdown_report(
                bug_id=bug_id,
                target_file=target_file_rel,
                attempts=attempt,
                test_cmd=target_test_command,
                patch_file=patch_file,
                output_report_path=report_file
            )
            print(f"[*] Audit report generated: {report_file.name}")

            # Generate PR Summary & Attempt Publication
            pr_info = self.publisher.generate_pr_summary(
                bug_id=bug_id,
                target_file=target_file_rel,
                attempts=attempt,
                test_cmd=target_test_command
            )
            pr_result = self.publisher.publish_pull_request(
                branch_name=self.workspace_mgr.active_branch,
                title=pr_info["title"],
                body=pr_info["body"]
            )

            return {
                "success": True,
                "attempts": attempt,
                "branch": self.workspace_mgr.active_branch,
                "worktree_path": str(worktree_path),
                "fixed_file": target_file_rel,
                "patch_file": str(patch_file),
                "report_file": str(report_file),
                "pr_info": pr_info,
                "pr_result": pr_result,
                "history": attempt_history,
            }

        print("[!] Max retry budget reached. Triggering automatic rollback...")
        self.workspace_mgr.cleanup()
        return {
            "success": False,
            "attempts": max_retries,
            "error": "Exhausted retry budget without passing all verification gates. Changes rolled back.",
            "history": attempt_history
        }