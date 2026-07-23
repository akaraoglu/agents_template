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
from .paths import contained_path, ensure_existing_workspace

GATES = ("development", "integration")
CONFIG_PATH = "management/TEST_GATES.toml"
RECORD_ROOT = "results/gates"


class GateConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GateConfig:
    verification_paths: tuple[str, ...]
    development_commands: tuple[tuple[str, ...], ...]
    integration_commands: tuple[tuple[str, ...], ...]
    development_timeout: int
    integration_timeout: int


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
    )


def run_gate(
    project: str | Path,
    gate: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if gate not in GATES:
        raise GateConfigError(f"unsupported gate: {gate}")
    root = ensure_existing_workspace(project)
    config = load_gate_config(root)
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
                    list(argv),
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=remaining,
                    check=False,
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
        "started_at": started_wall,
        "completed_at": _utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "verification_paths": list(config.verification_paths),
        "configuration_digest": _config_digest(config),
        "workspace_digest": _manifest_digest(manifest),
        "commands": records,
    }
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
    if not isinstance(record, dict) or record.get("schema_version") != "1.0":
        raise GateConfigError("gate record schema_version must be '1.0'")
    if record.get("gate") != gate or record.get("status") != "passed":
        raise GateConfigError(f"{gate} gate record is not a passing record")
    if record.get("project_root") != str(root):
        raise GateConfigError("gate record project root does not match")
    patterns = record.get("verification_paths")
    if not isinstance(patterns, list):
        raise GateConfigError("gate record verification_paths must be a list")
    if patterns != list(config.verification_paths) or record.get("configuration_digest") != _config_digest(config):
        raise GateConfigError(f"{gate} gate record is stale for the current gate configuration")
    current = _manifest_digest(verification_manifest(root, tuple(patterns)))
    if current != record.get("workspace_digest"):
        raise GateConfigError(f"{gate} gate record is stale for the current workspace")
    return record


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
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check_record:
            result = validate_current_gate_record(args.project, args.gate)
        else:
            result = run_gate(args.project, args.gate, dry_run=args.dry_run)
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
    return 0 if result.get("status") in {"passed", "dry_run"} else 1


def _gate_table(value: Any, name: str) -> tuple[tuple[tuple[str, ...], ...], int, tuple[str, ...]]:
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
    return tuple(commands), timeout, tuple(includes_value)


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
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _excluded(relative: str) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in (".git", ".codexteam/runtime", "results/gates")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _timeout_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


if __name__ == "__main__":
    raise SystemExit(main())
