"""Priority and fairness policy helpers for project scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from openclaw_agents.database.store import parse_timestamp, utc_now

PRIORITY_ORDER = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
QUEUE_ORDER = {"urgent": 0, "active_recovery": 1, "normal_ready": 2, "waiting_external": 3, "blocked": 4}


@dataclass(slots=True)
class QueueCandidate:
    project_id: str
    project_status: str
    runtime_status: str
    priority: str
    queue_state: str
    eligible_for_scheduling: bool
    pause_requested: bool
    resume_requested: bool
    preemption_allowed: bool
    waiting_reason: str | None
    last_scheduled_at: str | None
    times_scheduled: int
    fairness_deadline_at: str | None
    workspace_ref: str | None
    last_snapshot_id: str | None
    current_safe_boundary_type: str | None
    last_snapshot_safe_boundary_type: str | None
    next_action_json: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "QueueCandidate":
        return cls(
            project_id=record["project_id"],
            project_status=record["project_status"],
            runtime_status=record["runtime_status"],
            priority=record["priority"],
            queue_state=record.get("queue_state") or "normal_ready",
            eligible_for_scheduling=bool(record.get("eligible_for_scheduling")),
            pause_requested=bool(record.get("pause_requested")),
            resume_requested=bool(record.get("resume_requested")),
            preemption_allowed=bool(record.get("preemption_allowed")),
            waiting_reason=record.get("waiting_reason"),
            last_scheduled_at=record.get("last_scheduled_at"),
            times_scheduled=int(record.get("times_scheduled") or 0),
            fairness_deadline_at=record.get("fairness_deadline_at"),
            workspace_ref=record.get("workspace_ref"),
            last_snapshot_id=record.get("last_snapshot_id"),
            current_safe_boundary_type=record.get("current_safe_boundary_type"),
            last_snapshot_safe_boundary_type=record.get("last_snapshot_safe_boundary_type"),
            next_action_json=record.get("next_action_json"),
            raw=record,
        )


class QueuePolicy:
    """Apply eligibility checks and choose the next project for an orchestrator."""

    def __init__(self, *, fairness_window_minutes: int = 240) -> None:
        self.fairness_window_minutes = fairness_window_minutes

    def reasons_not_eligible(self, candidate: QueueCandidate, *, orchestrator_id: str) -> list[str]:
        reasons: list[str] = []
        if candidate.project_status in {"DONE", "CANCELLED"}:
            reasons.append("project_already_terminal")
        if candidate.runtime_status in {"DONE", "CANCELLED", "BLOCKED", "PAUSE_REQUESTED"}:
            reasons.append(f"runtime_status_{candidate.runtime_status.lower()}")
        if not candidate.eligible_for_scheduling:
            reasons.append("scheduler_marked_ineligible")
        if candidate.pause_requested:
            reasons.append("pause_requested")
        if not candidate.workspace_ref:
            reasons.append("missing_workspace_ref")
        if not candidate.last_snapshot_id:
            reasons.append("missing_snapshot")
        if orchestrator_id == "niobe" and candidate.runtime_status not in {"NEW", "READY", "ACTIVE", "PAUSED"}:
            reasons.append("not_ready_for_niobe")
        if orchestrator_id == "morpheus":
            if candidate.runtime_status not in {"READY", "ACTIVE", "PAUSED"}:
                reasons.append("not_ready_for_morpheus")
            if not candidate.next_action_json:
                reasons.append("missing_software_next_action")
        return reasons

    def _sort_key(self, candidate: QueueCandidate, *, now: str) -> tuple[Any, ...]:
        now_dt = parse_timestamp(now) or datetime.now(timezone.utc)
        fairness_deadline = parse_timestamp(candidate.fairness_deadline_at)
        overdue = bool(fairness_deadline and fairness_deadline <= now_dt and candidate.priority != "URGENT")
        last_scheduled = parse_timestamp(candidate.last_scheduled_at) or datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (
            PRIORITY_ORDER.get(candidate.priority, 99),
            0 if candidate.resume_requested else 1,
            0 if overdue else 1,
            QUEUE_ORDER.get(candidate.queue_state, 99),
            last_scheduled,
            candidate.times_scheduled,
            candidate.project_id,
        )

    def inspect(self, records: list[dict[str, Any]], *, orchestrator_id: str, now: str | None = None) -> list[dict[str, Any]]:
        now = now or utc_now()
        inspected: list[dict[str, Any]] = []
        for record in records:
            candidate = QueueCandidate.from_record(record)
            reasons = self.reasons_not_eligible(candidate, orchestrator_id=orchestrator_id)
            inspected.append(
                {
                    "project_id": candidate.project_id,
                    "priority": candidate.priority,
                    "queue_state": candidate.queue_state,
                    "eligible": not reasons,
                    "reasons": reasons,
                    "resume_requested": candidate.resume_requested,
                    "last_scheduled_at": candidate.last_scheduled_at,
                }
            )
        return inspected

    def choose_next_project(
        self,
        records: list[dict[str, Any]],
        *,
        orchestrator_id: str,
        now: str | None = None,
    ) -> QueueCandidate | None:
        now = now or utc_now()
        candidates: list[QueueCandidate] = []
        for record in records:
            candidate = QueueCandidate.from_record(record)
            if not self.reasons_not_eligible(candidate, orchestrator_id=orchestrator_id):
                candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: self._sort_key(candidate, now=now))
        return candidates[0]
