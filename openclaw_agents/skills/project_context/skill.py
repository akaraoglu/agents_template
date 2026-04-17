"""Shared project context skill."""

from __future__ import annotations

from typing import Any

from openclaw_agents.services.project_registry import ProjectRegistryService


class ProjectContextSkill:
    def __init__(self, project_registry: ProjectRegistryService) -> None:
        self.project_registry = project_registry

    def list_open_projects(self) -> list[dict[str, Any]]:
        return self.project_registry.list_projects()

    def resolve(self, text: str, topic_name: str | None = None) -> dict[str, Any]:
        resolution = self.project_registry.resolve_project_from_context(
            {"text": text, "topic_name": topic_name or ""}
        )
        return {
            "project_id": resolution.project_id,
            "ambiguous": resolution.ambiguous,
            "candidates": resolution.candidates,
            "follow_up_question": resolution.follow_up_question,
        }

