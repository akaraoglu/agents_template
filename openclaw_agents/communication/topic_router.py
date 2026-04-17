"""Stream/topic normalization and project context resolution helpers."""

from __future__ import annotations

import re

from .message_mapping_store import MessageMappingStore


_PROJECT_TOPIC_RE = re.compile(r"project/([a-zA-Z0-9_.-]+)")


class TopicRouter:
    def __init__(self, mapping_store: MessageMappingStore) -> None:
        self.mapping_store = mapping_store

    @staticmethod
    def canonical_project_topic(project_id: str) -> str:
        return f"project/{project_id}"

    @staticmethod
    def normalize_topic(topic_name: str) -> str:
        return topic_name.strip()

    def resolve_project_id(self, topic_name: str | None) -> str | None:
        if not topic_name:
            return None
        match = _PROJECT_TOPIC_RE.search(topic_name.lower())
        if match:
            return match.group(1)
        return None

    def resolve_topic_for_project(self, project_id: str) -> tuple[str, str]:
        mapped = self.mapping_store.get_primary_topic(project_id)
        if mapped:
            return mapped["stream_name"], mapped["topic_name"]
        return "projects", self.canonical_project_topic(project_id)

