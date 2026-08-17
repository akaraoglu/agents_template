from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import create_json
from .paths import PathValidationError, validate_identifier


DELEGATION_FILENAME = "delegation.json"
TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
ORPHAN_REASONS = {
    "thread_environment_missing", "invalid_thread_identifier", "lead_binding_missing",
    "lead_binding_unreadable", "lead_binding_project_mismatch",
}


def build_delegation(
    *,
    team_id: str,
    task_id: str,
    attempt_id: str,
    role: str,
    workspace: Path,
    created_at: str | None = None,
) -> dict[str, Any]:
    session_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    attribution = "orphan"
    reason: str | None = None
    parent_task: str | None = None
    if not session_id:
        reason = "thread_environment_missing"
    else:
        try:
            validate_identifier(session_id, label="Lead session ID")
        except PathValidationError:
            reason = "invalid_thread_identifier"
        else:
            marker_path = TOOLKIT_ROOT / ".codexteam/runtime/lead-sessions" / f"{session_id}.json"
            if marker_path.is_symlink() or not marker_path.is_file():
                reason = "lead_binding_missing"
            else:
                marker = _object(marker_path)
                if not marker:
                    reason = "lead_binding_unreadable"
                elif (
                    marker.get("session_id") != session_id
                    or marker.get("lead_root") != str(TOOLKIT_ROOT)
                    or marker.get("project") != str(workspace)
                ):
                    reason = "lead_binding_project_mismatch"
                else:
                    attribution = "bound_lead"
                    parent_task = marker.get("task_id") if isinstance(marker.get("task_id"), str) else None
    value = {
        "schema_version": "1.0",
        "kind": "lead_delegation",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "attribution": attribution,
        "parent": {
            "session_id": session_id if attribution == "bound_lead" else None,
            "task_id_at_launch": parent_task,
        },
        "child": {
            "team_id": team_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "agent_role": role,
            "workspace_root": str(workspace),
        },
    }
    if attribution == "orphan":
        value["orphan_reason"] = reason
    return validate_delegation(value)


def validate_delegation(value: Any, *, expected_child: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("delegation must be an object")
    fields = {"schema_version", "kind", "created_at", "attribution", "parent", "child"}
    if value.get("attribution") == "orphan":
        fields.add("orphan_reason")
    if set(value) != fields or value.get("schema_version") != "1.0" or value.get("kind") != "lead_delegation":
        raise ValueError("delegation fields do not match the contract")
    if value.get("attribution") not in {"bound_lead", "orphan"}:
        raise ValueError("delegation attribution is invalid")
    parent = value.get("parent")
    child = value.get("child")
    if not isinstance(parent, dict) or set(parent) != {"session_id", "task_id_at_launch"}:
        raise ValueError("delegation parent is invalid")
    required_child = {"team_id", "task_id", "attempt_id", "agent_role", "workspace_root"}
    if not isinstance(child, dict) or set(child) != required_child:
        raise ValueError("delegation child is invalid")
    if any(not isinstance(child.get(field), str) or not child[field] for field in required_child):
        raise ValueError("delegation child values must be non-empty strings")
    if value["attribution"] == "bound_lead":
        if not isinstance(parent.get("session_id"), str) or not parent["session_id"]:
            raise ValueError("bound delegation requires a parent session")
        if "orphan_reason" in value:
            raise ValueError("bound delegation cannot have an orphan reason")
    else:
        if parent.get("session_id") is not None or value.get("orphan_reason") not in ORPHAN_REASONS:
            raise ValueError("orphan delegation is invalid")
    if expected_child and any(child.get(key) != expected for key, expected in expected_child.items()):
        raise ValueError("delegation child identity mismatch")
    return value


def write_delegation(path: Path, value: dict[str, Any]) -> None:
    validate_delegation(value)
    create_json(path, value)


def load_delegation(path: Path, *, expected_child: dict[str, str] | None = None) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("delegation is missing or unsafe")
    value = _object(path)
    if not value:
        raise ValueError("delegation is unreadable")
    return validate_delegation(value, expected_child=expected_child)


def delegation_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
