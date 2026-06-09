import pytest
from datetime import datetime, timedelta
from AgenticTeam.scripts.v4_contracts import (
    TaskPackV4, WorkResultV4, EventV4, OracleResultV4, 
    validate_work_result_v4, validate_oracle_result_v4
)

def test_task_pack_valid():
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root="/tmp/test",
        allowed_artifacts=["file1.txt"]
    )
    assert tp.task_id == "T001"
    assert "file1.txt" in tp.allowed_artifacts

def test_task_pack_invalid_id():
    with pytest.raises(ValueError, match="task_id must match T###"):
        TaskPackV4(
            project_id="p1",
            task_id="invalid",
            workspace_root="/tmp/test"
        )

def test_work_result_valid_success():
    wr = WorkResultV4(
        task_id="T001",
        attempt_id="A001",
        status="DONE",
        summary="All good",
        output={"result": "ok"}
    )
    assert validate_work_result_v4(wr) is True

def test_work_result_not_done():
    wr = WorkResultV4(
        task_id="T001",
        attempt_id="A001",
        status="IN_PROGRESS",
        summary="Working..."
    )
    assert validate_work_result_v4(wr) is True

def test_work_result_invalid_done():
    wr = WorkResultV4(
        task_id="T001",
        attempt_id="A001",
        status="DONE",
        summary="Empty results",
        output={},
        evidence={}
    )
    assert validate_work_result_v4(wr) is False

def test_event_v4_valid():
    event = EventV4(
        event_type="test_event",
        payload={"data": 123},
        actor="test_actor"
    )
    assert event.event_type == "test_event"
    assert event.actor == "test_actor"
    assert "payload" in event.model_dump()

def test_oracle_result_valid():
    oracle = OracleResultV4(
        project_id="p1",
        task_id="T001",
        status="PASS",
        evidence_paths=["/tmp/test/evidence.txt"],
        summary="Verified"
    )
    assert validate_oracle_result_v4(oracle) is True

def test_oracle_result_invalid():
    oracle = OracleResultV4(
        project_id="p1",
        task_id="T001",
        status="PASS",
        evidence_paths=[],
        summary="No evidence"
    )
    assert validate_oracle_result_v4(oracle) is False
