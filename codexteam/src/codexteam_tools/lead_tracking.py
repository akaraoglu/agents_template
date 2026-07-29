"""Exact-session Lead metrics binding and Stop-hook capture."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .files import atomic_write_json
from .lead_metrics import record_lead_usage


TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
COUNTER_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")
TASK_ID_RE = re.compile(r"T[0-9]{3,6}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _marker_path(root: Path, session_id: str) -> Path:
    return root / ".codexteam" / "runtime" / "lead-sessions" / f"{session_id}.json"


def bind_session(
    project_value: str | Path,
    task_id: str,
    *,
    session_id: str | None = None,
    lead_root: Path | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Bind the active top-level Lead session to one project task."""
    project = Path(project_value).resolve()
    if not project.is_dir():
        raise ValueError(f"project path does not exist: {project}")
    session = session_id or os.environ.get("CODEX_THREAD_ID", "").strip()
    if not session:
        raise ValueError("CODEX_THREAD_ID is required on the top-level Lead surface")
    normalized_task = task_id.strip().upper()
    if not TASK_ID_RE.fullmatch(normalized_task):
        raise ValueError(f"invalid task ID: {task_id!r}")

    root = (lead_root or TOOLKIT_ROOT).resolve()
    path = _marker_path(root, session)
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(loaded, dict)
                and loaded.get("project") == str(project)
                and loaded.get("task_id") == normalized_task
            ):
                previous = loaded
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    marker = {
        "schema_version": "1.0",
        "session_id": session,
        "lead_root": str(root),
        "project": str(project),
        "task_id": normalized_task,
        "started_at": previous.get("started_at", (started_at or _now()).isoformat()),
        "baseline": previous.get("baseline"),
    }
    atomic_write_json(path, marker)
    return path


def _reverse_lines(path: Path, *, chunk_size: int = 64 * 1024) -> Iterator[str]:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        position = stream.tell()
        pending = b""
        while position:
            size = min(chunk_size, position)
            position -= size
            stream.seek(position)
            pending = stream.read(size) + pending
            lines = pending.split(b"\n")
            pending = lines[0]
            for line in reversed(lines[1:]):
                if line:
                    yield line.decode("utf-8")
        if pending:
            yield pending.decode("utf-8")


def _token_totals(event: object) -> dict[str, int] | None:
    if not isinstance(event, dict) or event.get("type") != "event_msg":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    totals = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(totals, dict):
        return None
    try:
        values = {key: totals[key] for key in COUNTER_KEYS}
    except KeyError:
        return None
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in values.values()
    ):
        return None
    return values


def _event_time(event: object) -> datetime | None:
    if not isinstance(event, dict) or not isinstance(event.get("timestamp"), str):
        return None
    try:
        return datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return None


def _usage_window(
    transcript: Path,
    *,
    started_at: datetime,
    need_baseline: bool,
) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    latest: dict[str, int] | None = None
    baseline: dict[str, int] | None = None
    for line in _reverse_lines(transcript):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        totals = _token_totals(event)
        if totals is None:
            continue
        if latest is None:
            latest = totals
            if not need_baseline:
                break
        event_time = _event_time(event)
        if need_baseline and event_time is not None and event_time <= started_at:
            baseline = totals
            break
    if latest is not None and need_baseline and baseline is None:
        baseline = {key: 0 for key in COUNTER_KEYS}
    return latest, baseline


def _session_provider(transcript: Path) -> str | None:
    with transcript.open(encoding="utf-8") as stream:
        for _ in range(20):
            line = stream.readline()
            if not line:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "session_meta":
                continue
            payload = event.get("payload")
            provider = payload.get("model_provider") if isinstance(payload, dict) else None
            if isinstance(provider, str) and provider.strip():
                return provider.strip()
    return None


def capture_stop(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    lead_root: Path | None = None,
) -> str:
    """Capture one exact Stop event; return a reason and never raise to Codex."""
    session = payload.get("session_id")
    if payload.get("hook_event_name") != "Stop" or not isinstance(session, str) or not session:
        return "ignored"
    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str):
        return "ignored"
    root = (lead_root or TOOLKIT_ROOT).resolve()
    if Path(cwd_value).resolve() != root:
        return "mismatch"
    marker_path = _marker_path(root, session)
    if not marker_path.is_file():
        return "unbound"

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if (
            not isinstance(marker, dict)
            or marker.get("session_id") != session
            or marker.get("lead_root") != str(root)
        ):
            return "mismatch"
        project = Path(marker["project"]).resolve()
        if not project.is_dir():
            return "mismatch"
        transcript_value = payload.get("transcript_path")
        model = payload.get("model")
        if not isinstance(transcript_value, str) or not isinstance(model, str) or not model.strip():
            return "invalid"
        transcript = Path(transcript_value)
        started_at = datetime.fromisoformat(marker["started_at"])
        stored_baseline = marker.get("baseline")
        need_baseline = not isinstance(stored_baseline, dict)
        totals, discovered_baseline = _usage_window(
            transcript,
            started_at=started_at,
            need_baseline=need_baseline,
        )
        if totals is None:
            return "no-totals"
        baseline = discovered_baseline if need_baseline else stored_baseline
        if not isinstance(baseline, dict) or not all(
            isinstance(baseline.get(key), int)
            and not isinstance(baseline[key], bool)
            and baseline[key] >= 0
            for key in COUNTER_KEYS
        ):
            return "invalid"
        deltas = {key: totals[key] - baseline[key] for key in COUNTER_KEYS}
        if any(value < 0 for value in deltas.values()):
            return "reset"
        if deltas["cached_input_tokens"] > deltas["input_tokens"]:
            return "reset"
        provider = _session_provider(transcript)
        if provider is None:
            return "no-provider"
        pending_present = "pending_transition" in marker
        pending = marker.get("pending_transition")
        next_task: str | None = None
        if pending_present:
            if not isinstance(pending, dict) or "next_task" not in pending:
                return "preserved"
            next_task = pending["next_task"]
            if next_task is not None and (
                not isinstance(next_task, str) or not TASK_ID_RE.fullmatch(next_task)
            ):
                return "preserved"
        captured_at = now or _now()
        duration = max(0.0, (captured_at - started_at).total_seconds())
        error = record_lead_usage(
            project,
            task_id=marker["task_id"],
            profile=model.strip(),
            provider=provider,
            duration_seconds=duration,
            input_tokens=deltas["input_tokens"],
            cached_input_tokens=deltas["cached_input_tokens"],
            output_tokens=deltas["output_tokens"],
        )
        if error:
            return "preserved"

        if pending_present:
            if next_task is None:
                marker_path.unlink()
                return "captured"
            marker.update(
                {
                    "task_id": next_task,
                    "started_at": captured_at.isoformat(),
                    "baseline": totals,
                }
            )
            marker.pop("pending_transition", None)
        elif need_baseline:
            marker["baseline"] = baseline
        atomic_write_json(marker_path, marker)
        return "captured"
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return "preserved"


def stop_from_stdin(stream: Any = None) -> int:
    try:
        payload = json.load(stream or sys.stdin)
        reason = capture_stop(payload) if isinstance(payload, dict) else "ignored"
        if reason not in {"captured", "ignored", "unbound"}:
            print(f"Lead metrics preserved: {reason}", file=sys.stderr)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return 0


def set_pending_transition(
    project: Path,
    task_id: str,
    next_task: str | None,
    *,
    session_id: str | None = None,
    lead_root: Path | None = None,
) -> bool:
    """Retain the old metrics task until its closing Stop is captured."""
    session = session_id or os.environ.get("CODEX_THREAD_ID", "").strip()
    if not session:
        return False
    root = (lead_root or TOOLKIT_ROOT).resolve()
    path = _marker_path(root, session)
    if not path.is_file():
        return False
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        if (
            marker.get("session_id") != session
            or marker.get("lead_root") != str(root)
            or Path(marker.get("project", "")).resolve() != project.resolve()
            or marker.get("task_id") != task_id
        ):
            return False
        marker["pending_transition"] = {"from_task": task_id, "next_task": next_task}
        atomic_write_json(path, marker)
        return True
    except (OSError, TypeError, AttributeError, json.JSONDecodeError):
        return False
