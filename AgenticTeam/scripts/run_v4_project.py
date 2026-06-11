#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from AgenticTeam.scripts.v4_events import clear_events_v4
from AgenticTeam.scripts.v4_project_layout import project_dir_for, validate_v4_project_layout
from AgenticTeam.scripts.v4_smith import smith_plan_project


DEFAULT_PROJECT_ROOT = Path("/home/alik/workspace/clawspace/projects/active")


def fibonacci_planned_tasks() -> list[dict[str, object]]:
    return [
        {
            "task_id": "T001",
            "title": "Implement Fibonacci branch-layer model in src/main.py",
            "body": "# Task T001: Implement Fibonacci branch-layer model in src/main.py\n\n## Objective\nImplement `fibonacci(n)` and `generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1)`.\n\n## Required Behavior\n- Implement Fibonacci with `F(1)=1`, `F(2)=1`, `F(3)=2`, `F(4)=3`, `F(5)=5`; return `0` for `n <= 0`.\n- The public helper function must be named exactly `fibonacci`. Do not rename it to `fib`, `fib_simple`, or another private helper name.\n- Return exactly `depth` layer dictionaries for positive depth and `[]` for non-positive depth.\n- Each layer contains `level`, `fibonacci`, `branches`, `span`, `angle`, and `thickness`.\n- `branches` must equal that layer's Fibonacci value. For `generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2)`, the final layer must have `branches == 5`, `angle == 42`, and `thickness == 2`.\n- `span` must be `max(1, int(round(fibonacci(level) * scale)))`.\n- Do not return the old nested `value/left/right` shape and do not output only Fibonacci numbers.\n\n## Required Outputs\n- `src/main.py`\n- `README.md`\n\n## Validation Note\nDo not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for the required artifacts. Task T004 owns semantic test creation.\n",
            "required_outputs": ["src/main.py", "README.md"],
        },
        {
            "task_id": "T002",
            "title": "Implement ASCII tree renderer in src/main.py",
            "body": "# Task T002: Implement ASCII tree renderer in src/main.py\n\n## Objective\nImplement `render_tree(layers, thickness=None)`.\n\n## Required Behavior\n- Return a single string with exactly one non-empty branch-drawing line per depth layer.\n- Use visible drawing characters such as `/`, `\\\\`, and `|`.\n- Each line must use the layer's `span` and `thickness`, so changing `scale` or `thickness` changes the rendered tree.\n- Do not render only Fibonacci numbers.\n- Use `chr(92)` when building backslash characters; do not put a raw trailing backslash inside a quoted string.\n\n## Required Outputs\n- `src/main.py`\n- `README.md`\n\n## Validation Note\nDo not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for the required artifacts. Task T004 owns semantic test creation.\n",
            "required_outputs": ["src/main.py", "README.md"],
        },
        {
            "task_id": "T003",
            "title": "Implement CLI depth and configuration flags in src/main.py",
            "body": "# Task T003: Implement CLI depth and configuration flags in src/main.py\n\n## Objective\nAdd an import-safe argparse CLI under `if __name__ == \"__main__\":`.\n\n## Required Behavior\n- Positional `depth` argument.\n- Optional `--scale`, `--angle`, and `--thickness` flags.\n- `python -m src.main 4 --scale 2 --angle 45 --thickness 2` prints four non-empty tree drawing lines.\n\n## Required Outputs\n- `src/main.py`\n- `README.md`\n\n## Validation Note\nDo not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for the required artifacts. Task T004 owns semantic test creation.\n",
            "required_outputs": ["src/main.py", "README.md"],
        },
        {
            "task_id": "T004",
            "title": "Implement semantic tests under tests/test_main.py and verify correctness",
            "body": "# Task T004: Implement semantic tests under tests/test_main.py and verify correctness\n\n## Objective\nAdd tests that prove the project draws a depth-controlled Fibonacci tree. Weak tests that only check `n=1` or a single returned Fibonacci number are invalid.\n\n## Required Behavior\n- Define a local `nonempty_lines(text)` helper inside `tests/test_main.py`; do not import it from `src.main` and do not add it to `src/main.py`.\n- Import and test the public `fibonacci` function from the implementation.\n- Test that `fibonacci(5) == 5`.\n- Test that `generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2)` returns exactly 5 layer dictionaries with `level`, `fibonacci`, `branches`, `span`, `angle`, and `thickness`.\n- Assert that the final layer has `fibonacci == 5`, `branches == 5`, `angle == 42`, and `thickness == 2`.\n- Assert that the returned layer dictionaries are not the old invalid nested `left`/`right` value-tree shape.\n- Import `fibonacci`, `generate_fibonacci_tree`, and `render_tree` from `src.main`.\n- Test output contains branch drawing characters `/`, `chr(92)`, and `|`, and exactly one non-empty line per requested depth layer.\n- Test changing scale changes output.\n- Test CLI `python -m src.main 4 --scale 2 --angle 45 --thickness 2` exits 0 and prints exactly four non-empty tree lines.\n- Tests must fail if output is only a Fibonacci number or numeric sequence.\n- If tests reveal a syntax or implementation error in `src/main.py`, and `src/main.py` is in the current allowed artifacts, repair it with a full-file `fs_write`.\n- Use `chr(92)` for literal backslash checks.\n\n## Required Outputs\n- `src/main.py`\n- `tests/test_main.py`\n- `README.md`\n",
            "required_outputs": ["src/main.py", "tests/test_main.py", "README.md"],
        },
    ]


def parse_task(value: str) -> dict[str, object]:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("task must be 'T001|Task title' or 'T001|Task title|path1,path2'")
    task_id, title = parts[0], parts[1]
    task: dict[str, object] = {"task_id": task_id, "title": title}
    if len(parts) >= 3 and parts[2]:
        task["required_outputs"] = [path.strip() for path in parts[2].split(",") if path.strip()]
    return task


def read_goal(args: argparse.Namespace) -> str:
    if args.project_file:
        return Path(args.project_file).expanduser().resolve().read_text(encoding="utf-8")
    return args.goal or args.title


def planned_tasks_for(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.fixture == "fibonacci_tree_visualizer":
        return fibonacci_planned_tasks()
    if args.task:
        return list(args.task)
    return [
        {
            "task_id": "T001",
            "title": "Implement the approved V4 project goal",
            "body": f"""# Task T001: Implement the approved V4 project goal

## Objective
Implement the project described in `PROJECT.md`.

## Required Behavior
1. Read `PROJECT.md` before editing.
2. Implement the project with the smallest complete Python solution that satisfies the acceptance criteria.
3. Add tests that prove the acceptance criteria.
4. Run the tests before submitting work.

## Required Outputs
- `README.md`
- `src/main.py`
- `tests/test_main.py`
""",
            "required_outputs": ["README.md", "src/main.py", "tests/test_main.py"],
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a persistent V4 project using the existing project-management layout.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="Directory that contains active projects.")
    parser.add_argument("--project-id", required=True, help="Project id / directory slug.")
    parser.add_argument("--title", default="V4 Project", help="Human-readable project title.")
    parser.add_argument("--goal", help="Project goal text.")
    parser.add_argument("--project-file", help="Existing markdown file to use as PROJECT.md content.")
    parser.add_argument("--fixture", choices=["fibonacci_tree_visualizer"], help="Seed a known fixture task plan.")
    parser.add_argument("--task", action="append", type=parse_task, help="Task as 'T001|Task title|optional/output,path'. Repeatable.")
    args = parser.parse_args()

    project_dir = project_dir_for(args.project_root, args.project_id)
    if project_dir.exists():
        print(f"ERROR: project already exists: {project_dir}", file=sys.stderr)
        return 2

    project_dir.mkdir(parents=True)
    os.environ["V4_EVENT_FILE"] = str(project_dir / ".openclaw" / "events.jsonl")
    clear_events_v4()

    goal = read_goal(args)
    if args.project_file:
        (project_dir / "PROJECT.md").write_text(goal, encoding="utf-8")

    smith_plan_project(
        str(project_dir),
        args.project_id,
        args.title,
        planned_tasks_for(args),
        goal=goal,
    )

    missing = validate_v4_project_layout(project_dir, require_runtime_files=False)
    if missing:
        print(f"ERROR: V4 project layout is incomplete: {missing}", file=sys.stderr)
        return 1

    print(f"V4_PROJECT_CREATED={project_dir}")
    print(f"PROJECT_ID={args.project_id}")
    print("NEXT_ACTION=Smith may dispatch the first task through the V4 conductor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
