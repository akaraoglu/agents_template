import shutil
from pathlib import Path

import pytest

from codexteam_tools.project_init import DEFAULT_TEMPLATE_ROOT, initialize_project
from codexteam_tools.tasks import parse_task_document


def test_project_dry_run_is_complete_and_does_not_write(tmp_path: Path):
    plan = initialize_project(
        "Example Project",
        "Deliver a verified example.",
        root=tmp_path,
        project_id="example-project",
        dry_run=True,
    )
    assert plan.tasks == ("T001", "T002", "T003", "T004", "T005")
    assert "PROJECT.md" in plan.files
    assert "management/tasks/T004.md" in plan.files
    assert "management/tasks/T005.md" in plan.files
    assert "ARCHITECTURE.md" in plan.files
    assert "management/GIT_POLICY.md" in plan.files
    assert "management/TEST_GATES.toml" in plan.files
    assert "management/TEST_GATES.md" in plan.files
    assert ".codexteam/skills/development-testing.md" in plan.files
    assert ".codexteam/skills/integration-testing.md" in plan.files
    assert ".codexteam/skills/verification.md" in plan.files
    assert ".codexteam/skills/subagent-orchestration.md" in plan.files
    assert ".codexteam/skills/codexteam-self-improvement.md" in plan.files
    assert ".codexteam/skills/feature-planning.md" in plan.files
    assert ".codexteam/skills/ux-ui-design.md" in plan.files
    assert ".codexteam/roles/developer.toml" in plan.files
    assert ".codexteam/roles/architect.toml" in plan.files
    assert ".codexteam/roles/feature_planner.toml" in plan.files
    assert ".codexteam/roles/git_steward.toml" in plan.files
    assert ".codexteam/roles/ux_designer.toml" in plan.files
    assert ".codexteam/native-agents/codexteam_tester.toml" in plan.files
    assert ".codexteam/native-agents/codexteam_feature_planner.toml" in plan.files
    assert ".codexteam/native-agents/codexteam_ux_designer.toml" in plan.files
    assert "tests/unit/.gitkeep" in plan.files
    assert "tests/smoke/.gitkeep" in plan.files
    assert "tests/integration/.gitkeep" in plan.files
    assert ".gitignore" in plan.files
    assert not plan.project_dir.exists()
    assert plan.initialize_git is True


def test_project_initialization_renders_all_tokens(tmp_path: Path):
    plan = initialize_project(
        "Example Project",
        "Deliver a verified example.",
        root=tmp_path,
        project_id="example-project",
    )
    assert (plan.project_dir / "results").is_dir()
    assert "Deliver a verified example." in (plan.project_dir / "PROJECT.md").read_text()
    assert "Ordinary corrections resume the same session and attempt." in (
        plan.project_dir / "BRIEF.md"
    ).read_text()
    assert ".codexteam/runtime/" in (plan.project_dir / ".gitignore").read_text()
    assert "Project `AGENTS.md` contains common project rules" in (
        plan.project_dir / ".codexteam" / "README.md"
    ).read_text()
    tasks = parse_task_document((plan.project_dir / "TASKS.md").read_text())
    assert tasks.row("T001").status == "In Progress"
    assert tasks.row("T002").owner == "architect-01"
    assert tasks.row("T004").owner == "test-engineer-01"
    assert tasks.row("T005").owner == "reviewer-01"
    gates = (plan.project_dir / "management" / "TEST_GATES.md").read_text()
    assert "Owner: Developer" in gates
    assert "Owner: Test Engineer (`tester` protocol role)" in gates
    assert "runs the Development Gate first" in gates
    assert "TEST_GATES.toml" in gates
    assert (plan.project_dir / ".git").is_dir()
    assert (
        __import__("subprocess").run(
            ["git", "-C", str(plan.project_dir), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        == str(plan.project_dir)
    )
    current_task = (plan.project_dir / "CURRENT_TASK.md").read_text()
    assert "Task ID: T001" in current_task
    assert "Status: In Progress" in current_task
    for path in plan.project_dir.rglob("*.md"):
        assert "{{" not in path.read_text(encoding="utf-8"), path


def test_t006_is_opt_in_and_has_a_stable_documenter_owner(tmp_path: Path):
    default_plan = initialize_project(
        "Default Project",
        "Deliver the default task set.",
        root=tmp_path,
        project_id="default-project",
        dry_run=True,
    )
    assert default_plan.tasks == ("T001", "T002", "T003", "T004", "T005")
    assert "management/tasks/T006.md" not in default_plan.files

    plan = initialize_project(
        "Documented Project",
        "Deliver verified code and reconciled documentation.",
        root=tmp_path,
        project_id="documented-project",
        tasks=("T001", "T002", "T003", "T004", "T005", "T006"),
    )
    tasks = parse_task_document((plan.project_dir / "TASKS.md").read_text())
    assert plan.tasks == ("T001", "T002", "T003", "T004", "T005", "T006")
    assert tasks.row("T006").owner == "documenter-01"
    handoff = (plan.project_dir / "management" / "tasks" / "T006.md").read_text()
    assert "`documenter-01`" in handoff
    assert "verified delivery evidence" in handoff


def test_custom_template_t006_handoff_is_not_overwritten(tmp_path: Path):
    template_root = tmp_path / "custom-template"
    shutil.copytree(DEFAULT_TEMPLATE_ROOT, template_root)
    custom_handoff = template_root / "management" / "tasks" / "T006.md"
    custom_handoff.write_text(
        "# Task T006: Document the Fibonacci CLI\n\n"
        "## Responsible AI\n\n"
        "`fibonacci-documenter-01` — project-specific documenter.\n"
    )

    plan = initialize_project(
        "Fibonacci CLI",
        "Deliver a verified Fibonacci CLI.",
        root=tmp_path,
        project_id="fibonacci-cli",
        tasks=("T001", "T002", "T003", "T004", "T005", "T006"),
        template_root=template_root,
    )

    rendered = (plan.project_dir / "management" / "tasks" / "T006.md").read_text()
    assert rendered == custom_handoff.read_text()
    assert "fibonacci-documenter-01" in rendered
    assert "Reconcile documentation with verified delivery evidence" not in rendered


def test_project_initialization_can_explicitly_skip_git(tmp_path: Path):
    plan = initialize_project(
        "No Git",
        "Create files only.",
        root=tmp_path,
        project_id="no-git",
        initialize_git=False,
    )
    assert plan.initialize_git is False
    assert not (plan.project_dir / ".git").exists()


def test_existing_project_is_not_overwritten(tmp_path: Path):
    initialize_project("Example", "Goal", root=tmp_path, project_id="example")
    with pytest.raises(FileExistsError):
        initialize_project("Example", "Different goal", root=tmp_path, project_id="example")


def test_unsupported_task_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported"):
        initialize_project("Example", "Goal", root=tmp_path, project_id="example", tasks=("T900",), dry_run=True)
