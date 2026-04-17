"""SDD artifact helper skill."""

from __future__ import annotations

from openclaw_agents.services.workspace_service import WorkspaceService


class SDDArtifactOpsSkill:
    def __init__(self, workspace_service: WorkspaceService) -> None:
        self.workspace_service = workspace_service

    def ensure_spec_and_plan(self, project_id: str, spec_text: str, plan_text: str) -> dict[str, str]:
        spec_path = self.workspace_service.write_project_file(project_id, "specs/SPEC.md", spec_text)
        plan_path = self.workspace_service.write_project_file(project_id, "plans/PLAN.md", plan_text)
        return {"spec_path": str(spec_path), "plan_path": str(plan_path)}

