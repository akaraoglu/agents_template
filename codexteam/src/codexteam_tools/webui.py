from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, render_template

from .paths import PathValidationError, contained_path, normalize_task_id, validate_identifier
from .tasks import TaskDocumentError, TaskRow, parse_task_document


CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = CODEXTEAM_ROOT / "projects"
UNKNOWN = "unknown"
VERDICTS = ("Lifecycle", "Product", "Evidence", "Management", "Manifest", "Performance")
TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
FAILED_TURN_STATUSES = {"turn_failed", "process_failed", "timed_out", "interrupted", "correction_needed"}
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
        task = {
            "id": task_id,
            "objective": row.description if row else UNKNOWN,
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

    completed = sum(task["status"] == "Completed" for task in tasks)
    blocked = sum(task["status"] == "Blocked" for task in tasks)
    failed = sum(
        task["status"] != "Completed" and task["failed_turns"] > 0
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
    agents = agents[:8]
    active_task = state.get("Active Task", UNKNOWN)
    active_task_details = next((task for task in tasks if task["id"] == active_task), None)
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
        "needs_attention": needs_attention,
        "agents": agents,
        "agent_total": agent_total,
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
    }


def create_app(projects_dir: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(projects_dir or PROJECTS_DIR).resolve(strict=False)

    @app.get("/")
    def projects_view():
        projects = list_projects(root)
        attention = [project for project in projects if project["needs_attention"]]
        active = [
            project
            for project in projects
            if not project["needs_attention"] and project["status"].lower() not in COMPLETED_PROJECT_STATUSES
        ]
        delivered = [project for project in projects if project["status"].lower() in COMPLETED_PROJECT_STATUSES]
        active_count = sum(project["status"].lower() not in COMPLETED_PROJECT_STATUSES for project in projects)
        return render_template(
            "webui/projects.html",
            projects=projects,
            attention_projects=attention,
            active_projects=active,
            delivered_projects=delivered,
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
        parsed = _jsonl(turn_file)
        if parsed["usage"] is not None:
            usage = parsed["usage"]
        turn_error = parsed["error"]
        turn_diagnostic = UNKNOWN
        if turn_error:
            turn_diagnostic = turn_file.relative_to(project).as_posix()
            stderr = turn_file.with_suffix(".stderr.txt")
            if stderr.is_file() and stderr.stat().st_size:
                turn_diagnostic = stderr.relative_to(project).as_posix()
        item = metadata.get(number, {})
        turn_usage = parsed["usage"] or {}
        turn_details.append(
            {
                "number": number,
                "phase": str(item.get("phase", phase)),
                "status": str(item.get("status", UNKNOWN)),
                "duration_seconds": item.get("duration_seconds"),
                "input_tokens": turn_usage.get("input_tokens"),
                "output_tokens": turn_usage.get("output_tokens"),
                "cached_tokens": turn_usage.get("cached_input_tokens"),
                "error": turn_error or UNKNOWN,
                "diagnostic_path": turn_diagnostic,
            }
        )
        if parsed["error"]:
            error = parsed["error"]
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
