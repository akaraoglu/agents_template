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

STEWARD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git-steward.py"


def git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def steward_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STEWARD_SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def repository(tmp_path: Path, *, integration_surface: str = "worker") -> Path:
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "--initial-branch", "main")
    git(project, "config", "user.name", "CodexTeam Test")
    git(project, "config", "user.email", "codexteam@example.invalid")
    (project / ".gitignore").write_text(".codexteam/runtime/\ntracked_ignored.txt\n")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    (project / "tracked_ignored.txt").write_text("keep this local\n")
    (project / "tracked_plain.txt").write_text("remain tracked\n")
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
        f'execution_surface = "{integration_surface}"\n'
        'includes = ["development"]\n'
        f"commands = [{json.dumps(command)}]\n"
    )
    git(
        project,
        "add",
        ".gitignore",
        "src/main.py",
        "tracked_plain.txt",
        "management/TEST_GATES.toml",
    )
    git(project, "add", "-f", "tracked_ignored.txt")
    git(project, "commit", "-m", "chore: initialize test repository")
    (project / "src" / "main.py").write_text("VALUE = 2\n")
    run_gate(project, "integration", execution_surface=integration_surface)
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
    assert preview["untrack_paths"] == []
    assert "untrack_paths" not in authorization
    assert "candidate_tree" not in preview
    assert git(project, "rev-parse", "HEAD") == before
    assert git(project, "count-objects", "-v") == objects_before


@pytest.mark.parametrize("integration_surface", ["worker", "lead_host"])
def test_authorized_plan_creates_one_exact_local_commit(
    tmp_path: Path, integration_surface: str,
):
    project = repository(tmp_path, integration_surface=integration_surface)
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


def test_untrack_paths_preserve_local_file_and_remove_only_index_entry(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    plan = json.loads(plan_path.read_text())
    plan["untrack_paths"] = ["tracked_ignored.txt"]
    plan_path.write_text(json.dumps(plan))
    authorization, authorization_path = authorize_plan(project, plan_path, apply=True)

    assert authorization["untrack_paths"] == ["tracked_ignored.txt"]
    preview, _ = commit_authorized_plan(project, plan_path, authorization_path, apply=False)
    assert preview["untrack_paths"] == ["tracked_ignored.txt"]

    record, _ = commit_authorized_plan(project, plan_path, authorization_path, apply=True)

    assert set(record["committed_paths"]) == {
        "src/main.py",
        "results/gates/integration.json",
        "tracked_ignored.txt",
    }
    assert (project / "tracked_ignored.txt").read_bytes() == b"keep this local\n"
    assert "tracked_ignored.txt" not in git(project, "ls-files")
    assert git(project, "status", "--short") == ""


def test_untrack_paths_reject_unsafe_duplicate_and_overlapping_entries(tmp_path: Path):
    project = repository(tmp_path)
    base = json.loads(write_plan(project).read_text())

    unsafe = dict(base)
    unsafe["untrack_paths"] = [".env"]
    with pytest.raises(GitStewardError, match="unsafe approved path"):
        validate_commit_plan(unsafe, project)

    duplicate = dict(base)
    duplicate["untrack_paths"] = ["tracked_ignored.txt", "tracked_ignored.txt"]
    with pytest.raises(GitStewardError, match="untrack_paths cannot contain duplicates"):
        validate_commit_plan(duplicate, project)

    overlap = dict(base)
    overlap["untrack_paths"] = ["src/main.py"]
    with pytest.raises(GitStewardError, match="approved and untrack paths overlap"):
        validate_commit_plan(overlap, project)


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        ("missing_ignored.txt", "untrack path is missing"),
        ("tracked_plain.txt", "untrack path is not ignored"),
    ],
)
def test_untrack_paths_reject_missing_and_non_ignored_entries(
    tmp_path: Path, path: str, pattern: str,
):
    project = repository(tmp_path)
    plan = json.loads(write_plan(project).read_text())
    plan["untrack_paths"] = [path]

    with pytest.raises(GitStewardError, match=pattern):
        validate_commit_plan(plan, project)


def test_untrack_paths_reject_untracked_and_directory_selectors(tmp_path: Path):
    project = repository(tmp_path)
    (project / "untracked_ignored.txt").write_text("not in index\n")
    (project / "ignored-directory").mkdir()
    (project / ".gitignore").write_text(
        ".codexteam/runtime/\ntracked_ignored.txt\nuntracked_ignored.txt\nignored-directory/\n"
    )

    base = json.loads(write_plan(project).read_text())
    untracked = dict(base)
    untracked["untrack_paths"] = ["untracked_ignored.txt"]
    with pytest.raises(GitStewardError, match="untrack path is not tracked"):
        validate_commit_plan(untracked, project)

    directory = dict(base)
    directory["untrack_paths"] = ["ignored-directory"]
    with pytest.raises(GitStewardError, match="cannot select a directory"):
        validate_commit_plan(directory, project)


def test_originating_973_file_shape_preserves_every_local_byte_and_exact_manifest(tmp_path: Path):
    project = repository(tmp_path)
    bulk = project / "local-evidence"
    bulk.mkdir()
    names = [f"local-evidence/evidence-{number:04d}.txt" for number in range(973)]
    for number, relative in enumerate(names):
        (project / relative).write_bytes(f"evidence-{number:04d}\n".encode())
    (project / ".gitignore").write_text(
        ".codexteam/runtime/\ntracked_ignored.txt\nlocal-evidence/\n"
    )
    git(project, "add", ".gitignore")
    git(project, "add", "-f", "--", *names)
    git(project, "commit", "-m", "chore: add representative local evidence")
    run_gate(project, "integration")

    before = {relative: (project / relative).read_bytes() for relative in names}
    plan = json.loads(write_plan(project).read_text())
    plan["untrack_paths"] = names
    plan_path = project / ".codexteam/runtime/git-steward/milestone-001/plan.json"
    plan_path.write_text(json.dumps(plan))
    authorization, authorization_path = authorize_plan(project, plan_path, apply=True)
    record, _ = commit_authorized_plan(project, plan_path, authorization_path, apply=True)

    assert authorization["untrack_paths"] == names
    assert set(record["committed_paths"]) == set(names) | {
        "src/main.py",
        "results/gates/integration.json",
    }
    assert git(project, "ls-files", "--", *names) == ""
    assert {relative: (project / relative).read_bytes() for relative in names} == before
    assert git(project, "status", "--short") == ""
    assert git(project, "remote") == ""


def test_cli_help_and_json_dry_run_do_not_mutate_repository(tmp_path: Path):
    project = repository(tmp_path)
    plan_path = write_plan(project)
    before = git(project, "rev-parse", "HEAD")

    help_result = steward_cli("--help")
    assert help_result.returncode == 0
    assert "Inspect and create verified local milestone commits" in help_result.stdout

    dry_authorize = steward_cli(
        "authorize", str(project), "--plan", str(plan_path), "--json"
    )
    assert dry_authorize.returncode == 0, dry_authorize.stderr
    assert json.loads(dry_authorize.stdout)["boundary_id"] == "milestone-001"
    authorization_path = project / ".codexteam/runtime/git-steward/milestone-001/authorization.json"
    assert not authorization_path.exists()

    applied_authorize = steward_cli(
        "authorize", str(project), "--plan", str(plan_path), "--apply", "--json"
    )
    assert applied_authorize.returncode == 0, applied_authorize.stderr
    preview = steward_cli(
        "commit", str(project), "--plan", str(plan_path),
        "--authorization", str(authorization_path), "--json",
    )
    assert preview.returncode == 0, preview.stderr
    payload = json.loads(preview.stdout)
    assert payload["status"] == "ready"
    assert "candidate_tree" not in payload
    assert git(project, "rev-parse", "HEAD") == before
    assert git(project, "diff", "--cached", "--name-only") == ""


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


def test_commit_plan_rejects_directory_selector(tmp_path: Path):
    project = repository(tmp_path)
    plan = json.loads(write_plan(project).read_text())
    plan["paths"] = ["src"]

    with pytest.raises(GitStewardError, match="cannot select a directory"):
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


def test_candidate_gate_failure_preserves_head_and_index(tmp_path: Path):
    project = repository(tmp_path)
    config = project / "management" / "TEST_GATES.toml"
    branch_check = [
        "git",
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
    ]
    config.write_text(
        config.read_text().replace(
            "commands = [[",
            f"commands = [{json.dumps(branch_check)}, [",
        )
    )
    run_gate(project, "integration")
    plan_path = write_plan(project)
    plan = json.loads(plan_path.read_text())
    plan["paths"].append("management/TEST_GATES.toml")
    plan_path.write_text(json.dumps(plan))
    before_head = git(project, "rev-parse", "HEAD")
    before_branch = git(project, "branch", "--show-current")
    before_source = (project / "src" / "main.py").read_bytes()
    before_config = config.read_bytes()
    _, authorization_path = authorize_plan(project, plan_path, apply=True)

    with pytest.raises(GitStewardError, match="candidate commit tree"):
        commit_authorized_plan(project, plan_path, authorization_path, apply=True)

    assert git(project, "rev-parse", "HEAD") == before_head
    assert git(project, "branch", "--show-current") == before_branch
    assert git(project, "diff", "--cached", "--name-only") == ""
    assert (project / "src" / "main.py").read_bytes() == before_source
    assert config.read_bytes() == before_config
