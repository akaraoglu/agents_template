import pytest
import os
import json
import datetime
from pathlib import Path
from AgenticTeam.scripts.contracts import Event
from AgenticTeam.scripts.state import (
    ProjectState,
    project_state_from_events,
    write_state,
    render_markdown_views,
    detect_markdown_drift
)

def test_state_projection():
    # 1. Test project creation event
    ev1 = Event(
        event_type="project_created",
        payload={"project_id": "test-p1", "title": "Test Project"},
        actor="smith"
    )
    
    # 2. Test task planned event
    ev2 = Event(
        event_type="task_planned",
        payload={"task_id": "T001", "title": "First task"},
        actor="smith"
    )
    
    # 3. Test task started event
    ev3 = Event(
        event_type="task_started",
        payload={"task_id": "T001", "attempt_id": "att-1"},
        actor="smith"
    )
    
    state = project_state_from_events([ev1, ev2, ev3])
    
    assert state.project_id == "test-p1"
    assert state.title == "Test Project"
    assert state.phase == "IN_PROGRESS"
    assert state.active_task == "T001"
    assert state.active_attempt == "att-1"
    assert state.waiting_for == "worker"
    assert "T001" in state.tasks
    assert state.tasks["T001"]["status"] == "READY"
    
    # 4. Test task completed
    ev_completed = Event(
        event_type="task_completed",
        payload={"task_id": "T001"},
        actor="worker"
    )
    # 5. Test task accepted
    ev5 = Event(
        event_type="task_accepted",
        payload={"task_id": "T001", "result": {"output_file": "src/main.py"}},
        actor="smith"
    )
    
    state2 = project_state_from_events([ev1, ev2, ev3, ev_completed, ev5])
    assert state2.phase == "IN_PROGRESS"
    assert state2.active_task == "none"
    assert state2.last_completed_task == "T001"
    assert state2.last_result == {"output_file": "src/main.py"}
    assert state2.tasks["T001"]["status"] == "DONE"

def test_write_and_render_and_drift(tmp_path):
    ev1 = Event(
        event_type="project_created",
        payload={"project_id": "test-p1", "title": "Test Project"},
        actor="smith"
    )
    ev2 = Event(
        event_type="task_planned",
        payload={"task_id": "T001", "title": "First task"},
        actor="smith"
    )
    ev3 = Event(
        event_type="task_started",
        payload={"task_id": "T001", "attempt_id": "att-1"},
        actor="smith"
    )
    
    state = project_state_from_events([ev1, ev2, ev3])
    
    # Write state
    write_state(state, str(tmp_path))
    state_json_file = tmp_path / ".openclaw" / "state.json"
    assert state_json_file.exists()
    
    with open(state_json_file, "r") as f:
        data = json.load(f)
    assert data["project_id"] == "test-p1"
    assert data["active_task"] == "T001"
    
    # Render markdown views
    render_markdown_views(state, str(tmp_path))
    
    assert (tmp_path / "PROJECT_STATE.md").exists()
    assert (tmp_path / "management" / "BACKLOG.md").exists()
    assert (tmp_path / "CURRENT_TASK.md").exists()
    
    # Drift detection
    drift = detect_markdown_drift(state, str(tmp_path))
    assert not any(drift.values()), f"Drift detected when there shouldn't be: {drift}"
    
    # Induce drift in CURRENT_TASK.md
    with open(tmp_path / "CURRENT_TASK.md", "a") as f:
        f.write("\nDrift text\n")
        
    drift_after = detect_markdown_drift(state, str(tmp_path))
    assert drift_after["CURRENT_TASK.md"] is True
