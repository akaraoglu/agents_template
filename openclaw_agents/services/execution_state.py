"""Durable execution-state tracking for Niaobe handoff consumption."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .projection_events import ProjectionEventService
from .project_provisioning import ProjectProvisioningService
from .state_store import StateStore
from .workspace_service import WorkspaceService


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class ExecutionStateService:
    def __init__(
        self,
        state_store: StateStore,
        project_provisioning: ProjectProvisioningService,
        projection_event_service: ProjectionEventService,
    ) -> None:
        self.state_store = state_store
        self.project_provisioning = project_provisioning
        self.projection_event_service = projection_event_service

    def get_or_create_for_handoff(self, handoff: dict[str, Any], *, actor_agent: str) -> dict[str, Any]:
        existing = self.state_store.list_execution_states(handoff_id=handoff["handoff_id"])
        if existing:
            return existing[-1]
        record = {
            "execution_id": str(uuid.uuid4()),
            "handoff_id": handoff["handoff_id"],
            "project_id": handoff["project_id"],
            "project_name": handoff.get("project_name", handoff["project_id"]),
            "owner_agent": actor_agent,
            "status": "PENDING",
            "workspace_path": handoff.get("workspace_path"),
            "summary": handoff.get("summary", ""),
            "latest_note": "",
            "blockers": [],
            "verification_reports": [],
            "created_at": _utc_now(),
        }
        return self.state_store.upsert_execution_state(record)

    def intake_handoff(self, handoff: dict[str, Any], *, actor_agent: str) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self.get_or_create_for_handoff(handoff, actor_agent=actor_agent)
        emitted_event: dict[str, Any] | None = None
        if state.get("status") != "IN_PROGRESS":
            state = self.state_store.upsert_execution_state(
                {
                    **state,
                    "status": "IN_PROGRESS",
                    "latest_note": "Execution intake started.",
                    "started_at": state.get("started_at", _utc_now()),
                }
            )
            self.state_store.update_handoff(
                handoff["handoff_id"],
                {"status": "IN_PROGRESS", "claimed_by": actor_agent},
            )
            emitted_event = self.projection_event_service.record_event(
                event_type="execution_started",
                project_id=handoff["project_id"],
                summary=f"Niaobe started execution for {handoff.get('project_name', handoff['project_id'])}.",
                payload={
                    "handoff_id": handoff["handoff_id"],
                    "execution_id": state["execution_id"],
                    "status": state["status"],
                },
                actor_agent=actor_agent,
            )
        return state, emitted_event or {}

    def get_state(self, *, handoff_id: str | None = None, project_id: str | None = None) -> dict[str, Any] | None:
        rows = self.state_store.list_execution_states(handoff_id=handoff_id, project_id=project_id)
        return rows[-1] if rows else None

    def get_execution_state_for_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        return self.get_state(handoff_id=handoff_id)

    def get_pending_handoff(self, *, project_id: str | None = None) -> dict[str, Any] | None:
        rows = self.state_store.list_handoffs(project_id=project_id, assignee_agent="niaobe")
        candidates = [
            row
            for row in rows
            if row.get("status") in {"PENDING", "IN_PROGRESS", "BLOCKED", "VERIFICATION_REPORTED"}
        ]
        return candidates[-1] if candidates else None

    def start_execution(self, handoff_id: str, *, actor_agent: str) -> dict[str, Any]:
        handoff = self.state_store.get_handoff(handoff_id)
        if not handoff:
            raise ValueError(f"Handoff '{handoff_id}' was not found.")
        state, event = self.intake_handoff(handoff, actor_agent=actor_agent)
        current_handoff = self.state_store.get_handoff(handoff_id) or handoff
        events = [event] if event else []
        return {"handoff": current_handoff, "execution_state": state, "projection_events": events}

    def list_states(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.state_store.list_execution_states(status=status, project_id=project_id)

    def start_execution(self, handoff_id: str, *, actor_agent: str) -> dict[str, Any]:
        handoff = self.state_store.get_handoff(handoff_id)
        if not handoff:
            raise ValueError(f"Handoff '{handoff_id}' was not found.")
        state, event = self.intake_handoff(handoff, actor_agent=actor_agent)
        events = [event] if event else []
        return {"handoff": handoff, "execution_state": state, "projection_events": events}

    def report_blocker(
        self,
        *,
        handoff_id: str,
        actor_agent: str,
        blocker: str,
        next_step: str | None = None,
        escalation_target: str | None = None,
    ) -> dict[str, Any]:
        handoff = self.state_store.get_handoff(handoff_id)
        if not handoff:
            raise ValueError(f"Handoff '{handoff_id}' was not found.")
        state = self.get_or_create_for_handoff(handoff, actor_agent=actor_agent)
        blockers = [*state.get("blockers", []), blocker]
        note = next_step.strip() if next_step else "Awaiting AgentSmith guidance."
        state = self.state_store.upsert_execution_state(
            {
                **state,
                "status": "BLOCKED",
                "blockers": blockers,
                "latest_note": note,
                "blocked_at": _utc_now(),
            }
        )
        self.state_store.update_handoff(handoff_id, {"status": "BLOCKED"})
        project = self.project_provisioning.update_project_surface(
            project_id=handoff["project_id"],
            updates={"status": "BLOCKED", "blockers": blockers, "next_actions": [note]},
            requested_by=actor_agent,
        )
        event = self.projection_event_service.record_event(
            event_type="execution_blocked",
            project_id=handoff["project_id"],
            summary=f"Niaobe reported an execution blocker for {project['name']}.",
            payload={
                "handoff_id": handoff_id,
                "execution_id": state["execution_id"],
                "blocker": blocker,
                "next_step": note,
                "escalation_target": escalation_target or "agent_smith",
            },
            actor_agent=actor_agent,
        )
        return {
            "handoff": self.state_store.get_handoff(handoff_id) or handoff,
            "execution_state": state,
            "project": project,
            "projection_events": [event],
            "escalation": {
                "target_agent": escalation_target or "agent_smith",
                "project_id": handoff["project_id"],
                "handoff_id": handoff_id,
                "summary": f"Execution blocker for {project['name']}: {blocker}",
            },
        }

    def report_verification(
        self,
        *,
        handoff_id: str,
        actor_agent: str,
        report_summary: str,
        report_body: str | None = None,
    ) -> dict[str, Any]:
        handoff = self.state_store.get_handoff(handoff_id)
        if not handoff:
            raise ValueError(f"Handoff '{handoff_id}' was not found.")
        state = self.get_or_create_for_handoff(handoff, actor_agent=actor_agent)
        reports = [*state.get("verification_reports", []), report_summary]
        state = self.state_store.upsert_execution_state(
            {
                **state,
                "status": "VERIFICATION_REPORTED",
                "verification_reports": reports,
                "latest_note": report_summary,
                "verification_reported_at": _utc_now(),
            }
        )
        self.state_store.update_handoff(handoff_id, {"status": "VERIFICATION_REPORTED"})
        project = self.project_provisioning.update_project_surface(
            project_id=handoff["project_id"],
            updates={"status": "VERIFICATION_PENDING", "next_actions": ["Review verification report."]},
            requested_by=actor_agent,
        )
        workspace = self.project_provisioning.workspace_service
        if isinstance(workspace, WorkspaceService):
            workspace.ensure_project_structure(handoff["project_id"])
            workspace.write_project_file(
                handoff["project_id"],
                "management/TEST_REPORT.md",
                "## Verification Report\n" + (report_body or report_summary) + "\n",
            )
        event = self.projection_event_service.record_event(
            event_type="verification_reported",
            project_id=handoff["project_id"],
            summary=f"Niaobe reported verification results for {project['name']}.",
            payload={
                "handoff_id": handoff_id,
                "execution_id": state["execution_id"],
                "verification_report": report_body or report_summary,
            },
            actor_agent=actor_agent,
        )
        return {
            "handoff": self.state_store.get_handoff(handoff_id) or handoff,
            "execution_state": state,
            "project": project,
            "projection_events": [event],
        }

    def status_summary(self) -> dict[str, Any]:
        rows = self.state_store.list_execution_states()
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status", "UNKNOWN"))
            counts[status] = counts.get(status, 0) + 1
        return {"count": len(rows), "by_status": counts}
