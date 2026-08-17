import os
import subprocess
import sys
from pathlib import Path

from codexteam_tools.project_init import initialize_project


CODEXTEAM_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CODEXTEAM_ROOT.parent
RUNNER = CODEXTEAM_ROOT / "scripts" / "run-e2e-fibonacci-test.sh"
FIXTURE = CODEXTEAM_ROOT / "tests" / "e2e" / "fibonacci-tree-cli"
ACCEPTANCE = FIXTURE / "assert_product_acceptance.py"


def write_valid_product(project: Path) -> None:
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "tests").mkdir(exist_ok=True)
    (project / "golden").mkdir(exist_ok=True)
    (project / "src" / "fibonacci_tree_cli.py").write_text(
        '''import argparse


def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def render(n):
    lines = [f"fib({n}) = {fib(n)}"]

    def visit(value, prefix, last):
        connector = "└── " if last else "├── "
        lines.append(f"{prefix}{connector}fib({value}) = {fib(value)}")
        if value >= 2:
            child_prefix = prefix + ("    " if last else "│   ")
            visit(value - 1, child_prefix, False)
            visit(value - 2, child_prefix, True)

    if n >= 2:
        visit(n - 1, "", False)
        visit(n - 2, "", True)
    return "\\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render N in the inclusive range 0..15; F(0) = 0 and F(1) = 1."
    )
    parser.add_argument("n", type=int)
    args = parser.parse_args(argv)
    if not 0 <= args.n <= 15:
        parser.error("n must be in range 0..15")
    print(render(args.n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    (project / "tests" / "test_fibonacci_tree_cli.py").write_text(
        '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.fibonacci_tree_cli import fib, render


class ProductTests(unittest.TestCase):
    def test_product(self):
        self.assertEqual(fib(4), 3)
        self.assertEqual(len(render(4).splitlines()), 9)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )
    (project / "golden" / "fib-4.txt").write_bytes((FIXTURE / "golden" / "fib-4.txt").read_bytes())
    (project / "README.md").write_text("Run `python3 src/fibonacci_tree_cli.py 4`.\n", encoding="utf-8")


def test_fibonacci_e2e_runner_is_executable_and_valid_bash():
    assert os.access(RUNNER, os.X_OK)
    completed = subprocess.run(
        ["bash", "-n", str(RUNNER)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_fibonacci_e2e_runner_uses_current_codexteam_projects_root():
    content = RUNNER.read_text(encoding="utf-8")
    assert 'PROJECTS_ROOT="${CODEXTEAM_PROJECTS_ROOT:-${CODEXTEAM_ROOT}/projects}"' in content
    assert "/home/alik/workspace/codexspace" not in content


def test_controlled_fixture_initializes_five_specific_tasks(tmp_path: Path):
    plan = initialize_project(
        "Fibonacci Tree CLI",
        "Deliver the controlled canary.",
        root=tmp_path,
        project_id="fibonacci-fixture",
        tasks=("T001", "T002", "T003", "T004", "T005"),
        template_root=FIXTURE / "template",
    )
    project = plan.project_dir

    tasks = (project / "TASKS.md").read_text(encoding="utf-8")
    assert "T001 | Validate the controlled project fixture" in tasks
    assert "| T001 |" in tasks and "| In Progress | fixture-lead-01" in tasks
    assert "T003 | Engineer and run the independent integration gate" in tasks
    assert "integration-test-engineer-01 (tester)" in tasks
    assert "T005 | Review operator documentation" in tasks
    assert (project / "management" / "tasks" / "T005.md").is_file()
    gates = (project / "management" / "TEST_GATES.md").read_text(encoding="utf-8")
    assert "Status: Configured" in gates
    assert "Owner: Test Engineer (`tester` protocol role)" in gates
    assert (project / "golden" / "fib-4.txt").read_text(encoding="utf-8").startswith("fib(4) = 3\n")
    assert "Next handoff:" in (project / "BRIEF.md").read_text(encoding="utf-8")
    for path in project.rglob("*.md"):
        assert "{{" not in path.read_text(encoding="utf-8"), path


def test_runner_dry_run_is_non_mutating_and_describes_ten_turns(tmp_path: Path):
    project_id = "fibonacci-dry-run"
    report = tmp_path / "dry-run-report.md"
    report.write_text("operator-owned report\n", encoding="utf-8")
    completed = subprocess.run(
        [
            str(RUNNER),
            "--dry-run",
            "--profile",
            "gpt54-mini",
            "--reasoning-effort",
            "medium",
            "--projects-root",
            str(tmp_path),
            "--project-id",
            project_id,
            "--report-file",
            str(report),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / project_id).exists()
    assert "Expected clean turns: 10" in completed.stdout
    assert completed.stdout.count("[deterministic draft gate]") == 5
    assert completed.stdout.count("--phase draft") == 5
    assert completed.stdout.count("--phase final") == 5
    assert completed.stdout.count("--backend codex") == 5
    assert completed.stdout.count("--profile gpt54-mini") == 5
    assert completed.stdout.count("--reasoning-effort medium") == 5
    assert report.read_text(encoding="utf-8") == "operator-owned report\n"


def test_runner_refuses_to_overwrite_an_existing_project(tmp_path: Path):
    project = tmp_path / "already-there"
    project.mkdir()
    marker = project / "owner-data.txt"
    marker.write_text("preserve me\n", encoding="utf-8")

    completed = subprocess.run(
        [
            str(RUNNER),
            "--dry-run",
            "--profile",
            "gpt54-mini",
            "--reasoning-effort",
            "medium",
            "--projects-root",
            str(tmp_path),
            "--project-id",
            project.name,
            "--report-file",
            str(tmp_path / "unused-report.md"),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode != 0
    assert "refusing to overwrite" in completed.stderr
    assert marker.read_text(encoding="utf-8") == "preserve me\n"


def test_product_only_mode_passes_offline_and_writes_report(tmp_path: Path):
    project = tmp_path / "valid-product"
    project.mkdir()
    write_valid_product(project)
    report = tmp_path / "product-report.md"

    completed = subprocess.run(
        [str(RUNNER), "--product-only", str(project), "--report-file", str(report)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report_text = report.read_text(encoding="utf-8")
    assert "- Status: PASS" in report_text
    assert "- Product verdict: PASS" in report_text
    assert "- Manifest verdict: NOT_APPLICABLE" in report_text
    assert "- Performance verdict: NOT_APPLICABLE" in report_text
    assert "- Correction ceiling status: NOT_APPLICABLE" in report_text
    assert "- Lead-token ceiling status: NOT_APPLICABLE" in report_text
    assert (project / "src" / "fibonacci_tree_cli.py").is_file()


def test_report_includes_validated_codex_reported_lead_usage(tmp_path: Path):
    project = tmp_path / "valid-product-with-lead-usage"
    project.mkdir()
    write_valid_product(project)
    report = tmp_path / "lead-usage-report.md"

    completed = subprocess.run(
        [
            str(RUNNER),
            "--product-only",
            str(project),
            "--report-file",
            str(report),
            "--lead-duration-seconds",
            "321",
            "--lead-input-tokens",
            "1250000",
            "--lead-cached-tokens",
            "800000",
            "--lead-output-tokens",
            "45000",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report_text = report.read_text(encoding="utf-8")
    assert "- Lead-token ceiling status: PASS" in report_text
    assert "- Lead input tokens: 1250000" in report_text
    assert "- Lead cached input tokens: 800000" in report_text
    assert "- Lead uncached input tokens: 450000" in report_text
    assert "- Lead output tokens: 45000" in report_text
    assert "- Lead duration seconds: 321" in report_text


def test_runner_rejects_partial_lead_token_reporting(tmp_path: Path):
    project = tmp_path / "unused-product"
    project.mkdir()

    completed = subprocess.run(
        [
            str(RUNNER),
            "--product-only",
            str(project),
            "--lead-input-tokens",
            "100",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires input, cached-input, and output values together" in completed.stderr


def test_product_only_failure_preserves_project_and_reports_recovery_state(tmp_path: Path):
    project = tmp_path / "failing-product"
    project.mkdir()
    write_valid_product(project)
    sentinel = project / "owner-data.txt"
    sentinel.write_text("preserve me\n", encoding="utf-8")
    (project / "src" / "fibonacci_tree_cli.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
    report = tmp_path / "failure-report.md"

    completed = subprocess.run(
        [str(RUNNER), "--product-only", str(project), "--report-file", str(report)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
    report_text = report.read_text(encoding="utf-8")
    assert "- Status: FAILED" in report_text
    assert "- Product verdict: FAIL" in report_text
    assert "- Manifest verdict: NOT_APPLICABLE" in report_text
    assert f"Project preserved at: {project}" in completed.stdout


def test_product_acceptance_detects_right_subtree_indentation_regression(tmp_path: Path):
    project = tmp_path / "bad-indentation"
    project.mkdir()
    write_valid_product(project)
    source_path = project / "src" / "fibonacci_tree_cli.py"
    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(
        source.replace(
            'child_prefix = prefix + ("    " if last else "│   ")',
            'child_prefix = prefix + "│   "',
        ),
        encoding="utf-8",
    )
    report = tmp_path / "indentation-report.md"

    completed = subprocess.run(
        [str(RUNNER), "--product-only", str(project), "--report-file", str(report)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "golden" in completed.stderr or "indentation" in completed.stderr
    assert "- Product verdict: FAIL" in report.read_text(encoding="utf-8")


def test_manifest_acceptance_detects_exploratory_helper(tmp_path: Path):
    plan = initialize_project(
        "Fibonacci Tree CLI",
        "Deliver the controlled canary.",
        root=tmp_path,
        project_id="dirty-manifest",
        tasks=("T001", "T002", "T003", "T004", "T005"),
        template_root=FIXTURE / "template",
    )
    project = plan.project_dir
    write_valid_product(project)
    clean = subprocess.run(
        [sys.executable, str(ACCEPTANCE), str(project), "--manifest-only"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert clean.returncode == 0, clean.stderr

    (project / "src" / "exploratory_helper.py").write_text("print('scratch')\n", encoding="utf-8")
    dirty = subprocess.run(
        [sys.executable, str(ACCEPTANCE), str(project), "--manifest-only"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert dirty.returncode != 0
    assert "unexpected source entries: exploratory_helper.py" in dirty.stderr


def test_runner_contains_no_destructive_or_automatic_recovery_path():
    source = RUNNER.read_text(encoding="utf-8")
    assert "rm -" not in source
    assert "--phase feedback" in source
    assert "No retry or model transfer was attempted" in source
    assert "--budget-seconds" in source
    assert "--enforce-budget" in source
    assert "--product-only" in source
    assert "Lifecycle verdict" in source
    assert "Manifest verdict" in source
    assert 'final_code == 3' in source
