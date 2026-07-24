from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, render_template

from .paths import PathValidationError, contained_path, normalize_task_id, validate_identifier
from .tasks import TaskDocumentError, TaskRow, parse_task_document
from .turn_metrics import load_summary, metrics_path


CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = CODEXTEAM_ROOT / "projects"
UNKNOWN = "unknown"
VERDICTS = ("Lifecycle", "Product", "Evidence", "Management", "Manifest", "Performance")
TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
FAILED_TURN_STATUSES = {"turn_failed", "process_failed", "timed_out", "interrupted", "correction_needed"}
COMPLETED_TASK_STATUSES = {"completed", "complete", "done"}
ACTIVE_PHASES = {"draft", "feedback", "final"}
_BOARD_COLUMNS = ("Backlog", "In Progress", "In Review", "In Validation", "Blocked", "Done")
COMPLETED_PROJECT_STATUSES = {"complete", "completed", "delivered", "done"}
PHASES = ("draft", "feedback", "final", "verify", "closed")


def list_projects(projects_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(projects_dir).resolve(strict=False)
    if not root.is_dir():
        return []
    projects = []
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            validate_identifier(path.name, label="project ID")
            projects.append(load_project(root, path.name))
        except (OSError, ValueError):
            continue
    projects.sort(key=lambda item: item["id"])
    projects.sort(
        key=lambda item: (
            _timestamp_value(item["updated_at"]),
            item["status"].lower() not in COMPLETED_PROJECT_STATUSES,
        ),
        reverse=True,
    )
    return projects


def load_project(projects_dir: str | Path, project_id: str) -> dict[str, Any]:
    root = Path(projects_dir).resolve(strict=False)
    project_id = validate_identifier(project_id, label="project ID")
    unresolved = root / project_id
    if unresolved.is_symlink():
        raise PathValidationError("project path cannot be a symlink")
    project = contained_path(root, project_id, label="project ID")
    if not project.is_dir():
        raise FileNotFoundError(project)

    state = _bullets(project / "PROJECT_STATE.md")
    report = _bullets(project / "results" / "e2e-report.md")
    rows = _task_rows(project / "TASKS.md")
    milestone_commits = _milestone_commits(project)

    sessions: dict[str, list[dict[str, Any]]] = {}
    session_root = project / ".codexteam" / "runtime" / "sessions"
    if session_root.is_dir():
        for path in session_root.rglob("session.json"):
            session = _session(project, path)
            if session:
                sessions.setdefault(session["task_id"], []).append(session)

    tasks = []
    known_task_ids = {row.task_id for row in rows} | set(sessions)
    rows_by_id = {row.task_id: row for row in rows}
    for task_id in sorted(known_task_ids):
        row = rows_by_id.get(task_id)
        attempts = sorted(sessions.get(task_id, []), key=lambda item: _timestamp_value(item["updated_at"]))
        latest = attempts[-1] if attempts else {}
        durations = [item["duration_seconds"] for item in attempts if item["duration_seconds"] is not None]
        objective = row.description if row else UNKNOWN
        milestone_id, display_objective = _task_presentation(objective)
        task = {
            "id": task_id,
            "objective": objective,
            "display_objective": display_objective,
            "milestone_id": milestone_id,
            "owner": row.owner if row and row.owner else UNKNOWN,
            "status": row.status if row else latest.get("status", UNKNOWN),
            "verification": row.verification if row and row.verification else UNKNOWN,
            "profile": latest.get("profile", UNKNOWN),
            "provider": latest.get("provider", UNKNOWN),
            "role": latest.get("role", UNKNOWN),
            "phase": latest.get("phase", UNKNOWN),
            "attempt": latest.get("attempt", UNKNOWN),
            "updated_at": latest.get("updated_at") or UNKNOWN,
            "turns": sum(item["turns"] for item in attempts),
            "corrections": sum(item["corrections"] for item in attempts),
            "failed_turns": sum(item["failed_turns"] for item in attempts),
            "duration_seconds": round(sum(durations), 3) if durations else None,
            "cloud_tokens": _total_tokens(attempts, "cloud_tokens") if attempts else 0,
            "local_tokens": _total_tokens(attempts, "local_tokens") if attempts else 0,
            "cloud_input_tokens": _total_tokens(attempts, "cloud_input_tokens") if attempts else 0,
            "cloud_output_tokens": _total_tokens(attempts, "cloud_output_tokens") if attempts else 0,
            "local_input_tokens": _total_tokens(attempts, "local_input_tokens") if attempts else 0,
            "local_output_tokens": _total_tokens(attempts, "local_output_tokens") if attempts else 0,
            "cached_tokens": _total_tokens(attempts, "cached_tokens") if attempts else 0,
            "error": latest.get("error", UNKNOWN),
            "diagnostic_path": latest.get("diagnostic_path", UNKNOWN),
            "attempts": list(reversed(attempts)),
        }
        task["needs_attention"] = task["status"] == "Blocked" or (
            task["status"] != "Completed" and task["failed_turns"] > 0
        )
        task["phases"] = _task_phases(task)
        tasks.append(task)

    tasks.sort(key=lambda item: item["id"])
    tasks.sort(key=lambda item: _timestamp_value(item["updated_at"]), reverse=True)
    expensive_drafts = _expensive_drafts(tasks)

    # --- Board column projection (T004) ---
    attention_count = 0
    open_count = 0
    for task in tasks:
        task["board_column"] = _board_column(task)
        status_lower = task["status"].lower()
        # board_attention: recoverable failures stay in progress lane with marker.
        # Also treat task-row recoverable statuses as attention even without sessions.
        is_recoverable_row = (
            status_lower not in COMPLETED_TASK_STATUSES
            and status_lower != "blocked"
            and (task["failed_turns"] > 0 or status_lower in FAILED_TURN_STATUSES)
        )
        task["board_attention"] = is_recoverable_row
        # Attention count includes canonical blocked tasks AND recoverable failures
        if task["board_column"] == "Blocked" or task["board_attention"]:
            attention_count += 1
        # Use COMPLETED_TASK_STATUSES for open vs completed distinction
        if status_lower not in COMPLETED_TASK_STATUSES:
            open_count += 1

    # Compact board groups (list of tasks per column)
    board_groups = {col: [] for col in _BOARD_COLUMNS}
    for task in tasks:
        col = task["board_column"]
        board_groups[col].append(task)
    # Sort within each lane by latest activity. Newer task IDs break ties for
    # planned tasks that do not have session timestamps yet.
    for col in _BOARD_COLUMNS:
        board_groups[col].sort(
            key=lambda task: (_timestamp_value(task["updated_at"]), int(task["id"][1:])),
            reverse=True,
        )

    # Compact card payload per task
    for task in tasks:
        task["card"] = _compact_card(task)

    timestamps = [item[key] for group in sessions.values() for item in group for key in ("created_at", "updated_at")]
    timestamps = [value for value in timestamps if value]
    started = min((item["created_at"] for group in sessions.values() for item in group if item["created_at"]), default=None)
    updated = _latest_timestamp([state.get("Updated At"), *timestamps]) or _latest_file_timestamp(
        project / "PROJECT.md",
        project / "PROJECT_STATE.md",
        project / "TASKS.md",
        project / "results" / "e2e-report.md",
    )
    elapsed = None if report.get("Profile") == "product-only" else _number(report.get("Elapsed seconds"))
    elapsed_source = "E2E report" if elapsed is not None else UNKNOWN
    if elapsed is None:
        elapsed = _elapsed_seconds(started, updated)
        if elapsed is not None:
            elapsed_source = "session timestamps"

    completed = sum(task["status"].lower() in COMPLETED_TASK_STATUSES for task in tasks)
    blocked = sum(task["status"].lower() == "blocked" for task in tasks)
    failed = sum(
        task["status"].lower() not in COMPLETED_TASK_STATUSES and task["failed_turns"] > 0
        for task in tasks
    )
    first_heading = _first_heading(project / "PROJECT.md")
    verdicts = {name.lower(): report.get(f"{name} verdict", UNKNOWN) for name in VERDICTS}
    attention_errors = [task for task in tasks if task["needs_attention"] and task["error"] != UNKNOWN]
    agents = []
    seen_agents = set()
    for task in tasks:
        agent_key = (task["role"], task["profile"], task["provider"])
        if task["role"] != UNKNOWN and agent_key not in seen_agents:
            seen_agents.add(agent_key)
            agents.append(
                {
                    "objective": task["display_objective"],
                    "milestone_id": task["milestone_id"],
                    "owner": task["owner"],
                    "role": task["role"],
                    "profile": task["profile"],
                    "provider": task["provider"],
                    "task_id": task["id"],
                    "phase": task["phase"],
                    "status": task["status"],
                }
            )
    agent_total = len(agents)
    agent_activity = _agent_activity(tasks)
    active_task = state.get("Active Task", UNKNOWN)
    active_task_details = next((task for task in tasks if task["id"] == active_task), None)
    agents = agents[:8]
    # Compact focus payload (T004)
    if active_task_details:
        focus_payload = {
            "task_id": active_task,
            "objective": active_task_details["display_objective"],
            "milestone_id": active_task_details["milestone_id"],
            "owner": active_task_details["owner"],
            "owner_label": _human_owner_label(active_task_details["owner"], active_task_details.get("role")),
            "role": active_task_details["role"],
            "profile": active_task_details["profile"],
            "stage": active_task_details["phase"],
            "last_activity": active_task_details["updated_at"],
        }
    else:
        focus_payload = {
            "task_id": active_task,
            "objective": None,
            "milestone_id": None,
            "owner": UNKNOWN,
            "owner_label": None,
            "role": UNKNOWN,
            "profile": UNKNOWN,
            "stage": UNKNOWN,
            "last_activity": UNKNOWN,
        }

    needs_attention = blocked > 0 or failed > 0 or str(state.get("Status", "")).lower() in {"blocked", "failed"}
    progress_percent = round(completed / len(tasks) * 100) if tasks else 0
    reported_error = report.get("Error")
    if reported_error:
        error = reported_error
        diagnostic_path = attention_errors[0]["diagnostic_path"] if attention_errors else UNKNOWN
    elif attention_errors:
        error = attention_errors[0]["error"]
        diagnostic_path = attention_errors[0]["diagnostic_path"]
    elif blocked:
        error = f"{blocked} blocked task{'s' if blocked != 1 else ''} require review"
        diagnostic_path = UNKNOWN
    else:
        error = diagnostic_path = UNKNOWN

    # Reported verdicts only (filter out unknown) — T004
    reported_verdicts = {name: val for name, val in verdicts.items() if val != UNKNOWN}

    # Portfolio group — T004
    portfolio_group = _portfolio_group(needs_attention, tasks, state)

    # Attention summary (short human label, no raw path) — T004
    attention_summary = _attention_summary(error, tasks)

    # Compact summary — T004
    project_summary = _compact_summary(
        completed, len(tasks), open_count, attention_count,
        tasks, elapsed,
    )

    return {
        "id": project_id,
        "name": first_heading or project_id,
        "status": state.get("Status", UNKNOWN),
        "active_task": active_task,
        "active_task_details": active_task_details,
        "started_at": started or UNKNOWN,
        "updated_at": updated or UNKNOWN,
        "elapsed_seconds": elapsed,
        "elapsed_source": elapsed_source,
        "tasks": tasks,
        "task_total": len(tasks),
        "task_completed": completed,
        "task_failed": failed,
        "task_blocked": blocked,
        "progress_percent": progress_percent,
        "portfolio_group": portfolio_group,
        "focus": focus_payload,
        "summary": project_summary,
        "board_groups": board_groups,
        "reported_verdicts": reported_verdicts,
        "has_all_verdicts_missing": all(v == UNKNOWN for v in verdicts.values()),
        "attention_summary": attention_summary,
        "needs_attention": needs_attention,
        "agents": agents,
        "agent_total": agent_total,
        "agent_activity": agent_activity,
        "turns": sum(task["turns"] for task in tasks),
        "corrections": sum(task["corrections"] for task in tasks),
        "failed_turns": sum(task["failed_turns"] for task in tasks),
        "cloud_tokens": _total_tokens(tasks, "cloud_tokens"),
        "local_tokens": _total_tokens(tasks, "local_tokens"),
        "cloud_input_tokens": _total_tokens(tasks, "cloud_input_tokens"),
        "cloud_output_tokens": _total_tokens(tasks, "cloud_output_tokens"),
        "local_input_tokens": _total_tokens(tasks, "local_input_tokens"),
        "local_output_tokens": _total_tokens(tasks, "local_output_tokens"),
        "cached_tokens": _total_tokens(tasks, "cached_tokens"),
        "error": error,
        "diagnostic_path": diagnostic_path,
        "verdicts": verdicts,
        "milestone_commits": milestone_commits,
        "expensive_drafts": expensive_drafts,
    }


def create_app(projects_dir: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(projects_dir or PROJECTS_DIR).resolve(strict=False)

    @app.get("/")
    def projects_view():
        projects = list_projects(root)
        # Portfolio grouping: each project in exactly one group (T004)
        attention_projects = [p for p in projects if p.get("portfolio_group") == "needs_attention"]
        active_projects = [p for p in projects if p.get("portfolio_group") == "active"]
        completed_projects = [p for p in projects if p.get("portfolio_group") == "recently_completed"]
        total_count = len(projects)
        active_count = sum(project["status"].lower() not in COMPLETED_PROJECT_STATUSES for project in projects)
        return render_template(
            "webui/projects.html",
            projects=projects,
            attention_projects=attention_projects,
            active_projects=active_projects,
            completed_projects=completed_projects,
            total_count=total_count,
            active_count=active_count,
        )

    @app.get("/projects/<project_id>")
    def project_view(project_id: str):
        try:
            project = load_project(root, project_id)
        except (OSError, ValueError):
            abort(404)
        return render_template("webui/project.html", project=project)

    return app


def _milestone_commits(project: Path) -> list[dict[str, Any]]:
    root = project / ".codexteam" / "runtime" / "git-steward"
    if not root.is_dir() or root.is_symlink():
        return []
    records = []
    for path in root.glob("*/commit-record.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        required = ("boundary_id", "branch", "head_after", "commit_subject", "committed_at", "committed_paths")
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != "1.0"
            or value.get("status") != "committed"
            or any(key not in value for key in required)
            or not isinstance(value["committed_paths"], list)
        ):
            continue
        records.append(
            {
                "boundary_id": str(value["boundary_id"]),
                "branch": str(value["branch"]),
                "commit": str(value["head_after"]),
                "short_commit": str(value["head_after"])[:12],
                "subject": str(value["commit_subject"]),
                "committed_at": str(value["committed_at"]),
                "path_count": len(value["committed_paths"]),
            }
        )
    records.sort(key=lambda item: _timestamp_value(item["committed_at"]), reverse=True)
    return records


def main() -> int:
    create_app().run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    return 0


def _session(project: Path, path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        task_id = data["task_id"]
        validate_identifier(data["attempt_id"], label="attempt ID")
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    turn_dir = path.parent / "turns"
    turn_files = []
    if turn_dir.is_dir():
        turn_files = sorted(file for file in turn_dir.iterdir() if file.is_file() and TURN_FILE.match(file.name))
    corrections = sum(TURN_FILE.match(file.name).group(2) == "feedback" for file in turn_files)
    usage = None
    error = None
    diagnostic = None
    turns = data.get("turns") if isinstance(data.get("turns"), list) else []
    metadata = {
        item.get("number"): item
        for item in turns
        if isinstance(item, dict) and isinstance(item.get("number"), int)
    }
    turn_details = []
    # Codex exports the persistent thread's total_token_usage at each completed
    # turn. The final completed record is the session total; summing records
    # would count the same earlier usage again.
    for turn_file in turn_files:
        match = TURN_FILE.match(turn_file.name)
        number = int(match.group(1))
        phase = match.group(2)
        metrics = load_summary(metrics_path(turn_file))
        parsed = _jsonl(turn_file) if metrics is None else None
        turn_usage = (
            metrics["usage"].get("cumulative", {})
            if metrics is not None
            else (parsed["usage"] or {})
        )
        turn_delta = metrics["usage"].get("delta", {}) if metrics is not None else {}
        activity = metrics.get("activity", {}) if metrics is not None else {}
        metric_turn = metrics.get("turn", {}) if metrics is not None else {}
        metric_events = metrics.get("events", {}) if metrics is not None else {}
        if _has_usage(turn_usage):
            usage = turn_usage
        turn_error = (
            metric_events.get("last_error")
            if metrics is not None
            else parsed["error"]
        )
        turn_diagnostic = UNKNOWN
        if turn_error:
            turn_diagnostic = turn_file.relative_to(project).as_posix()
            stderr = turn_file.with_suffix(".stderr.txt")
            if stderr.is_file() and stderr.stat().st_size:
                turn_diagnostic = stderr.relative_to(project).as_posix()
        item = metadata.get(number, {})
        turn_details.append(
            {
                "number": number,
                "phase": str(item.get("phase", phase)),
                "status": str(item.get("status", UNKNOWN)),
                "duration_seconds": item.get(
                    "duration_seconds",
                    metric_turn.get("duration_seconds"),
                ),
                "input_tokens": turn_usage.get("input_tokens"),
                "output_tokens": turn_usage.get("output_tokens"),
                "cached_tokens": turn_usage.get("cached_input_tokens"),
                "uncached_tokens": turn_usage.get("uncached_input_tokens"),
                "input_delta": turn_delta.get("input_tokens"),
                "output_delta": turn_delta.get("output_tokens"),
                "cached_delta": turn_delta.get("cached_input_tokens"),
                "uncached_delta": turn_delta.get("uncached_input_tokens"),
                "delta_mode": (
                    metrics["usage"].get("delta_mode", UNKNOWN)
                    if metrics is not None
                    else UNKNOWN
                ),
                "metrics_available": metrics is not None,
                "completed": metric_turn.get("completed") if metrics is not None else None,
                "tool_calls": activity.get("tool_calls"),
                "failed_tool_calls": activity.get("failed_tool_calls"),
                "command_calls": activity.get("command_calls"),
                "failed_command_calls": activity.get("failed_command_calls"),
                "edit_events": activity.get("edit_events"),
                "agent_messages": activity.get("agent_messages"),
                "command_output_bytes": activity.get("command_output_bytes"),
                "max_command_output_bytes": activity.get("max_command_output_bytes"),
                "repeated_commands": activity.get("repeated_commands", []),
                "largest_commands": activity.get("largest_commands", []),
                "error": turn_error or UNKNOWN,
                "diagnostic_path": turn_diagnostic,
            }
        )
        if turn_error:
            error = turn_error
            diagnostic = turn_diagnostic

    recorded_numbers = {item["number"] for item in turn_details}
    for number, item in metadata.items():
        if number not in recorded_numbers:
            turn_details.append(
                {
                    "number": number,
                    "phase": str(item.get("phase", UNKNOWN)),
                    "status": str(item.get("status", UNKNOWN)),
                    "duration_seconds": item.get("duration_seconds"),
                    "input_tokens": None,
                    "output_tokens": None,
                    "cached_tokens": None,
                    "uncached_tokens": None,
                    "input_delta": None,
                    "output_delta": None,
                    "cached_delta": None,
                    "uncached_delta": None,
                    "delta_mode": UNKNOWN,
                    "metrics_available": False,
                    "completed": None,
                    "tool_calls": None,
                    "failed_tool_calls": None,
                    "command_calls": None,
                    "failed_command_calls": None,
                    "edit_events": None,
                    "agent_messages": None,
                    "command_output_bytes": None,
                    "max_command_output_bytes": None,
                    "repeated_commands": [],
                    "largest_commands": [],
                    "error": UNKNOWN,
                    "diagnostic_path": UNKNOWN,
                }
            )
    turn_details.sort(key=lambda item: item["number"])

    if turn_details:
        for turn in turn_details:
            if turn["status"] == UNKNOWN and turn["number"] == turn_details[-1]["number"]:
                turn["status"] = str(data.get("last_status", UNKNOWN))

    durations = [item.get("duration_seconds") for item in turns if isinstance(item, dict)]
    durations = [float(value) for value in durations if isinstance(value, (int, float))]
    failed_turns = sum(
        item.get("status") in FAILED_TURN_STATUSES
        for item in turns
        if isinstance(item, dict)
    )
    if data.get("last_status") in FAILED_TURN_STATUSES:
        if not turns:
            failed_turns = 1
        if not diagnostic:
            last = data.get("last_turn_path")
            if isinstance(last, str):
                diagnostic = last.removesuffix(".txt") + ".jsonl"
        error = error or str(data.get("last_status"))
        if turn_details:
            last_turn = turn_details[-1]
            last_turn["error"] = error
            last_turn["diagnostic_path"] = diagnostic or UNKNOWN

    input_tokens = int((usage or {}).get("input_tokens", 0) or 0)
    output_tokens = int((usage or {}).get("output_tokens", 0) or 0)
    cached_tokens = int((usage or {}).get("cached_input_tokens", 0) or 0)
    total_tokens = input_tokens + output_tokens
    provider = str(data.get("model_provider", UNKNOWN))
    local = "local" in provider.lower() or "ollama" in provider.lower()
    return {
        "task_id": str(task_id),
        "attempt": str(data.get("attempt_id", UNKNOWN)),
        "profile": str(data.get("model_profile", UNKNOWN)),
        "provider": provider,
        "role": str(data.get("agent_role", UNKNOWN)),
        "phase": str(data.get("last_phase", UNKNOWN)),
        "status": str(data.get("last_status", UNKNOWN)),
        "turns": int(data.get("turn_count", len(turn_files)) or 0),
        "corrections": corrections,
        "failed_turns": failed_turns,
        "duration_seconds": round(sum(durations), 3) if durations else None,
        "cloud_tokens": 0 if local else (total_tokens if usage is not None else None),
        "local_tokens": (total_tokens if usage is not None else None) if local else 0,
        "cloud_input_tokens": 0 if local else (input_tokens if usage is not None else None),
        "cloud_output_tokens": 0 if local else (output_tokens if usage is not None else None),
        "local_input_tokens": (input_tokens if usage is not None else None) if local else 0,
        "local_output_tokens": (output_tokens if usage is not None else None) if local else 0,
        "cached_tokens": cached_tokens if usage is not None else None,
        "error": error or UNKNOWN,
        "diagnostic_path": diagnostic or UNKNOWN,
        "turn_details": turn_details,
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at") or "",
    }


def _jsonl(path: Path) -> dict[str, Any]:
    usage = None
    error = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
            if event.get("type") in {"turn.failed", "error"}:
                error = str(event.get("message") or event.get("error") or event.get("type"))
    except (OSError, ValueError, json.JSONDecodeError):
        error = "unreadable turn log"
    return {"usage": usage, "error": error}


def _has_usage(usage: Any) -> bool:
    return isinstance(usage, dict) and any(
        isinstance(usage.get(key), (int, float))
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    )


def _expensive_drafts(
    tasks: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    drafts = []
    for task in tasks:
        for attempt in task["attempts"]:
            for turn in attempt["turn_details"]:
                if (
                    turn["phase"] != "draft"
                    or not turn["metrics_available"]
                    or turn["completed"] is not True
                ):
                    continue
                ranking_tokens = turn["input_delta"]
                if ranking_tokens is None:
                    ranking_tokens = turn["input_tokens"]
                if ranking_tokens is None:
                    continue
                drafts.append(
                    {
                        "task_id": task["id"],
                        "attempt": attempt["attempt"],
                        "role": attempt["role"],
                        "profile": attempt["profile"],
                        "status": attempt["status"],
                        "turn": turn["number"],
                        "input_tokens": turn["input_tokens"],
                        "input_delta": turn["input_delta"],
                        "cached_tokens": turn["cached_tokens"],
                        "uncached_tokens": turn["uncached_tokens"],
                        "output_tokens": turn["output_tokens"],
                        "duration_seconds": turn["duration_seconds"],
                        "tool_calls": turn["tool_calls"],
                        "failed_tool_calls": turn["failed_tool_calls"],
                        "command_calls": turn["command_calls"],
                        "failed_command_calls": turn["failed_command_calls"],
                        "command_output_bytes": turn["command_output_bytes"],
                        "repeated_commands": turn["repeated_commands"],
                        "largest_commands": turn["largest_commands"],
                        "ranking_tokens": ranking_tokens,
                    }
                )
    drafts.sort(
        key=lambda item: (
            -item["ranking_tokens"],
            item["task_id"],
            item["attempt"],
            item["turn"],
        )
    )
    return drafts[:limit]


def _bullets(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values = {}
    for line in lines:
        match = re.match(r"^- ([^:]+):\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("`") or UNKNOWN
    return values


def _task_rows(path: Path) -> list[TaskRow]:
    try:
        text = path.read_text(encoding="utf-8")
        return list(parse_task_document(text).rows)
    except OSError:
        return []
    except (TaskDocumentError, ValueError):
        rows = []
        seen = set()
        for line in text.splitlines():
            if not re.match(r"^\|\s*T\d{3,6}\s*\|", line):
                continue
            cells = tuple(cell.strip().strip("`") for cell in line.strip()[1:-1].split("|"))
            if len(cells) != 6:
                continue
            task_id = normalize_task_id(cells[0])
            if task_id in seen:
                continue
            seen.add(task_id)
            status = cells[2]
            for prefix, normalized in (
                ("completed", "Completed"),
                ("blocked", "Blocked"),
                ("planned", "Planned"),
                ("assigned", "In Progress"),
                ("drafted", "In Progress"),
            ):
                if status.lower().startswith(prefix):
                    status = normalized
                    break
            rows.append(TaskRow(task_id, cells[1], status, cells[3], cells[4], cells[5]))
        return rows


def _first_heading(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return None


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _total_tokens(items: list[dict[str, Any]], key: str) -> int | None:
    if not items or any(item.get(key) is None for item in items):
        return None
    return sum(int(item[key]) for item in items)


def _elapsed_seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max(0, int((datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()))
    except ValueError:
        return None


def _task_phases(task: dict[str, Any]) -> list[dict[str, Any]]:
    turns = [
        turn
        for attempt in reversed(task["attempts"])
        for turn in attempt["turn_details"]
    ]
    phases = []
    for name in PHASES[:3]:
        matching = [turn for turn in turns if turn["phase"] == name]
        status = matching[-1]["status"] if matching else UNKNOWN
        state = "pending"
        if matching:
            if status == "correction_needed":
                state = "warning"
            elif status in FAILED_TURN_STATUSES:
                state = "failed"
            elif status in {"running", "in_progress"}:
                state = "active"
            else:
                state = "complete"
        elif task["phase"] == name and task["status"] != "Completed":
            state = "active"
        durations = [turn["duration_seconds"] for turn in matching if isinstance(turn["duration_seconds"], (int, float))]
        phases.append(
            {
                "name": name,
                "state": state,
                "status": status,
                "turns": len(matching),
                "duration_seconds": round(sum(durations), 3) if durations else None,
            }
        )

    verification = str(task["verification"]).lower()
    if verification in {"pass", "passed", "verified", "complete", "completed"}:
        verify_state = "complete"
    elif "fail" in verification:
        verify_state = "failed"
    elif task["phase"] == "verify":
        verify_state = "active"
    else:
        verify_state = "pending"
    phases.append({"name": "verify", "state": verify_state, "status": task["verification"], "turns": 0, "duration_seconds": None})

    task_status = str(task["status"]).lower()
    if task_status in {"complete", "completed", "closed", "done"}:
        closed_state = "complete"
    elif task_status in {"blocked", "failed"}:
        closed_state = "failed"
    else:
        closed_state = "pending"
    phases.append({"name": "closed", "state": closed_state, "status": task["status"], "turns": 0, "duration_seconds": None})
    return phases


def _latest_timestamp(values: list[Any]) -> str | None:
    available = [str(value) for value in values if value and _timestamp_value(value) != float("-inf")]
    return max(available, key=_timestamp_value) if available else None


def _timestamp_value(value: Any) -> float:
    if not value or value == UNKNOWN:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def _latest_file_timestamp(*paths: Path) -> str | None:
    existing = [path.stat().st_mtime for path in paths if path.is_file()]
    if not existing:
        return None
    return datetime.fromtimestamp(max(existing), timezone.utc).isoformat().replace("+00:00", "Z")


# --- Presentation projection helpers (T004) ---

def _board_column(task: dict[str, Any]) -> str:
    """Deterministic board column from task row + latest session evidence.

    Precedence: Blocked > Done > In Validation > In Review > In Progress > Backlog.
    Uses lowercase comparison throughout for session status to avoid case mismatches.
    """
    status = task["status"]
    phase = task["phase"]
    verification = task["verification"]
    attempts = task.get("attempts", [])

    # Normalize latest session status to lowercase for consistent comparison
    latest_session_status = ""
    if attempts:
        # attempts are stored newest-first in load_project
        latest_attempt = attempts[0]
        latest_session_status = str(latest_attempt.get("status", "")).lower()

    status_lower = status.lower()

    # Blocked — canonical blocked only
    if status_lower == "blocked":
        return "Blocked"

    # Done — completed + verified positively. Use COMPLETED_TASK_STATUSES for consistency.
    if status_lower in COMPLETED_TASK_STATUSES:
        verification_lower = str(verification).lower()
        if verification_lower in {"pass", "passed", "verified", "complete", "completed"}:
            return "Done"

    # In Validation — completed but verification pending/unknown/not positive.
    # Also finalized work awaiting positive verification.
    if status_lower in COMPLETED_TASK_STATUSES or latest_session_status == "finalized":
        return "In Validation"

    # In Review — draft_ready result, Needs Review status, or revised draft awaiting Lead.
    # Check both task-row status and session status (lowercase).
    if latest_session_status == "draft_ready" or status_lower == "draft_ready":
        return "In Review"
    if "review" in status_lower:
        return "In Review"

    # Active feedback correction or active phase work → In Progress
    if phase.lower() in ACTIVE_PHASES:
        return "In Progress"

    # Task row says In Progress, Assigned, Drafted
    if status_lower in {"in progress", "assigned", "drafted"}:
        return "In Progress"

    # Failed turns but not canonical blocked — recoverable, stays in progress lane.
    # Also explicit interrupted/correction_needed latest session statuses (lowercase).
    if task["failed_turns"] > 0:
        return "In Progress"
    if latest_session_status in FAILED_TURN_STATUSES:
        return "In Progress"
    # Task-row recoverable statuses even without session files
    if status_lower in {s for s in FAILED_TURN_STATUSES}:
        return "In Progress"

    # Backlog — Planned/Ready/no session/no higher match
    if status_lower in {"planned", "ready"}:
        return "Backlog"

    # Default fallback
    return "Backlog"


def _portfolio_group(needs_attention: bool, tasks: list[dict[str, Any]], state: dict[str, str]) -> str:
    """Return one of needs_attention, active, recently_completed.

    Each project appears in exactly one group with this precedence.
    """
    if needs_attention:
        return "needs_attention"
    status = state.get("Status", "").lower()
    if status in COMPLETED_PROJECT_STATUSES:
        return "recently_completed"
    if tasks and all(t["status"].lower() in {"completed"} for t in tasks):
        return "recently_completed"
    return "active"


def _task_presentation(objective: str) -> tuple[str | None, str | None]:
    """Split the existing ``M# — objective`` convention for UI presentation."""
    if not objective or objective == UNKNOWN:
        return None, None
    match = re.match(r"^\s*(M\d{1,3})\s*(?:—|–|-|:)\s*(.+?)\s*$", objective, re.IGNORECASE)
    if not match:
        return None, objective
    return match.group(1).upper(), match.group(2)


def _compact_card(task: dict[str, Any]) -> dict[str, Any]:
    """Compact task-card payload for the board lane.

    Includes objective-first hierarchy with useful secondary facts:
    owner, role/profile when present, stage/action, last activity,
    verification when reported, turns/corrections when non-zero.
    No raw paths or provider strings.
    """
    card = {
        "id": task["id"],
        "objective": task["display_objective"],
        "milestone_id": task["milestone_id"],
        "owner": task["owner"] if task["owner"] != UNKNOWN else None,
        "owner_label": _human_owner_label(task["owner"], task.get("role")),
        "board_column": task.get("board_column", "Backlog"),
        "attention": task.get("board_attention", False),
    }
    error = task.get("error", UNKNOWN)
    human = _human_error(error)
    if human:
        card["attention_label"] = human
    if task["role"] != UNKNOWN:
        card["role"] = task["role"]
    if task["profile"] != UNKNOWN:
        card["profile"] = task["profile"]
    # Current stage/action from phase (human-readable)
    phase = task.get("phase", UNKNOWN)
    if phase != UNKNOWN:
        card["stage"] = phase.title()
    # Last activity timestamp when available
    updated = task.get("updated_at", UNKNOWN)
    if updated and updated != UNKNOWN:
        card["last_activity"] = updated
    # Verification when reported (not unknown)
    verification = task.get("verification", UNKNOWN)
    if verification != UNKNOWN:
        card["verification"] = verification
    # Turns/corrections when non-zero
    turns = task.get("turns", 0)
    corrections = task.get("corrections", 0)
    if isinstance(turns, (int, float)) and int(turns) > 0:
        card["turns"] = int(turns)
    if isinstance(corrections, (int, float)) and int(corrections) > 0:
        card["corrections"] = int(corrections)
    return card


def _human_error(error: str) -> str | None:
    """Convert a raw error status to a short human label. Never returns raw paths."""
    if not error or error == UNKNOWN:
        return None
    mapping = {
        "turn_failed": "Worker failed",
        "process_failed": "Process failure",
        "timed_out": "Timeout",
        "interrupted": "Interrupted",
        "correction_needed": "Correction needed",
    }
    for key, label in mapping.items():
        if error.lower().startswith(key):
            return label
    # Check if the error message contains a known status indicator
    lower = error.lower()
    for key, label in mapping.items():
        if key in lower:
            return label
    text = error.split("\n")[0]
    return text if len(text) <= 120 else text[:117] + "..."


def _human_owner_label(owner: str, canonical_role: str | None = None) -> str | None:
    """Normalize raw owner string for presentation.

    Deterministic rules:
    1. Already-human text (no backticks, no em-dash descriptor, no parenthetical role) → unchanged.
    2. If canonical role is reported → return role with underscores→spaces, title-cased.
    3. Otherwise use parenthetical role when present.
    4. Otherwise use the final human role word from the em-dash descriptor after removing
       backticks and trailing attempt marker.

    Uses the module-level re import; does not hard-code model names.
    """
    if not owner or owner == UNKNOWN:
        return None
    label = owner.strip()

    # Determine if this is a machine-formatted owner string
    has_backticks = "`" in label
    has_emdash_descriptor = "—" in label
    paren_match = re.search(r"\s*\(([a-zA-Z][a-zA-Z0-9_-]*)\)\s*$", label)

    is_machine_formatted = has_backticks or has_emdash_descriptor or paren_match is not None

    if not is_machine_formatted:
        # Already-human text passes through unchanged
        return label

    # Machine-formatted: prefer canonical role if reported
    if canonical_role and canonical_role != UNKNOWN:
        return canonical_role.replace("_", " ").title()

    # Fall back to parenthetical role when present
    if paren_match is not None:
        role_name = paren_match.group(1)
        return role_name.replace("_", " ").title()

    # Last resort: extract the final human role word from em-dash descriptor
    # e.g., "`gitgui-m17-dev-T080` — GPT-5.4 mini Developer" → "Developer"
    label = label.replace("`", "")  # strip backticks
    if has_emdash_descriptor:
        parts = label.split("—")
        descriptor = parts[-1].strip()
        # Remove trailing attempt marker
        descriptor = re.sub(r"\s+att-\d{3}$", "", descriptor, flags=re.IGNORECASE)
        # Take the final word as the human role
        words = descriptor.split()
        if words:
            return words[-1].replace("_", " ").title()

    # If none of the above matched, fall back to title-cased label
    return label.title()


def _attention_summary(error: str, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compact attention summary without raw diagnostic paths.

    Derives the human label from task/session status for canonical names like
    "Worker failed", "Interrupted", etc.  Uses the error text only as a message.
    """
    if not error or error == UNKNOWN:
        return None
    # Prefer the canonical session/task status for the label
    label_source = error
    for task in tasks:
        if task.get("needs_attention") and task["error"] != UNKNOWN:
            # Use the attempt's last_status which is a canonical status string
            attempts = task.get("attempts", [])
            if attempts:
                # attempts[0] is newest-first per load_project contract
                last_status = attempts[0].get("status", "")
                if last_status and last_status != UNKNOWN:
                    label_source = last_status
                    break
    label = _human_error(label_source)

    # Sanitize the message: replace any raw diagnostic path with a generic sentence.
    # Do not attempt complex parsing; just check for known path fragments.
    raw_message = error.split(chr(10))[0] if chr(10) in error else error
    needs_sanitize = False
    for fragment in (".jsonl", ".stderr", "/sessions/", "/turns/", ".codexteam/runtime"):
        if fragment.lower() in raw_message:
            needs_sanitize = True
            break
    if needs_sanitize:
        # Use the human label as a short explanatory sentence, or generic fallback
        raw_message = label if label else "Attention needed"

    # Deduplicate: if label and message are equal case-insensitively, avoid repetition
    if label and label.lower() == raw_message.lower():
        raw_message = "Review the latest task details."

    return {
        "label": label,
        "message": raw_message,
    }


def _compact_summary(
    completed: int,
    total: int,
    open_count: int,
    attention_count: int,
    tasks: list[dict[str, Any]],
    elapsed: int | None,
) -> dict[str, Any]:
    """Compact project summary with only decision-useful facts."""
    summary = {
        "completed": completed,
        "total": total,
        "open": open_count,
    }
    if attention_count > 0:
        summary["attention"] = attention_count

    all_turns = sum(task["turns"] for task in tasks)
    if all_turns > 0:
        summary["turns"] = all_turns
    all_corrections = sum(task["corrections"] for task in tasks)
    if all_corrections > 0:
        summary["corrections"] = all_corrections
    if elapsed is not None:
        summary["elapsed"] = elapsed

    # Token totals only when reported across all tasks
    total_local = _safe_token_total(tasks, "local_tokens")
    total_cloud = _safe_token_total(tasks, "cloud_tokens")
    if total_local is not None:
        summary["tokens"] = total_local
    elif total_cloud is not None:
        summary["tokens"] = total_cloud

    return summary


def _safe_token_total(items: list[dict[str, Any]], key: str) -> int | None:
    """Safely sum a token key across tasks; returns None if any value is missing or all zeros."""
    values = []
    for item in items:
        val = item.get(key)
        if isinstance(val, (int, float)):
            values.append(int(val))
        elif val is not None:
            return None  # Mixed types — omit entirely
    if not values:
        return None
    total = sum(values)
    return total if total > 0 else None


def _agent_activity(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Split agents into active and inactive groups with compact payloads.

    Active = In Progress work only (not draft_ready/awaiting review).
    Dedup includes owner so different owners with same role/profile are separate.
    Preserves exact role/profile/provider values.
    """
    active = []
    inactive = []
    seen = set()
    for task in tasks:
        # Include owner in identity deduplication per feedback item 5
        agent_key = (task["role"], task["profile"], task["owner"])
        if agent_key in seen:
            continue
        seen.add(agent_key)
        # Active only = genuinely In Progress work (not draft_ready or awaiting review)
        is_active = (
            task["board_column"] == "In Progress"
            and task["status"].lower() not in {"completed"}
        )
        entry = {
            "objective": task["display_objective"],
            "milestone_id": task["milestone_id"],
            "owner": task["owner"] if task["owner"] != UNKNOWN else None,
            "owner_label": _human_owner_label(task["owner"], task.get("role")),
            "role": task["role"] if task["role"] != UNKNOWN else None,
            "profile": task["profile"] if task["profile"] != UNKNOWN else None,
            "provider": task.get("provider"),
            "task_id": task["id"],
            "phase": task["phase"] if task["phase"] != UNKNOWN else None,
            "status": task["status"],
            "activity_label": _activity_label(task),
        }
        if is_active:
            active.append(entry)
        else:
            inactive.append(entry)
    return {"active": active, "inactive": inactive}


def _activity_label(task: dict[str, Any]) -> str | None:
    """Short human-readable activity label."""
    phase = task["phase"]
    status = task["status"].lower()
    if status in {"completed"}:
        return "Completed"
    if status == "blocked":
        return "Blocked"
    if task.get("board_attention"):
        return "Needs attention"
    # draft_ready / awaiting review is not active execution
    attempts = task.get("attempts", [])
    latest_status = ""
    if attempts:
        latest_status = attempts[0].get("status", "")
    if latest_status == "draft_ready" or "review" in status:
        return "Awaiting review"
    if phase in ACTIVE_PHASES:
        return f"Working — {phase}"
    return None
