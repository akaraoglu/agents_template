"""Project registry service backed by the authoritative state store."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .state_store import StateStore


_OPEN_STATUSES = {"NEW", "ACTIVE", "VERIFICATION_PENDING", "BLOCKED"}


@dataclass
class ProjectResolution:
    project_id: str | None
    ambiguous: bool
    candidates: list[dict[str, Any]]
    follow_up_question: str | None = None


def _tokens(value: str) -> set[str]:
    return {chunk for chunk in re.split(r"[^a-zA-Z0-9]+", value.lower()) if chunk}


class ProjectRegistryService:
    """Read-only project query helper used by Neo/AgentSmith flows."""

    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store

    def list_projects(self, include_done: bool = False) -> list[dict[str, Any]]:
        projects = self.state_store.list_projects()
        if include_done:
            return sorted(projects, key=lambda row: row.get("updated_at", ""), reverse=True)
        filtered = [row for row in projects if row.get("status", "NEW") in _OPEN_STATUSES]
        return sorted(filtered, key=lambda row: row.get("updated_at", ""), reverse=True)

    def find_project(self, project_ref: str) -> ProjectResolution:
        project_ref = (project_ref or "").strip()
        if not project_ref:
            return ProjectResolution(None, False, [])
        direct = self.state_store.get_project(project_ref)
        if direct:
            return ProjectResolution(direct["id"], False, [direct])
        requested_tokens = _tokens(project_ref)
        candidates: list[dict[str, Any]] = []
        for project in self.state_store.list_projects():
            fields = " ".join(
                str(part)
                for part in (
                    project.get("id", ""),
                    project.get("name", ""),
                    project.get("canonical_topic", ""),
                    project.get("summary", ""),
                )
            )
            haystack_tokens = _tokens(fields)
            if requested_tokens and requested_tokens.issubset(haystack_tokens):
                candidates.append(project)
        if len(candidates) == 1:
            return ProjectResolution(candidates[0]["id"], False, candidates)
        if len(candidates) > 1:
            names = ", ".join(row.get("name", row["id"]) for row in candidates[:4])
            return ProjectResolution(
                None,
                True,
                candidates,
                f"I found multiple matching projects: {names}. Which one should I use?",
            )
        return ProjectResolution(None, False, [])

    def get_project_status(self, project_id: str) -> dict[str, Any] | None:
        project = self.state_store.get_project(project_id)
        if not project:
            return None
        return {
            "project_id": project_id,
            "name": project.get("name"),
            "status": project.get("status", "NEW"),
            "summary": project.get("summary", ""),
            "updated_at": project.get("updated_at"),
        }

    def get_project_summary(self, project_id: str) -> str:
        project = self.state_store.get_project(project_id)
        if not project:
            return f"Project '{project_id}' was not found."
        return (
            f"{project.get('name', project_id)} "
            f"[{project.get('status', 'NEW')}]: {project.get('summary', 'No summary yet.')}"
        )

    def get_blocked_projects(self) -> list[dict[str, Any]]:
        return [row for row in self.state_store.list_projects() if row.get("status") == "BLOCKED"]

    def get_project_next_actions(self, project_id: str) -> list[str]:
        project = self.state_store.get_project(project_id) or {}
        actions = project.get("next_actions")
        if isinstance(actions, list):
            return [str(action) for action in actions]
        if isinstance(actions, str) and actions:
            return [actions]
        return []

    def resolve_project_from_context(self, dm_or_topic_context: dict[str, Any]) -> ProjectResolution:
        text = str(dm_or_topic_context.get("text", "")).strip()
        topic_name = str(dm_or_topic_context.get("topic_name", "")).strip()

        topic_match = re.search(r"project/([a-zA-Z0-9_.-]+)", topic_name.lower())
        if topic_match:
            project_id = topic_match.group(1)
            if self.state_store.get_project(project_id):
                return ProjectResolution(project_id, False, [self.state_store.get_project(project_id)])

        explicit_match = re.search(
            r"(?:project[/\s:#-]+)([a-zA-Z0-9_.-]+)", text.lower()
        )
        if explicit_match:
            return self.find_project(explicit_match.group(1))

        matches: list[dict[str, Any]] = []
        text_tokens = _tokens(text)
        for project in self.state_store.list_projects():
            candidate_tokens = _tokens(project.get("name", "")) | _tokens(project.get("id", ""))
            if candidate_tokens and text_tokens.intersection(candidate_tokens):
                matches.append(project)
        if len(matches) == 1:
            return ProjectResolution(matches[0]["id"], False, matches)
        if len(matches) > 1:
            names = ", ".join(row.get("name", row["id"]) for row in matches[:4])
            return ProjectResolution(
                None,
                True,
                matches,
                f"I found multiple matching projects: {names}. Which one should I use?",
            )
        return ProjectResolution(None, False, [])

