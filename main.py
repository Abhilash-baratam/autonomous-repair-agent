import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

from agent.repair_loop import CoreRepairEngine


def setup_multi_module_repo(repo_dir: Path):
    """Initializes a repository with both a broken module and existing legacy tests."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Autonomous Agent"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "agent@repair.ai"], cwd=str(repo_dir), check=True)

    # 1. Dependency module (utils.py)
    utils_file = repo_dir / "utils.py"
    utils_file.write_text(
        "def compute_discount(subtotal: float, discount_percent: float) -> float:\n"
        '    """Returns total discount amount."""\n'
        "    return subtotal * (discount_percent / 100.0)\n\n"
        "def compute_tax(amount: float, tax_rate: float) -> float:\n"
        '    """Calculates tax on an amount."""\n'
        "    return amount * tax_rate\n",
        encoding="utf-8"
    )

    # 2. Existing regression suite for utils (test_utils.py)
    test_utils_file = repo_dir / "test_utils.py"
    test_utils_file.write_text(
        "from utils import compute_discount, compute_tax\n\n"
        "def test_compute_discount():\n"
        "    assert compute_discount(200.0, 15.0) == 30.0\n\n"
        "def test_compute_tax():\n"
        "    assert compute_tax(100.0, 0.05) == 5.0\n",
        encoding="utf-8"
    )

    # 3. Implementation module with the discount inversion bug (billing.py)
    billing_file = repo_dir / "billing.py"
    billing_file.write_text(
        "from utils import compute_discount, compute_tax\n\n"
        "def generate_invoice_total(subtotal: float, discount_percent: float, tax_rate: float) -> float:\n"
        "    # Bug: mistakenly adds discount instead of subtracting\n"
        "    discount = compute_discount(subtotal, discount_percent)\n"
        "    taxable_amount = subtotal + discount\n"
        "    tax = compute_tax(taxable_amount, tax_rate)\n"
        "    return round(taxable_amount + tax, 2)\n",
        encoding="utf-8"
    )

    # 4. Target test suite that fails (test_billing.py)
    test_billing_file = repo_dir / "test_billing.py"
    test_billing_file.write_text(
        "from billing import generate_invoice_total\n\n"
        "def test_generate_invoice_total():\n"
        "    # 100 subtotal - 10% discount = 90. 10% tax on 90 = 9. Total = 99.0\n"
        "    assert generate_invoice_total(100.0, 10.0, 0.10) == 99.0\n",
        encoding="utf-8"
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Baseline commit with billing failure and existing utils tests"], cwd=str(repo_dir), check=True)


if __name__ == "__main__":
    test_repo = Path("./mock_test_repo").resolve()

    if not (test_repo / ".git").exists():
        print("Setting up multi-module test repository with regression tests...")
        setup_multi_module_repo(test_repo)

    print("=" * 70, flush=True)
    print("AUTONOMOUS REPAIR AGENT: DUAL-PHASE VERIFICATION GATE", flush=True)
    print("=" * 70, flush=True)

    engine = CoreRepairEngine(repo_path=str(test_repo), model_name="gemini-flash-lite-latest")

    simulated_stack_trace = """
=================================== FAILURES ===================================
__________________________ test_generate_invoice_total _________________________

    def test_generate_invoice_total():
>       assert generate_invoice_total(100.0, 10.0, 0.10) == 99.0
E       assert 121.0 == 99.0

test_billing.py:5: AssertionError
File "billing.py", line 6, in generate_invoice_total
=========================== short test summary info ============================
FAILED test_billing.py::test_generate_invoice_total - assert 121.0 == 99.0
"""

    result = engine.execute_repair(
        bug_id=f"INV-DISCOUNT-REG-01-{uuid4().hex[:8]}",
        error_log=simulated_stack_trace,
        target_test_command=f'"{sys.executable}" -m pytest -p no:cacheprovider test_billing.py',
        regression_test_command=f'"{sys.executable}" -m pytest -p no:cacheprovider',
        max_retries=3
    )

    print("\n" + "=" * 70)
    print("DUAL-PHASE VERIFICATION RESULTS")
    print("=" * 70)
    print(f"Success Status:    {result['success']}")
    if result["success"]:
        print(f"Target Repaired:   {result['fixed_file']}")
        print(f"Iterations:        {result['attempts']}")
        print(f"Branch:            {result['branch']}")
        print(f"Exported Patch:    {result['patch_file']}")
        pr_result = result.get("pr_result", {})
        if pr_result.get("created"):
            print(f"Pull Request:      {pr_result['url']}")
        elif pr_result:
            print(f"Pull Request:      Not created: {pr_result.get('reason')}")
            if pr_result.get("manual_command"):
                print(f"Manual command:    {pr_result['manual_command']}")
        print(f"Verification Log:")
        for step in result["history"]:
            print(f"  - Attempt {step['attempt']}: Phase 1 Target={step.get('phase_1_target_passed')}, Phase 2 Regression={step.get('phase_2_regression_passed')}")
    else:
        print(f"Failure Reason:    {result.get('error')}")