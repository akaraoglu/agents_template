"""Provision isolated project workspaces for fresh control-plane projects."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.scheduler.management_writer import WorkspaceManagementWriter


class ProjectWorkspaceProvisioner:
    """Create and register a per-project workspace from the committed template."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        workspace_root: str | Path | None = None,
        template_root: str | Path | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        base = Path(__file__).resolve().parents[1]
        configured_root = workspace_root or os.environ.get("OPENCLAW_PROJECT_WORKSPACES_DIR")
        self.workspace_root = self._resolve_workspace_root(configured_root=configured_root)
        self.template_root = Path(template_root or (base / "templates" / "project_workspace")).resolve()
        self.management_writer = WorkspaceManagementWriter(
            self.store,
            template_root=self.template_root,
        )

    @staticmethod
    def _resolve_workspace_root(*, configured_root: str | Path | None) -> Path:
        if configured_root:
            return Path(configured_root).expanduser()
        default_workspace_root = Path.home() / "workspace" / "claw_software_workspace" / "projects"
        if default_workspace_root.exists():
            return default_workspace_root
        return Path("/tmp/openclaw_agents_workspaces")

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
        return slug.strip("-") or "project"

    def _workspace_path(self, project_id: str) -> Path:
        return (self.workspace_root / self._slugify(project_id)).resolve()

    def _copy_template(self, workspace_path: Path) -> None:
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_root, workspace_path, dirs_exist_ok=True)

    def _render_project_md(
        self,
        *,
        project_id: str,
        goal: str,
        priority: str,
        workspace_path: Path,
        checkpoint: str,
    ) -> str:
        summary = goal.strip() or f"Project {project_id}"
        return (
            "# PROJECT\n\n"
            "This file is the workspace-level project charter and execution contract. "
            "Keep it aligned with the authoritative control-plane state.\n\n"
            "## Identity\n\n"
            f"- Project ID: `{project_id}`\n"
            f"- Human name: `{project_id}`\n"
            f"- Priority: `{priority}`\n"
            "- Project status: `NEW`\n"
            "- Runtime status: `READY`\n"
            "- Assigned project orchestrator: `Niobe`\n"
            "- Assigned software orchestrator: `Morpheus`\n"
            f"- Workspace ref: `{workspace_path}`\n"
            f"- Repo root: `{workspace_path}`\n"
            f"- Branch or worktree id: `{workspace_path.name}`\n"
            f"- Last clean commit or checkpoint: `{checkpoint}`\n\n"
            "## Summary\n\n"
            f"{summary}\n\n"
            "## Goals\n\n"
            f"- Deliver the requested outcome for `{project_id}`.\n"
            "- Produce implementation evidence and verification evidence.\n"
            "- Keep the workspace aligned with control-plane state.\n\n"
            "## Non-Goals\n\n"
            "- Expanding scope beyond the human request without an explicit decision.\n"
            "- Treating Zulip discussion as authoritative state.\n\n"
            "## Acceptance Criteria\n\n"
            "- The delivered result satisfies the framed project charter.\n"
            "- Implementation evidence is persisted in workspace artifacts.\n"
            "- Oracle verification evidence exists before closure.\n\n"
            "## Constraints\n\n"
            "- Technical constraints: `[to be refined by Architect and Morpheus]`\n"
            "- Process constraints: `Use the control-plane workflow and persist artifacts at safe boundaries.`\n"
            "- Environment constraints: `[to be refined during execution]`\n\n"
            "## System Context\n\n"
            "- Upstream inputs: `Human intake through Zulip and the generated project_charter artifact.`\n"
            "- Downstream consumers: `The requesting human operator and the visible agent loop.`\n"
            "- Key artifacts expected: `project_charter`, `architecture_spec`, `software_delivery_package`, `verification_report`\n\n"
            "## Repositories And Commands\n\n"
            "- Primary repo or repos: `[workspace-scoped project files]`\n"
            "- Build command: `[to be defined]`\n"
            "- Test command: `[to be defined]`\n"
            "- Lint or static-check command: `[to be defined]`\n"
            "- Run or demo command: `[to be defined]`\n\n"
            "## Architecture Notes\n\n"
            "- Existing design references: `[none yet]`\n"
            "- Known technical boundaries: `Project-scoped isolated workspace only.`\n"
            "- Known risk areas: `[to be refined during design]`\n\n"
            "## External Dependencies\n\n"
            "- `[none recorded yet]`\n\n"
            "## Open Questions\n\n"
            "- `[none recorded yet]`\n\n"
            "## Operator Notes\n\n"
            "- Preferred escalation path: `Niobe -> requester`\n"
            "- Pause or switch sensitivity: `Safe after persisted task boundaries only.`\n"
            "- Recovery hints: `Use workspace validation and persisted snapshots before resume.`\n"
        )

    def _render_status_md(
        self,
        *,
        project_id: str,
        priority: str,
        workspace_path: Path,
    ) -> str:
        now = utc_now()
        return (
            "# STATUS\n\n"
            "This file is the human-readable project snapshot. Update it after accepted task "
            "results, escalations, pauses, resumes, and verification outcomes.\n\n"
            "## Current Snapshot\n\n"
            f"- Updated at: `{now}`\n"
            f"- Project ID: `{project_id}`\n"
            "- Project status: `NEW`\n"
            "- Runtime status: `READY`\n"
            f"- Priority: `{priority}`\n"
            "- Current phase: `intake`\n"
            "- Current owner agent: `agent_smith`\n"
            "- Next action: `FRAME_PROJECT`\n"
            "- Safe to pause or switch: `yes`\n"
            "- Last safe boundary type: `[none yet]`\n"
            "- Last snapshot id: `[none yet]`\n"
            f"- Workspace ref: `{workspace_path}`\n\n"
            "## Current Objective\n\n"
            "Frame the project charter and hand the project to Niobe.\n\n"
            "## Open Tasks\n\n"
            "| Task ID | Owner | Task Type | Status | Return To | Notes |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| `[pending]` | `agent_smith` | `FRAME_PROJECT` | `PENDING` | `requesting_agent` | `Created from human intake.` |\n\n"
            "## Recent Accepted Artifacts\n\n"
            "| Artifact Type | Artifact ID | Produced By | Location Or Ref | Why It Matters |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| `[none yet]` | `[none]` | `[none]` | `[none]` | `Awaiting first accepted result.` |\n\n"
            "## Blockers And Waiting Reasons\n\n"
            "- `[none yet]`\n\n"
            "## Recommended Operator Action\n\n"
            "- `no action`\n"
            "- Reason: `The project has been provisioned and is ready for the intake loop.`\n"
        )

    def _initialize_files(
        self,
        *,
        project_id: str,
        goal: str,
        priority: str,
        workspace_path: Path,
        checkpoint: str,
    ) -> None:
        project_path = workspace_path / "PROJECT.md"
        status_path = workspace_path / "management" / "STATUS.md"
        project_path.write_text(
            self._render_project_md(
                project_id=project_id,
                goal=goal,
                priority=priority,
                workspace_path=workspace_path,
                checkpoint=checkpoint,
            )
        )
        status_path.write_text(
            self._render_status_md(
                project_id=project_id,
                priority=priority,
                workspace_path=workspace_path,
            )
        )

    def ensure_for_project(
        self,
        *,
        project_id: str,
        goal: str,
        priority: str = "MEDIUM",
    ) -> dict[str, object]:
        project = self.store.get_project(project_id) or {}
        existing_ref = project.get("workspace_ref")
        workspace_path = Path(existing_ref).resolve() if existing_ref else self._workspace_path(project_id)
        checkpoint = "initial-provision"
        now = utc_now()

        self._copy_template(workspace_path)
        self._initialize_files(
            project_id=project_id,
            goal=goal,
            priority=priority,
            workspace_path=workspace_path,
            checkpoint=checkpoint,
        )

        workspace_ref = str(workspace_path)
        self.store.upsert(
            "workspace_states",
            {
                "workspace_ref": workspace_ref,
                "project_id": project_id,
                "repo_root": workspace_ref,
                "branch_or_worktree_id": workspace_path.name,
                "last_clean_commit_or_checkpoint": checkpoint,
                "is_consistent": True,
                "last_validated_at": None,
                "last_validation_summary": "workspace provisioned",
            },
            conflict_columns=["workspace_ref"],
        )
        self.store.update(
            "projects",
            {
                "workspace_ref": workspace_ref,
                "runtime_status": "READY",
                "updated_at": now,
                "last_activity_at": now,
            },
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "normal_ready",
                "eligible_for_scheduling": True,
                "pause_requested": False,
                "resume_requested": False,
                "preemption_allowed": True,
                "waiting_reason": None,
                "last_scheduled_at": None,
                "times_scheduled": 0,
            },
            conflict_columns=["project_id"],
        )
        self.management_writer.sync_project(project_id)
        return {
            "workspace_ref": workspace_ref,
            "repo_root": workspace_ref,
            "branch_or_worktree_id": workspace_path.name,
            "last_clean_commit_or_checkpoint": checkpoint,
        }
