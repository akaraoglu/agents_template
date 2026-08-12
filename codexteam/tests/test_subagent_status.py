import json
from datetime import datetime, timezone
from pathlib import Path

from codexteam_tools.subagent_status import collect_subagent_status, main


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_status_merges_session_and_running_turn_state(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(
        attempt / "session.json",
        {
            "team_id": "team-1",
            "task_id": "T002",
            "attempt_id": "att-001",
            "agent_role": "developer",
            "model_profile": "qwen36-27b",
            "role_policy_name": "codexteam_developer",
            "last_status": "draft_ready",
            "turn_count": 1,
        },
    )
    write_json(
        attempt / "turn-state.json",
        {
            "status": "running",
            "phase": "feedback",
            "turn_number": 2,
            "updated_at": "2026-07-22T12:00:00Z",
            "timeout_seconds": 600,
        },
    )

    records = collect_subagent_status(
        project,
        now=datetime(2026, 7, 22, 12, 5, tzinfo=timezone.utc),
    )
    assert records[0]["status"] == "running"
    assert records[0]["phase"] == "feedback"
    assert records[0]["policy"] == "codexteam_developer"
    assert "backend" not in records[0]


def test_old_running_turn_is_reported_stale(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T003/att-001"
    write_json(
        attempt / "turn-state.json",
        {
            "team_id": "team-1",
            "task_id": "T003",
            "attempt_id": "att-001",
            "agent_role": "tester",
            "model_profile": "qwen36-27b",
            "status": "running",
            "phase": "draft",
            "turn_number": 1,
            "updated_at": "2026-07-22T10:00:00Z",
            "timeout_seconds": 60,
        },
    )
    records = collect_subagent_status(
        project,
        now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert records[0]["status"] == "stale"
    assert records[0]["profile"] == "qwen36-27b"


def test_project_without_sessions_returns_empty(tmp_path: Path):
    assert collect_subagent_status(tmp_path) == []


def test_status_exposes_recorded_backend(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(
        attempt / "session.json",
        {
            "team_id": "team-1",
            "task_id": "T002",
            "attempt_id": "att-001",
            "agent_role": "developer",
            "model_profile": "ornith35b",
            "execution_backend": "opencode",
        },
    )
    assert collect_subagent_status(project)[0]["backend"] == "opencode"


def test_codex_status_table_retains_old_columns(tmp_path: Path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(
        attempt / "session.json",
        {
            "team_id": "team-1",
            "task_id": "T002",
            "attempt_id": "att-001",
            "agent_role": "developer",
            "model_profile": "qwen36-27b",
        },
    )

    assert main([str(project)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "TEAM TASK ATTEMPT ROLE PROFILE POLICY PHASE TURN STATUS UPDATED"
    assert "BACKEND" not in lines[0]


def test_mixed_status_table_adds_backend_column(tmp_path: Path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    for task, backend in (("T002", None), ("T003", "opencode")):
        attempt = project / f".codexteam/runtime/sessions/team-1/{task}/att-001"
        record = {
            "team_id": "team-1",
            "task_id": task,
            "attempt_id": "att-001",
            "agent_role": "developer",
            "model_profile": "ornith35b" if backend else "qwen36-27b",
        }
        if backend:
            record["execution_backend"] = backend
        write_json(attempt / "session.json", record)

    assert main([str(project)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "TEAM TASK ATTEMPT ROLE BACKEND PROFILE POLICY PHASE TURN STATUS UPDATED"
    assert any(" codex qwen36-27b " in line for line in lines[1:])
    assert any(" opencode ornith35b " in line for line in lines[1:])
