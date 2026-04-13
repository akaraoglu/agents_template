"""Artifact serialization helpers for workspace and store-backed refs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.database.store import ControlPlaneStore, utc_now

ARTIFACT_TYPES = {
    "clarification_brief",
    "project_charter",
    "project_status_report",
    "architecture_spec",
    "software_task_plan",
    "code_change",
    "test_execution_report",
    "software_delivery_package",
    "verification_report",
    "escalation_packet",
    "executive_decision",
    "project_closure_report",
}


def artifact_bucket_for_type(artifact_type: str) -> str:
    if artifact_type in {"project_status_report", "test_execution_report", "verification_report", "project_closure_report"}:
        return "reports"
    return "outgoing"


def artifact_extension(payload: Any) -> str:
    if isinstance(payload, str):
        return ".md"
    if isinstance(payload, (dict, list)):
        return ".yaml"
    return ".txt"


class ArtifactSerializer:
    """Persist artifacts to workspace paths or inline refs and record them in the database."""

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def _workspace_root(self, workspace_ref: str | None) -> Path:
        if not workspace_ref:
            raise ValueError("workspace_ref is required for workspace-backed artifacts")
        root = Path(workspace_ref)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _artifact_dir(self, workspace_ref: str, artifact_type: str) -> Path:
        root = self._workspace_root(workspace_ref)
        bucket = artifact_bucket_for_type(artifact_type)
        directory = root / "artifacts" / bucket
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _render_payload(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload if payload.endswith("\n") else payload + "\n"
        if isinstance(payload, (dict, list)):
            return yaml.safe_dump(payload, sort_keys=False)
        return f"{payload}\n"

    def serialize_to_workspace(
        self,
        *,
        project_id: str,
        artifact_type: str,
        payload: Any,
        workspace_ref: str,
        task_id: str | None = None,
        produced_by_agent: str | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"unsupported artifact_type {artifact_type}")
        artifact_id = self.store.new_id("artifact")
        directory = self._artifact_dir(workspace_ref, artifact_type)
        suffix = artifact_extension(payload)
        safe_filename = filename or f"{artifact_type}_{artifact_id}{suffix}"
        path = directory / safe_filename
        path.write_text(self._render_payload(payload))
        record = {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "task_id": task_id,
            "produced_by_agent": produced_by_agent,
            "artifact_type": artifact_type,
            "store_backend": "workspace",
            "ref": str(path),
            "content_hash": None,
            "metadata_json": {
                "workspace_ref": workspace_ref,
                "filename": safe_filename,
                "bucket": artifact_bucket_for_type(artifact_type),
                "created_at": utc_now(),
                **(metadata or {}),
            },
            "created_at": utc_now(),
        }
        self.store.upsert("artifacts", record, conflict_columns=["artifact_id"])
        return record

    def serialize_inline(
        self,
        *,
        project_id: str,
        artifact_type: str,
        payload: Any,
        task_id: str | None = None,
        produced_by_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"unsupported artifact_type {artifact_type}")
        artifact_id = self.store.new_id("artifact")
        record = {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "task_id": task_id,
            "produced_by_agent": produced_by_agent,
            "artifact_type": artifact_type,
            "store_backend": "inline_json",
            "ref": f"inline://{artifact_id}",
            "content_hash": None,
            "metadata_json": {"payload": payload, **(metadata or {})},
            "created_at": utc_now(),
        }
        self.store.upsert("artifacts", record, conflict_columns=["artifact_id"])
        return record

    def serialize(
        self,
        *,
        project_id: str,
        artifact_type: str,
        payload: Any,
        task_id: str | None = None,
        produced_by_agent: str | None = None,
        workspace_ref: str | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if workspace_ref:
            return self.serialize_to_workspace(
                project_id=project_id,
                artifact_type=artifact_type,
                payload=payload,
                workspace_ref=workspace_ref,
                task_id=task_id,
                produced_by_agent=produced_by_agent,
                filename=filename,
                metadata=metadata,
            )
        return self.serialize_inline(
            project_id=project_id,
            artifact_type=artifact_type,
            payload=payload,
            task_id=task_id,
            produced_by_agent=produced_by_agent,
            metadata=metadata,
        )

    def serialize_many(
        self,
        *,
        project_id: str,
        artifacts: list[dict[str, Any]],
        workspace_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in artifacts:
            records.append(
                self.serialize(
                    project_id=project_id,
                    artifact_type=item["artifact_type"],
                    payload=item["payload"],
                    task_id=item.get("task_id"),
                    produced_by_agent=item.get("produced_by_agent"),
                    workspace_ref=item.get("workspace_ref", workspace_ref),
                    filename=item.get("filename"),
                    metadata=item.get("metadata"),
                )
            )
        return records
