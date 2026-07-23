import json
import sys
from pathlib import Path

import pytest

from codexteam_tools.close_loop import (
    VerificationFailure,
    execute_close_loop,
    main,
    prepare_close_loop,
)
from codexteam_tools.project_init import initialize_project
from codexteam_tools.tasks import parse_task_document, update_task_document


def project_with_result(
    tmp_path: Path,
    result_factory,
    *,
    task_id: str = "T001",
    tasks: tuple[str, ...] = ("T001", "T002", "T003", "T004"),
) -> Path:
    project = initialize_project(
        "Example",
        "Deliver an example.",
        root=tmp_path,
        project_id=f"project-{task_id.lower()}",
        tasks=tasks,
    ).project_dir
    (project / "src" / "main.py").write_text("VALUE = 1\n")
    (project / "results" / "evidence.txt").write_text("passed\n")
    result = result_factory(task_id=task_id)
    (project / "results" / f"{task_id}-20260715T000000Z.json").write_text(json.dumps(result))
    return project


def test_close_loop_updates_task_and_project_state(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    original_brief = (project / "BRIEF.md").read_text()
    plan, result, tasks_text = prepare_close_loop(project, "T001", [sys.executable, "-c", "print('verified')"])
    assert execute_close_loop(plan, result, tasks_text, timeout_seconds=10)
    row = parse_task_document((project / "TASKS.md").read_text()).row("T001")
    assert row.status == "Completed"
    assert "T001-20260715T000000Z.json" in row.evidence
    tasks = parse_task_document((project / "TASKS.md").read_text())
    assert tasks.row("T002").status == "In Progress"
    assert "Active Task: T002" in (project / "PROJECT_STATE.md").read_text()
    current_task = (project / "CURRENT_TASK.md").read_text()
    assert "Task ID: T002" in current_task
    assert "Status: In Progress" in current_task
    brief = (project / "BRIEF.md").read_text()
    assert "- Phase: implementation" in brief
    assert "- Active task: `T002` — Design the code and project architecture" in brief
    assert "- Responsible AI: `architect-01`" in brief
    assert "`T001` independently verified" in brief
    assert "`results/T001-20260715T000000Z.json`" in brief
    assert "`results/T001-verification.txt`" in brief
    assert "execute `management/tasks/T002.md` as `architect-01`" in brief
    assert "## Authority Order" in brief
    assert original_brief.split("## Authority Order", 1)[1].split("## Team Responsibilities", 1)[0] in brief
    assert (project / "results" / "T001-verification.txt").is_file()


def test_close_loop_is_idempotent(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    command = [sys.executable, "-c", "print('verified')"]
    plan, result, tasks_text = prepare_close_loop(project, "T001", command)
    execute_close_loop(plan, result, tasks_text, timeout_seconds=10)
    snapshot = (project / "TASKS.md").read_text()
    plan, result, tasks_text = prepare_close_loop(project, "T001", command)
    assert not execute_close_loop(plan, result, tasks_text, timeout_seconds=10)
    assert (project / "TASKS.md").read_text() == snapshot


def test_failed_verification_does_not_update_task(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    original = (project / "TASKS.md").read_text()
    plan, result, tasks_text = prepare_close_loop(project, "T001", [sys.executable, "-c", "raise SystemExit(9)"])
    with pytest.raises(VerificationFailure):
        execute_close_loop(plan, result, tasks_text, timeout_seconds=10)
    assert (project / "TASKS.md").read_text() == original


def test_missing_declared_artifact_blocks_closure(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    (project / "results" / "evidence.txt").unlink()
    with pytest.raises(FileNotFoundError, match="does not exist"):
        prepare_close_loop(project, "T001", [sys.executable, "-c", "print('ok')"])


def test_verification_command_rejects_pipe_tokens(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    with pytest.raises(ValueError, match="cannot contain pipes"):
        prepare_close_loop(project, "T001", ["pytest", "|", "tee", "output.txt"])


def test_close_loop_cli_accepts_documented_argument_order(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    code = main([
        str(project),
        "--task",
        "T001",
        "--dry-run",
        "--",
        sys.executable,
        "-c",
        "print('verified')",
    ])
    assert code == 0
    assert parse_task_document((project / "TASKS.md").read_text()).row("T001").status == "In Progress"


def test_close_loop_can_select_explicit_result_among_multiple_attempts(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory)
    invalid = result_factory(task_id="T001")
    invalid["evidence"][0]["type"] = "unsupported_type"
    (project / "results" / "T001-att-invalid.json").write_text(json.dumps(invalid))

    plan, result, _ = prepare_close_loop(
        project,
        "T001",
        [sys.executable, "-c", "print('verified')"],
        result_value="results/T001-20260715T000000Z.json",
    )

    assert plan.result_path.name == "T001-20260715T000000Z.json"
    assert result["status"] == "completed"


def test_last_task_generates_delivery(tmp_path: Path, result_factory):
    project = project_with_result(tmp_path, result_factory, task_id="T004")
    tasks = (project / "TASKS.md").read_text()
    for task_id in ("T001", "T002", "T003"):
        tasks = update_task_document(
            tasks,
            task_id,
            status="Completed",
            verification="Passed",
            evidence="`results/prior.json`",
        )
    (project / "TASKS.md").write_text(tasks)
    plan, result, tasks_text = prepare_close_loop(project, "T004", [sys.executable, "-c", "print('verified')"])
    execute_close_loop(plan, result, tasks_text, timeout_seconds=10)
    assert (project / "DELIVERY.md").is_file()
    assert "Status: DELIVERED" in (project / "PROJECT_STATE.md").read_text()
    brief = (project / "BRIEF.md").read_text()
    assert "- Phase: delivery complete" in brief
    assert "- Active task: None" in brief
    assert "- Responsible AI: None" in brief
    assert "delivery complete after `T004` was independently verified" in brief
    assert "`results/T004-20260715T000000Z.json`" in brief
    assert "`results/T004-verification.txt`" in brief
    assert (
        "- Next handoff: None; review `DONE_REPORT.md`, `RESULT.md`, and "
        "`results/T004-verification.txt` for delivery evidence."
    ) in brief


def test_default_t005_reviewer_is_activated_instead_of_delivering_after_t004(
    tmp_path: Path, result_factory
):
    project = project_with_result(
        tmp_path,
        result_factory,
        task_id="T004",
        tasks=("T001", "T002", "T003", "T004", "T005"),
    )
    tasks_text = (project / "TASKS.md").read_text()
    for task_id in ("T001", "T002", "T003"):
        tasks_text = update_task_document(
            tasks_text,
            task_id,
            status="Completed",
            verification="Passed",
            evidence="`results/prior.json`",
        )
    (project / "TASKS.md").write_text(tasks_text)

    plan, result, tasks_text = prepare_close_loop(
        project,
        "T004",
        [sys.executable, "-c", "print('verified')"],
    )
    execute_close_loop(plan, result, tasks_text, timeout_seconds=10)

    document = parse_task_document((project / "TASKS.md").read_text())
    assert document.row("T005").status == "In Progress"
    assert document.row("T005").owner == "reviewer-01"
    current_task = (project / "CURRENT_TASK.md").read_text()
    assert "Task ID: T005" in current_task
    assert "Status: In Progress" in current_task
    assert not (project / "DELIVERY.md").exists()
