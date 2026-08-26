from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json
from .paths import (
    contained_path,
    ensure_existing_workspace,
    normalize_task_id,
    validate_identifier,
)
from .repository_binding import RepositoryBinding, load_repository_binding

GATES = ("development", "integration")
CONFIG_PATH = "management/TEST_GATES.toml"
RECORD_ROOT = "results/gates"
SNAPSHOT_ROOT = f"{RECORD_ROOT}/accepted"
EXECUTION_SURFACES = ("worker", "lead_host")
GATE_RECORD_FIELDS = {
    "schema_version", "gate", "status", "project_root", "execution_surface",
    "started_at", "completed_at", "duration_seconds", "verification_paths",
    "configuration_digest", "workspace_digest", "commands",
    "control_root", "work_root", "git_root", "git_prefix", "repo_id",
}
GATE_COMMAND_FIELDS = {
    "gate", "argv", "exit_code", "duration_seconds", "stdout_tail", "stderr_tail",
}
_INHERITED_GATE_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATHEXT",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
        "PYTHONDONTWRITEBYTECODE",
    }
)
_SENSITIVE_GATE_ENVIRONMENT_MARKERS = (
    "ACCESS_KEY",
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)
_SENSITIVE_GATE_ENVIRONMENT_NAMES = frozenset(
    {
        "GIT_ASKPASS",
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_TERMINAL_PROMPT",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
    }
)


class GateConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GateConfig:
    verification_paths: tuple[str, ...]
    development_commands: tuple[tuple[str, ...], ...]
    integration_commands: tuple[tuple[str, ...], ...]
    development_timeout: int
    integration_timeout: int
    development_surface: str
    integration_surface: str


def _gate_roots(
    project: str | Path,
    work_root: str | Path | None,
    repo_id: str | None,
) -> tuple[Path, Path, RepositoryBinding | None]:
    control = ensure_existing_workspace(project)
    if work_root is None and repo_id is None:
        return control, control, None
    if work_root is None or repo_id is None:
        raise GateConfigError("split-root gates require both work_root and repo_id")
    binding = load_repository_binding(control, work_root, repo_id)
    return control, binding.work_root, binding


def _binding_fields(binding: RepositoryBinding) -> dict[str, str]:
    return {
        "control_root": str(binding.control_root),
        "work_root": str(binding.work_root),
        "git_root": str(binding.git_root),
        "git_prefix": binding.git_prefix,
        "repo_id": binding.repo_id,
    }


def load_gate_config(project: str | Path) -> GateConfig:
    root = ensure_existing_workspace(project)
    path = contained_path(root, CONFIG_PATH, label="test gate configuration")
    if path.is_symlink() or not path.is_file():
        raise GateConfigError(f"test gate configuration is missing or unsafe: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise GateConfigError(f"invalid test gate TOML: {exc}") from exc
    if data.get("schema_version") != "1.0":
        raise GateConfigError("test gate schema_version must be '1.0'")
    verification_paths = _patterns(data.get("verification_paths"))
    development = _gate_table(data.get("development"), "development")
    integration = _gate_table(data.get("integration"), "integration")
    includes = integration[2]
    if includes != ("development",):
        raise GateConfigError("integration.includes must be exactly ['development']")
    return GateConfig(
        verification_paths=verification_paths,
        development_commands=development[0],
        integration_commands=integration[0],
        development_timeout=development[1],
        integration_timeout=integration[1],
        development_surface=development[3],
        integration_surface=integration[3],
    )


def run_gate(
    project: str | Path,
    gate: str,
    *,
    dry_run: bool = False,
    execution_surface: str = "worker",
    command_prefix: tuple[str, ...] = (),
    environment: dict[str, str] | None = None,
    work_root: str | Path | None = None,
    repo_id: str | None = None,
) -> dict[str, Any]:
    if gate not in GATES:
        raise GateConfigError(f"unsupported gate: {gate}")
    control_root, work, binding = _gate_roots(project, work_root, repo_id)
    config = load_gate_config(control_root)
    initial_manifest = verification_manifest(work, config.verification_paths)
    if not initial_manifest:
        raise GateConfigError(
            f"verification_paths matched no files in work root: {work}"
        )
    expected_surface = _configured_surface(config, gate)
    if execution_surface not in EXECUTION_SURFACES:
        raise GateConfigError(
            f"execution surface must be one of: {', '.join(EXECUTION_SURFACES)}"
        )
    if execution_surface != expected_surface:
        raise GateConfigError(
            f"{gate} gate requires execution surface {expected_surface!r}; "
            f"received {execution_surface!r}"
        )
    stages = [("development", config.development_commands)]
    timeout = config.development_timeout
    if gate == "integration":
        stages.append(("integration", config.integration_commands))
        timeout = config.integration_timeout
    planned = [
        {"gate": stage, "argv": list(argv)}
        for stage, commands in stages
        for argv in commands
    ]
    if dry_run:
        return {
            "schema_version": "1.0",
            "gate": gate,
            "status": "dry_run",
            "project_root": str(work),
            "execution_surface": execution_surface,
            "verification_paths": list(config.verification_paths),
            "commands": planned,
            **(_binding_fields(binding) if binding else {}),
        }

    started_wall = _utc_now()
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    status = "passed"
    for stage, commands in stages:
        for argv in commands:
            elapsed = time.monotonic() - started
            remaining = max(1, int(timeout - elapsed))
            command_started = time.monotonic()
            exit_code, stdout, stderr = _run_gate_command(
                [*command_prefix, *argv],
                cwd=work,
                timeout_seconds=remaining,
                environment=environment,
            )
            records.append(
                {
                    "gate": stage,
                    "argv": list(argv),
                    "exit_code": exit_code,
                    "duration_seconds": round(time.monotonic() - command_started, 3),
                    "stdout_tail": stdout[-4_000:],
                    "stderr_tail": stderr[-4_000:],
                }
            )
            if exit_code != 0:
                status = "failed"
                break
        if status == "failed":
            break
    manifest = verification_manifest(work, config.verification_paths)
    if not manifest:
        raise GateConfigError(
            f"verification_paths matched no files after gate execution: {work}"
        )
    record = {
        "schema_version": "1.0",
        "gate": gate,
        "status": status,
        "project_root": str(work),
        "execution_surface": execution_surface,
        "started_at": started_wall,
        "completed_at": _utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "verification_paths": list(config.verification_paths),
        "configuration_digest": _config_digest(config),
        "workspace_digest": _manifest_digest(manifest),
        "commands": records,
        **(_binding_fields(binding) if binding else {}),
    }
    validate_gate_record(record)
    record_path = gate_record_path(control_root, gate)
    atomic_write_json(record_path, record)
    return record


def _run_gate_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None,
) -> tuple[int, str, str]:
    env = _sanitized_gate_environment(environment)
    run_id = uuid.uuid4().hex
    env["CODEXTEAM_GATE_RUN_ID"] = run_id
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_tail = bytearray()
    stderr_tail = bytearray()
    readers = (
        threading.Thread(
            target=_read_bounded_tail,
            args=(process.stdout, stdout_tail),
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded_tail,
            args=(process.stderr, stderr_tail),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    descendants: set[int] = set()
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        while process.poll() is None:
            descendants.update(_process_descendants(process.pid))
            descendants.update(_gate_run_processes(run_id))
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_gate_processes(process, descendants, include_group=True)
                break
            time.sleep(0.02)
        process.wait()
        descendants.update(_gate_run_processes(run_id))
        descendants.discard(process.pid)
        if not timed_out:
            _terminate_gate_processes(process, descendants, include_group=True)
    except BaseException:
        descendants.update(_process_descendants(process.pid))
        descendants.update(_gate_run_processes(run_id))
        descendants.discard(process.pid)
        _terminate_gate_processes(process, descendants, include_group=True)
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
        for reader in readers:
            reader.join(timeout=0.5)
    stdout = stdout_tail.decode("utf-8", errors="replace")
    stderr = stderr_tail.decode("utf-8", errors="replace")
    if timed_out:
        return 124, stdout, stderr or f"gate command timed out after {timeout_seconds} seconds"
    return process.returncode, stdout, stderr


def _sanitized_gate_environment(
    overrides: dict[str, str] | None,
) -> dict[str, str]:
    inherited = os.environ if overrides is None else {}
    env = {
        name: value
        for name, value in inherited.items()
        if name.upper() in _INHERITED_GATE_ENVIRONMENT
        and not _sensitive_gate_environment_name(name)
    }
    if overrides is not None:
        env.update(
            {
                name: value
                for name, value in overrides.items()
                if not _sensitive_gate_environment_name(name)
            }
        )
    env.pop("CODEXTEAM_LAUNCHED_WORKER", None)
    return env


def _sensitive_gate_environment_name(name: str) -> bool:
    upper = name.upper()
    return (
        upper in _SENSITIVE_GATE_ENVIRONMENT_NAMES
        or upper == "NO_PROXY"
        or "PROXY" in upper
        or upper.startswith("GIT_CONFIG")
        or upper.startswith("GIT_SSH")
        or any(marker in upper for marker in _SENSITIVE_GATE_ENVIRONMENT_MARKERS)
    )


def _terminate_gate_processes(
    process: subprocess.Popen[bytes],
    descendants: set[int],
    *,
    include_group: bool,
) -> None:
    if include_group:
        _signal_process_group(process.pid, signal.SIGTERM)
    _signal_processes(descendants, signal.SIGTERM)
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline and any(_process_exists(pid) for pid in descendants):
        _reap_processes(descendants)
        time.sleep(0.01)
    if include_group:
        _signal_process_group(process.pid, signal.SIGKILL)
    _signal_processes(descendants, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
        process.wait()
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline and any(_process_exists(pid) for pid in descendants):
        _reap_processes(descendants)
        time.sleep(0.01)


def _process_descendants(process_id: int) -> set[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return set()
    children: dict[int, set[int]] = {}
    for status_path in proc.glob("[0-9]*/status"):
        try:
            status = status_path.read_text(encoding="utf-8")
            child_id = int(status_path.parent.name)
            match = re.search(r"^PPid:\s+(\d+)$", status, re.MULTILINE)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if match is not None:
            children.setdefault(int(match.group(1)), set()).add(child_id)
    descendants: set[int] = set()
    pending = [process_id]
    while pending:
        for child_id in children.get(pending.pop(), set()):
            if child_id not in descendants:
                descendants.add(child_id)
                pending.append(child_id)
    return descendants


def _signal_process_group(process_id: int, target_signal: int) -> None:
    try:
        os.killpg(process_id, target_signal)
    except ProcessLookupError:
        pass


def _signal_processes(process_ids: set[int], target_signal: int) -> None:
    for process_id in process_ids:
        try:
            os.kill(process_id, target_signal)
        except ProcessLookupError:
            pass


def _process_exists(process_id: int) -> bool:
    return Path(f"/proc/{process_id}").exists()


def _reap_processes(process_ids: set[int]) -> None:
    for process_id in process_ids:
        try:
            os.waitpid(process_id, os.WNOHANG)
        except (ChildProcessError, ProcessLookupError):
            pass


def _gate_run_processes(run_id: str) -> set[int]:
    marker = f"CODEXTEAM_GATE_RUN_ID={run_id}".encode()
    process_ids: set[int] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return process_ids
    for environ_path in proc.glob("[0-9]*/environ"):
        try:
            environment = environ_path.read_bytes().split(b"\0")
            process_id = int(environ_path.parent.name)
        except (OSError, ValueError):
            continue
        if marker in environment:
            process_ids.add(process_id)
    return process_ids


def _read_bounded_tail(stream: Any, output: bytearray, limit: int = 4_000) -> None:
    try:
        while chunk := stream.read(8_192):
            output.extend(chunk)
            if len(output) > limit:
                del output[:-limit]
    except (OSError, ValueError):
        pass


def gate_record_path(project: str | Path, gate: str) -> Path:
    if gate not in GATES:
        raise GateConfigError(f"unsupported gate: {gate}")
    root = ensure_existing_workspace(project)
    return contained_path(root, f"{RECORD_ROOT}/{gate}.json", label="gate record")


def validate_current_gate_record(
    project: str | Path,
    gate: str,
    *,
    work_root: str | Path | None = None,
    repo_id: str | None = None,
) -> dict[str, Any]:
    control_root = ensure_existing_workspace(project)
    config = load_gate_config(control_root)
    path = gate_record_path(control_root, gate)
    if path.is_symlink() or not path.is_file():
        raise GateConfigError(f"gate record is missing or unsafe: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateConfigError(f"invalid gate record JSON: {exc}") from exc
    record = validate_gate_record(record)
    if work_root is None and repo_id is None and "work_root" in record:
        work_root = record["work_root"]
        repo_id = record["repo_id"]
    control_root, work, binding = _gate_roots(control_root, work_root, repo_id)
    if record.get("gate") != gate or record.get("status") != "passed":
        raise GateConfigError(f"{gate} gate record is not a passing record")
    if record.get("project_root") != str(work):
        raise GateConfigError("gate record project root does not match")
    expected_binding = _binding_fields(binding) if binding is not None else {}
    observed_binding = {
        field: record[field]
        for field in ("control_root", "work_root", "git_root", "git_prefix", "repo_id")
        if field in record
    }
    if observed_binding != expected_binding:
        raise GateConfigError("gate record repository binding does not match")
    expected_surface = _configured_surface(config, gate)
    if record.get("execution_surface", "worker") != expected_surface:
        raise GateConfigError(f"{gate} gate record has the wrong execution surface")
    patterns = record.get("verification_paths")
    if not isinstance(patterns, list):
        raise GateConfigError("gate record verification_paths must be a list")
    if patterns != list(config.verification_paths) or record.get("configuration_digest") != _config_digest(config):
        raise GateConfigError(f"{gate} gate record is stale for the current gate configuration")
    expected_commands = [
        {"gate": stage, "argv": list(argv)}
        for stage, commands in _gate_stages(config, gate)
        for argv in commands
    ]
    observed_commands = [
        {"gate": item["gate"], "argv": item["argv"]}
        for item in record["commands"]
    ]
    if observed_commands != expected_commands:
        raise GateConfigError(f"{gate} gate record command observations do not match configuration")
    manifest = verification_manifest(work, tuple(patterns))
    if not manifest:
        raise GateConfigError("gate verification_paths currently match no files")
    current = _manifest_digest(manifest)
    if current != record.get("workspace_digest"):
        raise GateConfigError(f"{gate} gate record is stale for the current workspace")
    return record


def validate_gate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise GateConfigError("gate record must be a JSON object")
    required = GATE_RECORD_FIELDS - {
        "execution_surface", "control_root", "work_root", "git_root", "git_prefix", "repo_id"
    }
    missing = sorted(required - set(record))
    unknown = sorted(set(record) - GATE_RECORD_FIELDS)
    errors: list[str] = []
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if record.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if record.get("gate") not in GATES:
        errors.append("gate must be development or integration")
    if record.get("status") not in {"passed", "failed"}:
        errors.append("status must be passed or failed")
    if not isinstance(record.get("project_root"), str) or not Path(record.get("project_root", "")).is_absolute():
        errors.append("project_root must be an absolute path")
    split_fields = ("control_root", "work_root", "git_root", "git_prefix", "repo_id")
    present_split = [field for field in split_fields if field in record]
    if present_split and len(present_split) != len(split_fields):
        errors.append("split-root binding fields must be supplied together")
    if present_split:
        for field in ("control_root", "work_root", "git_root"):
            if not isinstance(record.get(field), str) or not Path(record[field]).is_absolute():
                errors.append(f"{field} must be an absolute path")
        for field in ("git_prefix", "repo_id"):
            if not isinstance(record.get(field), str) or not record[field]:
                errors.append(f"{field} must be a non-empty string")
        if record.get("project_root") != record.get("work_root"):
            errors.append("project_root must equal work_root")
    if record.get("execution_surface", "worker") not in EXECUTION_SURFACES:
        errors.append("execution_surface must be worker or lead_host")
    for field in ("started_at", "completed_at"):
        if not _valid_timestamp(record.get(field)):
            errors.append(f"{field} must be an ISO-8601 timestamp")
    duration = record.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
        errors.append("duration_seconds must be a non-negative number")
    paths = record.get("verification_paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(item, str) or not item for item in paths):
        errors.append("verification_paths must be a non-empty string list")
    elif len(paths) != len(set(paths)):
        errors.append("verification_paths cannot contain duplicates")
    for field in ("configuration_digest", "workspace_digest"):
        value = record.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            errors.append(f"{field} must be a lowercase SHA-256 digest")
    commands = record.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("commands must be a non-empty list")
    else:
        for index, command in enumerate(commands):
            prefix = f"commands[{index}]"
            if not isinstance(command, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if set(command) != GATE_COMMAND_FIELDS:
                errors.append(f"{prefix} must contain only the gate-record command fields")
            if command.get("gate") not in GATES:
                errors.append(f"{prefix}.gate must be development or integration")
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
                errors.append(f"{prefix}.argv must be a non-empty string list")
            exit_code = command.get("exit_code")
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                errors.append(f"{prefix}.exit_code must be an integer")
            item_duration = command.get("duration_seconds")
            if not isinstance(item_duration, (int, float)) or isinstance(item_duration, bool) or item_duration < 0:
                errors.append(f"{prefix}.duration_seconds must be a non-negative number")
            for field in ("stdout_tail", "stderr_tail"):
                if not isinstance(command.get(field), str):
                    errors.append(f"{prefix}.{field} must be a string")
        if record.get("status") == "passed" and any(
            isinstance(command.get("exit_code"), int)
            and not isinstance(command.get("exit_code"), bool)
            and command.get("exit_code") != 0
            for command in commands
            if isinstance(command, dict)
        ):
            errors.append("passed gate records require every command to exit zero")
        if record.get("status") == "failed" and not any(
            isinstance(command.get("exit_code"), int)
            and not isinstance(command.get("exit_code"), bool)
            and command.get("exit_code") != 0
            for command in commands
            if isinstance(command, dict)
        ):
            errors.append("failed gate records require a failing command observation")
    if errors:
        raise GateConfigError("invalid gate record: " + "; ".join(errors))
    return record


def snapshot_current_gate_record(
    project: str | Path,
    gate: str,
    *,
    task_id: str,
    attempt_id: str,
    work_root: str | Path | None = None,
    repo_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Persist one content-addressed snapshot of a current passing gate."""
    root = ensure_existing_workspace(project)
    normalized_task = normalize_task_id(task_id)
    normalized_attempt = validate_identifier(attempt_id, label="attempt ID")
    record = validate_current_gate_record(
        root, gate, work_root=work_root, repo_id=repo_id
    )
    record_bytes = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    record_sha256 = hashlib.sha256(record_bytes).hexdigest()
    relative = (
        f"{SNAPSHOT_ROOT}/{normalized_task}-{normalized_attempt}-{gate}-"
        f"{record_sha256[:16]}.json"
    )
    path = contained_path(root, relative, label="accepted gate snapshot")
    payload = {
        "schema_version": "1.0",
        "kind": "accepted_gate_snapshot",
        "task_id": normalized_task,
        "attempt_id": normalized_attempt,
        "gate": gate,
        "record_sha256": record_sha256,
        "record": record,
    }
    if path.is_symlink():
        raise GateConfigError(f"accepted gate snapshot cannot be a symlink: {path}")
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GateConfigError(f"invalid accepted gate snapshot: {path}: {exc}") from exc
        if current != payload:
            raise GateConfigError(f"accepted gate snapshot collision: {path}")
        return path, payload
    atomic_write_json(path, payload)
    return path, payload


def verification_manifest(project: Path, patterns: tuple[str, ...]) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for current_root, directory_names, file_names in os.walk(project, topdown=True):
        root = Path(current_root)
        relative_root = root.relative_to(project).as_posix()
        directory_names[:] = [
            name
            for name in directory_names
            if not _excluded(name if relative_root == "." else f"{relative_root}/{name}")
        ]
        for name in file_names:
            path = root / name
            relative = path.relative_to(project).as_posix()
            if _excluded(relative) or not any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns):
                continue
            if path.is_symlink():
                manifest[relative] = "symlink:" + os.readlink(path)
            else:
                manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(manifest.items()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a configured CodexTeam test gate without a shell.")
    parser.add_argument("project", nargs="?")
    parser.add_argument("--control-root")
    parser.add_argument("--work-root")
    parser.add_argument("--repo-id")
    parser.add_argument("--gate", required=True, choices=GATES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-record", action="store_true")
    parser.add_argument(
        "--execution-surface",
        choices=EXECUTION_SURFACES,
        default="worker",
    )
    parser.add_argument("--snapshot-task")
    parser.add_argument("--snapshot-attempt")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if bool(args.snapshot_task) != bool(args.snapshot_attempt):
            raise GateConfigError(
                "--snapshot-task and --snapshot-attempt must be supplied together"
            )
        split_values = (args.control_root, args.work_root, args.repo_id)
        if bool(args.project) == bool(any(split_values)) or (any(split_values) and not all(split_values)):
            raise GateConfigError(
                "supply either project or all of --control-root, --work-root, and --repo-id"
            )
        project = args.project or args.control_root
        if args.check_record:
            result = validate_current_gate_record(
                project, args.gate, work_root=args.work_root, repo_id=args.repo_id
            )
        else:
            result = run_gate(
                project,
                args.gate,
                dry_run=args.dry_run,
                execution_surface=args.execution_surface,
                work_root=args.work_root,
                repo_id=args.repo_id,
            )
        if args.snapshot_task:
            if args.dry_run:
                raise GateConfigError("cannot snapshot a dry-run gate")
            path, snapshot = snapshot_current_gate_record(
                project,
                args.gate,
                task_id=args.snapshot_task,
                attempt_id=args.snapshot_attempt,
                work_root=args.work_root,
                repo_id=args.repo_id,
            )
            result = dict(result)
            result["accepted_snapshot"] = {
                "artifact_ref": path.relative_to(Path(project).resolve()).as_posix(),
                "record_sha256": snapshot["record_sha256"],
            }
    except (FileNotFoundError, GateConfigError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Gate: {result['gate']}")
        print(f"Status: {result['status']}")
        if "workspace_digest" in result:
            print(f"Workspace digest: {result['workspace_digest']}")
        snapshot = result.get("accepted_snapshot")
        if isinstance(snapshot, dict):
            print(f"Accepted snapshot: {snapshot['artifact_ref']}")
    return 0 if result.get("status") in {"passed", "dry_run"} else 1


def _gate_table(
    value: Any,
    name: str,
) -> tuple[tuple[tuple[str, ...], ...], int, tuple[str, ...], str]:
    if not isinstance(value, dict):
        raise GateConfigError(f"{name} must be a TOML table")
    if value.get("configured") is not True:
        raise GateConfigError(f"{name} gate is not configured")
    commands_value = value.get("commands")
    if not isinstance(commands_value, list) or not commands_value:
        raise GateConfigError(f"{name}.commands must be a non-empty array of argument arrays")
    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(commands_value):
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item or "\x00" in item for item in command)
        ):
            raise GateConfigError(f"{name}.commands[{index}] must contain non-empty strings")
        commands.append(tuple(command))
    timeout = value.get("expected_max_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise GateConfigError(f"{name}.expected_max_seconds must be a positive integer")
    includes_value = value.get("includes", [])
    if not isinstance(includes_value, list) or any(not isinstance(item, str) for item in includes_value):
        raise GateConfigError(f"{name}.includes must be a string array")
    execution_surface = value.get("execution_surface", "worker")
    if execution_surface not in EXECUTION_SURFACES:
        raise GateConfigError(
            f"{name}.execution_surface must be one of: {', '.join(EXECUTION_SURFACES)}"
        )
    return tuple(commands), timeout, tuple(includes_value), execution_surface


def _gate_stages(
    config: GateConfig,
    gate: str,
) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    stages = [("development", config.development_commands)]
    if gate == "integration":
        stages.append(("integration", config.integration_commands))
    return tuple(stages)


def _patterns(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise GateConfigError("verification_paths must be a non-empty string array")
    patterns = tuple(value)
    if len(patterns) != len(set(patterns)):
        raise GateConfigError("verification_paths cannot contain duplicates")
    for pattern in patterns:
        if pattern.startswith("/") or "\\" in pattern or ".." in pattern.split("/"):
            raise GateConfigError(f"unsafe verification path pattern: {pattern!r}")
    return patterns


def _manifest_digest(manifest: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _config_digest(config: GateConfig) -> str:
    value = {
        "verification_paths": config.verification_paths,
        "development_commands": config.development_commands,
        "integration_commands": config.integration_commands,
        "development_timeout": config.development_timeout,
        "integration_timeout": config.integration_timeout,
        "development_surface": config.development_surface,
        "integration_surface": config.integration_surface,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def gate_config_digest(config: GateConfig) -> str:
    return _config_digest(config)


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _excluded(relative: str) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in (".git", ".codexteam/runtime", "results/gates")
    )


def _configured_surface(config: GateConfig, gate: str) -> str:
    return (
        config.development_surface
        if gate == "development"
        else config.integration_surface
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
