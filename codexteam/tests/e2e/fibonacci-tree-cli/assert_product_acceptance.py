#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


EXPECTED_VALUES = (0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610)
EXPECTED_ROOT_FILES = {
    ".gitignore",
    "AGENTS.md",
    "BLOCKED_REPORT.md",
    "BRIEF.md",
    "CURRENT_TASK.md",
    "DECISIONS.md",
    "DELIVERY.md",
    "DONE_REPORT.md",
    "IMPLEMENTATION_PLAN.md",
    "OPEN_QUESTIONS.md",
    "PROJECT.md",
    "PROJECT_STATE.md",
    "README.md",
    "RESULT.md",
    "TASKS.md",
}
EXPECTED_ROOT_DIRECTORIES = {".codexteam", ".git", "docs", "golden", "management", "results", "src", "tests"}
EXPECTED_SOURCE_FILES = {".gitkeep", "fibonacci_tree_cli.py"}
EXPECTED_TEST_FILES = {
    ".gitkeep",
    "integration",
    "smoke",
    "test_fibonacci_tree_cli.py",
    "unit",
}
EXPECTED_GOLDEN_FILES = {"fib-4.txt"}
EXPECTED_MANAGEMENT_FILES = {"BACKLOG.md", "PLAN.md", "TEST_GATES.md", "TEST_GATES.toml"}
EXPECTED_TASK_FILES = {f"T{number:03d}.md" for number in range(1, 6)}
EXPECTED_RESULT_FILES = {
    ".gitkeep",
    "e2e-report.md",
    "t001-fixture-validation.txt",
    "t002-development.txt",
    "t003-acceptance.txt",
    "t004-evidence-audit.md",
    "t005-delivery-review.md",
    *(f"T{number:03d}-att-001.json" for number in range(1, 6)),
    *(f"T{number:03d}-verification.txt" for number in range(1, 6)),
}
FORBIDDEN_NAMES = {
    ".coverage",
    ".DS_Store",
    ".env",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "auth.json",
    "credentials.json",
    "__pycache__",
}
FORBIDDEN_SUFFIXES = {
    ".bak",
    ".key",
    ".orig",
    ".patch",
    ".pem",
    ".pyc",
    ".pyo",
    ".rej",
    ".swo",
    ".swp",
    ".tmp",
}
INCOMPLETE_SOURCE_MARKERS = ("TODO", "FIXME", "NotImplementedError")
SECRET_NAME_MARKERS = ("credential", "private_key", "secret")


class AcceptanceFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def run_cli(cli: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(cli), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def assert_success(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    require(result.returncode == 0, f"{label}: exit code {result.returncode}, expected 0")
    require(result.stderr == "", f"{label}: stderr must be empty, found {result.stderr!r}")


def assert_invalid(
    cli: Path,
    arguments: tuple[str, ...],
    *,
    label: str,
    accepted_terms: tuple[str, ...] = (),
) -> None:
    result = run_cli(cli, *arguments)
    require(result.returncode != 0, f"{label}: exit code must be nonzero")
    require(result.stdout == "", f"{label}: stdout must be empty, found {result.stdout!r}")
    require(result.stderr != "", f"{label}: stderr must contain a concise diagnostic")
    require(len(result.stderr) <= 1000, f"{label}: stderr is not concise")
    require("Traceback" not in result.stderr, f"{label}: stderr contains a traceback")
    if accepted_terms:
        stderr = result.stderr.casefold()
        require(
            any(term.casefold() in stderr for term in accepted_terms),
            f"{label}: stderr does not identify the input category",
        )


def check_product(project: Path, fixture_root: Path) -> None:
    cli = project / "src" / "fibonacci_tree_cli.py"
    golden = fixture_root / "golden" / "fib-4.txt"
    project_golden = project / "golden" / "fib-4.txt"
    require(cli.is_file(), f"missing CLI: {cli}")
    require(golden.is_file(), f"missing repository golden: {golden}")
    require(project_golden.is_file(), f"missing generated-project golden: {project_golden}")

    golden_bytes = golden.read_bytes()
    require(golden_bytes.endswith(b"\n"), "repository golden must end with exactly one newline")
    require(not golden_bytes.endswith(b"\n\n"), "repository golden must not contain an extra trailing blank line")
    require(project_golden.read_bytes() == golden_bytes, "generated-project golden differs from repository golden")
    golden_text = golden_bytes.decode("utf-8")

    observed: dict[int, subprocess.CompletedProcess[str]] = {}
    for n, expected_value in enumerate(EXPECTED_VALUES):
        result = run_cli(cli, str(n))
        assert_success(result, label=f"input {n}")
        require(
            result.stdout.startswith(f"fib({n}) = {expected_value}\n"),
            f"input {n}: incorrect root Fibonacci value",
        )
        observed[n] = result

    require(observed[0].stdout == "fib(0) = 0\n", "input 0 stdout must be the exact base case")
    require(observed[1].stdout == "fib(1) = 1\n", "input 1 stdout must be the exact base case")
    require(observed[4].stdout == golden_text, "input 4 stdout differs byte-for-byte from the golden")
    byte_result = subprocess.run(
        [sys.executable, "-B", str(cli), "4"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    require(byte_result.returncode == 0, "input 4 byte check must exit 0")
    require(byte_result.stderr == b"", "input 4 byte check must keep stderr empty")
    require(byte_result.stdout == golden_bytes, "input 4 raw stdout bytes differ from the golden")

    golden_lines = observed[4].stdout.splitlines()
    require(golden_lines[7] == "    ├── fib(1) = 1", "right-subtree left child indentation regressed")
    require(golden_lines[8] == "    └── fib(0) = 0", "right-subtree right child indentation regressed")

    repeated = [run_cli(cli, "4") for _ in range(3)]
    for index, result in enumerate(repeated, start=1):
        assert_success(result, label=f"determinism run {index}")
    require(
        all((result.returncode, result.stdout, result.stderr) == (0, golden_text, "") for result in repeated),
        "repeated input-4 executions are not deterministic",
    )

    help_result = run_cli(cli, "--help")
    assert_success(help_result, label="help")
    compact_help = "".join(help_result.stdout.split())
    require("0..15" in help_result.stdout, "help does not state the accepted range 0..15")
    require("F(0)=0" in compact_help, "help does not state F(0) = 0")
    require("F(1)=1" in compact_help, "help does not state F(1) = 1")

    assert_invalid(
        cli,
        (),
        label="missing input",
    )
    assert_invalid(
        cli,
        ("abc",),
        label="non-integer input",
        accepted_terms=("integer", "int"),
    )
    for value in ("-1", "16"):
        assert_invalid(
            cli,
            (value,),
            label=f"out-of-range input {value}",
            accepted_terms=("0..15", "range"),
        )

    require(len(observed[15].stdout.splitlines()) == 1973, "input 15 must render exactly 1,973 lines")


def assert_exact_names(path: Path, expected: set[str], *, label: str) -> None:
    require(path.is_dir(), f"missing {label} directory: {path}")
    actual = {child.name for child in path.iterdir()}
    unexpected = sorted(actual - expected)
    require(not unexpected, f"unexpected {label} entries: {', '.join(unexpected)}")


def check_manifest(project: Path) -> None:
    root_entries = {child.name for child in project.iterdir()}
    unexpected_root = sorted(root_entries - EXPECTED_ROOT_FILES - EXPECTED_ROOT_DIRECTORIES)
    require(not unexpected_root, f"unexpected project-root entries: {', '.join(unexpected_root)}")

    assert_exact_names(project / "src", EXPECTED_SOURCE_FILES, label="source")
    assert_exact_names(project / "tests", EXPECTED_TEST_FILES, label="test")
    assert_exact_names(project / "golden", EXPECTED_GOLDEN_FILES, label="golden")
    assert_exact_names(project / "docs", {"architecture"}, label="documentation")
    assert_exact_names(project / "docs" / "architecture", {".gitkeep"}, label="architecture documentation")
    assert_exact_names(project / "management", EXPECTED_MANAGEMENT_FILES | {"tasks"}, label="management")
    assert_exact_names(project / "management" / "tasks", EXPECTED_TASK_FILES, label="task")
    assert_exact_names(project / "results", EXPECTED_RESULT_FILES, label="result")

    for path in project.rglob("*"):
        relative = path.relative_to(project)
        if relative.parts[:2] == (".codexteam", "runtime"):
            continue
        require(not path.is_symlink(), f"delivery contains symlink: {relative}")
        require(path.name not in FORBIDDEN_NAMES, f"delivery contains forbidden path: {relative}")
        require(path.suffix not in FORBIDDEN_SUFFIXES, f"delivery contains forbidden file: {relative}")
        lower_name = path.name.lower()
        require(not lower_name.startswith(".env."), f"delivery contains environment-secret file: {relative}")
        require(
            not any(marker in lower_name for marker in SECRET_NAME_MARKERS),
            f"delivery contains secret-like file: {relative}",
        )

    source = (project / "src" / "fibonacci_tree_cli.py").read_text(encoding="utf-8")
    for marker in INCOMPLETE_SOURCE_MARKERS:
        require(marker not in source, f"source contains incomplete marker {marker!r}")

    gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    require(".codexteam/runtime/" in gitignore, "persistent runtime directory is not excluded from delivery")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assert the controlled Fibonacci product contract.")
    parser.add_argument("project")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--product-only", action="store_true")
    mode.add_argument("--manifest-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project = Path(args.project).expanduser().resolve(strict=True)
    fixture_root = Path(__file__).resolve().parent
    run_product = not args.manifest_only
    run_manifest = not args.product_only
    try:
        if run_product:
            check_product(project, fixture_root)
            print("PRODUCT: PASS")
        if run_manifest:
            check_manifest(project)
            print("MANIFEST: PASS")
    except (AcceptanceFailure, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
