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
from .paths import contained_path, ensure_existing_workspace
from .tasks import TaskDocumentError, parse_task_document
from .test_gates import GateConfigError, validate_current_gate_record


TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
COUNTER_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")
TASK_ID_RE = re.compile(r"T[0-9]{3,6}")
_NO_TRANSITION = object()


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
    transcript_path: Path | None = None,
    sessions_root: Path | None = None,
    reset_existing: bool = False,
) -> Path:
    """Bind the active top-level Lead session to one project task."""
    project = ensure_existing_workspace(project_value)
    session = session_id or os.environ.get("CODEX_THREAD_ID", "").strip()
    if not session:
        raise ValueError("CODEX_THREAD_ID is required on the top-level Lead surface")
    normalized_task = task_id.strip().upper()
    if not TASK_ID_RE.fullmatch(normalized_task):
        raise ValueError(f"invalid task ID: {task_id!r}")

    root = (lead_root or TOOLKIT_ROOT).resolve()
    path = _marker_path(root, session)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            if not reset_existing:
                raise ValueError(
                    f"existing Lead binding is unreadable; use --reset to replace it: {path}"
                ) from exc
            loaded = None
        if isinstance(loaded, dict) and not reset_existing:
            if (
                loaded.get("session_id") != session
                or loaded.get("lead_root") != str(root)
            ):
                raise ValueError(
                    f"existing Lead binding does not match this session; use --reset: {path}"
                )
            if loaded.get("project") != str(project):
                raise ValueError(
                    "Lead session is bound to another project; finish that boundary "
                    "or use --reset explicitly"
                )
            if loaded.get("task_id") == normalized_task:
                return path
            if "pending_transition" in loaded:
                pending = loaded.get("pending_transition")
                if (
                    not isinstance(pending, dict)
                    or pending.get("next_task") != normalized_task
                ):
                    raise ValueError(
                        f"existing Lead binding has an unresolved transition: {pending!r}; "
                        "end the current turn before binding another task"
                    )
            reason = _checkpoint_transition(
                path,
                loaded,
                normalized_task,
                captured_at=started_at or _now(),
                transcript_path=transcript_path,
                sessions_root=sessions_root,
            )
            if reason == "captured":
                return path
            raise ValueError(
                f"cannot checkpoint existing Lead task {loaded.get('task_id')!r}: {reason}; "
                "end the current turn or use --reset to discard the stale binding"
            )

    marker = {
        "schema_version": "1.0",
        "session_id": session,
        "lead_root": str(root),
        "project": str(project),
        "task_id": normalized_task,
        "started_at": (started_at or _now()).isoformat(),
        "baseline": None,
    }
    resolved_transcript = _resolve_transcript(
        session,
        explicit_path=transcript_path,
        sessions_root=sessions_root,
    )
    if resolved_transcript is not None:
        marker["transcript_path"] = str(resolved_transcript)
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


def _session_model(transcript: Path) -> str | None:
    for line in _reverse_lines(transcript):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn_context":
            continue
        payload = event.get("payload")
        model = payload.get("model") if isinstance(payload, dict) else None
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


def _transcript_matches_session(transcript: Path, session_id: str) -> bool:
    try:
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
                if not isinstance(payload, dict):
                    return False
                return session_id in {payload.get("id"), payload.get("session_id")}
    except (OSError, UnicodeDecodeError):
        return False
    return False


def _resolve_transcript(
    session_id: str,
    *,
    explicit_path: Path | None = None,
    marker: dict[str, Any] | None = None,
    sessions_root: Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(Path(explicit_path).expanduser())
    marker_path = marker.get("transcript_path") if isinstance(marker, dict) else None
    if isinstance(marker_path, str) and marker_path:
        candidates.append(Path(marker_path).expanduser())
    root = sessions_root
    if root is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        root = codex_home / "sessions"
    if root.is_dir():
        candidates.extend(root.rglob(f"rollout-*-{session_id}.jsonl"))
    valid: list[Path] = []
    for candidate in dict.fromkeys(candidates):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and _transcript_matches_session(resolved, session_id):
            valid.append(resolved)
    if not valid:
        return None
    return max(valid, key=lambda item: item.stat().st_mtime_ns)


def _capture_bound_usage(
    marker_path: Path,
    marker: dict[str, Any],
    transcript: Path,
    model: str,
    captured_at: datetime,
    *,
    transition: object = _NO_TRANSITION,
) -> str:
    try:
        project = Path(marker["project"]).resolve()
        if not project.is_dir():
            return "mismatch"
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
        next_task: str | None = None
        if transition is not _NO_TRANSITION:
            pending_present = True
            next_task = transition if isinstance(transition, str) else None
        elif pending_present:
            pending = marker.get("pending_transition")
            if not isinstance(pending, dict) or "next_task" not in pending:
                return "preserved"
            next_task = pending["next_task"]
        if pending_present and next_task is not None and (
            not isinstance(next_task, str) or not TASK_ID_RE.fullmatch(next_task)
        ):
            return "preserved"

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
                    "transcript_path": str(transcript),
                    "model": model.strip(),
                    "provider": provider,
                }
            )
            marker.pop("pending_transition", None)
        else:
            if need_baseline:
                marker["baseline"] = baseline
            marker.update(
                {
                    "transcript_path": str(transcript),
                    "model": model.strip(),
                    "provider": provider,
                }
            )
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


def _checkpoint_transition(
    marker_path: Path,
    marker: dict[str, Any],
    next_task: str | None,
    *,
    captured_at: datetime,
    transcript_path: Path | None = None,
    sessions_root: Path | None = None,
) -> str:
    session = marker.get("session_id")
    if not isinstance(session, str) or not session:
        return "mismatch"
    transcript = _resolve_transcript(
        session,
        explicit_path=transcript_path,
        marker=marker,
        sessions_root=sessions_root,
    )
    if transcript is None:
        return "no-transcript"
    model = _session_model(transcript)
    if model is None:
        stored_model = marker.get("model")
        model = stored_model.strip() if isinstance(stored_model, str) else None
    if not model:
        return "no-model"
    return _capture_bound_usage(
        marker_path,
        marker,
        transcript,
        model,
        captured_at,
        transition=next_task,
    )


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
        transcript_value = payload.get("transcript_path")
        model = payload.get("model")
        if not isinstance(transcript_value, str) or not isinstance(model, str) or not model.strip():
            return "invalid"
        transcript = Path(transcript_value).resolve()
        if not _transcript_matches_session(transcript, session):
            return "mismatch"
        return _capture_bound_usage(
            marker_path,
            marker,
            transcript,
            model,
            now or _now(),
        )
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
    captured_at: datetime | None = None,
    transcript_path: Path | None = None,
    sessions_root: Path | None = None,
) -> bool:
    """Checkpoint the closing task, falling back to the next Stop when needed."""
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
        ):
            return False
        if marker.get("task_id") != task_id:
            pending = marker.get("pending_transition")
            if isinstance(pending, dict) and pending.get("next_task") == task_id:
                raise ValueError(
                    f"Lead metrics transition {marker.get('task_id')} -> {task_id} "
                    "is still waiting for a Stop checkpoint; end the current turn "
                    "before closing another task"
                )
            raise ValueError(
                f"Lead metrics are bound to {marker.get('task_id')!r}, not {task_id!r}; "
                "rebind the top-level Lead session before closing this task"
            )
        reason = _checkpoint_transition(
            path,
            marker,
            next_task,
            captured_at=captured_at or _now(),
            transcript_path=transcript_path,
            sessions_root=sessions_root,
        )
        if reason == "captured":
            return True
        existing_pending = marker.get("pending_transition")
        expected_pending = {"from_task": task_id, "next_task": next_task}
        if existing_pending is not None and existing_pending != expected_pending:
            raise ValueError(
                f"Lead metrics already have an unresolved transition: {existing_pending!r}"
            )
        marker["pending_transition"] = {"from_task": task_id, "next_task": next_task}
        atomic_write_json(path, marker)
        return True
    except (OSError, TypeError, AttributeError, json.JSONDecodeError):
        return False


def clear_delivered_project_bindings(
    project_value: str | Path,
    *,
    lead_root: Path | None = None,
) -> list[Path]:
    """Remove stale bindings only for a canonically delivered project."""
    project = Path(project_value).resolve()
    if not project.is_dir():
        raise ValueError(f"project path does not exist: {project}")
    state_path = project / "PROJECT_STATE.md"
    try:
        state = state_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read canonical project state: {state_path}") from exc
    values: dict[str, str] = {}
    for line in state.splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        values[key.strip()] = value.strip()
    if values.get("Status") != "DELIVERED" or values.get("Active Task") != "None":
        raise ValueError(
            "refusing to clear Lead bindings unless PROJECT_STATE.md has "
            "Status: DELIVERED and Active Task: None"
        )

    root = (lead_root or TOOLKIT_ROOT).resolve()
    sessions_dir = root / ".codexteam" / "runtime" / "lead-sessions"
    removed: list[Path] = []
    if not sessions_dir.is_dir():
        return removed
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(marker, dict) and marker.get("project") == str(project):
            path.unlink()
            removed.append(path)
    return removed


def create_lead_checkpoint(
    project_value: str | Path,
    *,
    generated_at: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a compact runtime-only handoff for starting a fresh Lead session."""
    project = Path(project_value).resolve()
    if not project.is_dir():
        raise ValueError(f"project path does not exist: {project}")

    state = _read_bullets(project / "PROJECT_STATE.md")
    current = _read_bullets(project / "CURRENT_TASK.md")
    try:
        tasks = parse_task_document((project / "TASKS.md").read_text(encoding="utf-8"))
    except (OSError, TaskDocumentError) as exc:
        raise ValueError(f"cannot read canonical task ledger: {exc}") from exc

    task_value = current.get("Task ID") or state.get("Active Task")
    task_id = task_value if isinstance(task_value, str) and TASK_ID_RE.fullmatch(task_value) else None
    if task_id is None:
        verified = state.get("Last Verified Task")
        if isinstance(verified, str) and TASK_ID_RE.fullmatch(verified):
            task_id = verified
    task_record: dict[str, Any] | None = None
    if task_id is not None:
        try:
            row = tasks.row(task_id)
        except TaskDocumentError:
            row = None
        if row is not None:
            task_record = {
                "task_id": row.task_id,
                "description": row.description,
                "status": row.status,
                "owner": row.owner,
                "verification": row.verification,
                "evidence": row.evidence,
            }

    gate = _checkpoint_gate(project)
    refs = ["PROJECT_STATE.md", "CURRENT_TASK.md", "TASKS.md"]
    if task_record is not None and task_record["status"] != "Completed":
        handoff = f"management/tasks/{task_record['task_id']}.md"
        if (project / handoff).is_file():
            refs.append(handoff)

    checkpoint = {
        "schema_version": "1.0",
        "kind": "lead_milestone_checkpoint",
        "generated_at": (generated_at or _now()).isoformat().replace("+00:00", "Z"),
        "project_root": str(project),
        "project_state": {
            key: state.get(key)
            for key in (
                "Phase",
                "Status",
                "Active Task",
                "Active Milestone",
                "Last Completed Milestone",
                "Last Verified Task",
                "Next Action",
                "Updated At",
            )
            if state.get(key) is not None
        },
        "current_task": {
            key: current.get(key)
            for key in (
                "Task ID",
                "Status",
                "Milestone",
                "Responsible AI",
                "Objective",
                "Handoff",
                "Evidence",
                "Next Action",
            )
            if current.get(key) is not None
        },
        "task_record": task_record,
        "integration_gate": gate,
        "canonical_refs": refs,
        "usage_note": (
            "Start a fresh Lead session from these references; this checkpoint is context, "
            "not acceptance evidence."
        ),
    }
    path = contained_path(
        project,
        ".codexteam/runtime/lead-checkpoint.json",
        label="Lead checkpoint",
    )
    if path.is_symlink():
        raise ValueError(f"Lead checkpoint path cannot be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, checkpoint)
    return path, checkpoint


def _read_bullets(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read canonical project state: {path}") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _checkpoint_gate(project: Path) -> dict[str, Any] | None:
    path = project / "results" / "gates" / "integration.json"
    try:
        record = validate_current_gate_record(project, "integration")
        current = True
        freshness_error = None
    except (FileNotFoundError, GateConfigError, OSError, ValueError) as exc:
        current = False
        freshness_error = str(exc)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
    if not isinstance(record, dict):
        return None
    return {
        "artifact_ref": "results/gates/integration.json",
        "status": record.get("status"),
        "current": current,
        "freshness_error": freshness_error,
        "completed_at": record.get("completed_at"),
        "workspace_digest": record.get("workspace_digest"),
        "configuration_digest": record.get("configuration_digest"),
        "execution_surface": record.get("execution_surface"),
    }
