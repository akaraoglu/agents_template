from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from AgenticTeam.scripts.v4_contracts import TaskPackV4
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_leases import acquire_lease
from AgenticTeam.scripts.v4_openclaw_worker import (
    RESULT_BEGIN,
    RESULT_END,
    V4OpenClawWorkerRunner,
    extract_marked_json,
)


@pytest.fixture(autouse=True)
def project_event_file(tmp_path, monkeypatch):
    monkeypatch.setenv("V4_EVENT_FILE", str(tmp_path / ".openclaw" / "events.jsonl"))
    clear_events_v4()
    yield
    clear_events_v4()


def make_runner(tmp_path: Path) -> V4OpenClawWorkerRunner:
    task_pack = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        expected_artifacts=["src/main.py", "README.md"],
    )
    lease = acquire_lease(
        str(tmp_path),
        "T001",
        "morpheus",
        duration_seconds=300,
        metadata={"project_id": "p1", "task_id": "T001", "attempt_id": "att-1"},
    )
    assert lease is not None
    return V4OpenClawWorkerRunner(task_pack, lease, actor="morpheus", timeout_seconds=30)


def completed_stdout(payload: dict) -> str:
    return f"noise\n{RESULT_BEGIN}\n{json.dumps(payload)}\n{RESULT_END}\n"


def test_openclaw_worker_success_submits_work_result(tmp_path):
    runner = make_runner(tmp_path)

    def fake_run(*args, **kwargs):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout=completed_stdout(
                {
                    "status": "DONE",
                    "summary": "implemented",
                    "output": {"artifacts": ["src/main.py", "README.md"]},
                    "evidence": {"validation": "inspected"},
                }
            ),
            stderr="",
        )

    with mock.patch("subprocess.run", side_effect=fake_run) as run_mock:
        assert runner.run() == "Success"

    command = run_mock.call_args.args[0]
    assert command[:4] == ["openclaw", "agent", "--agent", "morpheus"]
    events = read_events_v4()
    assert [event.event_type for event in events] == ["work_submitted"]
    assert events[0].payload["task_id"] == "T001"


def test_openclaw_worker_nonzero_records_agent_failure(tmp_path):
    runner = make_runner(tmp_path)
    with mock.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(["openclaw"], 42, stdout="bad", stderr="failed"),
    ):
        result = runner.run()

    assert "exited with code 42" in result
    events = read_events_v4()
    assert [event.event_type for event in events] == ["worker_agent_failed"]
    assert events[0].payload["reason_code"] == "agent_exit_nonzero"


def test_openclaw_worker_rejects_protected_project_file_change(tmp_path):
    runner = make_runner(tmp_path)

    def fake_run(*args, **kwargs):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# ok\n", encoding="utf-8")
        (tmp_path / "PROJECT_STATE.md").write_text("tampered\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout=completed_stdout({"status": "DONE", "summary": "done"}),
            stderr="",
        )

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = runner.run()

    assert "write_boundary_violation" in result
    events = read_events_v4()
    assert [event.event_type for event in events] == ["worker_agent_failed"]
    assert events[0].payload["reason_code"] == "write_boundary_violation"


def test_extract_marked_json_requires_marker_envelope():
    assert extract_marked_json(
        f"{RESULT_BEGIN}\n{{\"status\":\"DONE\"}}\n{RESULT_END}",
        RESULT_BEGIN,
        RESULT_END,
    ) == {"status": "DONE"}

    with pytest.raises(ValueError, match="did not include"):
        extract_marked_json('{"status":"DONE"}', RESULT_BEGIN, RESULT_END)
