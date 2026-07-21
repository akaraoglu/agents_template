"""Test configuration for local source imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def result_factory():
    def build(
        *,
        task_id: str = "T001",
        team_id: str = "team-1",
        attempt_id: str = "att-001",
        role: str = "developer",
        status: str = "completed",
        artifact_ref: str = "results/evidence.txt",
        file_path: str = "src/main.py",
    ):
        return {
            "schema_version": "1.0",
            "result_id": f"res-{task_id.lower()}-{attempt_id}",
            "team_id": team_id,
            "task_id": task_id,
            "agent_role": role,
            "attempt_id": attempt_id,
            "status": status,
            "summary": "Implemented and verified the assigned task.",
            "output": {
                "exit_code": 0,
                "stdout_tail": "verification passed",
                "stderr_tail": "",
                "duration_seconds": 0.1,
            },
            "file_changes": [{"path": file_path, "action": "created", "size_bytes": 1}],
            "evidence": [{
                "type": "test_output",
                "artifact_ref": artifact_ref,
                "summary": "Independent verification passed.",
                "metadata": {"exit_code": 0},
            }],
            "requested_followups": [],
            "errors": [],
            "warnings": [],
            "limitations": [],
            "produced_at": "2026-07-15T00:00:00Z",
        }

    return build
