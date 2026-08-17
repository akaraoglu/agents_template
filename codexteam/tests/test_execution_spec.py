from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import codexteam_tools.spawn as spawn
from codexteam_tools.execution_spec import (
    ExecutionSpecError,
    canonical_sha256,
    compile_execution_spec,
    load_execution_spec,
    validate_execution_spec,
)
from codexteam_tools.execution_registry import load_execution_registry


def _minimal_spec(**overrides):
    values = {
        "team_id": "team-1",
        "task_id": "T002",
        "attempt_id": "att-001",
        "role": "developer",
        "workspace_root": "/tmp/project",
        "handoff_source_path": "management/tasks/T002.md",
        "handoff_content_digest": "a" * 64,
        "role_policy_name": "codexteam_developer",
        "role_policy_version": "1.0",
        "role_policy_digest": "b" * 64,
        "agent_spec": None,
        "effective_policy_digest": "d" * 64,
        "guidance_files": ["implementation.md"],
        "guidance_digest": "c" * 64,
        "execution_profile": load_execution_registry().resolve(
            "codex", "qwen36-27b", "medium"
        ).reference(runtime_version=None, backend_material_digest="a" * 64),
        "sandbox_mode": "workspace-write",
        "trust_parent_sandbox": False,
        "additional_write_roots": [],
        "mcp_allowed_servers": [],
        "mcp_effective_servers": [],
        "mcp_missing_servers": [],
        "mcp_allowed_tools": {},
        "mcp_effective_tools": {},
        "bound_mcp_project": None,
        "task_write_scope": None,
        "gate_routing": {"gate": "development", "execution_surface": "worker"},
    }
    values.update(overrides)
    return compile_execution_spec(**values)


def _args(tmp_path: Path, monkeypatch, **overrides):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "qwen36-27b.config.toml").write_text(
        'model = "qwen"\nmodel_provider = "ollama_local"\n'
        'model_reasoning_effort = "high"\nmodel_verbosity = "medium"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    values = {
        "backend": "codex", "draft_format": None, "phase": "draft",
        "profile": "qwen36-27b", "reasoning_effort": "medium", "team": "team-1",
        "task": "T002", "attempt": "att-001", "role": "developer",
        "workspace": str(workspace), "prompt_file": None,
        "prompt": "SECRET-PROMPT-CONTENT", "skill_file": [], "add_dir": [],
        "trust_parent_sandbox": False, "run_guard": False, "timeout": 10,
        "result_dir": "results", "dry_run": False,
    }
    values.update(overrides)
    if values["phase"] != "draft":
        values["backend"] = None
        values["profile"] = None
        values["reasoning_effort"] = None
    return argparse.Namespace(**values)


def _events(message: str) -> spawn.ProcessResult:
    thread = "0199a213-81c0-7800-8aa1-bbab2a035a53"
    events = (
        json.dumps({"type": "thread.started", "thread_id": thread}) + "\n"
        + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": message}}) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {}}) + "\n"
    )
    return spawn.ProcessResult(0, events, "", 0.1)


def test_execution_spec_digest_is_deterministic_and_tampering_fails():
    first = _minimal_spec()
    second = _minimal_spec()
    assert first == second
    assert first["execution_spec_id"].startswith("exec-")
    assert len(first["execution_spec_id"]) == 37
    assert canonical_sha256({"b": 1, "a": 2}) == canonical_sha256({"a": 2, "b": 1})
    tampered = json.loads(json.dumps(first))
    tampered["execution_profile"]["profile"]["id"] = "codex/other"
    with pytest.raises(ExecutionSpecError, match="digest mismatch"):
        validate_execution_spec(tampered)


def test_execution_spec_accepts_agent_spec_reference_and_rejects_provider_default_effort_claim():
    value = _minimal_spec()
    value["agent_spec"] = {"id": "python-developer", "version": "1.0", "digest": "e" * 64}
    value["execution_spec_digest"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "execution_spec_digest"}
    )
    assert validate_execution_spec(value)["agent_spec"]["id"] == "python-developer"
    profile = load_execution_registry().resolve(
        "opencode", "qwen36-27b", "provider_default"
    ).reference(runtime_version=None, backend_material_digest="b" * 64)
    profile["reasoning"]["effective"] = "medium"
    with pytest.raises(ExecutionSpecError, match="provider_default"):
        _minimal_spec(execution_profile=profile)


def test_dry_run_builds_spec_without_writing(tmp_path: Path, monkeypatch, capsys):
    args = _args(tmp_path, monkeypatch)
    code = spawn.main([
        "--phase", "draft", "--backend", args.backend, "--profile", args.profile,
        "--reasoning-effort", args.reasoning_effort, "--team", args.team,
        "--task", args.task, "--attempt", args.attempt, "--role", args.role,
        "--workspace", args.workspace, "--prompt", args.prompt, "--dry-run",
    ])
    assert code == 0
    details = json.loads(capsys.readouterr().out)
    assert details["execution_spec"]["agent_spec"] is None
    assert details["execution_spec"]["handoff"]["source_path"] is None
    assert not Path(details["execution_spec_path"]).exists()


def test_draft_writes_spec_before_worker_and_stores_no_prompt(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(_args(tmp_path, monkeypatch))
    observed = {}

    def worker(*args, **kwargs):
        observed["exists"] = request.execution_spec_path.is_file()
        observed["value"] = load_execution_spec(request.execution_spec_path)
        return _events("DRAFT T002/att-001\nOutcome: done")

    monkeypatch.setattr(spawn, "run_process", worker)
    outcome, code = spawn.run_spawn(request)
    assert code == 0
    assert observed["exists"] is True
    serialized = request.execution_spec_path.read_text()
    assert "SECRET-PROMPT-CONTENT" not in serialized
    assert "prompt" not in observed["value"]
    assert observed["value"]["agent_spec"] is None
    session = json.loads(request.session_path.read_text())
    assert session["execution_spec"]["digest"] == observed["value"]["execution_spec_digest"]
    assert outcome["execution_spec"] == session["execution_spec"]


def test_pre_thread_failure_retains_spec_and_tamper_blocks_resume(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(_args(tmp_path, monkeypatch))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: spawn.ProcessResult(1, "", "failed", 0.1)
    )
    _, code = spawn.run_spawn(request)
    assert code == 1
    assert request.execution_spec_path.is_file()
    assert not request.session_path.exists()

    # A resumable session validates both its reference and sidecar digest.
    request2 = spawn.prepare_request(_args(tmp_path / "second", monkeypatch))
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: _events("DRAFT"))
    spawn.run_spawn(request2)
    value = json.loads(request2.execution_spec_path.read_text())
    value["identity"]["role"] = "reviewer"
    request2.execution_spec_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="digest mismatch"):
        spawn.prepare_request(
            _args(tmp_path / "second", monkeypatch, phase="feedback", prompt="revise")
        )


def test_worker_execution_spec_tampering_fails_before_result_or_session_write(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(_args(tmp_path, monkeypatch))

    def tamper(*args, **kwargs):
        value = json.loads(request.execution_spec_path.read_text())
        value["identity"]["role"] = "reviewer"
        request.execution_spec_path.write_text(json.dumps(value))
        return _events("DRAFT")

    monkeypatch.setattr(spawn, "run_process", tamper)
    with pytest.raises(ValueError, match="digest mismatch"):
        spawn.run_spawn(request)
    assert not request.session_path.exists()


def test_missing_referenced_spec_is_reported_invalid(tmp_path: Path):
    from codexteam_tools.subagent_status import collect_subagent_status

    project = tmp_path / "project"
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    attempt.mkdir(parents=True)
    (attempt / "session.json").write_text(json.dumps({
        "execution_spec": {
            "contract": "execution-spec",
            "path": "execution-spec.json",
            "digest": "a" * 64,
        }
    }))
    record = collect_subagent_status(project)[0]
    assert record["execution_spec_status"] == "invalid"
    assert "missing" in record["execution_spec_error"]


def test_malformed_execution_spec_reference_is_reported_invalid(tmp_path: Path):
    from codexteam_tools.subagent_status import collect_subagent_status

    project = tmp_path / "project"
    attempt = project / ".codexteam/runtime/sessions/team-1/T002/att-001"
    attempt.mkdir(parents=True)
    spec = _minimal_spec(workspace_root=str(project))
    (attempt / "execution-spec.json").write_text(json.dumps(spec))
    (attempt / "session.json").write_text(json.dumps({
        "execution_spec": {
            "contract": "wrong",
            "path": "execution-spec.json",
            "digest": spec["execution_spec_digest"],
        }
    }))
    record = collect_subagent_status(project)[0]
    assert record["execution_spec_status"] == "invalid"
    assert "reference mismatch" in record["execution_spec_error"]


def test_session_and_result_paths_are_unchanged(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(_args(tmp_path, monkeypatch))
    assert request.session_path.name == "session.json"
    assert request.result_path == request.workspace / "results/T002-att-001.json"


def test_prompt_file_records_path_and_digest_without_content(tmp_path: Path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    handoff = Path(args.workspace) / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("PRIVATE-HANDOFF-CONTENT\n")
    request = spawn.prepare_request(
        _args(
            tmp_path,
            monkeypatch,
            prompt=None,
            prompt_file=str(handoff),
        )
    )
    assert request.execution_spec["handoff"]["source_path"] == "management/tasks/T002.md"
    assert "PRIVATE-HANDOFF-CONTENT" not in json.dumps(request.execution_spec)
