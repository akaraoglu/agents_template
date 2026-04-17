"""Workspace filesystem helpers used by foundational skills and gateway actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


_REQUIRED_FILES = [
    "PROJECT.md",
    "management/PLAN.md",
    "management/STATUS.md",
    "management/MILESTONES.md",
    "management/BACKLOG.md",
    "management/DECISIONS.md",
    "management/TEST_REPORT.md",
]

_MANAGEMENT_SURFACE_FILES = [
    "PROJECT.md",
    "management/PLAN.md",
    "management/STATUS.md",
    "management/MILESTONES.md",
    "management/BACKLOG.md",
    "management/DECISIONS.md",
]


class WorkspaceService:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or RuntimePaths.from_root().ensure().projects_root
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def resolve_workspace(self, project_id: str) -> Path:
        path = self.workspace_root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_project_structure(self, project_id: str) -> Path:
        root = self.resolve_workspace(project_id)
        for rel_path in _REQUIRED_FILES:
            full_path = root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if not full_path.exists():
                full_path.write_text("", encoding="utf-8")
        (root / "artifacts" / "incoming").mkdir(parents=True, exist_ok=True)
        (root / "artifacts" / "outgoing").mkdir(parents=True, exist_ok=True)
        (root / "artifacts" / "reports").mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        return root

    def read_project_file(self, project_id: str, path: str) -> str:
        root = self.resolve_workspace(project_id)
        full_path = (root / path).resolve()
        if not str(full_path).startswith(str(root.resolve())):
            raise ValueError("Path escapes project workspace.")
        return full_path.read_text(encoding="utf-8")

    def read_management_surface(self, project_id: str) -> dict[str, str]:
        self.ensure_project_structure(project_id)
        return {
            rel_path: self.read_project_file(project_id, rel_path)
            for rel_path in _MANAGEMENT_SURFACE_FILES
        }

    def write_project_file(self, project_id: str, path: str, content: str) -> Path:
        root = self.resolve_workspace(project_id)
        full_path = (root / path).resolve()
        if not str(full_path).startswith(str(root.resolve())):
            raise ValueError("Path escapes project workspace.")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return full_path

    def validate_workspace(self, project_id: str) -> dict[str, Any]:
        root = self.resolve_workspace(project_id)
        missing = [rel_path for rel_path in _REQUIRED_FILES if not (root / rel_path).exists()]
        return {"project_id": project_id, "workspace": str(root), "valid": not missing, "missing": missing}

    def create_project_surface(
        self,
        project_id: str,
        project_name: str,
        summary: str,
        *,
        status: str = "ACTIVE",
        next_actions: list[str] | None = None,
        milestones: list[str] | None = None,
        backlog_items: list[str] | None = None,
        blockers: list[str] | None = None,
        decisions: list[str] | None = None,
    ) -> dict[str, Any]:
        root = self.ensure_project_structure(project_id)
        next_actions = next_actions or ["Awaiting execution handoff processing."]
        milestones = milestones or ["M1: Foundation setup"]
        backlog_items = backlog_items or ["Seed project backlog item"]
        blockers = blockers or []
        decisions = decisions or [
            "Initial project surface created by AgentSmith after confirmation."
        ]
        self.write_project_file(
            project_id,
            "PROJECT.md",
            f"# {project_name}\n\n## Summary\n{summary.strip()}\n",
        )
        self.write_project_file(
            project_id,
            "management/PLAN.md",
            "## Internal Plan\n- Execution plan pending.\n",
        )
        self.write_project_file(
            project_id,
            "management/STATUS.md",
            (
                f"Status: {status}\n\n"
                "Next:\n"
                + "\n".join(f"- {item}" for item in next_actions)
                + "\n\n"
                + "Blockers:\n"
                + (
                    "\n".join(f"- {item}" for item in blockers)
                    if blockers
                    else "- None\n"
                )
            ),
        )
        self.write_project_file(
            project_id,
            "management/MILESTONES.md",
            "## Milestones\n" + "\n".join(f"- {item}" for item in milestones) + "\n",
        )
        self.write_project_file(
            project_id,
            "management/BACKLOG.md",
            "## Backlog\n" + "\n".join(f"- {item}" for item in backlog_items) + "\n",
        )
        self.write_project_file(
            project_id,
            "management/DECISIONS.md",
            "## Decisions\n" + "\n".join(f"- {item}" for item in decisions) + "\n",
        )
        self.write_project_file(
            project_id,
            "management/TEST_REPORT.md",
            "## Test Report\n- No execution yet.\n",
        )
        return {"project_id": project_id, "workspace": str(root)}
