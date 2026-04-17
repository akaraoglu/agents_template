"""Resolve likely project context for DM conversations."""

from __future__ import annotations

import re
from typing import Any

from openclaw_agents.services.project_registry import ProjectRegistryService


class DMContextResolver:
    def __init__(self, project_registry: ProjectRegistryService) -> None:
        self.project_registry = project_registry
        self._session_project: dict[str, str] = {}

    @staticmethod
    def _session_key(event: dict[str, Any]) -> str:
        sender = event.get("sender_email", "")
        recipient = event.get("recipient_agent", "")
        return f"{sender}::{recipient}"

    def resolve(self, event: dict[str, Any]) -> dict[str, Any]:
        text = str(event.get("raw_content", ""))
        topic_name = str(event.get("topic_name", ""))
        session_key = self._session_key(event)

        explicit_match = re.search(r"(?:project[/\s:#-]+)([a-zA-Z0-9_.-]+)", text.lower())
        if explicit_match:
            resolution = self.project_registry.find_project(explicit_match.group(1))
            if resolution.project_id:
                self._session_project[session_key] = resolution.project_id
                return {
                    "project_id": resolution.project_id,
                    "ambiguous": False,
                    "follow_up_question": None,
                    "candidates": resolution.candidates,
                }
            if resolution.ambiguous:
                return {
                    "project_id": None,
                    "ambiguous": True,
                    "follow_up_question": resolution.follow_up_question,
                    "candidates": resolution.candidates,
                }

        inferred = self.project_registry.resolve_project_from_context({"text": text, "topic_name": topic_name})
        if inferred.project_id:
            self._session_project[session_key] = inferred.project_id
            return {
                "project_id": inferred.project_id,
                "ambiguous": False,
                "follow_up_question": None,
                "candidates": inferred.candidates,
            }
        if inferred.ambiguous:
            return {
                "project_id": None,
                "ambiguous": True,
                "follow_up_question": inferred.follow_up_question,
                "candidates": inferred.candidates,
            }

        existing = self._session_project.get(session_key)
        if existing:
            return {"project_id": existing, "ambiguous": False, "follow_up_question": None, "candidates": []}
        return {"project_id": None, "ambiguous": False, "follow_up_question": None, "candidates": []}

