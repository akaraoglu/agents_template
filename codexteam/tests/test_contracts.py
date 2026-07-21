import copy

import pytest

from codexteam_tools.contracts import ResultValidationError, synthetic_result, validate_handoff, validate_result


def test_valid_result_contract(result_factory):
    result = result_factory()
    assert validate_result(
        result,
        expected_task="T001",
        expected_team="team-1",
        expected_attempt="att-001",
        expected_role="developer",
    ) is result


@pytest.mark.parametrize("field", ["schema_version", "team_id", "output", "file_changes", "produced_at"])
def test_missing_required_result_fields_fail(result_factory, field):
    result = result_factory()
    del result[field]
    with pytest.raises(ResultValidationError):
        validate_result(result)


def test_completed_result_requires_evidence(result_factory):
    result = result_factory()
    result["evidence"] = []
    with pytest.raises(ResultValidationError, match="requires at least one evidence"):
        validate_result(result)


def test_lowercase_task_id_is_not_canonical(result_factory):
    result = result_factory()
    result["task_id"] = "t001"
    with pytest.raises(ResultValidationError, match="uppercase"):
        validate_result(result)


def test_template_copy_is_rejected(result_factory):
    result = result_factory()
    result["summary"] = "Describe the completed work."
    result["file_changes"][0]["path"] = "relative/path"
    with pytest.raises(ResultValidationError, match="placeholder"):
        validate_result(result)


def test_cross_attempt_mismatch_fails(result_factory):
    with pytest.raises(ResultValidationError, match="attempt mismatch"):
        validate_result(result_factory(), expected_attempt="att-999")


def test_synthetic_failure_is_contract_valid():
    result = synthetic_result(
        team_id="team-1",
        task_id="T002",
        role="tester",
        attempt_id="att-002",
        status="failed",
        summary="The worker process failed.",
        exit_code=1,
        duration_seconds=2.0,
        errors=["exit code 1"],
    )
    assert validate_result(result)["status"] == "failed"


def test_result_validation_does_not_mutate_input(result_factory):
    result = result_factory()
    original = copy.deepcopy(result)
    validate_result(result)
    assert result == original


def test_valid_handoff_contract():
    handoff = {
        "schema_version": "1.0",
        "handoff_id": "handoff-t001-att-001",
        "team_id": "team-1",
        "task_id": "T001",
        "attempt_id": "att-001",
        "agent_role": "developer",
        "model_profile": "qwen36-27b",
        "workspace_root": "/tmp/project",
        "task_context": {"prompt": "Implement the task."},
        "constraints": {"timeout_seconds": 10},
        "completion_criteria": ["Return result v1 JSON."],
    }
    assert validate_handoff(handoff) is handoff


def test_handoff_requires_absolute_workspace():
    with pytest.raises(ResultValidationError, match="absolute path"):
        validate_handoff({
            "schema_version": "1.0",
            "handoff_id": "handoff-t001-att-001",
            "team_id": "team-1",
            "task_id": "T001",
            "attempt_id": "att-001",
            "agent_role": "developer",
            "model_profile": "qwen36-27b",
            "workspace_root": "relative/project",
            "task_context": {"prompt": "Implement the task."},
            "constraints": {},
            "completion_criteria": ["Return result v1 JSON."],
        })
