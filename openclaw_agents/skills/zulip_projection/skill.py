"""Projection skill wrapper around canonical projection helpers."""

from __future__ import annotations

from typing import Any

from openclaw_agents.communication.projection_helpers import ProjectionHelpers


class ZulipProjectionSkill:
    def __init__(self, projection_helpers: ProjectionHelpers) -> None:
        self.projection_helpers = projection_helpers

    def project_update(self, project_id: str, summary: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.projection_helpers.post_project_update(project_id, summary=summary, payload=payload)

