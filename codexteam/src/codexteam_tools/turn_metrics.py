from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json
from .execution_spec import ExecutionSpecError, load_execution_spec
from .paths import ensure_existing_workspace


SCHEMA_VERSION = "1.0"
TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
METRICS_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.metrics\.json$")
PREVIEW_LIMIT = 180
REPEATED_COMMAND_LIMIT = 10
MODEL_STEP_LIMIT = 100
TOOL_TYPE_LIMIT = 50
NON_TOOL_ITEM_TYPES = {"agent_message", "reasoning", "todo_list"}
SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
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
    backend: str = "codex",
    context_bytes: dict[str, int] | None = None,
    requested_reasoning: str | None = None,
    effective_reasoning: str | None = None,
    exit_code: int | None = None,
    timed_out: bool = False,
    guard_triggered: bool = False,
    prompt_bytes: int | None = None,
    events_sha256: str | None = None,
    stderr_sha256: str | None = None,
) -> dict[str, Any]:
    if backend not in {"codex", "opencode"}:
        raise ValueError(f"unsupported execution backend: {backend}")
    item_counts: Counter[str] = Counter()
    commands: list[dict[str, Any]] = []
    mcp_observations: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    completed = False
    last_error: str | None = None
    parse_error_count = 0
    failed_tool_calls = 0
    mcp_failure_seen = False
    command_calls_after_mcp_failure = 0

    opencode_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    opencode_usage_seen = False
    opencode_cache_write_tokens = 0
    opencode_model_step_count = 0
    opencode_model_steps: list[dict[str, Any]] = []
    opencode_first_step_input: int | None = None
    opencode_last_step_input: int | None = None
    opencode_max_step_input: int | None = None
    opencode_tool_output_bytes: Counter[str] = Counter()
    terminal_reason: str | None = None
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
        if backend == "opencode":
            part = event.get("part")
            if event_type == "text":
                item_counts["agent_message"] += 1
            elif event_type == "tool_use":
                state = part.get("state") if isinstance(part, dict) else None
                if not isinstance(state, dict) or state.get("status") not in {
                    "completed",
                    "error",
                    "failed",
                }:
                    continue
                item_counts["tool_use"] += 1
                tool = _opencode_tool_name(part.get("tool") if isinstance(part, dict) else None)
                item_counts[f"tool:{tool}"] += 1
                failed_tool_calls += int(_opencode_tool_failed(state))
                measured_output = _opencode_tool_output_bytes(state)
                if measured_output is not None:
                    opencode_tool_output_bytes[tool] += measured_output
            elif event_type == "step_finish" and isinstance(part, dict):
                reason = part.get("reason")
                terminal_reason = reason[:64] if isinstance(reason, str) else "unknown"
                completed = completed or (
                    reason == "stop"
                )
                tokens = part.get("tokens")
                if isinstance(tokens, dict):
                    opencode_usage_seen = True
                    cache = tokens.get("cache")
                    raw_input = _opencode_token_int(tokens.get("input"))
                    raw_output = _opencode_token_int(tokens.get("output"))
                    reasoning = _opencode_token_int(tokens.get("reasoning"))
                    cache_read = 0
                    cache_write = 0
                    if isinstance(cache, dict):
                        cache_read = _opencode_token_int(cache.get("read"))
                        cache_write = _opencode_token_int(cache.get("write"))
                    opencode_usage["input_tokens"] += raw_input + cache_read + cache_write
                    opencode_usage["cached_input_tokens"] += cache_read
                    opencode_usage["output_tokens"] += raw_output + reasoning
                    opencode_usage["reasoning_output_tokens"] += reasoning
                    opencode_cache_write_tokens += cache_write
                    total_input = raw_input + cache_read + cache_write
                    opencode_model_step_count += 1
                    if opencode_first_step_input is None:
                        opencode_first_step_input = total_input
                    opencode_last_step_input = total_input
                    opencode_max_step_input = max(
                        opencode_max_step_input or 0,
                        total_input,
                    )
                    if len(opencode_model_steps) < MODEL_STEP_LIMIT:
                        opencode_model_steps.append(
                            {
                                "ordinal": opencode_model_step_count,
                                "reason": reason[:64] if isinstance(reason, str) else "unknown",
                                "input_tokens": total_input,
                                "cached_input_tokens": cache_read,
                                "uncached_input_tokens": total_input - cache_read,
                                "cache_write_tokens": cache_write,
                                "output_tokens": raw_output + reasoning,
                                "reasoning_output_tokens": reasoning,
                            }
                        )
            elif event_type == "error":
                last_error = _opencode_event_error(event)
            continue
        if event_type == "event_msg":
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            payload_type = payload.get("type")
            if payload_type == "token_count":
                info = payload.get("info")
                total = info.get("total_token_usage") if isinstance(info, dict) else None
                if isinstance(total, dict):
                    usage = total
            elif payload_type == "task_complete":
                completed = True
                terminal_reason = "completed"
            elif payload_type == "mcp_tool_call_end":
                observation = _mcp_observation_from_event(payload)
                if observation is None:
                    continue
                item_counts["mcp_tool_call"] += 1
                mcp_observations.append(observation)
                failed_tool_calls += int(observation["failed"])
                mcp_failure_seen = mcp_failure_seen or observation["failed"]
            elif payload_type == "agent_message":
                item_counts["agent_message"] += 1
            elif payload_type in {"error", "turn_aborted"}:
                last_error = _event_error(payload)
        elif event_type == "response_item":
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("type") == "tool_search_call":
                item_counts["tool_search_call"] += 1
                if payload.get("status") == "failed":
                    failed_tool_calls += 1
        elif event_type == "turn.completed":
            completed = True
            terminal_reason = "completed"
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
                observation = command_observation(item)
                commands.append(observation)
                failed_tool_calls += observation["failed"]
                if mcp_failure_seen:
                    command_calls_after_mcp_failure += 1
            elif item_type == "mcp_tool_call":
                observation = _mcp_observation_from_item(item)
                mcp_observations.append(observation)
                failed_tool_calls += int(observation["failed"])
                mcp_failure_seen = mcp_failure_seen or observation["failed"]
            elif item_type not in NON_TOOL_ITEM_TYPES and item.get("status") == "failed":
                failed_tool_calls += 1

    if backend == "opencode":
        delta = _usage_values(opencode_usage if opencode_usage_seen else None)
        cumulative = _opencode_cumulative_usage(delta, previous_summary)
        delta_mode = "per_turn" if opencode_usage_seen else "unavailable"
    else:
        cumulative = _usage_values(usage)
        previous = _previous_usage(previous_summary)
        delta, delta_mode = _usage_delta(cumulative, previous)
    if terminal_reason is None:
        terminal_reason = (
            "timeout" if timed_out else
            "guard_interrupted" if guard_triggered else
            "failed" if last_error else
            "process_exit" if isinstance(exit_code, int) and exit_code != 0 else
            "unknown"
        )
    repeated = _repeated_commands(commands)
    largest = sorted(
        commands,
        key=lambda item: (-item["output_bytes"], item["fingerprint"]),
    )[:3]
    output_bytes = sum(item["output_bytes"] for item in commands)
    tool_calls = sum(
        count
        for item_type, count in item_counts.items()
        if item_type not in NON_TOOL_ITEM_TYPES
        and (backend != "opencode" or not item_type.startswith("tool:"))
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "metric_scope": "worker_turn",
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
            "terminal_reason": terminal_reason,
        },
        "reasoning": {
            "requested": requested_reasoning,
            "effective": effective_reasoning,
        },
        "process": {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "guard_triggered": guard_triggered,
            "classification": (
                "timeout" if timed_out else
                "guard_interrupted" if guard_triggered else
                "success" if exit_code == 0 else
                "process_exit" if isinstance(exit_code, int) else
                "unknown"
            ),
        },
        "prompt_bytes": prompt_bytes,
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
            "mcp": _mcp_summary(
                mcp_observations,
                command_calls_after_mcp_failure=command_calls_after_mcp_failure,
            ),
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
            "diagnostics": {
                "events_sha256": events_sha256,
                "stderr_sha256": stderr_sha256,
            },
        },
        **(_opencode_fields(
            model_steps=opencode_model_steps,
            model_step_count=opencode_model_step_count,
            first_step_input=opencode_first_step_input,
            last_step_input=opencode_last_step_input,
            max_step_input=opencode_max_step_input,
            cache_write_tokens=opencode_cache_write_tokens,
            tool_output_bytes=opencode_tool_output_bytes,
            context_bytes=context_bytes,
        ) if backend == "opencode" else {}),
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
        execution_spec = _backfill_execution_spec(session_path.parent)
        profile_ref = execution_spec.get("execution_profile", {})
        backend_ref = profile_ref.get("backend", {}) if isinstance(profile_ref, dict) else {}
        named_profile = profile_ref.get("profile", {}) if isinstance(profile_ref, dict) else {}
        reasoning_ref = profile_ref.get("reasoning", {}) if isinstance(profile_ref, dict) else {}
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
                profile=str(named_profile.get("id") or session.get("model_profile") or "unknown"),
                turn_number=number,
                phase=phase,
                duration_seconds=item.get("duration_seconds"),
                source_event_file=event_path.name,
                previous_summary=prior,
                backend=str(backend_ref.get("id") or session.get("execution_backend") or "codex"),
                requested_reasoning=reasoning_ref.get("requested"),
                effective_reasoning=reasoning_ref.get("effective"),
            )
            action = "would_overwrite" if target_existed else "would_create"
            if write:
                write_summary(target, summary, overwrite=overwrite)
                action = "overwritten" if target_existed else "created"
            records.append(_backfill_record(project_root, target, action))
            prior = summary
    return records


def _backfill_execution_spec(session_dir: Path) -> dict[str, Any]:
    path = session_dir / "execution-spec.json"
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        value = load_execution_spec(path)
    except (OSError, ExecutionSpecError):
        return {}
    return value


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


def _opencode_fields(
    *,
    model_steps: list[dict[str, Any]],
    model_step_count: int,
    first_step_input: int | None,
    last_step_input: int | None,
    max_step_input: int | None,
    cache_write_tokens: int,
    tool_output_bytes: Counter[str],
    context_bytes: dict[str, int] | None,
) -> dict[str, Any]:
    output_by_tool = {
        tool: tool_output_bytes[tool]
        for tool in sorted(tool_output_bytes)[:TOOL_TYPE_LIMIT]
    }
    backend_usage = {
        "model_steps": model_step_count,
        "first_step_input_tokens": first_step_input,
        "last_step_input_tokens": last_step_input,
        "max_step_input_tokens": max_step_input,
        "cache_write_tokens": cache_write_tokens,
        "tool_text_output_bytes_by_tool": output_by_tool,
    }
    fields: dict[str, Any] = {
        "execution_backend": "opencode",
        "model_steps": model_steps,
        "backend_usage": backend_usage,
    }
    if context_bytes is not None:
        fields["context_bytes"] = dict(context_bytes)
    return fields


def _opencode_cumulative_usage(
    current: dict[str, int | None],
    previous_summary: dict[str, Any] | None,
) -> dict[str, int | None]:
    previous = _previous_usage(previous_summary)
    if all(value is None for value in current.values()):
        return _usage_values(previous) if previous is not None else dict(current)
    cumulative: dict[str, int | None] = {}
    for key, value in current.items():
        previous_value = _nonnegative_int(previous.get(key)) if previous else None
        cumulative[key] = value if previous_value is None else previous_value + (value or 0)
    return cumulative


def _opencode_tool_name(value: Any) -> str:
    return value if isinstance(value, str) and SAFE_TOOL_NAME.fullmatch(value) else "unknown"


def _opencode_tool_failed(state: dict[str, Any]) -> bool:
    if state.get("status") in {"error", "failed"} or state.get("error") is not None:
        return True
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return False
    for key in ("exit", "exit_code", "exitCode"):
        exit_code = metadata.get(key)
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            return exit_code != 0
    return metadata.get("success") is False


def _opencode_tool_output_bytes(state: dict[str, Any]) -> int | None:
    output = state.get("output")
    if isinstance(output, str):
        return len(output.encode("utf-8"))
    error = state.get("error")
    if isinstance(error, str):
        return len(error.encode("utf-8"))
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("output_bytes", "outputBytes"):
        measured = _nonnegative_int(metadata.get(key))
        if measured is not None:
            return measured
    metadata_output = metadata.get("output")
    if isinstance(metadata_output, str):
        return len(metadata_output.encode("utf-8"))
    streams = [
        metadata[key]
        for key in ("stdout", "stderr")
        if isinstance(metadata.get(key), str)
    ]
    return sum(len(value.encode("utf-8")) for value in streams) if streams else None


def _opencode_token_int(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return 0
    return int(value)


def _opencode_event_error(event: dict[str, Any]) -> str:
    error = event.get("error")
    error = error if isinstance(error, dict) else event
    name = error.get("name")
    data = error.get("data")
    message = data.get("message") if isinstance(data, dict) else None
    safe_name = name.strip()[:100] if isinstance(name, str) and name.strip() else "OpenCode error"
    if isinstance(message, str) and message.strip():
        return f"{safe_name}:sha256:{hashlib.sha256(message.encode('utf-8')).hexdigest()}"
    return safe_name


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


def command_observation(item: dict[str, Any]) -> dict[str, Any]:
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


def _mcp_observation_from_item(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result")
    error = item.get("error")
    failed = bool(
        item.get("status") == "failed"
        or error
        or (isinstance(result, dict) and result.get("isError") is True)
    )
    return _mcp_observation(
        server=item.get("server"),
        tool=item.get("tool"),
        result=result,
        failed=failed,
        client_duration_ms=None,
    )


def _mcp_observation_from_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    invocation = payload.get("invocation")
    if not isinstance(invocation, dict):
        return None
    result_wrapper = payload.get("result")
    result: Any = None
    failed = False
    if isinstance(result_wrapper, dict):
        if "Err" in result_wrapper:
            failed = True
        elif "Ok" in result_wrapper:
            result = result_wrapper["Ok"]
            failed = bool(isinstance(result, dict) and result.get("isError") is True)
        else:
            result = result_wrapper
            failed = bool(result_wrapper.get("isError") is True)
    elif result_wrapper is not None:
        failed = True
    return _mcp_observation(
        server=invocation.get("server"),
        tool=invocation.get("tool"),
        result=result,
        failed=failed,
        client_duration_ms=_event_duration_ms(payload.get("duration")),
    )


def _mcp_observation(
    *,
    server: Any,
    tool: Any,
    result: Any,
    failed: bool,
    client_duration_ms: float | None,
) -> dict[str, Any]:
    structured: Any = None
    if isinstance(result, dict):
        structured = result.get("structured_content")
        if not isinstance(structured, dict):
            structured = result.get("structuredContent")
    stats = structured.get("query_stats") if isinstance(structured, dict) else None
    if not isinstance(stats, dict):
        stats = {}
    return {
        "server": str(server or "unknown"),
        "tool": str(tool or "unknown"),
        "failed": bool(failed),
        "server_duration_ms": _nonnegative_number(stats.get("duration_ms")),
        "client_duration_ms": client_duration_ms,
        "returned_bytes": _nonnegative_int(stats.get("returned_bytes")),
        "source_bytes": _nonnegative_int(stats.get("source_bytes")),
        "response_bytes": _serialized_bytes(result),
        "cache_hit": stats.get("cache_hit") is True,
        "source_digests": _source_digests(structured),
    }


def _mcp_summary(
    observations: list[dict[str, Any]],
    *,
    command_calls_after_mcp_failure: int,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in observations:
        key = (item["server"], item["tool"])
        aggregate = grouped.setdefault(
            key,
            {
                "server": item["server"],
                "tool": item["tool"],
                "calls": 0,
                "failed_calls": 0,
                "server_duration_ms": 0.0,
                "client_duration_ms": 0.0,
                "returned_bytes": 0,
                "source_bytes": 0,
                "response_bytes": 0,
                "cache_hits": 0,
                "source_digests": set(),
            },
        )
        aggregate["calls"] += 1
        aggregate["failed_calls"] += int(item["failed"])
        aggregate["server_duration_ms"] += item["server_duration_ms"] or 0
        aggregate["client_duration_ms"] += item["client_duration_ms"] or 0
        aggregate["returned_bytes"] += item["returned_bytes"] or 0
        aggregate["source_bytes"] += item["source_bytes"] or 0
        aggregate["response_bytes"] += item["response_bytes"]
        aggregate["cache_hits"] += int(item["cache_hit"])
        aggregate["source_digests"].update(item["source_digests"])

    by_tool = sorted(grouped.values(), key=lambda item: (item["server"], item["tool"]))
    for item in by_tool:
        item["server_duration_ms"] = round(item["server_duration_ms"], 3)
        item["client_duration_ms"] = round(item["client_duration_ms"], 3)
        item["source_digests"] = sorted(item["source_digests"])
    return {
        "calls": len(observations),
        "failed_calls": sum(int(item["failed"]) for item in observations),
        "server_duration_ms": round(
            sum(item["server_duration_ms"] or 0 for item in observations),
            3,
        ),
        "client_duration_ms": round(
            sum(item["client_duration_ms"] or 0 for item in observations),
            3,
        ),
        "returned_bytes": sum(item["returned_bytes"] or 0 for item in observations),
        "source_bytes": sum(item["source_bytes"] or 0 for item in observations),
        "response_bytes": sum(item["response_bytes"] for item in observations),
        "cache_hits": sum(int(item["cache_hit"]) for item in observations),
        "source_digests": sorted(
            {digest for item in observations for digest in item["source_digests"]}
        ),
        "max_returned_bytes": max(
            (item["returned_bytes"] or 0 for item in observations),
            default=0,
        ),
        "max_response_bytes": max(
            (item["response_bytes"] for item in observations),
            default=0,
        ),
        "command_calls_after_failure": command_calls_after_mcp_failure,
        "repeated_tools": [
            {
                "server": item["server"],
                "tool": item["tool"],
                "calls": item["calls"],
            }
            for item in sorted(
                (item for item in by_tool if item["calls"] > 1),
                key=lambda item: (-item["calls"], item["server"], item["tool"]),
            )
        ],
        "by_tool": by_tool,
    }


def _source_digests(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if (
                    key in {"sha256", "source_sha256", "index_sha256"}
                    and isinstance(child, str)
                    and re.fullmatch(r"[a-f0-9]{64}", child)
                ):
                    found.add(child)
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _event_duration_ms(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    seconds = _nonnegative_number(value.get("secs"))
    nanos = _nonnegative_number(value.get("nanos"))
    if seconds is None or nanos is None:
        return None
    return round(seconds * 1000 + nanos / 1_000_000, 3)


def _serialized_bytes(value: Any) -> int:
    if value is None:
        return 0
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return 0
    return len(serialized.encode("utf-8"))


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
    encoded = str(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _nonnegative_int(value: Any) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return int(value)


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


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
