"""Test-engineer integration tests for the split-root CLI entry points.

These cross the real process boundary that the in-process unit tests in
tests/test_separation_audit.py and tests/test_test_gates.py do not: the
shipped scripts are executed as subprocesses and their exit codes,
stdout/stderr separation, and JSON contracts are asserted.

Requirement basis (codexteam control project PROJECT.md):

- AC-04 control/source separation: the audit CLI passes a clean split
  root, fails a contaminated one (control product scaffold, source
  control artifact, tracked-but-deleted Git-index artifacts), and
  reports usage errors distinctly.
- AC-02 independent product evidence: the gate CLI enforces the
  configured lead_host surface for the integration gate (a worker must
  not run it) and writes gate records to the control root, never the
  work root.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_CLI = TOOLKIT_ROOT / "scripts" / "audit-project-separation.py"
GATE_CLI = TOOLKIT_ROOT / "scripts" / "run-test-gate.py"


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def make_split_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    projects = tmp_path / "projects"
    control = projects / "product"
    work = tmp_path / "repos" / "product"
    control.mkdir(parents=True)
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": "product",
            "work_root": str(work),
            "git_root": str(work),
            "git_prefix": ".",
            "remote_url": None,
            "write_policy": "task-owned",
        }],
    }))
    return projects, control, work


def test_audit_cli_passes_clean_split_root(tmp_path: Path):
    projects, _control, _work = make_split_root(tmp_path)

    completed = run_cli(AUDIT_CLI, str(projects), "--json")

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["errors"] == []
    entry = payload["projects"][0]
    assert entry["project"] == "product"
    assert entry["errors"] == []
    assert entry["repositories"][0]["git_index_checked"] is True


def test_audit_cli_fails_contaminated_split_root(tmp_path: Path):
    projects, control, work = make_split_root(tmp_path)
    (control / "src").mkdir()
    (work / "TASKS.md").write_text("# Tasks\n")

    completed = run_cli(AUDIT_CLI, str(projects), "--json")

    assert completed.returncode == 1, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert any("control contains product scaffold: src" in e for e in payload["errors"])
    assert any("source contains control artifact: TASKS.md" in e for e in payload["errors"])


def test_audit_cli_detects_git_index_contamination(tmp_path: Path):
    projects, _control, work = make_split_root(tmp_path)
    artifact = work / "BRIEF.md"
    artifact.write_text("# Brief\n")
    subprocess.run(["git", "add", "BRIEF.md"], cwd=work, check=True)
    artifact.unlink()

    completed = run_cli(AUDIT_CLI, str(projects), "--json")

    assert completed.returncode == 1, completed.stdout
    payload = json.loads(completed.stdout)
    assert any(
        "source Git index contains control artifact: BRIEF.md" in e
        for e in payload["errors"]
    )


def test_audit_cli_missing_projects_root_is_usage_error(tmp_path: Path):
    completed = run_cli(AUDIT_CLI, str(tmp_path / "absent-projects-root"), "--json")

    assert completed.returncode == 2
    assert "ERROR:" in completed.stderr
    assert completed.stdout == ""


def make_gate_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    control = tmp_path / "control"
    git_root = tmp_path / "checkout" / "repo"
    work = git_root / "component"
    (control / "management").mkdir(parents=True)
    (work / "src").mkdir(parents=True)
    (work / "src" / "main.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=git_root, check=True)
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": "component",
            "work_root": str(work),
            "git_root": str(git_root),
            "git_prefix": "component",
            "remote_url": None,
            "write_policy": "task-owned",
        }],
    }))
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
    ]
    (control / "management" / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\n'
        'verification_paths = ["src/**"]\n\n'
        "[development]\n"
        "configured = true\n"
        'execution_surface = "worker"\n'
        "expected_max_seconds = 60\n"
        f"commands = [{json.dumps(command)}]\n\n"
        "[integration]\n"
        "configured = true\n"
        'execution_surface = "lead_host"\n'
        "expected_max_seconds = 60\n"
        'includes = ["development"]\n'
        f"commands = [{json.dumps(command)}]\n"
    )
    return control, work, git_root


def split_cli(control: Path, work: Path, *args: str):
    return run_cli(
        GATE_CLI,
        "--control-root", str(control),
        "--work-root", str(work),
        "--repo-id", "component",
        *args,
    )


def test_gate_cli_development_record_goes_to_control_root(tmp_path: Path):
    control, work, _git_root = make_gate_project(tmp_path)

    completed = split_cli(control, work, "--gate", "development")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Status: passed" in completed.stdout
    record_path = control / "results" / "gates" / "development.json"
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["control_root"] == str(control)
    assert record["work_root"] == str(work)
    assert record["git_prefix"] == "component"
    assert record["repo_id"] == "component"
    assert not (work / "results").exists()


def test_gate_cli_rejects_worker_surface_for_lead_host_integration(tmp_path: Path):
    control, work, _git_root = make_gate_project(tmp_path)

    completed = split_cli(control, work, "--gate", "integration")

    assert completed.returncode == 2
    assert "requires execution surface 'lead_host'" in completed.stdout + completed.stderr
    assert not (control / "results" / "gates" / "integration.json").exists()
