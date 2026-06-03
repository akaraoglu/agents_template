#!/usr/bin/env python3
"""Typed Covenant contracts for completion and verification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
import re


TASK_ID_RE = re.compile(r"T\d{3}")


class ContractValidationError(ValueError):
    """Raised when a Covenant contract payload is invalid."""


def _require_mapping(payload: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return payload


def _require_non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_task_id(value: Any, *, field: str = "task_id") -> str:
    task_id = _require_non_empty_string(value, field=field).upper()
    if not TASK_ID_RE.fullmatch(task_id):
        raise ContractValidationError(f"{field} must match T###")
    return task_id


def _require_iso_timestamp(value: Any, *, field: str = "timestamp") -> str:
    timestamp = _require_non_empty_string(value, field=field)
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field} must be ISO-8601") from exc
    return timestamp


def _require_command(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(f"{field} must be a non-empty string array")
    command: list[str] = []
    for idx, part in enumerate(value):
        if not isinstance(part, str) or not part.strip():
            raise ContractValidationError(f"{field}[{idx}] must be a non-empty string")
        command.append(part.strip())
    return command


def _require_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(f"{field} must be a non-empty string array")
    values: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ContractValidationError(f"{field}[{idx}] must be a non-empty string")
        values.append(item.strip())
    return values


def _require_optional_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractValidationError(f"{field} must be a string array")
    values: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ContractValidationError(f"{field}[{idx}] must be a non-empty string")
        values.append(item.strip())
    return values


def _require_optional_mapping_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractValidationError(f"{field} must be an object array")
    values: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        mapping = _require_mapping(item, field=f"{field}[{idx}]")
        values.append(dict(mapping))
    return values


def _require_non_negative_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractValidationError(f"{field} must be a non-negative integer")
    return value


def _normalize_relative_path(value: Any, *, field: str) -> str:
    raw = _require_non_empty_string(value, field=field)
    path = Path(raw)
    if path.is_absolute():
        raise ContractValidationError(f"{field} must be relative to workspace_root")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ContractValidationError(f"{field} contains invalid segment")
    return path.as_posix()


def _resolve_workspace_relative_path(relative_path: str, workspace_root: Path, *, field: str) -> Path:
    target = (workspace_root / relative_path).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ContractValidationError(f"{field} escapes workspace_root") from exc
    return target


def _normalize_absolute_root(value: Any, *, field: str) -> str:
    raw = _require_non_empty_string(value, field=field)
    path = Path(raw)
    if not path.is_absolute():
        raise ContractValidationError(f"{field} must be an absolute path")
    return path.resolve().as_posix()


def _normalize_report_destination(value: Any, *, field: str = "report_destination") -> str:
    raw = _require_non_empty_string(value, field=field)
    if "://" in raw:
        if not raw.startswith("covenant://"):
            raise ContractValidationError(f"{field} URI scheme must be covenant")
        return raw
    return _normalize_relative_path(raw, field=field)


def _relative_path_allowed(relative_path: str, allowed_write_paths: list[str]) -> bool:
    path_parts = Path(relative_path).parts
    for allowed in allowed_write_paths:
        allowed_parts = Path(allowed).parts
        if path_parts == allowed_parts or path_parts[: len(allowed_parts)] == allowed_parts:
            return True
    return False


def _normalize_evidence_path(
    value: Any,
    *,
    workspace_root: Path,
    approved_runtime_evidence_roots: tuple[Path, ...],
    field: str,
) -> tuple[str, str]:
    raw = _require_non_empty_string(value, field=field)
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            rel = resolved.relative_to(workspace_root).as_posix()
            return rel, "workspace"
        except ValueError:
            for root in approved_runtime_evidence_roots:
                try:
                    resolved.relative_to(root)
                    return resolved.as_posix(), "runtime"
                except ValueError:
                    continue
            raise ContractValidationError(f"{field} is outside workspace_root and not in approved runtime evidence roots")
    rel = _normalize_relative_path(raw, field=field)
    _resolve_workspace_relative_path(rel, workspace_root, field=field)
    return rel, "workspace"


@dataclass(frozen=True)
class VerificationEvidence:
    task_id: str
    agent: str
    timestamp: str
    performed: bool
    command: list[str]
    status: str
    summary: str
    evidence_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "timestamp": self.timestamp,
            "performed": self.performed,
            "command": self.command,
            "status": self.status,
            "summary": self.summary,
            "evidence_paths": self.evidence_paths,
        }


def validate_verification_evidence(payload: Any) -> VerificationEvidence:
    raw = _require_mapping(payload, field="verification")
    task_id = _require_task_id(raw.get("task_id"))
    agent = _require_non_empty_string(raw.get("agent"), field="agent").lower()
    timestamp = _require_iso_timestamp(raw.get("timestamp"))
    performed = raw.get("performed")
    if not isinstance(performed, bool):
        raise ContractValidationError("performed must be a boolean")
    command = _require_command(raw.get("command"), field="command")
    status = _require_non_empty_string(raw.get("status"), field="status").lower()
    if status not in {"pass", "passed"}:
        raise ContractValidationError("status must be pass")
    summary = _require_non_empty_string(raw.get("summary"), field="summary")
    evidence_paths = _require_string_list(raw.get("evidence_paths"), field="evidence_paths")
    if not performed:
        raise ContractValidationError("performed must be true for accepted evidence")
    return VerificationEvidence(
        task_id=task_id,
        agent=agent,
        timestamp=timestamp,
        performed=performed,
        command=command,
        status="pass",
        summary=summary,
        evidence_paths=evidence_paths,
    )


@dataclass(frozen=True)
class WorkResult:
    project_id: str
    task_id: str
    from_agent: str
    phase: str
    status: str
    summary: str
    reason: str | None
    next_action: str | None
    verification: VerificationEvidence | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "from": self.from_agent,
            "phase": self.phase,
            "status": self.status,
            "summary": self.summary,
            "reason": self.reason,
            "next_action": self.next_action,
            "verification": self.verification.to_dict() if self.verification else None,
        }


@dataclass(frozen=True)
class ProjectWorkspace:
    workspace_root: str
    allowed_write_paths: list[str]
    expected_artifacts: list[str]
    approved_runtime_evidence_roots: list[str]

    @property
    def workspace_root_path(self) -> Path:
        return Path(self.workspace_root)

    @property
    def approved_runtime_evidence_root_paths(self) -> tuple[Path, ...]:
        return tuple(Path(path) for path in self.approved_runtime_evidence_roots)


@dataclass(frozen=True)
class ArtifactManifest:
    created: list[str]
    changed: list[str]
    moved: list[dict[str, str]]
    deleted: list[str]
    expected_artifacts: list[str]
    evidence_paths: list[str]
    runtime_evidence_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "changed": self.changed,
            "moved": self.moved,
            "deleted": self.deleted,
            "expected_artifacts": self.expected_artifacts,
            "evidence_paths": self.evidence_paths,
            "runtime_evidence_paths": self.runtime_evidence_paths,
        }


@dataclass(frozen=True)
class TaskPack:
    project_id: str
    workspace_root: str
    task_id: str
    role: str
    goal: str
    acceptance_criteria: list[str]
    allowed_write_paths: list[str]
    expected_artifacts: list[str]
    relevant_files: list[str]
    available_tools: list[str]
    recommended_verification: list[str]
    previous_failure: dict[str, Any] | None
    repair_budget: int
    report_destination: str
    approved_runtime_evidence_roots: list[str]

    @property
    def workspace_root_path(self) -> Path:
        return Path(self.workspace_root)

    def to_project_workspace(self) -> ProjectWorkspace:
        return ProjectWorkspace(
            workspace_root=self.workspace_root,
            allowed_write_paths=self.allowed_write_paths,
            expected_artifacts=self.expected_artifacts,
            approved_runtime_evidence_roots=self.approved_runtime_evidence_roots,
        )


@dataclass(frozen=True)
class WorkReport:
    task_id: str
    agent: str
    status: str
    summary: str
    changed_files: list[str]
    verification: VerificationEvidence | None
    repair_attempts: list[dict[str, Any]]
    next_owner: str | None
    blocker: dict[str, str] | None
    artifact_manifest: ArtifactManifest | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "summary": self.summary,
            "changed_files": self.changed_files,
            "verification": self.verification.to_dict() if self.verification else None,
            "repair_attempts": self.repair_attempts,
            "next_owner": self.next_owner,
            "blocker": self.blocker,
            "artifact_manifest": self.artifact_manifest.to_dict() if self.artifact_manifest else None,
        }


def validate_project_workspace(payload: Any) -> ProjectWorkspace:
    raw = _require_mapping(payload, field="project_workspace")
    workspace_root = _normalize_absolute_root(raw.get("workspace_root"), field="workspace_root")
    allowed_write_paths = [_normalize_relative_path(item, field=f"allowed_write_paths[{idx}]") for idx, item in enumerate(_require_string_list(raw.get("allowed_write_paths"), field="allowed_write_paths"))]
    expected_artifacts = [_normalize_relative_path(item, field=f"expected_artifacts[{idx}]") for idx, item in enumerate(_require_string_list(raw.get("expected_artifacts"), field="expected_artifacts"))]
    runtime_roots_raw = raw.get("approved_runtime_evidence_roots") or []
    if not isinstance(runtime_roots_raw, list):
        raise ContractValidationError("approved_runtime_evidence_roots must be a string array")
    approved_runtime_evidence_roots = [
        _normalize_absolute_root(item, field=f"approved_runtime_evidence_roots[{idx}]")
        for idx, item in enumerate(runtime_roots_raw)
    ]
    workspace_path = Path(workspace_root)
    for idx, rel in enumerate(allowed_write_paths):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"allowed_write_paths[{idx}]")
    for idx, rel in enumerate(expected_artifacts):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"expected_artifacts[{idx}]")
    return ProjectWorkspace(
        workspace_root=workspace_root,
        allowed_write_paths=allowed_write_paths,
        expected_artifacts=expected_artifacts,
        approved_runtime_evidence_roots=approved_runtime_evidence_roots,
    )


def validate_task_pack(payload: Any) -> TaskPack:
    raw = _require_mapping(payload, field="task_pack")
    project_id = _require_non_empty_string(raw.get("project_id"), field="project_id")
    workspace_root = _normalize_absolute_root(raw.get("workspace_root"), field="workspace_root")
    task_id = _require_task_id(raw.get("task_id"))
    role = _require_non_empty_string(raw.get("role"), field="role").lower()
    goal = _require_non_empty_string(raw.get("goal"), field="goal")
    acceptance_criteria = _require_string_list(raw.get("acceptance_criteria"), field="acceptance_criteria")
    allowed_write_paths = [
        _normalize_relative_path(item, field=f"allowed_write_paths[{idx}]")
        for idx, item in enumerate(_require_string_list(raw.get("allowed_write_paths"), field="allowed_write_paths"))
    ]
    expected_artifacts = [
        _normalize_relative_path(item, field=f"expected_artifacts[{idx}]")
        for idx, item in enumerate(_require_string_list(raw.get("expected_artifacts"), field="expected_artifacts"))
    ]
    relevant_files = [
        _normalize_relative_path(item, field=f"relevant_files[{idx}]")
        for idx, item in enumerate(_require_optional_string_list(raw.get("relevant_files"), field="relevant_files"))
    ]
    available_tools = _require_optional_string_list(raw.get("available_tools"), field="available_tools")
    recommended_verification = _require_command(raw.get("recommended_verification"), field="recommended_verification")
    previous_failure_raw = raw.get("previous_failure")
    previous_failure = None
    if previous_failure_raw is not None:
        previous_failure = dict(_require_mapping(previous_failure_raw, field="previous_failure"))
    repair_budget = _require_non_negative_int(raw.get("repair_budget"), field="repair_budget")
    report_destination = _normalize_report_destination(raw.get("report_destination"))
    runtime_roots_raw = raw.get("approved_runtime_evidence_roots") or []
    if not isinstance(runtime_roots_raw, list):
        raise ContractValidationError("approved_runtime_evidence_roots must be a string array")
    approved_runtime_evidence_roots = [
        _normalize_absolute_root(item, field=f"approved_runtime_evidence_roots[{idx}]")
        for idx, item in enumerate(runtime_roots_raw)
    ]

    workspace_path = Path(workspace_root)
    for idx, rel in enumerate(allowed_write_paths):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"allowed_write_paths[{idx}]")
    for idx, rel in enumerate(expected_artifacts):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"expected_artifacts[{idx}]")
        if not _relative_path_allowed(rel, allowed_write_paths):
            raise ContractValidationError(f"expected_artifacts[{idx}] is outside allowed_write_paths")
    for idx, rel in enumerate(relevant_files):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"relevant_files[{idx}]")

    return TaskPack(
        project_id=project_id,
        workspace_root=workspace_root,
        task_id=task_id,
        role=role,
        goal=goal,
        acceptance_criteria=acceptance_criteria,
        allowed_write_paths=allowed_write_paths,
        expected_artifacts=expected_artifacts,
        relevant_files=relevant_files,
        available_tools=available_tools,
        recommended_verification=recommended_verification,
        previous_failure=previous_failure,
        repair_budget=repair_budget,
        report_destination=report_destination,
        approved_runtime_evidence_roots=approved_runtime_evidence_roots,
    )


def validate_artifact_manifest(payload: Any, *, workspace: ProjectWorkspace) -> ArtifactManifest:
    raw = _require_mapping(payload, field="artifact_manifest")
    workspace_path = workspace.workspace_root_path
    approved_roots = workspace.approved_runtime_evidence_root_paths
    created_raw = raw.get("created") or []
    changed_raw = raw.get("changed") or []
    deleted_raw = raw.get("deleted") or []
    if not isinstance(created_raw, list):
        raise ContractValidationError("created must be an array")
    if not isinstance(changed_raw, list):
        raise ContractValidationError("changed must be an array")
    if not isinstance(deleted_raw, list):
        raise ContractValidationError("deleted must be an array")
    created = [_normalize_relative_path(item, field=f"created[{idx}]") for idx, item in enumerate(created_raw)]
    changed = [_normalize_relative_path(item, field=f"changed[{idx}]") for idx, item in enumerate(changed_raw)]
    deleted = [_normalize_relative_path(item, field=f"deleted[{idx}]") for idx, item in enumerate(deleted_raw)]
    expected_artifacts = [_normalize_relative_path(item, field=f"expected_artifacts[{idx}]") for idx, item in enumerate(_require_string_list(raw.get("expected_artifacts"), field="expected_artifacts"))]
    moved_raw = raw.get("moved") or []
    if not isinstance(moved_raw, list):
        raise ContractValidationError("moved must be an array")
    moved: list[dict[str, str]] = []
    for idx, item in enumerate(moved_raw):
        mapping = _require_mapping(item, field=f"moved[{idx}]")
        source = _normalize_relative_path(mapping.get("from"), field=f"moved[{idx}].from")
        target = _normalize_relative_path(mapping.get("to"), field=f"moved[{idx}].to")
        moved.append({"from": source, "to": target})
    evidence_raw = _require_string_list(raw.get("evidence_paths"), field="evidence_paths")
    evidence_paths: list[str] = []
    runtime_evidence_paths: list[str] = []
    for idx, item in enumerate(evidence_raw):
        normalized, kind = _normalize_evidence_path(
            item,
            workspace_root=workspace_path,
            approved_runtime_evidence_roots=approved_roots,
            field=f"evidence_paths[{idx}]",
        )
        if kind == "runtime":
            runtime_evidence_paths.append(normalized)
        else:
            evidence_paths.append(normalized)
    for idx, rel in enumerate(created):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"created[{idx}]")
    for idx, rel in enumerate(changed):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"changed[{idx}]")
    for idx, rel in enumerate(deleted):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"deleted[{idx}]")
    for idx, rel in enumerate(expected_artifacts):
        _resolve_workspace_relative_path(rel, workspace_path, field=f"expected_artifacts[{idx}]")
    for idx, item in enumerate(moved):
        _resolve_workspace_relative_path(item["from"], workspace_path, field=f"moved[{idx}].from")
        _resolve_workspace_relative_path(item["to"], workspace_path, field=f"moved[{idx}].to")
    if not created and not changed and not moved and not deleted:
        raise ContractValidationError("artifact_manifest must declare at least one changed artifact")
    return ArtifactManifest(
        created=created,
        changed=changed,
        moved=moved,
        deleted=deleted,
        expected_artifacts=expected_artifacts,
        evidence_paths=evidence_paths,
        runtime_evidence_paths=runtime_evidence_paths,
    )


def validate_work_report(
    payload: Any,
    *,
    task_pack: TaskPack,
    artifact_exists: Any | None = None,
) -> WorkReport:
    raw = _require_mapping(payload, field="work_report")
    task_id = _require_task_id(raw.get("task_id"))
    if task_id != task_pack.task_id:
        raise ContractValidationError("work_report.task_id must match task_pack.task_id")
    agent = _require_non_empty_string(raw.get("agent"), field="agent").lower()
    if agent != task_pack.role:
        raise ContractValidationError("work_report.agent must match task_pack.role")
    status = _require_non_empty_string(raw.get("status"), field="status").upper()
    if status not in {"DONE", "BLOCKED", "FAILED", "NEEDS_REVIEW"}:
        raise ContractValidationError("status must be one of DONE|BLOCKED|FAILED|NEEDS_REVIEW")
    summary = _require_non_empty_string(raw.get("summary"), field="summary")
    changed_files = [
        _normalize_relative_path(item, field=f"changed_files[{idx}]")
        for idx, item in enumerate(_require_optional_string_list(raw.get("changed_files"), field="changed_files"))
    ]
    for changed_file in changed_files:
        if not _relative_path_allowed(changed_file, task_pack.allowed_write_paths):
            raise ContractValidationError(f"changed_files contains path outside allowed_write_paths: {changed_file}")
    repair_attempts = _require_optional_mapping_list(raw.get("repair_attempts"), field="repair_attempts")

    next_owner_raw = raw.get("next_owner")
    next_owner = None
    if next_owner_raw is not None:
        next_owner = _require_non_empty_string(next_owner_raw, field="next_owner").lower()

    blocker_payload = raw.get("blocker")
    blocker = None
    if blocker_payload is not None:
        blocker_raw = _require_mapping(blocker_payload, field="blocker")
        reason = _require_non_empty_string(blocker_raw.get("reason"), field="blocker.reason")
        blocker = {"reason": reason}
        if blocker_raw.get("next_action") is not None:
            blocker["next_action"] = _require_non_empty_string(blocker_raw.get("next_action"), field="blocker.next_action")

    verification = None
    artifact_manifest = None
    if status == "DONE":
        verification = validate_verification_evidence(raw.get("verification"))
        if verification.task_id != task_pack.task_id:
            raise ContractValidationError("verification.task_id must match task_pack.task_id")
        if verification.agent != task_pack.role:
            raise ContractValidationError("verification.agent must match task_pack.role")

        workspace = task_pack.to_project_workspace()
        manifest_payload = raw.get("artifact_manifest")
        if manifest_payload is None:
            manifest_payload = {
                "created": changed_files,
                "changed": [],
                "moved": [],
                "deleted": [],
                "expected_artifacts": task_pack.expected_artifacts,
                "evidence_paths": verification.evidence_paths,
            }
        artifact_manifest = validate_artifact_manifest(manifest_payload, workspace=workspace)
        missing_from_manifest = [path for path in task_pack.expected_artifacts if path not in artifact_manifest.expected_artifacts]
        if missing_from_manifest:
            raise ContractValidationError("artifact_manifest.expected_artifacts is missing required artifact(s): " + ", ".join(missing_from_manifest))
        unresolved_evidence = [
            path
            for path in verification.evidence_paths
            if path not in artifact_manifest.evidence_paths and path not in artifact_manifest.runtime_evidence_paths
        ]
        if unresolved_evidence:
            raise ContractValidationError("work_report verification evidence_paths are not resolvable in artifact_manifest: " + ", ".join(unresolved_evidence))
        exists = artifact_exists or (lambda path: Path(path).exists())
        missing_artifacts: list[str] = []
        for artifact in task_pack.expected_artifacts:
            artifact_path = _resolve_workspace_relative_path(artifact, task_pack.workspace_root_path, field="expected_artifacts")
            if not bool(exists(artifact_path)):
                missing_artifacts.append(artifact)
        if missing_artifacts:
            raise ContractValidationError("expected artifacts are missing in workspace_root: " + ", ".join(missing_artifacts))
    elif status == "BLOCKED":
        if blocker is None or "next_action" not in blocker:
            raise ContractValidationError("BLOCKED requires blocker.reason and blocker.next_action")
    elif status == "FAILED":
        if blocker is None:
            raise ContractValidationError("FAILED requires blocker.reason")
    elif status == "NEEDS_REVIEW":
        if blocker is None or next_owner is None:
            raise ContractValidationError("NEEDS_REVIEW requires blocker.reason and next_owner")

    return WorkReport(
        task_id=task_id,
        agent=agent,
        status=status,
        summary=summary,
        changed_files=changed_files,
        verification=verification,
        repair_attempts=repair_attempts,
        next_owner=next_owner,
        blocker=blocker,
        artifact_manifest=artifact_manifest,
    )


def validate_work_result(payload: Any) -> WorkResult:
    raw = _require_mapping(payload, field="work_result")
    project_id = _require_non_empty_string(raw.get("project_id"), field="project_id")
    task_id = _require_task_id(raw.get("task_id"))
    from_agent = _require_non_empty_string(raw.get("from"), field="from").lower()
    phase = _require_non_empty_string(raw.get("phase"), field="phase").upper()
    status = _require_non_empty_string(raw.get("status"), field="status").upper()
    if status not in {"DONE", "BLOCKED", "FAILED", "NEEDS_REVIEW"}:
        raise ContractValidationError("status must be one of DONE|BLOCKED|FAILED|NEEDS_REVIEW")
    summary = _require_non_empty_string(raw.get("summary"), field="summary")

    reason_raw = raw.get("reason")
    reason = None
    if reason_raw is not None:
        reason = _require_non_empty_string(reason_raw, field="reason")

    next_action_raw = raw.get("next_action")
    next_action = None
    if next_action_raw is not None:
        next_action = _require_non_empty_string(next_action_raw, field="next_action")

    verification_payload = raw.get("verification")
    verification = None
    if verification_payload is not None:
        verification = validate_verification_evidence(verification_payload)
        if verification.task_id != task_id:
            raise ContractValidationError("verification.task_id must match work_result.task_id")
        if verification.agent != from_agent:
            raise ContractValidationError("verification.agent must match work_result.from")

    if status == "DONE":
        if verification is None:
            raise ContractValidationError("DONE requires verification evidence")
    else:
        if not reason:
            raise ContractValidationError(f"{status} requires a reason")

    return WorkResult(
        project_id=project_id,
        task_id=task_id,
        from_agent=from_agent,
        phase=phase,
        status=status,
        summary=summary,
        reason=reason,
        next_action=next_action,
        verification=verification,
    )


def validate_envelope_work_result(
    envelope_payload: Any,
    *,
    expected_from: str,
    expected_phase: str,
    required_status: str | None = None,
) -> WorkResult:
    envelope = _require_mapping(envelope_payload, field="envelope")
    project_id = _require_non_empty_string(envelope.get("project_id"), field="project_id")
    task_id = _require_task_id(envelope.get("task_id"))
    from_agent = _require_non_empty_string(envelope.get("from"), field="from").lower()
    phase = _require_non_empty_string(envelope.get("phase"), field="phase").upper()
    if from_agent != expected_from.lower():
        raise ContractValidationError(f"from must be {expected_from}")
    if phase != expected_phase.upper():
        raise ContractValidationError(f"phase must be {expected_phase}")
    if "work_result" not in envelope:
        raise ContractValidationError("missing required field: work_result")
    if not isinstance(envelope.get("work_result"), Mapping):
        raise ContractValidationError("work_result must be a JSON object")
    work_result = validate_work_result(envelope.get("work_result"))
    if work_result.project_id != project_id:
        raise ContractValidationError("work_result.project_id must match envelope.project_id")
    if work_result.task_id != task_id:
        raise ContractValidationError("work_result.task_id must match envelope.task_id")
    if work_result.from_agent != from_agent:
        raise ContractValidationError("work_result.from must match envelope.from")
    if work_result.phase != phase:
        raise ContractValidationError("work_result.phase must match envelope.phase")
    if required_status and work_result.status != required_status.upper():
        raise ContractValidationError(f"work_result.status must be {required_status.upper()}")
    return work_result


def validate_done_workspace_contract(
    *,
    workspace_payload: Any,
    artifact_manifest_payload: Any,
    work_result: WorkResult,
    artifact_exists: Any,
) -> tuple[ProjectWorkspace, ArtifactManifest]:
    workspace = validate_project_workspace(workspace_payload)
    if artifact_manifest_payload is None:
        raise ContractValidationError("DONE requires artifact_manifest")
    manifest = validate_artifact_manifest(artifact_manifest_payload, workspace=workspace)
    missing_from_manifest = [path for path in workspace.expected_artifacts if path not in manifest.expected_artifacts]
    if missing_from_manifest:
        raise ContractValidationError("artifact_manifest.expected_artifacts is missing required artifact(s): " + ", ".join(missing_from_manifest))
    if work_result.verification is None:
        raise ContractValidationError("DONE requires verification evidence")
    unresolved_evidence = [
        path for path in work_result.verification.evidence_paths if path not in manifest.evidence_paths and path not in manifest.runtime_evidence_paths
    ]
    if unresolved_evidence:
        raise ContractValidationError("work_result verification evidence_paths are not resolvable in artifact_manifest: " + ", ".join(unresolved_evidence))
    workspace_root = workspace.workspace_root_path
    missing_artifacts: list[str] = []
    for artifact in workspace.expected_artifacts:
        artifact_path = _resolve_workspace_relative_path(artifact, workspace_root, field="expected_artifacts")
        if not bool(artifact_exists(artifact_path)):
            missing_artifacts.append(artifact)
    if missing_artifacts:
        raise ContractValidationError("expected artifacts are missing in workspace_root: " + ", ".join(missing_artifacts))
    return workspace, manifest
