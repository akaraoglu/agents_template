"""Durable internal software-loop orchestration for Morpheus and worker agents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .audit_log import AuditLogService
from .execution_state import ExecutionStateService
from .projection_events import ProjectionEventService
from .state_store import StateStore
from .workspace_service import WorkspaceService


_STAGES = ("morpheus", "planner", "implementer", "tester")
_ACTIVE_RUN_STATUSES = {"ACTIVE"}


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class InternalLoopService:
    def __init__(
        self,
        state_store: StateStore,
        workspace_service: WorkspaceService,
        execution_state: ExecutionStateService,
        projection_event_service: ProjectionEventService,
        audit_log: AuditLogService | None = None,
    ) -> None:
        self.state_store = state_store
        self.workspace_service = workspace_service
        self.execution_state = execution_state
        self.projection_event_service = projection_event_service
        self.audit_log = audit_log

    def ensure_run_for_handoff(
        self,
        handoff: dict[str, Any],
        *,
        execution_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_run_for_handoff(handoff["handoff_id"])
        if existing is not None:
            return existing
        state = execution_state or self.execution_state.get_execution_state_for_handoff(handoff["handoff_id"]) or {}
        record = {
            "run_id": str(uuid.uuid4()),
            "handoff_id": handoff["handoff_id"],
            "execution_id": state.get("execution_id"),
            "project_id": handoff["project_id"],
            "project_name": handoff.get("project_name", handoff["project_id"]),
            "workspace_path": handoff.get("workspace_path"),
            "owner_agent": "morpheus",
            "status": "ACTIVE",
            "current_stage": "morpheus",
            "stage_results": {},
            "stage_statuses": {
                "morpheus": "READY",
                "planner": "PENDING",
                "implementer": "PENDING",
                "tester": "PENDING",
            },
            "created_at": _utc_now(),
        }
        return self.state_store.upsert_internal_run(record)

    def get_run_for_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        rows = self.state_store.list_internal_runs(handoff_id=handoff_id)
        return rows[-1] if rows else None

    def list_runs(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.state_store.list_internal_runs(status=status, project_id=project_id)

    def next_work_items(
        self,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        rows = self.state_store.list_internal_runs()
        actionable = [
            row
            for row in rows
            if row.get("status") in _ACTIVE_RUN_STATUSES and row.get("current_stage") in _STAGES
        ]
        return actionable[: max(1, limit)]

    def build_stage_event(
        self,
        run: dict[str, Any],
        *,
        handoff: dict[str, Any],
        project: dict[str, Any] | None,
        execution_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stage = str(run.get("current_stage") or "morpheus")
        stage_results = dict(run.get("stage_results", {}))
        brief = self._stage_instruction(stage, project_name=run.get("project_name", run["project_id"]))
        return {
            "event_id": f"system::internal::{run['run_id']}::{stage}",
            "source_type": "internal_runtime_stage",
            "conversation_surface": "control",
            "recipient_agent": stage,
            "sender_email": "system@openclaw.local",
            "raw_content": brief,
            "project_id": run["project_id"],
            "control_key": f"internal::{run['run_id']}::{stage}",
            "execution_context": {
                "trigger": "internal_software_loop",
                "handoff": handoff,
                "handoff_id": handoff["handoff_id"],
                "execution_state": execution_state,
                "internal_run": run,
                "stage_results": stage_results,
                "project_name": run.get("project_name", run["project_id"]),
            },
        }

    @staticmethod
    def _stage_instruction(stage: str, *, project_name: str) -> str:
        if stage == "morpheus":
            return (
                f"Own the internal software loop for {project_name}. Summarize the execution objective, "
                "the riskiest delivery constraint, and the immediate planning focus for Planner."
            )
        if stage == "planner":
            return (
                f"Produce a concise execution plan for {project_name}. Focus on ordered implementation steps, "
                "verification gates, and the next execution checkpoint."
            )
        if stage == "implementer":
            return (
                f"Produce the implementation execution summary for {project_name}. Describe the concrete work "
                "package, any required workspace changes, and whether execution is blocked."
            )
        return (
            f"Assess implementation readiness for {project_name}. Either return a verification summary or "
            "raise an execution blocker if testing cannot proceed."
        )

    def apply_stage_response(
        self,
        run: dict[str, Any],
        response: Any,
        *,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        stage = str(run.get("current_stage") or "morpheus")
        summary = self._response_summary(response)
        updated = {
            **run,
            "stage_results": {**dict(run.get("stage_results", {})), stage: self._stage_record(stage, response, summary)},
        }
        stage_statuses = {**dict(run.get("stage_statuses", {})), stage: "COMPLETED"}
        updated["stage_statuses"] = stage_statuses

        stage_effects: dict[str, Any] = {"projection_events": [], "sender_agent": "niaobe"}
        blocker_intent = self._matching_intent(response.action_intents, "execution_blocker")
        verification_intent = self._matching_intent(response.action_intents, "verification_report")

        if blocker_intent is not None:
            blocker_text = str(blocker_intent.payload.get("blocker") or blocker_intent.summary or summary).strip()
            next_step = str(blocker_intent.payload.get("next_step") or "").strip() or None
            blocked = self.execution_state.report_blocker(
                handoff_id=handoff["handoff_id"],
                actor_agent="niaobe",
                blocker=blocker_text,
                next_step=next_step,
                escalation_target="agent_smith",
            )
            updated["status"] = "BLOCKED"
            updated["blocked_stage"] = stage
            updated["blocker"] = blocker_text
            stage_effects["projection_events"] = list(blocked.get("projection_events", []))
            stage_effects["escalation"] = blocked.get("escalation")
        elif stage == "morpheus":
            self._write_internal_artifact(run["project_id"], "artifacts/reports/MORPHEUS_LOOP.md", "## Morpheus\n" + summary + "\n")
            updated["current_stage"] = "planner"
            updated["stage_statuses"]["planner"] = "READY"
        elif stage == "planner":
            self._write_internal_artifact(run["project_id"], "management/PLAN.md", "## Internal Plan\n" + summary + "\n")
            event = self.projection_event_service.record_event(
                event_type="plan_updated",
                project_id=run["project_id"],
                summary=f"Planner updated the execution plan for {run.get('project_name', run['project_id'])}.",
                payload={"updated_fields": ["internal_plan"], "run_id": run["run_id"], "stage": stage},
                actor_agent="planner",
            )
            stage_effects["projection_events"] = [event]
            stage_effects["sender_agent"] = "agent_smith"
            updated["current_stage"] = "implementer"
            updated["stage_statuses"]["implementer"] = "READY"
        elif stage == "implementer":
            self._write_internal_artifact(
                run["project_id"],
                "artifacts/reports/IMPLEMENTATION_NOTES.md",
                "## Implementer\n" + summary + "\n",
            )
            event = self.projection_event_service.record_event(
                event_type="tasks_updated",
                project_id=run["project_id"],
                summary=f"Implementer updated the execution task package for {run.get('project_name', run['project_id'])}.",
                payload={"updated_fields": ["implementation_notes"], "run_id": run["run_id"], "stage": stage},
                actor_agent="implementer",
            )
            stage_effects["projection_events"] = [event]
            updated["current_stage"] = "tester"
            updated["stage_statuses"]["tester"] = "READY"
        else:
            verification_summary = str(
                (verification_intent.payload.get("report_summary") if verification_intent is not None else "")
                or summary
            ).strip()
            verification_body = str(
                (verification_intent.payload.get("report_body") if verification_intent is not None else "")
                or summary
            ).strip()
            verified = self.execution_state.report_verification(
                handoff_id=handoff["handoff_id"],
                actor_agent="niaobe",
                report_summary=verification_summary,
                report_body=verification_body,
            )
            updated["status"] = "COMPLETED"
            updated["current_stage"] = "done"
            stage_effects["projection_events"] = list(verified.get("projection_events", []))

        stored = self.state_store.upsert_internal_run(updated)
        self._record_audit(stage, stored, summary)
        return stage_effects

    @staticmethod
    def _response_summary(response: AgentTurnResponse) -> str:
        if response.internal_output and response.internal_output.get("reply"):
            return str(response.internal_output["reply"]).strip()
        if response.outbound_messages:
            return str(response.outbound_messages[0].content_markdown).strip()
        return "No internal summary was produced."

    @staticmethod
    def _matching_intent(intents: list[Any], kind: str) -> Any | None:
        for intent in intents:
            if intent.kind == kind:
                return intent
        return None

    @staticmethod
    def _stage_record(stage: str, response: AgentTurnResponse, summary: str) -> dict[str, Any]:
        return {
            "agent_id": stage,
            "summary": summary,
            "action_intents": [
                {"kind": intent.kind, "summary": intent.summary, "payload": intent.payload}
                for intent in response.action_intents
            ],
            "tool_results": [
                {"tool_name": result.tool_name, "ok": result.ok, "error": result.error}
                for result in response.tool_results
            ],
            "completed_at": _utc_now(),
        }

    def _write_internal_artifact(self, project_id: str, path: str, content: str) -> None:
        self.workspace_service.ensure_project_structure(project_id)
        self.workspace_service.write_project_file(project_id, path, content)

    def _record_audit(self, stage: str, run: dict[str, Any], summary: str) -> None:
        if self.audit_log is None:
            return
        self.audit_log.record(
            action_type="internal_loop_stage",
            actor_agent=stage,
            outcome="ok",
            project_id=run["project_id"],
            handoff_id=run.get("handoff_id"),
            payload={
                "run_id": run["run_id"],
                "stage": stage,
                "summary": summary[:240],
                "status": run.get("status"),
                "current_stage": run.get("current_stage"),
            },
        )

    def status_summary(self) -> dict[str, Any]:
        rows = self.state_store.list_internal_runs()
        counts: dict[str, int] = {}
        stages: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status", "UNKNOWN"))
            stage = str(row.get("current_stage", "unknown"))
            counts[status] = counts.get(status, 0) + 1
            stages[stage] = stages.get(stage, 0) + 1
        return {"count": len(rows), "by_status": counts, "by_stage": stages}
