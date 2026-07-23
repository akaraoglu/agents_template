from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codexteam_tools.git_steward import (
    GitStewardError,
    authorize_plan,
    commit_authorized_plan,
    exact_git_root,
    inspect_repository,
    validate_commit_plan,
)
from codexteam_tools.test_gates import run_gate


def git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "--initial-branch", "main")
    git(project, "config", "user.name", "CodexTeam Test")
    git(project, "config", "user.email", "codexteam@example.invalid")
    (project / ".gitignore").write_text(".codexteam/runtime/\n")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    (project / "management").mkdir()
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('src/main.py').read_text() == 'VALUE = 2\\n'",
    ]
    (project / "management" / "TEST_GATES.toml").write_text(
        'schema_version = "1.0"\nverification_paths = ["src/**"]\n\n'
        '[development]\nconfigured = true\nexpected_max_seconds = 30\n'
        f"commands = [{json.dumps(command)}]\n\n"
        '[integration]\nconfigured = true\nexpected_max_seconds = 60\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps(command)}]\n"
    )
    git(project, "add", ".gitignore", "src/main.py", "management/TEST_GATES.toml")
    git(project, "commit", "-m", "chore: initialize test repository")
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    run_gate(project, "integration")
    return project


def write_plan(project: Path, boundary: str = "milestone-001") -> Path:
    record = json.loads((project / "results/gates/integration.json").read_text())
    plan = {
        "schema_version": "1.0",
        "boundary_id": boundary,
        "project_root": str(project),
        "branch": "main",
        "expected_head": git(project, "rev-parse", "HEAD"),
        "task_ids": ["T003", "T004", "T005"],
        "paths": ["src/main.py", "results/gates/integration.json"],
        "excluded_paths": [],
        "verification": {
            "kind": "integration",
            "artifact_ref": "results/gates/integration.json",
            "workspace_digest": record["workspace_digest"],
        },
        "commit_subject": "feat: deliver verified milestone",
        "commit_body": "Implement the approved milestone and preserve gate evidence.",
        "pr_title": "Deliver verified milestone",
        "pr_summary": "The milestone passed the Development and Integration Gates.",
        "warnings": [],
    }
    path = project / ".codexteam/runtime/git-steward" / boundary / "plan.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(plan))
    return path


def test_exact_git_root_rejects_parent_repository_fallback(tmp_path: Path):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    git(root, "init", "--initial-branch", "main")
    with pytest.raises(GitStewardError, match="exact Git root"):
        exact_git_root(child)


def test_inspection_and_dry_run_do_not_mutate_git(tmp_path: Path):
    project = repository(tmp_path)
    before = git(project, "rev-parse", "HEAD")
    objects_before = git(project, "count-objects", "-v")
    inspection = inspect_repository(
        project,
        boundary_id="milestone-001",
        task_ids=("T003", "T004", "T005"),
    )
    assert "src/main.py" in inspection["changed_paths"]
    plan_path = write_plan(project)
    authorization, authorization_path = authorize_plan(project, plan_path, apply=True)
    preview, _ = commit_authorized_plan(
        project,
        plan_path,
        authorization_path,
        apply=False,
    )
    assert authorization["boundary_id"] == "milestone-001"
    assert preview["status"] == "ready"
    assert "candidate_tree" not in preview
    assert git(project, "rev-parse", "HEAD") == before
    assert git(project, "count-objects", "-v") == objects_before


def test_authorized_plan_creates_one_exact_local_commit(tmp_path: Path):
    project = repository(tmp_path)
    before = git(project, "rev-parse", "HEAD")
    plan_path = write_plan(project)
    _, authorization_path = authorize_plan(project, plan_path, apply=True)

    record, record_path = commit_authorized_plan(
        project,
        plan_path,
        authorization_path,
        apply=True,
    )

    assert record["head_before"] == before
    assert record["head_after"] == git(project, "rev-parse", "HEAD")
    assert set(record["committed_paths"]) == {
        "src/main.py",
        "results/gates/integration.json",
    }
    assert record_path.is_file()
    assert "CodexTeam-Boundary: milestone-001" in git(project, "show", "-s", "--format=%B", "HEAD")
    assert git(project, "rev-list", "--count", f"{before}..HEAD") == "1"
    assert git(project, "status", "--short") == ""


def test_stale_gate_or_head_blocks_authorization_and_commit(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    (project / "src" / "main.py").write_text("VALUE = 3\n")
    with pytest.raises(GitStewardError, match="stale|verification"):
        authorize_plan(project, plan_path, apply=True)


def test_commit_plan_rejects_runtime_and_secret_paths(tmp_path: Path):
    project = repository(tmp_path)
    plan = json.loads(write_plan(project).read_text())
    plan["paths"] = [".env"]
    with pytest.raises(GitStewardError, match="unsafe approved path"):
        validate_commit_plan(plan, project)


def test_authorization_requires_every_change_to_be_classified(tmp_path: Path):
    project = repository(tmp_path)
    (project / "README.md").write_text("unrelated\n")
    plan_path = write_plan(project)

    with pytest.raises(GitStewardError, match="unclassified.*README.md"):
        authorize_plan(project, plan_path, apply=True)


def test_architecture_only_plan_rejects_source_paths(tmp_path: Path):
    project = repository(tmp_path)
    plan = json.loads(write_plan(project).read_text())
    plan["verification"]["kind"] = "architecture"
    plan["verification"]["artifact_ref"] = "results/architecture-review.md"
    plan["verification"]["workspace_digest"] = "0" * 64

    with pytest.raises(GitStewardError, match="non-architecture paths"):
        validate_commit_plan(plan, project)


def test_authorized_exclusion_remains_untracked_and_unstaged(tmp_path: Path):
    project = repository(tmp_path)
    (project / "README.md").write_text("unrelated operator work\n")
    plan_path = write_plan(project)
    plan = json.loads(plan_path.read_text())
    plan["excluded_paths"] = ["README.md"]
    plan_path.write_text(json.dumps(plan))
    _, authorization_path = authorize_plan(project, plan_path, apply=True)

    record, _ = commit_authorized_plan(project, plan_path, authorization_path, apply=True)

    assert "README.md" not in record["committed_paths"]
    assert git(project, "status", "--short") == "?? README.md"


def test_plan_change_after_authorization_is_rejected(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    _, authorization_path = authorize_plan(project, plan_path, apply=True)
    plan = json.loads(plan_path.read_text())
    plan["commit_subject"] = "feat: changed after approval"
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(GitStewardError, match="authorization does not match"):
        commit_authorized_plan(project, plan_path, authorization_path, apply=True)


def test_existing_staged_changes_block_authorization(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    git(project, "add", "src/main.py")

    with pytest.raises(GitStewardError, match="already contains staged changes"):
        authorize_plan(project, plan_path, apply=True)


def test_active_hook_blocks_commit_before_candidate_objects(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    _, authorization_path = authorize_plan(project, plan_path, apply=True)
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    objects_before = git(project, "count-objects", "-v")

    with pytest.raises(GitStewardError, match="active Git hooks"):
        commit_authorized_plan(project, plan_path, authorization_path, apply=True)
    assert git(project, "count-objects", "-v") == objects_before
