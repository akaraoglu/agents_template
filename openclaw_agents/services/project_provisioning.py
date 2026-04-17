"""Project creation and update helpers for canonical project surfaces."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .state_store import StateStore
from .workspace_service import WorkspaceService


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _slugify(value: str) -> str:
    lowered = value.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "project"


def _normalize_lines(value: Any, fallback: list[str] | None = None) -> list[str]:
    if value is None:
        return list(fallback or [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return list(fallback or [])
    return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]


class ProjectProvisioningService:
    def __init__(self, state_store: StateStore, workspace_service: WorkspaceService) -> None:
        self.state_store = state_store
        self.workspace_service = workspace_service

    def _unique_project_id(self, preferred_name: str) -> str:
        base = _slugify(preferred_name)
        existing = {project["id"] for project in self.state_store.list_projects()}
        if base not in existing:
            return base
        counter = 2
        while f"{base}-{counter}" in existing:
            counter += 1
        return f"{base}-{counter}"

    def create_project_surface(
        self,
        name: str,
        summary: str,
        requested_by: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_project_id = project_id or self._unique_project_id(name)
        next_actions = ["Execution handoff pending for Niaobe."]
        milestones = ["M1: Foundation setup"]
        backlog_items = ["Seed project backlog item"]
        blockers: list[str] = []
        decisions = ["Initial project surface created by AgentSmith after confirmation."]
        workspace_info = self.workspace_service.create_project_surface(
            resolved_project_id,
            project_name=name,
            summary=summary,
            status="ACTIVE",
            next_actions=next_actions,
            milestones=milestones,
            backlog_items=backlog_items,
            blockers=blockers,
            decisions=decisions,
        )
        record = {
            "id": resolved_project_id,
            "name": name,
            "status": "ACTIVE",
            "summary": summary.strip() or "No summary provided.",
            "requested_by": requested_by,
            "canonical_stream": "projects",
            "canonical_topic": f"project/{resolved_project_id}",
            "workspace_path": workspace_info["workspace"],
            "next_actions": next_actions,
            "milestones": milestones,
            "backlog_items": backlog_items,
            "backlog_count": len(backlog_items),
            "blockers": blockers,
            "decisions": decisions,
            "created_from": "confirmed_mutation",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        return self.state_store.upsert_project(record)

    def update_project_surface(
        self,
        project_id: str,
        updates: dict[str, Any],
        requested_by: str,
    ) -> dict[str, Any]:
        current = self.state_store.get_project(project_id)
        if not current:
            raise ValueError(f"Project '{project_id}' was not found.")
        allowed = {
            "name",
            "summary",
            "status",
            "next_actions",
            "milestones",
            "backlog_items",
            "blockers",
            "decisions",
        }
        sanitized = {key: value for key, value in updates.items() if key in allowed}
        sanitized["requested_by"] = requested_by
        self.workspace_service.ensure_project_structure(project_id)

        project_name = str(sanitized.get("name", current.get("name", project_id))).strip()
        project_summary = str(sanitized.get("summary", current.get("summary", "No summary provided."))).strip()
        milestones = _normalize_lines(sanitized.get("milestones"), _normalize_lines(current.get("milestones")))
        next_actions = _normalize_lines(
            sanitized.get("next_actions"),
            _normalize_lines(current.get("next_actions")),
        )
        backlog_items = _normalize_lines(
            sanitized.get("backlog_items"),
            _normalize_lines(current.get("backlog_items")),
        )
        blockers = _normalize_lines(
            sanitized.get("blockers"),
            _normalize_lines(current.get("blockers")),
        )
        decisions = _normalize_lines(
            sanitized.get("decisions"),
            _normalize_lines(current.get("decisions")),
        )
        status = str(sanitized.get("status", current.get("status", "ACTIVE"))).strip() or "ACTIVE"

        if "summary" in sanitized:
            self.workspace_service.write_project_file(
                project_id,
                "PROJECT.md",
                f"# {project_name}\n\n## Summary\n{project_summary}\n",
            )
        elif "name" in sanitized:
            self.workspace_service.write_project_file(
                project_id,
                "PROJECT.md",
                f"# {project_name}\n\n## Summary\n{project_summary}\n",
            )
        if "milestones" in sanitized:
            sanitized["milestones"] = milestones
            body = "## Milestones\n" + "\n".join(f"- {item}" for item in milestones) + "\n"
            self.workspace_service.write_project_file(project_id, "management/MILESTONES.md", body)
        if "status" in sanitized or "next_actions" in sanitized or "blockers" in sanitized:
            sanitized["next_actions"] = next_actions
            sanitized["blockers"] = blockers
            body = (
                f"Status: {status}\n\n"
                "Next:\n"
                + "\n".join(f"- {item}" for item in next_actions)
                + "\n\n"
                + "Blockers:\n"
                + ("\n".join(f"- {item}" for item in blockers) if blockers else "- None")
                + "\n"
            )
            self.workspace_service.write_project_file(project_id, "management/STATUS.md", body)
        if "backlog_items" in sanitized:
            sanitized["backlog_items"] = backlog_items
            body = "## Backlog\n" + "\n".join(f"- {item}" for item in backlog_items) + "\n"
            self.workspace_service.write_project_file(project_id, "management/BACKLOG.md", body)
            sanitized["backlog_count"] = len(backlog_items)
        if "decisions" in sanitized:
            sanitized["decisions"] = decisions
            body = "## Decisions\n" + "\n".join(f"- {item}" for item in decisions) + "\n"
            self.workspace_service.write_project_file(project_id, "management/DECISIONS.md", body)
        merged = {**current, **sanitized, "updated_at": _utc_now()}
        return self.state_store.upsert_project(merged)
