"""Pause, resume, switch, cancel, and reprioritize command handlers."""

from __future__ import annotations

from dataclasses import dataclass

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.scheduler.lease_manager import LeaseConflictError, LeaseManager
from openclaw_agents.scheduler.recovery_manager import RecoveryManager
from openclaw_agents.scheduler.snapshot_store import SnapshotStore
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator


@dataclass(slots=True)
class ControlCommandResult:
    event_id: str
    command: str
    status: str
    summary: str
    project_id: str


class ControlCommandService:
    """Persist and apply control-plane commands for scheduling and switching."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        lease_manager: LeaseManager | None = None,
        snapshot_store: SnapshotStore | None = None,
        recovery_manager: RecoveryManager | None = None,
        workspace_validator: WorkspaceValidator | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.lease_manager = lease_manager or LeaseManager(self.store)
        self.snapshot_store = snapshot_store or SnapshotStore(self.store)
        self.recovery_manager = recovery_manager or RecoveryManager(self.store, snapshot_store=self.snapshot_store)
        self.workspace_validator = workspace_validator or WorkspaceValidator(self.store)

    def _record(
        self,
        *,
        project_id: str,
        command: str,
        requested_by: str,
        status: str,
        args: dict,
        orchestrator_id: str | None = None,
        reason: str | None = None,
        result_summary: str,
    ) -> ControlCommandResult:
        event = self.store.record_control_event(
            project_id=project_id,
            command=command,
            requested_by=requested_by,
            status=status,
            args=args,
            orchestrator_id=orchestrator_id,
            reason=reason,
            result_summary=result_summary,
        )
        return ControlCommandResult(event["event_id"], command, status, result_summary, project_id)

    def _is_safe_to_switch(self, project_id: str) -> bool:
        project = self.store.get_project(project_id)
        if not project:
            return False
        if project["runtime_status"] in {"PAUSED", "WAITING_EXTERNAL", "WAITING_VERIFICATION", "BLOCKED"}:
            return True
        scheduling = self.store.get_scheduling_record(project_id) or {}
        if scheduling.get("current_safe_boundary_type"):
            return True
        snapshot = self.store.get_latest_snapshot(project_id)
        return bool(snapshot and snapshot.get("safe_boundary_type"))

    def pause_project(
        self,
        project_id: str,
        *,
        requested_by: str,
        latest_human_summary: str,
        orchestrator_id: str | None = None,
        reason: str | None = None,
    ) -> ControlCommandResult:
        existing = self.store.get_scheduling_record(project_id) or {}
        try:
            snapshot = self.snapshot_store.capture_project_snapshot(
                project_id,
                captured_by=requested_by,
                latest_human_summary=latest_human_summary,
                safe_boundary_type="PROJECT_STATUS_SNAPSHOT_PERSISTED",
            )
        except ValueError as exc:
            return self._record(
                project_id=project_id,
                command="PAUSE_PROJECT",
                requested_by=requested_by,
                status="REJECTED",
                args={},
                orchestrator_id=orchestrator_id,
                reason=reason,
                result_summary=str(exc),
            )
        now = utc_now()
        self.store.update(
            "projects",
            {"runtime_status": "PAUSED", "updated_at": now, "last_activity_at": now},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "waiting_external",
                "eligible_for_scheduling": False,
                "pause_requested": True,
                "resume_requested": False,
                "preemption_allowed": False,
                "waiting_reason": "paused_by_operator",
                "last_scheduled_at": existing.get("last_scheduled_at") or now,
                "times_scheduled": int(existing.get("times_scheduled") or 0),
                "current_safe_boundary_type": snapshot["safe_boundary_type"],
            },
            conflict_columns=["project_id"],
        )
        self.lease_manager.release_project_leases(project_id, release_reason="pause-project")
        return self._record(
            project_id=project_id,
            command="PAUSE_PROJECT",
            requested_by=requested_by,
            status="APPLIED",
            args={"snapshot_id": snapshot["snapshot_id"]},
            orchestrator_id=orchestrator_id,
            reason=reason,
            result_summary="project paused at persisted boundary",
        )

    def resume_project(
        self,
        project_id: str,
        *,
        requested_by: str,
        orchestrator_id: str | None = None,
    ) -> ControlCommandResult:
        assessment = self.recovery_manager.assess_resume(project_id, orchestrator_id=orchestrator_id)
        if not assessment.ok:
            return self._record(
                project_id=project_id,
                command="RESUME_PROJECT",
                requested_by=requested_by,
                status="REJECTED",
                args={},
                orchestrator_id=orchestrator_id,
                result_summary=assessment.summary,
            )

        now = utc_now()
        existing = self.store.get_scheduling_record(project_id) or {}
        self.store.update(
            "projects",
            {"runtime_status": "READY", "updated_at": now, "last_activity_at": now},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "active_recovery",
                "eligible_for_scheduling": True,
                "pause_requested": False,
                "resume_requested": True,
                "preemption_allowed": True,
                "waiting_reason": None,
                "last_scheduled_at": existing.get("last_scheduled_at") or now,
                "times_scheduled": int(existing.get("times_scheduled") or 0),
            },
            conflict_columns=["project_id"],
        )
        return self._record(
            project_id=project_id,
            command="RESUME_PROJECT",
            requested_by=requested_by,
            status="APPLIED",
            args={},
            orchestrator_id=orchestrator_id,
            result_summary="project marked resumable and returned to scheduler queue",
        )

    def reprioritize_project(
        self,
        project_id: str,
        *,
        requested_by: str,
        priority: str,
    ) -> ControlCommandResult:
        now = utc_now()
        self.store.update(
            "projects",
            {"priority": priority, "updated_at": now},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        return self._record(
            project_id=project_id,
            command="REPRIORITIZE_PROJECT",
            requested_by=requested_by,
            status="APPLIED",
            args={"priority": priority},
            result_summary=f"project priority set to {priority}",
        )

    def cancel_project(self, project_id: str, *, requested_by: str, reason: str) -> ControlCommandResult:
        now = utc_now()
        existing = self.store.get_scheduling_record(project_id) or {}
        self.store.update(
            "projects",
            {
                "project_status": "CANCELLED",
                "runtime_status": "CANCELLED",
                "updated_at": now,
                "last_activity_at": now,
            },
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
                "waiting_reason": "cancelled",
                "last_scheduled_at": existing.get("last_scheduled_at") or now,
                "times_scheduled": int(existing.get("times_scheduled") or 0),
            },
            conflict_columns=["project_id"],
        )
        self.lease_manager.release_project_leases(project_id, release_reason="cancel-project")
        return self._record(
            project_id=project_id,
            command="CANCEL_PROJECT",
            requested_by=requested_by,
            status="APPLIED",
            args={"reason": reason},
            reason=reason,
            result_summary="project cancelled",
        )

    def create_status_snapshot(
        self,
        project_id: str,
        *,
        requested_by: str,
        latest_human_summary: str,
    ) -> ControlCommandResult:
        try:
            snapshot = self.snapshot_store.capture_project_snapshot(
                project_id,
                captured_by=requested_by,
                latest_human_summary=latest_human_summary,
                safe_boundary_type="PROJECT_STATUS_SNAPSHOT_PERSISTED",
            )
        except ValueError as exc:
            return self._record(
                project_id=project_id,
                command="STATUS_SNAPSHOT",
                requested_by=requested_by,
                status="REJECTED",
                args={},
                result_summary=str(exc),
            )
        return self._record(
            project_id=project_id,
            command="STATUS_SNAPSHOT",
            requested_by=requested_by,
            status="APPLIED",
            args={"snapshot_id": snapshot["snapshot_id"]},
            result_summary="project snapshot persisted",
        )

    def force_interrupt(
        self,
        project_id: str,
        *,
        requested_by: str,
        orchestrator_id: str,
        reason: str,
    ) -> ControlCommandResult:
        self.recovery_manager.record_forced_interrupt(project_id, orchestrator_id=orchestrator_id, reason=reason)
        now = utc_now()
        existing = self.store.get_scheduling_record(project_id) or {}
        self.store.update(
            "projects",
            {"runtime_status": "PAUSE_REQUESTED", "updated_at": now, "last_activity_at": now},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "blocked",
                "eligible_for_scheduling": False,
                "pause_requested": True,
                "resume_requested": False,
                "preemption_allowed": False,
                "waiting_reason": "forced_interrupt",
                "last_scheduled_at": existing.get("last_scheduled_at") or now,
                "times_scheduled": int(existing.get("times_scheduled") or 0),
            },
            conflict_columns=["project_id"],
        )
        self.lease_manager.release(orchestrator_id, release_reason="force-interrupt")
        return self._record(
            project_id=project_id,
            command="FORCE_INTERRUPT",
            requested_by=requested_by,
            status="APPLIED",
            args={"orchestrator_id": orchestrator_id, "reason": reason},
            orchestrator_id=orchestrator_id,
            reason=reason,
            result_summary="project interrupted and marked for recovery",
        )

    def switch_project(
        self,
        *,
        from_project_id: str,
        to_project_id: str,
        orchestrator_id: str,
        requested_by: str,
        reason: str | None = None,
        force: bool = False,
    ) -> ControlCommandResult:
        if not force and not self._is_safe_to_switch(from_project_id):
            return self._record(
                project_id=from_project_id,
                command="SWITCH_PROJECT",
                requested_by=requested_by,
                status="REJECTED",
                args={"from_project_id": from_project_id, "to_project_id": to_project_id},
                orchestrator_id=orchestrator_id,
                reason=reason,
                result_summary="switch rejected because the current project is not at a safe boundary",
            )

        validation = self.workspace_validator.validate_project(to_project_id)
        if not validation.ok:
            return self._record(
                project_id=to_project_id,
                command="SWITCH_PROJECT",
                requested_by=requested_by,
                status="REJECTED",
                args={"from_project_id": from_project_id, "to_project_id": to_project_id},
                orchestrator_id=orchestrator_id,
                reason=reason,
                result_summary=f"target project failed workspace validation: {validation.summary}",
            )

        try:
            current_snapshot = self.snapshot_store.capture_project_snapshot(
                from_project_id,
                captured_by=requested_by,
                latest_human_summary="project switched away after persisted boundary",
                safe_boundary_type="PROJECT_STATUS_SNAPSHOT_PERSISTED",
            )
        except ValueError as exc:
            return self._record(
                project_id=from_project_id,
                command="SWITCH_PROJECT",
                requested_by=requested_by,
                status="REJECTED",
                args={"from_project_id": from_project_id, "to_project_id": to_project_id},
                orchestrator_id=orchestrator_id,
                reason=reason,
                result_summary=str(exc),
            )
        now = utc_now()
        self.lease_manager.release(orchestrator_id, release_reason="switch-project", expected_project_id=from_project_id)
        self.store.update(
            "projects",
            {"runtime_status": "PAUSED", "updated_at": now},
            where_clause="project_id = ?",
            where_params=[from_project_id],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": from_project_id,
                "queue_state": "active_recovery",
                "eligible_for_scheduling": True,
                "pause_requested": False,
                "resume_requested": True,
                "preemption_allowed": True,
                "waiting_reason": "switched_away",
                "last_scheduled_at": now,
                "times_scheduled": 0,
                "current_safe_boundary_type": current_snapshot["safe_boundary_type"],
            },
            conflict_columns=["project_id"],
        )

        event_id = self.store.new_id("ctrl")
        try:
            self.lease_manager.acquire(orchestrator_id, to_project_id, run_id=event_id)
        except LeaseConflictError as exc:
            return self._record(
                project_id=to_project_id,
                command="SWITCH_PROJECT",
                requested_by=requested_by,
                status="FAILED",
                args={"from_project_id": from_project_id, "to_project_id": to_project_id},
                orchestrator_id=orchestrator_id,
                reason=reason,
                result_summary=str(exc),
            )

        self.store.update(
            "projects",
            {
                "runtime_status": "ACTIVE",
                "current_owner_agent": orchestrator_id,
                "updated_at": now,
                "last_activity_at": now,
            },
            where_clause="project_id = ?",
            where_params=[to_project_id],
        )
        existing = self.store.get_scheduling_record(to_project_id) or {}
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": to_project_id,
                "queue_state": "normal_ready",
                "eligible_for_scheduling": True,
                "pause_requested": False,
                "resume_requested": False,
                "preemption_allowed": True,
                "waiting_reason": None,
                "last_scheduled_at": now,
                "times_scheduled": int(existing.get("times_scheduled") or 0) + 1,
                "last_switch_reason": reason or "OPERATOR_REQUEST",
            },
            conflict_columns=["project_id"],
        )
        event = self.store.record_control_event(
            project_id=to_project_id,
            command="SWITCH_PROJECT",
            requested_by=requested_by,
            status="APPLIED",
            args={"from_project_id": from_project_id, "to_project_id": to_project_id},
            orchestrator_id=orchestrator_id,
            reason=reason,
            result_summary="switch completed",
            event_id=event_id,
        )
        return ControlCommandResult(event["event_id"], "SWITCH_PROJECT", "APPLIED", "switch completed", to_project_id)
