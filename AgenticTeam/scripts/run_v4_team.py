#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from AgenticTeam.scripts.run_v4_project import DEFAULT_PROJECT_ROOT, fibonacci_planned_tasks, parse_task
from AgenticTeam.scripts.v4_contracts import (
    DEFAULT_PROTECTED_PATHS,
    DEFAULT_WRITABLE_PATHS,
    OracleResultV4,
    TaskPackV4,
    WorkResultV4,
)
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_leases import release_lease
from AgenticTeam.scripts.v4_openclaw_worker import V4OpenClawWorkerRunner
from AgenticTeam.scripts.v4_oracle import V4OracleRunner
from AgenticTeam.scripts.v4_project_layout import project_dir_for, validate_v4_project_layout
from AgenticTeam.scripts.v4_smith import (
    smith_accept_work_result,
    smith_dispatch_oracle,
    smith_dispatch_worker,
    smith_expand_allowed_artifacts_for_block,
    smith_handle_oracle_result,
    smith_plan_project,
    smith_record_scope_expansion,
)
from AgenticTeam.scripts.v4_state import project_state_from_events
from AgenticTeam.scripts.v4_worker import V4WorkerRunner


DEFAULT_EXPECTED_ARTIFACTS = ["README.md", "src/main.py", "tests/test_main.py"]


def read_goal(args: argparse.Namespace) -> str:
    if args.project_file:
        return Path(args.project_file).expanduser().resolve().read_text(encoding="utf-8")
    return args.goal or args.title


def default_project_task(goal: str) -> list[dict[str, Any]]:
    body = f"""# Task T001: Implement the approved project goal

## Objective
Implement the project described in `PROJECT.md`.

## Project Goal
{goal.strip()}

## Required Behavior
1. Read `PROJECT.md` before editing.
2. Design the task locally before writing code.
3. Implement the smallest complete Python solution that satisfies the acceptance criteria.
4. Add tests that prove the acceptance criteria.
5. Run the tests with `tests_run`.
6. Submit `DONE` only after the implementation and tests are complete. Submit `BLOCKED` with an exact reason if the task cannot be completed inside the writable project scope.

## Required Outputs
- `README.md`
- `src/main.py`
- `tests/test_main.py`
"""
    return [
        {
            "task_id": "T001",
            "title": "Implement the approved project goal",
            "body": body,
            "required_outputs": list(DEFAULT_EXPECTED_ARTIFACTS),
        }
    ]


def planned_tasks_for(args: argparse.Namespace, goal: str) -> list[dict[str, Any]]:
    if args.fixture == "fibonacci_tree_visualizer":
        return fibonacci_planned_tasks()
    if args.task:
        tasks = list(args.task)
        for task in tasks:
            task.setdefault("required_outputs", list(DEFAULT_EXPECTED_ARTIFACTS))
        return tasks
    return default_project_task(goal)


def known_project_artifacts(planned_tasks: list[dict[str, Any]]) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()
    for task in planned_tasks:
        for path in task.get("required_outputs", []):
            if path not in seen:
                artifacts.append(path)
                seen.add(path)
    return artifacts


def latest_worker_block_reason(task_id: str) -> str:
    for event in reversed(read_events_v4()):
        if event.event_type == "work_blocked" and event.payload.get("task_id") == task_id:
            return str(event.payload.get("reason", ""))
    return ""


def latest_submitted_work(task_id: str):
    for event in reversed(read_events_v4()):
        if event.event_type == "work_submitted" and event.payload.get("task_id") == task_id:
            return event
    return None


def latest_oracle_report(events: list):
    for event in reversed(events):
        if event.event_type in ("oracle_passed", "oracle_failed"):
            return event
    return None


def latest_oracle_repair_task_id() -> str | None:
    for event in reversed(read_events_v4()):
        if event.event_type != "task_planned":
            continue
        task_id = event.payload.get("task_id")
        title = str(event.payload.get("title", ""))
        if task_id and title.startswith("Repair project based on Oracle failure"):
            return str(task_id)
    return None


def validate_fibonacci_fixture_artifacts(workspace_root: Path) -> list[str]:
    """Deterministic artifact gate for the Fibonacci E2E fixture, excluding final state."""
    errors: list[str] = []
    src_main = workspace_root / "src" / "main.py"
    tests_main = workspace_root / "tests" / "test_main.py"

    if src_main.exists():
        source_text = src_main.read_text(encoding="utf-8")
        for function_name in ("fibonacci", "generate_fibonacci_tree", "render_tree"):
            count = source_text.count(f"def {function_name}(")
            if count != 1:
                errors.append(f"src/main.py defines {function_name} {count} times, expected exactly once")
        if "def nonempty_lines(" in source_text:
            errors.append("test helper nonempty_lines leaked into src/main.py; keep test helpers in tests/test_main.py")
    else:
        errors.append("missing src/main.py")

    if tests_main.exists():
        test_text = tests_main.read_text(encoding="utf-8")
        if "def nonempty_lines(" not in test_text:
            errors.append("tests/test_main.py must define its own nonempty_lines helper")
        if "from main import" in test_text and not imports_name(test_text, "from main import", "fibonacci"):
            errors.append("tests/test_main.py must import and test the public fibonacci function")
        if "from src.main import" in test_text and not imports_name(test_text, "from src.main import", "fibonacci"):
            errors.append("tests/test_main.py must import and test the public fibonacci function")
        if "nonempty_lines" in test_text.split("from src.main import", 1)[-1].splitlines()[0]:
            errors.append("tests/test_main.py must not import nonempty_lines from src.main")
    else:
        errors.append("missing tests/test_main.py")

    env = os.environ.copy()
    workspace = str(workspace_root)
    env["PYTHONPATH"] = f"{workspace}:{workspace}/src:" + env.get("PYTHONPATH", "")
    semantic_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.main import fibonacci, generate_fibonacci_tree; "
                "assert fibonacci(5) == 5, fibonacci(5); "
                "layers = generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2); "
                "assert isinstance(layers, list), type(layers); "
                "assert len(layers) == 5, len(layers); "
                "assert layers[-1].get('branches') == 5, layers[-1]; "
                "assert layers[-1].get('angle') == 42, layers[-1]; "
                "assert layers[-1].get('thickness') == 2, layers[-1]; "
                "assert 'left' not in layers[0] and 'right' not in layers[0], layers[0]"
            ),
        ],
        cwd=str(workspace_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if semantic_probe.returncode != 0:
        errors.append(f"branch-layer model semantic probe failed: {semantic_probe.stderr or semantic_probe.stdout}")

    return errors


def fixture_acceptance_errors(workspace_root: Path, fixture: str | None) -> list[str]:
    if fixture == "fibonacci_tree_visualizer":
        return validate_fibonacci_fixture_artifacts(workspace_root)
    return []


def imports_name(source_text: str, import_prefix: str, name: str) -> bool:
    imported = source_text.split(import_prefix, 1)[-1].splitlines()[0]
    names = [part.strip().split(" as ", 1)[0].strip() for part in imported.split(",")]
    return name in names


def write_dry_run_artifacts(workspace_root: Path, expected_artifacts: list[str]) -> None:
    for relative in expected_artifacts:
        target = workspace_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        if relative.endswith(".py"):
            if target.name.startswith("test_"):
                target.write_text("def test_v4_dry_run_placeholder():\n    assert True\n", encoding="utf-8")
            else:
                target.write_text('"""V4 dry-run implementation placeholder."""\n', encoding="utf-8")
        else:
            target.write_text(f"# {relative}\n\nGenerated by V4 dry-run.\n", encoding="utf-8")


def run_worker_task(
    *,
    workspace_root: Path,
    project_id: str,
    task_id: str,
    title: str,
    expected_artifacts: list[str],
    project_artifacts: list[str],
    dry_run: bool,
    max_attempts: int,
    worker_backend: str,
    worker_timeout_seconds: int,
) -> bool:
    print(f"\n--- Smith dispatching {task_id}: {title} ---")
    current_expected = list(expected_artifacts)

    for attempt in range(1, max_attempts + 1):
        lease = smith_dispatch_worker(str(workspace_root), task_id, "morpheus")
        if not lease:
            print(f"ERROR: Smith could not acquire a Morpheus lease for {task_id}")
            return False

        if dry_run:
            write_dry_run_artifacts(workspace_root, current_expected)
            result = WorkResultV4(
                task_id=task_id,
                attempt_id=lease.metadata["attempt_id"],
                status="DONE",
                summary=f"Dry-run completed {task_id}.",
                output={"artifacts": current_expected},
                evidence={"dry_run": True},
            )
            smith_accept_work_result(str(workspace_root), result, lease.lease_id, "morpheus")
            return True

        task_pack = TaskPackV4(
            project_id=project_id,
            task_id=task_id,
            workspace_root=str(workspace_root),
            expected_artifacts=lease.metadata.get("expected_artifacts") or current_expected,
            writable_paths=lease.metadata.get("writable_paths") or list(DEFAULT_WRITABLE_PATHS),
            protected_paths=lease.metadata.get("protected_paths") or list(DEFAULT_PROTECTED_PATHS),
            allowed_artifacts=lease.metadata.get("expected_artifacts") or current_expected,
        )
        if worker_backend == "direct":
            runner = V4WorkerRunner(task_pack, lease, actor="morpheus")
            runner_result = runner.run(max_turns=35)
        else:
            runner = V4OpenClawWorkerRunner(
                task_pack,
                lease,
                actor="morpheus",
                timeout_seconds=worker_timeout_seconds,
            )
            runner_result = runner.run()
        print(f"Morpheus result for {task_id}: {runner_result}")

        state = project_state_from_events(read_events_v4())
        task_status = state.tasks.get(task_id, {}).get("status")
        if task_status in ("BLOCKED", "FAILED"):
            reason = latest_worker_block_reason(task_id)
            release_lease(str(workspace_root), lease.lease_id)
            expanded = smith_expand_allowed_artifacts_for_block(current_expected, reason, project_artifacts)
            if expanded and expanded != current_expected and attempt < max_attempts:
                smith_record_scope_expansion(str(workspace_root), task_id, current_expected, expanded, reason)
                current_expected = expanded
                print(f"Smith expanded {task_id} scope after repairable block: {expanded}")
                continue
            print(f"ERROR: {task_id} was {task_status}. Reason: {reason}")
            return False

        submitted = latest_submitted_work(task_id)
        if submitted is None:
            if attempt < max_attempts:
                release_lease(str(workspace_root), lease.lease_id)
                print(f"Smith retrying {task_id}; Morpheus returned no WorkResult.")
                continue
            blocked_result = WorkResultV4(
                task_id=task_id,
                attempt_id=lease.metadata["attempt_id"],
                status="BLOCKED",
                summary=f"Morpheus returned no WorkResult for {task_id}.",
                output={},
                evidence={"runner_result": runner_result},
                repair_reason=f"Morpheus returned no WorkResult for {task_id}: {runner_result}",
            )
            smith_accept_work_result(str(workspace_root), blocked_result, lease.lease_id, "morpheus")
            print(f"ERROR: Morpheus did not submit a WorkResult for {task_id}.")
            return False

        work_result = WorkResultV4(
            task_id=submitted.payload["task_id"],
            attempt_id=submitted.payload["attempt_id"],
            status=submitted.payload["status"],
            summary=submitted.payload["summary"],
            output=submitted.payload["output"],
            evidence=submitted.payload["evidence"],
        )
        smith_accept_work_result(str(workspace_root), work_result, lease.lease_id, "morpheus")
        return True

    return False


def run_oracle_cycle(workspace_root: Path, project_id: str, dry_run: bool, fixture: str | None = None) -> str | None:
    print("\n--- Smith dispatching Oracle final verification ---")
    event_count_before_dispatch = len(read_events_v4())
    lease = smith_dispatch_oracle(str(workspace_root), "oracle")
    if not lease:
        print("ERROR: Smith could not acquire an Oracle lease.")
        return None

    if dry_run:
        oracle_result = OracleResultV4(
            project_id=project_id,
            task_id="none",
            status="PASS",
            evidence_paths=["PROJECT.md", "README.md"],
            summary="Dry-run project verification passed.",
        )
        smith_handle_oracle_result(str(workspace_root), oracle_result, lease.lease_id, "oracle")
        return "PASS"

    runner = V4OracleRunner(str(workspace_root), lease, actor="oracle")
    runner_result = runner.run(max_turns=25)
    print(f"Oracle result: {runner_result}")

    oracle_event = latest_oracle_report(read_events_v4()[event_count_before_dispatch:])
    if oracle_event is None:
        release_lease(str(workspace_root), lease.lease_id)
        print("ERROR: Oracle did not submit a report.")
        return None

    status = "PASS" if oracle_event.event_type == "oracle_passed" else "FAIL"
    oracle_result = OracleResultV4(
        project_id=project_id,
        task_id="none",
        status=status,
        evidence_paths=oracle_event.payload.get("evidence_paths", []),
        summary=oracle_event.payload.get("summary", ""),
    )
    if status == "PASS":
        gate_errors = fixture_acceptance_errors(workspace_root, fixture)
        if gate_errors:
            status = "FAIL"
            oracle_result = OracleResultV4(
                project_id=project_id,
                task_id="none",
                status="FAIL",
                evidence_paths=["src/main.py", "tests/test_main.py"],
                summary="Deterministic fixture gate failed:\n- " + "\n- ".join(gate_errors),
            )
    smith_handle_oracle_result(str(workspace_root), oracle_result, lease.lease_id, "oracle")
    return status


def run_host_tests_if_present(workspace_root: Path) -> bool:
    test_path = workspace_root / "tests" / "test_main.py"
    if not test_path.exists():
        return True

    env = os.environ.copy()
    workspace = str(workspace_root)
    env["PYTHONPATH"] = f"{workspace}:{workspace}/src:" + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_main.py"],
        cwd=str(workspace_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERROR: final host tests failed")
        print(result.stdout)
        print(result.stderr)
        return False
    return True


def validate_done_state(workspace_root: Path) -> list[str]:
    errors: list[str] = []
    state_path = workspace_root / ".openclaw" / "state.json"
    if not state_path.exists():
        return ["missing .openclaw/state.json"]
    state = project_state_from_events(read_events_v4())
    if state.phase != "DONE":
        errors.append(f"final phase is {state.phase!r}, expected DONE")
    if state.waiting_for != "none":
        errors.append(f"waiting_for is {state.waiting_for!r}, expected none")
    return errors


def project_id_for(args: argparse.Namespace) -> str:
    if args.project_id:
        return args.project_id
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{args.title}-{stamp}"


def run_v4_team(args: argparse.Namespace) -> int:
    goal = read_goal(args)
    project_id = project_id_for(args)
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = project_dir_for(project_root, project_id)
    if workspace_root.exists():
        print(f"ERROR: project already exists: {workspace_root}", file=sys.stderr)
        return 2

    workspace_root.mkdir(parents=True)
    os.environ["V4_EVENT_FILE"] = str(workspace_root / ".openclaw" / "events.jsonl")
    clear_events_v4()

    if args.project_file:
        shutil.copy(Path(args.project_file).expanduser().resolve(), workspace_root / "PROJECT.md")

    planned_tasks = planned_tasks_for(args, goal)
    smith_plan_project(str(workspace_root), project_id, args.title, planned_tasks, goal=goal)
    missing = validate_v4_project_layout(workspace_root, require_runtime_files=False)
    if missing:
        print(f"ERROR: V4 project layout is incomplete: {missing}", file=sys.stderr)
        return 1

    print(f"V4_PROJECT_CREATED={workspace_root}")
    print(f"PROJECT_ID={project_id}")

    project_artifacts = known_project_artifacts(planned_tasks)
    for task in planned_tasks:
        if not run_worker_task(
            workspace_root=workspace_root,
            project_id=project_id,
            task_id=str(task["task_id"]),
            title=str(task["title"]),
            expected_artifacts=list(task.get("required_outputs", DEFAULT_EXPECTED_ARTIFACTS)),
            project_artifacts=project_artifacts,
            dry_run=args.dry_run,
            max_attempts=args.worker_attempts,
            worker_backend=args.worker_backend,
            worker_timeout_seconds=args.worker_timeout_seconds,
        ):
            print("V4_TEAM_RESULT=BLOCKED")
            return 1

    for oracle_attempt in range(1, args.oracle_attempts + 1):
        status = run_oracle_cycle(workspace_root, project_id, args.dry_run, args.fixture)
        if status == "PASS":
            break
        if status is None or oracle_attempt >= args.oracle_attempts:
            print("V4_TEAM_RESULT=BLOCKED")
            return 1

        repair_task_id = latest_oracle_repair_task_id()
        if not repair_task_id:
            print("ERROR: Oracle failed but Smith did not create a repair task.")
            print("V4_TEAM_RESULT=BLOCKED")
            return 1
        state = project_state_from_events(read_events_v4())
        repair_title = state.tasks.get(repair_task_id, {}).get("title", "Repair Oracle failure")
        if not run_worker_task(
            workspace_root=workspace_root,
            project_id=project_id,
            task_id=repair_task_id,
            title=repair_title,
            expected_artifacts=project_artifacts,
            project_artifacts=project_artifacts,
            dry_run=args.dry_run,
            max_attempts=args.worker_attempts,
            worker_backend=args.worker_backend,
            worker_timeout_seconds=args.worker_timeout_seconds,
        ):
            print("V4_TEAM_RESULT=BLOCKED")
            return 1

    if not run_host_tests_if_present(workspace_root):
        print("V4_TEAM_RESULT=BLOCKED")
        return 1

    errors = validate_done_state(workspace_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("V4_TEAM_RESULT=BLOCKED")
        return 1

    print("V4_TEAM_RESULT=DONE")
    print(f"FINAL_PROJECT_PATH={workspace_root}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the V4 Neo -> Smith -> Morpheus -> Oracle project loop.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="Directory that contains active projects.")
    parser.add_argument("--project-id", help="Project id / directory slug. Defaults to a slug from the title and timestamp.")
    parser.add_argument("--title", default="V4 Project", help="Human-readable project title.")
    parser.add_argument("--goal", help="Project goal text.")
    parser.add_argument("--project-file", help="Existing markdown file to use as PROJECT.md content.")
    parser.add_argument("--fixture", choices=["fibonacci_tree_visualizer"], help="Use a known V4 fixture plan.")
    parser.add_argument("--task", action="append", type=parse_task, help="Task as 'T001|Task title|optional/output,path'. Repeatable.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate Morpheus and Oracle results without calling the local model.")
    parser.add_argument(
        "--worker-backend",
        choices=["openclaw", "direct"],
        default="openclaw",
        help="Use real OpenClaw agent turns for workers by default; direct is a debug-only raw Ollama runner.",
    )
    parser.add_argument("--worker-timeout-seconds", type=int, default=600)
    parser.add_argument("--worker-attempts", type=int, default=3)
    parser.add_argument("--oracle-attempts", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    return run_v4_team(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
