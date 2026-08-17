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
    assert records[0]["policy"] == "invalid/unavailable"
    assert records[0]["execution_spec_status"] == "unsupported_pre_cutover"
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
    assert records[0]["profile"] == "unknown"


def test_project_without_sessions_returns_empty(tmp_path: Path):
    assert collect_subagent_status(tmp_path) == []


def test_pre_cutover_status_does_not_project_recorded_backend(tmp_path: Path):
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
    record = collect_subagent_status(project)[0]
    assert "backend" not in record
    assert record["execution_spec_status"] == "unsupported_pre_cutover"


def test_status_exposes_attempt_draft_format_pin(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(
        attempt / "draft-format.json",
        {"schema_version": "1.0", "draft_format": "compact-json"},
    )
    write_json(
        attempt / "turn-state.json",
        {
            "team_id": "team-1",
            "task_id": "T002",
            "attempt_id": "att-001",
            "status": "running",
        },
    )

    record = collect_subagent_status(project)[0]
    assert record["draft_format"] == "compact-json"
    assert record["draft_format_pinned"] is True


def test_pre_cutover_status_does_not_project_agent_spec_or_profile(tmp_path: Path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(
        attempt / "session.json",
        {
            "team_id": "team-1", "task_id": "T002", "attempt_id": "att-001",
            "agent_role": "developer", "model_profile": "qwen36-27b",
            "agent_spec": {"id": "python-developer", "version": "1.0", "digest": "a" * 64},
        },
    )
    record = collect_subagent_status(project)[0]
    assert record["role"] == "developer"
    assert record["agent_spec"] is None
    assert record["profile"] == "unknown"
    assert main([str(project)]) == 0
    assert "AGENT_SPEC" not in capsys.readouterr().out.splitlines()[0]


def test_status_reads_execution_spec_without_session(tmp_path: Path):
    from codexteam_tools.execution_spec import compile_execution_spec
    from codexteam_tools.execution_registry import load_execution_registry

    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    attempt.mkdir(parents=True)
    spec = compile_execution_spec(
        team_id="team-1", task_id="T002", attempt_id="att-001", role="developer",
        workspace_root=str(project), handoff_source_path=None,
        handoff_content_digest="a" * 64, role_policy_name="codexteam_developer",
        role_policy_version="1.0", role_policy_digest="b" * 64,
        agent_spec=None, effective_policy_digest="d" * 64,
        guidance_files=["implementation.md"], guidance_digest="c" * 64,
        execution_profile=load_execution_registry().resolve(
            "codex", "qwen36-27b", "medium"
        ).reference(runtime_version=None, backend_material_digest="e" * 64),
        sandbox_mode="workspace-write", trust_parent_sandbox=False, additional_write_roots=[],
        mcp_allowed_servers=[], mcp_effective_servers=[], mcp_missing_servers=[],
        mcp_allowed_tools={}, mcp_effective_tools={}, bound_mcp_project=None,
        gate_routing=None,
    )
    write_json(attempt / "execution-spec.json", spec)

    record = collect_subagent_status(project)[0]
    assert record["role"] == "developer"
    assert record["execution_spec_digest"] == spec["execution_spec_digest"]
    assert record["execution_spec_pinned"] is True


def test_legacy_status_defaults_to_unpinned_conversational(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(attempt / "session.json", {"team_id": "team-1"})

    record = collect_subagent_status(project)[0]
    assert record["draft_format"] == "conversational"
    assert record["draft_format_pinned"] is False


def test_legacy_resumed_turn_state_does_not_claim_a_pin(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    write_json(attempt / "session.json", {"team_id": "team-1"})
    write_json(
        attempt / "turn-state.json",
        {
            "draft_format": "conversational",
            "draft_format_pinned": False,
            "status": "draft_ready",
        },
    )

    assert collect_subagent_status(project)[0]["draft_format_pinned"] is False


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


def test_pre_cutover_mixed_status_table_has_no_backend_column(tmp_path: Path, capsys):
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
    assert lines[0] == "TEAM TASK ATTEMPT ROLE PROFILE POLICY PHASE TURN STATUS UPDATED"
    assert all(" opencode " not in line for line in lines[1:])
