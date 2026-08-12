import argparse
import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import codexteam_tools.spawn as spawn
from codexteam_tools import opencode_backend
from codexteam_tools.contracts import validate_result


THREAD_ID = "0199a213-81c0-7800-8aa1-bbab2a035a53"


def request_args(tmp_path: Path, monkeypatch, **overrides):
    codex_home = tmp_path / "source-codex-home"
    codex_home.mkdir(exist_ok=True)
    (codex_home / "qwen36-27b.config.toml").write_text(
        'model = "qwen"\n'
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
        "reasoning_effort": None,
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
    }
    values.update(overrides)
    return argparse.Namespace(**values)


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
    request.result_dir.mkdir()
    (request.result_dir / "evidence.txt").write_text("passed\n")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process(
            "DRAFT T002/att-001\n\nOutcome: implemented\nEvidence: focused tests pass"
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


def test_handoff_prompt_requires_draft_not_final_result(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(request_args(tmp_path, monkeypatch))
    handoff = spawn.build_handoff(request)
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))
    assert handoff["workspace_root"] == str(request.workspace)
    assert any("Return a draft" in item for item in handoff["completion_criteria"])
    assert "Do not emit result-v1" in prompt
    assert "DRAFT T002/att-001" in prompt


def test_tester_handoff_carries_host_only_gate_routing(tmp_path: Path, monkeypatch):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, role="tester", task="T003")
    )
    configure_test_gates(request.workspace, integration_surface="lead_host")

    handoff = spawn.build_handoff(request)
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))

    assert handoff["constraints"]["gate_routing"] == {
        "gate": "integration",
        "execution_surface": "lead_host",
        "worker_may_execute": False,
    }
    assert "Do not launch it from this worker" in prompt
    assert "same-digest host record" in prompt


def test_final_prompt_relies_on_schema_and_keeps_task_specific_truth(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))

    assert "matching the result-v1 contract" in prompt
    assert "team_id: team-1" in prompt
    assert "task_id: T002" in prompt
    assert "agent_role: developer" in prompt
    assert "attempt_id: att-001" in prompt
    assert "requested_followups, errors, warnings, limitations, and produced_at" in prompt
    assert "actual existing project-relative path" in prompt
    assert '"artifact_ref": "<actual existing project-relative evidence artifact>"' not in prompt
    assert "Allowed evidence types for this role" in prompt
    assert "normalized by the launcher" in prompt
    assert len(prompt) < 1600


def test_final_command_supplies_result_schema_only_for_openai_final_phase(
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
    local_final_command = spawn.build_command(final, final_turn)
    assert "--output-schema" not in local_final_command

    openai_final = replace(final, model_provider="openai")
    final_command = spawn.build_command(openai_final, final_turn)
    schema_index = final_command.index("--output-schema")

    schema_path = final.session_dir / spawn.RESULT_SCHEMA_FILENAME
    assert final_command[schema_index + 1] == str(schema_path)
    schema = json.loads(schema_path.read_text())
    assert schema["properties"]["task_id"]["const"] == "T002"
    assert schema["properties"]["agent_role"]["const"] == "developer"
    assert schema["properties"]["evidence"]["items"]["properties"]["type"][
        "enum"
    ] == list(final.role_policy.allowed_evidence_types)
    assert schema["properties"]["produced_at"]["pattern"] == "Z$"


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
    request.result_dir.mkdir()
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
    assert session["mcp_allowed_tools"] == expected
    assert session["mcp_effective_tools"] == expected
    assert state["mcp_allowed_tools"] == expected
    assert state["mcp_effective_tools"] == expected
    assert session["mcp_context_project"] == "workspace"
    assert state["mcp_context_project"] == "workspace"


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

    assert feedback.mcp_context_project == "workspace"
    assert (
        'mcp_servers.codexteam-context.env.CODEXTEAM_CONTEXT_PROJECT="workspace"'
        in mcp_overrides(command)
    )


def test_legacy_continuation_remains_unbound(tmp_path: Path, monkeypatch):
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
    del session["mcp_context_project"]
    draft.session_path.write_text(json.dumps(session))

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt="FEEDBACK: REVISE",
        )
    )

    assert feedback.mcp_context_project is None
    assert not any(
        "CODEXTEAM_CONTEXT_PROJECT" in override
        for override in mcp_overrides(
            spawn.build_command(feedback, spawn.prepare_turn(feedback))
        )
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
    session = json.loads(draft.session_path.read_text())
    session["mcp_context_project"] = "different-project"
    draft.session_path.write_text(json.dumps(session))

    with pytest.raises(ValueError, match="session MCP context project mismatch"):
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
            trust_parent_sandbox=True,
        )
    )
    resume_command = spawn.build_command(feedback, spawn.prepare_turn(feedback))
    session = json.loads(feedback.session_path.read_text())
    assert resume_command[:5] == ["codex", "-s", "danger-full-access", "exec", "resume"]
    assert session["trust_parent_sandbox"] is True


def test_parent_sandbox_mode_rejects_authenticated_openai_worker(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch, trust_parent_sandbox=True)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "qwen36-27b.config.toml").write_text(
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

    with pytest.raises(ValueError, match="reasoning effort override"):
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
    session = json.loads(feedback.session_path.read_text())

    assert session["model_reasoning_effort"] == "medium"
    assert session["reasoning_effort_override"] == "medium"
    assert 'model_reasoning_effort="medium"' in command


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

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            prompt="FEEDBACK: REVISE",
            reasoning_effort="low",
        )
    )
    with pytest.raises(ValueError, match="session model mismatch"):
        spawn.prepare_turn(feedback)


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
    assert command[command.index("-m") + 1] == "qwen"
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
    assert prompt_path.read_text() == "Implement the task.\n"
    assert stat.S_IMODE(prompt_path.stat().st_mode) == 0o600
    assert (request.session_dir / spawn.RESULT_SCHEMA_FILENAME).is_file()
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
        "schema_version",
        "team_id",
        "task_id",
        "attempt_id",
        "agent_role",
        "model_profile",
        "role_policy_name",
        "role_policy_version",
        "role_policy_digest",
        "instruction_bundle_digest",
        "result_schema_sha256",
        "model",
        "model_provider",
        "model_catalog_json",
        "model_reasoning_effort",
        "reasoning_effort_override",
        "model_verbosity",
        "mcp_allowed_servers",
        "mcp_effective_servers",
        "mcp_missing_servers",
        "mcp_allowed_tools",
        "mcp_effective_tools",
        "workspace_root",
        "trust_parent_sandbox",
        "thread_id",
        "turn_count",
        "last_phase",
        "last_status",
        "last_turn_path",
        "created_at",
        "updated_at",
        "turns",
    }
    assert set(state) == {
        "schema_version",
        "team_id",
        "task_id",
        "attempt_id",
        "agent_role",
        "model_profile",
        "role_policy_name",
        "role_policy_version",
        "role_policy_digest",
        "instruction_bundle_digest",
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
        "role_policy_name",
        "role_policy_version",
        "role_policy_digest",
        "instruction_bundle_digest",
        "result_schema_sha256",
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
            event_stream("DRAFT T002/att-001\n\nOutcome: feedback addressed"),
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
    assert session["model"] == "qwen"
    assert session["model_provider"] == "ollama_local"
    assert session["model_reasoning_effort"] == "medium"
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


def test_openai_profile_reuses_authenticated_source_home_without_copying_auth(
    tmp_path: Path, monkeypatch
):
    args = request_args(tmp_path, monkeypatch)
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "qwen36-27b.config.toml").write_text(
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


def test_completed_final_normalizes_launcher_owned_bookkeeping(
    tmp_path: Path, monkeypatch, result_factory
):
    run_draft(tmp_path, monkeypatch)
    result = result_factory(task_id="T002", role="developer")
    result["result_id"] = ""
    result["schema_version"] = "0.0"
    result["team_id"] = "wrong-team"
    result["task_id"] = "T999"
    result["agent_role"] = "reviewer"
    result["attempt_id"] = "wrong-attempt"
    result["produced_at"] = "not-utc"
    result.pop("requested_followups")
    result["warnings"] = [{"level": "cosmetic", "message": "Minor wording mismatch."}]
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process(json.dumps(result)),
    )
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )

    persisted, code = spawn.run_spawn(request)

    assert code == 0
    assert persisted["result_id"] == "res-t002-att-001"
    assert persisted["schema_version"] == "1.0"
    assert persisted["team_id"] == "team-1"
    assert persisted["task_id"] == "T002"
    assert persisted["agent_role"] == "developer"
    assert persisted["attempt_id"] == "att-001"
    assert persisted["produced_at"].endswith("Z")
    assert persisted["requested_followups"] == []
    assert persisted["warnings"] == ["Minor wording mismatch."]


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
    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("commit facts\n")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T220/att-001\n\nOutcome: planned"),
    )
    _, draft_code = spawn.run_spawn(draft)
    assert draft_code == 0

    schema = json.loads((draft.session_dir / spawn.RESULT_SCHEMA_FILENAME).read_text())
    assert schema["properties"]["file_changes"]["maxItems"] == 0
    assert "test_output" not in schema["properties"]["evidence"]["items"][
        "properties"
    ]["type"]["enum"]

    result = result_factory(task_id="T220", role="git_steward")
    result["file_changes"] = [{"path": "src/main.py", "action": "modified"}]
    result["evidence"][0]["type"] = "artifact"
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process(json.dumps(result)),
    )
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


def test_continuation_uses_session_pinned_result_schema_after_global_change(
    tmp_path: Path, monkeypatch
):
    request, _ = run_draft(tmp_path, monkeypatch)
    pinned_path = request.session_dir / spawn.RESULT_SCHEMA_FILENAME
    pinned_before = pinned_path.read_bytes()
    session = json.loads(request.session_path.read_text())
    assert session["result_schema_sha256"] == hashlib.sha256(pinned_before).hexdigest()

    changed_global = tmp_path / "changed-global-schema.json"
    changed_schema = json.loads(spawn.RESULT_SCHEMA_PATH.read_text())
    changed_schema["title"] = "Future Result Contract"
    changed_global.write_text(json.dumps(changed_schema))
    monkeypatch.setattr(spawn, "RESULT_SCHEMA_PATH", changed_global)

    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="Continue pinned attempt")
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001\n\nOutcome: continued"),
    )
    _, code = spawn.run_spawn(feedback)

    assert code == 0
    assert pinned_path.read_bytes() == pinned_before


def test_invalid_final_writes_no_result_and_session_remains_resumable(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process('{"status":"completed"}'),
    )
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    outcome, code = spawn.run_spawn(request)
    session = json.loads(request.session_path.read_text())
    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert not request.result_path.exists()
    assert session["last_status"] == "correction_needed"
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="Correct the result contract")
    )
    assert spawn.prepare_turn(feedback).number == 3


def test_final_with_missing_declared_artifact_remains_resumable(
    tmp_path: Path, monkeypatch, result_factory
):
    run_draft(tmp_path, monkeypatch)
    result = result_factory(
        task_id="T002",
        role="developer",
        artifact_ref="live command: python3 -B src/main.py",
    )
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process(json.dumps(result)),
    )
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )

    outcome, code = spawn.run_spawn(request)
    session = json.loads(request.session_path.read_text())

    assert code == 1
    assert outcome["status"] == "correction_needed"
    assert any("artifact_ref does not exist" in error for error in outcome["errors"])
    assert not request.result_path.exists()
    assert session["last_status"] == "correction_needed"
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="Correct the artifact ref")
    )
    assert spawn.prepare_turn(feedback).number == 3


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
        "message = json.dumps(final_result) if 'final' in output.name else f'DRAFT T002/att-001\\n\\nOutcome: turn {count}'\n"
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
    draft.result_dir.mkdir()
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
    assert (final.codex_home / "turn-count").read_text() == "3"
    assert len(list((final.session_dir / "turns").glob("*.jsonl"))) == 3
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
        "    message = 'DRAFT T002/att-001\\n\\nOutcome: changed diagnostic'\n"
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
    with pytest.raises(FileNotFoundError, match="Codex profile not found"):
        spawn.prepare_request(args)


def test_role_policy_supplies_default_profile_guidance_and_handoff_identity(
    tmp_path: Path, monkeypatch
):
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, profile=None, role="tester")
    )
    handoff = spawn.build_handoff(request)

    assert request.profile == "qwen36-27b"
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


def test_resume_without_profile_reuses_the_recorded_override(tmp_path: Path, monkeypatch):
    args = request_args(tmp_path, monkeypatch, profile="alternate")
    source_home = Path(spawn.os.environ["CODEX_HOME"])
    (source_home / "alternate.config.toml").write_text(
        'model = "qwen"\nmodel_provider = "ollama_local"\n'
    )
    request = spawn.prepare_request(args)
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_process("DRAFT T002/att-001"),
    )
    _, code = spawn.run_spawn(request)
    assert code == 0

    feedback = spawn.prepare_request(
        request_args(
            tmp_path,
            monkeypatch,
            phase="feedback",
            profile=None,
            prompt="FEEDBACK: REVISE",
        )
    )
    assert feedback.profile == "alternate"


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


def test_parser_and_legacy_session_default_to_codex(tmp_path: Path, monkeypatch):
    assert spawn.build_parser().parse_args(
        [
            "--phase", "draft", "--team", "team-1", "--task", "T002",
            "--attempt", "att-001", "--role", "developer", "--workspace", str(tmp_path),
            "--prompt", "work",
        ]
    ).backend == "codex"
    request, _ = run_draft(tmp_path, monkeypatch)
    session = json.loads(request.session_path.read_text())
    assert "execution_backend" not in session
    request.session_path.write_text(json.dumps(session))
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="continue")
    )
    assert feedback.backend == "codex"


def test_codex_dry_run_retains_pre_backend_shape(tmp_path: Path, monkeypatch, capsys):
    args = request_args(tmp_path, monkeypatch)
    code = spawn.main([
        "--phase", "draft", "--profile", args.profile,
        "--team", args.team, "--task", args.task, "--attempt", args.attempt,
        "--role", args.role, "--workspace", args.workspace,
        "--prompt", args.prompt, "--dry-run",
    ])

    assert code == 0
    details = json.loads(capsys.readouterr().out)
    assert set(details) == {
        "phase",
        "command",
        "profile_file",
        "role_policy",
        "role_policy_version",
        "role_policy_digest",
        "role_policy_source",
        "default_profile",
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
        "result_schema_path",
        "result_path",
        "skills",
    }
    assert details["phase"] == "draft"
    assert details["profile_file"].endswith("qwen36-27b.config.toml")
    assert details["reasoning_effort"] == "medium"
    assert details["command"][:2] == ["codex", "exec"]


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
    muse = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, backend="opencode", profile="muse-glimmer")
    )
    assert muse.model == "ollama/muse-glimmer:30b"
    assert muse.model_provider == "ollama"
    muse_config = opencode_backend.build_config(
        model=muse.model,
        role_name="Developer",
        role_instructions="Implement the task.",
    )
    assert muse_config["model"] == muse_config["small_model"] == "ollama/muse-glimmer:30b"
    assert muse_config["provider"]["ollama"]["models"] == {
        "muse-glimmer:30b": {"name": "Muse Glimmer 30B"}
    }
    with pytest.raises(ValueError, match="profile must be one of"):
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
        "models": {"ornith:35b": {"name": "Ornith 35B"}},
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
        "available_result_schema_bytes": len(
            (draft.session_dir / spawn.RESULT_SCHEMA_FILENAME).read_bytes()
        ),
    }

    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    result = result_factory(task_id="T002", role="developer")
    result["file_changes"] = []
    observed.clear()
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: observed.update(prompt=kwargs["prompt"])
        or successful_opencode_process(json.dumps(result)),
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
    final_turn = spawn.prepare_turn(final)
    checkpoint_json = json.dumps(
        final_turn.session["accepted_checkpoint"],
        indent=2,
        sort_keys=True,
    )
    _, final_code = spawn.run_spawn(final)
    assert final_code == 0

    final_metrics = json.loads(
        (final.session_dir / "turns/002-final.metrics.json").read_text()
    )
    final_config = json.loads(final.backend_config_path.read_text())
    assert final_metrics["context_bytes"] == {
        "worker_prompt_bytes": len(observed["prompt"].encode("utf-8")),
        "agent_prompt_bytes": len(
            final_config["agent"][opencode_backend.FINAL_AGENT]["prompt"].encode("utf-8")
        ),
        "lead_prompt_source_bytes": len(final.prompt.encode("utf-8")),
        "available_guidance_snapshot_bytes": len(guidance.read_bytes()),
        "available_guidance_snapshot_count": 1,
        "available_result_schema_bytes": len(
            (final.session_dir / spawn.RESULT_SCHEMA_FILENAME).read_bytes()
        ),
        "accepted_checkpoint_embedded_bytes": len(checkpoint_json.encode("utf-8")),
    }


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
    with pytest.raises(ValueError, match="backend mismatch"):
        spawn.prepare_request(
            request_args(tmp_path, monkeypatch, phase="feedback", prompt="wrong backend")
        )
    mismatched_profile = spawn.prepare_request(
        request_args(
            tmp_path, monkeypatch, backend="opencode", profile="qwen36-27b",
            phase="feedback", prompt="wrong profile",
        )
    )
    with pytest.raises(ValueError, match="session scope mismatch"):
        spawn.prepare_turn(mismatched_profile)


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

    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("passed\n")
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
    outcome, final_code = spawn.run_spawn(final)
    assert final_code == 1
    assert any(
        "must declare accepted created path: src/main.py" in error
        for error in outcome["errors"]
    )


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("reasoning_effort", "medium"),
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
        role_name="developer", role_instructions="Implement only the handoff."
    )
    assert config["plugin"] == []
    assert config["mcp"] == {}
    assert config["lsp"] is False
    assert config["skills"] == {"paths": [], "urls": []}
    assert config["enabled_providers"] == ["ollama"]
    assert config["provider"]["ollama"]["npm"] == "@ai-sdk/openai-compatible"
    final = config["agent"]["codexteam-final"]["permission"]
    assert final["edit"] == "deny"
    assert final["bash"] == "deny"
    assert final["read"] == "allow"
    assert final["webfetch"] == "deny"
    assert final["websearch"] == "deny"


def test_opencode_qwen_config_selects_only_tuned_qwen_model():
    config = opencode_backend.build_config(
        model="ollama/qwen3.6-27b:latest",
        role_name="reviewer",
        role_instructions="Review the handoff.",
    )
    assert config["model"] == "ollama/qwen3.6-27b:latest"
    assert config["small_model"] == "ollama/qwen3.6-27b:latest"
    assert config["provider"]["ollama"]["models"] == {
        "qwen3.6-27b:latest": {"name": "Qwen3.6 27B"}
    }
    assert config["agent"]["codexteam"]["model"] == "ollama/qwen3.6-27b:latest"
    assert config["agent"]["codexteam-final"]["model"] == "ollama/qwen3.6-27b:latest"


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


@pytest.mark.parametrize(
    ("profile", "model", "model_id"),
    [
        ("ornith35b", "ollama/ornith:35b", "ornith:35b"),
        ("qwen36-27b", "ollama/qwen3.6-27b:latest", "qwen3.6-27b:latest"),
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
        "message = json.dumps(result) if args[args.index('--agent') + 1] == 'codexteam-final' else f'DRAFT T002/att-001 turn {count}'\n"
        "print(json.dumps({'type':'step_start','sessionID':session,'part':{}}))\n"
        "print(json.dumps({'type':'text','sessionID':session,'part':{'text':message}}))\n"
        "print(json.dumps({'type':'step_finish','sessionID':session,'part':{'reason':'stop','tokens':{'input':2,'output':1,'reasoning':0,'cache':{'read':0,'write':0}}}}))\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    values = {"backend": "opencode", "profile": profile}
    draft = spawn.prepare_request(request_args(tmp_path, monkeypatch, phase="draft", **values))
    (draft.workspace / "src").mkdir()
    (draft.workspace / "src/main.py").write_text("VALUE = 1\n")
    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    draft_outcome, draft_code = spawn.run_spawn(draft, executable=str(fake))
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="revise", **values)
    )
    feedback_outcome, feedback_code = spawn.run_spawn(feedback, executable=str(fake))
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    final_outcome, final_code = spawn.run_spawn(final, executable=str(fake))
    session = json.loads(final.session_path.read_text())
    state = json.loads((final.session_dir / "turn-state.json").read_text())
    assert (draft_code, feedback_code, final_code) == (0, 0, 0)
    assert draft_outcome["thread_id"] == feedback_outcome["thread_id"] == THREAD_ID
    assert final_outcome["status"] == "completed"
    assert session["execution_backend"] == "opencode"
    assert session["opencode_session_id"] == THREAD_ID
    assert state["opencode_session_id"] == THREAD_ID
    assert session["backend_version"] == "1.18.14"
    assert session["backend_config_digest"]
    assert session["accepted_checkpoint"]["message_sha256"]
    assert (final.session_dir / "opencode-runtime/home/count").read_text() == "3"
    observed_config = json.loads(
        (final.session_dir / "opencode-runtime/home/observed-config.json").read_text()
    )
    assert observed_config["model"] == model
    validate_result(json.loads(final.result_path.read_text()), expected_attempt="att-001")


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
    draft.result_dir.mkdir()
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
    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    result = result_factory(task_id="T002", role="developer", file_path="extra.py")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(json.dumps(result)),
    )
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, code = spawn.run_spawn(final)
    assert code == 1
    assert any("path outside accepted product manifest: extra.py" in error for error in outcome["errors"])


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
    draft.result_dir.mkdir()
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


@pytest.mark.parametrize(
    ("declared_changes", "expected_error"),
    [
        ([], "must declare accepted created path: src/main.py"),
        (
            [{"path": "src/main.py", "action": "modified", "size_bytes": 1}],
            "must declare accepted created path: src/main.py",
        ),
        (
            [
                {"path": "src/main.py", "action": "created", "size_bytes": 1},
                {"path": "extra.py", "action": "created", "size_bytes": 1},
            ],
            "path outside accepted product manifest: extra.py",
        ),
        (
            [
                {"path": "src/main.py", "action": "created", "size_bytes": 1},
                {"path": "src/main.py", "action": "created", "size_bytes": 1},
            ],
            "duplicate path: src/main.py",
        ),
    ],
)
def test_opencode_noop_feedback_retains_provenance_and_rejects_bad_declaration(
    tmp_path: Path, monkeypatch, result_factory, declared_changes, expected_error
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
    draft.result_dir.mkdir()
    (draft.result_dir / "evidence.txt").write_text("passed\n")
    spawn.run_spawn(draft)
    monkeypatch.setattr(
        spawn, "run_process", lambda *args, **kwargs: successful_opencode_process("DRAFT revised")
    )
    feedback = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="feedback", prompt="revise", **values)
    )
    _, feedback_code = spawn.run_spawn(feedback)
    assert feedback_code == 0
    session = json.loads(feedback.session_path.read_text())
    assert session["accepted_checkpoint"]["changed_paths"] == ["src/main.py"]
    assert session["accepted_checkpoint"]["accepted_paths"]["src/main.py"]["action"] == "created"

    result = result_factory(task_id="T002", role="developer")
    result["file_changes"] = declared_changes
    if any(item["path"] == "extra.py" for item in declared_changes):
        (draft.workspace / "extra.py").write_text("EXTRA = True\n")
    monkeypatch.setattr(
        spawn,
        "run_process",
        lambda *args, **kwargs: successful_opencode_process(json.dumps(result)),
    )
    final = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="accept", **values)
    )
    outcome, code = spawn.run_spawn(final)
    assert code == 1
    assert any(expected_error in error for error in outcome["errors"])


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


def test_opencode_dry_run_has_no_reasoning_effort(tmp_path: Path, monkeypatch, capsys):
    code = spawn.main([
        "--backend", "opencode", "--phase", "draft", "--profile", "ornith35b",
        "--team", "team-1", "--task", "T002", "--attempt", "att-001",
        "--role", "developer", "--workspace", request_args(tmp_path, monkeypatch).workspace,
        "--prompt", "work", "--dry-run",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["reasoning_effort"] is None
