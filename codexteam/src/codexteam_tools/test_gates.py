from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import time
import tomllib
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

GATES = ("development", "integration")
CONFIG_PATH = "management/TEST_GATES.toml"
RECORD_ROOT = "results/gates"
SNAPSHOT_ROOT = f"{RECORD_ROOT}/accepted"
EXECUTION_SURFACES = ("worker", "lead_host")
GATE_RECORD_FIELDS = {
    "schema_version", "gate", "status", "project_root", "execution_surface",
    "started_at", "completed_at", "duration_seconds", "verification_paths",
    "configuration_digest", "workspace_digest", "commands",
}
GATE_COMMAND_FIELDS = {
    "gate", "argv", "exit_code", "duration_seconds", "stdout_tail", "stderr_tail",
}


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
) -> dict[str, Any]:
    if gate not in GATES:
        raise GateConfigError(f"unsupported gate: {gate}")
    root = ensure_existing_workspace(project)
    config = load_gate_config(root)
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
            "project_root": str(root),
            "execution_surface": execution_surface,
            "verification_paths": list(config.verification_paths),
            "commands": planned,
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
            try:
                completed = subprocess.run(
                    [*command_prefix, *argv],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=remaining,
                    check=False,
                    env=environment,
                )
                exit_code = completed.returncode
                stdout = completed.stdout
                stderr = completed.stderr
            except subprocess.TimeoutExpired as exc:
                exit_code = 124
                stdout = _timeout_text(exc.stdout)
                stderr = _timeout_text(exc.stderr) or f"gate command timed out after {remaining} seconds"
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
    manifest = verification_manifest(root, config.verification_paths)
    record = {
        "schema_version": "1.0",
        "gate": gate,
        "status": status,
        "project_root": str(root),
        "execution_surface": execution_surface,
        "started_at": started_wall,
        "completed_at": _utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "verification_paths": list(config.verification_paths),
        "configuration_digest": _config_digest(config),
        "workspace_digest": _manifest_digest(manifest),
        "commands": records,
    }
    validate_gate_record(record)
    record_path = gate_record_path(root, gate)
    atomic_write_json(record_path, record)
    return record


def gate_record_path(project: str | Path, gate: str) -> Path:
    if gate not in GATES:
        raise GateConfigError(f"unsupported gate: {gate}")
    root = ensure_existing_workspace(project)
    return contained_path(root, f"{RECORD_ROOT}/{gate}.json", label="gate record")


def validate_current_gate_record(project: str | Path, gate: str) -> dict[str, Any]:
    root = ensure_existing_workspace(project)
    config = load_gate_config(root)
    path = gate_record_path(root, gate)
    if path.is_symlink() or not path.is_file():
        raise GateConfigError(f"gate record is missing or unsafe: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateConfigError(f"invalid gate record JSON: {exc}") from exc
    record = validate_gate_record(record)
    if record.get("gate") != gate or record.get("status") != "passed":
        raise GateConfigError(f"{gate} gate record is not a passing record")
    if record.get("project_root") != str(root):
        raise GateConfigError("gate record project root does not match")
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
    current = _manifest_digest(verification_manifest(root, tuple(patterns)))
    if current != record.get("workspace_digest"):
        raise GateConfigError(f"{gate} gate record is stale for the current workspace")
    return record


def validate_gate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise GateConfigError("gate record must be a JSON object")
    required = GATE_RECORD_FIELDS - {"execution_surface"}
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
) -> tuple[Path, dict[str, Any]]:
    """Persist one content-addressed snapshot of a current passing gate."""
    root = ensure_existing_workspace(project)
    normalized_task = normalize_task_id(task_id)
    normalized_attempt = validate_identifier(attempt_id, label="attempt ID")
    record = validate_current_gate_record(root, gate)
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
    parser.add_argument("project")
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
        if args.check_record:
            result = validate_current_gate_record(args.project, args.gate)
        else:
            result = run_gate(
                args.project,
                args.gate,
                dry_run=args.dry_run,
                execution_surface=args.execution_surface,
            )
        if args.snapshot_task:
            if args.dry_run:
                raise GateConfigError("cannot snapshot a dry-run gate")
            path, snapshot = snapshot_current_gate_record(
                args.project,
                args.gate,
                task_id=args.snapshot_task,
                attempt_id=args.snapshot_attempt,
            )
            result = dict(result)
            result["accepted_snapshot"] = {
                "artifact_ref": path.relative_to(Path(args.project).resolve()).as_posix(),
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


def _timeout_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


if __name__ == "__main__":
    raise SystemExit(main())
