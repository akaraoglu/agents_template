"""Project scheduling entrypoint.

This module coordinates queue selection, lease acquisition, and safe project
switching for singleton orchestrators.
"""

from __future__ import annotations

from dataclasses import dataclass

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.scheduler.lease_manager import LeaseManager
from openclaw_agents.scheduler.queue_policy import QueueCandidate, QueuePolicy
from openclaw_agents.scheduler.recovery_manager import RecoveryManager
from openclaw_agents.scheduler.snapshot_store import SnapshotStore
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator


@dataclass(slots=True)
class SchedulingDecision:
    orchestrator_id: str
    selected_project_id: str | None
    reason: str
    queue: list[dict]


class ProjectScheduler:
    """Select and acquire the next project for a singleton orchestrator."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        lease_manager: LeaseManager | None = None,
        queue_policy: QueuePolicy | None = None,
        snapshot_store: SnapshotStore | None = None,
        workspace_validator: WorkspaceValidator | None = None,
        recovery_manager: RecoveryManager | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.lease_manager = lease_manager or LeaseManager(self.store)
        self.queue_policy = queue_policy or QueuePolicy()
        self.snapshot_store = snapshot_store or SnapshotStore(self.store)
        self.workspace_validator = workspace_validator or WorkspaceValidator(self.store)
        self.recovery_manager = recovery_manager or RecoveryManager(
            self.store,
            snapshot_store=self.snapshot_store,
            workspace_validator=self.workspace_validator,
        )

    def inspect_queue(self, orchestrator_id: str, *, now: str | None = None) -> SchedulingDecision:
        now = now or utc_now()
        records = self.store.list_projects_for_scheduler(orchestrator_id)
        candidate = self.queue_policy.choose_next_project(records, orchestrator_id=orchestrator_id, now=now)
        inspected = self.queue_policy.inspect(records, orchestrator_id=orchestrator_id, now=now)
        return SchedulingDecision(
            orchestrator_id=orchestrator_id,
            selected_project_id=candidate.project_id if candidate else None,
            reason="candidate_selected" if candidate else "no_eligible_project",
            queue=inspected,
        )

    def why_not_schedulable(self, project_id: str, *, orchestrator_id: str) -> list[str]:
        records = self.store.list_projects_for_scheduler(orchestrator_id)
        for record in records:
            if record["project_id"] == project_id:
                candidate = QueueCandidate.from_record(record)
                return self.queue_policy.reasons_not_eligible(candidate, orchestrator_id=orchestrator_id)
        return ["project_not_found_in_orchestrator_queue"]

    def acquire_next_project(
        self,
        orchestrator_id: str,
        *,
        run_id: str,
        now: str | None = None,
    ) -> dict | None:
        now = now or utc_now()
        decision = self.inspect_queue(orchestrator_id, now=now)
        if decision.selected_project_id is None:
            return None

        project_id = decision.selected_project_id
        assessment = self.recovery_manager.assess_resume(project_id, orchestrator_id=orchestrator_id)
        if not assessment.ok:
            return None

        self.lease_manager.acquire(orchestrator_id, project_id, run_id=run_id, now=now)
        project = self.store.get_project(project_id)
        if not project:
            return None
        self.store.update(
            "projects",
            {
                "runtime_status": "ACTIVE",
                "current_owner_agent": orchestrator_id,
                "updated_at": now,
                "last_activity_at": now,
            },
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        scheduling = self.store.get_scheduling_record(project_id) or {}
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "normal_ready",
                "eligible_for_scheduling": True,
                "pause_requested": False,
                "resume_requested": False,
                "preemption_allowed": True,
                "waiting_reason": None,
                "last_scheduled_at": now,
                "times_scheduled": int(scheduling.get("times_scheduled") or 0) + 1,
            },
            conflict_columns=["project_id"],
        )
        return self.store.get_project(project_id)

    def release_active_project(
        self,
        orchestrator_id: str,
        *,
        release_reason: str,
        snapshot_summary: str | None = None,
    ) -> dict | None:
        lease = self.lease_manager.get_lease(orchestrator_id)
        if not lease or lease.get("lease_status") != "HELD":
            return None
        project_id = lease.get("active_project_id")
        if not project_id:
            return None
        snapshot = None
        if snapshot_summary:
            snapshot = self.snapshot_store.capture_project_snapshot(
                project_id,
                captured_by=orchestrator_id,
                latest_human_summary=snapshot_summary,
            )
        self.lease_manager.release(orchestrator_id, release_reason=release_reason, expected_project_id=project_id)
        return snapshot
