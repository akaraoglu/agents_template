"""Helpers that project approved updates into canonical project threads."""

from __future__ import annotations

from typing import Any

from .message_mapping_store import MessageMappingStore
from .topic_router import TopicRouter
from .zulip_plugin import ZulipRuntimePlugin


def _yaml_block(payload: dict[str, Any]) -> str:
    rows = []
    for key, value in payload.items():
        if isinstance(value, list):
            rows.append(f"{key}:")
            for item in value:
                rows.append(f"  - {item}")
        else:
            rows.append(f"{key}: {value}")
    return "\n".join(rows)


def _render_projection_markdown(summary: str, event_type: str, project_id: str, payload: dict[str, Any]) -> str:
    title_map = {
        "project_kickoff": "Project Kickoff",
        "project_change_proposed": "Project Change Proposed",
        "project_change_confirmed": "Project Change Confirmed",
        "spec_updated": "Spec Updated",
        "plan_updated": "Plan Updated",
        "tasks_updated": "Tasks Updated",
        "execution_handoff_created": "Execution Handoff Created",
        "execution_started": "Execution Started",
        "execution_blocked": "Execution Blocked",
        "verification_reported": "Verification Reported",
        "project_closed": "Project Closed",
    }
    title = title_map.get(event_type, "Projection Event")
    details: list[str] = []
    if payload.get("updated_fields"):
        details.append("Updated fields: " + ", ".join(str(item) for item in payload["updated_fields"]))
    if payload.get("handoff_id"):
        details.append(f"Handoff: {payload['handoff_id']}")
    if payload.get("blocker"):
        details.append(f"Blocker: {payload['blocker']}")
    if payload.get("escalation_target"):
        details.append(f"Escalation target: {payload['escalation_target']}")
    if payload.get("verification_report"):
        report = str(payload["verification_report"]).strip()
        if len(report) > 220:
            report = report[:217] + "..."
        details.append(f"Verification: {report}")
    if payload.get("preview"):
        preview = str(payload["preview"]).strip()
        if len(preview) > 220:
            preview = preview[:217] + "..."
        details.append(f"Preview: {preview}")

    body = f"## {title}\n\n{summary}"
    if details:
        body += "\n\n" + "\n".join(f"- {line}" for line in details)
    body += (
        f"\n\n```yaml\n{_yaml_block({'event_type': event_type, 'project_id': project_id, **payload})}\n```"
    )
    return body


def _bullet_lines(values: list[Any]) -> str:
    return "\n".join(f"- {value}" for value in values if str(value).strip())


class ProjectionHelpers:
    def __init__(
        self,
        plugin: ZulipRuntimePlugin,
        message_mapping_store: MessageMappingStore,
        topic_router: TopicRouter,
    ) -> None:
        self.plugin = plugin
        self.message_mapping_store = message_mapping_store
        self.topic_router = topic_router

    def post_project_update(
        self,
        project_id: str,
        summary: str,
        payload: dict[str, Any],
        message_kind: str = "projection_event",
        sender_agent: str = "agent_smith",
    ) -> dict[str, Any]:
        stream_name, topic_name = self.topic_router.resolve_topic_for_project(project_id)
        event_type = str(payload.get("event_type") or message_kind)
        markdown = _render_projection_markdown(summary, event_type, project_id, {"kind": message_kind, **payload})
        result = self.plugin.reply_in_topic(
            stream_name=stream_name,
            topic_name=topic_name,
            content_markdown=markdown,
            project_id=project_id,
            task_id=payload.get("task_id"),
            message_kind=message_kind,
            sender_agent=sender_agent,
        )
        self.message_mapping_store.link_message(
            result.message_id, project_id, payload.get("task_id"), topic_name, message_kind
        )
        self.message_mapping_store.set_primary_topic(project_id, stream_name=stream_name, topic_name=topic_name)
        return {"message_id": result.message_id, "stream_name": stream_name, "topic_name": topic_name}

    def _render_projection_markdown(self, projection_event: dict[str, Any], message_kind: str) -> str:
        event_type = str(projection_event.get("event_type", "projection_event"))
        summary = str(projection_event.get("summary", "")).strip()
        payload = dict(projection_event.get("payload", {}))
        metadata = {
            "kind": message_kind,
            "project_id": projection_event.get("project_id"),
            "event_id": projection_event.get("event_id"),
            "event_type": event_type,
            "actor_agent": projection_event.get("actor_agent"),
            "project_version": projection_event.get("project_version", 1),
        }

        title_map = {
            "project_kickoff": "Project kickoff",
            "project_change_proposed": "Project change proposed",
            "project_change_confirmed": "Project change confirmed",
            "spec_updated": "Spec updated",
            "plan_updated": "Plan updated",
            "tasks_updated": "Tasks updated",
            "execution_handoff_created": "Execution handoff created",
            "execution_started": "Execution started",
            "execution_blocked": "Execution blocked",
            "verification_reported": "Verification reported",
            "project_closed": "Project closed",
        }
        title = title_map.get(event_type, "Project event").title()
        sections = [f"## {title}", f"**{title_map.get(event_type, 'Project event')}**", summary]

        if event_type == "project_change_proposed" and payload.get("updated_fields"):
            sections.append("Pending fields:\n" + _bullet_lines(list(payload.get("updated_fields", []))))
        elif event_type in {"spec_updated", "plan_updated", "tasks_updated"} and payload.get("updated_fields"):
            sections.append("Updated fields:\n" + _bullet_lines(list(payload.get("updated_fields", []))))
        elif event_type == "execution_handoff_created":
            sections.append(
                "Handoff:\n"
                + _bullet_lines(
                    [
                        f"handoff_id: {payload.get('handoff_id', 'unknown')}",
                        f"to_agent: {payload.get('to_agent', 'niaobe')}",
                        f"status: {payload.get('status', 'PENDING')}",
                    ]
                )
            )
        elif event_type == "execution_started":
            sections.append(
                "Execution:\n"
                + _bullet_lines(
                    [
                        f"handoff_id: {payload.get('handoff_id', 'unknown')}",
                        f"execution_id: {payload.get('execution_id', 'unknown')}",
                        f"status: {payload.get('status', 'IN_PROGRESS')}",
                    ]
                )
            )
        elif event_type == "execution_blocked":
            sections.append(
                "Blocker:\n"
                + _bullet_lines(
                    [
                        str(payload.get("blocker") or "Unspecified blocker."),
                        f"Next step: {payload.get('next_step', 'Awaiting follow-up.')}",
                    ]
                )
            )
        elif event_type == "verification_reported":
            sections.append(
                "Verification:\n"
                + _bullet_lines(
                    [
                        str(payload.get("report_summary") or "Verification reported."),
                    ]
                )
            )

        sections.append(f"```yaml\n{_yaml_block({**metadata, **payload})}\n```")
        return "\n\n".join(section for section in sections if section.strip())

    def post_projection_event(
        self,
        projection_event: dict[str, Any],
        *,
        sender_agent: str = "agent_smith",
    ) -> dict[str, Any]:
        project_id = str(projection_event["project_id"])
        event_type = str(projection_event.get("event_type", "projection_event"))
        payload = dict(projection_event.get("payload", {}))
        payload.update(
            {
                "event_id": projection_event.get("event_id"),
                "event_type": event_type,
                "actor_agent": projection_event.get("actor_agent"),
                "project_version": projection_event.get("project_version", 1),
            }
        )
        message_kind = "execution_handoff" if event_type == "execution_handoff_created" else "projection_event"
        stream_name, topic_name = self.topic_router.resolve_topic_for_project(project_id)
        result = self.plugin.reply_in_topic(
            stream_name=stream_name,
            topic_name=topic_name,
            content_markdown=self._render_projection_markdown(projection_event, message_kind),
            project_id=project_id,
            task_id=payload.get("task_id"),
            message_kind=message_kind,
            sender_agent=sender_agent,
        )
        self.message_mapping_store.link_message(
            result.message_id, project_id, payload.get("task_id"), topic_name, message_kind
        )
        self.message_mapping_store.set_primary_topic(project_id, stream_name=stream_name, topic_name=topic_name)
        return {"message_id": result.message_id, "stream_name": stream_name, "topic_name": topic_name}

    def post_execution_handoff(
        self,
        project_id: str,
        handoff_packet: dict[str, Any],
        sender_agent: str = "agent_smith",
    ) -> dict[str, Any]:
        return self.post_project_update(
            project_id=project_id,
            summary=(
                f"Execution handoff prepared for Niaobe: "
                f"{handoff_packet.get('project_name', project_id)}."
            ),
            payload={
                "task_id": handoff_packet.get("handoff_id"),
                "handoff_id": handoff_packet.get("handoff_id"),
                "from_agent": handoff_packet.get("from_agent"),
                "to_agent": handoff_packet.get("to_agent"),
                "status": handoff_packet.get("status"),
            },
            message_kind="execution_handoff",
            sender_agent=sender_agent,
        )
