"""Integration tests for AC-08 evidence-root ergonomics.

Verifies source/control evidence separation, relative-path acceptance,
wrong-root rejection, absolute/traversal rejection, legacy records, and
clear error messages. Runs without modifying production source.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from codexteam_tools.contracts import ResultValidationError, validate_result, validate_artifact_report
from codexteam_tools.paths import safe_relative_path, PathValidationError
from codexteam_tools import spawn


def _base_result():
    return {
        "schema_version": "1.0",
        "result_id": "res-T016-att-001",
        "team_id": "codexteam",
        "task_id": "T016",
        "agent_role": "tester",
        "attempt_id": "att-001",
        "status": "completed",
        "summary": "AC-08 evidence-root ergonomics verification",
        "output": {"exit_code": 0, "stdout_tail": "", "stderr_tail": "", "duration_seconds": 0.1},
        "file_changes": [],
        "evidence": [{
            "type": "test_output",
            "artifact_ref": "results/test.txt",
            "summary": "test evidence",
            "metadata": {}
        }],
        "requested_followups": [],
        "errors": [],
        "warnings": [],
        "limitations": [],
        "produced_at": "2026-08-27T00:00:00Z",
    }


def test_evidence_relative_path_accepted():
    result = _base_result()
    result["evidence"][0]["artifact_ref"] = "results/gates/development.json"
    validate_result(result)  # should not raise


def test_evidence_absolute_path_rejected():
    result = _base_result()
    result["evidence"][0]["artifact_ref"] = "/absolute/path.json"
    with pytest.raises(ResultValidationError) as exc:
        validate_result(result)
    assert "unsafe" in str(exc.value)


def test_evidence_traversal_rejected():
    result = _base_result()
    result["evidence"][0]["artifact_ref"] = "../outside.json"
    with pytest.raises(ResultValidationError) as exc:
        validate_result(result)
    assert "unsafe" in str(exc.value)


def test_evidence_dot_segment_rejected():
    result = _base_result()
    result["evidence"][0]["artifact_ref"] = "./file.txt"
    with pytest.raises(ResultValidationError) as exc:
        validate_result(result)
    assert "unsafe" in str(exc.value)


def test_evidence_metadata_root_valid():
    result = _base_result()
    for root in ("work", "control"):
        result["evidence"][0]["metadata"] = {"root": root}
        validate_result(result)


def test_evidence_metadata_root_invalid():
    result = _base_result()
    result["evidence"][0]["metadata"] = {"root": "invalid"}
    with pytest.raises(ResultValidationError) as exc:
        validate_result(result)
    assert "metadata.root must be 'work' or 'control'" in str(exc.value)


def test_evidence_metadata_legacy_compatibility():
    result = _base_result()
    # No root key
    validate_result(result)
    # Empty metadata
    result["evidence"][0]["metadata"] = {}
    validate_result(result)


def test_artifact_report_valid():
    data = {"version": 1, "summary": "ok", "evidence": ["results/gates/integration.json"], "limitations": []}
    validate_artifact_report(data)


def test_artifact_report_evidence_absolute_rejected():
    data = {"version": 1, "summary": "ok", "evidence": ["/abs/path"], "limitations": []}
    # Artifact report validation does not check path safety itself; safety is enforced on read.
    # Ensure validation passes schema level.
    validate_artifact_report(data)
    # Safe relative path should reject
    with pytest.raises(PathValidationError):
        safe_relative_path("/abs/path")


def test_safe_relative_path_rejects_backslash():
    with pytest.raises(PathValidationError):
        safe_relative_path("a\\b")


def test_safe_relative_path_rejects_empty():
    with pytest.raises(PathValidationError):
        safe_relative_path("")


