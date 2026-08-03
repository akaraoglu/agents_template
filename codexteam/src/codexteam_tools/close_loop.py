from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from .contracts import ResultValidationError, utc_now, validate_result
from .files import atomic_write_text
from .paths import contained_path, ensure_existing_workspace, normalize_task_id, safe_relative_path
from .spawn import ProcessResult, run_process
from .tasks import TaskDocumentError, parse_task_document, update_task_document
from .lead_tracking import set_pending_transition


@dataclass(frozen=True)
class CloseLoopPlan:
    project: Path
    task_id: str
    result_path: Path
    command: tuple[str, ...]
    deliverables: tuple[Path, ...]


def prepare_close_loop(
    project_value: str | Path,
    task_value: str,
    command: list[str],
    *,
    deliverables: list[str] | None = None,
    result_value: str | None = None,
) -> tuple[CloseLoopPlan, dict, str]:
    project = ensure_existing_workspace(project_value)
    task_id = normalize_task_id(task_value)
    if not command:
        raise ValueError("an independent verification command is required after '--'")
    if any("|" in argument or "\n" in argument or "\r" in argument for argument in command):
        raise ValueError("verification command arguments cannot contain pipes or newlines")

    tasks_path = contained_path(project, "TASKS.md", label="task ledger")
    tasks_text = tasks_path.read_text(encoding="utf-8")
    parse_task_document(tasks_text).row(task_id)
    result_path = _requested_result(project, result_value) if result_value else _latest_result(project, task_id)
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid result JSON: {result_path}: {exc}") from exc
    validate_result(result, expected_task=task_id, expected_status="completed")

    paths: list[Path] = []
    requested = list(deliverables or [])
    requested.extend(
        item["path"]
        for item in result["file_changes"]
        if item["action"] in {"created", "modified"}
    )
    requested.extend(item["artifact_ref"] for item in result["evidence"])
    for relative in dict.fromkeys(requested):
        safe_relative_path(relative, label="deliverable")
        path = contained_path(project, relative, label="deliverable")
        if not path.exists():
            raise FileNotFoundError(f"declared deliverable does not exist: {relative}")
        paths.append(path)

    return (
        CloseLoopPlan(project, task_id, result_path, tuple(command), tuple(paths)),
        result,
        tasks_text,
    )


def execute_close_loop(
    plan: CloseLoopPlan,
    result: dict,
    tasks_text: str,
    *,
    timeout_seconds: int,
    force: bool = False,
) -> bool:
    tasks_document = parse_task_document(tasks_text)
    current = tasks_document.row(plan.task_id)
    result_reference = plan.result_path.relative_to(plan.project).as_posix()
    if not force and current.status == "Completed" and result_reference in current.evidence:
        return False

    process = run_process(
        list(plan.command),
        prompt="",
        timeout_seconds=timeout_seconds,
        env=os.environ.copy(),
        cwd=plan.project,
    )
    if process.timed_out:
        raise VerificationFailure(f"verification timed out after {timeout_seconds} seconds", process)
    if process.exit_code != 0:
        raise VerificationFailure(f"verification exited with code {process.exit_code}", process)

    timestamp = utc_now()
    verification_relative = f"results/{plan.task_id}-verification.txt"
    verification_path = contained_path(plan.project, verification_relative, label="verification artifact")
    command_text = shlex.join(plan.command)
    verification_content = (
        f"Command: {command_text}\n"
        f"Exit code: {process.exit_code}\n"
        f"Duration seconds: {process.duration_seconds:.3f}\n"
        f"Verified at: {timestamp}\n\n"
        f"STDOUT\n{process.stdout}\n\nSTDERR\n{process.stderr}\n"
    )
    evidence_cell = f"`{result_reference}`, `{verification_relative}`"
    verification_cell = f"Passed independently: {plan.command[0]}"
    updated_tasks = update_task_document(
        tasks_text,
        plan.task_id,
        status="Completed",
        verification=verification_cell,
        evidence=evidence_cell,
        history=f"{timestamp}: {plan.task_id} independently verified with {result_reference}.",
    )
    updated_document = parse_task_document(updated_tasks)
    remaining = [row for row in updated_document.rows if row.status != "Completed"]
    next_task = remaining[0].task_id if remaining else None
    set_pending_transition(plan.project, plan.task_id, next_task)
    if remaining and remaining[0].status != "In Progress":
        updated_tasks = update_task_document(
            updated_tasks,
            remaining[0].task_id,
            status="In Progress",
        )
        updated_document = parse_task_document(updated_tasks)
        remaining = [row for row in updated_document.rows if row.status != "Completed"]
    all_done = not remaining

    project_state_path = contained_path(plan.project, "PROJECT_STATE.md", label="project state")
    current_task_path = contained_path(plan.project, "CURRENT_TASK.md", label="current task")
    result_report_path = contained_path(plan.project, "RESULT.md", label="result report")
    brief_path = contained_path(plan.project, "BRIEF.md", label="team brief")
    project_state = project_state_path.read_text(encoding="utf-8")
    current_task = current_task_path.read_text(encoding="utf-8")
    result_report = result_report_path.read_text(encoding="utf-8")
    brief = brief_path.read_text(encoding="utf-8")

    if all_done:
        state_values = {
            "Phase": "DELIVERY",
            "Status": "DELIVERED",
            "Active Task": "None",
            "Last Verified Task": plan.task_id,
            "Next Action": "Project delivery is complete.",
            "Updated At": timestamp,
        }
        task_values = {
            "Task ID": "None",
            "Status": "Completed",
            "Responsible AI": "None",
            "Objective": "All planned tasks are complete.",
            "Handoff": "None",
            "Next Action": "Review DONE_REPORT.md and RESULT.md.",
        }
        brief_values = {
            "Phase": "delivery complete",
            "Active task": "None",
            "Responsible AI": "None",
            "Last verified outcome": (
                f"delivery complete after `{plan.task_id}` was independently verified with "
                f"`{result_reference}` and `{verification_relative}`"
            ),
            "Next handoff": (
                f"None; review `DONE_REPORT.md`, `RESULT.md`, and `{verification_relative}` "
                "for delivery evidence."
            ),
        }
    else:
        next_row = remaining[0]
        state_values = {
            "Phase": "IMPLEMENTATION",
            "Status": "ACTIVE",
            "Active Task": next_row.task_id,
            "Last Verified Task": plan.task_id,
            "Next Action": f"Execute {next_row.task_id}: {next_row.description}.",
            "Updated At": timestamp,
        }
        task_values = {
            "Task ID": next_row.task_id,
            "Status": next_row.status,
            "Responsible AI": next_row.owner,
            "Objective": next_row.description,
            "Handoff": f"`management/tasks/{next_row.task_id}.md`",
            "Next Action": "Read the handoff and satisfy its completion criteria.",
        }
        brief_values = {
            "Phase": "implementation",
            "Active task": f"`{next_row.task_id}` — {next_row.description}",
            "Responsible AI": f"`{next_row.owner}`",
            "Last verified outcome": (
                f"`{plan.task_id}` independently verified with `{result_reference}` and "
                f"`{verification_relative}`"
            ),
            "Next handoff": f"execute `management/tasks/{next_row.task_id}.md` as `{next_row.owner}`.",
        }

    updated_state = update_bullets(project_state, state_values)
    updated_current = update_bullets(current_task, task_values)
    updated_brief = update_bullets(brief, brief_values)
    result_marker = f"## {plan.task_id} Verification ({result_reference})"
    if result_marker not in result_report:
        result_report = result_report.rstrip() + (
            f"\n\n{result_marker}\n\n"
            f"- Status: Passed\n"
            f"- Command: `{command_text}`\n"
            f"- Result: `{result_reference}`\n"
            f"- Verification output: `{verification_relative}`\n"
            f"- Verified At: {timestamp}\n"
        )

    atomic_write_text(verification_path, verification_content)
    atomic_write_text(contained_path(plan.project, "TASKS.md", label="task ledger"), updated_tasks)
    atomic_write_text(project_state_path, updated_state)
    atomic_write_text(current_task_path, updated_current)
    atomic_write_text(brief_path, updated_brief)
    atomic_write_text(result_report_path, result_report)

    if all_done:
        _write_delivery_reports(plan.project, updated_document, timestamp)
    return True


class VerificationFailure(RuntimeError):
    def __init__(self, message: str, process: ProcessResult):
        super().__init__(message)
        self.process = process


def update_bullets(text: str, values: dict[str, str]) -> str:
    lines = text.splitlines()
    updated: list[str] = []
    found: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        replacement = None
        for key, value in values.items():
            if line.startswith(f"- {key}:"):
                replacement = f"- {key}: {value}"
                found.add(key)
                break
        updated.append(replacement if replacement is not None else line)
        index += 1
        if replacement is not None:
            while index < len(lines) and lines[index].startswith(("  ", "\t")):
                index += 1
    missing = [key for key in values if key not in found]
    if missing:
        if updated and updated[-1].strip():
            updated.append("")
        updated.extend(f"- {key}: {values[key]}" for key in missing)
    return "\n".join(updated).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and atomically close one CodexTeam task.",
        epilog="Place the independent verification command after '--'.",
    )
    parser.add_argument("project", help="Project workspace")
    parser.add_argument("--task", required=True)
    parser.add_argument(
        "--result",
        help="Explicit project-relative result JSON (recommended when a task has multiple attempts)",
    )
    parser.add_argument("--deliverable", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-run verification for an already closed task")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw_arguments:
        separator = raw_arguments.index("--")
        parser_arguments = raw_arguments[:separator]
        command = raw_arguments[separator + 1:]
    else:
        parser_arguments = raw_arguments
        command = []
    args = build_parser().parse_args(parser_arguments)
    try:
        plan, result, tasks_text = prepare_close_loop(
            args.project,
            args.task,
            command,
            deliverables=args.deliverable,
            result_value=args.result,
        )
    except (FileNotFoundError, OSError, ResultValidationError, TaskDocumentError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.dry_run:
        print(json.dumps({
            "project": str(plan.project),
            "task_id": plan.task_id,
            "result": str(plan.result_path),
            "command": list(plan.command),
            "deliverables": [str(path) for path in plan.deliverables],
        }, indent=2))
        return 0

    try:
        changed = execute_close_loop(plan, result, tasks_text, timeout_seconds=args.timeout, force=args.force)
    except VerificationFailure as exc:
        print(f"VERIFICATION FAILED: {exc}")
        if exc.process.stdout:
            print(exc.process.stdout[-2_000:])
        if exc.process.stderr:
            print(exc.process.stderr[-2_000:])
        return 2
    except (OSError, TaskDocumentError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"{'Closed' if changed else 'Already closed'}: {plan.task_id}")
    return 0


def _latest_result(project: Path, task_id: str) -> Path:
    results = contained_path(project, "results", label="results directory")
    if not results.is_dir():
        raise FileNotFoundError(f"results directory not found: {results}")
    candidates = sorted(results.glob(f"{task_id}-*.json"))
    if not candidates:
        raise FileNotFoundError(f"no result JSON found for {task_id}")
    candidate = candidates[-1].resolve(strict=True)
    try:
        candidate.relative_to(project)
    except ValueError as exc:
        raise ValueError(f"result path escapes project root: {candidate}") from exc
    return candidate


def _requested_result(project: Path, result_value: str) -> Path:
    relative = safe_relative_path(result_value, label="result")
    if not relative.parts or relative.parts[0] != "results" or relative.suffix != ".json":
        raise ValueError("explicit result must be a JSON file under results/")
    candidate = contained_path(project, result_value, label="result")
    if not candidate.is_file():
        raise FileNotFoundError(f"result JSON not found: {result_value}")
    return candidate.resolve(strict=True)


def _write_delivery_reports(project: Path, document, timestamp: str) -> None:
    completed = [row.task_id for row in document.rows if row.status == "Completed"]
    rows = "\n".join(f"| {row.task_id} | {row.verification} | {row.evidence} |" for row in document.rows)
    done_report = (
        "# Done Report\n\n"
        f"- Status: Delivered\n- Delivered At: {timestamp}\n"
        f"- Completed Tasks: {', '.join(completed)}\n\n"
        "See `RESULT.md` for commands and evidence. Known limitations remain those "
        "recorded in the accepted result files.\n"
    )
    delivery = (
        "# Delivery\n\n"
        f"- Status: DELIVERED\n- Generated At: {timestamp}\n\n"
        "| Task | Verification | Evidence |\n|------|--------------|----------|\n"
        f"{rows}\n"
    )
    atomic_write_text(contained_path(project, "DONE_REPORT.md", label="done report"), done_report)
    atomic_write_text(contained_path(project, "DELIVERY.md", label="delivery report"), delivery)


if __name__ == "__main__":
    raise SystemExit(main())
