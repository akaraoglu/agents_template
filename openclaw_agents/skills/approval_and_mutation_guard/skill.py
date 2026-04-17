"""Approval and mutation boundary skill."""

from __future__ import annotations

from typing import Any

from openclaw_agents.communication.approval_helpers import ApprovalHelpers


class ApprovalAndMutationGuardSkill:
    def __init__(self, approval_helpers: ApprovalHelpers) -> None:
        self.approval_helpers = approval_helpers

    def classify(self, text: str) -> str:
        return self.approval_helpers.classify_action(text)

    def request(self, owner_agent: str, requester_email: str, change: dict[str, Any]) -> dict[str, Any]:
        return self.approval_helpers.request_confirmation(owner_agent, requester_email, change)

