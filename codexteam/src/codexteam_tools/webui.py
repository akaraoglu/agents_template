from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, abort, render_template, request

from .paths import PathValidationError, contained_path, validate_identifier
from .tasks import TaskDocumentError, parse_task_document


CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = CODEXTEAM_ROOT / "projects"
UNKNOWN = "unknown"
VERDICTS = ("Lifecycle", "Product", "Evidence", "Management", "Manifest", "Performance")
TURN_FILE = re.compile(r"^(\d+)-(draft|feedback|final)\.jsonl$")
FAILED_TURN_STATUSES = {"turn_failed", "process_failed", "timed_out", "interrupted", "correction_needed"}


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
    return sorted(projects, key=lambda item: item["id"])


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
    rows = []
    try:
        rows = list(parse_task_document((project / "TASKS.md").read_text(encoding="utf-8")).rows)
    except (OSError, TaskDocumentError, ValueError):
        pass

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
        attempts = sorted(sessions.get(task_id, []), key=lambda item: item["updated_at"])
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
            "phase": latest.get("phase", UNKNOWN),
            "attempt": latest.get("attempt", UNKNOWN),
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
        }
        tasks.append(task)

    timestamps = [item[key] for group in sessions.values() for item in group for key in ("created_at", "updated_at")]
    timestamps = [value for value in timestamps if value]
    started = min((item["created_at"] for group in sessions.values() for item in group if item["created_at"]), default=None)
    updated = state.get("Updated At") or (max(timestamps) if timestamps else None)
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
    errors = [task for task in tasks if task["error"] != UNKNOWN]
    return {
        "id": project_id,
        "name": first_heading or project_id,
        "status": state.get("Status", UNKNOWN),
        "active_task": state.get("Active Task", UNKNOWN),
        "started_at": started or UNKNOWN,
        "updated_at": updated or UNKNOWN,
        "elapsed_seconds": elapsed,
        "elapsed_source": elapsed_source,
        "tasks": tasks,
        "task_total": len(tasks),
        "task_completed": completed,
        "task_failed": failed,
        "task_blocked": blocked,
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
        "error": report.get("Error", errors[-1]["error"] if errors else UNKNOWN),
        "diagnostic_path": errors[-1]["diagnostic_path"] if errors else UNKNOWN,
        "verdicts": verdicts,
    }


def compare_projects(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    numeric = (
        ("Delivery time", "elapsed_seconds"),
        ("Worker turns", "turns"),
        ("Corrections", "corrections"),
        ("Failed turns", "failed_turns"),
        ("Cloud tokens", "cloud_tokens"),
        ("Local tokens", "local_tokens"),
    )
    rows = []
    for label, key in numeric:
        before, after = baseline[key], candidate[key]
        difference = after - before if isinstance(before, (int, float)) and isinstance(after, (int, float)) else UNKNOWN
        before_display = _display(before)
        after_display = _display(after)
        if key == "elapsed_seconds":
            before_display = f"{before_display} ({baseline['elapsed_source']})"
            after_display = f"{after_display} ({candidate['elapsed_source']})"
        rows.append({"metric": label, "baseline": before_display, "candidate": after_display, "difference": _display(difference)})
    for name in ("product", "evidence", "management", "performance"):
        before, after = baseline["verdicts"][name], candidate["verdicts"][name]
        difference = "same" if before == after else f"{before} -> {after}"
        rows.append({"metric": f"{name.title()} verdict", "baseline": before, "candidate": after, "difference": difference})
    return rows


def create_app(projects_dir: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(projects_dir or PROJECTS_DIR).resolve(strict=False)

    @app.get("/")
    def projects_view():
        return render_template("webui/projects.html", projects=list_projects(root))

    @app.get("/projects/<project_id>")
    def project_view(project_id: str):
        try:
            project = load_project(root, project_id)
        except (OSError, ValueError):
            abort(404)
        return render_template("webui/project.html", project=project)

    @app.get("/compare")
    def compare_view():
        baseline_id = request.args.get("baseline", "")
        candidate_id = request.args.get("candidate", "")
        projects = list_projects(root)
        comparison = None
        baseline = candidate = None
        if baseline_id or candidate_id:
            if not baseline_id or not candidate_id:
                abort(400)
            try:
                baseline = load_project(root, baseline_id)
                candidate = load_project(root, candidate_id)
            except (OSError, ValueError):
                abort(404)
            comparison = compare_projects(baseline, candidate)
        return render_template(
            "webui/compare.html",
            projects=projects,
            baseline=baseline,
            candidate=candidate,
            comparison=comparison,
        )

    return app


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
    # Codex exports the persistent thread's total_token_usage at each completed
    # turn. The final completed record is the session total; summing records
    # would count the same earlier usage again.
    for turn_file in turn_files:
        parsed = _jsonl(turn_file)
        if parsed["usage"] is not None:
            usage = parsed["usage"]
        if parsed["error"]:
            error = parsed["error"]
            diagnostic = turn_file.relative_to(project).as_posix()
            stderr = turn_file.with_suffix(".stderr.txt")
            if stderr.is_file() and stderr.stat().st_size:
                diagnostic = stderr.relative_to(project).as_posix()

    turns = data.get("turns") if isinstance(data.get("turns"), list) else []
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


def _display(value: Any) -> Any:
    return UNKNOWN if value is None else value
