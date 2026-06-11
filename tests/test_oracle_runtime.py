import pytest
import unittest.mock as mock
import json
import datetime
from pathlib import Path
from AgenticTeam.scripts.contracts import Lease, OracleResult
from AgenticTeam.scripts.oracle_runtime import OracleRunner
from AgenticTeam.scripts.leases import acquire_lease
from AgenticTeam.scripts.events import clear_events, read_events

@pytest.fixture(autouse=True)
def clean_logs():
    clear_events()
    yield
    clear_events()

def test_oracle_prompt_compilation(tmp_path):
    lease = Lease(
        lease_id="l1",
        resource_id="none",
        owner="oracle",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10),
        metadata={"project_id": "p1"}
    )
    runner = OracleRunner(str(tmp_path), lease)
    prompt = runner._compile_system_prompt()
    
    assert "Oracle" in prompt
    assert "IDENTITY.md" in prompt or "oracle" in prompt.lower()
    assert "oracle_report" in prompt
    assert "Do not PASS only because tests pass" in prompt
    assert "depth-controlled branch drawing" in prompt
    assert "def fibonacci(" in prompt
    assert "branches == 5" in prompt
    assert "nonempty_lines(text)" in prompt
    assert "Do not FAIL an ASCII tree only because it lacks Unicode" in prompt
    assert "fs_write" not in prompt

def test_oracle_react_loop_mock_execution(tmp_path):
    # Acquire a lease
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="none",
        owner="oracle",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "oracle-attempt"}
    )
    assert lease is not None
    
    runner = OracleRunner(str(tmp_path), lease)
    
    # Mock Ollama chat responses
    mock_responses = [
        # Turn 1: fs_list
        {
            "message": {
                "content": json.dumps({
                    "thought": "I will list the workspace directory.",
                    "tool": "fs_list",
                    "parameters": {"relative_path": "."}
                })
            }
        },
        # Turn 2: oracle_report
        {
            "message": {
                "content": json.dumps({
                    "thought": "Everything looks good. Submitting PASS.",
                    "tool": "oracle_report",
                    "parameters": {
                        "status": "PASS",
                        "summary": "Verified project successfully.",
                        "evidence_paths": ["."]
                    }
                })
            }
        }
    ]
    
    # Mock requests.post
    with mock.patch("requests.post") as mock_post:
        mock_response_objs = []
        for r in mock_responses:
            m_res = mock.Mock()
            m_res.status_code = 200
            m_res.json.return_value = r
            mock_response_objs.append(m_res)
            
        mock_post.side_effect = mock_response_objs
        
        result = runner.run(max_turns=2)
        
    assert result == "Success"
    
    # Check events emitted
    events = read_events()
    event_types = [ev.event_type for ev in events]
    assert "oracle_passed" in event_types
    
    passed_event = next(ev for ev in events if ev.event_type == "oracle_passed")
    assert passed_event.payload["project_id"] == "p1"
    assert passed_event.payload["status"] == "PASS"
