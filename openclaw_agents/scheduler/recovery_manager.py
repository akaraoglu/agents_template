"""Recovery hooks for interrupted runs, lease expiry, and broken workspaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.scheduler.snapshot_store import SnapshotStore
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator


@dataclass(slots=True)
class RecoveryAssessment:
    ok: bool
    summary: str
    issues: list[str]
    recovery_event_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)


class RecoveryManager:
    """Drive recovery-state persistence and resume readiness checks."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        workspace_validator: WorkspaceValidator | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.snapshot_store = snapshot_store or SnapshotStore(self.store)
        self.workspace_validator = workspace_validator or WorkspaceValidator(self.store)

    def assess_resume(self, project_id: str, *, orchestrator_id: str | None = None) -> RecoveryAssessment:
        project = self.store.get_project(project_id)
        if not project:
            return RecoveryAssessment(False, f"unknown project {project_id}", ["missing_project"])

        snapshot = self.snapshot_store.get_latest_snapshot(project_id)
        issues: list[str] = []
        details: dict[str, object] = {
            "project_id": project_id,
            "workspace_ref": project.get("workspace_ref"),
            "latest_snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
        }
        if not snapshot:
            issues.append("missing_snapshot")
        validation = self.workspace_validator.validate_project(project_id)
        details["workspace_validation"] = {
            "ok": validation.ok,
            "summary": validation.summary,
            "issues": validation.issues,
            "details": validation.details,
        }
        if not validation.ok:
            issues.extend(validation.issues)
        active_leases = self.store.list_active_leases_for_project(project_id)
        if active_leases:
            issues.append("active_orchestrator_lease_present")
            details["active_leases"] = active_leases

        active_attempts = self.store.list_project_active_task_attempts(project_id)
        if active_attempts:
            issues.append("active_task_attempts_present")
            details["active_task_attempts"] = [
                {
                    "attempt_id": attempt["attempt_id"],
                    "task_id": attempt["task_id"],
                    "agent_id": attempt["agent_id"],
                    "status": attempt["status"],
                }
                for attempt in active_attempts
            ]

        active_runs = self.store.list_project_active_agent_runs(project_id)
        if active_runs:
            issues.append("active_agent_runs_present")
            details["active_agent_runs"] = [
                {
                    "run_id": run["run_id"],
                    "task_id": run["task_id"],
                    "agent_id": run["agent_id"],
                    "runtime_backend": run["runtime_backend"],
                }
                for run in active_runs
            ]

        issues = list(dict.fromkeys(issues))

        if issues:
            event = self.store.record_recovery_event(
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                workspace_ref=project.get("workspace_ref"),
                failure_mode="resume_readiness_failed",
                action_taken="blocked_project_pending_recovery",
                status="OPEN",
                details=details | {"issues": issues},
            )
            self.store.update(
                "projects",
                {"runtime_status": "BLOCKED", "updated_at": utc_now()},
                where_clause="project_id = ?",
                where_params=[project_id],
            )
            self.store.upsert(
                "scheduling_records",
                {
                    "project_id": project_id,
                    "queue_state": "blocked",
                    "eligible_for_scheduling": False,
                    "pause_requested": False,
                    "resume_requested": False,
                    "preemption_allowed": False,
                    "waiting_reason": "recovery_required",
                    "last_scheduled_at": project.get("last_activity_at"),
                    "times_scheduled": 0,
                },
                conflict_columns=["project_id"],
            )
            summary = f"resume blocked pending recovery: {', '.join(issues)}"
            return RecoveryAssessment(False, summary, issues, event["recovery_id"], details)

        return RecoveryAssessment(True, "resume is safe", [], details=details)

    def record_forced_interrupt(
        self,
        project_id: str,
        *,
        orchestrator_id: str,
        reason: str,
    ) -> dict:
        project = self.store.get_project(project_id)
        snapshot = self.snapshot_store.get_latest_snapshot(project_id)
        return self.store.record_recovery_event(
            project_id=project_id,
            orchestrator_id=orchestrator_id,
            workspace_ref=project.get("workspace_ref") if project else None,
            failure_mode="forced_interrupt",
            action_taken=reason,
            status="OPEN",
            details={
                "requires_recovery_assessment": True,
                "latest_snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
            },
        )
