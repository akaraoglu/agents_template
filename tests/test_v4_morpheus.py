import pytest
import unittest.mock as mock
import json
from pathlib import Path
from AgenticTeam.scripts.v4_contracts import TaskPackV4, LeaseV4
from AgenticTeam.scripts.v4_worker import V4WorkerRunner
from AgenticTeam.scripts.v4_leases import acquire_lease
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_tools import V4ToolError

@pytest.fixture(autouse=True)
def clean_logs():
    clear_events_v4()
    yield
    clear_events_v4()

def test_morpheus_prompt_compilation(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path)
    )
    lease = LeaseV4(
        lease_id="l1",
        resource_id="T001",
        owner="morpheus",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10),
        metadata={}
    )
    runner = V4WorkerRunner(tp, lease)
    prompt = runner._compile_system_prompt()
    
    assert "Morpheus" in prompt
    assert "IDENTITY.md" in prompt or "morpheus" in prompt.lower()
    assert "fs_write" in prompt
    assert "Expected Artifacts are the required deliverables" in prompt
    assert "Writable Paths" in prompt
    assert "Protected Paths" in prompt

def test_morpheus_react_loop_mock_execution(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path)
    )
    
    # Acquire a lease
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"}
    )
    assert lease is not None
    
    runner = V4WorkerRunner(tp, lease)
    
    # Mock Ollama chat responses
    mock_responses = [
        # Turn 1: fs_write
        {
            "message": {
                "content": json.dumps({
                    "thought": "I will write a file.",
                    "tool": "fs_write",
                    "parameters": {"relative_path": "src/main.py", "content": "print('hello')"}
                })
            }
        },
        # Turn 2: work_submit
        {
            "message": {
                "content": json.dumps({
                    "thought": "I will submit the completed task.",
                    "tool": "work_submit",
                    "parameters": {
                        "status": "DONE",
                        "summary": "Completed writing main.py",
                        "output": {"file": "src/main.py"},
                        "evidence": {"written": True}
                    }
                })
            }
        }
    ]
    
    # Mock requests.post
    with mock.patch("requests.post") as mock_post:
        # Create a mock response object
        mock_response_objs = []
        for r in mock_responses:
            m_res = mock.Mock()
            m_res.status_code = 200
            m_res.json.return_value = r
            mock_response_objs.append(m_res)
            
        mock_post.side_effect = mock_response_objs
        
        result = runner.run(max_turns=2)
        
    assert result == "Success"
    assert (tmp_path / "src" / "main.py").exists()
    assert (tmp_path / "src" / "main.py").read_text() == "print('hello')"
    
    # Check events emitted
    events = read_events_v4()
    event_types = [ev.event_type for ev in events]
    assert "fs_write" in event_types
    assert "work_submitted" in event_types
    
    submitted_event = next(ev for ev in events if ev.event_type == "work_submitted")
    assert submitted_event.payload["task_id"] == "T001"
    assert submitted_event.payload["attempt_id"] == "att-1"

def test_morpheus_can_write_tests_when_only_source_is_expected(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        expected_artifacts=["src/main.py"]
    )
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"}
    )
    assert lease is not None

    runner = V4WorkerRunner(tp, lease)

    result = runner._execute_tool(
        "fs_write",
        {"relative_path": "tests/test_main.py", "content": "def test_ok(): assert True"},
    )

    assert "Success" in result
    assert (tmp_path / "tests" / "test_main.py").exists()


def test_morpheus_rejects_protected_project_paths(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        expected_artifacts=["src/main.py"],
    )
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"},
    )
    assert lease is not None

    runner = V4WorkerRunner(tp, lease)

    with pytest.raises(V4ToolError, match="path_protected"):
        runner._execute_tool("fs_write", {"relative_path": "PROJECT.md", "content": "# bad"})

    with pytest.raises(V4ToolError, match="path_protected"):
        runner._execute_tool("fs_write", {"relative_path": ".openclaw/state.json", "content": "{}"})

    with pytest.raises(V4ToolError, match="path_protected"):
        runner._execute_tool("fs_write", {"relative_path": "management/BACKLOG.md", "content": "# bad"})


def test_morpheus_rejects_paths_outside_writable_scope(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        expected_artifacts=["src/main.py"],
    )
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"},
    )
    assert lease is not None

    runner = V4WorkerRunner(tp, lease)

    with pytest.raises(V4ToolError, match="path_not_writable"):
        runner._execute_tool("fs_write", {"relative_path": "secrets.env", "content": "bad"})

def test_morpheus_allows_declared_artifact_write(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        allowed_artifacts=["src/main.py", "README.md"]
    )
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"}
    )
    assert lease is not None

    runner = V4WorkerRunner(tp, lease)
    result = runner._execute_tool("fs_write", {"relative_path": "src/main.py", "content": "print('ok')"})

    assert "Success" in result
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "print('ok')"


def test_morpheus_done_requires_expected_artifacts(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path),
        expected_artifacts=["src/main.py"],
    )
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"},
    )
    assert lease is not None

    runner = V4WorkerRunner(tp, lease)

    with pytest.raises(V4ToolError, match="missing_expected_artifacts"):
        runner._execute_tool(
            "work_submit",
            {
                "status": "DONE",
                "summary": "claimed done",
                "output": {"artifacts": ["src/main.py"]},
                "evidence": {"tests_passed": True},
            },
        )

    runner._execute_tool("fs_write", {"relative_path": "src/main.py", "content": "print('ok')"})
    assert runner._execute_tool(
        "work_submit",
        {
            "status": "DONE",
            "summary": "done",
            "output": {"artifacts": ["src/main.py"]},
            "evidence": {"tests_passed": True},
        },
    ) == "Success"

def test_morpheus_repair_loop(tmp_path):
    tp = TaskPackV4(
        project_id="p1",
        task_id="T001",
        workspace_root=str(tmp_path)
    )
    
    # Pre-create a failing test file
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_main.py").write_text("def test_fail(): assert False", encoding="utf-8")
    
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="T001",
        owner="morpheus",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "att-1"}
    )
    assert lease is not None
    
    runner = V4WorkerRunner(tp, lease)
    
    # Mock Ollama chat responses
    mock_responses = [
        # Turn 1: run test (fails)
        {
            "message": {
                "content": json.dumps({
                    "thought": "I will run the tests to check if they fail.",
                    "tool": "tests_run",
                    "parameters": {"test_path": "tests/test_main.py"}
                })
            }
        },
        # Turn 2: write repair
        {
            "message": {
                "content": json.dumps({
                    "thought": "The tests failed. I will write a passing test.",
                    "tool": "fs_write",
                    "parameters": {"relative_path": "tests/test_main.py", "content": "def test_pass(): assert True"}
                })
            }
        },
        # Turn 3: run test (passes)
        {
            "message": {
                "content": json.dumps({
                    "thought": "I will run the tests again to verify the fix.",
                    "tool": "tests_run",
                    "parameters": {"test_path": "tests/test_main.py"}
                })
            }
        },
        # Turn 4: work_submit
        {
            "message": {
                "content": json.dumps({
                    "thought": "Tests passed, submitting task.",
                    "tool": "work_submit",
                    "parameters": {
                        "status": "DONE",
                        "summary": "Repaired and completed.",
                        "output": {"file": "tests/test_main.py"},
                        "evidence": {"tests_passed": True}
                    }
                })
            }
        }
    ]
    
    with mock.patch("requests.post") as mock_post:
        mock_response_objs = []
        for r in mock_responses:
            m_res = mock.Mock()
            m_res.status_code = 200
            m_res.json.return_value = r
            mock_response_objs.append(m_res)
            
        mock_post.side_effect = mock_response_objs
        
        result = runner.run(max_turns=4)
        
    assert result == "Success"
    assert "assert True" in (tmp_path / "tests" / "test_main.py").read_text()

import datetime
