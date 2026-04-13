"""Workspace validation hooks for resume and recovery workflows."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from openclaw_agents.database.store import ControlPlaneStore, utc_now


@dataclass(slots=True)
class WorkspaceValidationResult:
    ok: bool
    workspace_ref: str | None
    summary: str
    issues: list[str]
    details: dict[str, object] = field(default_factory=dict)


class WorkspaceValidator:
    """Validate persisted workspace references before resume or recovery."""

    IGNORED_GENERATED_PREFIXES = (
        "artifacts/incoming/",
        "artifacts/outgoing/",
        "artifacts/reports/",
        ".agents/",
    )

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def validate_project(self, project_id: str) -> WorkspaceValidationResult:
        project = self.store.get_project(project_id)
        if not project:
            return WorkspaceValidationResult(False, None, f"unknown project {project_id}", ["missing_project"])
        workspace_ref = project.get("workspace_ref")
        if not workspace_ref:
            return WorkspaceValidationResult(False, None, "project is missing workspace_ref", ["missing_workspace_ref"])
        return self.validate_workspace_ref(workspace_ref)

    def validate_workspace_ref(self, workspace_ref: str) -> WorkspaceValidationResult:
        workspace_state = self.store.get_workspace_state(workspace_ref)
        issues: list[str] = []
        details: dict[str, object] = {"workspace_ref": workspace_ref}
        if not workspace_state:
            return WorkspaceValidationResult(
                False,
                workspace_ref,
                "workspace_state record is missing",
                ["missing_workspace_state"],
                details,
            )

        repo_root = Path(workspace_state["repo_root"])
        details["repo_root"] = str(repo_root)
        if not repo_root.exists():
            issues.append("repo_root_missing")
        workspace_path = Path(workspace_ref)
        if not workspace_path.is_absolute():
            workspace_path = repo_root / workspace_ref
        details["workspace_path"] = str(workspace_path)
        if not workspace_path.exists():
            issues.append("workspace_path_missing")
        elif repo_root.exists() and not self._is_within_repo_root(repo_root, workspace_path):
            issues.append("workspace_outside_repo_root")
        persisted_inconsistent = not bool(workspace_state.get("is_consistent"))
        details["persisted_inconsistent_flag"] = persisted_inconsistent
        expected_branch_or_worktree_id = str(workspace_state.get("branch_or_worktree_id") or "").strip()
        expected_checkpoint = str(workspace_state.get("last_clean_commit_or_checkpoint") or "").strip()
        details["expected_branch_or_worktree_id"] = expected_branch_or_worktree_id
        details["expected_checkpoint"] = expected_checkpoint
        if not expected_checkpoint:
            issues.append("missing_workspace_checkpoint")

        if repo_root.exists() and workspace_path.exists():
            git_details, git_issues = self._inspect_git_workspace(
                workspace_path=workspace_path,
                repo_root=repo_root,
                expected_branch_or_worktree_id=expected_branch_or_worktree_id,
                expected_checkpoint=expected_checkpoint,
            )
            details.update(git_details)
            issues.extend(git_issues)

        if persisted_inconsistent and issues:
            issues.insert(0, "workspace_marked_inconsistent")
        issues = list(dict.fromkeys(issues))
        summary = self._build_summary(issues, details)
        self.store.update(
            "workspace_states",
            {
                "is_consistent": not issues,
                "last_validated_at": utc_now(),
                "last_validation_summary": summary,
            },
            where_clause="workspace_ref = ?",
            where_params=[workspace_ref],
        )
        return WorkspaceValidationResult(not issues, workspace_ref, summary, issues, details)

    def _inspect_git_workspace(
        self,
        *,
        workspace_path: Path,
        repo_root: Path,
        expected_branch_or_worktree_id: str,
        expected_checkpoint: str,
    ) -> tuple[dict[str, object], list[str]]:
        details: dict[str, object] = {"git_checked": False}
        issues: list[str] = []
        git_root = self._run_git(workspace_path, "rev-parse", "--show-toplevel")
        if git_root is None:
            return details, issues

        resolved_git_root = Path(git_root)
        details["git_checked"] = True
        details["git_root"] = str(resolved_git_root)
        if resolved_git_root.resolve() != repo_root.resolve():
            issues.append("workspace_git_root_mismatch")

        current_branch = self._run_git(workspace_path, "branch", "--show-current")
        current_head = self._run_git(workspace_path, "rev-parse", "HEAD")
        details["current_branch"] = current_branch or None
        details["current_head"] = current_head or None
        candidate_ids = {
            item
            for item in (
                current_branch or None,
                workspace_path.name,
                resolved_git_root.name,
            )
            if item
        }
        if expected_branch_or_worktree_id and expected_branch_or_worktree_id not in candidate_ids:
            issues.append("workspace_branch_or_worktree_mismatch")

        dirty_files: list[str] = []
        untracked_files: list[str] = []
        status_output = self._run_git(
            workspace_path,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=all",
        )
        if status_output is not None:
            for line in status_output.splitlines():
                if len(line) < 3:
                    continue
                code = line[:2]
                path = self._status_path(line)
                if not path or self._is_ignored_generated_path(path):
                    continue
                if code == "??":
                    untracked_files.append(path)
                else:
                    dirty_files.append(path)
        if dirty_files:
            issues.append("workspace_dirty_tracked_files")
        if untracked_files:
            issues.append("workspace_has_untracked_files")
        details["dirty_tracked_files"] = dirty_files
        details["untracked_files"] = untracked_files

        if expected_checkpoint:
            resolved_checkpoint = self._run_git(workspace_path, "rev-parse", "--verify", f"{expected_checkpoint}^{{commit}}")
            if resolved_checkpoint:
                details["resolved_checkpoint"] = resolved_checkpoint
            elif self._looks_like_git_reference(expected_checkpoint):
                issues.append("workspace_checkpoint_reference_missing")

        return details, issues

    def _build_summary(self, issues: list[str], details: dict[str, object]) -> str:
        if issues:
            return f"workspace validation failed: {', '.join(issues)}"
        if details.get("git_checked"):
            branch = details.get("current_branch") or details.get("expected_branch_or_worktree_id") or "detached"
            head = str(details.get("current_head") or "")[:12]
            if head:
                return f"workspace is valid on {branch} at {head}"
        return "workspace is valid"

    def _run_git(self, cwd: Path, *args: str) -> str | None:
        command = ["git", "-C", str(cwd), *args]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.rstrip("\r\n")

    def _is_within_repo_root(self, repo_root: Path, workspace_path: Path) -> bool:
        try:
            workspace_path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return False
        return True

    def _is_ignored_generated_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        return any(
            normalized == prefix.rstrip("/") or normalized.startswith(prefix)
            for prefix in self.IGNORED_GENERATED_PREFIXES
        )

    def _status_path(self, line: str) -> str:
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            return raw_path.split(" -> ", 1)[1].strip()
        return raw_path

    def _looks_like_git_reference(self, value: str) -> bool:
        stripped = value.strip()
        if not stripped:
            return False
        if stripped in {"HEAD", "main", "master", "develop"}:
            return True
        if stripped.startswith("refs/") or "/" in stripped:
            return True
        if len(stripped) >= 7 and all(char in "0123456789abcdefABCDEF" for char in stripped):
            return True
        return False
