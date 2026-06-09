import pytest
import os
import json
import datetime
from pathlib import Path
from AgenticTeam.scripts.v4_contracts import WorkResultV4, OracleResultV4
from AgenticTeam.scripts.v4_smith import (
    smith_plan_project,
    smith_dispatch_worker,
    smith_accept_work_result,
    smith_dispatch_oracle,
    smith_handle_oracle_result,
    SmithConductorError
)
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_state import project_state_from_events

@pytest.fixture(autouse=True)
def clean_logs():
    clear_events_v4()
    yield
    clear_events_v4()

def test_smith_planning_and_dispatch(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci"},
        {"task_id": "T002", "title": "Add tests"}
    ]
    
    # 1. Test Planning
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)
    
    assert (tmp_path / "PROJECT_STATE.md").exists()
    assert (tmp_path / "management" / "BACKLOG.md").exists()
    assert (tmp_path / "CURRENT_TASK.md").exists()
    assert (tmp_path / ".openclaw" / "state.json").exists()
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data = json.load(f)
    assert state_data["project_id"] == "fib-project"
    assert state_data["phase"] == "PLANNING"
    assert "T001" in state_data["tasks"]
    assert state_data["tasks"]["T001"]["status"] == "PENDING"
    
    # 2. Test Dispatch
    lease = smith_dispatch_worker(str(tmp_path), "T001", "worker-1")
    assert lease is not None
    assert lease.resource_id == "T001"
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data2 = json.load(f)
    assert state_data2["phase"] == "IN_PROGRESS"
    assert state_data2["active_task"] == "T001"
    assert state_data2["waiting_for"] == "worker"
    assert state_data2["tasks"]["T001"]["status"] == "READY"
    
    # 3. Collision check
    lease2 = smith_dispatch_worker(str(tmp_path), "T001", "worker-2")
    assert lease2 is None # Locked

def test_smith_result_handling(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci"},
        {"task_id": "T002", "title": "Add tests"}
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)
    
    # Dispatch T001
    lease = smith_dispatch_worker(str(tmp_path), "T001", "worker-1")
    
    # Submit T001 WorkResult
    wr = WorkResultV4(
        task_id="T001",
        attempt_id=lease.metadata["attempt_id"],
        status="DONE",
        summary="Completed T001",
        output={"file": "src/main.py"},
        evidence={"tests": "passed"}
    )
    
    # Accept WorkResult
    smith_accept_work_result(str(tmp_path), wr, lease.lease_id, "worker-1")
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data = json.load(f)
    assert state_data["tasks"]["T001"]["status"] == "DONE"
    assert state_data["active_task"] == "none"
    assert state_data["last_completed_task"] == "T001"
    
    # Out of order result check (submitting T002 when not active)
    wr_out_of_order = WorkResultV4(
        task_id="T002",
        attempt_id="stale-att",
        status="DONE",
        output={"ok": True}
    )
    with pytest.raises(SmithConductorError, match="stale_lease"):
        smith_accept_work_result(str(tmp_path), wr_out_of_order, "invalid-lease", "worker-1")

def test_smith_oracle_verification_flow(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci"}
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)
    
    # Complete T001
    lease = smith_dispatch_worker(str(tmp_path), "T001", "worker-1")
    wr = WorkResultV4(
        task_id="T001",
        attempt_id=lease.metadata["attempt_id"],
        status="DONE",
        summary="Done T001",
        output={"ok": True},
        evidence={"ok": True}
    )
    smith_accept_work_result(str(tmp_path), wr, lease.lease_id, "worker-1")
    
    # Dispatch Oracle
    oracle_lease = smith_dispatch_oracle(str(tmp_path), "oracle-1")
    assert oracle_lease is not None
    assert oracle_lease.resource_id == "none"
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data = json.load(f)
    assert state_data["waiting_for"] == "oracle"
    
    # Submit OracleResult PASS
    or_res = OracleResultV4(
        project_id="fib-project",
        task_id="none",
        status="PASS",
        evidence_paths=["tests/test_main.py"],
        summary="Whole project verifies successfully."
    )
    
    smith_handle_oracle_result(str(tmp_path), or_res, oracle_lease.lease_id, "oracle-1")
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data2 = json.load(f)
    assert state_data2["phase"] == "DONE"
    assert state_data2["waiting_for"] == "none"

def test_smith_oracle_fail_flow(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci"}
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)
    
    # Complete T001
    lease = smith_dispatch_worker(str(tmp_path), "T001", "worker-1")
    wr = WorkResultV4(
        task_id="T001",
        attempt_id=lease.metadata["attempt_id"],
        status="DONE",
        summary="Done T001",
        output={"ok": True},
        evidence={"ok": True}
    )
    smith_accept_work_result(str(tmp_path), wr, lease.lease_id, "worker-1")
    
    # Dispatch Oracle
    oracle_lease = smith_dispatch_oracle(str(tmp_path), "oracle-1")
    assert oracle_lease is not None
    
    # Submit OracleResult FAIL
    or_res = OracleResultV4(
        project_id="fib-project",
        task_id="none",
        status="FAIL",
        evidence_paths=["tests/test_main.py"],
        summary="Tests fail."
    )
    
    smith_handle_oracle_result(str(tmp_path), or_res, oracle_lease.lease_id, "oracle-1")
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data2 = json.load(f)
    # Project should be BLOCKED (project_blocked sets state.phase = "BLOCKED")
    assert state_data2["phase"] == "BLOCKED"
    # A new repair task T002 should be planned
    assert "T002" in state_data2["tasks"]
    assert state_data2["tasks"]["T002"]["status"] == "PENDING"

