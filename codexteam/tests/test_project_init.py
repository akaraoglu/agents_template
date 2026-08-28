import shutil
from pathlib import Path

import pytest

from codexteam_tools.project_init import DEFAULT_TEMPLATE_ROOT, initialize_project, main
from codexteam_tools.tasks import parse_task_document


DEFAULT_PROJECT_MANIFEST = tuple(
    """.codexteam/README.md
.codexteam/native-agents/codexteam_architect.toml
.codexteam/native-agents/codexteam_developer.toml
.codexteam/native-agents/codexteam_documenter.toml
.codexteam/native-agents/codexteam_feature_planner.toml
.codexteam/native-agents/codexteam_git_steward.toml
.codexteam/native-agents/codexteam_leader.toml
.codexteam/native-agents/codexteam_reviewer.toml
.codexteam/native-agents/codexteam_tester.toml
.codexteam/native-agents/codexteam_ux_designer.toml
.codexteam/roles/architect.toml
.codexteam/roles/developer.toml
.codexteam/roles/documenter.toml
.codexteam/roles/feature_planner.toml
.codexteam/roles/git_steward.toml
.codexteam/roles/leader.toml
.codexteam/roles/reviewer.toml
.codexteam/roles/tester.toml
.codexteam/roles/ux_designer.toml
.codexteam/skills/architecture-design.md
.codexteam/skills/codexteam-self-improvement.md
.codexteam/skills/debugging.md
.codexteam/skills/delivery.md
.codexteam/skills/development-testing.md
.codexteam/skills/document-editing.md
.codexteam/skills/feature-planning.md
.codexteam/skills/git-steward.md
.codexteam/skills/implementation.md
.codexteam/skills/integration-testing.md
.codexteam/skills/project-doc-map.md
.codexteam/skills/project-lead.md
.codexteam/skills/sdd-workflow.md
.codexteam/skills/subagent-orchestration.md
.codexteam/skills/task-breakdown.md
.codexteam/skills/team-context-mcp.md
.codexteam/skills/testing.md
.codexteam/skills/ux-ui-design.md
.codexteam/skills/verification.md
.gitignore
AGENTS.md
ARCHITECTURE.md
BLOCKED_REPORT.md
BRIEF.md
CURRENT_TASK.md
DECISIONS.md
DONE_REPORT.md
IMPLEMENTATION_PLAN.md
OPEN_QUESTIONS.md
PROJECT.md
PROJECT_STATE.md
RESULT.md
TASKS.md
design/architecture/.gitkeep
docs/architecture/.gitkeep
docs/decisions/README.md
management/BACKLOG.md
management/GIT_POLICY.md
management/PLAN.md
management/TEST_GATES.md
management/TEST_GATES.toml
management/tasks/T001.md
management/tasks/T002.md
management/tasks/T003.md
management/tasks/T004.md
management/tasks/T005.md
results/.gitkeep
src/.gitkeep
tests/integration/.gitkeep
tests/smoke/.gitkeep
tests/unit/.gitkeep""".splitlines()
)


def test_project_dry_run_is_complete_and_does_not_write(tmp_path: Path):
    plan = initialize_project(
        "Example Project",
        "Deliver a verified example.",
        root=tmp_path,
        project_id="example-project",
        dry_run=True,
        control_only=False,
    )
    assert plan.tasks == ("T001", "T002", "T003", "T004", "T005")
    assert plan.files == DEFAULT_PROJECT_MANIFEST
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
    assert ".codexteam/skills/team-context-mcp.md" in plan.files
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
    assert "design/architecture/.gitkeep" in plan.files
    assert ".gitignore" in plan.files
    assert not plan.project_dir.exists()
    assert plan.initialize_git is True
    assert plan.control_only is False


def test_control_only_initialization_omits_product_scaffolds(tmp_path: Path):
    plan = initialize_project(
        "Control Project",
        "Manage external source.",
        root=tmp_path,
        project_id="control-project",
        control_only=True,
        dry_run=True,
    )
    assert plan.control_only is True
    assert "design/architecture/.gitkeep" in plan.files
    assert "docs/architecture/.gitkeep" in plan.files
    assert "results/.gitkeep" in plan.files
    assert not any(path == "src/.gitkeep" or path.startswith("tests/") for path in plan.files)


def test_control_only_is_the_default(tmp_path: Path):
    plan = initialize_project(
        "Control Project",
        "Manage external source.",
        root=tmp_path,
        project_id="control-project",
        dry_run=True,
    )
    assert plan.control_only is True
    assert not any(path == "src/.gitkeep" or path.startswith("tests/") for path in plan.files)


def test_cli_product_scaffold_is_explicit_opt_in(tmp_path: Path, capsys):
    code = main([
        "Legacy Project",
        "--goal", "Create a legacy single-root project.",
        "--projects-root", str(tmp_path),
        "--project-id", "legacy-project",
        "--with-product-scaffold",
        "--dry-run",
        "--json",
    ])

    assert code == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["control_only"] is False
    assert "src/.gitkeep" in payload["files"]


def test_project_initialization_renders_all_tokens(tmp_path: Path):
    plan = initialize_project(
        "Example Project",
        "Deliver a verified example.",
        root=tmp_path,
        project_id="example-project",
        control_only=False,
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
    project_agents = (plan.project_dir / "AGENTS.md").read_text()
    assert "Do not repeat the same command or failure path" in project_agents
    assert "Start with its exact context targets" in project_agents
    assert "historical results only when" in project_agents
    assert "the handoff targets them" in project_agents
    assert "Read `BRIEF.md`, `PROJECT.md`, `CURRENT_TASK.md`, and" not in project_agents
    tasks = parse_task_document((plan.project_dir / "TASKS.md").read_text())
    assert tasks.row("T001").status == "In Progress"
    assert tasks.row("T002").owner == "architect-01"
    assert tasks.row("T004").owner == "test-engineer-01"
    assert tasks.row("T005").owner == "reviewer-01"
    for task_id in ("T001", "T002", "T003", "T004", "T005"):
        handoff = (
            plan.project_dir / "management" / "tasks" / f"{task_id}.md"
        ).read_text()
        assert "## Short Description" in handoff
        assert "- Type:" in handoff
        assert "- Summary:" in handoff
        assert "- Outcome:" in handoff
        assert "- AgentSpec:" in handoff
        assert "- Backend:" in handoff
        assert "- Profile:" in handoff
        assert "- Reasoning:" in handoff
        assert "- Backend: `codex`" in handoff
        assert "- Profile: `qwen38-27b`" in handoff
        assert "## Execution Class\n\n- `complex`" in handoff
        assert "- Reasoning: `medium`" in handoff
    for task_id in ("T002", "T003", "T004", "T005"):
        handoff = (
            plan.project_dir / "management" / "tasks" / f"{task_id}.md"
        ).read_text()
        compact_handoff = " ".join(handoff.split())
        assert "## Prior Discoveries" in compact_handoff
        assert "No relevant prior discovery found." in compact_handoff
        assert "## Context Targets" in compact_handoff
        assert "Question:" in compact_handoff
        assert "Target:" in compact_handoff
        assert "Use:" in compact_handoff
        assert "exact" in compact_handoff
    developer_handoff = (
        plan.project_dir / "management" / "tasks" / "T003.md"
    ).read_text()
    assert "exact source path and symbol" in developer_handoff
    assert "exact test path and test name" in developer_handoff
    gates = (plan.project_dir / "management" / "TEST_GATES.md").read_text()
    assert "Owner: Developer" in gates
    assert "Owner: Test Engineer (`tester` protocol role)" in gates
    assert "runs the Development Gate first" in gates
    assert "TEST_GATES.toml" in gates
    assert (plan.project_dir / ".git").is_dir()
    initialized_files = tuple(
        sorted(
            path.relative_to(plan.project_dir).as_posix()
            for path in plan.project_dir.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(plan.project_dir).parts
        )
    )
    assert initialized_files == tuple(sorted(plan.files))
    assert not any(path.name == "FORMAT.json" for path in plan.project_dir.rglob("FORMAT.json"))
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


def test_initialized_project_routes_verification_and_delivery_criteria(tmp_path: Path):
    plan = initialize_project(
        "Criteria Project",
        "Deliver evidence-backed criteria.",
        root=tmp_path,
        project_id="criteria-project",
    )
    project = (plan.project_dir / "PROJECT.md").read_text(encoding="utf-8")
    compact_project = " ".join(project.split())
    assert "| Criterion | Validation | Verifier | Expected Evidence |" in project
    assert "| Delivery Requirement | Validation | Responsible Role | Expected Evidence |" in project
    assert "The Project Lead maintains these criteria throughout execution" in compact_project
    assert "the operator is not required to verify every criterion" in compact_project
    assert "AC-01 - Dependency-safe execution" in project
    assert "AC-02 - Independent product evidence" in project

    handoffs = {
        task_id: (
            plan.project_dir / "management" / "tasks" / f"{task_id}.md"
        ).read_text(encoding="utf-8")
        for task_id in ("T001", "T003", "T004", "T005")
    }
    compact_handoffs = {
        task_id: " ".join(handoff.split()) for task_id, handoff in handoffs.items()
    }
    assert "Lead-maintained Acceptance Criteria, Verification Plan, and Delivery Criteria" in compact_handoffs["T001"]
    assert "report their `AC-*` references" in compact_handoffs["T003"]
    assert "without claiming independent acceptance" in compact_handoffs["T003"]
    assert "passed, failed, blocked, or unverified with exact evidence" in compact_handoffs["T004"]
    assert "Verification Plan coverage, Delivery Criteria readiness" in compact_handoffs["T005"]
    assert "applicable to the milestone under review" in compact_handoffs["T005"]


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
    assert "- Type: Documentation" in handoff
    assert "- Summary:" in handoff
    assert "- Outcome:" in handoff
    assert "- AgentSpec: none" in handoff
    assert "- Backend: `codex`" in handoff
    assert "- Profile: `qwen38-27b`" in handoff
    assert "## Execution Class\n\n- `small`" in handoff
    assert "- Reasoning: `medium`" in handoff


def test_custom_template_t006_handoff_is_not_overwritten(tmp_path: Path):
    template_root = tmp_path / "custom-template"
    shutil.copytree(DEFAULT_TEMPLATE_ROOT, template_root)
    custom_handoff = template_root / "management" / "tasks" / "T006.md"
    custom_handoff.write_text(
        "# Task T006: Document the Fibonacci CLI\n\n"
        "## Responsible AI\n\n"
        "`fibonacci-documenter-01` — project-specific documenter.\n\n"
        "## Task Write Scope\n\n"
        "- `docs/**`\n\n"
        "## Context Mode\n\n"
        "- `bounded-mcp`\n\n"
        "## Execution Class\n\n"
        "- `small`\n"
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


def test_custom_canonical_handoff_requires_task_write_scope(tmp_path: Path):
    template_root = tmp_path / "custom-template"
    shutil.copytree(DEFAULT_TEMPLATE_ROOT, template_root)
    (template_root / "management/tasks/T001.md").write_text("# Task T001\n")

    with pytest.raises(ValueError, match="Task Write Scope"):
        initialize_project(
            "Scoped project",
            "Exercise canonical scope validation.",
            root=tmp_path,
            project_id="scoped-project",
            template_root=template_root,
        )


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
