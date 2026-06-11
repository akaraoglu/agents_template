import json
import os
import datetime
import posixpath
from pathlib import Path
from typing import List, Dict, Any, Optional

from AgenticTeam.scripts.contracts import (
    DEFAULT_PROTECTED_PATHS,
    DEFAULT_WRITABLE_PATHS,
    Event,
    WorkResult,
    OracleResult,
    Lease,
)
from AgenticTeam.scripts.events import append_event, read_events
from AgenticTeam.scripts.state import project_state_from_events, write_state, render_markdown_views
from AgenticTeam.scripts.leases import acquire_lease, release_lease, validate_lease
from AgenticTeam.scripts.project_layout import ensure_project_layout, render_task_md, write_planning_files

class SmithConductorError(Exception):
    pass


_SCOPE_BLOCK_MARKERS = (
    "allowed artifact",
    "not allowed",
    "path_not_allowed",
    "cannot modify",
    "cannot edit",
    "cannot write",
    "cannot patch",
)

_EVIDENCE_ARTIFACT_FORBIDDEN_CHARS = set("()[]{}<>|:;")


def _normalize_artifact_path(path: str) -> str:
    normalized = posixpath.normpath(str(path).replace("\\", "/")).strip("/")
    if normalized in ("", ".", "..") or normalized.startswith("../"):
        raise SmithConductorError(f"invalid_artifact_path:{path}")
    return normalized


def _normalize_evidence_artifact_path(path: str) -> Optional[str]:
    raw = str(path or "").strip().strip("`")
    if not raw or any(ch.isspace() for ch in raw):
        return None
    if any(ch in raw for ch in _EVIDENCE_ARTIFACT_FORBIDDEN_CHARS):
        return None
    try:
        return _normalize_artifact_path(raw)
    except SmithConductorError:
        return None


def _dedupe_artifacts(paths: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for path in paths:
        normalized = _normalize_artifact_path(path)
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _dedupe_path_rules(paths: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for path in paths:
        normalized = _normalize_artifact_path(path)
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _matches_path_rule(normalized: str, rule: str) -> bool:
    if rule.endswith("/**"):
        prefix = rule[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return normalized == rule


def _is_writable_artifact(path: str, writable_paths: List[str], protected_paths: List[str]) -> bool:
    return (
        any(_matches_path_rule(path, rule) for rule in writable_paths)
        and not any(_matches_path_rule(path, rule) for rule in protected_paths)
    )


def smith_repair_artifact_policy(
    tasks: Dict[str, Dict[str, Any]],
    oracle_result: OracleResult,
) -> Dict[str, List[str]]:
    """
    Build the artifact policy for an Oracle repair task from project-owned data.

    Existing task contracts are the primary source of truth. Oracle evidence paths
    can extend expected artifacts only when they are inside the writable project
    scope and outside protected control files.
    """
    expected_artifacts: List[str] = []
    writable_paths: List[str] = []
    protected_paths: List[str] = []

    for task in tasks.values():
        expected_artifacts.extend(task.get("expected_artifacts") or [])
        writable_paths.extend(task.get("writable_paths") or [])
        protected_paths.extend(task.get("protected_paths") or [])

    writable_paths = _dedupe_path_rules(writable_paths or list(DEFAULT_WRITABLE_PATHS))
    protected_paths = _dedupe_path_rules(protected_paths or list(DEFAULT_PROTECTED_PATHS))

    for evidence_path in oracle_result.evidence_paths or []:
        normalized = _normalize_evidence_artifact_path(evidence_path)
        if normalized is None:
            continue
        if _is_writable_artifact(normalized, writable_paths, protected_paths):
            expected_artifacts.append(normalized)

    return {
        "expected_artifacts": _dedupe_artifacts(expected_artifacts),
        "writable_paths": writable_paths,
        "protected_paths": protected_paths,
    }


def smith_expand_allowed_artifacts_for_block(
    current_allowed_artifacts: List[str],
    block_reason: str,
    known_project_artifacts: List[str],
) -> Optional[List[str]]:
    """
    Return an expanded artifact scope when a worker blocks only because it needs a
    known project artifact that was omitted from the current TaskPack.
    """
    reason_text = str(block_reason or "").replace("\\", "/")
    reason_lower = reason_text.lower()
    if not any(marker in reason_lower for marker in _SCOPE_BLOCK_MARKERS):
        return None

    current = _dedupe_artifacts(current_allowed_artifacts)
    known = _dedupe_artifacts(known_project_artifacts)
    additions = [path for path in known if path not in current and path in reason_text]
    if not additions:
        return None

    return current + additions


def smith_record_scope_expansion(
    workspace_root: str,
    task_id: str,
    previous_allowed_artifacts: List[str],
    expanded_allowed_artifacts: List[str],
    reason: str,
    actor: str = "smith",
) -> None:
    _bind_project_event_file(workspace_root)
    append_event(
        Event(
            event_type="task_scope_expanded",
            payload={
                "task_id": task_id,
                "previous_allowed_artifacts": _dedupe_artifacts(previous_allowed_artifacts),
                "expanded_allowed_artifacts": _dedupe_artifacts(expanded_allowed_artifacts),
                "reason": reason,
            },
            actor=actor,
        )
    )


def smith_render_oracle_repair_task(
    task_id: str,
    oracle_result: OracleResult,
    expected_artifacts: Optional[List[str]] = None,
    writable_paths: Optional[List[str]] = None,
    protected_paths: Optional[List[str]] = None,
) -> str:
    summary = oracle_result.summary.strip() or "Oracle verification failed."
    evidence_paths = oracle_result.evidence_paths or []
    evidence_lines = "\n".join(f"- `{path}`" for path in evidence_paths) or "- none"
    expected_lines = "\n".join(f"- `{path}`" for path in (expected_artifacts or [])) or "- See the task pack."
    writable_lines = "\n".join(f"- `{path}`" for path in (writable_paths or [])) or "- See the task pack."
    protected_lines = "\n".join(f"- `{path}`" for path in (protected_paths or [])) or "- See the task pack."
    return f"""# Task {task_id}: Repair project based on Oracle verification failure

## Objective
Repair the project so it satisfies `PROJECT.md` and passes Oracle verification.

## Oracle Failure
{summary}

## Evidence Paths
{evidence_lines}

## Expected Artifacts
{expected_lines}

## Writable Paths
{writable_lines}

## Protected Paths
{protected_lines}

## Required Actions
1. Read `PROJECT.md`, `BRIEF.md`, `management/PLAN.md`, `management/BACKLOG.md`, and the Oracle evidence paths above.
2. Inspect the implementation and tests before editing.
3. Fix the smallest set of allowed project artifacts needed to satisfy the original project goal.
4. Run the relevant validation command.
5. Submit `DONE` only when implementation behavior, tests, and Oracle feedback agree. Submit `BLOCKED` with an exact reason if the repair needs a path outside the task pack.

## Scope
Expected Artifacts are the required deliverables. Writable Paths are the edit boundary. Do not change the project goal.
"""


def smith_write_task_file(workspace_root: str, task: Dict[str, Any]) -> None:
    workspace = Path(workspace_root).resolve()
    task_id = str(task["task_id"])
    task_file = workspace / "management" / "tasks" / f"{task_id}.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(render_task_md(task), encoding="utf-8")


def _bind_project_event_file(workspace_root: str) -> None:
    os.environ["TEAM_EVENT_FILE"] = str(Path(workspace_root).resolve() / ".openclaw" / "events.jsonl")

def smith_plan_project(
    workspace_root: str,
    project_id: str,
    title: str,
    planned_tasks: List[Dict[str, Any]],
    *,
    goal: str = "",
):
    """
    Initializes a new project by planning tasks.
    Appends project_created and task_planned events.
    """
    _bind_project_event_file(workspace_root)
    ensure_project_layout(workspace_root, project_id=project_id, title=title, goal=goal)
    write_planning_files(workspace_root, planned_tasks, title=title)

    # 1. Emit project_created
    ev_proj = Event(
        event_type="project_created",
        payload={"project_id": project_id, "title": title, "goal": goal},
        actor="smith"
    )
    append_event(ev_proj)
    
    # 2. Emit task_planned for each task
    for t in planned_tasks:
        ev_task = Event(
            event_type="task_planned",
            payload={
                "task_id": t["task_id"],
                "title": t["title"],
                "expected_artifacts": _dedupe_artifacts(t.get("required_outputs", [])),
                "writable_paths": t.get("writable_paths", list(DEFAULT_WRITABLE_PATHS)),
                "protected_paths": t.get("protected_paths", list(DEFAULT_PROTECTED_PATHS)),
            },
            actor="smith"
        )
        append_event(ev_task)
        
    # 3. Project state and render
    events = read_events()
    state = project_state_from_events(events)
    write_state(state, workspace_root)
    render_markdown_views(state, workspace_root)

def smith_dispatch_worker(workspace_root: str, task_id: str, actor: str, duration_seconds: int = 300) -> Optional[Lease]:
    """
    Dispatches a task to a worker by acquiring a lease on the task_id.
    Emits a task_dispatched event and syncs state.
    """
    _bind_project_event_file(workspace_root)
    events = read_events()
    state = project_state_from_events(events)
    
    if task_id not in state.tasks:
        raise SmithConductorError(f"Task {task_id} is not planned in the project.")
        
    t = state.tasks[task_id]
    if t["status"] == "DONE":
        raise SmithConductorError(f"Task {task_id} is already completed.")
        
    # Acquire lease
    attempt_id = f"attempt-{datetime.datetime.now(datetime.timezone.utc).strftime('%s')}"
    metadata = {
        "project_id": state.project_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "expected_artifacts": _dedupe_artifacts(t.get("expected_artifacts") or []),
        "writable_paths": _dedupe_path_rules(t.get("writable_paths") or list(DEFAULT_WRITABLE_PATHS)),
        "protected_paths": _dedupe_path_rules(t.get("protected_paths") or list(DEFAULT_PROTECTED_PATHS)),
    }
    
    lease = acquire_lease(workspace_root, task_id, actor, duration_seconds, metadata)
    if not lease:
        # Cannot acquire lease (already locked)
        return None
        
    # Emit task_dispatched
    ev_disp = Event(
        event_type="task_dispatched",
            payload={
                "task_id": task_id,
                "attempt_id": attempt_id,
                "lease_id": lease.lease_id,
                "actor": actor,
                "expected_artifacts": metadata["expected_artifacts"],
                "writable_paths": metadata["writable_paths"],
                "protected_paths": metadata["protected_paths"],
            },
            actor="smith"
    )
    append_event(ev_disp)
    
    # Sync state and render
    events = read_events()
    state = project_state_from_events(events)
    write_state(state, workspace_root)
    render_markdown_views(state, workspace_root)
    
    return lease

def smith_accept_work_result(workspace_root: str, work_result: WorkResult, lease_id: str, actor: str):
    """
    Processes a worker's WorkResult.
    If valid and DONE, marks task done and releases the lease.
    If FAILED or BLOCKED, puts project into BLOCKED phase.
    """
    _bind_project_event_file(workspace_root)
    events = read_events()
    state = project_state_from_events(events)
    
    # 1. Validate lease
    if not validate_lease(workspace_root, lease_id, work_result.task_id, actor, work_result.attempt_id):
        raise SmithConductorError("stale_lease")
        
    # 2. Idempotency checks
    if state.tasks.get(work_result.task_id, {}).get("status") == "DONE":
        # Already done, ignore duplicate submission
        release_lease(workspace_root, lease_id)
        return
        
    # 3. Reject out-of-order results
    # Active task in state must match work_result.task_id
    if state.active_task != work_result.task_id:
        raise SmithConductorError("out_of_order_task_result")
        
    if work_result.status.upper() == "DONE":
        # Emit work_accepted
        ev_ok = Event(
            event_type="work_accepted",
            payload={
                "task_id": work_result.task_id,
                "attempt_id": work_result.attempt_id,
                "result": work_result.output
            },
            actor="smith"
        )
        append_event(ev_ok)
        
        # Release lease
        release_lease(workspace_root, lease_id)
        
    elif work_result.status.upper() in ("FAILED", "BLOCKED"):
        # Emit work_blocked
        ev_fail = Event(
            event_type="work_blocked",
            payload={
                "task_id": work_result.task_id,
                "attempt_id": work_result.attempt_id,
                "reason": work_result.repair_reason or "Worker reported failure/block."
            },
            actor="smith"
        )
        append_event(ev_fail)
        
        # Release lease
        release_lease(workspace_root, lease_id)
        
    # Re-project and update views
    events = read_events()
    state = project_state_from_events(events)
    write_state(state, workspace_root)
    render_markdown_views(state, workspace_root)

def smith_dispatch_oracle(workspace_root: str, actor: str = "oracle-1", duration_seconds: int = 300) -> Optional[Lease]:
    """
    Dispatches project verification to Oracle after all tasks are completed.
    Acquires a lease on task_id='none' or task_id='project' representing verification phase.
    """
    _bind_project_event_file(workspace_root)
    events = read_events()
    state = project_state_from_events(events)
    
    # Check if all planned tasks are done
    all_done = all(t["status"] == "DONE" for t in state.tasks.values())
    if not all_done:
        raise SmithConductorError("Cannot dispatch Oracle verification before all planned tasks are completed.")
        
    # Lease resource is the project verification resource (using 'project-verification' or task_id='none')
    lease = acquire_lease(workspace_root, "none", actor, duration_seconds, {"project_id": state.project_id, "attempt_id": "oracle-attempt"})
    if not lease:
        return None
        
    # Emit oracle_dispatched event
    ev_or = Event(
        event_type="oracle_dispatched",
        payload={"lease_id": lease.lease_id, "actor": actor},
        actor="smith"
    )
    append_event(ev_or)
    
    # Sync state and render
    events = read_events()
    state = project_state_from_events(events)
    write_state(state, workspace_root)
    render_markdown_views(state, workspace_root)
    
    return lease

def smith_handle_oracle_result(workspace_root: str, oracle_result: OracleResult, lease_id: str, actor: str):
    """
    Handles OracleResult.
    If PASS, transitions project state to DONE.
    If FAIL, transitions project state to BLOCKED and creates a repair task.
    """
    _bind_project_event_file(workspace_root)
    events = read_events()
    state = project_state_from_events(events)
    
    # Validate lease
    if not validate_lease(workspace_root, lease_id, "none", actor, "oracle-attempt"):
        raise SmithConductorError("stale_lease")
        
    if state.phase == "DONE":
        # Idempotent: don't process PASS twice
        release_lease(workspace_root, lease_id)
        write_state(state, workspace_root)
        render_markdown_views(state, workspace_root)
        return
        
    if oracle_result.status.upper() == "PASS":
        # Emit project_done event
        ev_done = Event(
            event_type="project_done",
            payload={"summary": oracle_result.summary},
            actor="smith"
        )
        append_event(ev_done)
        
    else:
        # Emit project_blocked event
        ev_block = Event(
            event_type="project_blocked",
            payload={"reason": oracle_result.summary, "evidence_paths": oracle_result.evidence_paths},
            actor="smith"
        )
        append_event(ev_block)
        
        # Create a repair task for Morpheus/Worker
        tids = [int(tid[1:]) for tid in state.tasks.keys() if tid.startswith("T") and tid[1:].isdigit()]
        next_num = max(tids) + 1 if tids else 1
        next_tid = f"T{next_num:03d}"
        repair_title = f"Repair project based on Oracle failure {next_tid}"
        repair_policy = smith_repair_artifact_policy(state.tasks, oracle_result)
        smith_write_task_file(
            workspace_root,
            {
                "task_id": next_tid,
                "title": repair_title,
                "body": smith_render_oracle_repair_task(
                    next_tid,
                    oracle_result,
                    repair_policy["expected_artifacts"],
                    repair_policy["writable_paths"],
                    repair_policy["protected_paths"],
                ),
                "required_outputs": repair_policy["expected_artifacts"],
                "writable_paths": repair_policy["writable_paths"],
                "protected_paths": repair_policy["protected_paths"],
            },
        )
        
        ev_repair = Event(
            event_type="task_planned",
            payload={
                "task_id": next_tid,
                "title": repair_title,
                "expected_artifacts": repair_policy["expected_artifacts"],
                "writable_paths": repair_policy["writable_paths"],
                "protected_paths": repair_policy["protected_paths"],
                "repair_of": "oracle_failed",
            },
            actor="smith"
        )
        append_event(ev_repair)
        
    # Release lease
    release_lease(workspace_root, lease_id)
    
    # Sync state and render
    events = read_events()
    state = project_state_from_events(events)
    write_state(state, workspace_root)
    render_markdown_views(state, workspace_root)
