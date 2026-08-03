from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from codexteam_tools.test_gates import (
    GateConfigError,
    main,
    run_gate,
    snapshot_current_gate_record,
    validate_current_gate_record,
)


def configure(project: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
    ]
    content = (
        'schema_version = "1.0"\n'
        'verification_paths = ["src/**", "tests/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 30\n'
        f"commands = [{json.dumps(command)}]\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 60\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps(command)}]\n"
    )
    (project / "management").mkdir(exist_ok=True)
    (project / "management" / "TEST_GATES.toml").write_text(content)


def test_integration_gate_runs_development_first_and_detects_staleness(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)

    record = run_gate(project, "integration")

    assert record["status"] == "passed"
    assert [entry["gate"] for entry in record["commands"]] == [
        "development",
        "integration",
    ]
    assert validate_current_gate_record(project, "integration") == record
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    with pytest.raises(GateConfigError, match="stale"):
        validate_current_gate_record(project, "integration")


def test_gate_record_is_stale_when_commands_change(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    run_gate(project, "integration")

    config = project / "management" / "TEST_GATES.toml"
    config.write_text(config.read_text().replace("expected_max_seconds = 60", "expected_max_seconds = 61"))

    with pytest.raises(GateConfigError, match="configuration"):
        validate_current_gate_record(project, "integration")


def test_gate_dry_run_is_non_mutating_and_rejects_unconfigured(tmp_path: Path):
    project = tmp_path / "project"
    (project / "management").mkdir(parents=True)
    (project / "management" / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n'
        '[development]\nconfigured = false\nexpected_max_seconds = 1\ncommands = []\n'
        '[integration]\nconfigured = false\nexpected_max_seconds = 1\nincludes = ["development"]\ncommands = []\n'
    )
    with pytest.raises(GateConfigError, match="not configured"):
        run_gate(project, "development", dry_run=True)
    assert not (project / "results").exists()


def test_host_only_gate_rejects_worker_and_writes_immutable_snapshot(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management" / "TEST_GATES.toml"
    config.write_text(
        config.read_text().replace(
            "[integration]\nconfigured = true",
            '[integration]\nconfigured = true\nexecution_surface = "lead_host"',
        )
    )

    with pytest.raises(GateConfigError, match="requires execution surface 'lead_host'"):
        run_gate(project, "integration")

    record = run_gate(project, "integration", execution_surface="lead_host")
    assert record["execution_surface"] == "lead_host"
    path, snapshot = snapshot_current_gate_record(
        project,
        "integration",
        task_id="T003",
        attempt_id="att-001",
    )
    assert path.parent == project / "results/gates/accepted"
    assert snapshot["record"] == record
    assert len(snapshot["record_sha256"]) == 64
    assert snapshot_current_gate_record(
        project,
        "integration",
        task_id="T003",
        attempt_id="att-001",
    )[0] == path

    before = path.read_bytes()
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    assert path.read_bytes() == before
    with pytest.raises(GateConfigError, match="stale"):
        snapshot_current_gate_record(
            project,
            "integration",
            task_id="T004",
            attempt_id="att-001",
        )


def test_gate_cli_prints_accepted_snapshot_path(tmp_path: Path, capsys):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)

    code = main(
        [
            str(project),
            "--gate",
            "integration",
            "--snapshot-task",
            "T003",
            "--snapshot-attempt",
            "att-001",
        ]
    )

    assert code == 0
    assert "Accepted snapshot: results/gates/accepted/T003-att-001-integration-" in capsys.readouterr().out
