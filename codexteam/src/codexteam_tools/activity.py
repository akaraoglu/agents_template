from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .execution_registry import ExecutionRegistryError, load_execution_registry
from .delegation import DELEGATION_FILENAME, load_delegation
from .execution_spec import EXECUTION_SPEC_FILENAME, ExecutionSpecError, load_execution_spec
from .paths import PathValidationError, validate_identifier
from .tasks import TaskDocumentError, parse_task_document
from .turn_metrics import load_summary, metrics_path


TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
ATTENTION_STATUSES = {
    "blocked", "correction_needed", "interrupted", "process_failed", "stale",
    "timed_out", "turn_failed",
}
COMPLETED_STATUSES = {"completed", "finalized"}
OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_RESPONSE_LIMIT = 1024 * 1024


def collect_team_activity(
    projects_dir: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(projects_dir).resolve(strict=False)
    observed_at = now or datetime.now(timezone.utc)
    registry = _registry()
    attempts: list[dict[str, Any]] = []
    if root.is_dir():
        for project in sorted(root.iterdir()):
            if not project.is_dir() or project.is_symlink():
                continue
            try:
                validate_identifier(project.name, label="project ID")
            except PathValidationError:
                continue
            sessions = project / ".codexteam" / "runtime" / "sessions"
            if not sessions.is_dir() or sessions.is_symlink():
                continue
            task_meta = _task_metadata(project)
            for attempt_dir in sorted(sessions.glob("*/*/*")):
                if _safe_attempt_dir(sessions, attempt_dir):
                    attempt = _attempt(project, attempt_dir, observed_at, registry, task_meta)
                    if attempt is not None:
                        attempts.append(attempt)

    attempts.sort(
        key=lambda item: (
            _status_rank(item["display_status"]),
            _timestamp(item["updated_at"]),
            item["project_id"], item["task_id"], item["attempt_id"],
        ),
        reverse=True,
    )
    counts = {
        "total": len(attempts),
        "running": sum(item["display_status"] == "running" for item in attempts),
        "attention": sum(item["group"] == "needs_attention" for item in attempts),
        "waiting": sum(item["group"] == "waiting" for item in attempts),
        "completed": sum(item["group"] == "completed" for item in attempts),
    }
    return {
        "attempts": attempts,
        "counts": counts,
        "observed_at": observed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "hidden_completed": 0,
        "filters": {
            "projects": sorted({item["project_id"] for item in attempts}),
            "statuses": sorted({item["display_status"] for item in attempts}),
            "roles": sorted({item["role"] for item in attempts}),
            "backends": sorted({item["backend"] for item in attempts}),
            "models": sorted({item["model"] for item in attempts}),
            "agent_specs": sorted({item["agent_spec"] for item in attempts if item["agent_spec"]}),
        },
        "delegations": _delegation_groups(attempts),
    }


def collect_model_fleet(*, timeout_seconds: float = 1.0) -> dict[str, Any]:
    registry = _registry()
    if registry is None:
        return {"available": False, "error": "registry_unavailable", "models": []}
    try:
        tags = _ollama_json("/api/tags", timeout_seconds)
        running = _ollama_json("/api/ps", timeout_seconds)
    except (OSError, ValueError, urllib.error.URLError):
        return {"available": False, "error": "ollama_unavailable", "models": []}
    installed = {
        item.get("name"): item
        for item in tags.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    loaded = {
        item.get("name"): item
        for item in running.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    profiles_by_model: dict[str, list[str]] = {}
    locators: dict[str, set[str]] = {}
    for profile in registry.profiles.values():
        if profile.get("provider") != "ollama":
            continue
        model_id = profile["model_id"]
        profiles_by_model.setdefault(model_id, []).append(
            f"{profile['backend_id']}/{profile['profile_id']}"
        )
        locators.setdefault(model_id, set()).add(profile["provider_locator"].removeprefix("ollama/"))
    models = []
    for model_id in sorted(profiles_by_model):
        definition = registry.models[model_id]
        names = locators[model_id]
        installed_record = next((installed[name] for name in names if name in installed), None)
        loaded_record = next((loaded[name] for name in names if name in loaded), None)
        models.append({
            "model_id": model_id,
            "display_name": definition["display_name"],
            "provider_locators": sorted(f"ollama/{name}" for name in names),
            "profiles": sorted(profiles_by_model[model_id]),
            "installed": installed_record is not None,
            "loaded": loaded_record is not None,
            "size_bytes": _integer((loaded_record or installed_record or {}).get("size")),
            "context_length": _integer((loaded_record or {}).get("context_length")),
            "expires_at": (loaded_record or {}).get("expires_at"),
            "processor": _processor(loaded_record),
            "curated_context_limit": definition.get("context_limit"),
            "curated_output_limit": definition.get("output_limit"),
        })
    return {"available": True, "error": None, "models": models}


def filter_team_activity(
    attempts: list[dict[str, Any]],
    *,
    project: str = "",
    status: str = "",
    role: str = "",
    backend: str = "",
    model: str = "",
    agent_spec: str = "",
    active_only: bool = False,
) -> list[dict[str, Any]]:
    filters = {
        "project_id": project,
        "display_status": status,
        "role": role,
        "backend": backend,
        "model": model,
        "agent_spec": agent_spec,
    }
    return [
        item for item in attempts
        if all(not value or item[field] == value for field, value in filters.items())
        and (not active_only or item["display_status"] in {"running", "stale"})
    ]


def build_task_activity(
    attempts: list[dict[str, Any]],
    *,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for attempt in attempts:
        grouped.setdefault((attempt["project_id"], attempt["task_id"]), []).append(attempt)
    tasks: list[dict[str, Any]] = []
    for (project_id, task_id), history in grouped.items():
        history.sort(key=lambda item: _timestamp(item["updated_at"]), reverse=True)
        current = next(
            (item for item in history if item["display_status"] == "running"),
            history[0],
        )
        ordered_history = [current, *(item for item in history if item is not current)]
        canonical_complete = _canonical_task_complete(current.get("task_status"))
        if canonical_complete and not include_history and current["display_status"] != "running":
            continue
        severity = _severity(current)
        if severity == "complete" and not canonical_complete:
            severity = "normal"
        alerts = {
            "errors": current["error_count"],
            "failed_tools": current["failed_tool_calls"],
            "context_warning": current["context_warning"],
            "spec_invalid": current["execution_spec_status"] != "valid",
            "delegation_invalid": current["delegation_status"] == "invalid",
        }
        tasks.append({
            "task_key": f"{project_id}/{task_id}",
            "project_id": project_id,
            "project_name": current["project_name"],
            "task_id": task_id,
            "task_status": current.get("task_status") or "unknown",
            "objective": current.get("task_objective") or task_id,
            "current_attempt": current,
            "prior_attempt_count": max(0, len(history) - 1),
            "attempts": ordered_history,
            "severity": severity,
            "last_activity_at": current["updated_at"],
            "alerts": alerts,
        })
    tasks.sort(
        key=lambda item: (
            _severity_rank(item["severity"]),
            _timestamp(item["last_activity_at"]),
            item["project_id"], item["task_id"],
        ),
        reverse=True,
    )
    return tasks


def filter_task_activity(
    tasks: list[dict[str, Any]],
    *,
    project: str = "",
    state: str = "active",
    query: str = "",
    role: str = "",
    backend: str = "",
    model: str = "",
    agent_spec: str = "",
) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    selected: list[dict[str, Any]] = []
    for task in tasks:
        attempt = task["current_attempt"]
        canonical_complete = _canonical_task_complete(task.get("task_status"))
        if project and task["project_id"] != project:
            continue
        if role and attempt["role"] != role:
            continue
        if backend and attempt["backend"] != backend:
            continue
        if model and attempt["model"] != model:
            continue
        if agent_spec and attempt["agent_spec"] != agent_spec:
            continue
        if state == "attention" and task["severity"] not in {"critical", "warning"}:
            continue
        if state == "running" and attempt["display_status"] != "running":
            continue
        if state == "waiting" and (
            canonical_complete
            or attempt["display_status"] == "running"
            or task["severity"] in {"critical", "warning"}
        ):
            continue
        if state == "completed" and not canonical_complete:
            continue
        if state == "active" and canonical_complete:
            continue
        if needle and needle not in " ".join((
            task["project_id"], task["project_name"], task["task_id"],
            task["objective"], attempt["attempt_id"], attempt["role"],
        )).lower():
            continue
        selected.append(task)
    return selected


def task_activity_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "visible": len(tasks),
        "running": sum(item["current_attempt"]["display_status"] == "running" for item in tasks),
        "attention": sum(item["severity"] in {"critical", "warning"} for item in tasks),
        "waiting": sum(
            not _canonical_task_complete(item.get("task_status"))
            and item["current_attempt"]["display_status"] != "running"
            and item["severity"] not in {"critical", "warning"}
            for item in tasks
        ),
    }


def group_delegations(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _delegation_groups(attempts)


def attach_fleet_activity(
    fleet: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    if not fleet.get("available") or not isinstance(fleet.get("models"), list):
        return fleet
    for model in fleet["models"]:
        if not isinstance(model, dict):
            continue
        matching = [item for item in attempts if item.get("model") == model.get("model_id")]
        model["assigned_attempts"] = len(matching)
        model["running_attempts"] = sum(item.get("display_status") == "running" for item in matching)
    return fleet


def _attempt(
    project: Path,
    attempt_dir: Path,
    now: datetime,
    registry: Any | None,
    task_meta: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    session = _object(attempt_dir / "session.json")
    state = _object(attempt_dir / "turn-state.json")
    if not session and not state and not (attempt_dir / EXECUTION_SPEC_FILENAME).exists():
        return None
    spec_status = "valid"
    spec_error: str | None = None
    try:
        spec = load_execution_spec(attempt_dir / EXECUTION_SPEC_FILENAME)
    except (ExecutionSpecError, OSError) as exc:
        spec = {}
        spec_status = "invalid" if (attempt_dir / EXECUTION_SPEC_FILENAME).exists() else "absent"
        spec_error = exc.__class__.__name__

    merged = {**session, **state}
    identity = spec.get("identity", {})
    execution = spec.get("execution_profile", {})
    model_record = execution.get("model", {})
    profile_record = execution.get("profile", {})
    backend_record = execution.get("backend", {})
    reasoning = execution.get("reasoning", {})
    permissions = spec.get("permissions", {})
    role_policy = spec.get("role_policy", {})
    task_id = str(identity.get("task_id") or merged.get("task_id") or attempt_dir.parent.name)
    attempt_id = str(identity.get("attempt_id") or merged.get("attempt_id") or attempt_dir.name)
    try:
        validate_identifier(attempt_id, label="attempt ID")
    except PathValidationError:
        return None

    status = str(state.get("status") or session.get("last_status") or "unknown")
    if status == "running":
        status = _running_status(state, now)
    group = _group(status)
    turns = _turns(attempt_dir / "turns")
    latest_metrics = next((turn for turn in reversed(turns) if turn["metrics_available"]), None)
    usage = latest_metrics.get("usage", {}) if latest_metrics else {}
    model_display, context_limit, output_limit = _model_info(
        registry,
        model_record.get("id"),
        execution.get("registry_digest"),
        model_record.get("definition_digest"),
    )
    latest_input = latest_metrics.get("max_step_input_tokens") if latest_metrics else None
    context_percent = (
        round(100 * latest_input / context_limit, 1)
        if isinstance(latest_input, int) and context_limit else None
    )
    tool_calls = sum(turn["tool_calls"] or 0 for turn in turns)
    failed_tools = sum(turn["failed_tool_calls"] or 0 for turn in turns)
    mcp_calls = sum(turn["mcp_calls"] or 0 for turn in turns)
    updated_at = str(
        state.get("updated_at") or session.get("updated_at") or
        (latest_metrics.get("generated_at") if latest_metrics else "") or ""
    )
    started_at = str(state.get("started_at") or session.get("created_at") or "")
    return {
        "project_id": project.name,
        "project_name": _project_name(project),
        "task_id": task_id,
        "task_status": task_meta.get(task_id, {}).get("status", "unknown"),
        "task_objective": task_meta.get(task_id, {}).get("objective", task_id),
        "attempt_id": attempt_id,
        "team_id": str(identity.get("team_id") or merged.get("team_id") or attempt_dir.parents[1].name),
        "role": str(identity.get("role") or merged.get("agent_role") or "unknown"),
        "agent_spec": (
            str(spec["agent_spec"]["id"])
            if isinstance(spec.get("agent_spec"), dict) else None
        ),
        "backend": str(backend_record.get("id") or state.get("execution_backend") or "unknown"),
        "backend_version": backend_record.get("runtime_version") or state.get("backend_version"),
        "model": str(model_record.get("id") or "unknown"),
        "model_display": model_display or str(model_record.get("id") or "unknown"),
        "provider": str(model_record.get("provider") or "unknown"),
        "provider_locator": str(model_record.get("provider_locator") or "unknown"),
        "profile": str(profile_record.get("id") or "unknown"),
        "reasoning_requested": reasoning.get("requested"),
        "reasoning_effective": reasoning.get("effective"),
        "reasoning_status": reasoning.get("support_status"),
        "phase": str(state.get("phase") or session.get("last_phase") or "unknown"),
        "turn_number": state.get("turn_number") or session.get("turn_count") or 0,
        "display_status": status,
        "group": group,
        "started_at": started_at,
        "updated_at": updated_at,
        "elapsed_seconds": _elapsed(started_at, updated_at, now, status == "running"),
        "execution_spec_status": spec_status,
        "execution_spec_error": spec_error,
        "execution_spec_digest": spec.get("execution_spec_digest"),
        "role_policy": role_policy.get("name"),
        "sandbox_mode": permissions.get("sandbox_mode"),
        "task_write_scope": permissions.get("task_write_scope"),
        "additional_write_roots": permissions.get("additional_write_roots", []),
        "mcp_effective_servers": permissions.get("mcp_effective_servers", []),
        "mcp_effective_tools": permissions.get("mcp_effective_tools", {}),
        "gate_routing": spec.get("gate_routing"),
        "changed_paths": state.get("changed_paths", []),
        "error_count": len(state.get("errors", [])) if isinstance(state.get("errors"), list) else 0,
        "turns": turns,
        "turn_count": len(turns) or int(session.get("turn_count") or 0),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "tool_calls": tool_calls,
        "failed_tool_calls": failed_tools,
        "mcp_calls": mcp_calls,
        "context_limit": context_limit,
        "output_limit": output_limit,
        "context_percent": context_percent,
        "context_warning": context_percent is not None and context_percent >= 80,
        "timeline": _timeline(project, task_id, attempt_id, turns),
        **_delegation(attempt_dir, identity, merged, project),
    }


def _turns(turns_dir: Path) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    if not turns_dir.is_dir() or turns_dir.is_symlink():
        return turns
    for event_path in sorted(turns_dir.iterdir()):
        match = TURN_FILE.match(event_path.name)
        if not match or not event_path.is_file() or event_path.is_symlink():
            continue
        metrics = load_summary(metrics_path(event_path))
        if metrics is None:
            turns.append({
                "number": int(match.group(1)), "phase": match.group(2),
                "status": "unreported", "metrics_available": False,
                "duration_seconds": None, "terminal_reason": None,
                "input_tokens": None, "output_tokens": None,
                "tool_calls": None, "failed_tool_calls": None, "mcp_calls": None,
                "usage": {}, "generated_at": None, "diagnostics": {},
            })
            continue
        turn = metrics.get("turn")
        metric_usage = metrics.get("usage")
        activity = metrics.get("activity")
        events = metrics.get("events")
        if not all(isinstance(value, dict) for value in (turn, metric_usage, activity, events)):
            continue
        assert isinstance(turn, dict)
        assert isinstance(metric_usage, dict)
        assert isinstance(activity, dict)
        assert isinstance(events, dict)
        usage = metric_usage.get("cumulative")
        mcp = activity.get("mcp")
        backend_usage = metrics.get("backend_usage")
        if not isinstance(usage, dict) or not isinstance(mcp, dict):
            continue
        max_step_input = (
            _number(backend_usage.get("max_step_input_tokens"))
            if isinstance(backend_usage, dict) else None
        )
        turns.append({
            "number": int(match.group(1)),
            "phase": str(turn.get("phase") or match.group(2)),
            "status": "completed" if turn.get("completed") else "incomplete",
            "metrics_available": True,
            "duration_seconds": _number(turn.get("duration_seconds")),
            "terminal_reason": turn.get("terminal_reason"),
            "input_tokens": _integer(usage.get("input_tokens")),
            "output_tokens": _integer(usage.get("output_tokens")),
            "max_step_input_tokens": _integer(max_step_input),
            "tool_calls": _integer(activity.get("tool_calls")),
            "failed_tool_calls": _integer(activity.get("failed_tool_calls")),
            "mcp_calls": _integer(mcp.get("calls")),
            "usage": {
                "input_tokens": _integer(usage.get("input_tokens")),
                "output_tokens": _integer(usage.get("output_tokens")),
                "cached_input_tokens": _integer(usage.get("cached_input_tokens")),
            },
            "generated_at": metrics.get("generated_at"),
            "diagnostics": events.get("diagnostics", {}) if isinstance(events.get("diagnostics"), dict) else {},
        })
    return turns


def _model_info(
    registry: Any | None,
    model_id: Any,
    registry_digest: Any,
    model_digest: Any,
) -> tuple[str | None, int | None, int | None]:
    if registry is None or not isinstance(model_id, str):
        return None, None, None
    model = registry.models.get(model_id)
    if not isinstance(model, dict):
        return None, None, None
    if registry_digest != registry.digest or model_digest != _digest(model):
        return None, None, None
    context = model.get("context_limit")
    output = model.get("output_limit")
    return (
        model.get("display_name") if isinstance(model.get("display_name"), str) else None,
        context if isinstance(context, int) else None,
        output if isinstance(output, int) else None,
    )


def _registry() -> Any | None:
    try:
        return load_execution_registry()
    except (ExecutionRegistryError, OSError):
        return None


def _timeline(
    project: Path,
    task_id: str,
    attempt_id: str,
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events = [
        {
            "kind": "turn", "occurred_at": turn.get("generated_at"),
            "status": turn["status"], "label": f"Turn {turn['number']} · {turn['phase']}",
            "duration_seconds": turn.get("duration_seconds"),
            "tokens": {
                "input": turn.get("input_tokens"), "output": turn.get("output_tokens"),
            },
            "artifact_ref": None,
        }
        for turn in turns
    ]
    accepted = project / "results/gates/accepted"
    if accepted.is_dir() and not accepted.is_symlink():
        for path in accepted.glob(f"{task_id}-{attempt_id}-*.json"):
            value = _object(path)
            if (
                value.get("kind") == "accepted_gate_snapshot"
                and value.get("task_id") == task_id
                and value.get("attempt_id") == attempt_id
                and _valid_gate_snapshot(path, value)
            ):
                record_value = value.get("record")
                record = record_value if isinstance(record_value, dict) else {}
                events.append({
                    "kind": "gate", "occurred_at": record.get("completed_at"),
                    "status": str(record.get("status") or "unknown"),
                    "label": f"{str(value.get('gate') or 'gate').title()} Gate",
                    "duration_seconds": _number(record.get("duration_seconds")),
                    "tokens": None,
                    "artifact_ref": path.relative_to(project).as_posix(),
                })
    verification = project / f"results/{task_id}-verification.txt"
    verified_at = _verified_at(verification)
    if verified_at and _verification_matches_attempt(
        project, task_id, attempt_id, verification.relative_to(project).as_posix()
    ):
        events.append({
            "kind": "closure", "occurred_at": verified_at, "status": "verified",
            "label": "Independent closure", "duration_seconds": None, "tokens": None,
            "artifact_ref": verification.relative_to(project).as_posix(),
        })
    events.sort(key=lambda item: _timestamp(item.get("occurred_at")))
    return events


def _delegation(
    attempt_dir: Path,
    identity: dict[str, Any],
    merged: dict[str, Any],
    project: Path,
) -> dict[str, Any]:
    path = attempt_dir / DELEGATION_FILENAME
    if not path.exists() and not path.is_symlink():
        return {"delegation_status": "legacy", "parent_session_id": None,
                "delegation_reason": "record_absent"}
    expected = {
        "team_id": str(identity.get("team_id") or merged.get("team_id") or attempt_dir.parents[1].name),
        "task_id": str(identity.get("task_id") or merged.get("task_id") or attempt_dir.parent.name),
        "attempt_id": str(identity.get("attempt_id") or merged.get("attempt_id") or attempt_dir.name),
        "agent_role": str(identity.get("role") or merged.get("agent_role") or "unknown"),
        "workspace_root": str(project),
    }
    try:
        value = load_delegation(path, expected_child=expected)
    except ValueError:
        return {"delegation_status": "invalid", "parent_session_id": None,
                "delegation_reason": "record_invalid"}
    if value["attribution"] == "orphan":
        return {"delegation_status": "orphan", "parent_session_id": None,
                "delegation_reason": value.get("orphan_reason")}
    return {
        "delegation_status": "bound_lead",
        "parent_session_id": value["parent"]["session_id"],
        "parent_task_id": value["parent"].get("task_id_at_launch"),
        "delegation_reason": None,
    }


def _delegation_groups(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    orphans: list[dict[str, Any]] = []
    for attempt in attempts:
        parent = attempt.get("parent_session_id")
        if attempt.get("delegation_status") == "bound_lead" and isinstance(parent, str):
            grouped.setdefault(parent, []).append(attempt)
        else:
            orphans.append(attempt)
    roots = [
        {"session_id": session, "short_session_id": session[:12], "children": children,
         "historical": not _lead_marker_exists(session)}
        for session, children in sorted(grouped.items())
    ]
    if orphans:
        roots.append({"session_id": None, "short_session_id": "Orphan attempts",
                      "children": orphans, "historical": False})
    return roots


def _valid_gate_snapshot(path: Path, value: dict[str, Any]) -> bool:
    if value.get("schema_version") != "1.0" or value.get("gate") not in {"development", "integration"}:
        return False
    record = value.get("record")
    expected = value.get("record_sha256")
    if not isinstance(record, dict) or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        return False
    actual = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        return False
    prefix = f"{value['task_id']}-{value['attempt_id']}-{value['gate']}-{expected[:16]}.json"
    return path.name == prefix


def _lead_marker_exists(session_id: str) -> bool:
    root = Path(__file__).resolve().parents[2]
    path = root / ".codexteam/runtime/lead-sessions" / f"{session_id}.json"
    return path.is_file() and not path.is_symlink()


def _ollama_json(path: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(OLLAMA_BASE + path)
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if not response.geturl().startswith(OLLAMA_BASE + "/"):
            raise ValueError("Ollama redirected outside loopback")
        content = response.read(OLLAMA_RESPONSE_LIMIT + 1)
    if len(content) > OLLAMA_RESPONSE_LIMIT:
        raise ValueError("Ollama response is too large")
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Ollama response must be an object")
    return value


def _processor(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    size = _integer(record.get("size"))
    vram = _integer(record.get("size_vram"))
    if size is None or vram is None or size == 0:
        return None
    if vram >= size * .95:
        return "GPU"
    if vram == 0:
        return "CPU"
    return "CPU/GPU"


def _verified_at(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"^Verified at:\s*(\S+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else None


def _verification_matches_attempt(
    project: Path,
    task_id: str,
    attempt_id: str,
    verification_ref: str,
) -> bool:
    tasks_path = project / "TASKS.md"
    if tasks_path.is_symlink() or not tasks_path.is_file():
        return False
    try:
        row = parse_task_document(tasks_path.read_text(encoding="utf-8")).row(task_id)
    except (OSError, UnicodeDecodeError, TaskDocumentError, ValueError):
        return False
    result_ref = f"results/{task_id}-{attempt_id}.json"
    return result_ref in row.evidence and verification_ref in row.evidence


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_attempt_dir(sessions: Path, attempt: Path) -> bool:
    if attempt.is_symlink() or not attempt.is_dir():
        return False
    try:
        relative = attempt.relative_to(sessions)
    except ValueError:
        return False
    if len(relative.parts) != 3:
        return False
    current = sessions
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        attempt.resolve().relative_to(sessions.resolve())
    except (OSError, ValueError):
        return False
    return True


def _digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _project_name(project: Path) -> str:
    path = project / "PROJECT.md"
    if path.is_symlink() or not path.is_file():
        return project.name
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return project.name
    return first.removeprefix("# ").strip() or project.name


def _running_status(state: dict[str, Any], now: datetime) -> str:
    updated = _parse_time(state.get("updated_at") or state.get("started_at"))
    timeout = state.get("timeout_seconds")
    if updated is None or not isinstance(timeout, int) or timeout < 1:
        return "running"
    grace = max(30, min(timeout, 300))
    return "stale" if now > updated + timedelta(seconds=timeout + grace) else "running"


def _group(status: str) -> str:
    lowered = status.lower()
    if lowered == "running":
        return "running"
    if lowered in ATTENTION_STATUSES:
        return "needs_attention"
    if lowered in COMPLETED_STATUSES:
        return "completed"
    return "waiting"


def _status_rank(status: str) -> int:
    return {"running": 4, "stale": 3}.get(status, 2 if status in ATTENTION_STATUSES else 1)


def _severity(attempt: dict[str, Any]) -> str:
    status = attempt["display_status"]
    if status in {"blocked", "process_failed", "timed_out", "turn_failed"}:
        return "critical"
    if status in {"correction_needed", "interrupted", "stale"}:
        return "warning"
    if status == "running":
        return "running"
    if attempt["group"] == "completed":
        return "complete"
    return "normal"


def _severity_rank(severity: str) -> int:
    return {"critical": 5, "warning": 4, "running": 3, "normal": 2, "complete": 1}.get(severity, 0)


def _canonical_task_complete(status: Any) -> bool:
    if not isinstance(status, str):
        return False
    normalized = status.strip().lower()
    return any(normalized == value or normalized.startswith(f"{value} ") for value in (
        "completed", "complete", "done",
    ))


def _task_metadata(project: Path) -> dict[str, dict[str, str]]:
    path = project / "TASKS.md"
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    metadata: dict[str, dict[str, str]] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if len(cells) < 3 or not re.fullmatch(r"T[0-9]{3,6}", cells[0]):
            continue
        metadata[cells[0]] = {"objective": cells[1], "status": cells[2]}
    return metadata


def _elapsed(start: str, updated: str, now: datetime, running: bool) -> float | None:
    started = _parse_time(start)
    ended = now if running else _parse_time(updated)
    if started is None or ended is None or ended < started:
        return None
    return round((ended - started).total_seconds(), 3)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _timestamp(value: Any) -> float:
    parsed = _parse_time(value)
    return parsed.timestamp() if parsed else 0.0
