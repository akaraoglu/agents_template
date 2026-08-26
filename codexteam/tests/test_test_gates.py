from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from codexteam_tools.test_gates import (
    GateConfigError,
    main,
    run_gate,
    snapshot_current_gate_record,
    validate_current_gate_record,
    validate_gate_record,
)


def configure(project: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
    ]
    content = (
        'schema_version = "1.0"\n'
        'verification_paths = ["src/**", "tests/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 30\n'
        f"commands = [{json.dumps(command)}]\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 60\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps(command)}]\n"
    )
    (project / "management").mkdir(exist_ok=True)
    (project / "management" / "TEST_GATES.toml").write_text(content)


def test_integration_gate_runs_development_first_and_detects_staleness(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)

    record = run_gate(project, "integration")

    assert record["status"] == "passed"
    assert [entry["gate"] for entry in record["commands"]] == [
        "development",
        "integration",
    ]
    assert validate_current_gate_record(project, "integration") == record
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    with pytest.raises(GateConfigError, match="stale"):
        validate_current_gate_record(project, "integration")


def test_gate_record_is_stale_when_commands_change(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    run_gate(project, "integration")

    config = project / "management" / "TEST_GATES.toml"
    config.write_text(config.read_text().replace("expected_max_seconds = 60", "expected_max_seconds = 61"))

    with pytest.raises(GateConfigError, match="configuration"):
        validate_current_gate_record(project, "integration")


def test_gate_record_contract_rejects_unknown_fields_and_accepts_legacy_surface(
    tmp_path: Path,
):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    record = run_gate(project, "development")

    legacy = dict(record)
    legacy.pop("execution_surface")
    assert validate_gate_record(legacy) is legacy

    tampered = dict(record)
    tampered["unexpected"] = True
    with pytest.raises(GateConfigError, match="unknown fields"):
        validate_gate_record(tampered)

    changed_commands = dict(record)
    changed_commands["commands"] = [dict(item) for item in record["commands"]]
    changed_commands["commands"][0]["argv"] = [sys.executable, "-c", "print('different')"]
    (project / "results" / "gates" / "development.json").write_text(
        json.dumps(changed_commands)
    )
    with pytest.raises(GateConfigError, match="command observations"):
        validate_current_gate_record(project, "development")

    contradictory = dict(record)
    contradictory["commands"] = [dict(item) for item in record["commands"]]
    contradictory["commands"][0]["exit_code"] = 1
    with pytest.raises(GateConfigError, match="require every command to exit zero"):
        validate_gate_record(contradictory)

    malformed_exit = dict(record)
    malformed_exit["commands"] = [dict(item) for item in record["commands"]]
    malformed_exit["status"] = "failed"
    malformed_exit["commands"][0]["exit_code"] = []
    with pytest.raises(GateConfigError, match="exit_code must be an integer"):
        validate_gate_record(malformed_exit)


def test_gate_failure_stops_later_commands_in_configured_order(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    marker = project / "order.txt"
    commands = [
        [sys.executable, "-c", "from pathlib import Path; Path('order.txt').write_text('development-1\\n')"],
        [sys.executable, "-c", "from pathlib import Path; Path('order.txt').write_text(Path('order.txt').read_text() + 'development-2\\n'); raise SystemExit(9)"],
    ]
    integration = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('order.txt').write_text(Path('order.txt').read_text() + 'integration\\n')",
    ]
    (project / "management").mkdir()
    (project / "management" / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 30\n'
        f"commands = {json.dumps(commands)}\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 60\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps(integration)}]\n"
    )

    record = run_gate(project, "integration")

    assert record["status"] == "failed"
    assert [item["exit_code"] for item in record["commands"]] == [0, 9]
    assert marker.read_text() == "development-1\ndevelopment-2\n"


def test_changes_outside_verification_paths_do_not_stale_gate(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    record = run_gate(project, "development")

    (project / "notes.txt").write_text("outside configured verification scope\n")

    assert validate_current_gate_record(project, "development") == record


def test_gate_dry_run_is_non_mutating_and_rejects_unconfigured(tmp_path: Path):
    project = tmp_path / "project"
    (project / "management").mkdir(parents=True)
    (project / "management" / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n'
        '[development]\nconfigured = false\nexpected_max_seconds = 1\ncommands = []\n'
        '[integration]\nconfigured = false\nexpected_max_seconds = 1\nincludes = ["development"]\ncommands = []\n'
    )
    with pytest.raises(GateConfigError, match="not configured"):
        run_gate(project, "development", dry_run=True)
    assert not (project / "results").exists()


def test_gate_rejects_empty_verification_manifest(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    configure(project)

    with pytest.raises(GateConfigError, match="matched no files"):
        run_gate(project, "development")


def test_gate_rejects_manifest_emptied_by_successful_command(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management/TEST_GATES.toml"
    delete_command = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('src/main.py').unlink()",
    ]
    config.write_text(config.read_text().replace(
        json.dumps([
            sys.executable, "-c",
            "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
        ]),
        json.dumps(delete_command),
    ))

    with pytest.raises(GateConfigError, match="after gate execution"):
        run_gate(project, "development")


def test_gate_output_capture_retains_only_bounded_tail(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management/TEST_GATES.toml"
    noisy_command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 100000 + 'END'); sys.stderr.write('y' * 100000 + 'ERR')",
    ]
    config.write_text(config.read_text().replace(
        json.dumps([
            sys.executable, "-c",
            "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
        ]),
        json.dumps(noisy_command),
    ))

    record = run_gate(project, "development")

    command = record["commands"][0]
    assert len(command["stdout_tail"].encode()) <= 4_000
    assert len(command["stderr_tail"].encode()) <= 4_000
    assert command["stdout_tail"].endswith("END")
    assert command["stderr_tail"].endswith("ERR")


def test_host_only_gate_rejects_worker_and_writes_immutable_snapshot(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management" / "TEST_GATES.toml"
    config.write_text(
        config.read_text().replace(
            "[integration]\nconfigured = true",
            '[integration]\nconfigured = true\nexecution_surface = "lead_host"',
        )
    )

    with pytest.raises(GateConfigError, match="requires execution surface 'lead_host'"):
        run_gate(project, "integration")

    record = run_gate(project, "integration", execution_surface="lead_host")
    assert record["execution_surface"] == "lead_host"
    path, snapshot = snapshot_current_gate_record(
        project,
        "integration",
        task_id="T003",
        attempt_id="att-001",
    )
    assert path.parent == project / "results/gates/accepted"
    assert snapshot["record"] == record
    assert len(snapshot["record_sha256"]) == 64
    assert snapshot_current_gate_record(
        project,
        "integration",
        task_id="T003",
        attempt_id="att-001",
    )[0] == path

    before = path.read_bytes()
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    assert path.read_bytes() == before
    with pytest.raises(GateConfigError, match="stale"):
        snapshot_current_gate_record(
            project,
            "integration",
            task_id="T004",
            attempt_id="att-001",
        )


def test_gate_cli_prints_accepted_snapshot_path(tmp_path: Path, capsys):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    configure(project)

    code = main(
        [
            str(project),
            "--gate",
            "integration",
            "--snapshot-task",
            "T003",
            "--snapshot-attempt",
            "att-001",
        ]
    )

    assert code == 0
    assert "Accepted snapshot: results/gates/accepted/T003-att-001-integration-" in capsys.readouterr().out


def test_split_gate_loads_control_config_runs_and_manifests_work(tmp_path: Path):
    control = tmp_path / "control"
    git_root = tmp_path / "repo"
    work = git_root / "component"
    decoy = git_root / "decoy"
    control.mkdir()
    (work / "src").mkdir(parents=True)
    decoy.mkdir()
    (work / "src/main.py").write_text("VALUE = 1\n")
    (decoy / "unchanged.txt").write_text("decoy\n")
    subprocess.run(["git", "init", "-q"], cwd=git_root, check=True)
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": "component", "work_root": str(work), "git_root": str(git_root),
            "git_prefix": "component", "remote_url": None, "write_policy": "task-owned",
        }],
    }))
    configure(control)

    record = run_gate(control, "development", work_root=work, repo_id="component")

    assert record["status"] == "passed"
    assert record["control_root"] == str(control)
    assert record["work_root"] == record["project_root"] == str(work)
    assert record["git_root"] == str(git_root)
    assert record["git_prefix"] == "component"
    assert (control / "results/gates/development.json").is_file()
    assert not (work / "results/gates/development.json").exists()
    assert (decoy / "unchanged.txt").read_text() == "decoy\n"
    assert validate_current_gate_record(
        control, "development", work_root=work, repo_id="component"
    ) == record
    assert validate_current_gate_record(control, "development") == record
    snapshot_path, snapshot = snapshot_current_gate_record(
        control, "development", task_id="T003", attempt_id="att-001",
        work_root=work, repo_id="component",
    )
    assert snapshot_path.is_relative_to(control)
    assert snapshot["record"]["repo_id"] == "component"


def test_gate_removes_internal_worker_marker(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management/TEST_GATES.toml"
    command = [
        sys.executable, "-c",
        "import os; raise SystemExit('CODEXTEAM_LAUNCHED_WORKER' in os.environ)",
    ]
    config.write_text(config.read_text().replace(
        json.dumps([
            sys.executable, "-c",
            "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
        ]),
        json.dumps(command),
    ))
    monkeypatch.setenv("CODEXTEAM_LAUNCHED_WORKER", "1")

    assert run_gate(project, "development")["status"] == "passed"


def test_gate_sanitizes_inherited_and_explicit_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    configure(project)
    config = project / "management/TEST_GATES.toml"
    command = [
        sys.executable,
        "-c",
        "import json,os; print(json.dumps({k: os.environ.get(k) for k in "
        "('PATH','SECRET_TOKEN','HTTPS_PROXY','GIT_ASKPASS','PASSWORD','NO_PROXY','SAFE_GATE_VALUE')}))",
    ]
    config.write_text(config.read_text().replace(
        json.dumps([
            sys.executable, "-c",
            "from pathlib import Path; assert Path('src/main.py').read_text().strip() == 'VALUE = 1'",
        ]),
        json.dumps(command),
    ))
    monkeypatch.setenv("SECRET_TOKEN", "inherited-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("GIT_ASKPASS", "/tmp/credential-helper")

    inherited_record = run_gate(project, "development")
    inherited = json.loads(inherited_record["commands"][0]["stdout_tail"])
    assert inherited["PATH"]
    assert inherited["SECRET_TOKEN"] is None
    assert inherited["HTTPS_PROXY"] is None
    assert inherited["GIT_ASKPASS"] is None

    record = run_gate(
        project,
        "development",
        environment={
            **os.environ,
            "SAFE_GATE_VALUE": "explicit-safe-value",
            "PASSWORD": "explicit-secret",
        },
    )

    assert record["status"] == "passed"
    observed = json.loads(record["commands"][0]["stdout_tail"])
    assert observed["PATH"]
    assert observed["SAFE_GATE_VALUE"] == "explicit-safe-value"
    assert observed["SECRET_TOKEN"] is None
    assert observed["HTTPS_PROXY"] is None
    assert observed["GIT_ASKPASS"] is None
    assert observed["PASSWORD"] is None
    assert observed["NO_PROXY"] is None


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups and sockets")
def test_gate_timeout_releases_detached_listener(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    pid_path = project / "listener.txt"
    command = [
        sys.executable,
        "-c",
        "import os,socket,time; pid=os.fork(); "
        "os.setsid() if pid == 0 else None; "
        "s=socket.socket() if pid == 0 else None; "
        "s.bind(('127.0.0.1', 0)) if pid == 0 else None; "
        "s.listen() if pid == 0 else None; "
        f"open({str(pid_path)!r}, 'w').write(str(os.getpid()) + ' ' + str(s.getsockname()[1])) if pid == 0 else None; "
        "time.sleep(30)",
    ]
    (project / "management").mkdir()
    (project / "management/TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 1\n'
        f"commands = [{json.dumps(command)}]\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 5\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps([sys.executable, '-c', 'pass'])}]\n"
    )

    record = run_gate(project, "development")

    assert record["status"] == "failed"
    assert record["commands"][0]["exit_code"] == 124
    listener_pid, listener_port = (int(value) for value in pid_path.read_text().split())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not Path(f"/proc/{listener_pid}").exists():
            break
        time.sleep(0.01)
    else:
        pytest.fail(f"detached gate listener process {listener_pid} survived timeout")

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", listener_port))
                break
            except OSError:
                time.sleep(0.01)
    else:
        pytest.fail(f"detached gate listener {listener_pid} retained port {listener_port}")


def test_gate_kills_detached_descendant_after_parent_exit(tmp_path: Path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/main.py").write_text("VALUE = 1\n")
    pid_path = project / "child.pid"
    command = [
        sys.executable, "-c",
        "import os,sys,time; pid=os.fork(); "
        f"open({str(pid_path)!r},'w').write(str(pid)) if pid else None; "
        "os.setsid() if pid == 0 else None; "
        "os.execl(sys.executable,sys.executable,'-c','import time; time.sleep(30)') if pid == 0 else None",
    ]
    (project / "management").mkdir()
    (project / "management/TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 5\n'
        f"commands = [{json.dumps(command)}]\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 10\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps([sys.executable, '-c', 'pass'])}]\n"
    )

    record = run_gate(project, "development")

    assert record["status"] == "passed"
    child_pid = int(pid_path.read_text())
    deadline = time.monotonic() + 2
    while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if Path(f"/proc/{child_pid}").exists():
        status = Path(f"/proc/{child_pid}/status").read_text()
        assert "State:\tZ" in status
