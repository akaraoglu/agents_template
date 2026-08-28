import copy
import importlib
import json
from pathlib import Path

import pytest

from codexteam_tools.contract_registry import (
    CONTRACT_REGISTRY,
    EVALUATION_CHECKS,
    get_contract,
    validate_milestone_retrospective_evaluation,
)
from codexteam_tools.contracts import (
    ResultValidationError,
    synthetic_result,
    validate_artifact_report,
    validate_handoff,
    validate_result,
    validate_session,
)


def test_contract_registry_contains_registered_contracts():
    assert set(CONTRACT_REGISTRY) == {
        "handoff",
        "artifact-report-v1",
        "result",
        "session",
        "role-policy",
        "gate-record",
        "execution-spec",
        "agent-spec",
        "milestone-retrospective",
        "milestone-retrospective-evaluation",
        "improvement-proposal",
        "improvement-disposition",
    }
    root = Path(__file__).parents[1]
    for entry in CONTRACT_REGISTRY.values():
        if entry.schema_path is not None:
            assert (root / entry.schema_path).is_file()
    assert get_contract("result").unknown_fields == "additive"
    with pytest.raises(ValueError, match="unknown CodexTeam contract"):
        get_contract("missing")


def test_retrospective_contract_schemas_match_strict_validator_fields():
    root = Path(__file__).parents[1]
    expected = {
        "milestone-retrospective.json": {
            "schema_version", "boundary_id", "evidence_digest", "disposition",
            "signals", "proposals", "advisory_model",
        },
        "milestone-retrospective-evaluation.json": {
            "schema_version", "boundary_id", "boundary_digest",
            "preparation_digest", "evidence_digest", "prepared_analysis_digest",
            "agent_spec_id", "agent_spec_version", "agent_spec_digest", "profile",
            "verdict", "checks", "observation_assessments", "investigations", "proposals",
            "creates_task", "grants_implementation_authority",
        },
        "improvement-proposal.json": {
            "schema_version", "proposal_id", "boundary_id", "recurrence_key",
            "category", "scope", "impact", "confidence", "evidence", "trigger",
            "expected_gain", "validation", "rollback", "status",
            "human_disposition", "creates_task",
            "grants_implementation_authority",
        },
        "improvement-disposition.json": {
            "schema_version", "boundary_id", "proposal_id", "proposal_sha256",
            "decision", "status", "approver", "reason", "decided_at",
            "approval_scope", "creates_task", "grants_implementation_authority",
        },
    }
    for filename, fields in expected.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == fields
        assert set(schema["properties"]) == fields


def _evaluation_report():
    return {
        "schema_version": "1.0",
        "boundary_id": "M001",
        "boundary_digest": "a" * 64,
        "preparation_digest": "b" * 64,
        "evidence_digest": "c" * 64,
        "prepared_analysis_digest": "d" * 64,
        "agent_spec_id": "agent-evaluator",
        "agent_spec_version": "1.0",
        "agent_spec_digest": "e" * 64,
        "profile": "codex/qwen38-27b",
        "verdict": "ACCEPT",
        "checks": {
            name: {"status": "PASS", "detail": f"{name} passed."}
            for name in EVALUATION_CHECKS
        },
        "observation_assessments": [{
            "observation_id": "OBS-001",
            "evidence_ceiling": "E1",
            "classification": "INSUFFICIENT_EVIDENCE",
            "facts": ["One timeout was recorded."],
            "hypotheses": ["The timeout may reflect natural complexity."],
            "alternatives": ["Natural complexity", "Avoidable tool friction"],
            "discriminator": "Comparable repeated work would distinguish the causes.",
            "action": "NO_CHANGE",
            "rationale": "E1 does not justify investigation or change.",
            "evidence_refs": ["evidence.json#/tasks/0"],
        }],
        "investigations": [],
        "proposals": [],
        "creates_task": False,
        "grants_implementation_authority": False,
    }


def test_milestone_evaluation_contract_is_strict_and_authority_free():
    report = _evaluation_report()
    assert validate_milestone_retrospective_evaluation(report) is report
    assert tuple(report["checks"]) == EVALUATION_CHECKS

    invalid = copy.deepcopy(report)
    invalid["future"] = True
    with pytest.raises(ValueError, match="strict contract"):
        validate_milestone_retrospective_evaluation(invalid)

    invalid = copy.deepcopy(report)
    invalid["grants_implementation_authority"] = True
    with pytest.raises(ValueError, match="authority"):
        validate_milestone_retrospective_evaluation(invalid)


def test_milestone_evaluation_enforces_checks_refs_and_evidence_ceiling():
    report = _evaluation_report()
    report["checks"].pop("authority")
    with pytest.raises(ValueError, match="check names"):
        validate_milestone_retrospective_evaluation(report)

    report = _evaluation_report()
    report["observation_assessments"][0]["evidence_refs"] = ["../private.json"]
    with pytest.raises(ValueError, match="unsafe"):
        validate_milestone_retrospective_evaluation(report)

    report = _evaluation_report()
    report["observation_assessments"][0]["action"] = "PROPOSE"
    with pytest.raises(ValueError, match="evidence ceiling"):
        validate_milestone_retrospective_evaluation(report)

    report = _evaluation_report()
    report["observation_assessments"][0]["rationale"] = "line one\nline two"
    with pytest.raises(ValueError, match="rationale"):
        validate_milestone_retrospective_evaluation(report)

    report = _evaluation_report()
    report["observation_assessments"][0]["facts"] = ["<!-- injected -->"]
    with pytest.raises(ValueError, match="facts"):
        validate_milestone_retrospective_evaluation(report)


def test_contract_registry_validator_symbols_resolve():
    for entry in CONTRACT_REGISTRY.values():
        module_name, symbol = entry.validator_symbol.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module_name), symbol))


def test_artifact_report_is_small_and_permissive():
    payload = {
        "version": 1,
        "summary": "Reviewed the accepted change.",
        "evidence": ["results/review.md"],
        "limitations": [],
        "future_field": {"ignored": True},
    }
    assert validate_artifact_report(payload) is payload
    with pytest.raises(ResultValidationError, match="version must be 1"):
        validate_artifact_report({**payload, "version": "1"})
    with pytest.raises(ResultValidationError, match="version must be 1"):
        validate_artifact_report({**payload, "version": True})
    with pytest.raises(ResultValidationError, match="evidence"):
        validate_artifact_report({**payload, "evidence": ["   "]})
    with pytest.raises(ResultValidationError, match="limitations"):
        validate_artifact_report({**payload, "limitations": [""]})


def test_session_contract_is_strict():
    session = {
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "future_addition": {"kept": True},
    }
    with pytest.raises(ResultValidationError, match="unknown fields"):
        validate_session(session)
    session["draft_format"] = "unknown"
    with pytest.raises(ResultValidationError, match="draft_format"):
        validate_session(session)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("last_phase", "bogus", "last_phase"),
        ("last_status", "", "last_status"),
        ("created_at", "not-a-date", "created_at"),
        ("created_at", "2026-08-14 12:00:00Z", "ISO-8601"),
        ("updated_at", "2026-08-14T12:00:00", "timezone"),
    ),
)
def test_session_contract_validates_known_phase_status_and_timestamps(field, value, message):
    session = {"schema_version": "1.0", "thread_id": "thread-1", field: value}
    with pytest.raises(ResultValidationError, match=message):
        validate_session(session)


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
        "execution_spec": {
            "contract": "execution-spec",
            "path": "execution-spec.json",
            "digest": "a" * 64,
        },
        "workspace_root": "/tmp/project",
        "task_context": {"prompt": "Implement the task."},
        "constraints": {"timeout_seconds": 10},
        "completion_criteria": ["Return result JSON."],
    }
    assert validate_handoff(handoff) is handoff


def test_handoff_rejects_unknown_root_and_role_policy_fields():
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
        "constraints": {},
        "completion_criteria": ["Return a draft."],
        "unexpected": True,
    }
    with pytest.raises(ResultValidationError, match="unknown handoff fields"):
        validate_handoff(handoff)
    handoff.pop("unexpected")
    handoff["role_policy"] = {
        "name": "codexteam_developer",
        "schema_version": "1.0",
        "digest": "a" * 64,
        "unexpected": True,
    }
    with pytest.raises(ResultValidationError, match="contain only"):
        validate_handoff(handoff)


def test_result_integer_fields_reject_booleans(result_factory):
    result = result_factory()
    result["output"]["exit_code"] = True
    result["file_changes"][0]["size_bytes"] = False
    with pytest.raises(ResultValidationError, match="integer"):
        validate_result(result)


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
            "completion_criteria": ["Return result JSON."],
        })


def test_artifact_report_required_fields_and_types():
    report = {"version": 1, "summary": "Done.", "evidence": [], "limitations": []}
    assert validate_artifact_report(report) is report
    for field in ("version", "summary", "evidence", "limitations"):
        invalid = dict(report)
        del invalid[field]
        with pytest.raises(ResultValidationError, match="missing required artifact report fields"):
            validate_artifact_report(invalid)

def test_evidence_metadata_root_valid_values(result_factory):
    result = result_factory()
    for root in ("work", "control"):
        result["evidence"][0]["metadata"]["root"] = root
        assert validate_result(result) is result

def test_evidence_metadata_root_invalid_value_rejected(result_factory):
    result = result_factory()
    result["evidence"][0]["metadata"]["root"] = "invalid"
    with pytest.raises(ResultValidationError, match="metadata.root must be 'work' or 'control'"):
        validate_result(result)

def test_evidence_metadata_root_legacy_compatibility(result_factory):
    result = result_factory()
    # No root present
    assert validate_result(result) is result
    # Empty metadata
    result["evidence"][0]["metadata"] = {}
    assert validate_result(result) is result
