from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json
from .paths import ensure_existing_workspace


SCHEMA_VERSION = "1.0"
TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
METRICS_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.metrics\.json$")
PREVIEW_LIMIT = 180
REPEATED_COMMAND_LIMIT = 10
NON_TOOL_ITEM_TYPES = {"agent_message", "reasoning", "todo_list"}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*)"
    r"=([^\s]+)"
)
SECRET_FLAG = re.compile(
    r"(?i)(--(?:api[-_]?key|token|password|secret|authorization)(?:=|\s+))([^\s]+)"
)
BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[^\s]+")
SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[-_]?key|token|password|secret|authorization)=)([^&\s]+)"
)
CURL_USER = re.compile(r"(?i)(\s-u\s+)(\"[^\"]*\"|'[^']*'|[^\s]+)")


def metrics_path(events_path: Path) -> Path:
    if events_path.suffix != ".jsonl":
        raise ValueError(f"turn event path must end in .jsonl: {events_path}")
    return events_path.with_suffix(".metrics.json")


def summarize_turn(
    event_text: str,
    *,
    task_id: str,
    attempt_id: str,
    role: str,
    profile: str,
    turn_number: int,
    phase: str,
    duration_seconds: float | int | None,
    source_event_file: str,
    previous_summary: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    item_counts: Counter[str] = Counter()
    commands: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    completed = False
    last_error: str | None = None
    parse_error_count = 0
    failed_tool_calls = 0

    for raw_line in event_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_error_count += 1
            continue
        if not isinstance(event, dict):
            parse_error_count += 1
            continue
        event_type = event.get("type")
        if event_type == "turn.completed":
            completed = True
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
        elif event_type in {"turn.failed", "error"}:
            last_error = _event_error(event)
        elif event_type == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "unknown")
            item_counts[item_type] += 1
            if item_type == "command_execution":
                observation = _command_observation(item)
                commands.append(observation)
                failed_tool_calls += observation["failed"]
            elif item_type not in NON_TOOL_ITEM_TYPES and item.get("status") == "failed":
                failed_tool_calls += 1

    cumulative = _usage_values(usage)
    previous = _previous_usage(previous_summary)
    delta, delta_mode = _usage_delta(cumulative, previous)
    repeated = _repeated_commands(commands)
    largest = sorted(
        commands,
        key=lambda item: (-item["output_bytes"], item["fingerprint"]),
    )[:3]
    output_bytes = sum(item["output_bytes"] for item in commands)
    tool_calls = sum(
        count for item_type, count in item_counts.items() if item_type not in NON_TOOL_ITEM_TYPES
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "agent_role": role,
        "model_profile": profile,
        "source_event_file": source_event_file,
        "turn": {
            "number": turn_number,
            "phase": phase,
            "completed": completed,
            "duration_seconds": _duration(duration_seconds),
        },
        "usage": {
            "cumulative": cumulative,
            "delta": delta,
            "delta_mode": delta_mode,
        },
        "activity": {
            "tool_calls": tool_calls,
            "failed_tool_calls": failed_tool_calls,
            "command_calls": item_counts["command_execution"],
            "failed_command_calls": sum(item["failed"] for item in commands),
            "edit_events": item_counts["file_change"],
            "agent_messages": item_counts["agent_message"],
            "command_output_bytes": output_bytes,
            "max_command_output_bytes": max(
                (item["output_bytes"] for item in commands),
                default=0,
            ),
            "item_type_counts": dict(sorted(item_counts.items())),
            "repeated_commands": repeated,
            "largest_commands": [
                {
                    "fingerprint": item["fingerprint"],
                    "preview": item["preview"],
                    "output_bytes": item["output_bytes"],
                    "exit_code": item["exit_code"],
                    "failed": item["failed"],
                }
                for item in largest
            ],
        },
        "events": {
            "parse_error_count": parse_error_count,
            "last_error": last_error,
        },
        "generated_at": generated_at or _utc_now(),
    }


def write_summary(
    path: Path,
    summary: dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    if path.is_symlink():
        raise ValueError(f"turn metrics path cannot be a symlink: {path}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"turn metrics already exist: {path}")
    atomic_write_json(path, summary)
    path.chmod(0o600)


def load_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return None
    turn = value.get("turn")
    usage = value.get("usage")
    activity = value.get("activity")
    events = value.get("events")
    if not all(isinstance(item, dict) for item in (turn, usage, activity, events)):
        return None
    if (
        not isinstance(usage.get("cumulative"), dict)
        or not isinstance(usage.get("delta"), dict)
        or not isinstance(activity.get("largest_commands"), list)
        or not isinstance(activity.get("repeated_commands"), list)
    ):
        return None
    return value


def previous_summary(turns_dir: Path, turn_number: int) -> dict[str, Any] | None:
    candidates: list[tuple[int, Path]] = []
    if not turns_dir.is_dir():
        return None
    for path in turns_dir.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        match = METRICS_FILE.match(path.name)
        if match and int(match.group(1)) < turn_number:
            candidates.append((int(match.group(1)), path))
    for _, path in sorted(candidates, reverse=True):
        summary = load_summary(path)
        if summary is not None:
            return summary
    event_candidates: list[tuple[int, Path]] = []
    for path in turns_dir.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        match = TURN_FILE.match(path.name)
        if match and int(match.group(1)) < turn_number:
            event_candidates.append((int(match.group(1)), path))
    for _, path in sorted(event_candidates, reverse=True):
        usage = _last_usage(path.read_text(encoding="utf-8"))
        if usage is not None:
            return {"usage": {"cumulative": _usage_values(usage)}}
    return None


def backfill_project(
    project: str | Path,
    *,
    write: bool = False,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    if overwrite and not write:
        raise ValueError("--overwrite requires --write")
    project_root = ensure_existing_workspace(project)
    sessions_root = project_root / ".codexteam" / "runtime" / "sessions"
    if not sessions_root.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for session_path in sorted(sessions_root.rglob("session.json")):
        if session_path.is_symlink() or not session_path.is_file():
            continue
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(session, dict):
            continue
        turns_dir = session_path.parent / "turns"
        if not turns_dir.is_dir() or turns_dir.is_symlink():
            continue
        session_turns = (
            session.get("turns")
            if isinstance(session.get("turns"), list)
            else []
        )
        metadata = {
            item.get("number"): item
            for item in session_turns
            if isinstance(item, dict) and isinstance(item.get("number"), int)
        }
        prior: dict[str, Any] | None = None
        event_paths = sorted(
            path
            for path in turns_dir.iterdir()
            if path.is_file() and not path.is_symlink() and TURN_FILE.match(path.name)
        )
        for event_path in event_paths:
            match = TURN_FILE.match(event_path.name)
            number = int(match.group(1))
            phase = match.group(2)
            target = metrics_path(event_path)
            target_existed = target.exists()
            existing = load_summary(target)
            if existing is not None and not overwrite:
                prior = existing
                records.append(_backfill_record(project_root, target, "exists"))
                continue
            item = metadata.get(number, {})
            summary = summarize_turn(
                event_path.read_text(encoding="utf-8"),
                task_id=str(session.get("task_id") or event_path.parents[2].name),
                attempt_id=str(session.get("attempt_id") or event_path.parent.parent.name),
                role=str(session.get("agent_role") or "unknown"),
                profile=str(session.get("model_profile") or "unknown"),
                turn_number=number,
                phase=phase,
                duration_seconds=item.get("duration_seconds"),
                source_event_file=event_path.name,
                previous_summary=prior,
            )
            action = "would_overwrite" if target_existed else "would_create"
            if write:
                write_summary(target, summary, overwrite=overwrite)
                action = "overwritten" if target_existed else "created"
            records.append(_backfill_record(project_root, target, action))
            prior = summary
    return records


def _usage_values(usage: dict[str, Any] | None) -> dict[str, int | None]:
    input_tokens = _nonnegative_int((usage or {}).get("input_tokens"))
    cached_tokens = _nonnegative_int((usage or {}).get("cached_input_tokens"))
    output_tokens = _nonnegative_int((usage or {}).get("output_tokens"))
    reasoning_tokens = _nonnegative_int((usage or {}).get("reasoning_output_tokens"))
    uncached_tokens = None
    if input_tokens is not None and cached_tokens is not None and cached_tokens <= input_tokens:
        uncached_tokens = input_tokens - cached_tokens
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": uncached_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_tokens,
    }


def _last_usage(event_text: str) -> dict[str, Any] | None:
    usage = None
    for raw_line in event_text.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "turn.completed"
            and isinstance(event.get("usage"), dict)
        ):
            usage = event["usage"]
    return usage


def _previous_usage(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    usage = summary.get("usage")
    cumulative = usage.get("cumulative") if isinstance(usage, dict) else None
    return cumulative if isinstance(cumulative, dict) else None


def _usage_delta(
    current: dict[str, int | None],
    previous: dict[str, Any] | None,
) -> tuple[dict[str, int | None], str]:
    keys = tuple(current)
    if all(current[key] is None for key in keys):
        return {key: None for key in keys}, "unavailable"
    if previous is None:
        return dict(current), "initial"
    delta: dict[str, int | None] = {}
    non_monotonic = False
    for key in keys:
        current_value = current[key]
        previous_value = _nonnegative_int(previous.get(key))
        if current_value is None or previous_value is None:
            delta[key] = None
        elif current_value < previous_value:
            delta[key] = None
            non_monotonic = True
        else:
            delta[key] = current_value - previous_value
    return delta, "reset_or_non_monotonic" if non_monotonic else "cumulative"


def _command_observation(item: dict[str, Any]) -> dict[str, Any]:
    command = str(item.get("command") or "")
    normalized = " ".join(command.split())
    sanitized = _redact_command(normalized)
    output = item.get("aggregated_output")
    if not isinstance(output, str):
        output = item.get("output") if isinstance(item.get("output"), str) else ""
    exit_code = item.get("exit_code")
    exit_code = exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    failed = bool(item.get("status") == "failed" or (exit_code is not None and exit_code != 0))
    return {
        "fingerprint": hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16],
        "preview": _command_preview(sanitized),
        "output_bytes": len(output.encode("utf-8")),
        "exit_code": exit_code,
        "failed": failed,
    }


def _repeated_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(item["fingerprint"] for item in commands)
    first = {item["fingerprint"]: item for item in commands}
    repeated = [
        {
            "fingerprint": fingerprint,
            "preview": first[fingerprint]["preview"],
            "count": count,
        }
        for fingerprint, count in counts.items()
        if count > 1
    ]
    repeated.sort(key=lambda item: (-item["count"], item["fingerprint"]))
    return repeated[:REPEATED_COMMAND_LIMIT]


def _command_preview(command: str) -> str:
    return command if len(command) <= PREVIEW_LIMIT else command[: PREVIEW_LIMIT - 3] + "..."


def _redact_command(command: str) -> str:
    value = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", command)
    value = SECRET_FLAG.sub(lambda match: f"{match.group(1)}<redacted>", value)
    value = BEARER_VALUE.sub("Bearer <redacted>", value)
    value = SECRET_QUERY.sub(lambda match: f"{match.group(1)}<redacted>", value)
    return CURL_USER.sub(lambda match: f"{match.group(1)}<redacted>", value)


def _event_error(event: dict[str, Any]) -> str:
    value = event.get("message") or event.get("error") or event.get("type") or "unknown error"
    if isinstance(value, dict):
        value = value.get("message") or json.dumps(value, sort_keys=True)
    return str(value)[:500]


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def _duration(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    rounded = round(float(value), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _backfill_record(project: Path, path: Path, action: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(project).as_posix(),
        "action": action,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
