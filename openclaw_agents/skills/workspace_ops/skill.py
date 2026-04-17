"""Shared workspace operations skill."""

from __future__ import annotations

from typing import Any

from openclaw_agents.services.workspace_service import WorkspaceService


class WorkspaceOpsSkill:
    def __init__(self, workspace_service: WorkspaceService) -> None:
        self.workspace_service = workspace_service

    def ensure_surface(self, project_id: str) -> str:
        return str(self.workspace_service.ensure_project_structure(project_id))

    def validate(self, project_id: str) -> dict[str, Any]:
        return self.workspace_service.validate_workspace(project_id)

    def write_file(self, project_id: str, rel_path: str, content: str) -> str:
        return str(self.workspace_service.write_project_file(project_id, rel_path, content))

