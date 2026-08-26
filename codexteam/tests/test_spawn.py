import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

import codexteam_tools.spawn as spawn
from codexteam_tools import opencode_backend
from codexteam_tools.contracts import validate_result
from codexteam_tools.execution_registry import load_execution_registry
from codexteam_tools.execution_spec import execution_spec_reference


THREAD_ID = "0199a213-81c0-7800-8aa1-bbab2a035a53"


def draft_message(**overrides) -> str:
    value = {
        "schema_version": "1.0",
        "outcome": "Completed the assigned work.",
        "evidence": [],
        "findings": [],
        "limitations": [],
        "proposed_disposition": "ready_for_review",
    }
    value.update(overrides)
    return json.dumps(value)


def write_artifact_report(request, **overrides) -> None:
    request.artifact_report_path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "version": 1,
        "summary": "Completed and verified the assigned work.",
        "evidence": ["results/evidence.txt"],
        "limitations": [],
    }
    value.update(overrides)
    request.artifact_report_path.write_text(json.dumps(value))


def request_args(tmp_path: Path, monkeypatch, **overrides):
    monkeypatch.setattr(
        spawn,
        "host_availability",
        lambda *args, **kwargs: {"host_available": True, "reason_unavailable": None},
    )
    codex_home = tmp_path / "source-codex-home"
    codex_home.mkdir(exist_ok=True)
    (codex_home / "qwen36-27b.config.toml").write_text(
        'model = "qwen3.6-27b"\n'
        'model_provider = "ollama_local"\n'
        'model_catalog_json = "/tmp/local-models.json"\n'
        'model_reasoning_effort = "high"\n'
        'model_verbosity = "medium"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    values = {
        "backend": "codex",
        "phase": "draft",
        "profile": "qwen36-27b",
        "reasoning_effort": "medium",
        "team": "team-1",
        "task": "T002",
        "attempt": "att-001",
        "role": "developer",
        "workspace": str(workspace),
        "prompt_file": None,
        "prompt": "Implement the task.",
        "skill_file": [],
        "add_dir": [],
        "trust_parent_sandbox": False,
        "run_guard": False,
        "timeout": 10,
        "result_dir": "results",
        "dry_run": False,
        "feedback_mode": None,
    }
    values.update(overrides)
    if values["phase"] != "draft":
        values["backend"] = None
        values["profile"] = None
        values["reasoning_effort"] = None
    elif values["backend"] == "opencode" and "reasoning_effort" not in overrides:
        values["reasoning_effort"] = "provider_default"
    report = workspace / "results/reports" / f"{values['task']}-{values['attempt']}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    if not report.exists():
        report.write_text(json.dumps({
            "version": 1,
            "summary": "Completed and verified the assigned work.",
            "evidence": [report.relative_to(workspace).as_posix()],
            "limitations": [],
        }))
    return argparse.Namespace(**values)


def split_request_args(tmp_path: Path, monkeypatch, **overrides):
    args = request_args(tmp_path, monkeypatch)
    control = tmp_path / "control"
    git_root = tmp_path / "repository"
    work = git_root / "component"
    decoy = git_root / "decoy"
    control.mkdir()
    work.mkdir(parents=True)
    decoy.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=git_root, check=True)
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": "component", "work_root": str(work), "git_root": str(git_root),
            "git_prefix": "component", "remote_url": None, "write_policy": "task-owned",
        }],
    }))
    values = vars(args) | {
        "workspace": None,
        "control_root": str(control),
        "work_root": str(work),
        "repo_id": "component",
    }
    values.update(overrides)
    return argparse.Namespace(**values), control, work, git_root, decoy


def event_stream(message: str, *, thread_id: str = THREAD_ID, completed: bool = True) -> str:
    events = [
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
    ]
    if completed:
        events.append({"type": "turn.completed", "usage": {}})
    return "".join(json.dumps(event) + "\n" for event in events)


def successful_process(message: str, *, thread_id: str = THREAD_ID) -> spawn.ProcessResult:
    return spawn.ProcessResult(0, event_stream(message, thread_id=thread_id), "", 0.2)


def test_split_request_routes_control_and_work_and_pins_binding(tmp_path: Path, monkeypatch):
    args, control, work, git_root, decoy = split_request_args(tmp_path, monkeypatch)
    handoff = control / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "Implement the task.\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)

    request = spawn.prepare_request(args)
    turn = spawn.prepare_turn(request)
    command = spawn.build_command(request, turn, executable="codex")

    assert request.workspace == request.work_root == work
    assert request.control_root == control
    assert request.git_root == git_root
    assert request.git_prefix == "component"
    assert command[command.index("-C") + 1] == str(work)
    assert request.worker_add_dirs == (request.session_dir / "exchange",)
    gated_request = replace(request, gate_routing={
        "gate": "development", "execution_surface": "worker",
    })
    assert gated_request.worker_add_dirs == (request.session_dir / "exchange",)
    assert request.result_path.is_relative_to(control)
    assert request.session_path.is_relative_to(control)
    assert not request.result_path.is_relative_to(work)
    assert request.execution_spec["schema_version"] == "1.1"
    assert request.execution_spec["identity"] == {
        "team_id": "team-1", "task_id": "T002", "attempt_id": "att-001",
        "role": "developer", "workspace_root": str(work),
        "control_root": str(control), "work_root": str(work),
        "git_root": str(git_root), "git_prefix": "component", "repo_id": "component",
    }
    assert request.effective_mcp_servers == ()
    assert not (work / ".codexteam").exists()
    assert list(decoy.iterdir()) == []

    def worker(*_args, **_kwargs):
        (work / "src").mkdir()
        (work / "src/main.py").write_text("VALUE = 1\n")
        write_artifact_report(request, evidence=["src/main.py"])
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", worker)
    outcome, code = spawn.run_spawn(request)
    assert code == 0 and outcome["status"] == "draft_ready"
    session = json.loads(request.session_path.read_text())
    assert "src/main.py" in session["worker_change_manifest"]
    assert request.artifact_report_path.is_file()
    assert not (work / "results").exists()
    assert not (work / ".codexteam").exists()
    assert list(decoy.iterdir()) == []


def test_split_continuation_rejects_repository_drift(tmp_path: Path, monkeypatch):
    args, control, work, _git_root, _decoy = split_request_args(tmp_path, monkeypatch)
    request = spawn.prepare_request(args)
    def worker(*_args, **_kwargs):
        write_artifact_report(request)
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", worker)
    spawn.run_spawn(request)
    registry = json.loads((control / "REPOSITORIES.json").read_text())
    registry["repositories"][0]["git_prefix"] = "wrong"
    (control / "REPOSITORIES.json").write_text(json.dumps(registry))
    args.phase = "feedback"
    args.backend = args.profile = args.reasoning_effort = None
    args.prompt = "revise"
    with pytest.raises(ValueError, match="git_prefix mismatch"):
        spawn.prepare_request(args)


def test_split_workspace_snapshot_uses_git_visible_subtree(tmp_path: Path, monkeypatch):
    args, _control, work, git_root, decoy = split_request_args(tmp_path, monkeypatch)
    (work / "tracked.py").write_text("tracked\n")
    (work / "untracked.py").write_text("untracked\n")
    (work / "ignored.bin").write_bytes(b"ignored")
    (decoy / "outside.py").write_text("outside\n")
    (git_root / ".gitignore").write_text("*.bin\n")
    subprocess.run(
        ["git", "add", ".gitignore", "component/tracked.py"], cwd=git_root, check=True
    )
    request = spawn.prepare_request(args)

    snapshot = spawn._snapshot_request_workspace(request)

    assert set(snapshot) == {"tracked.py", "untracked.py"}


def test_split_workspace_snapshot_skips_nested_git_root_directory(
    tmp_path: Path, monkeypatch
):
    args, _control, work, _git_root, _decoy = split_request_args(tmp_path, monkeypatch)
    nested = work / "nested"
    nested.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
    (nested / "source.py").write_text("nested\n")
    request = spawn.prepare_request(args)

    snapshot = spawn._snapshot_request_workspace(request)

    assert "nested" not in snapshot
    assert not any(path.startswith("nested/") for path in snapshot)


def test_split_feedback_resume_configures_writable_exchange(tmp_path: Path, monkeypatch):
    args, _control, _work, _git_root, _decoy = split_request_args(tmp_path, monkeypatch)
    draft = spawn.prepare_request(args)
    def worker(*_args, **_kwargs):
        write_artifact_report(draft)
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", worker)
    spawn.run_spawn(draft)
    args.phase = "feedback"
    args.backend = args.profile = args.reasoning_effort = None
    args.prompt = "revise"
    feedback = spawn.prepare_request(args)

    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))

    assert command[:3] == ["codex", "exec", "resume"]
    assert "--add-dir" not in command
    assert (
        "sandbox_workspace_write.writable_roots="
        f"{json.dumps([str(path) for path in feedback.worker_add_dirs])}"
    ) in command


def test_split_finalization_accepts_control_exchange_checkpoint(tmp_path: Path, monkeypatch):
    args, _control, work, _git_root, _decoy = split_request_args(tmp_path, monkeypatch)
    draft = spawn.prepare_request(args)
    (work / "results").mkdir()
    (work / "results/evidence.txt").write_text("passed\n")
    def worker(*_args, **_kwargs):
        write_artifact_report(draft)
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", worker)
    spawn.run_spawn(draft)
    args.phase = "final"
    args.backend = args.profile = args.reasoning_effort = None
    args.prompt = "accept"
    final = spawn.prepare_request(args)

    result, code = spawn.run_spawn(final)

    assert code == 0
    assert result["status"] == "completed"
    assert final.result_path.is_file()


def opencode_stream(message: str, *, session_id: str = THREAD_ID) -> str:
    events = [
        {"type": "step_start", "sessionID": session_id, "part": {}},
        {"type": "text", "sessionID": session_id, "part": {"text": message}},
        {
            "type": "step_finish",
            "sessionID": session_id,
            "part": {
                "reason": "stop",
                "tokens": {
                    "input": 10,
                    "output": 4,
                    "reasoning": 2,
                    "cache": {"read": 3, "write": 1},
                },
            },
        },
    ]
    return "".join(json.dumps(event) + "\n" for event in events)


def successful_opencode_process(message: str) -> spawn.ProcessResult:
    return spawn.ProcessResult(0, opencode_stream(message), "", 0.2)


def configure_mcp_servers(source_home: Path, projects_root: Path) -> None:
    (source_home / "config.toml").write_text(
        f"""
[mcp_servers.codexteam-context]
command = "context-server"
args = ["--projects-root", {json.dumps(str(projects_root))}]

[mcp_servers.github-readonly]
command = "github-server"

[mcp_servers.playwright]
command = "playwright-server"

[mcp_servers.local-docs]
command = "local-docs-server"
""".lstrip()
    )


def configure_test_gates(workspace: Path, *, integration_surface: str) -> None:
    management = workspace / "management"
    management.mkdir(exist_ok=True)
    (management / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\n'
        'verification_paths = ["src/**", "tests/**"]\n\n'
        '[development]\nconfigured = true\nexecution_surface = "worker"\n'
        'expected_max_seconds = 30\ncommands = [["true"]]\n\n'
        f'[integration]\nconfigured = true\nexecution_surface = "{integration_surface}"\n'
        'expected_max_seconds = 60\nincludes = ["development"]\n'
        'commands = [["true"]]\n'
    )


def mcp_overrides(command: list[str]) -> set[str]:
    return {
        command[index + 1]
        for index, argument in enumerate(command[:-1])
        if argument == "-c" and command[index + 1].startswith("mcp_servers.")
    }


def run_draft(tmp_path: Path, monkeypatch) -> tuple[spawn.SpawnRequest, dict]:
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    (request.workspace / "src").mkdir()
    (request.workspace / "src" / "main.py").write_text("VALUE = 1\n")
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("passed\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process(
            "DRAFT T002/att-001\n\nOutcome: implemented\nEvidence: focused tests pass\n"
            "Uncertainties or conflicts: none\nProposed disposition: ready for review"
        ),
    )
    outcome, code = spawn.run_spawn(request)
    assert code == 0
    return request, outcome


def test_prepare_request_uses_deterministic_result_and_session_paths(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    assert request.task_id == "T002"
    assert request.result_path == request.workspace / "results" / "T002-att-001.json"
    assert request.session_path == (
        request.workspace
        / ".codexteam"
        / "runtime"
        / "sessions"
        / "team-1"
        / "T002"
        / "att-001"
        / "session.json"
    )


def test_new_attempt_defaults_to_artifact_report_contract(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    request = spawn.prepare_request(args)

    assert request.draft_format == "artifact-report-v1"
    assert request.artifact_report_path == request.workspace / "results/reports/T002-att-001.json"
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))
    assert "Write the artifact report" in prompt
    assert "Terminal output is diagnostic only" in prompt


def test_execution_class_derives_and_pins_timeout(tmp_path: Path, monkeypatch):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen38-27b-context",
        reasoning_effort="medium", timeout=None
    )
    workspace = Path(args.workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n"
        "## Execution Class\n\n- `complex`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)
    assert request.execution_class == "complex"
    assert request.timeout_seconds == 1200
    spawn._prepare_session_storage(request, initial=True, session=None)
    contract = json.loads((request.session_dir / spawn.HANDOFF_CONTRACT_FILENAME).read_text())
    assert contract["execution_class"] == "complex"
    assert contract["timeout_seconds"] == 1200


def test_explicit_timeout_overrides_execution_class(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, timeout=900)
    workspace = Path(args.workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n"
        "## Execution Class\n\n- `complex`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)
    assert request.timeout_seconds == 900


def test_continuation_rejects_timeout_drift(tmp_path: Path, monkeypatch):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen38-27b-context",
        reasoning_effort="medium", timeout=900
    )
    workspace = Path(args.workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n"
        "## Execution Class\n\n- `complex`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    draft = spawn.prepare_request(args)
    assert draft.execution_spec is not None
    spawn._prepare_session_storage(draft, initial=True, session=None)
    session = {
        "schema_version": "1.0", "team_id": draft.team_id, "task_id": draft.task_id,
        "attempt_id": draft.attempt_id, "agent_role": draft.role,
        "workspace_root": str(draft.workspace), "thread_id": THREAD_ID, "turn_count": 1,
        "last_phase": "draft", "last_status": "draft_ready",
        "last_turn_path": ".codexteam/runtime/placeholder", "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z", "turns": [{
            "number": 1, "phase": "draft", "status": "draft_ready", "duration_seconds": 1,
        }], "execution_spec": execution_spec_reference(draft.execution_spec),
        "handoff_contract_sha256": hashlib.sha256(
            (draft.session_dir / spawn.HANDOFF_CONTRACT_FILENAME).read_bytes()
        ).hexdigest(), "backend_version": "1.18.18",
        "backend_config_digest": draft.backend_config_digest,
    }
    spawn._write_session(draft.session_path, session)
    with pytest.raises(ValueError, match="continuation timeout"):
        spawn.prepare_request(request_args(
            tmp_path, monkeypatch, backend="opencode", profile="qwen38-27b-context",
            phase="feedback", prompt="continue", timeout=1200,
        ))


def test_continuation_tolerates_unrelated_registry_growth(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    registry = load_execution_registry()
    registry.digest = "f" * 64
    monkeypatch.setattr(spawn, "load_execution_registry", lambda: registry)

    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="continue",
    ))

    assert feedback.execution_profile.registry_digest == "f" * 64


def test_complex_checkpoint_sequence_is_same_session(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, timeout=None)
    workspace = Path(args.workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n"
        "## Execution Class\n\n- `complex`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)
    assert spawn._required_complex_checkpoint(request) == "source_focused_tests"
    assert spawn._complex_checkpoint_error(
        request, {"checkpoint": "development_gate"}
    ) == "complex work requires checkpoint 'source_focused_tests', got 'development_gate'"


def test_complex_developer_finalizes_after_focused_checkpoint_and_launcher_gate(
    tmp_path: Path, monkeypatch
):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen38-27b-context",
        reasoning_effort="medium", timeout=None
    )
    workspace = Path(args.workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n"
        "## Execution Class\n\n- `complex`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)
    (workspace / "results").mkdir(exist_ok=True)
    (workspace / "results/evidence.txt").write_text("passed\n")
    write_artifact_report(request, checkpoint="source_focused_tests")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    draft_outcome, draft_code = spawn.run_spawn(request)
    assert draft_code == 0, draft_outcome.get("errors")
    session = json.loads(request.session_path.read_text())
    assert session["complex_checkpoint"] == "source_focused_tests"

    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
        phase="final", prompt="accept", timeout=None,
    ))
    result, code = spawn.run_spawn(final)
    assert code == 0
    assert result["status"] == "completed"
    assert json.loads(final.session_path.read_text())["complex_checkpoint"] == "source_focused_tests"


def test_artifact_result_finalization_is_provider_free_and_launcher_owned(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch)
    configure_test_gates(Path(args.workspace), integration_surface="lead_host")
    request = spawn.prepare_request(args)
    (request.workspace / "src").mkdir()
    (request.workspace / "results").mkdir(exist_ok=True)
    (request.workspace / "results/evidence.txt").write_text("passed\n")
    write_artifact_report(request)

    def draft_process(*args, **kwargs):
        (request.workspace / "src/main.py").write_text("VALUE = 1\n")
        return successful_process("terminal prose is ignored")

    monkeypatch.setattr(spawn, "run_process", draft_process)
    draft, draft_code = spawn.run_spawn(request)
    assert draft_code == 0
    assert draft["status"] == "draft_ready"

    final = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT",
            result_status="completed",
        )
    )
    monkeypatch.setattr(
        spawn,
        "adapter_for",
        lambda backend: (_ for _ in ()).throw(AssertionError("provider accessed")),
    )
    persisted, final_code = spawn.run_spawn(final)

    assert any(
        item["artifact_ref"] == "results/gates/development.json"
        and item["type"] == "test_output"
        for item in persisted["evidence"]
    )

    assert final_code == 0
    assert persisted["status"] == "completed"
    assert persisted["team_id"] == "team-1"
    assert persisted["file_changes"] == [{"path": "src/main.py", "action": "created"}]
    assert persisted["output"] == {
        "exit_code": 0, "stdout_tail": "", "stderr_tail": "", "duration_seconds": 0.0,
    }
    assert json.loads(final.session_path.read_text())["turns"][-1]["duration_seconds"] == 0.0


@pytest.mark.parametrize("status", ("blocked", "failed", "partial", "needs_review"))
def test_artifact_finalization_uses_explicit_lead_status(
    tmp_path: Path, monkeypatch, status: str
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("evidence\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="close", result_status=status,
    ))

    result, code = spawn.run_spawn(final)

    assert result["status"] == status
    assert code == (0 if status == "needs_review" else 1)


def test_result_status_is_rejected_before_finalization(tmp_path: Path, monkeypatch):
    with pytest.raises(ValueError, match="only for finalization"):
        spawn.prepare_request(request_args(
            tmp_path, monkeypatch, result_status="completed",
        ))


def test_artifact_finalization_rolls_back_result_and_session_on_state_failure(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("evidence\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))
    session_before = final.session_path.read_bytes()
    state_before = (final.session_dir / "turn-state.json").read_bytes()
    monkeypatch.setattr(
        spawn,
        "_write_turn_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("state write failed")),
    )

    with pytest.raises(OSError, match="state write failed"):
        spawn.run_spawn(final)

    assert not final.result_path.exists()
    assert final.session_path.read_bytes() == session_before
    assert (final.session_dir / "turn-state.json").read_bytes() == state_before


def test_artifact_finalization_rejects_existing_lock_before_reading_state(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("evidence\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))
    lock = final.session_dir / "turn.lock"
    lock.write_text(str(spawn.os.getpid()))
    session_before = final.session_path.read_bytes()

    with pytest.raises(ValueError, match="already in progress"):
        spawn.run_spawn(final)

    assert final.session_path.read_bytes() == session_before
    assert not final.result_path.exists()


def test_artifact_finalization_recovers_dead_owner_lock(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("evidence\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))
    lock = final.session_dir / "turn.lock"
    lock.write_text("999999999")

    result, code = spawn.run_spawn(final)

    assert code == 0
    assert result["status"] == "completed"
    assert not lock.exists()


def test_direct_context_rejects_codex_backend(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    workspace = Path(args.workspace)
    source = workspace / "src/main.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    configure_test_gates(workspace, integration_surface="lead_host")
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/main.py`\n- `results/report.md`\n\n"
        "## Context Mode\n\n- `direct`\n\n## Result Report\n\n- `results/report.md`\n\n"
        "## Direct Context\n\n- `src/main.py:1-1`\n\n"
        "## Verification Commands\n\n- `[\"true\"]`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    with pytest.raises(ValueError, match="requires the OpenCode backend"):
        spawn.prepare_request(args)


def test_artifact_finalization_rejects_changes_after_latest_accepted_turn(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("evidence\n")
    write_artifact_report(request)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    session = json.loads(request.session_path.read_text())
    session["last_status"] = "correction_needed"
    session["turn_count"] = 2
    session["worker_change_manifest"]["src/unaccepted.py"] = {
        "action": "created", "sha256": "a" * 64,
    }
    request.session_path.write_text(json.dumps(session))
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))

    with pytest.raises(ValueError, match="latest worker turn"):
        spawn.run_spawn(final)

    assert not final.result_path.exists()


def test_handoff_prompt_requires_artifact_report_and_contains_task_once(tmp_path: Path, monkeypatch):
    task = "Implement the uniquely named task once."
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch, prompt=task))
    handoff = spawn.build_handoff(request)
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))
    assert handoff["workspace_root"] == str(request.workspace)
    assert any("Return a draft" in item for item in handoff["completion_criteria"])
    assert "Do not emit result" in prompt
    assert "results/reports/T002-att-001.json" in prompt
    assert "Terminal output is diagnostic only" in prompt
    assert prompt.count(task) == 1
    assert "[TASK DETAILS]" not in prompt


def test_invalid_artifact_report_stays_resumable(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.artifact_report_path.write_text('{"version":1}')
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    outcome, code = spawn.run_spawn(request)
    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("missing required artifact report fields" in error for error in outcome["errors"])


def test_terminal_text_does_not_affect_valid_artifact_report(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("malformed { terminal")
    )
    outcome, code = spawn.run_spawn(request)
    assert code == 0
    assert outcome["status"] == "draft_ready"


def test_session_draft_format_duplicate_is_rejected(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    session["draft_format"] = "compact-json"
    request.session_path.write_text(json.dumps(session))

    with pytest.raises(ValueError, match="unknown fields"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
        )


def test_specialist_agent_spec_is_pinned_with_guidance(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, agent_spec="python-developer")
    )
    assert request.role == "developer"
    assert request.agent_spec.agent_spec_id == "python-developer"
    assert request.skill_files[-1].name == "python-specialization.md"
    assert request.execution_spec["agent_spec"] == request.agent_spec.reference()
    assert request.profile == "qwen36-27b"
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT")
    )
    spawn.run_spawn(request)
    assert request.agent_spec_path.is_file()
    assert request.execution_spec["agent_spec"]["id"] == "python-developer"


def test_agent_spec_override_on_continuation_is_rejected(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="valid only when creating"):
        spawn.prepare_request(
            request_args(
                tmp_path, monkeypatch, phase="feedback", prompt="continue",
                agent_spec="python-developer",
            )
        )


def test_pre_cutover_phase_two_attempt_is_rejected(
    tmp_path: Path, monkeypatch
):
    request, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    spec = json.loads(request.execution_spec_path.read_text())
    spec["backend"] = spec.pop("execution_profile")["backend"]
    request.execution_spec_path.write_text(json.dumps(spec))

    with pytest.raises(ValueError, match="execution spec"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
        )


def test_malformed_draft_format_sidecar_fails_closed(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    request.draft_format_path.write_text('{"schema_version":"1.0","draft_format":"bad"}')

    with pytest.raises(ValueError, match="unsupported contract"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
        )


def test_session_additions_are_rejected(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    session["future_addition"] = {"preserve": True}
    request.session_path.write_text(json.dumps(session))
    with pytest.raises(ValueError, match="unknown fields"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
        )


def test_draft_rejects_missing_evidence_artifact(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    write_artifact_report(request, evidence=["results/missing.txt"])
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("ignored"),
    )

    outcome, code = spawn.run_spawn(request)

    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("does not name an existing regular file" in error for error in outcome["errors"])


def test_draft_rejects_escaping_evidence_symlink_without_losing_session(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    outside = tmp_path / "outside"
    outside.mkdir()
    evidence_link = request.workspace / "evidence-link"
    evidence_link.symlink_to(outside, target_is_directory=True)
    write_artifact_report(request, evidence=["evidence-link/proof.txt"])
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("ignored"),
    )

    outcome, code = spawn.run_spawn(request)

    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("escapes workspace root" in error for error in outcome["errors"])
    session = json.loads(request.session_path.read_text())
    assert session["thread_id"] == THREAD_ID
    assert session["last_status"] == "correction_needed"


def test_tester_handoff_carries_host_only_gate_routing(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, role="tester", task="T003")
    configure_test_gates(Path(args.workspace), integration_surface="lead_host")
    request = spawn.prepare_request(args)

    handoff = spawn.build_handoff(request)
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))

    assert handoff["constraints"]["gate_routing"] == {
        "gate": "integration",
        "execution_surface": "lead_host",
        "worker_may_execute": False,
    }
    assert "launcher owns the configured integration gate" in prompt
    assert "do not launch the configured gate" in prompt


def test_direct_context_mode_disables_task_context_mcp(tmp_path: Path, monkeypatch):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
    )
    handoff = Path(args.workspace) / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    source = Path(args.workspace) / "src/main.js"
    source.parent.mkdir()
    source.write_text("line one\nline two\n")
    configure_test_gates(Path(args.workspace), integration_surface="lead_host")
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/main.js`\n- `results/task/REPORT.md`\n\n"
        "## Context Mode\n\n- `direct`\n\n"
        "## Result Report\n\n- `results/task/REPORT.md`\n\n"
        "## Direct Context\n\n- `src/main.js:1-2`\n\n"
        "## Verification Commands\n\n- `[\"true\"]`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)

    request = spawn.prepare_request(args)

    assert request.context_mode == "direct"
    assert request.effective_mcp_servers == ()
    assert request.effective_mcp_tools == ()
    assert spawn.build_handoff(request)["task_context"]["context_mode"] == "direct"
    config = json.loads(request.backend_config_path.read_text()) if request.backend_config_path.exists() else opencode_backend.build_config(
        model=request.model, role_name=request.role,
        role_instructions=request.effective_role_policy.developer_instructions,
        context_limit=request.execution_profile.model["context_limit"],
        output_limit=request.execution_profile.model["output_limit"],
        direct_mode=True, editable_paths=request.task_write_scope or (),
    )
    permissions = config["agent"][opencode_backend.AGENT]["permission"]
    assert permissions["read"] == permissions["grep"] == permissions["glob"] == "deny"
    assert permissions["list"] == "deny"
    assert permissions["bash"] == "deny"


def test_artifact_finalization_rejects_evidence_changed_after_acceptance(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request.result_dir.mkdir(exist_ok=True)
    evidence = request.result_dir / "evidence.txt"
    evidence.write_text("accepted\n")
    write_artifact_report(request, evidence=["results/evidence.txt"])
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("ignored")
    )
    assert spawn.run_spawn(request)[1] == 0
    evidence.write_text("changed\n")
    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))
    with pytest.raises(ValueError, match="evidence digest mismatch"):
        spawn.run_spawn(final)


def test_bounded_mcp_context_mode_enables_only_pinned_task_context(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b")
    handoff = Path(args.workspace) / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)

    request = spawn.prepare_request(args)

    assert request.context_mode == "bounded-mcp"
    assert request.effective_mcp_servers == ("codexteam-context",)
    assert request.effective_mcp_tools == (("codexteam-context", ("get_task_context",)),)


def test_direct_preflight_rejects_system_output_scope_before_launch(
    tmp_path: Path, monkeypatch
):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
    )
    workspace = Path(args.workspace)
    source = workspace / "src/main.js"
    source.parent.mkdir()
    source.write_text("value\n")
    configure_test_gates(workspace, integration_surface="lead_host")
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/**`\n- `results/**`\n\n"
        "## Context Mode\n\n- `direct`\n\n"
        "## Result Report\n\n- `results/task/REPORT.md`\n\n"
        "## Direct Context\n\n- `src/main.js:1-1`\n\n"
        "## Verification Commands\n\n- `[\"true\"]`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)

    with pytest.raises(ValueError, match="literal files"):
        spawn.run_spawn(request)

    state = json.loads((request.session_dir / "turn-state.json").read_text())
    assert state["status"] == "turn_failed"
    assert "literal files" in state["errors"][0]


def test_direct_attempt_ignores_terminal_contract_and_runs_launcher_verification(
    tmp_path: Path, monkeypatch
):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
    )
    workspace = Path(args.workspace)
    source = workspace / "src/main.js"
    source.parent.mkdir()
    source.write_text("const value = 1;\n")
    configure_test_gates(workspace, integration_surface="lead_host")
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/main.js`\n- `results/task/REPORT.md`\n\n"
        "## Context Mode\n\n- `direct`\n\n"
        "## Result Report\n\n- `results/task/REPORT.md`\n\n"
        "## Direct Context\n\n- `src/main.js:1-1`\n\n"
        "## Verification Commands\n\n- `[\"true\"]`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)

    observed = {}

    def worker(command, **kwargs):
        if "true" in command:
            return spawn.ProcessResult(0, "verification passed\n", "", 0.01)
        observed["prompt"] = kwargs["prompt"]
        source.write_text("const value = 2;\n")
        report = workspace / "results/task/REPORT.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Report\n\nDisposition: ready_for_review\n\nChanged the value.\n")
        return successful_opencode_process("not JSON and deliberately ignored")

    monkeypatch.setattr(spawn, "run_process", worker)
    def gate(*args, **kwargs):
        record = {
            "status": "passed", "gate": "development",
            "commands": [{"argv": ["true"], "exit_code": 0}],
        }
        path = workspace / "results/gates/development.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        return record
    monkeypatch.setattr(spawn, "run_gate", gate)
    monkeypatch.setattr(spawn, "validate_current_gate_record", lambda *args, **kwargs: gate())
    draft, code = spawn.run_spawn(request)

    assert code == 0, draft.get("errors")
    assert draft["status"] == "draft_ready"
    assert "[DIRECT CONTEXT: src/main.js:1-1]" in observed["prompt"]
    assert "const value = 1;" in observed["prompt"]
    semantic = json.loads(request.session_dir.joinpath("turns/001-draft.txt").read_text())
    assert semantic["summary"] == "developer completed T002; see results/task/REPORT.md."
    assert semantic["evidence"] == [
        "results/task/REPORT.md",
        "results/checks/T002-att-001.json",
        "results/gates/development.json",
    ]
    config = json.loads(request.backend_config_path.read_text())
    permissions = config["agent"][opencode_backend.AGENT]["permission"]
    assert permissions["read"] == permissions["bash"] == "deny"

    final = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="final", prompt="accept",
    ))
    monkeypatch.setattr(
        spawn,
        "adapter_for",
        lambda backend: (_ for _ in ()).throw(AssertionError("provider accessed")),
    )
    result, final_code = spawn.run_spawn(final)
    assert final_code == 0
    assert result["status"] == "completed"


def test_direct_feedback_replays_pinned_context_not_worker_modified_source(
    tmp_path: Path, monkeypatch
):
    args = request_args(
        tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
    )
    workspace = Path(args.workspace)
    source = workspace / "src/main.js"
    source.parent.mkdir()
    source.write_text("original context\n")
    configure_test_gates(workspace, integration_surface="lead_host")
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\n## Task Write Scope\n\n- `src/main.js`\n- `results/task/REPORT.md`\n\n"
        "## Context Mode\n\n- `direct`\n\n"
        "## Result Report\n\n- `results/task/REPORT.md`\n\n"
        "## Direct Context\n\n- `src/main.js:1-1`\n\n"
        "## Verification Commands\n\n- `[\"true\"]`\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)

    def worker(command, **kwargs):
        if "true" in command:
            return spawn.ProcessResult(0, "", "", 0.01)
        source.write_text("worker modified context\n")
        report = workspace / "results/task/REPORT.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("Disposition: ready_for_review\n")
        return successful_opencode_process("ignored")

    monkeypatch.setattr(spawn, "run_process", worker)
    def gate(*args, **kwargs):
        record = {
            "status": "passed", "gate": "development",
            "commands": [{"argv": ["true"], "exit_code": 0}],
        }
        path = workspace / "results/gates/development.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        return record
    monkeypatch.setattr(spawn, "run_gate", gate)
    assert spawn.run_spawn(request)[1] == 0
    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="revise report",
    ))
    prompt = spawn.build_prompt(feedback, spawn.prepare_turn(feedback))
    assert "original context" not in prompt
    assert "worker modified context" not in prompt
    assert "Correction: revise report" in prompt


def test_direct_report_requires_ready_disposition(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    request = replace(
        request,
        context_mode="direct",
        result_report="results/report.md",
    )
    report = request.workspace / "results/report.md"
    report.parent.mkdir(exist_ok=True)
    report.write_text("Disposition: blocked\n")
    with pytest.raises(ValueError, match="ready_for_review"):
        spawn._direct_semantic_result(request)


def test_direct_verification_uses_bwrap_and_scrubbed_environment(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    configure_test_gates(request.workspace, integration_surface="lead_host")
    request = replace(
        request,
        verification_commands=(("true",),),
        gate_routing={"gate": "development", "execution_surface": "worker"},
    )
    observed = {}
    monkeypatch.setenv("SECRET_TOKEN", "private")

    def process(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return spawn.ProcessResult(0, "", "", 0.01)

    def gate(*args, **kwargs):
        observed["command"] = [*kwargs["command_prefix"], "true"]
        observed["env"] = kwargs["environment"]
        path = request.workspace / "results/gates/development.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return {"status": "passed", "commands": []}

    monkeypatch.setattr(spawn, "run_gate", gate)
    spawn._run_direct_verification(request)
    assert observed["command"][0].endswith("bwrap")
    assert "--unshare-all" in observed["command"]
    assert "SECRET_TOKEN" not in observed["env"]


def test_finalization_has_no_provider_payload(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))

    assert prompt == "Finalization is deterministic and does not invoke a provider.\n"
    assert spawn.build_command(request, spawn.prepare_turn(request)) == []


def test_feedback_never_supplies_result_schema_and_final_has_no_command(
    tmp_path: Path, monkeypatch
):
    run_draft(tmp_path, monkeypatch)

    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    feedback_command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    assert "--output-schema" not in feedback_command

    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    final_turn = spawn.prepare_turn(final)
    assert spawn.build_command(final, final_turn) == []


def test_initial_command_persists_json_session_without_ephemeral(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    turn = spawn.prepare_turn(request)
    command = spawn.build_command(request, turn)
    assert command[:2] == ["codex", "exec"]
    assert "--profile" in command
    assert "--json" in command
    assert "-o" in command
    assert "--ephemeral" not in command
    assert "--last" not in command
    assert 'model_reasoning_effort="medium"' in command


def test_role_policy_enforces_mcp_servers_with_per_process_overrides(
    tmp_path: Path, monkeypatch
):
    developer_args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, Path(developer_args.workspace).parent)

    developer = spawn.prepare_request(developer_args)
    developer_command = spawn.build_command(developer, spawn.prepare_turn(developer))
    assert developer.effective_mcp_servers == (
        "codexteam-context",
        "local-docs",
    )
    assert developer.missing_mcp_servers == ()
    assert developer.mcp_context_project == "workspace"
    assert mcp_overrides(developer_command) == {
        "mcp_servers.codexteam-context.enabled=true",
        'mcp_servers.codexteam-context.enabled_tools=["get_task_context","search_repository","get_gate_status","get_change_summary"]',
        'mcp_servers.codexteam-context.env.CODEXTEAM_CONTEXT_PROJECT="workspace"',
        "mcp_servers.github-readonly.enabled=false",
        "mcp_servers.playwright.enabled=false",
        "mcp_servers.local-docs.enabled=true",
    }

    tester = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="tester")
    )
    tester_command = spawn.build_command(tester, spawn.prepare_turn(tester))
    assert tester.effective_mcp_servers == (
        "codexteam-context",
        "playwright",
    )
    assert tester.mcp_context_project == "workspace"
    assert mcp_overrides(tester_command) == {
        "mcp_servers.codexteam-context.enabled=true",
        'mcp_servers.codexteam-context.enabled_tools=["get_task_context","get_change_summary","get_gate_status"]',
        'mcp_servers.codexteam-context.env.CODEXTEAM_CONTEXT_PROJECT="workspace"',
        "mcp_servers.github-readonly.enabled=false",
        "mcp_servers.playwright.enabled=true",
        "mcp_servers.local-docs.enabled=false",
    }

    leader = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="leader")
    )
    leader_command = spawn.build_command(leader, spawn.prepare_turn(leader))
    assert leader.effective_mcp_servers == (
        "codexteam-context",
        "github-readonly",
    )
    assert leader.mcp_context_project is None
    assert mcp_overrides(leader_command) == {
        "mcp_servers.codexteam-context.enabled=true",
        "mcp_servers.github-readonly.enabled=true",
        "mcp_servers.playwright.enabled=false",
        "mcp_servers.local-docs.enabled=false",
    }

    architect = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="architect")
    )
    architect_command = spawn.build_command(architect, spawn.prepare_turn(architect))
    assert architect.effective_mcp_servers == ("local-docs",)
    assert mcp_overrides(architect_command) == {
        "mcp_servers.codexteam-context.enabled=false",
        "mcp_servers.github-readonly.enabled=false",
        "mcp_servers.playwright.enabled=false",
        "mcp_servers.local-docs.enabled=true",
    }

    reviewer = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="reviewer")
    )
    reviewer_command = spawn.build_command(reviewer, spawn.prepare_turn(reviewer))
    assert reviewer.effective_mcp_servers == ("codexteam-context",)
    assert reviewer.mcp_context_project == "workspace"
    assert mcp_overrides(reviewer_command) == {
        "mcp_servers.codexteam-context.enabled=true",
        'mcp_servers.codexteam-context.enabled_tools=["get_task_context","get_attempt_summary","validate_result_record","get_gate_status","get_change_summary"]',
        'mcp_servers.codexteam-context.env.CODEXTEAM_CONTEXT_PROJECT="workspace"',
        "mcp_servers.github-readonly.enabled=false",
        "mcp_servers.playwright.enabled=false",
        "mcp_servers.local-docs.enabled=false",
    }

    git_steward = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="git_steward")
    )
    git_steward_command = spawn.build_command(
        git_steward,
        spawn.prepare_turn(git_steward),
    )
    assert git_steward.effective_mcp_servers == ("codexteam-context",)
    assert git_steward.mcp_context_project == "workspace"
    assert mcp_overrides(git_steward_command) == {
        "mcp_servers.codexteam-context.enabled=true",
        'mcp_servers.codexteam-context.enabled_tools=["get_task_context","get_change_summary","get_gate_status"]',
        'mcp_servers.codexteam-context.env.CODEXTEAM_CONTEXT_PROJECT="workspace"',
        "mcp_servers.github-readonly.enabled=false",
        "mcp_servers.playwright.enabled=false",
        "mcp_servers.local-docs.enabled=false",
    }


def test_role_mcp_policy_reports_missing_server_without_enabling_it(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="tester")
    )

    assert request.effective_mcp_servers == ()
    assert request.missing_mcp_servers == (
        "codexteam-context",
        "playwright",
    )
    assert mcp_overrides(spawn.build_command(request, spawn.prepare_turn(request))) == set()


def test_mcp_tool_subsets_are_persisted_in_session_and_turn_state(
    tmp_path: Path,
    monkeypatch,
):
    args = request_args(tmp_path, monkeypatch, role="reviewer")
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, Path(args.workspace).parent)
    request = spawn.prepare_request(args)
    request.result_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )

    _outcome, code = spawn.run_spawn(request)

    assert code == 0
    session = json.loads(request.session_path.read_text())
    state = json.loads((request.session_dir / "turn-state.json").read_text())
    expected = {
        "codexteam-context": [
            "get_task_context",
            "get_attempt_summary",
            "validate_result_record",
            "get_gate_status",
            "get_change_summary",
        ]
    }
    permissions = request.execution_spec["permissions"]
    assert permissions["mcp_allowed_tools"] == expected
    assert permissions["mcp_effective_tools"] == expected
    assert permissions["bound_mcp_project"] == "workspace"


def test_context_binding_is_pinned_across_continuation_turns(
    tmp_path: Path,
    monkeypatch,
):
    args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, Path(args.workspace).parent)
    draft = spawn.prepare_request(args)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _outcome, code = spawn.run_spawn(draft)
    assert code == 0

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt="FEEDBACK: REVISE",
        )
    )
    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))

    assert feedback.mcp_context_project is None
    assert not any("CODEXTEAM_CONTEXT_PROJECT" in item for item in mcp_overrides(command))


def test_pre_cutover_continuation_without_execution_spec_is_rejected(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, Path(args.workspace).parent)
    draft = spawn.prepare_request(args)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _outcome, code = spawn.run_spawn(draft)
    assert code == 0
    session = json.loads(draft.session_path.read_text())
    session.pop("execution_spec", None)
    draft.session_path.write_text(json.dumps(session))
    draft.execution_spec_path.unlink()

    with pytest.raises(ValueError, match="execution_spec"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
        )


def test_context_binding_rejects_tampered_session(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, Path(args.workspace).parent)
    draft = spawn.prepare_request(args)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _outcome, code = spawn.run_spawn(draft)
    assert code == 0
    spec = json.loads(draft.execution_spec_path.read_text())
    spec["permissions"]["bound_mcp_project"] = "different-project"
    draft.execution_spec_path.write_text(json.dumps(spec))

    with pytest.raises(ValueError, match="digest mismatch"):
        spawn.prepare_request(
            request_args(
                tmp_path,
                monkeypatch,
                phase="feedback",
                prompt="FEEDBACK: REVISE",
            )
        )


def test_context_binding_rejects_workspace_outside_configured_projects_root(
    tmp_path: Path,
    monkeypatch,
):
    args = request_args(tmp_path, monkeypatch)
    configured_root = tmp_path / "different-projects"
    configured_root.mkdir()
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    configure_mcp_servers(source_home, configured_root)

    with pytest.raises(ValueError, match="must be a direct child"):
        spawn.prepare_request(args)


def test_worker_environment_disables_project_bytecode_caches(tmp_path: Path, monkeypatch):
    observed = {}

    def fake_process(command, **kwargs):
        observed["environment"] = kwargs["env"]
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", fake_process)
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))

    _, code = spawn.run_spawn(request)

    assert code == 0
    assert observed["environment"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_worker_environment_removes_parent_lead_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "lead-session")
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    environment = spawn.adapter_for(request.backend).environment(request)

    assert "CODEX_THREAD_ID" not in environment
    assert environment["CODEXTEAM_LAUNCHED_WORKER"] == "1"


def test_nested_worker_launch_is_rejected_even_for_dry_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODEXTEAM_LAUNCHED_WORKER", "1")
    with pytest.raises(ValueError, match="nested CodexTeam worker launches"):
        spawn.prepare_request(request_args(tmp_path, monkeypatch, dry_run=True))


def test_new_attempt_persists_orphan_delegation_without_lead_binding(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT T002/att-001")
    )
    spawn.run_spawn(request)

    delegation = json.loads((request.session_dir / "delegation.json").read_text())
    assert delegation["attribution"] == "orphan"
    assert delegation["orphan_reason"] == "thread_environment_missing"


def test_new_attempt_persists_exact_bound_lead_delegation(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    marker_root = spawn.CODEXTEAM_ROOT / ".codexteam/runtime/lead-sessions"
    marker_root.mkdir(parents=True, exist_ok=True)
    session_id = "lead-test-session"
    marker = marker_root / f"{session_id}.json"
    marker.write_text(json.dumps({
        "session_id": session_id,
        "lead_root": str(spawn.CODEXTEAM_ROOT),
        "project": args.workspace,
        "task_id": "T001",
    }))
    monkeypatch.setenv("CODEX_THREAD_ID", session_id)
    try:
        request = spawn.prepare_request(args)
        monkeypatch.setattr(
            spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT T002/att-001")
        )
        spawn.run_spawn(request)
        delegation = json.loads((request.session_dir / "delegation.json").read_text())
        assert delegation["attribution"] == "bound_lead"
        assert delegation["parent"] == {
            "session_id": session_id, "task_id_at_launch": "T001",
        }
    finally:
        marker.unlink(missing_ok=True)


def test_legacy_continuation_without_delegation_record_remains_supported(tmp_path: Path, monkeypatch):
    draft, _ = run_draft(tmp_path, monkeypatch)
    (draft.session_dir / "delegation.json").unlink()
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT T002/att-001 continued")
    )
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
    )
    outcome, code = spawn.run_spawn(feedback)
    assert code == 0
    assert outcome["status"] == "draft_ready"


def test_parent_sandbox_mode_skips_redundant_worker_namespace_and_persists(
    tmp_path: Path, monkeypatch
):
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, trust_parent_sandbox=True)
    )
    initial_command = spawn.build_command(draft, spawn.prepare_turn(draft))
    assert initial_command[:4] == ["codex", "-s", "danger-full-access", "exec"]
    assert "workspace-write" not in initial_command

    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _, code = spawn.run_spawn(draft)
    assert code == 0

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt="FEEDBACK: REVISE",
        )
    )
    resume_command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    session = json.loads(feedback.session_path.read_text())
    assert resume_command[:5] == ["codex", "-s", "danger-full-access", "exec", "resume"]
    assert feedback.execution_spec["permissions"]["additional_write_roots"] == []


def test_continuation_restores_additional_write_roots_from_execution_spec(
    tmp_path: Path, monkeypatch
):
    extra = tmp_path / "extra"
    extra.mkdir()
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, add_dir=[str(extra)])
    )
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT T002/att-001")
    )
    spawn.run_spawn(draft)

    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
    )

    assert feedback.add_dirs == (extra.resolve(),)


def test_additional_write_root_changes_are_audited(tmp_path: Path, monkeypatch):
    extra = tmp_path / "extra"
    extra.mkdir()
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, add_dir=[str(extra)])
    )

    def change_extra(*args, **kwargs):
        (extra / "management").mkdir()
        (extra / "management/forbidden.txt").write_text("changed\n")
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", change_extra)
    outcome, code = spawn.run_spawn(request)

    assert code == 1
    assert any("role policy" in error for error in outcome["errors"])


def test_session_reasoning_field_is_rejected(tmp_path: Path, monkeypatch):
    draft, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(draft.session_path.read_text())
    session["model_reasoning_effort"] = "low"
    draft.session_path.write_text(json.dumps(session))

    with pytest.raises(ValueError, match="unknown fields"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
        )


def test_declared_task_write_scope_rejects_role_allowed_out_of_scope_change(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch)
    handoff = Path(args.workspace) / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# Task T002\n\n## Task Write Scope\n\n- `src/**`\n\n"
        "## Context Mode\n\n- `bounded-mcp`\n\n## Reporting\n\nReport.\n"
    )
    args.prompt = None
    args.prompt_file = str(handoff)
    request = spawn.prepare_request(args)

    def change_outside_scope(*args, **kwargs):
        (request.workspace / "tests").mkdir()
        (request.workspace / "tests/test_new.py").write_text("pass\n")
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", change_outside_scope)
    outcome, code = spawn.run_spawn(request)

    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("task write scope" in error for error in outcome["errors"])
    assert request.execution_spec["permissions"]["task_write_scope"] == ["src/**"]


def test_turn_writes_private_context_pack_without_prompt_content(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    path = request.session_dir / "turns/001-context-pack.json"
    value = json.loads(path.read_text())

    assert value["handoff"]["content_digest"] == request.prompt_content_digest
    assert value["policy"]["execution_spec_digest"] == request.execution_spec["execution_spec_digest"]
    assert value["mcp"]["effective_servers"] == list(request.effective_mcp_servers)
    assert request.prompt not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_parent_sandbox_mode_rejects_authenticated_openai_worker(
    tmp_path: Path, monkeypatch
):
    args = request_args(
        tmp_path, monkeypatch, profile="gpt54-mini", trust_parent_sandbox=True
    )
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "gpt54-mini.config.toml").write_text(
        'model = "gpt-5.4-mini"\n'
        'model_provider = "openai"\n'
        'model_reasoning_effort = "medium"\n'
    )
    (source_home / "auth.json").write_text("credential-store")

    with pytest.raises(ValueError, match="requires a local model profile"):
        spawn.prepare_request(args)


def test_reasoning_effort_override_is_validated_and_applied_to_initial_turn(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, reasoning_effort="medium")
    )
    command = spawn.build_command(request, spawn.prepare_turn(request))

    assert request.model_reasoning_effort == "high"
    assert request.reasoning_effort_override == "medium"
    assert 'model_reasoning_effort="medium"' in command

    with pytest.raises(ValueError, match="reasoning request"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, reasoning_effort="unsupported")
        )


def test_reasoning_effort_override_persists_when_resume_omits_flag(
    tmp_path: Path, monkeypatch
):
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, reasoning_effort="medium")
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _, code = spawn.run_spawn(draft)
    assert code == 0

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt="FEEDBACK: REVISE",
            reasoning_effort=None,
        )
    )
    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    profile = feedback.execution_spec["execution_profile"]
    assert profile["reasoning"]["requested"] == "medium"
    assert profile["reasoning"]["effective"] == "medium"
    assert 'model_reasoning_effort="medium"' in command


def test_non_default_reasoning_effort_persists_in_execution_spec(
    tmp_path: Path, monkeypatch
):
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, reasoning_effort="low")
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    spawn.run_spawn(draft)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
    )
    assert feedback.execution_spec["execution_profile"]["reasoning"]["requested"] == "low"
    assert feedback.execution_spec["execution_profile"]["reasoning"]["effective"] == "low"


def test_resume_rejects_a_different_reasoning_effort_override(tmp_path: Path, monkeypatch):
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, reasoning_effort="medium")
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    spawn.run_spawn(draft)

    args = request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    args.reasoning_effort = "low"
    with pytest.raises(ValueError, match="load backend, profile, and reasoning"):
        spawn.prepare_request(args)


def test_resume_command_uses_exact_thread_and_no_initial_only_flags(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    assert command[:3] == ["codex", "exec", "resume"]
    assert THREAD_ID in command
    assert "--last" not in command
    assert "--profile" not in command
    assert "-C" not in command
    assert "--add-dir" not in command
    assert command[command.index("-m") + 1] == "qwen3.6-27b"
    assert 'model_provider="ollama_local"' in command
    assert 'model_catalog_json="/tmp/local-models.json"' in command
    assert 'model_reasoning_effort="medium"' in command
    assert 'model_verbosity="medium"' in command


def test_event_parser_extracts_thread_message_and_terminal_state():
    summary = spawn.parse_codex_events(event_stream("draft text"))
    assert summary.thread_ids == (THREAD_ID,)
    assert summary.last_agent_message == "draft text"
    assert summary.completed is True
    assert summary.failures == ()
    assert summary.parse_errors == ()


def test_event_parser_reports_malformed_and_failed_events():
    text = '{"type":"thread.started","thread_id":"abc"}\nnot-json\n'
    text += json.dumps({"type": "turn.failed", "error": {"message": "model failed"}}) + "\n"
    summary = spawn.parse_codex_events(text)
    assert summary.thread_ids == ("abc",)
    assert summary.completed is False
    assert summary.failures == ("model failed",)
    assert summary.parse_errors


def test_completed_turn_tolerates_a_recovered_transient_error_event():
    text = event_stream("draft text").replace(
        json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
        json.dumps({"type": "error", "message": "Reconnecting..."}) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
    )
    events = spawn.parse_codex_events(text)
    status, code, errors = spawn._turn_failure(
        spawn.ProcessResult(0, text, "", 0.2),
        events,
        thread_id=THREAD_ID,
        thread_mismatch=False,
    )
    assert events.completed is True
    assert events.failures == ("Reconnecting...",)
    assert (status, code, errors) == (None, 0, [])


def test_draft_persists_private_session_and_no_result(tmp_path: Path, monkeypatch):
    request, outcome = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    metrics = Path(outcome["metrics_path"])
    summary = json.loads(metrics.read_text())
    assert outcome["status"] == "draft_ready"
    assert session["thread_id"] == THREAD_ID
    assert session["turn_count"] == 1
    assert session["last_phase"] == "draft"
    assert session["turns"] == [
        {
            "number": 1,
            "phase": "draft",
            "status": "draft_ready",
            "duration_seconds": 0.2,
        }
    ]
    assert not request.result_path.exists()
    assert stat.S_IMODE(request.session_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(metrics.stat().st_mode) == 0o600
    prompt_path = Path(outcome["lead_prompt_path"])
    assert prompt_path.read_text() == "Implement the task."
    assert stat.S_IMODE(prompt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(request.codex_home.stat().st_mode) == 0o700
    assert summary["task_id"] == "T002"
    assert summary["attempt_id"] == "att-001"
    assert summary["turn"]["completed"] is True
    assert summary["turn"]["duration_seconds"] == 0.2
    assert "execution_backend" not in summary
    assert "context_bytes" not in summary
    assert "model_steps" not in summary
    assert "backend_usage" not in summary

    backend_fields = {
        "execution_backend",
        "backend_version",
        "backend_config_digest",
        "resolved_model",
        "opencode_session_id",
    }
    state = json.loads((request.session_dir / spawn.TURN_STATE_FILENAME).read_text())
    assert backend_fields.isdisjoint(session)
    assert backend_fields.isdisjoint(state)
    assert backend_fields.isdisjoint(outcome)
    assert set(session) == {
        "schema_version", "team_id", "task_id", "attempt_id", "agent_role",
        "workspace_root", "thread_id", "turn_count", "last_phase", "last_status",
        "last_turn_path", "created_at", "updated_at", "turns", "execution_spec",
        "handoff_contract_sha256",
        "workspace_baseline_sha256", "worker_change_manifest", "accepted_checkpoint",
    }
    assert set(state) == {
        "schema_version",
        "team_id",
        "task_id",
        "attempt_id",
        "agent_role",
        "model_profile",
        "draft_format",
        "draft_format_pinned",
        "role_policy_name",
        "role_policy_version",
        "role_policy_digest",
        "agent_spec",
        "effective_policy_digest",
        "instruction_bundle_digest",
        "execution_spec",
        "phase",
        "turn_number",
        "status",
        "started_at",
        "updated_at",
        "timeout_seconds",
        "run_guard_enabled",
        "mcp_allowed_servers",
        "mcp_effective_servers",
        "mcp_missing_servers",
        "mcp_allowed_tools",
        "mcp_effective_tools",
        "changed_paths",
        "errors",
        "duration_seconds",
        "exit_code",
        "timed_out",
        "run_guard_triggered",
    }
    assert set(outcome) == {
        "phase",
        "status",
        "team_id",
        "task_id",
        "attempt_id",
        "agent_role",
        "draft_format",
        "draft_format_pinned",
        "role_policy_name",
        "role_policy_version",
        "role_policy_digest",
        "agent_spec",
        "effective_policy_digest",
        "instruction_bundle_digest",
        "execution_spec",
            "mcp_context_project",
        "thread_id",
        "turn_count",
        "session_path",
        "turn_path",
        "lead_prompt_path",
        "events_path",
        "metrics_path",
        "stderr_path",
        "result_path",
        "errors",
    }


def test_feedback_resumes_same_home_thread_and_attempt_without_result(tmp_path: Path, monkeypatch):
    initial, _ = run_draft(tmp_path, monkeypatch)
    observed = {}

    def fake_process(command, **kwargs):
        observed["command"] = command
        observed["codex_home"] = kwargs["env"]["CODEX_HOME"]
        observed["sqlite_home"] = kwargs["env"]["CODEX_SQLITE_HOME"]
        return spawn.ProcessResult(
            0,
            event_stream(
                "DRAFT T002/att-001\n\nOutcome: Feedback addressed.\nEvidence: focused tests pass\n"
                "Uncertainties or conflicts: none\nProposed disposition: ready for review"
            ),
            "",
            0.75,
        )

    monkeypatch.setattr(spawn, "run_process", fake_process)
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    outcome, code = spawn.run_spawn(request)
    session = json.loads(request.session_path.read_text())
    assert code == 0
    assert outcome["status"] == "draft_ready"
    assert session["thread_id"] == THREAD_ID
    assert session["attempt_id"] == "att-001"
    assert request.execution_spec["execution_profile"]["model"]["provider_locator"] == "qwen3.6-27b"
    assert request.execution_spec["execution_profile"]["model"]["provider"] == "ollama_local"
    assert request.execution_spec["execution_profile"]["reasoning"]["effective"] == "medium"
    assert session["turn_count"] == 2
    assert session["turns"][1] == {
        "number": 2,
        "phase": "feedback",
        "status": "draft_ready",
        "duration_seconds": 0.75,
    }
    assert observed["command"][-2:] == [THREAD_ID, "-"]
    assert observed["codex_home"] == str(initial.codex_home)
    assert observed["sqlite_home"] == str(initial.codex_home)
    assert not request.result_path.exists()


def test_feedback_prompt_is_delta_only_without_context_replay(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="Fix the exact assertion.",
    ))
    prompt = spawn.build_prompt(feedback, spawn.prepare_turn(feedback))
    assert "Task: T002/att-001" in prompt
    assert "Correction: Fix the exact assertion." in prompt
    assert "Output: update results/reports/T002-att-001.json" in prompt
    assert "[CODEXTEAM HANDOFF]" not in prompt
    assert "PINNED GUIDANCE" not in prompt
    assert "BOUNDED LOCAL MCP CONTEXT" not in prompt


def test_opencode_feedback_does_not_inject_mcp_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opencode_backend, "version", lambda executable: "1.18.18")
    values = {"backend": "opencode", "profile": "qwen36-27b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("ignored")
    )
    assert spawn.run_spawn(draft)[1] == 0
    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="revise", **values,
    ))
    monkeypatch.setattr(
        spawn,
        "_opencode_task_context",
        lambda request: (_ for _ in ()).throw(AssertionError("MCP replayed")),
    )
    assert spawn.run_spawn(feedback)[1] == 0


def test_format_only_feedback_uses_no_tools_agent_and_rejects_other_changes(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda executable: "1.18.18")
    values = {"backend": "opencode", "profile": "qwen36-27b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("ignored")
    )
    assert spawn.run_spawn(draft)[1] == 0
    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="repair JSON",
        feedback_mode="format-only", **values,
    ))
    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    assert command[command.index("--agent") + 1] == opencode_backend.FORMAT_AGENT

    def mutate(*args, **kwargs):
        (feedback.workspace / "src").mkdir(exist_ok=True)
        (feedback.workspace / "src/forbidden.py").write_text("bad\n")
        return successful_opencode_process("ignored")

    monkeypatch.setattr(spawn, "run_process", mutate)
    outcome, code = spawn.run_spawn(feedback)
    assert code == 1
    assert any("format-only feedback" in error for error in outcome["errors"])
    assert not (feedback.workspace / "src/forbidden.py").exists()


def test_format_only_invalid_report_restores_previous_bytes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opencode_backend, "version", lambda executable: "1.18.18")
    values = {"backend": "opencode", "profile": "qwen36-27b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("ignored")
    )
    assert spawn.run_spawn(draft)[1] == 0
    before = draft.artifact_report_path.read_bytes()
    feedback = spawn.prepare_request(request_args(
        tmp_path, monkeypatch, phase="feedback", prompt="repair",
        feedback_mode="format-only", **values,
    ))

    def corrupt(*args, **kwargs):
        feedback.artifact_report_path.write_text("{bad")
        return successful_opencode_process("ignored")

    monkeypatch.setattr(spawn, "run_process", corrupt)
    outcome, code = spawn.run_spawn(feedback)
    assert code == 1
    assert any("valid JSON" in error for error in outcome["errors"])
    assert feedback.artifact_report_path.read_bytes() == before


def test_openai_profile_reuses_authenticated_source_home_without_copying_auth(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch, profile="gpt54-mini")
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "gpt54-mini.config.toml").write_text(
        'model = "gpt-5.4-mini"\n'
        'model_provider = "openai"\n'
        'model_reasoning_effort = "high"\n'
        'model_verbosity = "medium"\n'
    )
    (source_home / "auth.json").write_text("credential-store")
    observed = {}

    def fake_process(command, **kwargs):
        observed["codex_home"] = kwargs["env"]["CODEX_HOME"]
        observed["sqlite_home"] = kwargs["env"]["CODEX_SQLITE_HOME"]
        return successful_process("DRAFT T002/att-001\n\nOutcome: authenticated")

    monkeypatch.setattr(spawn, "run_process", fake_process)
    request = spawn.prepare_request(args)
    outcome, code = spawn.run_spawn(request)

    assert code == 0
    assert outcome["status"] == "draft_ready"
    assert observed["codex_home"] == str(source_home)
    assert observed["sqlite_home"] == str(request.codex_home)
    assert not (request.codex_home / "auth.json").exists()


def test_final_writes_one_contract_valid_result_and_finalizes_session(
    tmp_path: Path, monkeypatch, result_factory
):
    run_draft(tmp_path, monkeypatch)
    result = result_factory(task_id="T002")
    result["agent_role"] = "developer"
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: successful_process(json.dumps(result)))
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    persisted, code = spawn.run_spawn(request)
    session = json.loads(request.session_path.read_text())
    assert code == 0
    assert persisted["status"] == "completed"
    validate_result(
        json.loads(request.result_path.read_text()),
        expected_task="T002",
        expected_attempt="att-001",
    )
    assert session["last_status"] == "finalized"
    assert session["final_result_path"] == "results/T002-att-001.json"
    assert list(request.result_dir.glob("T002-*.json")) == [request.result_path]


def test_git_steward_final_has_role_specific_schema_and_empty_changes(
    tmp_path: Path, monkeypatch, result_factory
):
    draft = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            role="git_steward",
            task="T220",
            prompt="Plan the verified local commit.",
        )
    )
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("commit facts\n")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T220/att-001\n\nOutcome: planned"),
    )
    _, draft_code = spawn.run_spawn(draft)
    assert draft_code == 0

    final = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="final",
            role="git_steward",
            task="T220",
            prompt="Commit plan accepted.",
        )
    )

    persisted, final_code = spawn.run_spawn(final)

    assert final_code == 0
    assert persisted["file_changes"] == []


def test_feedback_can_resume_when_draft_created_the_reserved_result_path(
    tmp_path: Path, monkeypatch
):
    request, _ = run_draft(tmp_path, monkeypatch)
    request.result_dir.mkdir(parents=True, exist_ok=True)
    request.result_path.write_text('{"draft_evidence": true}\n')

    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="Move the draft artifact")
    )
    assert spawn.prepare_turn(feedback).number == 2

    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    with pytest.raises(ValueError, match="reserved result path already exists"):
        spawn.prepare_turn(final)


def test_timeout_after_thread_start_preserves_resumable_session(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    stdout = json.dumps({"type": "thread.started", "thread_id": THREAD_ID}) + "\n"
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: spawn.ProcessResult(124, stdout, "", 10.0, timed_out=True),
    )
    outcome, code = spawn.run_spawn(request)
    session = json.loads(request.session_path.read_text())
    assert code == 3
    assert outcome["status"] == "interrupted"
    assert session["thread_id"] == THREAD_ID
    assert session["last_status"] == "interrupted"


def test_failure_before_thread_start_requires_new_attempt(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: spawn.ProcessResult(7, "", "worker failed", 0.1),
    )
    outcome, code = spawn.run_spawn(request)
    assert code == 1
    assert outcome["thread_id"] is None
    assert not request.session_path.exists()
    assert json.loads(request.draft_format_path.read_text())["draft_format"] == "artifact-report-v1"
    assert request.session_dir.joinpath("turns", "001-draft.stderr.txt").read_text() == "worker failed"
    with pytest.raises(ValueError, match="non-resumable session data"):
        spawn.prepare_turn(spawn.prepare_request(request_args(tmp_path, monkeypatch)))


def test_session_scope_mismatch_is_rejected_before_resume(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    session["agent_role"] = "tester"
    request.session_path.write_text(json.dumps(session))
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    with pytest.raises(ValueError, match="session scope mismatch"):
        spawn.prepare_turn(feedback)


def test_finalized_session_refuses_additional_turns(tmp_path: Path, monkeypatch, result_factory):
    run_draft(tmp_path, monkeypatch)
    result = result_factory(task_id="T002")
    result["agent_role"] = "developer"
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: successful_process(json.dumps(result)))
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    _, code = spawn.run_spawn(final)
    assert code == 0
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="More feedback")
    )
    with pytest.raises(ValueError, match="already finalized"):
        spawn.prepare_turn(feedback)


def test_persistent_home_seeds_profiles_and_catalogs_but_not_auth(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "config.toml").write_text("sandbox_mode = 'workspace-write'\n")
    (source_home / "auth.json").write_text("secret")
    catalogs = source_home / "model_catalogs"
    catalogs.mkdir()
    (catalogs / "local.json").write_text("{}")
    request = spawn.prepare_request(args)
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT"))
    _, code = spawn.run_spawn(request)
    assert code == 0
    assert (request.codex_home / "config.toml").is_file()
    assert (request.codex_home / "qwen36-27b.config.toml").is_file()
    assert (request.codex_home / "model_catalogs" / "local.json").is_file()
    assert not (request.codex_home / "auth.json").exists()


def test_fake_cli_runs_draft_feedback_final_in_one_persistent_session(
    tmp_path: Path, monkeypatch, result_factory
):
    result = result_factory(task_id="T002")
    result["agent_role"] = "developer"
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"thread = {THREAD_ID!r}\n"
        f"final_result = {result!r}\n"
        "args = sys.argv[1:]\n"
        "home = Path(os.environ['CODEX_HOME'])\n"
        "sentinel = home / 'turn-count'\n"
        "count = int(sentinel.read_text()) if sentinel.exists() else 0\n"
        "is_resume = len(args) > 1 and args[0] == 'exec' and args[1] == 'resume'\n"
        "if is_resume and thread not in args:\n"
        "    raise SystemExit(8)\n"
        "count += 1\n"
        "sentinel.write_text(str(count))\n"
        "output = Path(args[args.index('-o') + 1])\n"
        "draft = {'schema_version':'1.0','outcome':f'turn {count}','evidence':[],'findings':[],'limitations':[],'proposed_disposition':'ready_for_review'}\n"
        "message = json.dumps(final_result) if 'final' in output.name else json.dumps(draft)\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "output.write_text(message + '\\n')\n"
        "print(json.dumps({'type':'thread.started','thread_id':thread}))\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':message}}))\n"
        "print(json.dumps({'type':'turn.completed','usage':{}}))\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, phase="draft"))
    (draft.workspace / "src").mkdir()
    (draft.workspace / "src" / "main.py").write_text("VALUE = 1\n")
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    draft_outcome, draft_code = spawn.run_spawn(draft, executable=str(fake))
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    feedback_outcome, feedback_code = spawn.run_spawn(feedback, executable=str(fake))
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    final_outcome, final_code = spawn.run_spawn(final, executable=str(fake))

    session = json.loads(final.session_path.read_text())
    assert (draft_code, feedback_code, final_code) == (0, 0, 0)
    assert draft_outcome["thread_id"] == feedback_outcome["thread_id"] == THREAD_ID
    assert final_outcome["status"] == "completed"
    assert session["thread_id"] == THREAD_ID
    assert session["turn_count"] == 3
    assert (final.codex_home / "turn-count").read_text() == "2"
    assert len(list((final.session_dir / "turns").glob("*.jsonl"))) == 2
    assert list(final.result_dir.glob("T002-*.json")) == [final.result_path]
    validate_result(json.loads(final.result_path.read_text()), expected_attempt="att-001")


def test_run_guard_streams_and_interrupts_identical_failed_commands(tmp_path: Path):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        f"thread = {THREAD_ID!r}\n"
        "def emit(event):\n"
        "    print(json.dumps(event), flush=True)\n"
        "emit({'type': 'thread.started', 'thread_id': thread})\n"
        "print('diagnostic', file=sys.stderr, flush=True)\n"
        "for _ in range(3):\n"
        "    emit({'type': 'item.completed', 'item': {\n"
        "        'type': 'command_execution',\n"
        "        'command': 'API_KEY=secret pytest -q',\n"
        "        'aggregated_output': 'same failure',\n"
        "        'exit_code': 1,\n"
        "        'status': 'failed',\n"
        "    }})\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    events_path = tmp_path / "turn.jsonl"
    stderr_path = tmp_path / "turn.stderr.txt"

    result = spawn.run_process(
        [str(fake)],
        prompt="run",
        timeout_seconds=5,
        env=spawn.os.environ.copy(),
        events_path=events_path,
        stderr_path=stderr_path,
        run_guard=True,
    )

    assert result.guard_triggered is True
    assert result.timed_out is False
    assert result.duration_seconds < 5
    assert "3 consecutive identical failed commands" in (result.guard_reason or "")
    assert "API_KEY=<redacted>" in (result.guard_reason or "")
    assert "secret" not in (result.guard_reason or "")
    assert events_path.read_text() == result.stdout
    assert stderr_path.read_text() == result.stderr
    assert "diagnostic" in result.stderr


def test_ordinary_run_streams_without_enabling_guard(tmp_path: Path):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        "event = {'type':'item.completed','item':{'type':'command_execution',"
        "'command':'false','aggregated_output':'same failure','exit_code':1,'status':'failed'}}\n"
        "for _ in range(3): print(json.dumps(event), flush=True)\n"
        "print('diagnostic', file=sys.stderr, flush=True)\n"
        "time.sleep(.5)\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    events_path = tmp_path / "turn.jsonl"
    stderr_path = tmp_path / "turn.stderr.txt"
    observed = {}

    def run():
        observed["result"] = spawn.run_process(
            [str(fake)], prompt="run", timeout_seconds=5,
            env=spawn.os.environ.copy(), events_path=events_path,
            stderr_path=stderr_path,
        )

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (
        not stderr_path.exists()
        or stderr_path.stat().st_size == 0
        or not events_path.exists()
        or events_path.read_text().count("item.completed") < 3
    ):
        time.sleep(.01)
    assert events_path.read_text().count("item.completed") == 3
    assert stderr_path.read_text() == "diagnostic\n"
    assert worker.is_alive()
    worker.join(timeout=2)
    result = observed["result"]
    assert result.exit_code == 0
    assert result.guard_triggered is False
    assert result.stdout == events_path.read_text()
    assert result.stderr == stderr_path.read_text()


def test_run_process_stops_waiting_when_detached_descendant_retains_pipes(tmp_path: Path):
    fake = tmp_path / "fake-codex"
    child_pid = tmp_path / "child.pid"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        f"    open({str(child_pid)!r}, 'w').write(str(os.getpid()))\n"
        "    os.execl(sys.executable, sys.executable, '-c', 'import time; time.sleep(10)')\n"
        "print('worker complete', flush=True)\n"
        "time.sleep(.2)\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    started = time.monotonic()
    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5, env=spawn.os.environ.copy()
    )

    assert result.exit_code == 0
    assert result.stdout == "worker complete\n"
    assert time.monotonic() - started < 2
    process_id = int(child_pid.read_text())
    deadline = time.monotonic() + 1
    while Path(f"/proc/{process_id}").exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert not Path(f"/proc/{process_id}").exists()


def test_streaming_progress_reports_only_safe_metadata(tmp_path: Path, monkeypatch, capsys):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'type':'tool_use','part':{'tool':'read','state':{"
        "'status':'completed','input':{'path':'/private/secret'}}}}), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(spawn, "PROGRESS_INTERVAL_SECONDS", 0.0)

    spawn.run_process(
        [str(fake)], prompt="secret prompt", timeout_seconds=5,
        env=spawn.os.environ.copy(),
    )

    progress = capsys.readouterr().err
    assert "Worker progress:" in progress
    assert "last tool read" in progress
    assert "private" not in progress
    assert "secret" not in progress


def test_progress_replaces_unknown_provider_labels():
    event_type, tool = spawn._safe_progress_event(json.dumps({
        "type": "API_KEY_private", "part": {"tool": "token_private"},
    }))
    assert event_type == "unknown"
    assert tool is None


def test_debug_stream_assistant_prints_text_without_tool_payload(tmp_path: Path, capsys):
    fake = tmp_path / "fake-opencode"
    events = [
        {"type": "text", "sessionID": THREAD_ID, "part": {"text": "Inspecting routes."}},
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "read", "state": {
                "status": "completed", "input": {"path": "/private/source.py"},
                "output": "secret source content",
            },
        }},
    ]
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), debug_stream="assistant",
    )

    debug = capsys.readouterr().err
    assert "[worker assistant]\nInspecting routes." in debug
    assert "[worker tool]" not in debug
    assert "/private/source.py" not in debug
    assert "secret source content" not in debug
    assert result.stdout == "".join(json.dumps(event) + "\n" for event in events)


def test_debug_stream_activity_reports_metadata_without_output_content(tmp_path: Path, capsys):
    fake = tmp_path / "fake-opencode"
    events = [
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "read", "state": {
                "status": "completed", "input": {"filePath": str(tmp_path / "README.md")},
                "output": "private file contents", "time": {"start": 1000, "end": 1005},
                "metadata": {"truncated": False},
            },
        }},
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "grep", "state": {
                "status": "completed", "input": {
                    "pattern": "Debug Stream", "path": str(tmp_path), "include": "*.md",
                },
                "output": "private matching line", "time": {"start": 2000, "end": 6750},
                "metadata": {"count": 3, "truncated": False},
            },
        }},
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "glob", "state": {
                "status": "completed", "input": {"pattern": "**/*.py", "path": str(tmp_path)},
                "output": "private paths", "time": {"start": 7000, "end": 7014},
                "metadata": {"count": 100, "truncated": True},
            },
        }},
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "bash", "state": {
                "status": "completed",
                "input": {
                    "command": "API_KEY='alpha beta gamma' curl -H 'Authorization: Bearer private-token' /status",
                    "token": "structured-private-token",
                    "workdir": str(tmp_path),
                },
                "output": "api_key=private-key private command output\x1b[2J",
                "time": {"start": 8000, "end": 8003},
                "metadata": {"exit": 0, "truncated": True},
            },
        }},
        {"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "reason": "tool-calls", "tokens": {
                "input": 100, "output": 20, "reasoning": 3,
                "cache": {"read": 10, "write": 5},
            },
        }},
    ]
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path, debug_stream="activity",
    )

    debug = capsys.readouterr().err
    assert "[worker tool] read completed" in debug
    assert "target: README.md" in debug
    assert "duration: 5ms" in debug
    assert "result: 21 bytes, complete" in debug
    assert "[worker tool] grep completed" in debug
    assert "query: Debug Stream" in debug
    assert "path: ." in debug
    assert "matches: 3" in debug
    assert "duration: 4.750s" in debug
    assert "[worker tool] glob completed" in debug
    assert "pattern: **/*.py" in debug
    assert "matches: 100" in debug
    assert "result: 13 bytes, truncated" in debug
    assert "[worker tool] bash completed" in debug
    assert "command: API_KEY=<redacted> curl -H 'Authorization: <redacted>" in debug
    assert str(tmp_path) not in debug
    assert "workdir: ." in debug
    assert "exit: 0" in debug
    assert "result: 46 bytes, truncated" in debug
    assert "[worker step] 1 completed" in debug
    assert "reason: tool-calls" in debug
    assert "input: 115 tokens" in debug
    assert "output: 23 tokens" in debug
    assert "[worker process] completed" in debug
    assert "private-token" not in debug
    assert "alpha beta gamma" not in debug
    assert "private-key" not in debug
    assert "structured-private-token" not in debug
    assert "private file contents" not in debug
    assert "private matching line" not in debug
    assert "private command output" not in debug
    assert "\x1b" not in debug
    assert result.stdout == "".join(json.dumps(event) + "\n" for event in events)


def test_debug_stream_activity_hides_write_edit_and_patch_bodies(tmp_path: Path, capsys):
    fake = tmp_path / "fake-opencode"
    outside = tmp_path.parent / "outside.txt"
    events = [
        {"type": "tool_use", "part": {"tool": "write", "state": {
            "status": "completed", "input": {
                "filePath": str(tmp_path / "new.txt"), "content": "PRIVATE WRITE BODY",
            }, "output": "PRIVATE WRITE RESULT",
        }}},
        {"type": "tool_use", "part": {"tool": "edit", "state": {
            "status": "completed", "input": {
                "filePath": str(outside), "oldString": "PRIVATE OLD", "newString": "PRIVATE NEW",
            }, "output": "PRIVATE EDIT RESULT",
        }}},
        {"type": "tool_use", "part": {"tool": "apply_patch", "state": {
            "status": "completed", "input": {
                "patchText": "*** Begin Patch\n*** Update File: src/app.py\n-PRIVATE PATCH OLD\n+PRIVATE PATCH NEW\n*** End Patch",
            }, "output": "PRIVATE PATCH RESULT",
        }}},
    ]
    fake.write_text(
        "#!/usr/bin/env python3\nimport json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path, debug_stream="activity",
    )

    debug = capsys.readouterr().err
    assert "[worker tool] write completed" in debug
    assert "target: new.txt" in debug
    assert "content: 18 bytes" in debug
    assert "[worker tool] edit completed" in debug
    assert "target: <outside-workspace>/outside.txt" in debug
    assert "old text: 11 bytes" in debug
    assert "new text: 11 bytes" in debug
    assert "[worker tool] apply_patch completed" in debug
    assert "targets: src/app.py" in debug
    assert "actions: 1" in debug
    for private in (
        "PRIVATE WRITE BODY", "PRIVATE WRITE RESULT", "PRIVATE OLD", "PRIVATE NEW",
        "PRIVATE EDIT RESULT", "PRIVATE PATCH OLD", "PRIVATE PATCH NEW", "PRIVATE PATCH RESULT",
    ):
        assert private not in debug


def test_debug_stream_activity_reports_unknown_tools_without_payload(tmp_path: Path, capsys):
    fake = tmp_path / "fake-opencode"
    event = {"type": "tool_use", "part": {"tool": "custom", "state": {
        "status": "failed", "input": {"target": "x", "prompt": "PRIVATE PROMPT"},
        "metadata": {"outputBytes": 14, "exitCode": 7},
        "error": "PRIVATE ERROR OUTPUT",
    }}}
    fake.write_text(
        "#!/usr/bin/env python3\nimport json\n"
        f"print(json.dumps({event!r}), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path, debug_stream="activity",
    )

    debug = capsys.readouterr().err
    assert "[worker tool] custom failed" in debug
    assert "input fields: target" in debug
    assert "result: 20 bytes" in debug
    assert "exit: 7" in debug
    assert "error: provider error reported; see private JSONL" in debug
    assert "PRIVATE PROMPT" not in debug
    assert "PRIVATE ERROR OUTPUT" not in debug


def test_debug_stream_activity_hides_delegated_description_and_marks_relative_escape(
    tmp_path: Path, capsys
):
    fake = tmp_path / "fake-opencode"
    events = [
        {"type": "tool_use", "part": {"tool": "task", "state": {
            "status": "completed", "input": {
                "description": "PRIVATE DELEGATED PROMPT", "subagent_type": "explore",
            }, "metadata": {"output_bytes": 25},
        }}},
        {"type": "tool_use", "part": {"tool": "read", "state": {
            "status": "error", "input": {"filePath": "../secret.txt"},
            "error": "PRIVATE FILE EXCERPT",
        }}},
        {"type": "error", "error": {"message": "PRIVATE PROVIDER PAYLOAD"}},
    ]
    fake.write_text(
        "#!/usr/bin/env python3\nimport json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path, debug_stream="activity",
    )

    debug = capsys.readouterr().err
    assert "[worker tool] task completed" in debug
    assert "agent: explore" in debug
    assert "result: 25 bytes" in debug
    assert "target: <outside-workspace>/secret.txt" in debug
    assert "[worker error] provider error reported; see private JSONL" in debug
    assert "PRIVATE DELEGATED PROMPT" not in debug
    assert "PRIVATE FILE EXCERPT" not in debug
    assert "PRIVATE PROVIDER PAYLOAD" not in debug


def test_debug_stream_neutralizes_terminal_controls_in_assistant_and_labels(
    tmp_path: Path, capsys
):
    fake = tmp_path / "fake-opencode"
    events = [
        {"type": "text", "sessionID": THREAD_ID, "part": {
            "text": "before\x1b[2Jafter\rforged",
        }},
        {"type": "tool_use", "sessionID": THREAD_ID, "part": {
            "tool": "bash\x1b[2J", "state": {"status": "completed\rforged"},
        }},
    ]
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), debug_stream="activity",
    )

    debug = capsys.readouterr().err
    assert "before[2Jafterforged" in debug
    assert "[worker tool] bash[2J completedforged" in debug
    assert "\x1b" not in debug
    assert "\r" not in debug


def test_debug_stream_rejects_codex_backend(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    args.debug_stream = "assistant"
    with pytest.raises(ValueError, match="supported only by the OpenCode backend"):
        spawn.prepare_request(args)


def test_run_guard_interruption_preserves_exact_thread_for_feedback(
    tmp_path: Path, monkeypatch
):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        "from pathlib import Path\n"
        f"thread = {THREAD_ID!r}\n"
        "args = sys.argv[1:]\n"
        "def emit(event):\n"
        "    print(json.dumps(event), flush=True)\n"
        "emit({'type': 'thread.started', 'thread_id': thread})\n"
        "if 'resume' in args:\n"
        "    output = Path(args[args.index('-o') + 1])\n"
        "    message = json.dumps({'schema_version':'1.0','outcome':'changed diagnostic','evidence':[],'findings':[],'limitations':[],'proposed_disposition':'ready_for_review'})\n"
        "    output.write_text(message + '\\n')\n"
        "    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}})\n"
        "    emit({'type': 'turn.completed', 'usage': {}})\n"
        "else:\n"
        "    for _ in range(3):\n"
        "        emit({'type': 'item.completed', 'item': {\n"
        "            'type': 'command_execution',\n"
        "            'command': 'pytest -q tests/test_feature.py',\n"
        "            'aggregated_output': 'same failure',\n"
        "            'exit_code': 1,\n"
        "            'status': 'failed',\n"
        "        }})\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, run_guard=True, timeout=5)
    )
    draft_outcome, draft_code = spawn.run_spawn(draft, executable=str(fake))
    session = json.loads(draft.session_path.read_text())
    turn_state = json.loads((draft.session_dir / "turn-state.json").read_text())

    assert draft_code == 3
    assert draft_outcome["status"] == "interrupted"
    assert draft_outcome["thread_id"] == THREAD_ID
    assert session["thread_id"] == THREAD_ID
    assert session["last_status"] == "interrupted"
    assert turn_state["run_guard_enabled"] is True
    assert turn_state["run_guard_triggered"] is True
    assert "3 consecutive identical failed commands" in turn_state["run_guard_reason"]

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
                phase="feedback",
                prompt="Use a materially different diagnostic.",
                timeout=5,
            )
        )
    feedback_outcome, feedback_code = spawn.run_spawn(feedback, executable=str(fake))

    assert feedback_code == 0
    assert feedback_outcome["status"] == "draft_ready"
    assert feedback_outcome["thread_id"] == THREAD_ID


def test_prepare_request_rejects_result_escape(tmp_path: Path, monkeypatch):
    with pytest.raises(ValueError):
        spawn.prepare_request(request_args(tmp_path, monkeypatch, result_dir="../outside"))


def test_prepare_request_rejects_missing_profile(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, profile="missing-profile")
    with pytest.raises(ValueError, match="unsupported execution profile"):
        spawn.prepare_request(args)


def test_role_policy_supplies_guidance_and_handoff_identity_not_profile(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch, role="tester"))
    handoff = spawn.build_handoff(request)

    assert [path.name for path in request.skill_files] == [
        "integration-testing.md",
        "verification.md",
    ]
    assert handoff["role_policy"] == {
        "name": "codexteam_tester",
        "schema_version": "1.0",
        "digest": request.role_policy.digest,
    }
    command = spawn.build_command(request, spawn.prepare_turn(request))
    assert any(
        argument.startswith("developer_instructions=") for argument in command
    )


def test_skill_contents_are_pinned_for_attempt_continuations(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom-skill.md"
    custom.write_text("original guidance\n")
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, skill_file=[str(custom)])
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _, code = spawn.run_spawn(draft)
    assert code == 0
    custom.write_text("changed guidance\n")

    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    assert feedback.skill_files[0].read_text() == "original guidance\n"
    assert feedback.guidance_digest == draft.guidance_digest
    assert feedback.skill_files[0].is_relative_to(feedback.session_dir)


def test_first_draft_prompt_uses_pinned_snapshot_not_mutable_source(
    tmp_path: Path, monkeypatch
):
    custom = tmp_path / "custom-skill.md"
    custom.write_text("original guidance\n")
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, skill_file=[str(custom)])
    )
    # In the real flow prepare_turn runs before session storage preparation.
    turn = spawn.prepare_turn(request)
    # Session storage preparation snapshots the mutable source guidance.
    spawn._prepare_session_storage(request, initial=True, session=None)
    pinned = next((request.session_dir / "guidance").rglob("*.md"))
    assert pinned.read_text(encoding="utf-8") == "original guidance\n"

    # Mutate the mutable source after the snapshot was taken.
    custom.write_text("changed guidance\n")

    # The first-draft model prompt must still carry the snapshot bytes.
    prompt = spawn.build_prompt(request, turn)
    assert "original guidance" in prompt
    assert "changed guidance" not in prompt


def test_pinned_skill_tampering_is_rejected(tmp_path: Path, monkeypatch):
    draft, _ = run_draft(tmp_path, monkeypatch)
    pinned = next((draft.session_dir / "guidance").rglob("*.md"))
    pinned.write_text("tampered\n")
    with pytest.raises(ValueError, match="snapshot digest mismatch"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
        )


def test_draft_pins_role_policy_snapshot_for_continuations(tmp_path: Path, monkeypatch):
    request, _ = run_draft(tmp_path, monkeypatch)
    snapshot = json.loads(request.role_policy_path.read_text())
    assert snapshot["name"] == "codexteam_developer"
    assert snapshot["digest"] == request.role_policy.digest

    monkeypatch.setattr(
        spawn,
        "load_role_policy",
        lambda *args, **kwargs: pytest.fail("resume must use the pinned snapshot"),
    )
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="FEEDBACK: REVISE")
    )
    assert feedback.role_policy.source_path == request.role_policy_path
    assert feedback.role_policy.digest == request.role_policy.digest


def test_installed_unregistered_profile_is_rejected(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, profile="alternate")
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "alternate.config.toml").write_text(
        'model = "qwen3.6-27b"\nmodel_provider = "ollama_local"\n'
    )
    with pytest.raises(ValueError, match="unsupported execution profile"):
        spawn.prepare_request(args)


def test_forbidden_tester_write_requires_correction(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="tester", task="T003")
    )

    def fake_process(*args, **kwargs):
        source = request.workspace / "src" / "production.py"
        source.parent.mkdir()
        source.write_text("CHANGED = True\n")
        return successful_process("DRAFT T003/att-001\n\nOutcome: checked")

    monkeypatch.setattr(spawn, "run_process", fake_process)
    outcome, code = spawn.run_spawn(request)
    state = json.loads((request.session_dir / "turn-state.json").read_text())

    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("src/production.py" in error for error in outcome["errors"])
    assert state["changed_paths"] == ["src/production.py"]
    assert state["role_policy_name"] == "codexteam_tester"


def test_workspace_snapshot_keeps_control_paths_for_role_boundary_auditing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    control = workspace / ".codexteam/lead-prompt-T002-att-001.md"
    runtime = workspace / ".codexteam/runtime/session.json"
    control.parent.mkdir(parents=True)
    runtime.parent.mkdir(parents=True)
    control.write_text("feedback\n")
    runtime.write_text("{}\n")
    snapshot = spawn.snapshot_workspace(workspace)
    assert ".codexteam/lead-prompt-T002-att-001.md" in snapshot
    assert ".codexteam/runtime/session.json" not in snapshot


def test_running_turn_state_is_written_before_worker_execution(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    observed = {}

    def fake_process(*args, **kwargs):
        observed.update(json.loads((request.session_dir / "turn-state.json").read_text()))
        return successful_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", fake_process)
    outcome, code = spawn.run_spawn(request)

    assert code == 0
    assert observed["status"] == "running"
    assert observed["phase"] == "draft"
    assert observed["model_profile"] == "qwen36-27b"
    terminal = json.loads((request.session_dir / "turn-state.json").read_text())
    assert terminal["status"] == "draft_ready"
    assert outcome["role_policy_name"] == "codexteam_developer"


def test_launcher_runs_configured_gate_after_valid_draft(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    configure_test_gates(Path(args.workspace), integration_surface="lead_host")
    request = spawn.prepare_request(args)
    request.result_dir.mkdir(exist_ok=True)
    (request.result_dir / "evidence.txt").write_text("passed\n")
    write_artifact_report(request)
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT"))
    calls = []

    def gate(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "passed", "gate": "development"}

    monkeypatch.setattr(spawn, "run_gate", gate)
    outcome, code = spawn.run_spawn(request)

    assert code == 0 and outcome["status"] == "draft_ready"
    assert calls[0][0] == (request.control_root, "development")
    assert calls[0][1]["execution_surface"] == "worker"


def test_launcher_does_not_run_gate_for_invalid_report(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    configure_test_gates(Path(args.workspace), integration_surface="lead_host")
    request = spawn.prepare_request(args)
    request.artifact_report_path.write_text("{}\n")
    monkeypatch.setattr(spawn, "run_process", lambda *args, **kwargs: successful_process("DRAFT"))
    monkeypatch.setattr(
        spawn, "run_gate", lambda *args, **kwargs: pytest.fail("invalid draft ran gate")
    )

    outcome, code = spawn.run_spawn(request)

    assert code == 1 and outcome["status"] == "correction_needed"


def test_setup_failure_preserves_terminal_turn_state(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    monkeypatch.setattr(
        spawn, "_build_handoff_contract", lambda *_args: (_ for _ in ()).throw(ValueError("setup boom"))
    )

    with pytest.raises(ValueError, match="setup boom"):
        spawn.run_spawn(request)

    state = json.loads(request.session_dir.joinpath("turn-state.json").read_text())
    assert state["status"] == "turn_failed"
    assert state["errors"] == ["worker setup failed: setup boom"]


def test_parser_requires_explicit_backend_for_draft(tmp_path: Path, monkeypatch):
    assert spawn.build_parser().parse_args(
        [
            "--phase", "draft", "--team", "team-1", "--task", "T002",
            "--attempt", "att-001", "--role", "developer", "--workspace", str(tmp_path),
            "--prompt", "work",
        ]
    ).backend is None


def test_codex_dry_run_retains_pre_backend_shape(tmp_path: Path, monkeypatch, capsys):
    args = request_args(tmp_path, monkeypatch)
    code = spawn.main([
        "--phase", "draft", "--backend", args.backend, "--profile", args.profile,
        "--reasoning-effort", args.reasoning_effort,
        "--team", args.team, "--task", args.task, "--attempt", args.attempt,
        "--role", args.role, "--workspace", args.workspace,
        "--prompt", args.prompt, "--dry-run",
    ])

    assert code == 0
    details = json.loads(capsys.readouterr().out)
    assert set(details) == {
        "phase",
        "draft_format",
        "draft_format_pinned",
        "draft_format_path",
        "execution_spec",
        "execution_spec_path",
        "command",
        "profile_file",
        "role_policy",
        "role_policy_version",
        "role_policy_digest",
        "role_policy_source",
        "agent_spec",
        "effective_policy_digest",
        "sandbox_mode",
        "mcp_allowed_servers",
        "mcp_effective_servers",
        "mcp_missing_servers",
        "mcp_allowed_tools",
        "mcp_effective_tools",
        "mcp_context_project",
        "reasoning_effort",
        "reasoning_effort_override",
        "workspace",
        "trust_parent_sandbox",
        "run_guard",
        "session_path",
        "lead_prompt_path",
        "turn_path",
        "stderr_path",
            "result_path",
            "result_status",
            "skills",
    }
    assert details["phase"] == "draft"
    assert details["profile_file"].endswith("qwen36-27b.config.toml")
    assert details["reasoning_effort"] == "medium"
    assert details["command"][:2] == ["codex", "exec"]


def test_live_draft_rejects_inline_and_noncanonical_handoffs(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch)
    args.prompt = "work"
    with pytest.raises(ValueError, match="canonical management/tasks/<task>.md"):
        spawn._require_canonical_draft_handoff(args)

    other = Path(args.workspace) / "other.md"
    other.write_text("# T002\n\n## Task Write Scope\n\n- `src/**`\n")
    args.prompt = None
    args.prompt_file = str(other)
    with pytest.raises(ValueError, match="exact canonical task handoff"):
        spawn._require_canonical_draft_handoff(args)


def test_opencode_resolves_local_profiles_without_codex_profile(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, backend="opencode", profile="ornith35b")
    Path(spawn.os.environ["CODEX_HOME"]).joinpath("qwen36-27b.config.toml").unlink()
    request = spawn.prepare_request(args)
    assert request.model == "ollama/ornith:35b"
    assert request.model_provider == "ollama"
    qwen = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b")
    )
    assert qwen.model == "ollama/qwen3.6-27b:latest"
    assert qwen.model_provider == "ollama"
    qwen38 = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, backend="opencode", profile="qwen38-27b-context",
            reasoning_effort="medium",
        )
    )
    assert qwen38.model == "ollama/qwen3.8-27b:latest"
    assert qwen38.model_provider == "ollama"
    muse = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="muse-glimmer")
    )
    assert muse.model == "ollama/muse-glimmer:30b"
    assert muse.model_provider == "ollama"
    muse_config = opencode_backend.build_config(
        model=muse.model,
        role_name="Developer",
        role_instructions="Implement the task.",
        display_name="Muse Glimmer 30B",
        context_limit=131072,
        output_limit=32768,
    )
    assert muse_config["model"] == muse_config["small_model"] == "ollama/muse-glimmer:30b"
    assert muse_config["provider"]["ollama"]["models"] == {
        "muse-glimmer:30b": {
            "name": "Muse Glimmer 30B",
            "limit": {"context": 131072, "output": 32768},
        }
    }
    with pytest.raises(ValueError, match="unsupported execution profile"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, backend="opencode", profile="unknown")
        )


def test_opencode_command_environment_and_prompt_are_private(tmp_path: Path, monkeypatch):
    workspace = Path(request_args(tmp_path, monkeypatch).workspace)
    (workspace / "AGENTS.md").write_text("PINNED PROJECT RULE\n")
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="ornith35b")
    )
    turn = spawn.prepare_turn(request)
    command = spawn.build_command(request, turn)
    assert command == [
        "opencode", "run", "--pure", "--format", "json", "--model",
        "ollama/ornith:35b", "--agent", "codexteam", "--dir", str(request.workspace),
        "--title", "CodexTeam T002/att-001",
    ]
    prompt = spawn.build_prompt(request, turn)
    assert "[PINNED GUIDANCE:" in prompt
    assert "[GUIDANCE: implementation.md]" not in prompt
    assert prompt.count(request.prompt) == 1

    observed = {}
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: observed.update(
            env=kwargs["env"],
            config=json.loads(Path(kwargs["env"]["OPENCODE_CONFIG"]).read_text()),
        ) or successful_opencode_process("DRAFT"),
    )
    _, code = spawn.run_spawn(request)
    assert code == 0
    assert observed["env"]["HOME"].startswith(str(request.session_dir))
    assert observed["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert observed["env"]["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    assert observed["env"]["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert observed["env"]["OPENCODE_CONFIG"] == str(request.backend_config_path)
    config = observed["config"]
    assert config["provider"]["ollama"] == {
        "npm": "@ai-sdk/openai-compatible",
        "options": {"baseURL": "http://localhost:11434/v1"},
        "models": {
            "ornith:35b": {
                "name": "Ornith 35B",
                "limit": {"context": 262144, "output": 32768},
            }
        },
    }
    assert "PINNED PROJECT RULE" in config["agent"]["codexteam"]["prompt"]
    assert config["agent"]["codexteam"]["permission"]["webfetch"] == "deny"
    assert config["agent"]["codexteam"]["permission"]["websearch"] == "deny"


def test_opencode_spawn_records_exact_unicode_context_bytes(
    tmp_path: Path,
    monkeypatch,
    result_factory,
):
    args = request_args(
        tmp_path,
        monkeypatch,
        backend="opencode",
        profile="ornith35b",
        prompt="Implement café λ.",
    )
    workspace = Path(args.workspace)
    agents = "Pinned 日本語 rule.\n"
    (workspace / "AGENTS.md").write_text(agents, encoding="utf-8")
    guidance = tmp_path / "unicode-guidance.md"
    guidance.write_text("Guidance résumé.\n", encoding="utf-8")
    args.skill_file = [str(guidance)]
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    observed = {}
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: observed.update(prompt=kwargs["prompt"])
        or successful_opencode_process("DRAFT T002/att-001"),
    )
    draft = spawn.prepare_request(args)
    _, draft_code = spawn.run_spawn(draft)
    assert draft_code == 0

    draft_metrics = json.loads(
        (draft.session_dir / "turns/001-draft.metrics.json").read_text()
    )
    draft_config = json.loads(draft.backend_config_path.read_text())
    assert draft_metrics["context_bytes"] == {
        "worker_prompt_bytes": len(observed["prompt"].encode("utf-8")),
        "agent_prompt_bytes": len(
            draft_config["agent"][opencode_backend.AGENT]["prompt"].encode("utf-8")
        ),
        "lead_prompt_source_bytes": len(draft.prompt.encode("utf-8")),
        "available_guidance_snapshot_bytes": len(guidance.read_bytes()),
        "available_guidance_snapshot_count": 1,
    }

    observed.clear()
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider accessed")),
    )
    final = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            backend="opencode",
            profile="ornith35b",
            phase="final",
            prompt="Accept résumé ✓.",
        )
    )
    _, final_code = spawn.run_spawn(final)
    assert final_code == 0
    assert not (final.session_dir / "turns/002-final.metrics.json").exists()


def test_opencode_environment_neutralizes_hostile_parent_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":"allow"}')
    monkeypatch.setenv("OPENCODE_PERMISSION", '{"*":"allow"}')
    monkeypatch.setenv("OPENCODE_DB", "/tmp/hostile-opencode.db")
    monkeypatch.setenv("OPENCODE_MODELS_PATH", "/tmp/hostile-models.json")
    monkeypatch.setenv("OPENCODE_EXPERIMENTAL_NATIVE_LLM", "1")
    monkeypatch.setenv("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX", "999999")
    monkeypatch.setenv("OPENCODE_WORKSPACE_ID", "hostile-workspace")
    observed = {}
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: observed.update(env=kwargs["env"])
        or successful_opencode_process("DRAFT"),
    )
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="ornith35b")
    )
    _, code = spawn.run_spawn(request)
    assert code == 0
    env = observed["env"]
    assert "OPENCODE_CONFIG_CONTENT" not in env
    assert "OPENCODE_PERMISSION" not in env
    assert "OPENCODE_DB" not in env
    assert "OPENCODE_MODELS_PATH" not in env
    assert "OPENCODE_EXPERIMENTAL_NATIVE_LLM" not in env
    assert "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX" not in env
    assert "OPENCODE_WORKSPACE_ID" not in env
    assert env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] == "1"
    assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"
    assert env["OPENCODE_CONFIG"] == str(request.backend_config_path)


@pytest.mark.parametrize(
    ("baseline", "previous", "current", "expected"),
    [
        ({}, {"src/main.py": {"action": "created", "sha256": "new"}}, {}, {}),
        (
            {"src/main.py": "original"},
            {"src/main.py": {"action": "modified", "sha256": "changed"}},
            {"src/main.py": "original"},
            {},
        ),
        (
            {"src/main.py": "original"},
            {"src/main.py": {"action": "deleted", "sha256": None}},
            {"src/main.py": "original"},
            {},
        ),
        (
            {"src/main.py": "original"},
            {},
            {"src/main.py": "changed"},
            {"src/main.py": {"action": "modified", "sha256": "changed"}},
        ),
    ],
)
def test_opencode_worker_change_manifest_uses_attempt_baseline(
    baseline, previous, current, expected
):
    merged = spawn._merge_worker_change_manifest(
        baseline,
        previous,
        {"src/main.py": "modified"},
        current,
    )
    assert merged == expected


def test_opencode_resume_exact_session_and_mismatches_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    draft = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="ornith35b")
    )
    spawn.run_spawn(draft)
    feedback = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, backend="opencode", profile="ornith35b",
            phase="feedback", prompt="revise",
        )
    )
    command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    assert command[command.index("--session") + 1] == THREAD_ID
    assert "--continue" not in command
    assert "--fork" not in command
    with pytest.raises(ValueError, match="load backend, profile, and reasoning"):
        args = request_args(tmp_path, monkeypatch, phase="feedback", prompt="wrong backend")
        args.backend = "codex"
        spawn.prepare_request(args)
    args = request_args(tmp_path, monkeypatch, phase="feedback", prompt="wrong profile")
    args.profile = "qwen36-27b"
    with pytest.raises(ValueError, match="load backend, profile, and reasoning"):
        spawn.prepare_request(args)


def test_opencode_mismatched_resume_preserves_changes_under_stored_session(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    spawn.run_spawn(draft)
    product = draft.workspace / "src/main.py"

    def mismatched_change(*args, **kwargs):
        product.parent.mkdir(exist_ok=True)
        product.write_text("VALUE = 1\n")
        return spawn.ProcessResult(
            0,
            opencode_stream("mismatched", session_id="different-session"),
            "",
            0.1,
        )

    monkeypatch.setattr(spawn, "run_process", mismatched_change)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="revise", **values)
    )
    outcome, code = spawn.run_spawn(feedback)
    assert code == 1
    assert outcome["status"] == "session_mismatch"
    session = json.loads(feedback.session_path.read_text())
    assert session["thread_id"] == THREAD_ID
    assert session["opencode_session_id"] == THREAD_ID
    assert session["worker_change_manifest"]["src/main.py"]["action"] == "created"

    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT recovered")
    )
    recovery = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="recover", **values)
    )
    _, recovery_code = spawn.run_spawn(recovery)
    assert recovery_code == 0
    recovered = json.loads(recovery.session_path.read_text())
    assert recovered["accepted_checkpoint"]["accepted_paths"]["src/main.py"]["action"] == "created"


@pytest.mark.parametrize("initially_present", [True, False])
def test_opencode_restored_baseline_bytes_remove_net_change(
    tmp_path: Path, monkeypatch, initially_present
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    args = request_args(tmp_path, monkeypatch, **values)
    product = Path(args.workspace) / "src/main.py"
    product.parent.mkdir()
    if initially_present:
        product.write_text("ORIGINAL\n")

    def first_turn(*args, **kwargs):
        if initially_present:
            product.unlink()
        else:
            product.write_text("CREATED\n")
        return successful_opencode_process("DRAFT")

    monkeypatch.setattr(spawn, "run_process", first_turn)
    draft = spawn.prepare_request(args)
    spawn.run_spawn(draft)

    def restore_baseline(*args, **kwargs):
        if initially_present:
            product.write_text("ORIGINAL\n")
        else:
            product.unlink()
        return successful_opencode_process("DRAFT restored")

    monkeypatch.setattr(spawn, "run_process", restore_baseline)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="restore", **values)
    )
    _, code = spawn.run_spawn(feedback)
    assert code == 0
    session = json.loads(feedback.session_path.read_text())
    assert session["worker_change_manifest"] == {}
    assert session["accepted_checkpoint"]["accepted_paths"] == {}


def test_opencode_workspace_baseline_digest_is_pinned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    spawn.run_spawn(draft)
    baseline = draft.session_dir / spawn.WORKSPACE_BASELINE_FILENAME
    assert stat.S_IMODE(baseline.stat().st_mode) == 0o600
    session = json.loads(draft.session_path.read_text())
    assert session["workspace_baseline_sha256"] == spawn._workspace_baseline_digest(
        json.loads(baseline.read_text())
    )
    baseline.write_text('{"tampered":"digest"}\n')
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue", **values)
    )
    with pytest.raises(ValueError, match="workspace baseline digest mismatch"):
        spawn.run_spawn(feedback)


def test_opencode_worker_cannot_repin_mutated_workspace_baseline(
    tmp_path: Path, monkeypatch, result_factory
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    spawn.run_spawn(draft)
    original_session = json.loads(draft.session_path.read_text())
    trusted_digest = original_session["workspace_baseline_sha256"]
    baseline = draft.session_dir / spawn.WORKSPACE_BASELINE_FILENAME
    trusted_content = baseline.read_bytes()
    product = draft.workspace / "src/main.py"

    def mutate_private_baseline(*args, **kwargs):
        baseline.write_text('{"attacker":"controlled"}\n')
        product.parent.mkdir(exist_ok=True)
        product.write_text("VALUE = 1\n")
        return successful_opencode_process("DRAFT tampered")

    monkeypatch.setattr(spawn, "run_process", mutate_private_baseline)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue", **values)
    )
    outcome, code = spawn.run_spawn(feedback)
    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("changed the private workspace baseline" in error for error in outcome["errors"])
    session = json.loads(feedback.session_path.read_text())
    assert session["thread_id"] == THREAD_ID
    assert session["workspace_baseline_sha256"] == trusted_digest
    assert session["worker_change_manifest"]["src/main.py"]["action"] == "created"
    assert baseline.read_bytes() == trusted_content
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT recovered")
    )
    recovery = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="recover", **values)
    )
    _, recovery_code = spawn.run_spawn(recovery)
    assert recovery_code == 0
    recovered = json.loads(recovery.session_path.read_text())
    accepted = recovered["accepted_checkpoint"]["accepted_paths"]
    assert accepted["src/main.py"]["action"] == "created"

    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, final_code = spawn.run_spawn(final)
    assert final_code == 0
    assert outcome["file_changes"] == [{"path": "src/main.py", "action": "created"}]


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("trust_parent_sandbox", True),
        ("run_guard", True),
    ],
)
def test_opencode_rejects_unsupported_flags(tmp_path: Path, monkeypatch, flag, value):
    with pytest.raises(ValueError, match=f"--{flag.replace('_', '-')}"):
        spawn.prepare_request(
            request_args(
                tmp_path, monkeypatch, backend="opencode", profile="ornith35b", **{flag: value}
            )
        )


def test_opencode_config_disables_integrations_and_final_agent_is_read_only():
    config = opencode_backend.build_config(
        model="ollama/ornith:35b",
        role_name="developer", role_instructions="Implement only the handoff.",
        context_limit=131072, output_limit=32768,
    )
    assert config["plugin"] == []
    assert config["mcp"] == {}
    assert config["lsp"] is False
    assert config["skills"] == {"paths": [], "urls": []}
    assert config["enabled_providers"] == ["ollama"]
    assert config["provider"]["ollama"]["npm"] == "@ai-sdk/openai-compatible"
    formatter = config["agent"]["codexteam-format"]["permission"]
    assert "*" not in formatter
    assert formatter["read"] == "deny"
    assert formatter["bash"] == "deny"


def test_opencode_qwen38_config_pins_context_plugin_and_reasoning(tmp_path: Path):
    plugin = tmp_path / "codexteam-context-plugin.js"
    archive = tmp_path / "private" / "tool-results"
    digest = "a" * 64
    config = opencode_backend.build_config(
        model="ollama/qwen3.8-27b:latest",
        role_name="reviewer",
        role_instructions="Review only the handoff.",
        context_limit=262144,
        output_limit=32768,
        context_plugin={
            "path": str(plugin),
            "archive_root": str(archive),
            "digest": digest,
            "reasoning_effort": "medium",
        },
    )
    assert config["plugin"] == [[plugin.as_uri(), {
        "archiveRoot": str(archive),
        "sourceSha256": digest,
        "reasoningEffort": "medium",
    }]]
    command = opencode_backend.build_command(
        executable="opencode", workspace=tmp_path,
        model="ollama/qwen3.8-27b:latest", phase="draft",
        session_id=None, title="test", pure=False,
    )
    assert "--pure" not in command


def test_opencode_context_plugin_copy_is_digest_verified(tmp_path: Path):
    path = tmp_path / "plugin.js"
    opencode_backend.write_context_plugin(path)
    digest = opencode_backend.context_plugin_digest()
    opencode_backend.ensure_context_plugin(path, digest)
    assert path.read_bytes() == opencode_backend.CONTEXT_PLUGIN_SOURCE.read_bytes()
    path.write_text(path.read_text() + "\n// tampered\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        opencode_backend.ensure_context_plugin(path, digest)


def test_opencode_context_plugin_archives_and_projects_bounded_history(tmp_path: Path):
    plugin = tmp_path / "plugin.js"
    opencode_backend.write_context_plugin(plugin)
    digest = opencode_backend.context_plugin_digest()
    archive = tmp_path / "private" / "tool-results"
    full = tmp_path / "provider-output.txt"
    full_text = "FAILED test_auth\n" + ("success noise\n" * 3000) + "TRACE src/auth.py:4\n"
    full.write_text(full_text)
    runner = Path(__file__).parent / "fixtures" / "run_opencode_context_plugin.mjs"
    completed = subprocess.run(
        ["node", str(runner), str(plugin), str(archive), digest, str(full)],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert value["reasoningEffort"] == "medium"
    assert value["artifactText"] == full_text
    assert value["artifactMode"] == 0o600
    assert value["rootMode"] == 0o700
    assert len(value["projected"].encode()) < 6500
    assert value["projected"] == value["resumedProjected"]
    assert "FAILED test_auth" in value["projected"]
    assert "TRACE src/auth.py:4" in value["projected"]
    assert value["projected"].count("success noise") <= 80
    assert "provider-output.txt" not in value["projected"]
    record = value["manifest"]["records"][0]
    assert record["bytes"] == len(full_text.encode())
    assert record["compacted"] is True
    assert record["sha256"] == hashlib.sha256(full_text.encode()).hexdigest()


def test_opencode_format_agent_allows_only_exact_report_edit():
    report = "/workspace/results/reports/T001-att-001.json"
    config = opencode_backend.build_config(
        model="ollama/qwen3.8-27b:latest",
        role_name="developer",
        role_instructions="Implement only the handoff.",
        context_limit=262144,
        output_limit=32768,
        artifact_report_path=report,
    )
    permissions = config["agent"]["codexteam-format"]["permission"]
    assert config["agent"]["codexteam-format"]["prompt"] == (
        "Correct only the assigned artifact report JSON. "
        "Use only the edit or write tool on that exact report path."
    )
    assert permissions["edit"] == "allow"
    assert all(
        permissions[name] == "deny"
        for name in (
            "read", "glob", "grep", "list", "bash", "task", "skill", "lsp",
            "question", "webfetch", "websearch", "external_directory",
        )
    )


def test_opencode_format_agent_config_preserves_edit_tool_for_post_turn_audit(tmp_path: Path):
    report = "/workspace/results/reports/T001-att-001.json"
    config = opencode_backend.build_config(
        model="ollama/qwen3.8-27b:latest",
        role_name="developer",
        role_instructions="Implement only the handoff.",
        context_limit=262144,
        output_limit=32768,
        artifact_report_path=report,
    )
    path = tmp_path / "opencode.json"
    opencode_backend.write_config(path, config)
    written = json.loads(path.read_text())
    permissions = written["agent"]["codexteam-format"]["permission"]
    assert permissions["edit"] == "allow"
    assert permissions["read"] == permissions["bash"] == "deny"


def test_opencode_qwen_config_selects_only_tuned_qwen_model():
    config = opencode_backend.build_config(
        model="ollama/qwen3.6-27b:latest",
        role_name="reviewer",
        role_instructions="Review the handoff.",
        display_name="Qwen 3.6 27B",
        context_limit=262144,
        output_limit=32768,
    )
    assert config["model"] == "ollama/qwen3.6-27b:latest"
    assert config["small_model"] == "ollama/qwen3.6-27b:latest"
    assert config["provider"]["ollama"]["models"] == {
        "qwen3.6-27b:latest": {
            "name": "Qwen 3.6 27B",
            "limit": {"context": 262144, "output": 32768},
        }
    }
    assert config["agent"]["codexteam"]["model"] == "ollama/qwen3.6-27b:latest"
    assert config["agent"]["codexteam-format"]["model"] == "ollama/qwen3.6-27b:latest"


def test_opencode_qwen38_config_selects_only_tuned_qwen_model():
    config = opencode_backend.build_config(
        model="ollama/qwen3.8-27b:latest",
        role_name="developer",
        role_instructions="Implement the handoff.",
        display_name="Qwen 3.8 27B",
        context_limit=262144,
        output_limit=32768,
    )
    assert config["model"] == "ollama/qwen3.8-27b:latest"
    assert config["small_model"] == "ollama/qwen3.8-27b:latest"
    assert config["provider"]["ollama"]["models"] == {
        "qwen3.8-27b:latest": {
            "name": "Qwen 3.8 27B",
            "limit": {"context": 262144, "output": 32768},
        }
    }
    assert config["agent"]["codexteam"]["model"] == "ollama/qwen3.8-27b:latest"
    assert config["agent"]["codexteam-format"]["model"] == "ollama/qwen3.8-27b:latest"


def test_opencode_event_parser_handles_tools_steps_and_bad_streams():
    text = opencode_stream("first").replace(
        json.dumps({
            "type": "step_finish", "sessionID": THREAD_ID,
            "part": {"reason": "stop", "tokens": {"input": 10, "output": 4,
            "reasoning": 2, "cache": {"read": 3, "write": 1}}},
        }) + "\n",
        json.dumps({"type": "tool_use", "sessionID": THREAD_ID,
                    "part": {"tool": "read", "state": {"status": "completed"}}}) + "\n"
        + json.dumps({"type": "step_finish", "sessionID": THREAD_ID,
                      "part": {"reason": "tool-calls", "tokens": {"input": 1, "output": 1}}}) + "\n"
        + json.dumps({"type": "text", "sessionID": THREAD_ID, "part": {"text": "last"}}) + "\n"
        + json.dumps({"type": "step_finish", "sessionID": THREAD_ID,
                      "part": {"reason": "stop", "tokens": {"input": 2, "output": 2}}}) + "\n",
    )
    summary = opencode_backend.parse_events(text)
    assert summary.thread_ids == (THREAD_ID,)
    assert summary.last_agent_message == "last"
    assert summary.completed is True
    assert summary.parse_errors == ()

    error = opencode_backend.parse_events(
        json.dumps({"type": "error", "sessionID": THREAD_ID, "error": {"data": {"message": "bad"}}}) + "\n"
    )
    assert error.failures == ("bad",)
    malformed = opencode_backend.parse_events("not-json\n")
    assert malformed.parse_errors
    inconsistent = opencode_backend.parse_events(
        opencode_stream("x") + json.dumps({"type": "text", "sessionID": "other", "part": {"text": "y"}}) + "\n"
    )
    assert any("inconsistent" in item for item in inconsistent.parse_errors)
    for reason in ("length", "unknown"):
        non_terminal = opencode_backend.parse_events(
            json.dumps({"type": "text", "sessionID": THREAD_ID, "part": {"text": "x"}}) + "\n"
            + json.dumps({"type": "step_finish", "sessionID": THREAD_ID,
                          "part": {"reason": reason, "tokens": {}}}) + "\n"
        )
        assert non_terminal.completed is False
        assert non_terminal.terminal_reason == reason


def test_opencode_event_parser_uses_only_terminal_step_message():
    progress_id = "msg-progress"
    terminal_id = "msg-terminal"
    text = "".join((
        json.dumps({"type": "text", "sessionID": THREAD_ID, "part": {
            "messageID": progress_id, "text": "Now let me apply the edit."
        }}) + "\n",
        json.dumps({"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "messageID": progress_id, "reason": "tool-calls", "tokens": {}
        }}) + "\n",
        json.dumps({"type": "text", "sessionID": THREAD_ID, "part": {
            "messageID": terminal_id, "text": "DRAFT T002/att-001\n\nOutcome: done"
        }}) + "\n",
        json.dumps({"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "messageID": terminal_id, "reason": "stop", "tokens": {}
        }}) + "\n",
    ))

    summary = opencode_backend.parse_events(text)

    assert summary.completed is True
    assert summary.terminal_reason == "stop"
    assert summary.last_agent_message == "DRAFT T002/att-001\n\nOutcome: done"


def test_opencode_event_parser_does_not_reuse_progress_for_blank_terminal_stop():
    text = "".join((
        json.dumps({"type": "text", "sessionID": THREAD_ID, "part": {
            "messageID": "msg-progress", "text": "Now let me apply the edit."
        }}) + "\n",
        json.dumps({"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "messageID": "msg-progress", "reason": "tool-calls", "tokens": {}
        }}) + "\n",
        json.dumps({"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "messageID": "msg-terminal", "reason": "stop", "tokens": {}
        }}) + "\n",
    ))

    summary = opencode_backend.parse_events(text)

    assert summary.completed is True
    assert summary.terminal_reason == "stop"
    assert summary.last_agent_message == ""


def test_opencode_stop_without_text_accepts_valid_artifact_report(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.18")
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b")
    )
    stream = "".join((
        json.dumps({"type": "step_start", "sessionID": THREAD_ID, "part": {
            "messageID": "msg-terminal"
        }}) + "\n",
        json.dumps({"type": "step_finish", "sessionID": THREAD_ID, "part": {
            "messageID": "msg-terminal", "reason": "stop", "tokens": {}
        }}) + "\n",
    ))
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: spawn.ProcessResult(0, stream, "", 0.2),
    )

    outcome, code = spawn.run_spawn(request)

    assert code == 0
    assert outcome["status"] == "draft_ready"
    session = json.loads(request.session_path.read_text())
    assert session["thread_id"] == THREAD_ID
    assert session["last_status"] == "draft_ready"


@pytest.mark.parametrize(
    ("profile", "model", "model_id"),
    [
        ("ornith35b", "ollama/ornith:35b", "ornith:35b"),
        ("qwen36-27b", "ollama/qwen3.6-27b:latest", "qwen3.6-27b:latest"),
        ("qwen38-27b-context", "ollama/qwen3.8-27b:latest", "qwen3.8-27b:latest"),
    ],
)
def test_fake_opencode_draft_feedback_final_persists_session_and_result(
    tmp_path, monkeypatch, result_factory, profile, model, model_id
):
    result = result_factory(task_id="T002", role="developer")
    result["file_changes"] = []
    fake = tmp_path / "fake-opencode"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"session = {THREAD_ID!r}\n"
        f"result = {result!r}\n"
        "if '--version' in sys.argv: print('1.18.14'); raise SystemExit\n"
        "args = sys.argv[1:]\n"
        "home = Path(os.environ['HOME']); count_file = home / 'count'\n"
        "config_path = Path(os.environ['OPENCODE_CONFIG'])\n"
        "config = json.loads(config_path.read_text())\n"
        "assert config_path.parent == Path(os.environ['OPENCODE_CONFIG_DIR'])\n"
        "assert config_path.parents[1] == Path(os.environ['XDG_CONFIG_HOME'])\n"
        f"assert config['provider']['ollama']['models'][{model_id!r}]\n"
        "(home / 'observed-config.json').write_text(json.dumps(config))\n"
        "count = int(count_file.read_text()) if count_file.exists() else 0\n"
        "if count and args[args.index('--session') + 1] != session: raise SystemExit(8)\n"
        "count += 1; count_file.write_text(str(count))\n"
        "draft = {'schema_version':'1.0','outcome':f'turn {count}','evidence':[],'findings':[],'limitations':[],'proposed_disposition':'ready_for_review'}\n"
        "message = json.dumps(result) if args[args.index('--agent') + 1] == 'codexteam-final' else json.dumps(draft)\n"
        "print(json.dumps({'type':'step_start','sessionID':session,'part':{}}))\n"
        "print(json.dumps({'type':'text','sessionID':session,'part':{'text':message}}))\n"
        "print(json.dumps({'type':'step_finish','sessionID':session,'part':{'reason':'stop','tokens':{'input':2,'output':1,'reasoning':0,'cache':{'read':0,'write':0}}}}))\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    values = {
        "backend": "opencode",
        "profile": profile,
        "reasoning_effort": "medium" if profile == "qwen38-27b-context" else "provider_default",
    }
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, phase="draft", **values))
    (draft.workspace / "src").mkdir()
    (draft.workspace / "src/main.py").write_text("VALUE = 1\n")
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    draft_outcome, draft_code = spawn.run_spawn(draft, executable=str(fake))
    continuation_values = {"backend": "opencode", "profile": profile}
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="revise", **continuation_values)
    )
    feedback_outcome, feedback_code = spawn.run_spawn(feedback, executable=str(fake))
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **continuation_values)
    )
    final_outcome, final_code = spawn.run_spawn(final, executable=str(fake))
    session = json.loads(final.session_path.read_text())
    state = json.loads((final.session_dir / "turn-state.json").read_text())
    assert (draft_code, feedback_code, final_code) == (0, 0, 0)
    assert draft_outcome["thread_id"] == feedback_outcome["thread_id"] == THREAD_ID
    assert final_outcome["status"] == "completed"
    assert final.execution_spec["execution_profile"]["backend"]["id"] == "opencode"
    assert session["opencode_session_id"] == THREAD_ID
    assert state["opencode_session_id"] == THREAD_ID
    assert session["backend_version"] == "1.18.14"
    assert session["backend_config_digest"]
    assert session["accepted_checkpoint"]["artifact_report_sha256"]
    assert final.draft_format == "artifact-report-v1"
    assert (final.session_dir / "opencode-runtime/home/count").read_text() == "2"
    observed_config = json.loads(
        (final.session_dir / "opencode-runtime/home/observed-config.json").read_text()
    )
    assert observed_config["model"] == model
    validate_result(json.loads(final.result_path.read_text()), expected_attempt="att-001")
    assert "draft_format" not in json.loads(final.result_path.read_text())


def test_opencode_feedback_disables_pinned_handoff_mcp_permissions(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(draft_message()),
    )
    values = {"backend": "opencode", "profile": "qwen36-27b"}
    draft_args = request_args(tmp_path, monkeypatch, **values)
    handoff = Path(draft_args.workspace) / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# T002\n\nImplement the task.\n\n## Task Write Scope\n\n"
        "- `src/**`\n\n## Context Mode\n\n- `bounded-mcp`\n"
    )
    draft_args.prompt = None
    draft_args.prompt_file = str(handoff)
    draft = spawn.prepare_request(draft_args)
    spawn.run_spawn(draft)

    feedback_prompt = draft.workspace / ".codexteam/lead-prompt-T002-att-001.md"
    feedback_prompt.parent.mkdir(exist_ok=True)
    feedback_prompt.write_text("PLAN ACCEPTED\n")
    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt=None,
            prompt_file=str(feedback_prompt),
            **values,
        )
    )

    assert feedback.effective_mcp_servers == ()
    assert feedback.effective_mcp_tools == ()
    assert feedback.mcp_context_project is None
    assert feedback.execution_spec["permissions"] == draft.execution_spec["permissions"]


def test_opencode_final_rejects_workspace_changed_after_accepted_checkpoint(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    product = draft.workspace / "src/main.py"
    product.parent.mkdir()
    product.write_text("VALUE = 1\n")

    def modify_product(*args, **kwargs):
        product.write_text("VALUE = 2\n")
        return successful_opencode_process("DRAFT")

    monkeypatch.setattr(spawn, "run_process", modify_product)
    spawn.run_spawn(draft)
    product.write_text("VALUE = 3\n")
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    with pytest.raises(ValueError, match="product path mismatch"):
        spawn.run_spawn(final)


def test_opencode_final_tolerates_private_lead_prompt_update(
    tmp_path: Path, monkeypatch, result_factory
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    private_prompt = draft.workspace / ".codexteam/lead-prompt-T002-att-001.md"
    private_prompt.parent.mkdir()
    private_prompt.write_text("FEEDBACK: REVISE\n")
    product = draft.workspace / "src/main.py"
    product.parent.mkdir()
    product.write_text("VALUE = 1\n")
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    spawn.run_spawn(draft)

    private_prompt.write_text("FEEDBACK: ACCEPT\n")
    snapshot = spawn.snapshot_workspace(draft.workspace)
    assert ".codexteam/lead-prompt-T002-att-001.md" in snapshot
    assert "src/main.py" in snapshot

    result = result_factory(task_id="T002", role="developer")
    result["file_changes"] = []
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(json.dumps(result)),
    )
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, code = spawn.run_spawn(final)
    assert code == 0
    assert outcome["status"] == "completed"


def test_opencode_empty_accepted_manifest_rejects_declared_change(
    tmp_path: Path, monkeypatch, result_factory
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    spawn.run_spawn(draft)
    extra = draft.workspace / "extra.py"
    extra.write_text("EXTRA = True\n")
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    with pytest.raises(ValueError, match="latest worker turn"):
        spawn.run_spawn(final)


def test_opencode_final_allows_independent_gate_and_test_artifacts(
    tmp_path: Path, monkeypatch, result_factory
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    product = draft.workspace / "src/main.py"
    product.parent.mkdir()

    def create_product(*args, **kwargs):
        product.write_text("VALUE = 1\n")
        return successful_opencode_process("DRAFT")

    monkeypatch.setattr(spawn, "run_process", create_product)
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    spawn.run_spawn(draft)
    integration_test = draft.workspace / "tests/integration/test_feature.py"
    integration_test.parent.mkdir(parents=True)
    integration_test.write_text("def test_feature(): assert True\n")
    gate = draft.workspace / "results/gates/integration.json"
    gate.parent.mkdir(parents=True)
    gate.write_text('{"status":"passed"}\n')

    result = result_factory(task_id="T002", role="developer")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(json.dumps(result)),
    )
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, code = spawn.run_spawn(final)
    assert code == 0
    assert outcome["status"] == "completed"


def test_opencode_rolling_gate_change_is_not_an_accepted_product_path(
    tmp_path: Path, monkeypatch, result_factory
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    product = draft.workspace / "src/main.py"
    product.parent.mkdir()
    rolling_gate = draft.workspace / "results/gates/development.json"

    def worker_changes(*args, **kwargs):
        product.write_text("VALUE = 1\n")
        rolling_gate.parent.mkdir(parents=True)
        rolling_gate.write_text('{"status":"passed","run":1}\n')
        return successful_opencode_process("DRAFT")

    monkeypatch.setattr(spawn, "run_process", worker_changes)
    draft.result_dir.mkdir(exist_ok=True)
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    spawn.run_spawn(draft)
    session = json.loads(draft.session_path.read_text())
    assert "src/main.py" in session["accepted_checkpoint"]["accepted_paths"]
    assert "results/gates/development.json" not in session["accepted_checkpoint"]["accepted_paths"]
    assert "results/gates/development.json" in session["worker_change_manifest"]
    rolling_gate.write_text('{"status":"passed","run":2}\n')

    result = result_factory(task_id="T002", role="developer")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(json.dumps(result)),
    )
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, code = spawn.run_spawn(final)
    assert code == 0
    assert outcome["status"] == "completed"


def test_opencode_upstream_task_result_is_not_an_accepted_product_path(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.18")
    values = {"backend": "opencode", "profile": "qwen36-27b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    product = draft.workspace / "src/main.py"
    upstream_result = draft.workspace / "results/T001-att-001.json"

    def worker_changes(*args, **kwargs):
        product.parent.mkdir(parents=True)
        product.write_text("VALUE = 1\n")
        upstream_result.parent.mkdir(parents=True, exist_ok=True)
        upstream_result.write_text('{"status":"completed"}\n')
        return successful_opencode_process("DRAFT T002/att-001")

    monkeypatch.setattr(spawn, "run_process", worker_changes)
    spawn.run_spawn(draft)
    session = json.loads(draft.session_path.read_text())

    assert "src/main.py" in session["accepted_checkpoint"]["accepted_paths"]
    assert "results/T001-att-001.json" not in session["accepted_checkpoint"]["accepted_paths"]
    assert "results/T001-att-001.json" in session["worker_change_manifest"]


def test_opencode_failed_turn_changes_survive_noop_feedback(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    product = draft.workspace / "src/main.py"
    product.parent.mkdir()

    def failed_change(*args, **kwargs):
        product.write_text("VALUE = 1\n")
        return spawn.ProcessResult(
            1,
            json.dumps({"type": "step_start", "sessionID": THREAD_ID, "part": {}}) + "\n",
            "failed",
            0.1,
        )

    monkeypatch.setattr(spawn, "run_process", failed_change)
    outcome, code = spawn.run_spawn(draft)
    assert code == 1
    assert outcome["status"] == "turn_failed"
    failed_session = json.loads(draft.session_path.read_text())
    assert failed_session["worker_change_manifest"]["src/main.py"]["action"] == "created"

    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT recovered")
    )
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="recover", **values)
    )
    _, feedback_code = spawn.run_spawn(feedback)
    assert feedback_code == 0
    session = json.loads(feedback.session_path.read_text())
    assert session["accepted_checkpoint"]["accepted_paths"]["src/main.py"]["action"] == "created"


def test_opencode_continuation_rejects_config_mismatch(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    values = {"backend": "opencode", "profile": "ornith35b"}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, **values))
    spawn.run_spawn(draft)
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue", **values)
    )
    config = json.loads(feedback.backend_config_path.read_text())
    config["share"] = "manual"
    feedback.backend_config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="config digest mismatch"):
        spawn.run_spawn(feedback)


def test_opencode_continuation_uses_pinned_project_instructions_and_version(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch, backend="opencode", profile="ornith35b")
    workspace = Path(args.workspace)
    (workspace / "AGENTS.md").write_text("ORIGINAL PROJECT RULE\n")
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.18.14")
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT")
    )
    draft = spawn.prepare_request(args)
    spawn.run_spawn(draft)
    config_before = draft.backend_config_path.read_bytes()
    (workspace / "AGENTS.md").write_text("MUTATED PROJECT RULE\n")
    feedback = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, backend="opencode", profile="ornith35b",
            phase="feedback", prompt="continue",
        )
    )
    assert feedback.backend_config_path.read_bytes() == config_before
    outcome, code = spawn.run_spawn(feedback)
    assert code == 0
    assert outcome["status"] == "draft_ready"
    assert feedback.backend_config_path.read_bytes() == config_before
    next_feedback = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, backend="opencode", profile="ornith35b",
            phase="feedback", prompt="continue again",
        )
    )
    monkeypatch.setattr(opencode_backend, "version", lambda _executable: "1.19.0")
    with pytest.raises(ValueError, match="backend version mismatch"):
        spawn.run_spawn(next_feedback)


def test_opencode_draft_command_is_disabled(tmp_path: Path, monkeypatch, capsys):
    workspace = Path(request_args(tmp_path, monkeypatch).workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("# T002\n\n## Task Write Scope\n\n- `src/**`\n")
    code = spawn.main([
        "--backend", "opencode", "--phase", "draft", "--profile", "ornith35b",
        "--reasoning-effort", "provider_default",
        "--team", "team-1", "--task", "T002", "--attempt", "att-001",
        "--role", "developer", "--workspace", str(workspace),
        "--prompt-file", str(handoff), "--dry-run",
    ])
    assert code == 2
    assert "opencode execution is disabled" in capsys.readouterr().out


def test_opencode_draft_command_remains_disabled_with_debug_override(tmp_path: Path, monkeypatch, capsys):
    workspace = Path(request_args(tmp_path, monkeypatch).workspace)
    handoff = workspace / "management/tasks/T002.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("# T002\n\n## Task Write Scope\n\n- `src/**`\n")
    code = spawn.main([
        "--backend", "opencode", "--phase", "draft", "--profile", "ornith35b",
        "--reasoning-effort", "provider_default",
        "--team", "team-1", "--task", "T002", "--attempt", "att-001",
        "--role", "developer", "--workspace", str(workspace),
        "--prompt-file", str(handoff), "--debug-stream", "off", "--dry-run",
    ])
    assert code == 2
    assert "opencode execution is disabled" in capsys.readouterr().out
