"""Artifact parsing helpers for workspace and store-backed refs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.database.store import ControlPlaneStore


class ArtifactParser:
    """Load artifact payloads from database records, workspace files, or inline refs."""

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self.store.fetchone("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,))

    def _parse_text(self, path: Path) -> Any:
        text = path.read_text()
        if path.suffix in {".yaml", ".yml"}:
            return yaml.safe_load(text)
        if path.suffix == ".json":
            return json.loads(text)
        return text

    def parse_record(self, record: dict[str, Any]) -> Any:
        backend = record["store_backend"]
        if backend == "inline_json":
            return (record.get("metadata_json") or {}).get("payload")
        if backend == "workspace":
            return self._parse_text(Path(record["ref"]))
        if backend == "external_ref":
            return {"ref": record["ref"], "metadata": record.get("metadata_json") or {}}
        if backend == "artifact_store":
            return {"ref": record["ref"], "metadata": record.get("metadata_json") or {}}
        raise ValueError(f"unsupported artifact backend {backend}")

    def parse_artifact(self, artifact_id: str) -> Any:
        record = self.get_artifact(artifact_id)
        if not record:
            raise ValueError(f"unknown artifact {artifact_id}")
        return self.parse_record(record)

    def parse_ref(self, ref: str) -> Any:
        if ref.startswith("inline://"):
            artifact_id = ref.split("://", 1)[1]
            return self.parse_artifact(artifact_id)
        path = Path(ref)
        if path.exists():
            return self._parse_text(path)
        raise ValueError(f"unsupported or missing artifact ref {ref}")

    def list_project_artifacts(
        self,
        project_id: str,
        *,
        artifact_type: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM artifacts WHERE project_id = ?"
        params: list[Any] = [project_id]
        if artifact_type:
            sql += " AND artifact_type = ?"
            params.append(artifact_type)
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at ASC"
        return self.store.fetchall(sql, params)

    def summarize_artifacts(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for record in records:
            summary.append(
                {
                    "artifact_id": record["artifact_id"],
                    "artifact_type": record["artifact_type"],
                    "store_backend": record["store_backend"],
                    "ref": record["ref"],
                    "task_id": record.get("task_id"),
                    "produced_by_agent": record.get("produced_by_agent"),
                }
            )
        return summary
