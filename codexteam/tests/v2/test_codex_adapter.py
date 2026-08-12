from __future__ import annotations

import json
import hashlib
import os
import stat
import time
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from codexteam_tools.v2 import (
    CodexRuntimeAdapter,
    DefectPacket,
    RuntimeBackendError,
    RuntimeOutputError,
    RuntimePreflightError,
    RuntimeSessionError,
    StageRunner,
    workspace_manifest,
)
from codexteam_tools.v2.canonical import canonical_sha256
from tests.v2.test_runtime import NOW, _setup


FAKE_CODEX = r'''#!/usr/bin/python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli " + os.environ.get("FAKE_CODEX_VERSION", "0.146.1"))
    raise SystemExit(0)

if args and args[0] == "sandbox":
    cwd = Path.cwd()
    root_access = next(item for item in args if item.startswith('permissions.codexteam-direct.filesystem='))
    writable = '"write"' in root_access
    assert Path(args[args.index("-C") + 1]) == cwd
    assert Path(os.environ["CODEX_HOME"]).parent.parent.parent.parent.parent == cwd.parent
    print(json.dumps({
        "control_read": False, "runtime_read": False,
        "control_write": False, "runtime_write": False,
        "network_connect": False, "product_write": writable,
    }, sort_keys=True))
    raise SystemExit(0)

prompt = sys.stdin.read()
runtime = Path(os.environ["CODEX_HOME"]).parent
def record_scope_child(child):
    path = os.environ.get("FAKE_SYSTEMD_RECORD")
    if path:
        record = json.loads(Path(path).read_text())
        record.setdefault("members", []).append(child.pid)
        Path(path).write_text(json.dumps(record), encoding="utf-8")
(Path(os.environ["CODEX_HOME"]) / "skills").mkdir(exist_ok=True)
(Path(os.environ["CODEX_HOME"]) / "skills/state.json").write_text("{}\n", encoding="utf-8")
with (runtime / "fake-calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"executable": sys.argv[0], "argv": args, "cwd": str(Path.cwd()), "env": dict(os.environ)}) + "\n")

if (runtime / "timeout").exists():
    child = subprocess.Popen(["/usr/bin/setsid", "/usr/bin/python3", "-c", "import pathlib,time;time.sleep(2);pathlib.Path('detached.txt').write_text('bad')"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record_scope_child(child)
    (runtime / "child.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
if (runtime / "detach-on-success").exists():
    child = subprocess.Popen(["/usr/bin/setsid", "/usr/bin/python3", "-c", "import pathlib,time;time.sleep(2);pathlib.Path('detached.txt').write_text('bad')"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record_scope_child(child)
    (runtime / "child.pid").write_text(str(child.pid), encoding="utf-8")

resume_thread = next((item for item in args if item.startswith("thread-")), None)
stage = next(line.split(": ", 1)[1] for line in prompt.splitlines() if line.startswith("Stage: ")) if "Stage: " in prompt else (resume_thread.removeprefix("thread-") if resume_thread else "discovery")
thread = "thread-" + stage
candidate = "strictly read-only reporting turn" in prompt
if not candidate:
    if stage == "architecture":
        path = Path("docs/architecture/CLI.md"); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("# CLI Architecture\n\nIterative stdlib CLI with unit and integration tests.\n")
    elif stage == "ux":
        path = Path("docs/design/CLI.md"); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("# CLI Design\n\n`python3 src/fib.py 7` prints `13`.\n")
    elif stage == "implementation":
        source = Path("src/fib.py"); source.parent.mkdir(parents=True, exist_ok=True); source.write_text("import sys\n\ndef fibonacci(n: int) -> int:\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nif __name__ == '__main__':\n    print(fibonacci(int(sys.argv[1])))\n")
        unit = Path("tests/test_fib_unit.py"); unit.parent.mkdir(parents=True, exist_ok=True); unit.write_text("from project.src.fib import fibonacci\n\nassert fibonacci(7) == 13\n")
    elif stage == "verification":
        integration = Path("tests/integration/test_cli.py"); integration.parent.mkdir(parents=True, exist_ok=True); integration.write_text("import pathlib\nimport subprocess\nimport sys\n\nsource = pathlib.Path(__file__).parents[2] / 'src' / 'fib.py'\nrun = subprocess.run((sys.executable, str(source), '7'), capture_output=True, text=True)\nassert run.returncode == 0, run.stderr\nassert run.stderr == ''\nassert run.stdout == '13\\n', run.stdout\nprint('13')\n")
    value = {"summary": "completed " + stage, "notes": []}
else:
    if (runtime / "candidate-mutation").exists():
        sandbox = next(item for item in args if item.startswith('sandbox_mode='))
        candidate_write = sandbox != 'sandbox_mode="read-only"'
        if candidate_write:
            Path("candidate-mutation.txt").write_text("bad\n")
        (runtime / "candidate-write-result").write_text(json.dumps(candidate_write), encoding="utf-8")
    evidence_type = {"discovery": "analysis", "architecture": "artifact", "ux": "artifact", "implementation": "artifact", "verification": "test_output", "assurance": "review", "review": "review"}[stage]
    evidence = [{"evidence_type": evidence_type, "content": stage + " completed\n"}]
    if stage == "discovery":
        value = {"stage": "discovery", "outcome": "succeeded", "requested_optional_stages": ["architecture", "ux"], "rationale": "Both design stages are required.", "evidence": evidence}
    elif stage == "assurance":
        value = {"stage": "assurance", "outcome": "succeeded", "dispositions": [{"domain": "security_privacy", "disposition": "pass", "findings": []}], "evidence": evidence}
    elif stage == "review":
        value = {"stage": "review", "outcome": "succeeded", "decision": "ACCEPT", "rationale": "Independent evidence satisfies acceptance.", "evidence": evidence}
    else:
        value = {"stage": stage, "outcome": "succeeded", "evidence": evidence}

if (runtime / "malformed-semantic").exists():
    value = {"summary": 3}
message = json.dumps(value)
if (runtime / "fence-only").exists():
    message = "```json\n" + message + "\n```"
if (runtime / "prose-fence").exists():
    message = "Here is the result:\n```json\n" + message + "\n```"
if not resume_thread or (runtime / "resume-thread").exists():
    emitted = "thread-conflict" if (runtime / "conflict-thread").exists() else thread
    if not (runtime / "missing-thread").exists():
        print(json.dumps({"type": "thread.started", "thread_id": emitted}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": message}}))
if (runtime / "malformed-final").exists():
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "not-json"}}))
if (runtime / "item-error").exists():
    print(json.dumps({"type": "item.completed", "item": {"type": "error", "message": "sandbox configuration failed"}}))
print(json.dumps({"type": "turn.completed"}))
'''


FAKE_SYSTEMD_RUN = r'''#!/usr/bin/python3
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if sys.argv[1:] == ["--version"]:
    print("systemd 255")
    raise SystemExit(0)
args = sys.argv[1:]
unit = next(item.split("=", 1)[1] for item in args if item.startswith("--unit="))
command = args[args.index("--") + 1:]
state = Path(__file__).parent / "state"
state.mkdir(exist_ok=True)
with (state / "run.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")
ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)
child_env = dict(os.environ)
child_env["FAKE_SYSTEMD_MEMBER"] = unit
record = state / (unit + ".json")
child_env["FAKE_SYSTEMD_RECORD"] = str(record)
process = subprocess.Popen(command, env=child_env)
record.write_text(
    json.dumps({"wrapper": os.getpid(), "command": process.pid}), encoding="utf-8"
)
returncode = process.wait()
members = []
try:
    members.extend(json.loads(record.read_text()).get("members", []))
except FileNotFoundError:
    pass
for path in Path("/proc").glob("[0-9]*/stat"):
    try:
        values = path.read_text().split()
        if int(values[3]) == os.getpid():
            members.append(int(values[0]))
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass
record.write_text(
    json.dumps({"wrapper": os.getpid(), "command": process.pid, "members": members}),
    encoding="utf-8",
)
raise SystemExit(returncode)
'''


FAKE_SYSTEMCTL = r'''#!/usr/bin/python3
import json
import os
from pathlib import Path
import signal
import sys

if sys.argv[1:] == ["--version"]:
    print("systemd 255")
    raise SystemExit(0)
args = sys.argv[1:]
state = Path(__file__).parent / "state"
state.mkdir(exist_ok=True)
with (state / "control.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False

def descendants(roots):
    result = set(roots)
    changed = True
    while changed:
        changed = False
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                values = path.read_text().split()
                pid, parent = int(values[0]), int(values[3])
                if parent in result and pid not in result:
                    result.add(pid)
                    changed = True
            except (FileNotFoundError, ProcessLookupError, ValueError):
                pass
    return result

def unit_members(unit_name):
    expected = b"FAKE_SYSTEMD_MEMBER=" + unit_name.removesuffix(".scope").encode()
    result = set()
    for path in Path("/proc").glob("[0-9]*/environ"):
        try:
            if expected in path.read_bytes().split(b"\0"):
                result.add(int(path.parent.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            pass
    return result

operation = args[1]
unit = next((item for item in args[2:] if item.endswith(".scope")), "")
path = state / (unit.removesuffix(".scope") + ".json")
try:
    value = json.loads(path.read_text())
except FileNotFoundError:
    value = None
if operation == "show":
    roots = [] if not value else [value["wrapper"], value["command"], *value.get("members", [])]
    active = any(alive(pid) for pid in descendants(roots) | unit_members(unit))
    print("LoadState=" + ("loaded" if active else "not-found"))
    print("ActiveState=" + ("active" if active else "inactive"))
    print("SubState=" + ("running" if active else "dead"))
elif operation == "kill":
    if not value:
        print("Unit not loaded", file=sys.stderr)
        raise SystemExit(1)
    roots = [value["wrapper"], value["command"], *value.get("members", [])]
    for pid in sorted(descendants(roots) | unit_members(unit), reverse=True):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
elif operation not in {"reset-failed", "clean"}:
    raise SystemExit(2)
'''


def _source_home(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "source-home"
    home.mkdir(mode=0o700)
    catalog_dir = home / "catalogs"
    catalog_dir.mkdir(mode=0o700)
    catalog = catalog_dir / "models.json"
    catalog.write_text(json.dumps({"models": [{
        "slug": "qwen3.6-27b", "display_name": "Qwen", "description": "local",
        "provider": "ollama_local", "enabled": True,
        "supported_reasoning_levels": [
            {"effort": "medium", "description": "medium"},
            {"effort": "xhigh", "description": "xhigh"},
        ],
        "shell_type": "shell_command", "visibility": "list", "supported_in_api": True,
        "base_instructions": "safe", "model_messages": {}, "supports_reasoning_summaries": True,
        "default_reasoning_summary": "none", "support_verbosity": True,
        "default_verbosity": "medium", "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image", "supports_search_tool": True,
        "experimental_supported_tools": ["web_search"], "input_modalities": ["text", "image"],
        "context_window": 262144, "max_context_window": 262144,
        "effective_context_window_percent": 95, "supports_parallel_tool_calls": True,
    }, {"slug": "other", "provider": "ollama_local"}]}), encoding="utf-8")
    catalog.chmod(0o600)
    profile = home / "qwen36-27b.config.toml"
    profile.write_text(
        f'model = "qwen3.6-27b"\nmodel_provider = "ollama_local"\nmodel_catalog_json = "{catalog}"\nmodel_reasoning_effort = "xhigh"\napi_key = "DO-NOT-COPY"\n',
        encoding="utf-8",
    )
    profile.chmod(0o600)
    return home, profile, catalog


def _adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, timeout: int = 5):
    test_bin = tmp_path / "test-bin"
    test_bin.mkdir(mode=0o700)
    executable = test_bin / "codex"
    executable.write_text(FAKE_CODEX, encoding="utf-8")
    executable.chmod(0o700)
    systemd_bin = tmp_path / "systemd-bin"
    systemd_bin.mkdir(mode=0o700)
    (systemd_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN, encoding="utf-8")
    (systemd_bin / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8")
    (systemd_bin / "systemd-run").chmod(0o700)
    (systemd_bin / "systemctl").chmod(0o700)
    home, profile, source_catalog = _source_home(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog, work, store, revision, stage = _setup(workspace)
    adapter = CodexRuntimeAdapter(
        catalog=catalog, executable=executable, codex_home=home,
        timeout_seconds=timeout, overall_timeout_seconds=30,
        test_executable_root=test_bin, _test_only_allow_executable_root=True,
        _test_only_systemd_root=systemd_bin,
    )
    monkeypatch.setattr(adapter, "_ollama_digest", lambda selected_context_window=None: "a" * 64)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work,
        pipeline_revision=revision, stage=stage, run_id="runtime-run", now=NOW,
    )
    return adapter, runner, profile, source_catalog, executable


def _js_package(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "node_modules/@openai/codex"
    launcher = root / "bin/codex.js"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    launcher.chmod(0o755)
    package = root / "package.json"
    package.write_text(json.dumps({
        "name": "@openai/codex", "version": "0.146.1",
        "bin": {"codex": "bin/codex.js"},
    }), encoding="utf-8")
    package.chmod(0o644)
    target = root / "node_modules/@openai/codex-linux-x64"
    target.mkdir(parents=True)
    target_package = target / "package.json"
    target_package.write_text(json.dumps({
        "name": "@openai/codex", "version": "0.146.1-linux-x64",
        "os": ["linux"], "cpu": ["x64"],
    }), encoding="utf-8")
    target_package.chmod(0o644)
    native = target / "vendor/x86_64-unknown-linux-musl/bin/codex"
    native.parent.mkdir(parents=True)
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (62).to_bytes(2, "little")
    native.write_bytes(header)
    native.chmod(0o755)
    return launcher, package, target_package, native


def _runtime(tmp_path: Path) -> Path:
    return next(path for path in (tmp_path / "workspace/.codexteam/v2/runtime").iterdir() if path.is_dir())


def _touch_control(tmp_path: Path, name: str) -> Path:
    path = _runtime(tmp_path) / name
    path.write_text("1", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_codex_adapter_pins_config_private_home_and_sanitized_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOST_SECRET_TOKEN", "must-not-leak")
    adapter, runner, _, source_catalog, _ = _adapter(tmp_path, monkeypatch)
    execution = runner.run()
    assert execution.session_id == "thread-discovery"
    runtime = _runtime(tmp_path)
    home = runtime / "codex-home"
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    session = json.loads((runtime / "session.json").read_text())
    calls = [json.loads(line) for line in (runtime / "fake-calls.jsonl").read_text().splitlines()]
    assert calls[0]["argv"][:3] == ["exec", "--profile", "qwen36-27b"]
    assert calls[1]["argv"][:2] == ["exec", "resume"]
    assert "--profile" not in calls[1]["argv"]
    assert "thread-discovery" in calls[1]["argv"] and "--last" not in calls[1]["argv"]
    for call in calls:
        argv = call["argv"]
        assert call["executable"] == session["runtime_executable"]["path"]
        assert call["cwd"] == str(tmp_path / "workspace/project")
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv
        assert "--ignore-user-config" in argv
        assert "--ignore-rules" in argv
        assert "--strict-config" in argv
        joined = " ".join(argv)
        assert 'model_reasoning_effort="medium"' in joined
        assert 'model_verbosity="medium"' in joined
        assert 'approval_policy="never"' in joined
        assert 'default_permissions="codexteam-direct"' in joined
        filesystem_arg = next(
            item for item in argv
            if item.startswith("permissions.codexteam-direct.filesystem=")
        )
        assert f'{tmp_path / "workspace/.codexteam"}' in filesystem_arg
        assert '="none"' in filesystem_arg
        assert f'{tmp_path / "workspace/project"}' in filesystem_arg
        assert 'permissions.codexteam-direct.network.enabled=false' in joined
        assert "use_legacy_landlock" not in joined
        assert call["env"]["HOME"].endswith("/codex-home/home")
        assert call["env"]["CODEX_HOME"] == str(home)
        assert call["env"]["XDG_CONFIG_HOME"] == str(home / "xdg/config")
        assert "HOST_SECRET_TOKEN" not in call["env"]
    assert calls[0]["argv"][calls[0]["argv"].index("-s") + 1] == "workspace-write"
    assert 'sandbox_mode="read-only"' in " ".join(calls[1]["argv"])
    generated = json.loads((home / "model-catalog.json").read_text())
    assert stat.S_IMODE((home / "model-catalog.json").stat().st_mode) == 0o400
    assert len(generated["models"]) == 1
    assert [item["slug"] for item in generated["models"]] == ["qwen3.6-27b"]
    assert generated["models"][0]["supported_reasoning_levels"] == [{"effort": "medium", "description": "medium"}]
    captured = "".join(path.read_text(errors="ignore") for path in runtime.rglob("*") if path.is_file())
    assert "DO-NOT-COPY" not in captured and "must-not-leak" not in captured
    assert session["source_executable"]["digest"] == session["runtime_executable"]["digest"]
    assert session["systemd"]["version"] == "255"
    assert session["systemd"]["systemd_run"]["digest"]
    assert session["systemd"]["systemctl"]["digest"]
    assert session["source_executable"]["path"] != session["runtime_executable"]["path"]
    assert session["source_chain_digest"] == canonical_sha256(session["source_chain"])
    assert session["runtime_executable"]["mode"] == 0o500
    private_executable = Path(session["runtime_executable"]["path"])
    assert stat.S_IMODE(private_executable.stat().st_mode) == 0o500
    assert (home / "skills/state.json").exists()
    assert stat.S_IMODE((home / "config.toml").stat().st_mode) == 0o400
    assert session["material"]["effective_config"]["model_reasoning_effort"] == "medium"
    assert "features.use_legacy_landlock" not in session["material"]["effective_config"]
    assert "use_legacy_landlock" not in (home / "config.toml").read_text()
    assert session["material"]["source_profile_digest"]
    source_record = json.loads(source_catalog.read_text())["models"][0]
    assert session["material"]["selected_record_digest"] == canonical_sha256(source_record)
    assert session["material"]["selected_context_window"] == 262144
    assert session["ollama_model_digest"] == "a" * 64
    assert session["workspace"] == str(tmp_path / "workspace/project")
    assert session["private_codex_home"] == str(home)
    assert session["outer_sandbox"] == "host-parent-native-read-only"
    assert adapter.sessions == {"discovery": "thread-discovery"}


def test_codex_preflight_native_sandbox_probe_runs_once_through_adapter(tmp_path, monkeypatch) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    calls = 0

    def counted(role, workspace, executable):
        nonlocal calls
        calls += 1
        before = workspace_manifest(workspace).root_digest
        assert workspace_manifest(workspace).root_digest == before
        return ()

    monkeypatch.setattr(adapter, "_sandbox_capability_probe", counted)
    runner.prepare()
    assert calls == 1


def test_native_sandbox_probe_uses_supported_command_and_private_runtime(
    tmp_path, monkeypatch,
) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    prepared = runner.prepare()
    executable = adapter._role_executables[prepared.role_instance.role_instance_id].runtime
    captured = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({
            "control_read": False, "runtime_read": False,
            "control_write": False, "runtime_write": False,
            "network_connect": False, "product_write": False,
        })
        stderr = ""

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return Completed()

    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setattr(adapter, "_role_can_write_product", lambda role: False)
    monkeypatch.setattr(
        adapter, "_sandbox_capability_probe",
        CodexRuntimeAdapter._sandbox_capability_probe.__get__(adapter),
    )
    adapter._sandbox_capability_probe(prepared.role_instance, tmp_path / "workspace", executable)
    command = captured["argv"]
    sandbox = command.index("sandbox")
    assert command[sandbox:sandbox + 3] == ["sandbox", "-C", str(tmp_path / "workspace/project")]
    assert command[sandbox + 3] == "-P"
    assert command[sandbox + 4] == "codexteam-direct"
    assert "linux" not in command[sandbox:sandbox + 5]
    assert "use_legacy_landlock" not in " ".join(command)
    assert "--sandbox-state-disable-network" in command
    assert "/usr/bin/python3" in command
    assert captured["cwd"] == tmp_path / "workspace/project"
    assert captured["env"]["CODEX_HOME"] == str(_runtime(tmp_path) / "codex-home")


def test_host_command_uses_product_root_without_outer_bwrap(tmp_path, monkeypatch) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    prepared = runner.prepare()
    executable = adapter._role_executables[prepared.role_instance.role_instance_id].runtime
    command = adapter._command(
        prepared.role_instance, tmp_path / "workspace/project", executable,
        session=None, read_only=False,
    )
    assert command[0] == executable.path
    assert command[1:4] == ["exec", "--profile", "qwen36-27b"]
    assert command[command.index("-C") + 1] == str(tmp_path / "workspace/project")
    assert "/usr/bin/bwrap" not in command


def test_live_turn_wrapper_uses_pinned_scope_and_private_codex(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.draft()
    runs = [
        json.loads(line)
        for line in (tmp_path / "systemd-bin/state/run.jsonl").read_text().splitlines()
    ]
    turn = next(args for args in runs if "exec" in args)
    assert turn[:3] == ["--user", "--scope", "--quiet"]
    assert any(item.startswith("--unit=ctv2-") for item in turn)
    assert "--property=KillMode=control-group" in turn
    assert "--property=CollectMode=inactive-or-failed" in turn
    command = turn[turn.index("--") + 1:]
    session = json.loads((_runtime(tmp_path) / "session.json").read_text())
    assert command[0] == session["runtime_executable"]["path"]


def test_codex_adapter_malformed_output_retains_session_for_correction(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "malformed-semantic")
    with pytest.raises(RuntimeOutputError, match="SemanticResponse"):
        runner.draft()
    assert list((tmp_path / "workspace/.codexteam/v2/runtime").glob("*/session.json"))


def test_final_malformed_agent_message_does_not_fall_back(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "malformed-final")
    with pytest.raises(RuntimeOutputError, match="final Codex agent message"):
        runner.draft()


def test_final_fence_only_message_is_accepted(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "fence-only")
    assert runner.draft().response.summary == "completed discovery"


def test_final_prose_plus_fence_is_rejected(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "prose-fence")
    with pytest.raises(RuntimeOutputError, match="final Codex agent message"):
        runner.draft()


@pytest.mark.parametrize("message", [
    "```json\n{}\n```\n```json\n{}\n```",
    "```JSON\n{}\n```",
    "```python\n{}\n```",
    "```json\n{malformed}\n```",
    "```json {} ```",
])
def test_final_message_parser_rejects_unsupported_fences(message) -> None:
    with pytest.raises(RuntimeOutputError, match="final Codex agent message"):
        CodexRuntimeAdapter._parse_final_message(message)


def test_final_message_parser_accepts_raw_object_and_exact_json_fence() -> None:
    expected = {"summary": "ok"}
    assert CodexRuntimeAdapter._parse_final_message(' \n{"summary":"ok"}\n ') == expected
    assert CodexRuntimeAdapter._parse_final_message(
        ' \n```json\n{"summary":"ok"}\n```\n '
    ) == expected


def test_item_completed_error_fails_even_when_turn_completes(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "item-error")
    with pytest.raises(RuntimeBackendError, match="sandbox configuration failed"):
        runner.draft()


def test_initial_thread_is_required_and_resume_conflict_is_rejected(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    missing = _touch_control(tmp_path, "missing-thread")
    with pytest.raises(RuntimeSessionError, match="exactly one thread"):
        runner.draft()
    missing.unlink()
    turn = runner.draft()
    _touch_control(tmp_path, "resume-thread")
    _touch_control(tmp_path, "conflict-thread")
    with pytest.raises(RuntimeSessionError, match="conflicting thread"):
        runner.adapter.candidate(turn.session_id, read_only=True)


def test_session_runtime_and_model_drift_fail_closed(tmp_path, monkeypatch) -> None:
    adapter, runner, _, _, executable = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    session_path = _runtime(tmp_path) / "session.json"
    session = json.loads(session_path.read_text())
    original_context_digest = session["context_digest"]
    session["context_digest"] = "0" * 64
    session_path.write_text(json.dumps(session), encoding="utf-8")
    session_path.chmod(0o600)
    with pytest.raises(RuntimeSessionError, match="canonical JSON"):
        adapter.candidate(turn.session_id, read_only=True)

    session_path.write_text(json.dumps(session, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeSessionError, match="context_digest mismatch"):
        adapter.candidate(turn.session_id, read_only=True)

    session["context_digest"] = original_context_digest
    session_path.write_text(json.dumps(session, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    monkeypatch.setattr(adapter, "_ollama_digest", lambda selected_context_window=None: "b" * 64)
    with pytest.raises(RuntimeSessionError, match="model digest changed"):
        adapter.candidate(turn.session_id, read_only=True)

    monkeypatch.setattr(adapter, "_ollama_digest", lambda selected_context_window=None: "a" * 64)
    replacement = executable.with_name("codex-replacement")
    replacement.write_text(FAKE_CODEX + "\n# drift\n", encoding="utf-8")
    replacement.chmod(0o700)
    os.replace(replacement, executable)
    with pytest.raises(RuntimeSessionError, match="source executable identity changed"):
        adapter.candidate(turn.session_id, read_only=True)


def test_continuation_uses_pinned_private_copies_and_rejects_runtime_catalog_drift(tmp_path, monkeypatch) -> None:
    adapter, runner, profile, _, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    profile.write_text("source may change after generation\n", encoding="utf-8")
    adapter.candidate(turn.session_id, read_only=True)
    runtime_catalog = _runtime(tmp_path) / "codex-home/model-catalog.json"
    runtime_catalog.chmod(0o600)
    runtime_catalog.write_text('{"models":[]}\n', encoding="utf-8")
    runtime_catalog.chmod(0o400)
    with pytest.raises(RuntimeSessionError, match="catalog digest changed"):
        adapter.candidate(turn.session_id, read_only=True)


@pytest.mark.parametrize(
    ("profile_text", "match"),
    [
        ('model = "wrong"\nmodel_provider = "ollama_local"\nmodel_catalog_json = "/tmp/no"\n', "role model"),
        ('model = "qwen3.6-27b"\nmodel_provider = "openai"\nmodel_catalog_json = "/tmp/no"\n', "ollama_local"),
    ],
)
def test_codex_adapter_rejects_profile_mismatch(tmp_path, monkeypatch, profile_text, match) -> None:
    _, runner, profile, _, _ = _adapter(tmp_path, monkeypatch)
    profile.write_text(profile_text, encoding="utf-8")
    with pytest.raises(RuntimePreflightError, match=match):
        runner.prepare()


def test_codex_adapter_allows_only_group_writable_owner_catalog_data(tmp_path, monkeypatch) -> None:
    _, runner, profile, source_catalog, executable = _adapter(tmp_path, monkeypatch)
    source_catalog.chmod(0o620)
    prepared = runner.prepare()
    private_catalog = _runtime(tmp_path) / "codex-home/model-catalog.json"
    assert stat.S_IMODE(private_catalog.stat().st_mode) == 0o400
    assert len(json.loads(private_catalog.read_text())["models"]) == 1
    assert any("source model catalog is group writable" in item for item in prepared.preflight.enforcement_limitations)

    source_catalog.chmod(0o602)
    with pytest.raises(RuntimePreflightError, match="world writable"):
        runner.adapter._source_material()

    source_catalog.chmod(0o600)
    profile.chmod(0o620)
    with pytest.raises(RuntimePreflightError, match="group writable"):
        runner.adapter._source_material()

    profile.chmod(0o600)
    executable.chmod(0o720)
    with pytest.raises(RuntimePreflightError, match="group writable"):
        runner.adapter._source_executable()


def test_group_writable_catalog_rejects_foreign_owner_and_group(tmp_path, monkeypatch) -> None:
    adapter, _, _, source_catalog, _ = _adapter(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign-catalog.json"
    foreign.write_text('{}\n', encoding="utf-8")
    foreign.chmod(0o620)
    monkeypatch.setattr(os, "getuid", lambda: foreign.stat().st_uid + 1)
    with pytest.raises(RuntimePreflightError, match="owned by the current user"):
        adapter._read_pinned(
            foreign, "foreign catalog", owners={foreign.stat().st_uid},
            allow_owner_group_write_data=True,
        )

    monkeypatch.setattr(os, "getuid", lambda: source_catalog.stat().st_uid)
    source_catalog.chmod(0o620)
    monkeypatch.setattr(os, "getgroups", lambda: [])
    monkeypatch.setattr(os, "getgid", lambda: source_catalog.stat().st_gid + 1)
    monkeypatch.setattr(os, "getegid", lambda: source_catalog.stat().st_gid + 1)
    with pytest.raises(RuntimePreflightError, match="current user's groups"):
        adapter._source_material()


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"provider": "openai"}, "provider must be ollama_local"),
        ({"enabled": False}, "must be enabled"),
        ({"model_provider": "openai"}, "provider must be ollama_local"),
        ({"context_window": 0}, "positive integers"),
        ({"max_context_window": 131072}, "must be equal"),
    ],
)
def test_codex_adapter_rejects_untrusted_selected_catalog_record(
    tmp_path, monkeypatch, updates, match
) -> None:
    adapter, _, _, source_catalog, _ = _adapter(tmp_path, monkeypatch)
    value = json.loads(source_catalog.read_text())
    value["models"][0].update(updates)
    source_catalog.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimePreflightError, match=match):
        adapter._source_material()


def test_source_catalog_change_between_preflight_and_turn_is_rejected(tmp_path, monkeypatch) -> None:
    _, runner, _, source_catalog, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    value = json.loads(source_catalog.read_text())
    value["models"][0]["description"] = "changed after preflight"
    source_catalog.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimePreflightError, match="identity changed since preflight"):
        runner.draft()


class _JSONResponse:
    def __init__(self, value) -> None:
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._value).encode("utf-8")


def test_ollama_pin_requires_exact_name_digest_and_sufficient_context(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    monkeypatch.undo()
    digest = "a" * 64
    requests = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        if request.full_url.endswith("/api/tags"):
            return _JSONResponse({"models": [
                {"name": "qwen3.6-27b:other", "digest": "2" * 64},
                {"name": "qwen3.6-27b:latest", "digest": digest},
            ]})
        return _JSONResponse({"model_info": {"qwen3.context_length": 262144}})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert adapter._ollama_digest(262144) == digest
    assert json.loads(requests[1].data) == {"model": "qwen3.6-27b:latest"}

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, **_kwargs: _JSONResponse({"models": [
            {"name": "qwen3.6-27b:latest", "digest": digest.upper()},
        ]}),
    )
    with pytest.raises(RuntimePreflightError, match="invalid model digest"):
        adapter._ollama_digest()


def test_ollama_show_context_mismatch_fails_closed(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    monkeypatch.undo()

    def urlopen(request, **_kwargs):
        if request.full_url.endswith("/api/tags"):
            return _JSONResponse({"models": [{
                "name": "qwen3.6-27b:latest", "digest": "1" * 64,
            }]})
        return _JSONResponse({"model_info": {"qwen3.context_length": 131072}})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(RuntimePreflightError, match="smaller than the selected catalog"):
        adapter._ollama_digest(262144)


def test_ollama_show_may_be_explicitly_unsupported(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    monkeypatch.undo()

    def urlopen(request, **_kwargs):
        if request.full_url.endswith("/api/tags"):
            return _JSONResponse({"models": [{
                "name": "qwen3.6-27b:latest", "digest": "1" * 64,
            }]})
        raise urllib.error.HTTPError(request.full_url, 404, "not found", Message(), None)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert adapter._ollama_digest(262144) == "1" * 64


def test_codex_adapter_resolves_known_js_package_without_node(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, _, _, native = _js_package(tmp_path)
    adapter.executable = launcher
    content, pin, source_chain, source_chain_digest = adapter._source_executable()
    assert pin.path == str(native)
    assert pin.mode == 0o755
    assert pin.digest == hashlib.sha256(content).hexdigest()
    assert tuple(Path(item.path).name for item in source_chain) == (
        "codex.js", "package.json", "package.json", "codex",
    )
    assert source_chain_digest == canonical_sha256(source_chain)


def test_codex_adapter_rejects_wrong_js_platform_target(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, _, metadata, _ = _js_package(tmp_path)
    value = json.loads(metadata.read_text())
    value["cpu"] = ["arm64"]
    metadata.write_text(json.dumps(value), encoding="utf-8")
    adapter.executable = launcher
    with pytest.raises(RuntimePreflightError, match="x86_64 Linux target"):
        adapter._source_executable()


def test_group_writable_current_user_package_source_is_copied_and_only_private_copy_executes(
    tmp_path, monkeypatch,
) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, package, target_package, native = _js_package(tmp_path)
    native.write_text(FAKE_CODEX, encoding="utf-8")
    for path in (launcher, package, target_package, native):
        path.chmod(0o660)
    adapter.executable = launcher
    monkeypatch.setattr(adapter, "_validate_x64_linux_elf", lambda _content: None)

    turn = runner.draft()
    runtime = _runtime(tmp_path)
    calls = [json.loads(line) for line in (runtime / "fake-calls.jsonl").read_text().splitlines()]
    session = json.loads((runtime / "session.json").read_text())

    assert turn.session_id == "thread-discovery"
    expected_executable = session["runtime_executable"]["path"]
    assert stat.S_IMODE(Path(expected_executable).stat().st_mode) == 0o500
    assert calls[0]["executable"] == expected_executable
    assert all(call["executable"] not in {str(launcher), str(native)} for call in calls)
    assert len(session["source_chain"]) == 4
    assert session["source_chain_digest"] == canonical_sha256(session["source_chain"])


@pytest.mark.parametrize("mode", [0o662, 0o666])
def test_package_source_rejects_world_writable_files(tmp_path, monkeypatch, mode) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, package, _, _ = _js_package(tmp_path)
    package.chmod(mode)
    adapter.executable = launcher
    with pytest.raises(RuntimePreflightError, match="world writable"):
        adapter._source_executable()


def test_group_writable_package_source_rejects_foreign_group(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, package, _, _ = _js_package(tmp_path)
    package.chmod(0o660)
    adapter.executable = launcher
    monkeypatch.setattr(os, "getgroups", lambda: [])
    monkeypatch.setattr(os, "getgid", lambda: package.stat().st_gid + 1)
    monkeypatch.setattr(os, "getegid", lambda: package.stat().st_gid + 1)
    with pytest.raises(RuntimePreflightError, match="current user's groups"):
        adapter._source_executable()


@pytest.mark.parametrize("source_name", ["launcher", "package", "platform", "native"])
def test_package_source_mutation_after_preflight_fails_session(
    tmp_path, monkeypatch, source_name,
) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    launcher, package, target_package, native = _js_package(tmp_path)
    native.write_text(FAKE_CODEX, encoding="utf-8")
    adapter.executable = launcher
    monkeypatch.setattr(adapter, "_validate_x64_linux_elf", lambda _content: None)
    runner.prepare()

    source = {
        "launcher": launcher, "package": package,
        "platform": target_package, "native": native,
    }[source_name]
    replacement = source.with_name(source.name + ".replacement")
    replacement.write_bytes(source.read_bytes() + b"\n")
    replacement.chmod(stat.S_IMODE(source.stat().st_mode))
    os.replace(replacement, source)

    with pytest.raises(RuntimeSessionError, match="source chain identity changed"):
        runner.draft()


def test_codex_adapter_rejects_private_executable_mutation(tmp_path, monkeypatch) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    private = Path(json.loads((_runtime(tmp_path) / "session.json").read_text())["runtime_executable"]["path"])
    private.chmod(0o700)
    private.write_text(FAKE_CODEX + "\n# runtime drift\n", encoding="utf-8")
    private.chmod(0o500)
    with pytest.raises(RuntimeSessionError, match="private Codex executable identity changed"):
        adapter.candidate(turn.session_id, read_only=True)


def test_codex_adapter_rejects_private_executable_mode_change(tmp_path, monkeypatch) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    private = Path(json.loads((_runtime(tmp_path) / "session.json").read_text())["runtime_executable"]["path"])
    private.chmod(0o700)
    with pytest.raises(RuntimeSessionError, match="mode must be 0500"):
        adapter.candidate(turn.session_id, read_only=True)


def test_codex_adapter_timeout_kills_complete_scope(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch, timeout=1)
    runner.prepare()
    _touch_control(tmp_path, "timeout")
    with pytest.raises(RuntimeBackendError, match="timed out"):
        runner.draft()
    pid_file = _runtime(tmp_path) / "child.pid"
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    time.sleep(2.2)
    assert not (tmp_path / "workspace/project/detached.txt").exists()
    diagnostic = json.loads((_runtime(tmp_path) / "001-draft.scope.json").read_text())
    assert diagnostic["scope_unit"].endswith(".scope")
    assert "confirmed=true" in diagnostic["cleanup_result"]
    controls = [
        json.loads(line)
        for line in (tmp_path / "systemd-bin/state/control.jsonl").read_text().splitlines()
    ]
    assert any(
        args[1:4] == ["kill", "--kill-whom=all", "--signal=SIGKILL"]
        and args[-1] == diagnostic["scope_unit"]
        for args in controls
    )


def test_success_with_lingering_descendant_fails_before_audit(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    runner.prepare()
    _touch_control(tmp_path, "detach-on-success")
    with pytest.raises(RuntimeBackendError, match="detached descendant"):
        runner.draft()
    time.sleep(2.2)
    assert not (tmp_path / "workspace/project/detached.txt").exists()
    seals = tmp_path / "workspace/.codexteam/v2/seals"
    assert not seals.exists() or not any(seals.iterdir())


def test_systemd_unavailable_fails_preflight_without_process_group_fallback(
    tmp_path, monkeypatch,
) -> None:
    adapter, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    adapter._systemd_run = tmp_path / "missing-systemd-run"
    with pytest.raises(RuntimePreflightError, match="systemd-run executable is unavailable"):
        runner.prepare()
    assert not (tmp_path / "systemd-bin/state/run.jsonl").exists()


@pytest.mark.skipif(
    not Path("/usr/bin/systemd-run").exists() or not Path("/usr/bin/systemctl").exists(),
    reason="integration: actual user-systemd tools are unavailable",
)
def test_actual_user_systemd_scope_probe_in_dry_run(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    adapter._systemd_run = Path("/usr/bin/systemd-run")
    adapter._systemctl = Path("/usr/bin/systemctl")
    adapter._test_systemd = False
    adapter._systemd_material = None
    adapter._systemd_probes = None
    probes = adapter._containment_probe()
    assert any("KillMode=control-group" in probe.evidence_summary for probe in probes)


def test_native_probe_covers_detached_descendant_containment(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    prepared = runner.prepare()
    process_probes = [
        probe for probe in prepared.preflight.probes
        if probe.operation.value == "execute" and probe.resource.value == "process"
    ]
    assert any("detached delayed command" in probe.evidence_summary for probe in process_probes)
    assert any("KillMode=control-group" in probe.evidence_summary for probe in process_probes)


def test_candidate_native_sandbox_is_read_only_and_runtime_updates(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    _touch_control(tmp_path, "candidate-mutation")
    session_path = _runtime(tmp_path) / "session.json"
    before = json.loads(session_path.read_text())["turn"]
    runner.candidate()
    assert not (tmp_path / "workspace/project/candidate-mutation.txt").exists()
    assert json.loads((_runtime(tmp_path) / "candidate-write-result").read_text()) is False
    assert json.loads(session_path.read_text())["turn"] == before + 1
    assert (_runtime(tmp_path) / "002-candidate.stderr.txt").exists()
    assert turn.session_id == "thread-discovery"


def test_feedback_resume_replays_workspace_write_sandbox(tmp_path, monkeypatch) -> None:
    _, runner, _, _, _ = _adapter(tmp_path, monkeypatch)
    turn = runner.draft()
    runner.adapter.feedback(turn.session_id, DefectPacket(summary="fix", criterion_ids=()))
    calls = [json.loads(line) for line in (_runtime(tmp_path) / "fake-calls.jsonl").read_text().splitlines()]
    feedback = calls[-1]["argv"]
    assert feedback[:2] == ["exec", "resume"]
    assert 'default_permissions="codexteam-direct"' in " ".join(feedback)
    assert 'sandbox_mode="workspace-write"' in " ".join(feedback)
    assert "--dangerously-bypass-approvals-and-sandbox" not in feedback


def test_dry_run_redacts_host_paths_and_secrets(tmp_path, monkeypatch) -> None:
    adapter, _, _, _, _ = _adapter(tmp_path, monkeypatch)
    plan = adapter.dry_run_plan(tmp_path / "not-created")
    rendered = json.dumps(plan)
    assert plan["model_calls"] is False
    assert "/usr/bin/bwrap" not in rendered
    assert "<private-runtime>/codex-home" in rendered
    assert "<private-executable-cache>/codex" in rendered
    assert plan["source_executable_digest"] == plan["runtime_executable_digest"]
    assert plan["systemd_version"] == "255"
    assert plan["systemd_run_digest"] and plan["systemctl_digest"]
    assert all(
        command.startswith("/usr/bin/systemd-run --user --scope")
        for command in plan["command_previews"]
    )
    assert "codexteam-v2-dry-run" not in rendered
    assert "/codexteam-test-bin" not in rendered
    assert "/home/linuxbrew" not in " ".join(plan["command_previews"])
    assert str(tmp_path / "source-home") not in rendered
    assert "DO-NOT-COPY" not in rendered
    assert "<explicit-safe-config>" in rendered
