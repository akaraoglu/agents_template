import os
import subprocess
from pathlib import Path

from codexteam_tools.project_init import initialize_project


CODEXTEAM_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CODEXTEAM_ROOT.parent
RUNNER = CODEXTEAM_ROOT / "scripts" / "run-e2e-fibonacci-test.sh"
FIXTURE = CODEXTEAM_ROOT / "tests" / "e2e" / "fibonacci-tree-cli"


def write_valid_product(project: Path) -> None:
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
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
    parser = argparse.ArgumentParser(description="Fibonacci tree; range 0..15; F(0)=0 and F(1)=1")
    parser.add_argument("n", type=int)
    args = parser.parse_args(argv)
    if not 0 <= args.n <= 15:
        parser.error("n must be in 0..15")
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
    assert "T005 | Review operator documentation" in tasks
    assert (project / "management" / "tasks" / "T005.md").is_file()
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
    assert completed.stdout.count("--reasoning-effort medium") == 10
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
    assert "- Status: PASS" in report.read_text(encoding="utf-8")
    assert (project / "src" / "fibonacci_tree_cli.py").is_file()


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
    assert "- Status: FAILED" in report.read_text(encoding="utf-8")
    assert f"Project preserved at: {project}" in completed.stdout


def test_runner_contains_no_destructive_or_automatic_recovery_path():
    source = RUNNER.read_text(encoding="utf-8")
    assert "rm -" not in source
    assert '"${PROJECT}"/run_verification*.sh' in source
    assert '"${PROJECT}"/run_verification.sh)' not in source
    assert "--phase feedback" in source
    assert "No retry or model transfer was attempted" in source
    assert "--budget-seconds" in source
    assert "--enforce-budget" in source
    assert "--product-only" in source
