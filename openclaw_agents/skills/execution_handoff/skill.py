"""Execution handoff skill wrapper."""

from __future__ import annotations

from openclaw_agents.services.artifact_refs import ArtifactRefService


class ExecutionHandoffSkill:
    def __init__(self, artifact_ref_service: ArtifactRefService) -> None:
        self.artifact_ref_service = artifact_ref_service

    def create_and_persist(self, project: dict, approved_summary: str) -> dict:
        packet = self.artifact_ref_service.build_execution_handoff(project, approved_summary=approved_summary)
        return self.artifact_ref_service.persist_execution_handoff(packet)

