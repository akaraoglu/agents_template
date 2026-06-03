#!/usr/bin/env python3
"""Shared markdown task-progress helpers for Smith-style task sequencing."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


PLAN_TASK_RE = re.compile(r"^\s*\d+\.\s+\*\*(T\d{3}):\s*(.+?)\*\*\s*$")
BACKLOG_BULLET_RE = re.compile(
    r"^\s*-\s*\[(?P<status>[A-Z_]+)\]\s*(?P<task_id>T\d{3}):\s*(?P<title>.+?)"
    r"(?:\s*--\s*(?P<note>.+?))?\s*$"
)
BACKLOG_LEGACY_RE = re.compile(r"^\s*-\s*(?P<task_id>T\d{3})\s+(?P<status>[A-Z_]+)\s*$")
CURRENT_TASK_HEADING_RE = re.compile(r"^\s*##\s*(?P<label>Task ID|Task Name):\s*(?P<value>.+?)\s*$", re.IGNORECASE)
CURRENT_TASK_BULLET_RE = re.compile(r"^\s*-\s*\*\*(?P<label>task_id|task_name)\*\*:\s*(?P<value>.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PlannedTask:
    task_id: str
    title: str


@dataclass
class BacklogTask:
    task_id: str
    title: str
    status: str
    note: str = ""


def normalize_task_id(task_id: str) -> str:
    normalized = task_id.strip().upper()
    if not re.fullmatch(r"T\d{3}", normalized):
        raise ValueError(f"invalid task id: {task_id}")
    return normalized


def parse_plan(text: str) -> list[PlannedTask]:
    tasks: list[PlannedTask] = []
    in_phases = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.lower() == "## phases":
            in_phases = True
            continue
        if in_phases and stripped.startswith("## ") and stripped.lower() != "## phases":
            break
        if not in_phases:
            continue
        match = PLAN_TASK_RE.match(raw)
        if match:
            tasks.append(PlannedTask(task_id=normalize_task_id(match.group(1)), title=match.group(2).strip()))
    return tasks


def parse_backlog(text: str, plan: Iterable[PlannedTask] | None = None) -> list[BacklogTask]:
    plan_by_id = {task.task_id: task.title for task in plan or []}
    entries: list[BacklogTask] = []
    for raw in text.splitlines():
        bullet = BACKLOG_BULLET_RE.match(raw)
        if bullet:
            task_id = normalize_task_id(bullet.group("task_id"))
            entries.append(
                BacklogTask(
                    task_id=task_id,
                    title=bullet.group("title").strip(),
                    status=bullet.group("status").strip().upper(),
                    note=(bullet.group("note") or "").strip(),
                )
            )
            continue
        legacy = BACKLOG_LEGACY_RE.match(raw)
        if legacy:
            task_id = normalize_task_id(legacy.group("task_id"))
            entries.append(
                BacklogTask(
                    task_id=task_id,
                    title=plan_by_id.get(task_id, task_id),
                    status=legacy.group("status").strip().upper(),
                )
            )
    return entries


def backlog_by_id(entries: Iterable[BacklogTask]) -> dict[str, BacklogTask]:
    return {entry.task_id: entry for entry in entries}


def merge_plan_and_backlog(plan: list[PlannedTask], backlog: list[BacklogTask]) -> list[BacklogTask]:
    backlog_map = backlog_by_id(backlog)
    merged: list[BacklogTask] = []
    for index, task in enumerate(plan):
        existing = backlog_map.get(task.task_id)
        if existing is not None:
            merged.append(
                BacklogTask(
                    task_id=task.task_id,
                    title=existing.title or task.title,
                    status=existing.status,
                    note=existing.note,
                )
            )
        else:
            merged.append(
                BacklogTask(
                    task_id=task.task_id,
                    title=task.title,
                    status="READY" if index == 0 else "PENDING",
                )
            )
    return merged


def mark_done(entries: list[BacklogTask], task_id: str) -> list[BacklogTask]:
    task_id = normalize_task_id(task_id)
    updated = [BacklogTask(entry.task_id, entry.title, entry.status, entry.note) for entry in entries]
    for entry in updated:
        if entry.task_id == task_id:
            entry.status = "DONE"
            entry.note = ""
    return updated


def mark_blocked(entries: list[BacklogTask], task_id: str, reason: str) -> list[BacklogTask]:
    task_id = normalize_task_id(task_id)
    updated = [BacklogTask(entry.task_id, entry.title, entry.status, entry.note) for entry in entries]
    for entry in updated:
        if entry.task_id == task_id:
            entry.status = "BLOCKED"
            entry.note = reason.strip()
    return updated


def next_pending(plan: list[PlannedTask], backlog: list[BacklogTask], current_task_id: str) -> BacklogTask | None:
    task_id = normalize_task_id(current_task_id)
    backlog_map = backlog_by_id(backlog)
    seen_current = False
    for task in plan:
        if task.task_id == task_id:
            seen_current = True
            continue
        if not seen_current:
            continue
        entry = backlog_map.get(task.task_id)
        status = (entry.status if entry is not None else "PENDING").strip().upper()
        if status not in {"DONE", "BLOCKED"}:
            title = entry.title if entry is not None and entry.title else task.title
            note = entry.note if entry is not None else ""
            return BacklogTask(task.task_id, title, status if status in {"READY", "PENDING"} else "READY", note)
    return None


def render_backlog(tasks: list[BacklogTask], *, title: str = "Backlog") -> str:
    lines = [f"# {title}", "", "## Ready Queue"]
    for task in tasks:
        suffix = f" -- {task.note}" if task.note else ""
        lines.append(f"- [{task.status}] {task.task_id}: {task.title}{suffix}")
    if len(tasks) == 0:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_current_task(
    task_id: str | None,
    title: str | None,
    *,
    project_id: str,
    status: str = "active",
    notes: list[str] | None = None,
) -> str:
    task_id_text = task_id or "none"
    title_text = title or "none"
    state = status.lower().strip() or "active"
    lines = [
        f"# Current Task: {task_id_text}",
        "",
        f"## Task ID: {task_id_text}",
        f"## Task Name: {title_text}",
        "",
        "## Task Envelope",
        f"- **project_id**: {project_id}",
        f"- **task_id**: {task_id_text}",
        f"- **status**: {state}",
        "- **owner**: smith",
        "",
        "## Objective",
    ]
    if task_id and task_id != "none":
        lines.extend(
            [
                f"Read `management/tasks/{task_id}.md` and complete this task only.",
                "",
                "## Inputs",
                f"- `BRIEF.md`",
                f"- `PROJECT.md`",
                f"- `management/PLAN.md`",
                f"- `management/BACKLOG.md`",
                f"- `management/tasks/{task_id}.md`",
                "",
                "## Deliverables",
                f"- Completion of `{task_id}: {title_text}`",
                "",
                "## Completion Signal",
                "- `TASK_DONE` or `TASK_BLOCKED` returned to Smith after the task closes.",
            ]
        )
    else:
        lines.extend(["No active task remains.", "", "## Inputs", "- None", "", "## Deliverables", "- Project completion report to Neo", "", "## Completion Signal", "- `DONE` reported to Neo"])
    if notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in notes if note.strip())
    return "\n".join(lines) + "\n"


def render_brief(
    project_id: str,
    *,
    active_task_id: str | None,
    active_task_title: str | None,
    next_task_id: str | None = None,
    next_task_title: str | None = None,
    project_goal: str | None = None,
    status_note: str | None = None,
) -> str:
    active_id = active_task_id or "none"
    active_title = active_task_title or "none"
    next_id = next_task_id or "none"
    next_title = next_task_title or "none"
    lines = [
        f"# Project Brief — {project_id}",
        "",
        "## Goal",
        project_goal.strip() if project_goal and project_goal.strip() else "Continue the project by advancing the current task loop.",
        "",
        "## Current Step",
        f"- Active task: {active_id}: {active_title}",
    ]
    if next_id != "none":
        lines.extend(
            [
                f"- Next task: {next_id}: {next_title}",
                "- Mark the completed task done in `management/BACKLOG.md`.",
                "- Rewrite `CURRENT_TASK.md` to the next task before handing off.",
                "- If `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `management/BACKLOG.md` disagree, repair them first.",
                "- If the task is blocked, revise the backlog and current task before retrying.",
            ]
        )
    else:
        lines.extend(
            [
                "- No next task remains.",
                "- Close the project, report completion to Neo, and stop.",
            ]
        )
    if status_note and status_note.strip():
        lines.extend(["", "## Notes", f"- {status_note.strip()}"])
    return "\n".join(lines) + "\n"
