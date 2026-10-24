import argparse
import sys
import uuid
from pathlib import Path
from agent.repair_loop import CoreRepairEngine
from execution_runtime.test_executor import LocalTestExecutor


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Software Repair Agent: Detect, patch, verify, and export bug fixes."
    )
    parser.add_argument("--repo", type=str, required=True, help="Path to target Git repository")
    parser.add_argument("--target-test", type=str, required=True, help="Command to run the failing test")
    parser.add_argument("--regression-test", type=str, default="pytest -q", help="Command for full regression suite")
    parser.add_argument("--max-retries", type=int, default=3, help="Max repair retry budget")
    parser.add_argument("--model", type=str, default="gemini-flash-lite-latest", help="LLM model identifier")

    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()

    if not (repo_path / ".git").exists():
        print(f"[!] Error: '{repo_path}' is not a valid Git repository.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Running baseline target test: `{args.target_test}`...")
    initial_run = LocalTestExecutor.run_tests(repo_path, args.target_test)

    if initial_run["passed"]:
        print("[OK] Baseline target test passed. No repairs needed.")
        sys.exit(0)

    print("[!] Target test failed as expected. Triggering autonomous repair engine...")
    engine = CoreRepairEngine(repo_path=str(repo_path), model_name=args.model)
    bug_id = f"BUG-{uuid.uuid4().hex[:8].upper()}"

    result = engine.execute_repair(
        bug_id=bug_id,
        error_log=initial_run["output"],
        target_test_command=args.target_test,
        regression_test_command=args.regression_test,
        max_retries=args.max_retries
    )

    if result["success"]:
        print("\n" + "=" * 60)
        print(f"[OK] SUCCESS: Fix committed to branch: '{result['branch']}'")
        print(f"[*] Exported Patch: {result['patch_file']}")
        if "pr_info" in result:
            print(f"[*] PR Title: {result['pr_info']['title']}")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print(f"[x] FAILED: {result.get('error')}")
        for attempt in result.get("history", []):
            reason = attempt.get("reason")
            if reason:
                print(f"[!] Attempt {attempt.get('attempt')} failed: {reason}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()