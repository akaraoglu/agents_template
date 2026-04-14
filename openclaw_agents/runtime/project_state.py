"""Helpers for project-local hidden runtime state under each workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectStateLayout:
    """Resolved project-local runtime layout under ``<workspace>/.agents``."""

    project_root: Path
    agents_root: Path
    project_db_path: Path
    runtime_root: Path
    runtime_incoming_dir: Path
    runtime_responses_dir: Path
    openclaw_root: Path
    openclaw_workspace_dir: Path
    openclaw_agents_dir: Path

    @classmethod
    def from_workspace(cls, workspace_ref: str | Path) -> "ProjectStateLayout":
        project_root = Path(workspace_ref).resolve()
        agents_root = project_root / ".agents"
        runtime_root = agents_root / "runtime"
        openclaw_root = agents_root / "openclaw"
        return cls(
            project_root=project_root,
            agents_root=agents_root,
            project_db_path=agents_root / "project.db",
            runtime_root=runtime_root,
            runtime_incoming_dir=runtime_root / "incoming",
            runtime_responses_dir=runtime_root / "runtime_responses",
            openclaw_root=openclaw_root,
            openclaw_workspace_dir=openclaw_root / "workspace",
            openclaw_agents_dir=openclaw_root / "agents",
        )

    def ensure_runtime_dirs(self, *, response_dir_name: str = "runtime_responses") -> Path:
        self.runtime_incoming_dir.mkdir(parents=True, exist_ok=True)
        response_dir = self.runtime_root / response_dir_name
        response_dir.mkdir(parents=True, exist_ok=True)
        return response_dir

    def ensure_openclaw_workspace(self) -> Path:
        workspace_dir = self.openclaw_workspace_dir
        workspace_dir.mkdir(parents=True, exist_ok=True)
        project_link = workspace_dir / "project"
        expected_target = self.project_root
        if project_link.is_symlink():
            target = project_link.resolve()
            if target != expected_target:
                project_link.unlink()
                project_link.symlink_to(expected_target, target_is_directory=True)
        elif project_link.exists():
            raise RuntimeError(f"{project_link} exists and is not the expected project symlink")
        else:
            project_link.symlink_to(expected_target, target_is_directory=True)
        return workspace_dir

    def openclaw_agent_dir(self, backend_agent_id: str) -> Path:
        return self.openclaw_agents_dir / backend_agent_id / "agent"
