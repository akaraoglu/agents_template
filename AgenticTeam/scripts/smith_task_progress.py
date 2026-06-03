#!/usr/bin/env python3
"""Smith task-advance helper for TASK_DONE / TASK_BLOCKED reports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from task_progress import (
    BacklogTask,
    PlannedTask,
    mark_blocked,
    mark_done,
    merge_plan_and_backlog,
    next_pending,
    parse_backlog,
    parse_plan,
    render_brief,
    render_backlog,
    render_current_task,
)
from worker_runtime import extract_handoff_envelope, live_bin_root, require_ok, resolve_project, run_command, send_session_message


class TaskProgressError(RuntimeError):
    pass


STATE_FIELD_RE = re.compile(r"^\s*[-*]?\s*(?:\*\*)?(?P<field>[a-z_]+)(?:\*\*)?:\s*(?P<value>.+?)\s*$", re.IGNORECASE)


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise TaskProgressError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def _parse_state_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        match = STATE_FIELD_RE.match(raw)
        if match:
            fields[match.group("field").lower()] = match.group("value").strip().strip("`")
    return fields


def _parse_current_task(text: str) -> tuple[str, str]:
    task_id = "none"
    task_name = "none"
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.lower().startswith("## task id:") or stripped.lower().startswith("- **task_id**:"):
            task_id = stripped.split(":", 1)[1].strip().strip("`")
        if stripped.lower().startswith("## task name:") or stripped.lower().startswith("- **task_name**:"):
            task_name = stripped.split(":", 1)[1].strip().strip("`")
    return task_id, task_name


def _load_task_context(project_path: Path) -> tuple[list[PlannedTask], list[BacklogTask], str, str, Path, Path, Path]:
    plan_path = project_path / "management" / "PLAN.md"
    backlog_path = project_path / "management" / "BACKLOG.md"
    current_task_path = project_path / "CURRENT_TASK.md"
    plan = parse_plan(_read_text(plan_path))
    backlog = parse_backlog(_read_text(backlog_path), plan)
    current_task_id, current_task_name = _parse_current_task(_read_text(current_task_path))
    merged_backlog = merge_plan_and_backlog(plan, backlog)
    return plan, merged_backlog, current_task_id, current_task_name, plan_path, backlog_path, current_task_path


def _write_brief(
    project_path: Path,
    project_id: str,
    active_task_id: str | None,
    active_task_title: str | None,
    next_task_id: str | None = None,
    next_task_title: str | None = None,
    status_note: str | None = None,
) -> None:
    brief_path = project_path / "BRIEF.md"
    _write_text(
        brief_path,
        render_brief(
            project_id,
            active_task_id=active_task_id,
            active_task_title=active_task_title,
            next_task_id=next_task_id,
            next_task_title=next_task_title,
            status_note=status_note,
        ),
    )


def _read_project_state_fields(project_path: Path) -> dict[str, str]:
    return _parse_state_fields(_read_text(project_path / "PROJECT_STATE.md"))


def _sync_task_docs_from_state(project_path: Path, project_id: str) -> dict[str, str]:
    plan, backlog, current_task_id, current_task_name, _, backlog_path, current_task_path = _load_task_context(project_path)
    state = _read_project_state_fields(project_path)
    active_task_id = state.get("active_task", "none").strip() or "none"
    last_completed_task = state.get("last_completed_task", "").strip() or "none"
    if active_task_id.lower() in {"none", ""}:
        _write_text(current_task_path, render_current_task(None, None, project_id=project_id, status="done"))
        _write_brief(project_path, project_id, None, None, status_note="No active task remains.")
        return {"status": "synced", "message": "No active task remains."}
    active_task_id = active_task_id.upper()
    active_task = next((task for task in plan if task.task_id == active_task_id), None)
    if active_task is None:
        raise TaskProgressError(f"project state active_task {active_task_id} is not present in PLAN.md")
    synced_backlog = merge_plan_and_backlog(plan, backlog)
    active_index = next((index for index, task in enumerate(plan) if task.task_id == active_task_id), None)
    if active_index is None:
        raise TaskProgressError(f"unable to locate active task {active_task_id} in plan")
    for index, entry in enumerate(synced_backlog):
        if index < active_index:
            entry.status = "DONE"
            entry.note = ""
        elif entry.task_id == active_task_id:
            entry.status = "READY"
            entry.note = ""
        elif entry.status not in {"DONE", "BLOCKED"}:
            entry.status = "PENDING"
            entry.note = ""
    _write_text(backlog_path, render_backlog(synced_backlog))
    _write_text(
        current_task_path,
        render_current_task(active_task.task_id, active_task.title, project_id=project_id, status="active"),
    )
    next_task = next_pending(plan, synced_backlog, active_task_id)
    _write_brief(
        project_path,
        project_id,
        active_task.task_id,
        active_task.title,
        next_task.task_id if next_task is not None else None,
        next_task.title if next_task is not None else None,
        status_note=(
            f"Synced from PROJECT_STATE.md. Last completed task: {last_completed_task}."
            if last_completed_task and last_completed_task != "none"
            else "Synced from PROJECT_STATE.md."
        ),
    )
    return {
        "status": "synced",
        "message": f"Synced task docs to {active_task_id}.",
        "current_task_id": current_task_id,
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_validation_report(project_path: Path, task_id: str) -> str:
    report_path = project_path / "management" / "validation" / f"{task_id}_REPORT.md"
    return _read_text(report_path)


def _validate_pass_report(project_path: Path, task_id: str) -> None:
    report = _read_validation_report(project_path, task_id)
    if task_id not in report or "PASS" not in report:
        raise TaskProgressError(f"validation report does not confirm PASS for {task_id}")


def _write_project_state_done(project_id: str, task_id: str) -> None:
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            project_id,
            "DONE",
            "none",
            "--actor",
            "smith",
            "--expect-owner",
            "niaobe",
            "--set-owner",
            "smith",
            "--current-agent",
            "none",
            "--active-task",
            "none",
            "--task-phase",
            "none",
            "--task-status",
            "DONE",
            "--last-completed-task",
            task_id,
            "--last-task-result",
            "PASS",
            "--note",
            "All tasks complete. Project finished.",
        ],
        timeout=120,
    )
    require_ok(result, action="write_state done")


def _write_project_state_next(project_id: str, task_id: str, next_task_id: str) -> None:
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            project_id,
            "PLANNING",
            "niaobe",
            "--actor",
            "smith",
            "--expect-owner",
            "niaobe",
            "--set-owner",
            "smith",
            "--active-task",
            next_task_id,
            "--task-phase",
            "TASK_HANDOFF",
            "--task-status",
            "READY",
            "--last-completed-task",
            task_id,
            "--last-task-result",
            "PASS",
            "--note",
            f"Task {task_id} complete. Activated {next_task_id}.",
        ],
        timeout=120,
    )
    require_ok(result, action="write_state next")


def _write_project_state_blocked(project_id: str, task_id: str, reason: str) -> None:
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            project_id,
            "PLANNING",
            "smith",
            "--actor",
            "smith",
            "--expect-owner",
            "niaobe",
            "--set-owner",
            "smith",
            "--current-agent",
            "smith",
            "--active-task",
            task_id,
            "--task-phase",
            "TASK_BLOCKED",
            "--task-status",
            "BLOCKED",
            "--blocked-reason",
            reason,
            "--note",
            "Task blocked. Smith is revising the plan.",
        ],
        timeout=120,
    )
    require_ok(result, action="write_state blocked")


def _send_next_task(project_id: str, task_id: str, next_task_id: str) -> str:
    instructions = (
        f"Task {next_task_id} is ready. Read CURRENT_TASK.md and management/tasks/{next_task_id}.md, "
        "then run Design -> Implement -> Verify for that task only. Report TASK_DONE or TASK_BLOCKED to Smith."
    )
    handoff_result = run_command(
        [
            "bash",
            str(live_bin_root() / "handoff.sh"),
            "smith",
            "niaobe",
            project_id,
            instructions,
            "TASK_HANDOFF",
            next_task_id,
        ],
        timeout=120,
    )
    handoff_output = require_ok(handoff_result, action="handoff.sh smith->niaobe")
    envelope = extract_handoff_envelope(handoff_output)
    send_session_message("agent:niaobe:main", envelope)
    return handoff_output


def _send_project_done(project_id: str, task_id: str) -> str:
    payload = {
        "project_id": project_id,
        "from": "smith",
        "to": "neo",
        "phase": "DONE",
        "instructions": f"DONE: All tasks complete. Final validation report management/validation/{task_id}_REPORT.md verified.",
    }
    return send_session_message("agent:neo:main", json.dumps(payload, separators=(",", ":")))


def advance_task(project_id: str, task_id: str) -> dict[str, str]:
    resolved = resolve_project(project_id)
    project_path = Path(str(resolved["project_path"]))
    plan, backlog, current_task_id, current_task_name, _, backlog_path, current_task_path = _load_task_context(project_path)

    if current_task_id not in {"none", "", task_id}:
        return {
            "status": "stale",
            "message": f"Current task is {current_task_id}; ignoring duplicate TASK_DONE for {task_id}.",
        }

    if current_task_id == task_id:
        _validate_pass_report(project_path, task_id)
        backlog = mark_done(backlog, task_id)
        next_task = next_pending(plan, backlog, task_id)
        if next_task is not None:
            for entry in backlog:
                if entry.task_id == next_task.task_id:
                    entry.status = "READY"
                    entry.note = ""
                    break
        _write_text(backlog_path, render_backlog(backlog))

        if next_task is None:
            _write_text(current_task_path, render_current_task(None, None, project_id=project_id, status="done"))
            _write_brief(
                project_path,
                project_id,
                None,
                None,
                status_note="All tasks complete. Report project completion to Neo.",
            )
            _write_project_state_done(project_id, task_id)
            send_response = _send_project_done(project_id, task_id)
            return {
                "status": "done",
                "message": "Project complete. Neo notified.",
                "send_response": send_response,
            }

        _write_text(
            current_task_path,
            render_current_task(next_task.task_id, next_task.title, project_id=project_id, status="active"),
        )
        following_task = next_pending(plan, backlog, next_task.task_id)
        _write_brief(
            project_path,
            project_id,
            next_task.task_id,
            next_task.title,
            following_task.task_id if following_task is not None else None,
            following_task.title if following_task is not None else None,
            status_note=f"Smith activated {next_task.task_id}. Keep BACKLOG.md and CURRENT_TASK.md in sync.",
        )
        _write_project_state_next(project_id, task_id, next_task.task_id)
        handoff_output = _send_next_task(project_id, task_id, next_task.task_id)
        return {
            "status": "advanced",
            "next_task_id": next_task.task_id,
            "message": f"Activated {next_task.task_id}.",
            "handoff_output": handoff_output,
        }

    # No-op if Smith already moved forward and sees a duplicate report.
    return {
        "status": "stale",
        "message": f"Current task is {current_task_id}; no advancement required for {task_id}.",
    }


def block_task(project_id: str, task_id: str, reason: str) -> dict[str, str]:
    if not reason.strip():
        raise TaskProgressError("blocked task requires an exact reason")
    resolved = resolve_project(project_id)
    project_path = Path(str(resolved["project_path"]))
    plan, backlog, current_task_id, current_task_name, _, backlog_path, current_task_path = _load_task_context(project_path)
    if current_task_id not in {"none", "", task_id}:
        raise TaskProgressError(f"current task is {current_task_id}; refusing to block stale report for {task_id}")
    backlog = mark_blocked(backlog, task_id, reason)
    _write_text(backlog_path, render_backlog(backlog))
    current_title = current_task_name if current_task_id == task_id else None
    _write_text(
        current_task_path,
        render_current_task(
            task_id,
            current_title or (next((item.title for item in plan if item.task_id == task_id), task_id)),
            project_id=project_id,
            status="blocked",
            notes=[reason, "Smith must revise the plan before re-activating the task."],
        ),
    )
    _write_brief(
        project_path,
        project_id,
        task_id,
        current_title or (next((item.title for item in plan if item.task_id == task_id), task_id)),
        status_note=f"Task {task_id} is blocked. Repair the plan or add prerequisites before retrying.",
    )
    _write_project_state_blocked(project_id, task_id, reason)
    return {
        "status": "blocked",
        "message": f"Recorded blocker for {task_id}. Smith must revise the plan.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Advance or block Smith task progress.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    complete = subparsers.add_parser("complete")
    complete.add_argument("project_id")
    complete.add_argument("task_id")

    blocked = subparsers.add_parser("blocked")
    blocked.add_argument("project_id")
    blocked.add_argument("task_id")
    blocked.add_argument("--reason", required=True)

    sync = subparsers.add_parser("sync")
    sync.add_argument("project_id")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "complete":
            outcome = advance_task(args.project_id, args.task_id)
        elif args.command == "sync":
            resolved = resolve_project(args.project_id)
            outcome = _sync_task_docs_from_state(Path(str(resolved["project_path"])), args.project_id)
        else:
            outcome = block_task(args.project_id, args.task_id, args.reason)
    except TaskProgressError as exc:
        print(f"SMITH_TASK_PROGRESS_FAILED: {exc}")
        return 20
    print(outcome["message"])
    if "next_task_id" in outcome:
        print(f"NEXT_TASK={outcome['next_task_id']}")
    if "handoff_output" in outcome:
        print(outcome["handoff_output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
