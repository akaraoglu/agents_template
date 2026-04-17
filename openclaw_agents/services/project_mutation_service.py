"""Project mutation and execution-handoff services outside the gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .artifact_refs import ArtifactRefService
from .audit_log import AuditLogService
from .project_provisioning import ProjectProvisioningService
from .projection_events import ProjectionEventService


@dataclass(slots=True)
class MutationExecutionResult:
    project: dict[str, Any]
    handoff: dict[str, Any]
    summary: str
    projection_events: list[dict[str, Any]]


class ProjectMutationService:
    def __init__(
        self,
        project_provisioning: ProjectProvisioningService,
        artifact_ref_service: ArtifactRefService,
        projection_event_service: ProjectionEventService,
        audit_log: AuditLogService | None = None,
    ) -> None:
        self.project_provisioning = project_provisioning
        self.artifact_ref_service = artifact_ref_service
        self.projection_event_service = projection_event_service
        self.audit_log = audit_log

    @staticmethod
    def extract_project_name(raw_text: str) -> str | None:
        quoted = re.search(r'["“](.+?)["”]', raw_text)
        if quoted:
            return quoted.group(1).strip()
        match = re.search(
            r"create project\s+([a-zA-Z0-9 _-]+?)(?:\s+(?:to|for|with|that)\b|$)",
            raw_text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" .:-")
        return None

    @staticmethod
    def _normalize_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return []
        text = str(value).strip()
        if not text:
            return []
        if "\n" in text:
            return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        return [chunk.strip() for chunk in text.split(",") if chunk.strip()]

    def _build_from_structured_change(
        self,
        structured_change: dict[str, Any],
        *,
        raw_text: str,
        context_project_id: str | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        action = str(structured_change.get("action") or "").strip().lower() or "update_project"
        if action == "close_project":
            action = "update_project"
            structured_change = {**structured_change, "action": action, "status": "CLOSED"}

        request_text = str(
            structured_change.get("request_text")
            or structured_change.get("change_text")
            or raw_text
        ).strip()

        if action == "create_project":
            name = str(structured_change.get("name") or "").strip() or self.extract_project_name(raw_text)
            if not name:
                return None, "I need the project name before I can propose creating it."
            summary = str(structured_change.get("summary") or request_text or "No summary provided.").strip()
            return {
                "action": "create_project",
                "name": name,
                "summary": summary,
                "request_text": request_text,
            }, None

        project_id = str(structured_change.get("project_id") or context_project_id or "").strip()
        if not project_id:
            return None, "I need the project context before updating. Which project should I update?"

        change: dict[str, Any] = {
            "action": "update_project",
            "project_id": project_id,
            "request_text": request_text,
        }
        for key in ("name", "summary", "status"):
            value = structured_change.get(key)
            if value is not None and str(value).strip():
                change[key] = str(value).strip()
        for key in ("milestones", "next_actions", "backlog_items", "blockers", "decisions"):
            values = self._normalize_lines(structured_change.get(key))
            if values:
                change[key] = values

        update_fields = {
            key
            for key in ("name", "summary", "status", "milestones", "next_actions", "backlog_items", "blockers", "decisions")
            if key in change
        }
        if not update_fields:
            change["summary"] = request_text
        return change, None

    def _build_from_text(
        self,
        raw_text: str,
        *,
        context_project_id: str | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        lower = raw_text.lower()
        if "create project" in lower or "new project" in lower:
            project_name = self.extract_project_name(raw_text) or "New Project"
            return (
                {
                    "action": "create_project",
                    "name": project_name,
                    "summary": raw_text.strip(),
                    "request_text": raw_text.strip(),
                },
                None,
            )
        if not any(
            token in lower
            for token in (
                "update project",
                "change milestone",
                "change backlog",
                "update backlog",
                "update tasks",
                "update summary",
                "update spec",
                "update plan",
                "close project",
                "block project",
            )
        ):
            return None, "I can propose project create/update mutations. Please state the intended project action."
        if not context_project_id:
            return None, "I need the project context before updating. Which project should I update?"

        change: dict[str, Any] = {
            "action": "update_project",
            "project_id": context_project_id,
            "request_text": raw_text.strip(),
        }
        if "close project" in lower:
            change["status"] = "CLOSED"
        elif "block project" in lower:
            change["status"] = "BLOCKED"
        if "change milestone" in lower or "update milestone" in lower or "milestones" in lower:
            quoted = re.search(r'["“](.+?)["”]', raw_text)
            if quoted:
                change["milestones"] = [quoted.group(1).strip()]
        if "change backlog" in lower or "update backlog" in lower or "update tasks" in lower:
            quoted = re.search(r'["“](.+?)["”]', raw_text)
            if quoted:
                change["backlog_items"] = [quoted.group(1).strip()]
        if "update summary" in lower or "update spec" in lower:
            quoted = re.search(r'["“](.+?)["”]', raw_text)
            if quoted:
                change["summary"] = quoted.group(1).strip()
        if "blocker" in lower:
            blocker_match = re.search(r"blocker(?:s)?[:\s]+(.+)$", raw_text, flags=re.IGNORECASE)
            if blocker_match:
                change["blockers"] = self._normalize_lines(blocker_match.group(1))
        update_fields = {
            key
            for key in ("summary", "status", "milestones", "backlog_items", "blockers")
            if key in change
        }
        if not update_fields:
            change["summary"] = raw_text.strip()
        return change, None

    def build_change_request(
        self,
        raw_text: str,
        *,
        context_project_id: str | None,
        structured_change: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if structured_change:
            return self._build_from_structured_change(
                structured_change,
                raw_text=raw_text,
                context_project_id=context_project_id,
            )
        return self._build_from_text(raw_text, context_project_id=context_project_id)

    @staticmethod
    def _changed_fields(change: dict[str, Any]) -> list[str]:
        return [
            field
            for field in (
                "name",
                "summary",
                "status",
                "milestones",
                "next_actions",
                "backlog_items",
                "blockers",
                "decisions",
            )
            if field in change
        ]

    def _record_update_events(
        self,
        *,
        project: dict[str, Any],
        approval_record: dict[str, Any],
        change: dict[str, Any],
        changed_fields: list[str],
    ) -> list[dict[str, Any]]:
        payload = {
            "approval_id": approval_record["approval_id"],
            "mutation_action": change["action"],
            "approved_by": approval_record.get("confirmed_by", "unknown"),
            "updated_fields": changed_fields,
        }
        events: list[dict[str, Any]] = []
        project_id = project["id"]
        project_name = project["name"]

        if any(field in changed_fields for field in ("name", "summary")):
            events.append(
                self.projection_event_service.record_event(
                    event_type="spec_updated",
                    project_id=project_id,
                    summary=f"Confirmed project summary/spec update for {project_name}.",
                    payload=payload,
                    actor_agent="agent_smith",
                )
            )
        if any(field in changed_fields for field in ("milestones", "next_actions", "decisions")):
            events.append(
                self.projection_event_service.record_event(
                    event_type="plan_updated",
                    project_id=project_id,
                    summary=f"Confirmed plan update for {project_name}.",
                    payload=payload,
                    actor_agent="agent_smith",
                )
            )
        if "backlog_items" in changed_fields:
            events.append(
                self.projection_event_service.record_event(
                    event_type="tasks_updated",
                    project_id=project_id,
                    summary=f"Confirmed backlog/task update for {project_name}.",
                    payload=payload,
                    actor_agent="agent_smith",
                )
            )
        if change.get("status") == "CLOSED":
            events.append(
                self.projection_event_service.record_event(
                    event_type="project_closed",
                    project_id=project_id,
                    summary=f"Confirmed project closeout for {project_name}.",
                    payload=payload,
                    actor_agent="agent_smith",
                )
            )
        elif any(field in changed_fields for field in ("status", "blockers")) or not events:
            events.append(
                self.projection_event_service.record_event(
                    event_type="project_change_confirmed",
                    project_id=project_id,
                    summary=f"Confirmed project change for {project_name}.",
                    payload=payload,
                    actor_agent="agent_smith",
                )
            )
        return events

    def apply_confirmed_change(self, approval_record: dict[str, Any]) -> MutationExecutionResult:
        change = approval_record["change"]
        requester = approval_record.get("requester_email", "unknown@local")

        if change["action"] == "create_project":
            project = self.project_provisioning.create_project_surface(
                name=change.get("name", "New Project"),
                summary=change.get("summary", ""),
                requested_by=requester,
            )
            summary = f"Approved project creation for {project['name']}."
            primary_event = self.projection_event_service.record_event(
                event_type="project_kickoff",
                project_id=project["id"],
                summary=summary,
                payload={
                    "approval_id": approval_record["approval_id"],
                    "mutation_action": change["action"],
                    "approved_by": approval_record.get("confirmed_by", "unknown"),
                },
                actor_agent="agent_smith",
            )
            projection_events = [primary_event]
        elif change["action"] == "update_project":
            changed_fields = self._changed_fields(change)
            updates = {field: change[field] for field in changed_fields}
            project = self.project_provisioning.update_project_surface(
                project_id=change["project_id"],
                updates=updates,
                requested_by=requester,
            )
            if changed_fields:
                summary = (
                    f"Approved project update for {project['name']}: "
                    + ", ".join(changed_fields)
                    + "."
                )
            else:
                summary = f"Approved project update for {project['name']}."
            projection_events = self._record_update_events(
                project=project,
                approval_record=approval_record,
                change=change,
                changed_fields=changed_fields,
            )
        else:
            raise ValueError(f"Unsupported mutation action: {change['action']}")

        handoff_packet = self.artifact_ref_service.build_execution_handoff(
            project=project,
            approved_summary=summary,
        )
        stored_handoff = self.artifact_ref_service.persist_execution_handoff(handoff_packet)
        handoff_event = self.projection_event_service.record_event(
            event_type="execution_handoff_created",
            project_id=project["id"],
            summary=f"Execution handoff prepared for Niaobe: {project['name']}.",
            payload={
                "handoff_id": stored_handoff["handoff_id"],
                "from_agent": stored_handoff.get("from_agent"),
                "to_agent": stored_handoff.get("to_agent"),
                "status": stored_handoff.get("status"),
            },
            actor_agent="agent_smith",
        )
        if self.audit_log:
            self.audit_log.record(
                action_type="confirmed_project_mutation",
                actor_agent="agent_smith",
                outcome="executed",
                project_id=project["id"],
                handoff_id=stored_handoff["handoff_id"],
                payload={"summary": summary, "change": change},
            )
        return MutationExecutionResult(
            project=project,
            handoff=stored_handoff,
            summary=summary,
            projection_events=[*projection_events, handoff_event],
        )
