"""Append-only runtime audit logging backed by the authoritative state store."""

from __future__ import annotations

from typing import Any

from .state_store import StateStore


class AuditLogService:
    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store

    def record(
        self,
        *,
        action_type: str,
        actor_agent: str,
        outcome: str,
        payload: dict[str, Any] | None = None,
        project_id: str | None = None,
        handoff_id: str | None = None,
    ) -> dict[str, Any]:
        return self.state_store.record_audit(
            {
                "action_type": action_type,
                "actor_agent": actor_agent,
                "outcome": outcome,
                "payload": payload or {},
                "project_id": project_id,
                "handoff_id": handoff_id,
            }
        )

    def tail(
        self,
        *,
        limit: int = 20,
        action_type: str | None = None,
        actor_agent: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.state_store.list_audit_entries(
            action_type=action_type,
            actor_agent=actor_agent,
            project_id=project_id,
        )
        return rows[-max(1, limit):]

    def summary(self) -> dict[str, Any]:
        rows = self.state_store.list_audit_entries()
        by_action: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        for row in rows:
            action_type = str(row.get("action_type", "unknown"))
            outcome = str(row.get("outcome", "unknown"))
            by_action[action_type] = by_action.get(action_type, 0) + 1
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        return {
            "entry_count": len(rows),
            "by_action_type": by_action,
            "by_outcome": by_outcome,
        }
