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
    smith_expand_allowed_artifacts_for_block,
    smith_record_scope_expansion,
    smith_render_oracle_repair_task,
    smith_repair_artifact_policy,
    SmithConductorError
)
from AgenticTeam.scripts.v4_contracts import EventV4
from AgenticTeam.scripts.v4_events import append_event_v4, clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_leases import release_lease
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
    assert (tmp_path / "BRIEF.md").exists()
    assert (tmp_path / "management" / "PLAN.md").exists()
    assert (tmp_path / "management" / "BACKLOG.md").exists()
    assert (tmp_path / "management" / "tasks" / "T001.md").exists()
    assert (tmp_path / "management" / "tasks" / "T002.md").exists()
    assert (tmp_path / "management" / "architecture").is_dir()
    assert (tmp_path / "management" / "validation").is_dir()
    assert (tmp_path / "CURRENT_TASK.md").exists()
    assert (tmp_path / ".openclaw" / "state.json").exists()
    assert (tmp_path / ".openclaw" / "events.jsonl").exists()

    plan_text = (tmp_path / "management" / "PLAN.md").read_text(encoding="utf-8")
    assert "T001: Implement Fibonacci" in plan_text
    assert "T002: Add tests" in plan_text
    
    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data = json.load(f)
    assert state_data["project_id"] == "fib-project"
    assert state_data["phase"] == "PLANNING"
    assert "T001" in state_data["tasks"]
    assert state_data["tasks"]["T001"]["status"] == "PENDING"
    assert "writable_paths" in state_data["tasks"]["T001"]
    assert "protected_paths" in state_data["tasks"]["T001"]
    
    # 2. Test Dispatch
    lease = smith_dispatch_worker(str(tmp_path), "T001", "worker-1")
    assert lease is not None
    assert lease.resource_id == "T001"
    assert "writable_paths" in lease.metadata
    assert "protected_paths" in lease.metadata
    
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

    project_state_text = (tmp_path / "PROJECT_STATE.md").read_text(encoding="utf-8")
    assert "- **phase**: DONE" in project_state_text
    assert "- **waiting_for**: none" in project_state_text


def test_smith_syncs_state_when_oracle_pass_event_already_exists(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci"}
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)

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

    oracle_lease = smith_dispatch_oracle(str(tmp_path), "oracle-1")
    append_event_v4(
        EventV4(
            event_type="oracle_passed",
            payload={
                "project_id": "fib-project",
                "task_id": "none",
                "status": "PASS",
                "evidence_paths": ["tests/test_main.py"],
                "summary": "Oracle already passed.",
            },
            actor="oracle-1",
        )
    )

    or_res = OracleResultV4(
        project_id="fib-project",
        task_id="none",
        status="PASS",
        evidence_paths=["tests/test_main.py"],
        summary="Oracle already passed.",
    )
    smith_handle_oracle_result(str(tmp_path), or_res, oracle_lease.lease_id, "oracle-1")

    with open(tmp_path / ".openclaw" / "state.json", "r") as f:
        state_data = json.load(f)
    assert state_data["phase"] == "DONE"
    assert state_data["waiting_for"] == "none"

    project_state_text = (tmp_path / "PROJECT_STATE.md").read_text(encoding="utf-8")
    assert "- **phase**: DONE" in project_state_text
    assert "- **waiting_for**: none" in project_state_text

def test_smith_oracle_fail_flow(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement Fibonacci", "required_outputs": ["src/main.py", "README.md"]}
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
    assert state_data2["tasks"]["T002"]["title"] == "Repair project based on Oracle failure T002"
    assert state_data2["tasks"]["T002"]["expected_artifacts"] == [
        "src/main.py",
        "README.md",
        "tests/test_main.py",
    ]
    assert "src/**" in state_data2["tasks"]["T002"]["writable_paths"]
    assert "tests/**" in state_data2["tasks"]["T002"]["writable_paths"]
    assert "PROJECT.md" in state_data2["tasks"]["T002"]["protected_paths"]
    repair_task = tmp_path / "management" / "tasks" / "T002.md"
    assert repair_task.exists()
    repair_text = repair_task.read_text(encoding="utf-8")
    assert "Repair project based on Oracle verification failure" in repair_text
    assert "Tests fail." in repair_text
    assert "`tests/test_main.py`" in repair_text
    assert "`src/main.py`" in repair_text
    assert "## Writable Paths" in repair_text
    assert "Expected Artifacts are the required deliverables" in repair_text


def test_smith_oracle_repair_dispatch_has_executable_contract(tmp_path):
    planned_tasks = [
        {"task_id": "T001", "title": "Implement source", "required_outputs": ["src/main.py", "README.md"]},
        {"task_id": "T002", "title": "Add tests", "required_outputs": ["tests/test_main.py"]},
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)

    for task_id in ("T001", "T002"):
        lease = smith_dispatch_worker(str(tmp_path), task_id, "worker-1")
        wr = WorkResultV4(
            task_id=task_id,
            attempt_id=lease.metadata["attempt_id"],
            status="DONE",
            summary=f"Done {task_id}",
            output={"ok": True},
            evidence={"ok": True},
        )
        smith_accept_work_result(str(tmp_path), wr, lease.lease_id, "worker-1")

    oracle_lease = smith_dispatch_oracle(str(tmp_path), "oracle-1")
    smith_handle_oracle_result(
        str(tmp_path),
        OracleResultV4(
            project_id="fib-project",
            task_id="none",
            status="FAIL",
            evidence_paths=["src/main.py", "tests/test_main.py", "PROJECT.md"],
            summary="render_tree is missing and tests fail.",
        ),
        oracle_lease.lease_id,
        "oracle-1",
    )

    repair_lease = smith_dispatch_worker(str(tmp_path), "T003", "morpheus")

    assert repair_lease is not None
    assert repair_lease.metadata["expected_artifacts"] == ["src/main.py", "README.md", "tests/test_main.py"]
    assert "src/**" in repair_lease.metadata["writable_paths"]
    assert "tests/**" in repair_lease.metadata["writable_paths"]
    assert "PROJECT.md" in repair_lease.metadata["protected_paths"]


def test_smith_repair_artifact_policy_uses_project_contract_then_oracle_evidence():
    policy = smith_repair_artifact_policy(
        {
            "T001": {
                "expected_artifacts": ["src/main.py", "README.md"],
                "writable_paths": ["src/**", "tests/**", "README.md"],
                "protected_paths": ["PROJECT.md", ".openclaw/**"],
            }
        },
        OracleResultV4(
            project_id="fib-project",
            task_id="none",
            status="FAIL",
            evidence_paths=["tests/test_main.py", "PROJECT.md", "../bad"],
            summary="Tests fail.",
        ),
    )

    assert policy["expected_artifacts"] == ["src/main.py", "README.md", "tests/test_main.py"]
    assert policy["writable_paths"] == ["src/**", "tests/**", "README.md"]
    assert policy["protected_paths"] == ["PROJECT.md", ".openclaw/**"]


def test_smith_oracle_repair_task_is_generic():
    oracle_result = OracleResultV4(
        project_id="fib-project",
        task_id="none",
        status="FAIL",
        evidence_paths=["src/main.py"],
        summary="Rendered output is numeric-only.",
    )

    body = smith_render_oracle_repair_task("T002", oracle_result)

    assert "PROJECT.md" in body
    assert "Rendered output is numeric-only." in body
    assert "`src/main.py`" in body
    assert "Expected Artifacts" in body
    assert "Do not change the project goal" in body


def test_smith_expands_scope_for_known_project_artifact_block():
    expanded = smith_expand_allowed_artifacts_for_block(
        ["tests/test_main.py", "README.md"],
        "Cannot modify src/main.py as it is not an allowed artifact.",
        ["src/main.py", "README.md", "tests/test_main.py"],
    )

    assert expanded == ["tests/test_main.py", "README.md", "src/main.py"]


def test_smith_does_not_expand_scope_for_unknown_or_vague_block():
    known = ["src/main.py", "README.md", "tests/test_main.py"]

    assert smith_expand_allowed_artifacts_for_block(
        ["tests/test_main.py"],
        "Cannot modify secrets.env as it is not an allowed artifact.",
        known,
    ) is None

    assert smith_expand_allowed_artifacts_for_block(
        ["tests/test_main.py"],
        "Tests are failing in src/main.py.",
        known,
    ) is None


def test_smith_records_scope_expansion_and_can_retry_task(tmp_path):
    planned_tasks = [
        {"task_id": "T004", "title": "Add tests"}
    ]
    smith_plan_project(str(tmp_path), "fib-project", "Fibonacci project", planned_tasks)

    lease1 = smith_dispatch_worker(str(tmp_path), "T004", "morpheus")
    assert lease1 is not None
    append_event_v4(
        EventV4(
            event_type="work_blocked",
            payload={
                "task_id": "T004",
                "attempt_id": lease1.metadata["attempt_id"],
                "reason": "Cannot modify src/main.py as it is not an allowed artifact.",
            },
            actor="morpheus",
        )
    )
    release_lease(str(tmp_path), lease1.lease_id)

    expanded = smith_expand_allowed_artifacts_for_block(
        ["tests/test_main.py", "README.md"],
        "Cannot modify src/main.py as it is not an allowed artifact.",
        ["src/main.py", "README.md", "tests/test_main.py"],
    )
    assert expanded == ["tests/test_main.py", "README.md", "src/main.py"]
    smith_record_scope_expansion(
        str(tmp_path),
        "T004",
        ["tests/test_main.py", "README.md"],
        expanded,
        "Cannot modify src/main.py as it is not an allowed artifact.",
    )

    lease2 = smith_dispatch_worker(str(tmp_path), "T004", "morpheus")
    assert lease2 is not None
    assert lease2.lease_id != lease1.lease_id

    events = read_events_v4()
    assert any(ev.event_type == "task_scope_expanded" for ev in events)
    state = project_state_from_events(events)
    assert state.phase == "IN_PROGRESS"
    assert state.active_task == "T004"
    assert state.tasks["T004"]["status"] == "READY"
    assert state.tasks["T004"]["expected_artifacts"] == expanded
