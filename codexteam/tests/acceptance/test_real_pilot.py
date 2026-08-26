"""Test-engineer acceptance checks for the real split-root pilot.

These run only on a host that hosts the real pilot roots; elsewhere they
are skipped so the CI-equivalent gate stays portable. They implement the
codexteam control project PROJECT.md verification-plan rows:

- AC-04: real pilot audit of the codexteam control project plus an
  independent scan that the source work root carries no control state
  entries (the product's central-exception exemption is not relied on).
- AC-03: the documented run procedure entry points respond (documented
  gate interpreter, gate executor CLI, separation audit CLI).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLKIT_ROOT = Path("/home/alik/workspace/agent_template/codexteam")
PROJECTS_ROOT = Path("/home/alik/workspace/codexspace/projects")
CONTROL_ROOT = PROJECTS_ROOT / "codexteam"
WORK_ROOT = TOOLKIT_ROOT
PYTHON = Path("/home/alik/workspace/agent_template/env-python/bin/python")
AUDIT_CLI = TOOLKIT_ROOT / "scripts" / "audit-project-separation.py"
GATE_CLI = TOOLKIT_ROOT / "scripts" / "run-test-gate.py"

CONTROL_STATE_ENTRIES = (
    "TASKS.md",
    "BRIEF.md",
    "PROJECT.md",
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
    "DONE_REPORT.md",
    "BLOCKED_REPORT.md",
    "DELIVERY.md",
    "RESULT.md",
    "OPEN_QUESTIONS.md",
    "IMPLEMENTATION_PLAN.md",
    "management",
    "results",
)

pytestmark = pytest.mark.skipif(
    not (CONTROL_ROOT.is_dir() and TOOLKIT_ROOT.is_dir()),
    reason="real pilot roots are not present on this host",
)


def test_real_pilot_audit_reports_codexteam_project_clean():
    completed = subprocess.run(
        [sys.executable, str(AUDIT_CLI), str(PROJECTS_ROOT), "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] in {"passed", "failed"}
    projects = {entry["project"]: entry for entry in payload["projects"]}
    assert "codexteam" in projects
    codexteam = projects["codexteam"]
    assert codexteam["errors"] == []
    repos = {entry["id"]: entry for entry in codexteam["repositories"]}
    assert "codexteam" in repos
    repo = repos["codexteam"]
    assert repo["errors"] == []
    # The central toolkit work root is the documented central exception:
    # the record must state the exemption instead of silently skipping.
    assert repo["central_exception"] is True
    assert repo["work_root"] == str(WORK_ROOT)


def test_real_pilot_work_root_has_no_control_state_entries():
    found = [name for name in CONTROL_STATE_ENTRIES if (WORK_ROOT / name).exists()]
    assert found == [], f"control state entries found in work root: {found}"


def test_real_pilot_run_procedure_entry_points_respond():
    assert PYTHON.is_file(), "documented gate interpreter is missing"
    version = subprocess.run(
        [str(PYTHON), "--version"], capture_output=True, text=True, check=False
    )
    assert version.returncode == 0
    assert "Python 3." in version.stdout + version.stderr

    gate_help = subprocess.run(
        [str(PYTHON), str(GATE_CLI), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert gate_help.returncode == 0
    assert "--gate" in gate_help.stdout
    assert "--execution-surface" in gate_help.stdout

    audit_help = subprocess.run(
        [str(PYTHON), str(AUDIT_CLI), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert audit_help.returncode == 0
    assert "projects_root" in audit_help.stdout
