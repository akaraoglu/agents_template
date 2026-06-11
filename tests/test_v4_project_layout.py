import subprocess
import sys
from pathlib import Path

from AgenticTeam.scripts.v4_project_layout import (
    ensure_v4_project_layout,
    project_dir_for,
    validate_v4_project_layout,
    write_planning_files,
)


def test_project_dir_for_normalizes_project_id(tmp_path):
    project_dir = project_dir_for(tmp_path, "Fibonacci Tree Visualizer 2026")
    assert project_dir == tmp_path / "fibonacci-tree-visualizer-2026"


def test_ensure_layout_preserves_existing_project_process_shape(tmp_path):
    ensure_v4_project_layout(
        tmp_path,
        project_id="demo",
        title="Demo Project",
        goal="Build a demo.",
    )

    expected_dirs = [
        ".openclaw",
        "management",
        "management/tasks",
        "management/architecture",
        "management/validation",
        "src",
        "tests",
    ]
    for rel in expected_dirs:
        assert (tmp_path / rel).is_dir(), rel

    expected_files = [
        "PROJECT.md",
        "BRIEF.md",
        "RESULT.md",
        "DONE_REPORT.md",
        "BLOCKED_REPORT.md",
        ".openclaw/handoffs.jsonl",
    ]
    for rel in expected_files:
        assert (tmp_path / rel).is_file(), rel

    missing = validate_v4_project_layout(tmp_path, require_runtime_files=False)
    assert missing == []


def test_write_planning_files_creates_plan_and_task_docs(tmp_path):
    ensure_v4_project_layout(tmp_path, project_id="demo", title="Demo", goal="Goal")
    write_planning_files(
        tmp_path,
        [
            {"task_id": "T001", "title": "Implement main", "required_outputs": ["src/main.py"]},
            {
                "task_id": "T002",
                "title": "Add tests",
                "body": "# Task T002: Add tests\n\n## Objective\nWrite tests.\n",
            },
        ],
        title="Demo",
    )

    plan_text = (tmp_path / "management" / "PLAN.md").read_text(encoding="utf-8")
    assert "T001: Implement main" in plan_text
    assert "T002: Add tests" in plan_text

    task_1 = (tmp_path / "management" / "tasks" / "T001.md").read_text(encoding="utf-8")
    assert "# Task T001: Implement main" in task_1
    assert "- src/main.py" in task_1

    task_2 = (tmp_path / "management" / "tasks" / "T002.md").read_text(encoding="utf-8")
    assert task_2 == "# Task T002: Add tests\n\n## Objective\nWrite tests.\n"


def test_run_v4_project_creates_persistent_project_layout(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "AgenticTeam/scripts/run_v4_project.py",
            "--project-root",
            str(tmp_path),
            "--project-id",
            "demo-v4-project",
            "--title",
            "Demo V4 Project",
            "--goal",
            "Build a demo V4 project.",
            "--task",
            "T001|Create README|README.md",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-v4-project"
    assert f"V4_PROJECT_CREATED={project_dir}" in result.stdout
    assert (project_dir / "PROJECT.md").is_file()
    assert (project_dir / "PROJECT_STATE.md").is_file()
    assert (project_dir / "BRIEF.md").is_file()
    assert (project_dir / "CURRENT_TASK.md").is_file()
    assert (project_dir / ".openclaw" / "events.jsonl").is_file()
    assert (project_dir / ".openclaw" / "state.json").is_file()
    assert (project_dir / "management" / "PLAN.md").is_file()
    assert (project_dir / "management" / "BACKLOG.md").is_file()
    assert (project_dir / "management" / "tasks" / "T001.md").is_file()
    assert (project_dir / "management" / "architecture").is_dir()
    assert (project_dir / "management" / "validation").is_dir()
