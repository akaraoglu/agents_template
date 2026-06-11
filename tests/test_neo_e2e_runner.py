from pathlib import Path

from AgenticTeam.scripts.run_e2e_fibonacci_neo_test import (
    build_neo_fibonacci_request,
    validate_neo_e2e_project_structure,
)
from AgenticTeam.scripts.create_project import fibonacci_planned_tasks


def test_neo_fibonacci_request_uses_real_startup_path():
    request = build_neo_fibonacci_request(
        project_id="run-e2e-fibonacci-neo-test",
        title="Fibonacci Tree Visualizer",
        project_root=Path("/tmp/active-projects"),
        project_info="# Project: Fibonacci Tree Visualizer\n",
    )

    assert "Neo, start this as a real team project" in request
    assert "run-e2e-fibonacci-neo-test" in request
    assert "/home/alik/workspace/clawspace/bin/run_team.sh" in request
    assert "--background" in request
    assert "--fixture fibonacci_tree_visualizer" in request
    assert "TEAM_STARTED" in request
    assert "TEAM_LOG" in request
    assert "PROJECT_INFO_BEGIN" in request
    assert "# Project: Fibonacci Tree Visualizer" in request
    assert "new_project.sh" not in request
    assert "handoff.sh" not in request
    assert "sessions_send" not in request


def test_validate_neo_e2e_project_structure_requires_four_task_docs(tmp_path):
    project_dir = tmp_path / "project"
    tasks_dir = project_dir / "management" / "tasks"
    tasks_dir.mkdir(parents=True)
    (project_dir / ".openclaw").mkdir()
    (project_dir / ".openclaw" / "events.jsonl").write_text("", encoding="utf-8")
    for task_id in ("T001", "T002", "T003"):
        (tasks_dir / f"{task_id}.md").write_text("# task\n", encoding="utf-8")

    errors = validate_neo_e2e_project_structure(project_dir)

    assert "missing management/tasks/T004.md" in errors


def test_validate_neo_e2e_project_structure_accepts_four_task_docs(tmp_path):
    project_dir = tmp_path / "project"
    tasks_dir = project_dir / "management" / "tasks"
    tasks_dir.mkdir(parents=True)
    (project_dir / ".openclaw").mkdir()
    (project_dir / ".openclaw" / "events.jsonl").write_text("", encoding="utf-8")
    for task_id in ("T001", "T002", "T003", "T004"):
        (tasks_dir / f"{task_id}.md").write_text("# task\n", encoding="utf-8")

    assert validate_neo_e2e_project_structure(project_dir) == []


def test_fibonacci_fixture_tasks_include_outer_semantic_gate_requirements():
    tasks = {task["task_id"]: task for task in fibonacci_planned_tasks()}

    t001 = tasks["T001"]["body"]
    assert "named exactly `fibonacci`" in t001
    assert "`branches` must equal" in t001
    assert "branches == 5" in t001
    assert "max(1, int(round(fibonacci(level) * scale)))" in t001

    t002 = tasks["T002"]["body"]
    assert "Return a single string" in t002
    assert "visible `|` trunk" in t002
    assert "changing `scale` or `thickness` changes" in t002

    t004 = tasks["T004"]["body"]
    assert "nonempty_lines(text)" in t004
    assert "fibonacci(5) == 5" in t004
    assert "Import `fibonacci`, `generate_fibonacci_tree`, and `render_tree`" in t004
    assert "includes visible branch characters" in t004
    assert "do not import it from `src.main`" in t004
    assert "branches == 5" in t004
    assert "`src/main.py`" in t004
