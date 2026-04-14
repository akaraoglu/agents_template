"""Zulip message-link persistence helpers."""

from __future__ import annotations

from openclaw_agents.database.store import ControlPlaneStore


class MessageMappingStore:
    """Persist and query Zulip message mappings in the control-plane store."""

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def link_message(
        self,
        *,
        project_id: str,
        zulip_message_id: str,
        stream_name: str,
        topic_name: str,
        direction: str,
        message_kind: str,
        linked_entity_type: str,
        linked_entity_id: str,
        task_id: str | None = None,
        control_event_id: str | None = None,
    ) -> dict:
        return self.store.link_zulip_message(
            project_id=project_id,
            zulip_message_id=zulip_message_id,
            stream_name=stream_name,
            topic_name=topic_name,
            direction=direction,
            message_kind=message_kind,
            linked_entity_type=linked_entity_type,
            linked_entity_id=linked_entity_id,
            task_id=task_id,
            control_event_id=control_event_id,
        )

    def get_by_message_id(self, zulip_message_id: str) -> dict | None:
        return self.store.get_zulip_message_link(zulip_message_id)

    def get_for_task(self, task_id: str) -> list[dict]:
        return self.store.list_zulip_links_for_task(task_id)
