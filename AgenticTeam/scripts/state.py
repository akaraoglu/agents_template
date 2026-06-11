import json
import os
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from AgenticTeam.scripts.contracts import DEFAULT_PROTECTED_PATHS, DEFAULT_WRITABLE_PATHS, Event

class ProjectState(BaseModel):
    project_id: str = "none"
    phase: str = "PLANNING"  # PLANNING | IN_PROGRESS | DONE | BLOCKED
    owner: str = "smith"
    active_task: str = "none"
    active_attempt: str = "none"
    waiting_for: str = "none"  # worker | oracle | smith | neo | none
    last_completed_task: Optional[str] = "none"
    last_result: Optional[Dict[str, Any]] = None
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    tasks: Dict[str, Dict[str, Any]] = Field(default_factory=dict) # task_id -> {task_id, title, status, note}
    title: str = "none"
    created: str = ""

def project_state_from_events(events: List[Event]) -> ProjectState:
    state = ProjectState()
    for ev in events:
        payload = ev.payload
        state.updated_at = ev.timestamp.isoformat()
        
        if ev.event_type == "project_created":
            state.project_id = payload.get("project_id", "none")
            state.title = payload.get("title", "none")
            state.created = ev.timestamp.isoformat()
            state.phase = "PLANNING"
            state.waiting_for = "smith"
        
        elif ev.event_type == "task_planned":
            task_id = payload.get("task_id")
            if task_id:
                state.tasks[task_id] = {
                    "task_id": task_id,
                    "title": payload.get("title", ""),
                    "status": "PENDING",
                    "note": "",
                    "expected_artifacts": payload.get("expected_artifacts", []),
                    "writable_paths": payload.get("writable_paths") or list(DEFAULT_WRITABLE_PATHS),
                    "protected_paths": payload.get("protected_paths") or list(DEFAULT_PROTECTED_PATHS),
                }

        elif ev.event_type == "task_scope_expanded":
            task_id = payload.get("task_id")
            if task_id in state.tasks:
                expanded = payload.get("expanded_allowed_artifacts") or payload.get("expanded_expected_artifacts")
                if expanded:
                    state.tasks[task_id]["expected_artifacts"] = expanded
                
        elif ev.event_type in ("task_dispatched", "task_started"):
            task_id = payload.get("task_id", "none")
            attempt_id = payload.get("attempt_id", "none")
            state.active_task = task_id
            state.active_attempt = attempt_id
            state.phase = "IN_PROGRESS"
            state.waiting_for = "worker"
            if task_id in state.tasks:
                state.tasks[task_id]["status"] = "READY"
                
        elif ev.event_type in ("work_submitted", "task_completed"):
            state.waiting_for = "smith"
            
        elif ev.event_type in ("work_accepted", "task_accepted"):
            task_id = payload.get("task_id", "none")
            state.last_completed_task = task_id
            state.last_result = payload.get("result")
            state.active_task = "none"
            state.active_attempt = "none"
            state.waiting_for = "smith"
            if task_id in state.tasks:
                state.tasks[task_id]["status"] = "DONE"
                
        elif ev.event_type in ("work_blocked", "task_blocked"):
            task_id = payload.get("task_id", "none")
            state.phase = "BLOCKED"
            state.waiting_for = "smith"
            if task_id in state.tasks:
                state.tasks[task_id]["status"] = "BLOCKED"
                state.tasks[task_id]["note"] = payload.get("reason", "blocked")
                
        elif ev.event_type == "oracle_dispatched":
            state.waiting_for = "oracle"
            state.active_task = "none"
            state.active_attempt = "none"
            
        elif ev.event_type == "oracle_passed":
            state.phase = "DONE"
            state.waiting_for = "none"
            
        elif ev.event_type == "oracle_failed":
            state.phase = "BLOCKED"
            state.waiting_for = "smith"
            
        elif ev.event_type == "project_done":
            state.phase = "DONE"
            state.waiting_for = "none"
            
        elif ev.event_type == "project_blocked":
            state.phase = "BLOCKED"
            state.waiting_for = "neo"
            
    return state

def write_state(state: ProjectState, workspace_root: str):
    workspace_path = Path(workspace_root)
    openclaw_dir = workspace_path / ".openclaw"
    openclaw_dir.mkdir(parents=True, exist_ok=True)
    state_file = openclaw_dir / "state.json"
    
    # Write atomically using a temporary file
    temp_file = state_file.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=2) + "\n")
    temp_file.replace(state_file)

def render_backlog(state: ProjectState) -> str:
    lines = ["# Backlog", "", "## Ready Queue"]
    sorted_task_ids = sorted(state.tasks.keys())
    for tid in sorted_task_ids:
        t = state.tasks[tid]
        status = t["status"]
        title = t["title"]
        note = t["note"]
        suffix = f" -- {note}" if note else ""
        lines.append(f"- [{status}] {tid}: {title}{suffix}")
    if not sorted_task_ids:
        lines.append("- none")
    return "\n".join(lines) + "\n"

def render_current_task(state: ProjectState) -> str:
    task_id_text = state.active_task or "none"
    title_text = "none"
    if state.active_task in state.tasks:
        title_text = state.tasks[state.active_task]["title"]
    
    lines = [
        f"# Current Task: {task_id_text}",
        "",
        f"## Task ID: {task_id_text}",
        f"## Task Name: {title_text}",
        "",
        "## Task Envelope",
        f"- **project_id**: {state.project_id}",
        f"- **task_id**: {task_id_text}",
        f"- **status**: {state.phase.lower()}",
        f"- **owner**: {state.owner}",
        "",
        "## Objective"
    ]
    if task_id_text != "none":
        lines.extend([
            f"Read `management/tasks/{task_id_text}.md` and complete this task only.",
            "",
            "## Inputs",
            "- `BRIEF.md`",
            "- `PROJECT.md`",
            "- `management/PLAN.md`",
            "- `management/BACKLOG.md`",
            f"- `management/tasks/{task_id_text}.md`",
            "",
            "## Deliverables",
            f"- Completion of {task_id_text}: {title_text}",
            "",
            "## Completion Signal",
            "- `TASK_DONE` or `TASK_BLOCKED` returned to Smith after the task closes."
        ])
    else:
        lines.extend([
            "No active task remains.",
            "",
            "## Inputs",
            "- None",
            "",
            "## Deliverables",
            "- Project completion report to Neo",
            "",
            "## Completion Signal",
            "- `DONE` reported to Neo"
        ])
    return "\n".join(lines) + "\n"

def render_markdown_views(state: ProjectState, workspace_root: str):
    workspace_path = Path(workspace_root)
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    # 1. PROJECT_STATE.md
    project_state_content = f"""# Project State — {state.project_id}

## Overview
- **schema_version**: 2
- **project_id**: {state.project_id}
- **title**: {state.title}
- **created**: {state.created}
- **owner**: {state.owner}

## Status
- **phase**: {state.phase}
- **active_task**: {state.active_task}
- **task_phase**: {state.phase}
- **task_status**: {state.phase}
- **current_agent**: {state.owner}
- **waiting_for**: {state.waiting_for}
- **blocked_count**: {1 if state.phase == "BLOCKED" else 0}
- **blocked_reason**: {state.tasks.get(state.active_task, {}).get("note", "none") if state.active_task in state.tasks else "none"}
- **last_completed_task**: {state.last_completed_task or "none"}
- **last_task_result**: {json.dumps(state.last_result) if state.last_result else "none"}

## Task Ledger
<!-- Smith records task transitions from the typed event log -->

## Blockers

## Milestones
"""
    with open(workspace_path / "PROJECT_STATE.md", "w", encoding="utf-8") as f:
        f.write(project_state_content)
        
    # 2. management/BACKLOG.md
    backlog_dir = workspace_path / "management"
    backlog_dir.mkdir(parents=True, exist_ok=True)
    backlog_content = render_backlog(state)
    with open(backlog_dir / "BACKLOG.md", "w", encoding="utf-8") as f:
        f.write(backlog_content)
        
    # 3. CURRENT_TASK.md
    current_task_content = render_current_task(state)
    with open(workspace_path / "CURRENT_TASK.md", "w", encoding="utf-8") as f:
        f.write(current_task_content)

def detect_markdown_drift(state: ProjectState, workspace_root: str) -> Dict[str, bool]:
    workspace_path = Path(workspace_root)
    drift = {}
    
    # Check PROJECT_STATE.md
    ps_file = workspace_path / "PROJECT_STATE.md"
    if not ps_file.exists():
        drift["PROJECT_STATE.md"] = True
    else:
        actual_fields = {}
        with open(ps_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("- **"):
                    parts = line.strip().split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().strip("- *")
                        val = parts[1].strip()
                        actual_fields[key] = val
        
        has_drift = False
        if actual_fields.get("project_id") != state.project_id:
            has_drift = True
        if actual_fields.get("phase") != state.phase:
            has_drift = True
        if actual_fields.get("active_task") != state.active_task:
            has_drift = True
        if actual_fields.get("waiting_for") != state.waiting_for:
            has_drift = True
        drift["PROJECT_STATE.md"] = has_drift

    # Check BACKLOG.md
    backlog_file = workspace_path / "management" / "BACKLOG.md"
    if not backlog_file.exists():
        drift["BACKLOG.md"] = True
    else:
        expected = render_backlog(state).strip()
        actual = backlog_file.read_text(encoding="utf-8").strip()
        drift["BACKLOG.md"] = (expected != actual)

    # Check CURRENT_TASK.md
    ct_file = workspace_path / "CURRENT_TASK.md"
    if not ct_file.exists():
        drift["CURRENT_TASK.md"] = True
    else:
        expected = render_current_task(state).strip()
        actual = ct_file.read_text(encoding="utf-8").strip()
        drift["CURRENT_TASK.md"] = (expected != actual)
        
    return drift
