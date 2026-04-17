"""Mutation preview and confirmation gate helpers."""

from __future__ import annotations

import re
from typing import Any

from openclaw_agents.services.state_store import StateStore


class ApprovalHelpers:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store

    @staticmethod
    def classify_action(raw_text: str) -> str:
        text = raw_text.lower()
        if any(token in text for token in ("handoff", "resume execution", "start execution")):
            return "execution_handoff"
        if any(
            token in text
            for token in (
                "create project",
                "new project",
                "update project",
                "change milestone",
                "change backlog",
                "update backlog",
                "update tasks",
                "update summary",
                "update spec",
                "update plan",
                "update status",
                "close project",
                "block project",
                "blocker",
                "create workspace",
                "create surface",
            )
        ):
            return "proposed_project_action"
        return "free_conversation"

    @staticmethod
    def confirmation_required(action_class: str) -> bool:
        return action_class in {"proposed_project_action", "execution_handoff"}

    @staticmethod
    def preview_mutation(change: dict[str, Any]) -> str:
        action = change.get("action", "unknown_action")
        project_name = change.get("name") or change.get("project_id") or "unknown project"
        summary = str(change.get("request_text") or change.get("summary") or "").strip()
        snippet = summary[:180] + ("..." if len(summary) > 180 else "")
        changed_fields = [
            field
            for field in (
                "summary",
                "status",
                "milestones",
                "next_actions",
                "backlog_items",
                "blockers",
                "decisions",
            )
            if field in change
        ]
        field_text = f" Fields: {', '.join(changed_fields)}." if changed_fields else ""
        return (
            f"Proposed mutation: {action} for {project_name}.{field_text} "
            f"Summary: {snippet or 'n/a'}"
        )

    def request_confirmation(
        self,
        owner_agent: str,
        requester_email: str,
        change: dict[str, Any],
    ) -> dict[str, Any]:
        preview = self.preview_mutation(change)
        return self.state_store.create_approval(
            {
                "owner_agent": owner_agent,
                "requester_email": requester_email,
                "change": change,
                "preview": preview,
                "status": "PENDING",
            }
        )

    def list_pending(self, requester_email: str, owner_agent: str) -> list[dict[str, Any]]:
        return self.state_store.list_pending_approvals(
            requester_email=requester_email, owner_agent=owner_agent
        )

    @staticmethod
    def parse_confirmation_text(raw_text: str) -> tuple[str | None, str | None]:
        text = raw_text.strip().lower()
        approval_id_match = re.search(
            r"\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b", text
        )
        approval_id = approval_id_match.group(1) if approval_id_match else None
        words = set(re.findall(r"[a-z]+", text))
        if words.intersection({"confirm", "approve", "approved", "yes", "proceed"}):
            return approval_id, "APPROVED"
        if words.intersection({"reject", "decline", "cancel", "no"}):
            return approval_id, "REJECTED"
        return approval_id, None

    def record_confirmation(
        self,
        approval_id: str,
        result: str,
        confirmer_email: str,
    ) -> dict[str, Any]:
        return self.state_store.update_approval(
            approval_id,
            {"status": result, "confirmed_by": confirmer_email},
        )
