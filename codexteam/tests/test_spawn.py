import argparse
import json
import stat
from pathlib import Path

import pytest

import codexteam_tools.spawn as spawn
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


def test_final_prompt_includes_copyable_result_object_shapes(tmp_path: Path, monkeypatch):
    run_draft(tmp_path, monkeypatch)
    request = spawn.prepare_request(
        request_args(tmp_path, monkeypatch, phase="final", prompt="FEEDBACK: ACCEPT")
    )
    prompt = spawn.build_prompt(request, spawn.prepare_turn(request))

    assert '"action": "modified"' in prompt
    assert '"type": "artifact"' in prompt
    assert '"artifact_ref": "<actual existing project-relative evidence artifact>"' in prompt
    assert '"stderr_tail": ""' in prompt
    assert "Remove the example file-change object when no file changed" in prompt
    assert "never copy a placeholder into the result" in prompt


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
    assert stat.S_IMODE(request.codex_home.stat().st_mode) == 0o700
    assert summary["task_id"] == "T002"
    assert summary["attempt_id"] == "att-001"
    assert summary["turn"]["completed"] is True
    assert summary["turn"]["duration_seconds"] == 0.2


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
