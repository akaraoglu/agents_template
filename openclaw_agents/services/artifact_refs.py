"""Artifact reference and execution handoff persistence helpers."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths

from .state_store import StateStore


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class ArtifactRefService:
    def __init__(self, state_store: StateStore, artifacts_root: Path | None = None) -> None:
        self.state_store = state_store
        self.artifacts_root = artifacts_root or RuntimePaths.from_root().ensure().artifacts_root
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def create_artifact_ref(
        self, project_id: str, artifact_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        target_dir = self.artifacts_root / project_id
        target_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = target_dir / f"{artifact_type}_{artifact_id}.json"
        artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "artifact_type": artifact_type,
            "path": str(artifact_path),
            "created_at": _utc_now(),
        }

    def build_execution_handoff(
        self,
        project: dict[str, Any],
        approved_summary: str,
        from_agent: str = "agent_smith",
        to_agent: str = "niaobe",
    ) -> dict[str, Any]:
        return {
            "handoff_id": str(uuid.uuid4()),
            "project_id": project["id"],
            "project_name": project.get("name", project["id"]),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "status": "PENDING",
            "summary": approved_summary,
            "workspace_path": project.get("workspace_path"),
            "canonical_stream": project.get("canonical_stream", "projects"),
            "canonical_topic": project.get("canonical_topic", f"project/{project['id']}"),
            "created_at": _utc_now(),
        }

    def persist_execution_handoff(self, packet: dict[str, Any]) -> dict[str, Any]:
        artifact_ref = self.create_artifact_ref(
            project_id=packet["project_id"],
            artifact_type="execution_handoff",
            payload=packet,
        )
        stored = self.state_store.add_handoff({**packet, "artifact_ref": artifact_ref})
        project = self.state_store.get_project(packet["project_id"]) or {}
        if project:
            project["last_handoff_id"] = stored["handoff_id"]
            project["handoff_status"] = stored.get("status", "PENDING")
            next_actions = project.get("next_actions")
            if not next_actions:
                project["next_actions"] = ["Niaobe to start execution loop."]
            self.state_store.upsert_project(project)
        return stored
