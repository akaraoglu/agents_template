import json
from datetime import datetime, timezone
from pathlib import Path

from codexteam_tools.subagent_status import collect_subagent_status


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
