from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from codexteam_tools.v2 import (
    OpenCodeRuntimeAdapter,
    RuntimeBackendError,
    RuntimeOutputError,
    RuntimePreflightError,
    RuntimeSessionError,
    StageRunner,
)
from tests.v2.test_codex_adapter import FAKE_SYSTEMCTL, FAKE_SYSTEMD_RUN
from tests.v2.test_runtime import NOW, _setup


FAKE_OPENCODE = r'''#!/usr/bin/python3
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print(os.environ.get("FAKE_OPENCODE_VERSION", "1.18.16"))
    raise SystemExit(0)
if args == ["debug", "config", "--pure"]:
    value = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
    value["mode"] = {}
    value["command"] = {}
    for agent in value["agent"].values():
        agent["options"] = {}
    print(json.dumps(value))
    raise SystemExit(0)

prompt = sys.stdin.read()
runtime = Path(os.environ["OPENCODE_CONFIG"]).parents[2]
config = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
agent = args[args.index("--agent") + 1]

def permission_write(path, content):
    rule = config["agent"][agent]["permission"]["write"]
    permission_path = (Path.cwd() / path).resolve().as_posix()
    allowed = rule == "allow"
    if isinstance(rule, dict):
        allowed = False
        for pattern, action in rule.items():
            if fnmatch.fnmatchcase(permission_path, pattern):
                allowed = action == "allow"
    if not allowed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True

with (runtime / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "executable": sys.argv[0], "argv": args, "cwd": str(Path.cwd()),
        "env": dict(os.environ), "prompt": prompt,
    }) + "\n")

if (runtime / "timeout").exists():
    child = subprocess.Popen([
        "/usr/bin/setsid", "/usr/bin/python3", "-c",
        "import pathlib,time;time.sleep(2);pathlib.Path('detached.txt').write_text('bad')",
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record = Path(os.environ.get("FAKE_SYSTEMD_RECORD", ""))
    if record:
        value = json.loads(record.read_text())
        value.setdefault("members", []).append(child.pid)
        record.write_text(json.dumps(value))
    (runtime / "child.pid").write_text(str(child.pid))
    time.sleep(60)

stage = next((line.split(": ", 1)[1] for line in prompt.splitlines() if line.startswith("Stage: ")), "discovery")
session = args[args.index("--session") + 1] if "--session" in args else "ses-" + stage
candidate = args[args.index("--agent") + 1] == "readonly"
if not candidate:
    if stage == "architecture":
        permission_write(Path("docs/architecture/CLI.md"), "# CLI Architecture\n\nIterative stdlib CLI.\n")
    elif stage == "ux":
        permission_write(Path("docs/design/CLI.md"), "# CLI Design\n\n`python3 src/fib.py 7` prints `13`.\n")
    elif stage == "implementation":
        if os.environ.get("FAKE_OPENCODE_BYPASS") == "1":
            Path("go.mod").write_text("module forbidden\n")
        permission_write(Path("src/fib.py"), "import sys\n\ndef fibonacci(n: int) -> int:\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nif __name__ == '__main__':\n    print(fibonacci(int(sys.argv[1])))\n")
        permission_write(Path("tests/test_fib_unit.py"), "from project.src.fib import fibonacci\n\nassert fibonacci(7) == 13\n")
    elif stage == "verification":
        permission_write(Path("tests/integration/test_cli.py"), "import pathlib\nimport subprocess\nimport sys\n\nsource = pathlib.Path(__file__).parents[2] / 'src' / 'fib.py'\nrun = subprocess.run((sys.executable, str(source), '7'), capture_output=True, text=True)\nassert run.returncode == 0, run.stderr\nassert run.stderr == ''\nassert run.stdout == '13\\n', run.stdout\nprint('13')\n")
    value = {"summary": "completed " + stage, "notes": []}
else:
    if (runtime / "candidate-mutate").exists():
        denied = all(
            config["agent"]["readonly"]["permission"][tool] == "deny"
            for tool in ("edit", "write")
        )
        if not denied:
            Path("candidate-mutation.txt").write_text("bad\n")
    evidence_type = {"discovery": "analysis", "architecture": "artifact", "ux": "artifact", "implementation": "artifact", "verification": "test_output", "assurance": "review", "review": "review"}[stage]
    evidence = [{"evidence_type": evidence_type, "content": stage + " completed\n"}]
    if stage == "discovery":
        value = {"stage": stage, "outcome": "succeeded", "requested_optional_stages": ["architecture", "ux"], "rationale": "Both stages are useful.", "evidence": evidence}
    elif stage == "assurance":
        value = {"stage": stage, "outcome": "succeeded", "dispositions": [{"domain": "security_privacy", "disposition": "pass", "findings": []}], "evidence": evidence}
    elif stage == "review":
        value = {"stage": stage, "outcome": "succeeded", "decision": "ACCEPT", "rationale": "Evidence satisfies acceptance.", "evidence": evidence}
    else:
        value = {"stage": stage, "outcome": "succeeded", "evidence": evidence}

if (runtime / "malformed").exists():
    print("not-json")
    raise SystemExit(0)
if (runtime / "error").exists():
    print(json.dumps({"type": "error", "sessionID": session, "error": {"data": {"message": "model failed"}}}))
else:
    emitted = "ses-conflict" if (runtime / "conflict").exists() else session
    message = json.dumps(value)
    if (runtime / "fence").exists():
        message = "```json\n" + message + "\n```"
    print(json.dumps({"type": "step_start", "sessionID": emitted, "part": {}}))
    print(json.dumps({"type": "text", "sessionID": emitted, "part": {"text": message}}))
    print(json.dumps({"type": "step_finish", "sessionID": emitted, "part": {"reason": "stop"}}))
'''


def _adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, timeout: int = 5,
    stage_name: str = "discovery", model: str = "ollama/muse-glimmer:30b",
):
    test_bin = tmp_path / "test-bin"
    test_bin.mkdir(mode=0o700)
    executable = test_bin / "opencode"
    executable.write_text(FAKE_OPENCODE, encoding="utf-8")
    executable.chmod(0o700)
    systemd_bin = tmp_path / "systemd-bin"
    systemd_bin.mkdir(mode=0o700)
    (systemd_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN, encoding="utf-8")
    (systemd_bin / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8")
    (systemd_bin / "systemd-run").chmod(0o700)
    (systemd_bin / "systemctl").chmod(0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog, work, store, revision, stage = _setup(workspace, stage_name)
    adapter = OpenCodeRuntimeAdapter(
        catalog=catalog, executable=executable, model=model, timeout_seconds=timeout,
        overall_timeout_seconds=30, test_executable_root=test_bin,
        _test_only_allow_executable_root=True,
        _test_only_systemd_root=systemd_bin,
    )
    monkeypatch.setattr(adapter, "_ollama_digest", lambda: "a" * 64)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work,
        pipeline_revision=revision, stage=stage, run_id="runtime-run", now=NOW,
    )
    return adapter, runner, executable


def _runtime(tmp_path: Path) -> Path:
    return next((tmp_path / "workspace/.codexteam/v2/runtime").glob("*/opencode"))


def _calls(runtime: Path) -> list[dict]:
    return [json.loads(line) for line in (runtime / "calls.jsonl").read_text().splitlines()]


def test_assurance_and_review_prompts_require_supplied_upstream_evidence(tmp_path, monkeypatch) -> None:
    adapter, runner, _ = _adapter(tmp_path, monkeypatch)
    prepared = runner.prepare()
    context = runner._rendered_context
    assert context is not None
    for stage in ("assurance", "review"):
        role = prepared.role_instance.model_copy(update={"stage_id": stage})
        prompt = adapter._turn_prompt(role, context, "candidate", candidate=True)
        assert "decisions must use the supplied implementation candidate" in prompt
        assert "accepted verification receipt criterion evidence" in prompt
        assert "assurance report" in prompt


def test_candidate_prompts_narrow_evidence_schema_to_active_stage(tmp_path, monkeypatch) -> None:
    adapter, runner, _ = _adapter(tmp_path, monkeypatch)
    prepared = runner.prepare()
    context = runner._rendered_context
    assert context is not None
    expected = {
        "discovery": ["analysis"],
        "architecture": ["artifact"],
        "ux": ["artifact"],
        "implementation": ["artifact", "analysis"],
        "verification": ["test_output"],
        "assurance": ["review"],
        "review": ["review"],
    }
    for stage, evidence_types in expected.items():
        role = prepared.role_instance.model_copy(update={"stage_id": stage})
        prompt = adapter._turn_prompt(role, context, "candidate", candidate=True)
        schema = json.loads(prompt.rsplit("matching this schema:\n", 1)[1])
        assert schema["$defs"]["EvidenceType"]["enum"] == evidence_types


def test_config_is_strict_private_and_environment_is_clean(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOST_SECRET_TOKEN", "do-not-leak")
    _, runner, source = _adapter(tmp_path, monkeypatch)
    execution = runner.run()
    runtime = _runtime(tmp_path)
    config_path = runtime / "config/opencode/opencode.json"
    config = json.loads(config_path.read_text())
    assert execution.session_id == "ses-discovery"
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o400
    assert config["enabled_providers"] == ["ollama"]
    assert config["model"] == config["small_model"] == "ollama/muse-glimmer:30b"
    assert config["provider"]["ollama"]["models"] == {
        "muse-glimmer:30b": {
            "attachment": True,
            "family": "muse-glimmer",
            "id": "muse-glimmer:30b",
            "interleaved": "reasoning",
            "limit": {"context": 131072, "input": 114688, "output": 16384},
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "name": "Muse Glimmer 30B local",
            "reasoning": True,
            "temperature": True,
            "tool_call": True,
        }
    }
    assert config["plugin"] == [] and config["mcp"] == {}
    assert config["lsp"] is False and config["formatter"] is False
    assert config["instructions"] == [] and config["skills"] == {"paths": [], "urls": []}
    assert config["subagent_depth"] == 0 and config["share"] == "disabled"
    assert config["snapshot"] is False and config["autoupdate"] is False
    assert config["agent"]["mutable"]["permission"]["bash"] == "deny"
    assert config["agent"]["mutable"]["permission"]["edit"] == "deny"
    assert config["agent"]["mutable"]["permission"]["write"] == "deny"
    assert config["agent"]["mutable"]["permission"]["read"] == {"*": "deny", "**": "allow"}
    assert config["agent"]["readonly"]["permission"]["edit"] == "deny"
    assert config["agent"]["readonly"]["permission"]["write"] == "deny"
    session = json.loads((runtime / "session.json").read_text())
    assert session["source_executable"]["path"] == str(source)
    assert session["runtime_executable"]["path"] != str(source)
    assert session["source_executable"]["digest"] == session["runtime_executable"]["digest"]
    assert session["runtime_executable"]["mode"] == 0o500
    for call in _calls(runtime):
        assert call["cwd"] == str(tmp_path / "workspace/project")
        assert call["executable"] == session["runtime_executable"]["path"]
        assert "HOST_SECRET_TOKEN" not in call["env"]
        assert "HTTP_PROXY" not in call["env"] and "HTTPS_PROXY" not in call["env"]
        assert call["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
        assert call["env"]["OPENCODE_DISABLE_MODELS_FETCH"] == "1"


def test_effective_config_rejects_changed_edit_permission(tmp_path, monkeypatch) -> None:
    adapter, runner, _ = _adapter(tmp_path, monkeypatch, stage_name="implementation")
    original_run = subprocess.run

    def reorder(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if len(args) > 0 and "debug" in args[0]:
            value = json.loads(result.stdout)
            value["agent"]["mutable"]["permission"]["edit"] = "deny"
            result.stdout = json.dumps(value)
        return result

    monkeypatch.setattr("codexteam_tools.v2.runtime.opencode.subprocess.run", reorder)
    with pytest.raises(Exception, match="permissions changed|permission changed"):
        runner.prepare()


def test_effective_config_rejects_missing_muse_metadata(tmp_path, monkeypatch) -> None:
    _, runner, _ = _adapter(tmp_path, monkeypatch)
    original_run = subprocess.run

    def omit_metadata(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if len(args) > 0 and "debug" in args[0]:
            value = json.loads(result.stdout)
            del value["provider"]["ollama"]["models"]["muse-glimmer:30b"]["reasoning"]
            result.stdout = json.dumps(value)
        return result

    monkeypatch.setattr("codexteam_tools.v2.runtime.opencode.subprocess.run", omit_metadata)
    with pytest.raises(RuntimePreflightError, match="model metadata changed"):
        runner.prepare()


def test_exact_initial_and_resume_argv_and_session(tmp_path, monkeypatch) -> None:
    adapter, runner, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    adapter.candidate(turn.session_id, read_only=True)
    calls = _calls(_runtime(tmp_path))
    initial, resume = calls
    common = [
        "run", "--pure", "--format", "json", "--model",
        "ollama/muse-glimmer:30b",
    ]
    assert initial["argv"][:6] == common
    assert initial["argv"][initial["argv"].index("--agent") + 1] == "mutable"
    assert initial["argv"][initial["argv"].index("--dir") + 1] == str(tmp_path / "workspace/project")
    assert "--title" in initial["argv"] and "--session" not in initial["argv"]
    assert resume["argv"][:6] == common
    assert resume["argv"][resume["argv"].index("--agent") + 1] == "readonly"
    assert resume["argv"][resume["argv"].index("--session") + 1] == "ses-discovery"
    for call in calls:
        assert not {"--continue", "--fork", "--auto"} & set(call["argv"])


def test_event_parser_is_strict_and_accepts_exact_fence() -> None:
    message = json.dumps({"summary": "ok", "notes": []})
    stream = "\n".join((
        json.dumps({"type": "step_start", "sessionID": "ses-1", "part": {}}),
        json.dumps({"type": "text", "sessionID": "ses-1", "part": {"text": "old"}}),
        json.dumps({"type": "text", "sessionID": "ses-1", "part": {"text": f"```json\n{message}\n```"}}),
        json.dumps({"type": "step_finish", "sessionID": "ses-1", "part": {"reason": "stop"}}),
    ))
    session, value = OpenCodeRuntimeAdapter._parse_events(stream)
    assert session == "ses-1" and value == {"summary": "ok", "notes": []}
    with pytest.raises(RuntimeOutputError, match="invalid OpenCode JSONL"):
        OpenCodeRuntimeAdapter._parse_events("not-json")
    with pytest.raises(RuntimeSessionError, match="consistent"):
        OpenCodeRuntimeAdapter._parse_events(stream.replace('"ses-1"', '"ses-2"', 1))
    error = json.dumps({"type": "error", "sessionID": "ses-1", "message": "bad"})
    with pytest.raises(RuntimeBackendError, match="bad"):
        OpenCodeRuntimeAdapter._parse_events(error)


def test_session_config_model_workspace_and_context_drift_fail(tmp_path, monkeypatch) -> None:
    adapter, runner, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    runtime = _runtime(tmp_path)
    session_path = runtime / "session.json"
    session = json.loads(session_path.read_text())
    for field, value, match in (
        ("model", "other/model", "model mismatch"),
        ("workspace", "/tmp/other", "workspace mismatch"),
        ("context_digest", "0" * 64, "context_digest mismatch"),
    ):
        original = session[field]
        session[field] = value
        session_path.write_text(json.dumps(session, sort_keys=True, separators=(",", ":")) + "\n")
        session_path.chmod(0o600)
        with pytest.raises(RuntimeSessionError, match=match):
            adapter.candidate(turn.session_id, read_only=True)
        session[field] = original
    config_path = runtime / "config/opencode/opencode.json"
    config_path.chmod(0o600)
    config_path.write_text("{}\n")
    config_path.chmod(0o400)
    with pytest.raises(RuntimeSessionError, match="config digest changed"):
        adapter.candidate(turn.session_id, read_only=True)


def test_candidate_readonly_denial_and_stage_audit(tmp_path, monkeypatch) -> None:
    _, runner, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    runtime = _runtime(tmp_path)
    (runtime / "candidate-mutate").write_text("1")
    runner.adapter.candidate(turn.session_id, read_only=True)
    assert not (tmp_path / "workspace/project/candidate-mutation.txt").exists()


def test_timeout_kills_entire_scope(tmp_path, monkeypatch) -> None:
    _, runner, _ = _adapter(tmp_path, monkeypatch, timeout=1)
    runner.prepare()
    runtime = _runtime(tmp_path)
    (runtime / "timeout").write_text("1")
    with pytest.raises(RuntimeBackendError, match="timed out"):
        runner.draft()
    with pytest.raises(ProcessLookupError):
        os.kill(int((runtime / "child.pid").read_text()), 0)
    assert not (tmp_path / "workspace/project/detached.txt").exists()


def test_group_write_is_privately_copied_and_world_write_rejected(tmp_path, monkeypatch) -> None:
    _, runner, executable = _adapter(tmp_path, monkeypatch)
    executable.chmod(0o720)
    runner.prepare()
    runtime = _runtime(tmp_path)
    private = next((runtime / "bin").iterdir())
    assert stat.S_IMODE(private.stat().st_mode) == 0o500
    executable.chmod(0o702)
    with pytest.raises(Exception, match="world writable"):
        runner.adapter._source()


def test_production_constructor_requires_exact_pinned_path() -> None:
    from codexteam_tools.v2 import load_catalog

    with pytest.raises(ValueError, match="must be pinned"):
        OpenCodeRuntimeAdapter(catalog=load_catalog("v2"), executable="/tmp/opencode")


class _JSONResponse:
    def __init__(self, value) -> None:
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._value).encode("utf-8")


def test_ollama_pin_uses_exact_muse_tag_digest_and_metadata(tmp_path, monkeypatch) -> None:
    adapter, _, _ = _adapter(tmp_path, monkeypatch)
    monkeypatch.delattr(adapter, "_ollama_digest")
    digest = "de878ce33ad81d060001db1469a02eebe4d86f0ad58cfe52dc062fdcbe4464c1"
    requests = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        if request.full_url.endswith("/api/tags"):
            return _JSONResponse({"models": [
                {"name": "muse-glimmer:latest", "digest": "2" * 64},
                {"name": "muse-glimmer:30b", "digest": digest},
            ]})
        return _JSONResponse({
            "details": {
                "family": "muse-glimmer",
                "parameter_size": "27.9B",
                "quantization_level": "Q4_K_M",
            },
            "model_info": {"muse-glimmer.context_length": 131072},
            "capabilities": ["completion", "vision", "tools", "thinking"],
        })

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert adapter._ollama_digest() == digest
    assert requests[0].full_url.endswith("/api/tags")
    assert requests[1].full_url.endswith("/api/show")
    assert json.loads(requests[1].data) == {"model": "muse-glimmer:30b"}


def test_inactive_qwen_model_is_supported_but_rejected_by_active_agent_specs(tmp_path, monkeypatch) -> None:
    _, runner, _ = _adapter(
        tmp_path, monkeypatch, model="ollama/qwen3.6-27b:latest"
    )
    with pytest.raises(RuntimePreflightError, match="adapter OpenCode model"):
        runner.prepare()
