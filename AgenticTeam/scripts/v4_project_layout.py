from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT_FILES = (
    "PROJECT.md",
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
    "BRIEF.md",
)

MANAGEMENT_DIRS = (
    "management",
    "management/tasks",
    "management/architecture",
    "management/validation",
)

OPENCLAW_DIRS = (
    ".openclaw",
)

WORKSPACE_DIRS = (
    "src",
    "tests",
)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def normalize_project_id(value: str) -> str:
    project_id = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    project_id = "-".join(part for part in project_id.split("-") if part)
    return project_id or "v4-project"


def project_dir_for(root: str | Path, project_id: str) -> Path:
    return Path(root).expanduser().resolve() / normalize_project_id(project_id)


def ensure_v4_project_layout(
    workspace_root: str | Path,
    *,
    project_id: str,
    title: str,
    goal: str = "",
) -> Path:
    """Create the existing project-process folders without changing their shape."""
    workspace = Path(workspace_root).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    for rel in (*OPENCLAW_DIRS, *MANAGEMENT_DIRS, *WORKSPACE_DIRS):
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    _write_if_missing(workspace / "PROJECT.md", render_project_md(project_id, title, goal))
    _write_if_missing(workspace / "BRIEF.md", render_brief_md(project_id, title, goal))
    _write_if_missing(workspace / "PROJECT_STATE.md", render_project_state_placeholder_md(project_id, title))
    _write_if_missing(workspace / "CURRENT_TASK.md", render_current_task_placeholder_md(project_id))
    _write_if_missing(workspace / "RESULT.md", render_result_md(project_id))
    _write_if_missing(workspace / "DONE_REPORT.md", render_done_report_md(project_id))
    _write_if_missing(workspace / "BLOCKED_REPORT.md", render_blocked_report_md(project_id))
    _write_if_missing(workspace / ".openclaw" / "handoffs.jsonl", "")
    return workspace


def required_layout_paths() -> tuple[str, ...]:
    return (
        *ROOT_FILES,
        "RESULT.md",
        "DONE_REPORT.md",
        "BLOCKED_REPORT.md",
        ".openclaw",
        ".openclaw/events.jsonl",
        ".openclaw/state.json",
        ".openclaw/leases.json",
        ".openclaw/handoffs.jsonl",
        "management",
        "management/PLAN.md",
        "management/BACKLOG.md",
        "management/tasks",
        "management/architecture",
        "management/validation",
        "src",
        "tests",
    )


def validate_v4_project_layout(workspace_root: str | Path, *, require_runtime_files: bool = True) -> list[str]:
    workspace = Path(workspace_root).expanduser().resolve()
    missing: list[str] = []
    for rel in required_layout_paths():
        if not require_runtime_files and rel in {
            ".openclaw/events.jsonl",
            ".openclaw/state.json",
            ".openclaw/leases.json",
            "management/PLAN.md",
            "management/BACKLOG.md",
        }:
            continue
        if not (workspace / rel).exists():
            missing.append(rel)
    return missing


def write_planning_files(workspace_root: str | Path, planned_tasks: Iterable[dict[str, Any]], *, title: str) -> None:
    workspace = Path(workspace_root).expanduser().resolve()
    tasks = list(planned_tasks)
    management = workspace / "management"
    tasks_dir = management / "tasks"
    management.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    (management / "PLAN.md").write_text(render_plan_md(title, tasks), encoding="utf-8")
    for task in tasks:
        task_id = str(task["task_id"])
        (tasks_dir / f"{task_id}.md").write_text(render_task_md(task), encoding="utf-8")


def _write_if_missing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def render_project_md(project_id: str, title: str, goal: str) -> str:
    goal_text = goal.strip() or title.strip() or project_id
    return (
        f"# Project: {title or project_id}\n\n"
        "## Goal\n"
        f"{goal_text}\n\n"
        "## Requirements\n"
        "- Preserve the existing AgenticTeam project-management file layout.\n\n"
        "## Acceptance Criteria\n"
        "- The project completes through the V4 typed WorkResult and OracleResult flow.\n"
    )


def render_brief_md(project_id: str, title: str, goal: str) -> str:
    goal_text = goal.strip() or title.strip() or project_id
    return (
        f"# Project Brief - {project_id}\n\n"
        "## Goal\n"
        f"{goal_text}\n\n"
        "## Requirements\n"
        "- Keep PROJECT.md, PROJECT_STATE.md, CURRENT_TASK.md, BRIEF.md, management/PLAN.md, management/BACKLOG.md, and management/tasks/ as the project process surface.\n\n"
        "## Acceptance Criteria\n"
        "- Smith owns progress, Morpheus completes tasks, and Oracle validates the final project.\n\n"
        "## Milestones\n"
        "1. Plan tasks.\n"
        "2. Complete tasks.\n"
        "3. Validate project.\n"
    )


def render_project_state_placeholder_md(project_id: str, title: str) -> str:
    return (
        f"# Project State - {project_id}\n\n"
        "## Overview\n"
        "- **schema_version**: 2\n"
        f"- **project_id**: {project_id}\n"
        f"- **title**: {title or project_id}\n"
        f"- **created**: {utc_now()}\n"
        "- **owner**: smith\n\n"
        "## Status\n"
        "- **phase**: PLANNING\n"
        "- **active_task**: none\n"
        "- **task_phase**: none\n"
        "- **task_status**: none\n"
        "- **current_agent**: smith\n"
        "- **waiting_for**: smith\n"
        "- **blocked_count**: 0\n"
        "- **blocked_reason**: none\n"
        "- **last_completed_task**: none\n"
        "- **last_task_result**: none\n\n"
        "## Task Ledger\n\n"
        "## Blockers\n\n"
        "## Milestones\n"
    )


def render_current_task_placeholder_md(project_id: str) -> str:
    return (
        f"# Current Task - {project_id}\n\n"
        "## Task Envelope\n"
        f"- **project_id**: {project_id}\n"
        "- **task_id**: none\n"
        "- **status**: idle\n"
        "- **owner**: smith\n\n"
        "## Objective\n"
        "No active task yet.\n\n"
        "## Inputs\n"
        "- BRIEF.md\n"
        "- PROJECT.md\n"
        "- management/PLAN.md\n"
        "- management/BACKLOG.md\n\n"
        "## Deliverables\n"
        "- Await Smith task activation.\n\n"
        "## Completion Signal\n"
        "- None\n"
    )


def render_result_md(project_id: str) -> str:
    return (
        f"# Result - {project_id}\n\n"
        "## Project Outcome\n"
        f"- **project_id**: {project_id}\n"
        "- **status**: in_progress\n\n"
        "## Completed Tasks\n"
        "<!-- Smith summarizes completed tasks here once the project is done -->\n\n"
        "## Validation Summary\n"
        "<!-- Final Oracle / Smith verification summary -->\n\n"
        "## Remaining Follow-ups\n"
        "<!-- Optional post-delivery follow-ups -->\n"
    )


def render_done_report_md(project_id: str) -> str:
    return (
        f"# DONE Report - V4 - {project_id}\n\n"
        "## Result\n"
        "- **status**: pending\n"
        f"- **completed_at**: {utc_now()}\n\n"
        "## What Was Done\n"
        "- Pending final Oracle validation.\n\n"
        "## Files Changed\n"
        "- Pending.\n\n"
        "## Test Results\n"
        "- Pending.\n"
    )


def render_blocked_report_md(project_id: str) -> str:
    return (
        f"# BLOCKED Report - V4 - {project_id}\n\n"
        "## Blocker\n"
        "- **status**: pending\n"
        "- **reason**: none\n\n"
        "## Evidence\n"
        "- Pending.\n"
    )


def render_plan_md(title: str, planned_tasks: list[dict[str, Any]]) -> str:
    lines = [
        f"# Plan - {title}",
        "",
        "## Strategy",
        "Execute tasks sequentially through the V4 Smith -> Morpheus -> Smith -> Oracle loop.",
        "",
        "## Tasks",
    ]
    for task in planned_tasks:
        task_id = str(task["task_id"])
        task_title = str(task.get("title", task_id))
        lines.append(f"- {task_id}: {task_title}")
    if not planned_tasks:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_task_md(task: dict[str, Any]) -> str:
    task_id = str(task["task_id"])
    title = str(task.get("title", task_id))
    body = str(task.get("body") or task.get("description") or "").strip()
    required_outputs = task.get("required_outputs") or []

    if body:
        return body.rstrip() + "\n"

    lines = [
        f"# Task {task_id}: {title}",
        "",
        "## Objective",
        title,
        "",
        "## Required Outputs",
    ]
    if required_outputs:
        lines.extend(f"- {path}" for path in required_outputs)
    else:
        lines.append("- See PROJECT.md and CURRENT_TASK.md")
    return "\n".join(lines) + "\n"
