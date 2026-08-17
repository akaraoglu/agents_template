from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from codexteam_tools.activity import (
    attach_fleet_activity, build_task_activity, collect_model_fleet,
    collect_team_activity, filter_task_activity, filter_team_activity,
    task_activity_counts,
)
from codexteam_tools.execution_registry import load_execution_registry
from codexteam_tools.execution_spec import canonical_sha256, compile_execution_spec


def _attempt(root: Path, *, status: str = "running") -> Path:
    project = root / "demo"
    project.mkdir()
    (project / "PROJECT.md").write_text("# Demo Project\n")
    attempt = project / ".codexteam/runtime/sessions/demo/T001/att-001"
    turns = attempt / "turns"
    turns.mkdir(parents=True)
    profile = load_execution_registry().resolve(
        "opencode", "qwen36-27b", "provider_default"
    )
    spec = compile_execution_spec(
        team_id="demo", task_id="T001", attempt_id="att-001", role="reviewer",
        workspace_root=str(project), handoff_source_path="management/tasks/T001.md",
        handoff_content_digest="a" * 64, role_policy_name="codexteam_reviewer",
        role_policy_version="1.0", role_policy_digest="b" * 64,
        agent_spec={"id": "security-reviewer", "version": "1.0", "digest": "c" * 64},
        effective_policy_digest="d" * 64, guidance_files=["verification.md"],
        guidance_digest="e" * 64,
        execution_profile=profile.reference(runtime_version="1.18.18", backend_material_digest="f" * 64),
        sandbox_mode="read-only", trust_parent_sandbox=False,
        additional_write_roots=[], mcp_allowed_servers=["codexteam-context"],
        mcp_effective_servers=["codexteam-context"], mcp_missing_servers=[],
        mcp_allowed_tools={"codexteam-context": ["get_task_context"]},
        mcp_effective_tools={"codexteam-context": ["get_task_context"]},
        bound_mcp_project="demo", gate_routing=None, task_write_scope=["results/**"],
    )
    (attempt / "execution-spec.json").write_text(json.dumps(spec))
    (attempt / "session.json").write_text(json.dumps({
        "team_id": "demo", "task_id": "T001", "attempt_id": "att-001",
        "agent_role": "reviewer", "thread_id": "thread-1", "turn_count": 1,
        "last_phase": "draft", "last_status": status,
        "created_at": "2026-08-17T08:00:00Z", "updated_at": "2026-08-17T08:01:00Z",
    }))
    (attempt / "turn-state.json").write_text(json.dumps({
        "status": status, "phase": "draft", "turn_number": 1,
        "started_at": "2026-08-17T08:00:00Z", "updated_at": "2026-08-17T08:01:00Z",
        "timeout_seconds": 300, "changed_paths": [], "errors": [],
    }))
    events = '{"type":"turn.completed","usage":{}}\n'
    (turns / "001-draft.jsonl").write_text(events)
    metrics = {
        "schema_version": "1.0", "metric_scope": "worker_turn",
        "task_id": "T001", "attempt_id": "att-001", "agent_role": "reviewer",
        "model_profile": "qwen36-27b", "source_event_file": "001-draft.jsonl",
        "turn": {"number": 1, "phase": "draft", "completed": True,
                 "duration_seconds": 60, "terminal_reason": "stop"},
        "reasoning": {"requested": "provider_default", "effective": None},
        "process": {"exit_code": 0, "timed_out": False, "guard_triggered": False,
                    "classification": "success"},
        "prompt_bytes": 100,
        "usage": {"cumulative": {"input_tokens": 100000, "cached_input_tokens": 0,
                                   "uncached_input_tokens": 100000, "output_tokens": 100,
                                   "reasoning_output_tokens": 0},
                  "delta": {}, "delta_mode": "initial"},
        "activity": {"tool_calls": 3, "failed_tool_calls": 1, "command_calls": 0,
                     "failed_command_calls": 0, "edit_events": 0, "agent_messages": 1,
                     "command_output_bytes": 0, "max_command_output_bytes": 0,
                     "item_type_counts": {}, "repeated_commands": [], "largest_commands": [],
                     "mcp": {"calls": 2}},
        "events": {"parse_error_count": 0, "last_error": None,
                   "diagnostics": {"events_sha256": hashlib.sha256(events.encode()).hexdigest(),
                                   "stderr_sha256": "0" * 64}},
        "generated_at": "2026-08-17T08:01:00Z",
        "backend_usage": {"max_step_input_tokens": 100000},
    }
    (turns / "001-draft.metrics.json").write_text(json.dumps(metrics))
    return project


def test_activity_projects_execution_identity_metrics_and_context_pressure(tmp_path: Path):
    _attempt(tmp_path)
    activity = collect_team_activity(
        tmp_path, now=datetime(2026, 8, 17, 8, 2, tzinfo=timezone.utc)
    )

    assert activity["counts"] == {
        "total": 1, "running": 1, "attention": 0, "waiting": 0, "completed": 0,
    }
    item = activity["attempts"][0]
    assert (item["role"], item["agent_spec"]) == ("reviewer", "security-reviewer")
    assert (item["backend"], item["model"], item["profile"]) == (
        "opencode", "qwen36-27b", "opencode/qwen36-27b",
    )
    assert item["model_display"] == "Qwen 3.6 27B"
    assert item["context_limit"] == 262144
    assert item["context_percent"] == 38.1
    assert item["tool_calls"] == 3
    assert item["mcp_calls"] == 2
    assert "prompt" not in json.dumps(item).lower()


def test_activity_stale_classification_and_filters(tmp_path: Path):
    _attempt(tmp_path)
    activity = collect_team_activity(
        tmp_path, now=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    )
    item = activity["attempts"][0]
    assert item["display_status"] == "stale"
    assert item["group"] == "needs_attention"
    assert filter_team_activity(activity["attempts"], active_only=True) == [item]
    assert filter_team_activity(activity["attempts"], backend="codex") == []
    assert filter_team_activity(activity["attempts"], agent_spec="security-reviewer") == [item]


def test_activity_retains_completed_history_for_task_grouping(tmp_path: Path):
    project = _attempt(tmp_path, status="finalized")
    original = project / ".codexteam/runtime/sessions/demo/T001/att-001"
    for index in range(2, 53):
        target = original.parent / f"att-{index:03d}"
        target.mkdir()
        for name in ("session.json", "turn-state.json"):
            value = json.loads((original / name).read_text())
            value["attempt_id"] = f"att-{index:03d}"
            (target / name).write_text(json.dumps(value))
        spec = json.loads((original / "execution-spec.json").read_text())
        spec["identity"]["attempt_id"] = f"att-{index:03d}"
        spec["execution_spec_digest"] = canonical_sha256(
            {key: value for key, value in spec.items() if key != "execution_spec_digest"}
        )
        (target / "execution-spec.json").write_text(json.dumps(spec))

    activity = collect_team_activity(tmp_path)

    assert activity["counts"]["completed"] == 52
    assert activity["hidden_completed"] == 0


def test_activity_rejects_intermediate_session_symlink(tmp_path: Path):
    project = tmp_path / "demo"
    project.mkdir()
    outside = tmp_path / "outside"
    (outside / "T001/att-001").mkdir(parents=True)
    sessions = project / ".codexteam/runtime/sessions"
    sessions.mkdir(parents=True)
    (sessions / "linked-team").symlink_to(outside, target_is_directory=True)

    assert collect_team_activity(tmp_path)["attempts"] == []


def test_activity_degrades_malformed_metrics(tmp_path: Path):
    project = _attempt(tmp_path)
    metrics = project / ".codexteam/runtime/sessions/demo/T001/att-001/turns/001-draft.metrics.json"
    value = json.loads(metrics.read_text())
    value["activity"]["mcp"] = "bad"
    value["activity"]["tool_calls"] = "many"
    metrics.write_text(json.dumps(value))

    item = collect_team_activity(tmp_path)["attempts"][0]
    assert item["tool_calls"] == 0
    assert item["context_percent"] is None


def test_activity_degrades_invalid_utf8_metrics(tmp_path: Path):
    project = _attempt(tmp_path)
    metrics = project / ".codexteam/runtime/sessions/demo/T001/att-001/turns/001-draft.metrics.json"
    metrics.write_bytes(b"\xff\xfe")

    item = collect_team_activity(tmp_path)["attempts"][0]
    assert item["turns"][0]["metrics_available"] is False
    assert item["tool_calls"] == 0


def test_activity_projects_accepted_gate_and_closure_timeline(tmp_path: Path):
    project = _attempt(tmp_path, status="finalized")
    (project / "TASKS.md").write_text(
        "# Tasks\n\n| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Review | Completed | reviewer | Passed | `results/T001-att-001.json`, `results/T001-verification.txt` |\n"
    )
    accepted = project / "results/gates/accepted"
    accepted.mkdir(parents=True)
    record = {"status": "passed", "completed_at": "2026-08-17T08:02:00Z",
              "duration_seconds": 2}
    record_sha = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (accepted / f"T001-att-001-integration-{record_sha[:16]}.json").write_text(json.dumps({
        "schema_version": "1.0", "kind": "accepted_gate_snapshot",
        "task_id": "T001", "attempt_id": "att-001", "gate": "integration",
        "record_sha256": record_sha, "record": record,
    }))
    (project / "results/T001-verification.txt").write_text(
        "Verified at: 2026-08-17T08:03:00Z\n"
    )

    timeline = collect_team_activity(tmp_path)["attempts"][0]["timeline"]

    assert [item["kind"] for item in timeline] == ["turn", "gate", "closure"]
    assert timeline[1]["artifact_ref"].startswith("results/gates/accepted/")


def test_activity_rejects_forged_gate_and_other_attempt_closure(tmp_path: Path):
    project = _attempt(tmp_path, status="finalized")
    (project / "TASKS.md").write_text(
        "# Tasks\n\n| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Review | Completed | reviewer | Passed | `results/T001-att-999.json`, `results/T001-verification.txt` |\n"
    )
    accepted = project / "results/gates/accepted"
    accepted.mkdir(parents=True)
    (accepted / "T001-att-001-integration-deadbeefdeadbeef.json").write_text(json.dumps({
        "schema_version": "1.0", "kind": "accepted_gate_snapshot",
        "task_id": "T001", "attempt_id": "att-001", "gate": "integration",
        "record_sha256": "0" * 64, "record": {"status": "passed"},
    }))
    (project / "results/T001-verification.txt").write_text(
        "Verified at: 2026-08-17T08:03:00Z\n"
    )
    timeline = collect_team_activity(tmp_path)["attempts"][0]["timeline"]
    assert [item["kind"] for item in timeline] == ["turn"]


def test_activity_projects_bound_and_orphan_delegations(tmp_path: Path):
    project = _attempt(tmp_path)
    attempt = project / ".codexteam/runtime/sessions/demo/T001/att-001"
    (attempt / "delegation.json").write_text(json.dumps({
        "schema_version": "1.0", "kind": "lead_delegation",
        "created_at": "2026-08-17T08:00:00Z", "attribution": "bound_lead",
        "parent": {"session_id": "lead-session", "task_id_at_launch": "T001"},
        "child": {"team_id": "demo", "task_id": "T001", "attempt_id": "att-001",
                  "agent_role": "reviewer", "workspace_root": str(project)},
    }))

    activity = collect_team_activity(tmp_path)

    assert activity["attempts"][0]["delegation_status"] == "bound_lead"
    assert activity["delegations"][0]["session_id"] == "lead-session"


def test_model_fleet_is_bounded_to_curated_ollama_models(monkeypatch):
    def fake(path: str, timeout: float):
        assert timeout == 1.0
        if path == "/api/tags":
            return {"models": [
                {"name": "qwen3.6-27b:latest", "size": 10},
                {"name": "uncurated:latest", "size": 20},
            ]}
        return {"models": [{
            "name": "qwen3.6-27b:latest", "size": 10, "size_vram": 10,
            "context_length": 262144, "expires_at": "2026-08-17T09:00:00Z",
        }]}

    monkeypatch.setattr("codexteam_tools.activity._ollama_json", fake)
    fleet = collect_model_fleet()

    assert fleet["available"] is True
    qwen = next(item for item in fleet["models"] if item["model_id"] == "qwen36-27b")
    assert qwen["loaded"] is True
    assert qwen["context_length"] == 262144
    assert qwen["processor"] == "GPU"
    assert "uncurated:latest" not in json.dumps(fleet)


def test_model_fleet_degrades_when_ollama_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "codexteam_tools.activity._ollama_json",
        lambda *args: (_ for _ in ()).throw(OSError("offline")),
    )
    assert collect_model_fleet() == {
        "available": False, "error": "ollama_unavailable", "models": [],
    }


def test_fleet_activity_counts_visible_assignments():
    fleet = {"available": True, "models": [{"model_id": "qwen36-27b"}]}
    attempts = [
        {"model": "qwen36-27b", "display_status": "running"},
        {"model": "qwen36-27b", "display_status": "finalized"},
    ]
    model = attach_fleet_activity(fleet, attempts)["models"][0]
    assert model["assigned_attempts"] == 2
    assert model["running_attempts"] == 1


def test_task_activity_uses_latest_attempt_and_hides_completed_canonical_task(tmp_path: Path):
    project = _attempt(tmp_path, status="finalized")
    (project / "TASKS.md").write_text(
        "# Tasks\n\n| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Review product | Completed | reviewer | Passed | evidence |\n"
    )
    activity = collect_team_activity(tmp_path)
    assert build_task_activity(activity["attempts"]) == []
    tasks = build_task_activity(activity["attempts"], include_history=True)
    assert tasks[0]["objective"] == "Review product"
    assert tasks[0]["severity"] == "complete"


def test_task_activity_filters_and_counts_current_tasks(tmp_path: Path):
    _attempt(tmp_path, status="running")
    activity = collect_team_activity(
        tmp_path, now=datetime(2026, 8, 17, 8, 2, tzinfo=timezone.utc)
    )
    tasks = build_task_activity(activity["attempts"])
    assert task_activity_counts(tasks) == {
        "visible": 1, "running": 1, "attention": 0, "waiting": 0,
    }
    assert filter_task_activity(tasks, state="running") == tasks
    assert filter_task_activity(tasks, state="attention") == []
    assert filter_task_activity(tasks, query="demo project") == tasks


def test_finalized_attempt_for_open_task_remains_active_and_waiting(tmp_path: Path):
    project = _attempt(tmp_path, status="finalized")
    (project / "TASKS.md").write_text(
        "# Tasks\n\n| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Review product | In Progress | reviewer | Pending | - |\n"
    )
    tasks = build_task_activity(collect_team_activity(tmp_path)["attempts"])

    assert len(tasks) == 1
    assert tasks[0]["severity"] == "normal"
    assert task_activity_counts(tasks)["waiting"] == 1
    assert filter_task_activity(tasks, state="active") == tasks
    assert filter_task_activity(tasks, state="waiting") == tasks
    assert filter_task_activity(tasks, state="completed") == []
