import json
import os
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from AgenticTeam.scripts.v4_contracts import EventV4, WorkResultV4, OracleResultV4, LeaseV4
from AgenticTeam.scripts.v4_events import append_event_v4, read_events_v4
from AgenticTeam.scripts.v4_state import project_state_from_events, write_state_v4, render_markdown_views
from AgenticTeam.scripts.v4_leases import acquire_lease, release_lease, validate_lease

class SmithConductorError(Exception):
    pass

def smith_plan_project(workspace_root: str, project_id: str, title: str, planned_tasks: List[Dict[str, str]]):
    """
    Initializes a new project by planning tasks.
    Appends project_created and task_planned events.
    """
    # 1. Emit project_created
    ev_proj = EventV4(
        event_type="project_created",
        payload={"project_id": project_id, "title": title},
        actor="smith"
    )
    append_event_v4(ev_proj)
    
    # 2. Emit task_planned for each task
    for t in planned_tasks:
        ev_task = EventV4(
            event_type="task_planned",
            payload={"task_id": t["task_id"], "title": t["title"]},
            actor="smith"
        )
        append_event_v4(ev_task)
        
    # 3. Project state and render
    events = read_events_v4()
    state = project_state_from_events(events)
    write_state_v4(state, workspace_root)
    render_markdown_views(state, workspace_root)

def smith_dispatch_worker(workspace_root: str, task_id: str, actor: str, duration_seconds: int = 300) -> Optional[LeaseV4]:
    """
    Dispatches a task to a worker by acquiring a lease on the task_id.
    Emits a task_dispatched event and syncs state.
    """
    events = read_events_v4()
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
        "attempt_id": attempt_id
    }
    
    lease = acquire_lease(workspace_root, task_id, actor, duration_seconds, metadata)
    if not lease:
        # Cannot acquire lease (already locked)
        return None
        
    # Emit task_dispatched
    ev_disp = EventV4(
        event_type="task_dispatched",
        payload={
            "task_id": task_id,
            "attempt_id": attempt_id,
            "lease_id": lease.lease_id,
            "actor": actor
        },
        actor="smith"
    )
    append_event_v4(ev_disp)
    
    # Sync state and render
    events = read_events_v4()
    state = project_state_from_events(events)
    write_state_v4(state, workspace_root)
    render_markdown_views(state, workspace_root)
    
    return lease

def smith_accept_work_result(workspace_root: str, work_result: WorkResultV4, lease_id: str, actor: str):
    """
    Processes a worker's WorkResultV4.
    If valid and DONE, marks task done and releases the lease.
    If FAILED or BLOCKED, puts project into BLOCKED phase.
    """
    events = read_events_v4()
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
        ev_ok = EventV4(
            event_type="work_accepted",
            payload={
                "task_id": work_result.task_id,
                "attempt_id": work_result.attempt_id,
                "result": work_result.output
            },
            actor="smith"
        )
        append_event_v4(ev_ok)
        
        # Release lease
        release_lease(workspace_root, lease_id)
        
    elif work_result.status.upper() in ("FAILED", "BLOCKED"):
        # Emit work_blocked
        ev_fail = EventV4(
            event_type="work_blocked",
            payload={
                "task_id": work_result.task_id,
                "attempt_id": work_result.attempt_id,
                "reason": work_result.repair_reason or "Worker reported failure/block."
            },
            actor="smith"
        )
        append_event_v4(ev_fail)
        
        # Release lease
        release_lease(workspace_root, lease_id)
        
    # Re-project and update views
    events = read_events_v4()
    state = project_state_from_events(events)
    write_state_v4(state, workspace_root)
    render_markdown_views(state, workspace_root)

def smith_dispatch_oracle(workspace_root: str, actor: str = "oracle-1", duration_seconds: int = 300) -> Optional[LeaseV4]:
    """
    Dispatches project verification to Oracle after all tasks are completed.
    Acquires a lease on task_id='none' or task_id='project' representing verification phase.
    """
    events = read_events_v4()
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
    ev_or = EventV4(
        event_type="oracle_dispatched",
        payload={"lease_id": lease.lease_id, "actor": actor},
        actor="smith"
    )
    append_event_v4(ev_or)
    
    # Sync state and render
    events = read_events_v4()
    state = project_state_from_events(events)
    write_state_v4(state, workspace_root)
    render_markdown_views(state, workspace_root)
    
    return lease

def smith_handle_oracle_result(workspace_root: str, oracle_result: OracleResultV4, lease_id: str, actor: str):
    """
    Handles OracleResultV4.
    If PASS, transitions project state to DONE.
    If FAIL, transitions project state to BLOCKED and creates a repair task.
    """
    events = read_events_v4()
    state = project_state_from_events(events)
    
    # Validate lease
    if not validate_lease(workspace_root, lease_id, "none", actor, "oracle-attempt"):
        raise SmithConductorError("stale_lease")
        
    if state.phase == "DONE":
        # Idempotent: don't process PASS twice
        release_lease(workspace_root, lease_id)
        return
        
    if oracle_result.status.upper() == "PASS":
        # Emit project_done event
        ev_done = EventV4(
            event_type="project_done",
            payload={"summary": oracle_result.summary},
            actor="smith"
        )
        append_event_v4(ev_done)
        
    else:
        # Emit project_blocked event
        ev_block = EventV4(
            event_type="project_blocked",
            payload={"reason": oracle_result.summary, "evidence_paths": oracle_result.evidence_paths},
            actor="smith"
        )
        append_event_v4(ev_block)
        
        # Create a repair task for Morpheus/Worker
        tids = [int(tid[1:]) for tid in state.tasks.keys() if tid.startswith("T") and tid[1:].isdigit()]
        next_num = max(tids) + 1 if tids else 1
        next_tid = f"T{next_num:03d}"
        
        ev_repair = EventV4(
            event_type="task_planned",
            payload={
                "task_id": next_tid,
                "title": f"Repair project based on Oracle failure: {oracle_result.summary}"
            },
            actor="smith"
        )
        append_event_v4(ev_repair)
        
    # Release lease
    release_lease(workspace_root, lease_id)
    
    # Sync state and render
    events = read_events_v4()
    state = project_state_from_events(events)
    write_state_v4(state, workspace_root)
    render_markdown_views(state, workspace_root)
