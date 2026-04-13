"""Project snapshot persistence helpers."""

from __future__ import annotations

from openclaw_agents.database.store import ControlPlaneStore, utc_now


class SnapshotStore:
    """Capture and load persisted project snapshots at safe boundaries."""

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def capture_project_snapshot(
        self,
        project_id: str,
        *,
        captured_by: str,
        latest_human_summary: str,
        safe_boundary_type: str = "PROJECT_STATUS_SNAPSHOT_PERSISTED",
        created_from_control_event_id: str | None = None,
        created_from_run_id: str | None = None,
    ) -> dict:
        project = self.store.get_project(project_id)
        if not project:
            raise ValueError(f"unknown project {project_id}")
        workspace_ref = project.get("workspace_ref")
        if not workspace_ref:
            raise ValueError(f"project {project_id} is missing workspace_ref")

        open_tasks = [task["task_id"] for task in self.store.list_open_tasks(project_id)]
        artifact_refs = self.store.list_recent_artifact_refs(project_id)
        next_action = project.get("next_action_json") or {}
        snapshot = self.store.record_snapshot(
            {
                "project_id": project_id,
                "captured_by": captured_by,
                "project_status": project["runtime_status"],
                "current_phase": project["current_phase"],
                "current_owner_agent": project.get("current_owner_agent"),
                "open_tasks": open_tasks,
                "next_action": next_action,
                "workspace_ref": workspace_ref,
                "artifact_refs": artifact_refs,
                "latest_human_summary": latest_human_summary,
                "safe_boundary_type": safe_boundary_type,
                "created_from_control_event_id": created_from_control_event_id,
                "created_from_run_id": created_from_run_id,
                "captured_at": utc_now(),
            }
        )
        self.store.update(
            "scheduling_records",
            {"current_safe_boundary_type": safe_boundary_type},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        return snapshot

    def get_latest_snapshot(self, project_id: str) -> dict | None:
        return self.store.get_latest_snapshot(project_id)
