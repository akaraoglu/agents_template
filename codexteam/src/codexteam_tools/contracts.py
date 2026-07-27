from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from .paths import PathValidationError, normalize_task_id, safe_relative_path, validate_identifier, validate_profile

RESULT_SCHEMA_VERSION = "1.0"
HANDOFF_SCHEMA_VERSION = "1.0"
RESULT_STATUSES = {"completed", "failed", "partial", "blocked", "needs_review"}
AGENT_ROLES = {
    "architect",
    "developer",
    "documenter",
    "feature_planner",
    "git_steward",
    "leader",
    "reviewer",
    "tester",
    "ux_designer",
}
FILE_ACTIONS = {"created", "modified", "deleted"}
EVIDENCE_TYPES = {"test_output", "artifact", "file_manifest", "cli_invocation", "spec_compliance", "code_review"}
FOLLOWUP_ACTIONS = {"request_review", "delegate_task", "request_approval"}

REQUIRED_RESULT_FIELDS = {
    "schema_version",
    "result_id",
    "team_id",
    "task_id",
    "agent_role",
    "attempt_id",
    "status",
    "summary",
    "output",
    "file_changes",
    "evidence",
    "requested_followups",
    "errors",
    "warnings",
    "limitations",
    "produced_at",
}
REQUIRED_HANDOFF_FIELDS = {
    "schema_version",
    "handoff_id",
    "team_id",
    "task_id",
    "attempt_id",
    "agent_role",
    "model_profile",
    "workspace_root",
    "task_context",
    "constraints",
    "completion_criteria",
}


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_result(
    data: Any,
    *,
    expected_task: str | None = None,
    expected_status: str | None = None,
    expected_team: str | None = None,
    expected_attempt: str | None = None,
    expected_role: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ResultValidationError(["result must be a JSON object"])

    missing = sorted(REQUIRED_RESULT_FIELDS - data.keys())
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")

    if data.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESULT_SCHEMA_VERSION!r}")

    task_id = _task_id(data.get("task_id"), "task_id", errors)
    team_id = _identifier(data.get("team_id"), "team_id", errors)
    attempt_id = _identifier(data.get("attempt_id"), "attempt_id", errors)
    _identifier(data.get("result_id"), "result_id", errors)

    role = data.get("agent_role")
    if role not in AGENT_ROLES:
        errors.append(f"agent_role must be one of {sorted(AGENT_ROLES)}")

    status = data.get("status")
    if status not in RESULT_STATUSES:
        errors.append(f"status must be one of {sorted(RESULT_STATUSES)}")

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2_000:
        errors.append("summary must be a non-empty string of at most 2000 characters")
    elif _has_placeholder(summary):
        errors.append("summary contains template placeholder text")

    _validate_output(data.get("output"), errors)
    _validate_file_changes(data.get("file_changes"), errors)
    _validate_evidence(data.get("evidence"), status, errors)
    _validate_followups(data.get("requested_followups"), errors)
    for field in ("errors", "warnings", "limitations"):
        _validate_string_list(data.get(field), field, errors)
    _validate_timestamp(data.get("produced_at"), errors)

    if expected_task is not None:
        try:
            normalized_expected = normalize_task_id(expected_task)
            if task_id != normalized_expected:
                errors.append(f"task mismatch: expected {normalized_expected}, got {task_id or data.get('task_id')}")
        except PathValidationError as exc:
            errors.append(str(exc))
    if expected_status is not None and status != expected_status:
        errors.append(f"status mismatch: expected {expected_status}, got {status}")
    if expected_team is not None and team_id != expected_team:
        errors.append(f"team mismatch: expected {expected_team}, got {team_id or data.get('team_id')}")
    if expected_attempt is not None and attempt_id != expected_attempt:
        errors.append(f"attempt mismatch: expected {expected_attempt}, got {attempt_id or data.get('attempt_id')}")
    if expected_role is not None and role != expected_role:
        errors.append(f"role mismatch: expected {expected_role}, got {role}")

    if errors:
        raise ResultValidationError(errors)
    return data


def validate_handoff(data: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ResultValidationError(["handoff must be a JSON object"])

    missing = sorted(REQUIRED_HANDOFF_FIELDS - data.keys())
    if missing:
        errors.append(f"missing required handoff fields: {', '.join(missing)}")
    if data.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        errors.append(f"schema_version must be {HANDOFF_SCHEMA_VERSION!r}")
    _identifier(data.get("handoff_id"), "handoff_id", errors)
    _identifier(data.get("team_id"), "team_id", errors)
    _task_id(data.get("task_id"), "task_id", errors)
    _identifier(data.get("attempt_id"), "attempt_id", errors)
    if data.get("agent_role") not in AGENT_ROLES:
        errors.append(f"agent_role must be one of {sorted(AGENT_ROLES)}")
    model_profile = data.get("model_profile")
    if not isinstance(model_profile, str):
        errors.append("model_profile must be a string")
    else:
        try:
            validate_profile(model_profile)
        except PathValidationError as exc:
            errors.append(str(exc))
    role_policy = data.get("role_policy")
    if role_policy is not None:
        if not isinstance(role_policy, dict):
            errors.append("role_policy must be an object")
        else:
            policy_name = role_policy.get("name")
            if (
                not isinstance(policy_name, str)
                or not policy_name.startswith("codexteam_")
            ):
                errors.append("role_policy.name must use the codexteam_<role> form")
            if role_policy.get("schema_version") != "1.0":
                errors.append("role_policy.schema_version must be '1.0'")
            digest = role_policy.get("digest")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                errors.append("role_policy.digest must be a lowercase SHA-256 digest")

    instruction_bundle = data.get("instruction_bundle")
    if instruction_bundle is not None:
        if not isinstance(instruction_bundle, dict):
            errors.append("instruction_bundle must be an object")
        else:
            if set(instruction_bundle) != {"digest", "files"}:
                errors.append("instruction_bundle must contain only digest and files")
            digest = instruction_bundle.get("digest")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                errors.append("instruction_bundle.digest must be a lowercase SHA-256 digest")
            files = instruction_bundle.get("files")
            if (
                not isinstance(files, list)
                or not files
                or any(not isinstance(item, str) or not item.strip() for item in files)
            ):
                errors.append("instruction_bundle.files must be a non-empty string list")

    workspace_root = data.get("workspace_root")
    if not isinstance(workspace_root, str) or not PurePosixPath(workspace_root).is_absolute():
        errors.append("workspace_root must be an absolute path string")
    task_context = data.get("task_context")
    if (
        not isinstance(task_context, dict)
        or not isinstance(task_context.get("prompt"), str)
        or not task_context.get("prompt", "").strip()
    ):
        errors.append("task_context.prompt must be a non-empty string")
    if not isinstance(data.get("constraints"), dict):
        errors.append("constraints must be an object")
    criteria = data.get("completion_criteria")
    if (
        not isinstance(criteria, list)
        or not criteria
        or any(not isinstance(item, str) or not item.strip() for item in criteria)
    ):
        errors.append("completion_criteria must be a non-empty list of non-empty strings")

    if errors:
        raise ResultValidationError(errors)
    return data


def synthetic_result(
    *,
    team_id: str,
    task_id: str,
    role: str,
    attempt_id: str,
    status: str,
    summary: str,
    exit_code: int,
    duration_seconds: float,
    stdout_tail: str = "",
    stderr_tail: str = "",
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": f"res-{task_id.lower()}-{attempt_id}",
        "team_id": team_id,
        "task_id": task_id,
        "agent_role": role,
        "attempt_id": attempt_id,
        "status": status,
        "summary": summary,
        "output": {
            "exit_code": exit_code,
            "stdout_tail": stdout_tail[-2_000:],
            "stderr_tail": stderr_tail[-2_000:],
            "duration_seconds": round(duration_seconds, 3),
        },
        "file_changes": [],
        "evidence": [],
        "requested_followups": [],
        "errors": errors or [],
        "warnings": warnings or [],
        "limitations": [],
        "produced_at": utc_now(),
    }
    validate_result(result, expected_task=task_id, expected_team=team_id, expected_attempt=attempt_id)
    return result


def _task_id(value: Any, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be a string")
        return None
    try:
        normalized = normalize_task_id(value)
        if normalized != value:
            errors.append(f"{field} must use canonical uppercase form: {normalized}")
        return normalized
    except PathValidationError as exc:
        errors.append(str(exc))
        return None


def _identifier(value: Any, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be a string")
        return None
    try:
        return validate_identifier(value, label=field)
    except PathValidationError as exc:
        errors.append(str(exc))
        return None


def _validate_output(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("output must be an object")
        return
    required = {"exit_code", "stdout_tail", "stderr_tail", "duration_seconds"}
    missing = sorted(required - value.keys())
    if missing:
        errors.append(f"output missing fields: {', '.join(missing)}")
    if not isinstance(value.get("exit_code"), int):
        errors.append("output.exit_code must be an integer")
    if (
        not isinstance(value.get("duration_seconds"), (int, float))
        or isinstance(value.get("duration_seconds"), bool)
        or value.get("duration_seconds", -1) < 0
    ):
        errors.append("output.duration_seconds must be a number")
    for field in ("stdout_tail", "stderr_tail"):
        if not isinstance(value.get(field), str):
            errors.append(f"output.{field} must be a string")


def _validate_file_changes(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("file_changes must be a list")
        return
    for index, item in enumerate(value):
        prefix = f"file_changes[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _relative(item.get("path"), f"{prefix}.path", errors)
        if isinstance(item.get("path"), str) and _has_placeholder(item["path"]):
            errors.append(f"{prefix}.path contains template placeholder text")
        if item.get("action") not in FILE_ACTIONS:
            errors.append(f"{prefix}.action must be one of {sorted(FILE_ACTIONS)}")
        size = item.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            errors.append(f"{prefix}.size_bytes must be a non-negative integer")


def _validate_evidence(value: Any, status: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("evidence must be a list")
        return
    if status in {"completed", "needs_review"} and not value:
        errors.append(f"status {status!r} requires at least one evidence entry")
    for index, item in enumerate(value):
        prefix = f"evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if item.get("type") not in EVIDENCE_TYPES:
            errors.append(f"{prefix}.type must be one of {sorted(EVIDENCE_TYPES)}")
        _relative(item.get("artifact_ref"), f"{prefix}.artifact_ref", errors)
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{prefix}.summary must be a non-empty string")
        elif _has_placeholder(summary):
            errors.append(f"{prefix}.summary contains template placeholder text")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            errors.append(f"{prefix}.metadata must be an object")


def _validate_followups(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("requested_followups must be a list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"requested_followups[{index}] must be an object")
            continue
        prefix = f"requested_followups[{index}]"
        if item.get("action_type") not in FOLLOWUP_ACTIONS:
            errors.append(f"{prefix}.action_type must be one of {sorted(FOLLOWUP_ACTIONS)}")
        target_role = item.get("target_role")
        if not isinstance(target_role, str) or not target_role.strip():
            errors.append(f"{prefix}.target_role must be a non-empty string")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{prefix}.reason must be a non-empty string")
        if "task_id" in item:
            _task_id(item.get("task_id"), f"{prefix}.task_id", errors)


def _validate_string_list(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{field} must be a list of strings")


def _validate_timestamp(value: Any, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append("produced_at must be an ISO-8601 UTC string")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append("produced_at must be an ISO-8601 timestamp")
        return
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        errors.append("produced_at must use UTC")


def _relative(value: Any, field: str, errors: list[str]) -> PurePosixPath | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be a string")
        return None
    try:
        return safe_relative_path(value, label=field)
    except PathValidationError as exc:
        errors.append(str(exc))
        return None


def _has_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in (
            "brief description",
            "completed | failed",
            "[todo]",
            "<placeholder>",
            "describe the completed work",
            "describe the evidence",
            "relative/path",
        )
    )
