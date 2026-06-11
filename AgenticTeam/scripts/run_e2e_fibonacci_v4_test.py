#!/usr/bin/env python3
import argparse
import sys
import os
import json
import time
import shutil
import tempfile
import datetime
import subprocess
from pathlib import Path

# Add script directory to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
    
# Add parent directory so imports work
if str(SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))

from AgenticTeam.scripts.v4_smith import (
    smith_plan_project,
    smith_dispatch_worker,
    smith_accept_work_result,
    smith_dispatch_oracle,
    smith_handle_oracle_result,
    smith_expand_allowed_artifacts_for_block,
    smith_record_scope_expansion,
)
from AgenticTeam.scripts.v4_worker import V4WorkerRunner
from AgenticTeam.scripts.v4_oracle import V4OracleRunner
from AgenticTeam.scripts.v4_state import project_state_from_events
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_leases import release_lease
from AgenticTeam.scripts.v4_contracts import (
    DEFAULT_PROTECTED_PATHS,
    DEFAULT_WRITABLE_PATHS,
    TaskPackV4,
    WorkResultV4,
    OracleResultV4,
)
from AgenticTeam.scripts.v4_project_layout import project_dir_for


def known_project_artifacts(planned_tasks: list[dict]) -> list[str]:
    artifacts: list[str] = []
    seen = set()
    for task in planned_tasks:
        for path in task.get("required_outputs", []):
            if path not in seen:
                artifacts.append(path)
                seen.add(path)
    return artifacts


def latest_worker_block_reason(events: list, task_id: str) -> str:
    for ev in reversed(events):
        if ev.event_type == "work_blocked" and ev.payload.get("task_id") == task_id:
            return str(ev.payload.get("reason", ""))
    return ""


def project_python_env(workspace_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    ws_root_str = str(workspace_root)
    env["PYTHONPATH"] = f"{ws_root_str}:{ws_root_str}/src:" + env.get("PYTHONPATH", "")
    return env


def nonempty_output_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def output_is_numeric_only(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and all(ch in "0123456789 \n\r\t.-+" for ch in stripped)


def run_visualizer_cli(
    workspace_root: Path,
    *,
    depth: int,
    scale: float = 1.0,
    angle: float = 30.0,
    thickness: int = 1,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            str(depth),
            "--scale",
            str(scale),
            "--angle",
            str(angle),
            "--thickness",
            str(thickness),
        ],
        cwd=str(workspace_root),
        env=project_python_env(workspace_root),
        capture_output=True,
        text=True,
    )


def validate_visualizer_output(output: str, expected_depth: int) -> list[str]:
    errors: list[str] = []
    lines = nonempty_output_lines(output)
    if len(lines) != expected_depth:
        errors.append(f"expected {expected_depth} non-empty rendered lines, got {len(lines)}")
    if output_is_numeric_only(output):
        errors.append("output is numeric-only; expected a visible tree drawing")
    for char in ("/", chr(92), "|"):
        if char not in output:
            errors.append(f"output missing branch character {char!r}")
    return errors


def validate_final_state_files(workspace_root: Path) -> list[str]:
    errors: list[str] = []
    state_path = workspace_root / ".openclaw" / "state.json"
    if not state_path.exists():
        errors.append("missing .openclaw/state.json")
    else:
        state_data = json.loads(state_path.read_text(encoding="utf-8"))
        if state_data.get("phase") != "DONE":
            errors.append(f".openclaw/state.json phase is {state_data.get('phase')!r}, expected DONE")
        if state_data.get("waiting_for") != "none":
            errors.append(f".openclaw/state.json waiting_for is {state_data.get('waiting_for')!r}, expected none")

    project_state_path = workspace_root / "PROJECT_STATE.md"
    if not project_state_path.exists():
        errors.append("missing PROJECT_STATE.md")
    else:
        text = project_state_path.read_text(encoding="utf-8")
        if "- **phase**: DONE" not in text:
            errors.append("PROJECT_STATE.md does not show phase DONE")
        if "- **waiting_for**: none" not in text:
            errors.append("PROJECT_STATE.md does not show waiting_for none")
    return errors


def validate_fibonacci_visualizer_project(workspace_root: Path) -> list[str]:
    errors: list[str] = []
    env = project_python_env(workspace_root)
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
        if "nonempty_lines" in test_text.split("from src.main import", 1)[-1].splitlines()[0]:
            errors.append("tests/test_main.py must not import nonempty_lines from src.main")
    else:
        errors.append("missing tests/test_main.py")

    semantic_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.main import generate_fibonacci_tree; "
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

    base = run_visualizer_cli(workspace_root, depth=4, scale=1.0, angle=30, thickness=1)
    scaled = run_visualizer_cli(workspace_root, depth=4, scale=3.0, angle=30, thickness=1)
    deeper = run_visualizer_cli(workspace_root, depth=5, scale=1.0, angle=30, thickness=1)
    for label, result, depth in (("base", base, 4), ("scaled", scaled, 4), ("deeper", deeper, 5)):
        if result.returncode != 0:
            errors.append(f"{label} CLI failed: {result.stderr or result.stdout}")
            continue
        errors.extend(f"{label} CLI: {error}" for error in validate_visualizer_output(result.stdout, depth))

    if base.returncode == 0 and scaled.returncode == 0 and base.stdout == scaled.stdout:
        errors.append("changing --scale did not change CLI output")
    if base.returncode == 0 and deeper.returncode == 0 and base.stdout == deeper.stdout:
        errors.append("changing depth did not change CLI output")

    errors.extend(validate_final_state_files(workspace_root))
    return errors


def latest_submitted_work(events: list, task_id: str):
    for ev in reversed(events):
        if ev.event_type == "work_submitted" and ev.payload.get("task_id") == task_id:
            return ev
    return None


def latest_oracle_report(events: list):
    for ev in reversed(events):
        if ev.event_type in ("oracle_passed", "oracle_failed"):
            return ev
    return None


def latest_oracle_repair_task_id(events: list) -> str | None:
    for ev in reversed(events):
        if ev.event_type != "task_planned":
            continue
        title = str(ev.payload.get("title", ""))
        task_id = ev.payload.get("task_id")
        if task_id and title.startswith("Repair project based on Oracle failure"):
            return str(task_id)
    return None


def simulate_morpheus_task(workspace_root: Path, task_id: str) -> None:
    print(f"[Dry Run] Simulating Morpheus work for {task_id}...")
    if task_id == "T001":
        code = """
def fibonacci(n):
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1):
    if depth <= 0:
        return []
    layers = []
    for level in range(1, depth + 1):
        fib_value = fibonacci(level)
        layers.append({
            "level": level,
            "fibonacci": fib_value,
            "branches": fib_value,
            "span": max(1, int(round(fib_value * scale))),
            "angle": angle,
            "thickness": thickness,
        })
    return layers
"""
        (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
    elif task_id == "T002":
        code = (workspace_root / "src" / "main.py").read_text(encoding="utf-8") + """
def render_tree(layers, thickness=None):
    if not layers:
        return ""
    total = len(layers)
    lines = []
    for layer in layers:
        level = int(layer.get("level", 1))
        span = max(1, int(layer.get("span", 1)))
        trunk_width = int(thickness if thickness is not None else layer.get("thickness", 1))
        indent = " " * max(0, total - level)
        left = "/" * span
        trunk = "|" * max(1, trunk_width)
        right = chr(92) * span
        lines.append(f"{indent}{left}{trunk}{right}")
    return "\\n".join(lines) + "\\n"
"""
        (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
    elif task_id == "T003":
        code = (workspace_root / "src" / "main.py").read_text(encoding="utf-8") + """
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Render a Fibonacci branch tree.")
    parser.add_argument("depth", type=int)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--angle", type=float, default=30.0)
    parser.add_argument("--thickness", type=int, default=1)
    args = parser.parse_args()
    layers = generate_fibonacci_tree(args.depth, scale=args.scale, angle=args.angle, thickness=args.thickness)
    print(render_tree(layers, thickness=args.thickness), end="")
"""
        (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
    elif task_id == "T004":
        test_code = """
import os
import subprocess
import sys
from src.main import generate_fibonacci_tree, render_tree


def nonempty_lines(text):
    return [line for line in text.splitlines() if line.strip()]


def test_generate_tree_depth_and_layer_schema():
    layers = generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2)
    assert isinstance(layers, list)
    assert len(layers) == 5
    assert layers[-1]["fibonacci"] == 5
    assert layers[-1]["branches"] == 5
    assert layers[-1]["angle"] == 42
    assert layers[-1]["thickness"] == 2
    assert all(key in layers[0] for key in ("level", "fibonacci", "branches", "span", "angle", "thickness"))
    assert "left" not in layers[0]
    assert "right" not in layers[0]


def test_render_tree_draws_one_line_per_depth_with_branch_chars():
    output = render_tree(generate_fibonacci_tree(4, thickness=2), thickness=2)
    lines = nonempty_lines(output)
    assert len(lines) == 4
    assert "/" in output
    assert chr(92) in output
    assert "|" in output
    assert output.strip() not in {"1", "2", "3", "5"}


def test_scale_changes_rendered_tree():
    small = render_tree(generate_fibonacci_tree(4, scale=1.0))
    large = render_tree(generate_fibonacci_tree(4, scale=3.0))
    assert small != large


def test_cli_depth_and_flags_render_tree():
    env = os.environ.copy()
    cwd = os.getcwd()
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "4", "--scale", "2", "--angle", "45", "--thickness", "2"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    lines = nonempty_lines(result.stdout)
    assert len(lines) == 4
    assert "/" in result.stdout
    assert chr(92) in result.stdout
    assert "|" in result.stdout
"""
        (workspace_root / "tests" / "test_main.py").write_text(test_code, encoding="utf-8")


def run_morpheus_task(
    *,
    workspace_root: Path,
    project_id: str,
    task_id: str,
    title: str,
    expected_artifacts: list[str],
    project_artifacts: list[str],
    dry_run: bool,
) -> bool:
    print(f"\n--- Processing Task {task_id}: {title} ---")
    current_expected = list(expected_artifacts)

    for worker_attempt in range(1, 4):
        print(f"Smith dispatching {task_id} attempt {worker_attempt} with expected artifacts: {current_expected}")
        lease = smith_dispatch_worker(str(workspace_root), task_id, "morpheus")
        if not lease:
            print(f"Error: Smith could not acquire lease for task {task_id}")
            return False

        if dry_run:
            simulate_morpheus_task(workspace_root, task_id)
            wr = WorkResultV4(
                task_id=task_id,
                attempt_id=lease.metadata["attempt_id"],
                status="DONE",
                summary=f"Completed task {task_id}.",
                output={"artifacts": current_expected or ["src/main.py", "tests/test_main.py", "README.md"]},
                evidence={"tests_passed": True},
            )
            smith_accept_work_result(str(workspace_root), wr, lease.lease_id, "morpheus")
            break

        task_pack = TaskPackV4(
            project_id=project_id,
            task_id=task_id,
            workspace_root=str(workspace_root),
            expected_artifacts=lease.metadata.get("expected_artifacts") or current_expected,
            writable_paths=lease.metadata.get("writable_paths") or list(DEFAULT_WRITABLE_PATHS),
            protected_paths=lease.metadata.get("protected_paths") or list(DEFAULT_PROTECTED_PATHS),
            allowed_artifacts=lease.metadata.get("expected_artifacts") or current_expected,
        )

        print(f"Starting Morpheus Worker Runner for {task_id}...")
        runner = V4WorkerRunner(task_pack, lease, actor="morpheus")
        res = runner.run(max_turns=35)
        print(f"Morpheus result for {task_id}: {res}")

        events = read_events_v4()
        state = project_state_from_events(events)
        task_status = state.tasks.get(task_id, {}).get("status")
        if task_status in ("BLOCKED", "FAILED"):
            reason = latest_worker_block_reason(events, task_id)
            release_lease(str(workspace_root), lease.lease_id)
            expanded = smith_expand_allowed_artifacts_for_block(current_expected, reason, project_artifacts)
            if expanded and expanded != current_expected and worker_attempt < 3:
                smith_record_scope_expansion(
                    str(workspace_root),
                    task_id,
                    current_expected,
                    expanded,
                    reason,
                )
                print(f"Smith expanding {task_id} scope after repairable block: {expanded}")
                current_expected = expanded
                continue

            print(f"Error: Task {task_id} was marked {task_status} by worker. Reason: {reason}")
            return False

        submitted = latest_submitted_work(events, task_id)
        if submitted is None:
            release_lease(str(workspace_root), lease.lease_id)
            if worker_attempt < 3:
                print(f"Smith retrying {task_id} after Morpheus returned no work result: {res}")
                continue
            print(f"Error: Morpheus did not submit work result for {task_id}.")
            return False

        wr = WorkResultV4(
            task_id=submitted.payload["task_id"],
            attempt_id=submitted.payload["attempt_id"],
            status=submitted.payload["status"],
            summary=submitted.payload["summary"],
            output=submitted.payload["output"],
            evidence=submitted.payload["evidence"],
        )
        print(f"Smith accepting work result for {task_id}...")
        smith_accept_work_result(str(workspace_root), wr, lease.lease_id, "morpheus")
        break
    else:
        print(f"Error: Task {task_id} did not complete after Smith retry budget.")
        return False

    events = read_events_v4()
    state = project_state_from_events(events)
    if state.tasks.get(task_id, {}).get("status") != "DONE":
        print(f"Error: Task {task_id} status in state is not DONE: {state.tasks.get(task_id)}")
        return False
    return True


def run_oracle_cycle(workspace_root: Path, project_id: str, dry_run: bool) -> str | None:
    print("\n--- Dispatching Oracle Project Verification ---")
    event_count_before_dispatch = len(read_events_v4())
    oracle_lease = smith_dispatch_oracle(str(workspace_root), "oracle")
    if not oracle_lease:
        print("Error: Smith could not dispatch Oracle.")
        return None

    if dry_run:
        print("[Dry Run] Simulating Oracle PASS report...")
        or_res = OracleResultV4(
            project_id=project_id,
            task_id="none",
            status="PASS",
            evidence_paths=["src/main.py", "tests/test_main.py"],
            summary="All Fibonacci E2E dry-run requirements satisfied.",
        )
        smith_handle_oracle_result(str(workspace_root), or_res, oracle_lease.lease_id, "oracle")
        return "PASS"

    print("Starting Oracle Runner...")
    runner = V4OracleRunner(str(workspace_root), oracle_lease, actor="oracle")
    res = runner.run(max_turns=25)
    print(f"Oracle result: {res}")

    oracle_event = latest_oracle_report(read_events_v4()[event_count_before_dispatch:])
    if oracle_event is None:
        release_lease(str(workspace_root), oracle_lease.lease_id)
        print("Error: Oracle did not submit a verification report.")
        return None

    oracle_status = "PASS" if oracle_event.event_type == "oracle_passed" else "FAIL"
    or_res = OracleResultV4(
        project_id=project_id,
        task_id="none",
        status=oracle_status,
        evidence_paths=oracle_event.payload.get("evidence_paths", []),
        summary=oracle_event.payload.get("summary", ""),
    )
    print("Smith handling OracleResult...")
    smith_handle_oracle_result(str(workspace_root), or_res, oracle_lease.lease_id, "oracle")
    return oracle_status


def run_single_e2e(
    run_index: int,
    dry_run: bool = False,
    keep_workspace: bool = False,
    project_root: str | None = None,
) -> bool:
    print(f"\n==========================================")
    print(f"Starting E2E Run #{run_index} (dry_run={dry_run})")
    print(f"==========================================\n")
    
    # 1. Setup workspace
    temp_dir = None
    if project_root:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        project_id = f"run-e2e-fibonacci-v4-{timestamp}-{run_index}"
        workspace_root = project_dir_for(project_root, project_id)
        workspace_root.mkdir(parents=True, exist_ok=False)
        keep_workspace = True
    else:
        project_id = f"fib-v4-run-{run_index}"
        temp_dir = tempfile.mkdtemp(prefix=f"fibonacci_v4_run_{run_index}_")
        workspace_root = Path(temp_dir)
    print(f"Workspace root: {workspace_root}")
    
    # Isolate V4 event file
    os.environ["V4_EVENT_FILE"] = str(workspace_root / ".openclaw" / "events.jsonl")
    clear_events_v4()
    
    # Copy project fixture
    fixture_path = SCRIPT_DIR.parent / "fixtures" / "fibonacci_tree_visualizer.md"
    if not fixture_path.exists():
        print(f"Error: Fixture fibonacci_tree_visualizer.md not found at {fixture_path}")
        sys.exit(1)
        
    shutil.copy(fixture_path, workspace_root / "PROJECT.md")
    
    # 2. Plan the project tasks
    planned_tasks = [
        {
            "task_id": "T001",
            "title": "Implement Fibonacci branch-layer model in src/main.py"
        },
        {
            "task_id": "T002",
            "title": "Implement ASCII tree renderer in src/main.py"
        },
        {
            "task_id": "T003",
            "title": "Implement CLI depth and configuration flags in src/main.py"
        },
        {
            "task_id": "T004",
            "title": "Implement semantic tests under tests/test_main.py and verify correctness"
        }
   ]
    
    t001_desc = """# Task T001: Implement Fibonacci branch-layer model in src/main.py

## Objective
Implement the data model for an ASCII Fibonacci tree visualizer.

This project must draw a visible tree for a requested number of depth layers. Do NOT implement a recursive dictionary that only returns Fibonacci values. Do NOT make the CLI output only numbers.

## Specifications
1. Implement `fibonacci(n)` with F(1)=1, F(2)=1, F(3)=2, F(4)=3, F(5)=5. Return 0 for `n <= 0`.
2. Implement `generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1)`.
3. If `depth <= 0`, return an empty list `[]`.
4. For positive depth, return a list with exactly `depth` layer dictionaries.
5. Each layer dictionary must contain at least these keys:
   - `level`: 1-based layer number
   - `fibonacci`: Fibonacci value for that level
   - `branches`: same value as `fibonacci`
   - `span`: `max(1, int(round(fibonacci(level) * scale)))`
   - `angle`: the supplied angle value
   - `thickness`: the supplied thickness value
6. Do not return a nested `{"value": ..., "left": ..., "right": ...}` tree. That shape is invalid for this project because it does not directly support drawing N visible layers.

## Required Outputs
- `src/main.py`

## Validation Note
Do not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for `src/main.py`. Task T004 owns semantic test creation.
"""

    t002_desc = """# Task T002: Implement ASCII tree renderer in src/main.py

## Objective
Implement a renderer that turns the branch-layer model from T001 into a visible terminal tree.

## Specifications
1. Implement `render_tree(layers, thickness=None)` in `src/main.py`.
2. If `layers` is empty, return `""`.
3. Return a string with exactly one non-empty line per layer.
4. Each line must contain visible branch drawing characters such as `/`, `\\`, and `|`.
5. Each line must use the layer's `span` and `thickness`, so changing `scale` or `thickness` changes the drawing.
6. Use `chr(92)` when you need a backslash character. Do not put a raw trailing backslash inside a quoted string, because that creates Python syntax errors.
7. A valid simple implementation pattern is:
   ```python
   total = len(layers)
   lines = []
   for layer in layers:
       level = int(layer["level"])
       span = max(1, int(layer["span"]))
       trunk_width = int(thickness if thickness is not None else layer["thickness"])
       indent = " " * max(0, total - level)
       line = indent + "/" * span + "|" * max(1, trunk_width) + chr(92) * span
       lines.append(line)
   return "\\n".join(lines) + "\\n"
   ```
8. A valid simple output shape is:
   ```
      /|\\
     /|\\
    //|\\\\
   ///|\\\\\\
   ```
9. The renderer may include layer labels, but it must not output only Fibonacci numbers.

## Required Outputs
- `src/main.py`

## Validation Note
Do not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for `src/main.py`. Task T004 owns semantic test creation.
"""

    t003_desc = """# Task T003: Implement CLI depth and configuration flags in src/main.py

## Objective
Implement the command-line interface that renders the Fibonacci tree drawing.

## Specifications
1. Use `argparse` inside the `if __name__ == "__main__":` block only.
2. Positional argument: `depth` integer, the number of visible tree layers to render.
3. Optional flags:
   - `--scale` float, default `1.0`
   - `--angle` float, default `30.0`
   - `--thickness` integer, default `1`
4. The CLI must call `generate_fibonacci_tree(depth, scale=args.scale, angle=args.angle, thickness=args.thickness)` and print `render_tree(...)`.
5. Running `python -m src.main 4 --scale 2 --angle 45 --thickness 2` must print four non-empty branch lines, not just the number 3 or a Fibonacci sequence.
6. CRITICAL: Do NOT execute `parse_args()` or print statements at module import time.

## Required Outputs
- `src/main.py`

## Validation Note
Do not block only because `tests/test_main.py` is not an allowed artifact for this task. Run existing tests if available, then submit evidence for `src/main.py`. Task T004 owns semantic test creation.
"""

    t004_desc = """# Task T004: Implement semantic tests under tests/test_main.py and verify correctness

## Objective
Implement tests that prove the project draws a depth-controlled Fibonacci tree. Weak tests that only check `n=1` or a single returned Fibonacci number are invalid.

## Specifications
1. Write tests using pytest-style functions or `unittest`.
2. Tests must import from `src.main`.
3. Include a test that `generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2)` returns a list of exactly 5 layer dictionaries with `level`, `fibonacci`, `branches`, `span`, `angle`, and `thickness`.
4. Include a test that the returned layer dictionaries are not the old invalid nested `left`/`right` value-tree shape.
5. Include a test that `render_tree(generate_fibonacci_tree(4, thickness=2), thickness=2)` returns exactly 4 non-empty lines and contains branch drawing characters `/`, `\\`, and `|`.
6. Include a test that changing `scale` changes the rendered output.
7. Include a CLI test using `subprocess.run([sys.executable, "-m", "src.main", "4", "--scale", "2", "--angle", "45", "--thickness", "2"], ...)`.
8. The CLI test must assert the command exits 0, prints exactly 4 non-empty lines, and includes branch drawing characters. It must fail if output is only a Fibonacci number or numeric sequence.
9. Run the tests using the tests runner tool to verify they pass successfully.
10. Do NOT create any new files/directories inside `tests` other than `tests/test_main.py`.
11. If the semantic tests reveal a syntax error or implementation defect in `src/main.py`, repair `src/main.py` with `fs_write` using the full corrected file content. Do not block for a source or test file that is inside Writable Paths.
12. If you need a literal backslash in code or tests, use `chr(92)` to avoid broken string escaping.
13. Keep `nonempty_lines` as a test helper inside `tests/test_main.py`. Do NOT import it from `src.main` and do NOT add it to `src/main.py`.
14. Prefer a single full-file `fs_write` for `tests/test_main.py` using the recommended content below. Avoid incremental `fs_patch` additions for this test file.
15. If `src/main.py` has duplicate functions, nested function definitions, broken indentation, or test helpers, replace `src/main.py` with a clean full implementation containing exactly one `fibonacci`, one `generate_fibonacci_tree`, one `render_tree`, and one `if __name__ == "__main__"` block.
16. If pytest fails during collection with `argparse`, `parse_args`, `SystemExit: 2`, `unrecognized arguments`, or an invalid depth argument from pytest's own command line, do NOT weaken or delete tests. Fix `src/main.py` so CLI parsing happens only in `main(argv=None)` or under `if __name__ == "__main__"` and importable functions have no side effects.

## Recommended test file
You may copy this exact `tests/test_main.py` content if helpful:

```python
import os
import subprocess
import sys

from src.main import generate_fibonacci_tree, render_tree


def nonempty_lines(text):
    return [line for line in text.splitlines() if line.strip()]


def test_generate_tree_depth_and_layer_schema():
    layers = generate_fibonacci_tree(5, scale=1.5, angle=42, thickness=2)
    assert isinstance(layers, list)
    assert len(layers) == 5
    assert layers[-1]["fibonacci"] == 5
    assert layers[-1]["branches"] == 5
    assert layers[-1]["angle"] == 42
    assert layers[-1]["thickness"] == 2
    assert all(key in layers[0] for key in ("level", "fibonacci", "branches", "span", "angle", "thickness"))
    assert "left" not in layers[0]
    assert "right" not in layers[0]


def test_render_tree_draws_one_line_per_depth_with_branch_chars():
    output = render_tree(generate_fibonacci_tree(4, thickness=2), thickness=2)
    lines = nonempty_lines(output)
    assert len(lines) == 4
    assert "/" in output
    assert chr(92) in output
    assert "|" in output
    assert output.strip() not in {"1", "2", "3", "5"}


def test_scale_changes_rendered_tree():
    small = render_tree(generate_fibonacci_tree(4, scale=1.0))
    large = render_tree(generate_fibonacci_tree(4, scale=3.0))
    assert small != large


def test_cli_depth_and_flags_render_tree():
    env = os.environ.copy()
    cwd = os.getcwd()
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "4", "--scale", "2", "--angle", "45", "--thickness", "2"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    lines = nonempty_lines(result.stdout)
    assert len(lines) == 4
    assert "/" in result.stdout
    assert chr(92) in result.stdout
    assert "|" in result.stdout
```

## Required Outputs
- `src/main.py`
- `tests/test_main.py`
- `README.md`
"""

    task_bodies = {
        "T001": t001_desc,
        "T002": t002_desc,
        "T003": t003_desc,
        "T004": t004_desc,
    }
    for task in planned_tasks:
        task["body"] = task_bodies[task["task_id"]]
        task["required_outputs"] = ["src/main.py", "tests/test_main.py", "README.md"] if task["task_id"] == "T004" else ["src/main.py"]

    print("Smith planning project...")
    smith_plan_project(
        str(workspace_root),
        project_id,
        "Fibonacci Tree Visualizer",
        planned_tasks,
        goal=fixture_path.read_text(encoding="utf-8"),
    )
        
    # Create empty placeholders to avoid missing files before starting
    (workspace_root / "src").mkdir(parents=True, exist_ok=True)
    (workspace_root / "tests").mkdir(parents=True, exist_ok=True)
    skeleton = """# Fibonacci Tree Visualizer

def fibonacci(n):
    pass

def generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1):
    pass

def render_tree(layers, thickness=None):
    pass

if __name__ == "__main__":
    pass
"""
    (workspace_root / "src" / "main.py").write_text(skeleton, encoding="utf-8")
    (workspace_root / "tests" / "test_main.py").write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    (workspace_root / "README.md").write_text("# Fibonacci Tree Visualizer\n", encoding="utf-8")

    # 3. Task implementation loop (T001 -> T002 -> T003 -> T004)
    project_artifacts = known_project_artifacts(planned_tasks)
    for t in planned_tasks:
        if not run_morpheus_task(
            workspace_root=workspace_root,
            project_id=project_id,
            task_id=t["task_id"],
            title=t["title"],
            expected_artifacts=list(t.get("required_outputs", [])),
            project_artifacts=project_artifacts,
            dry_run=dry_run,
        ):
            return False

    # 4. Project verification with a bounded Oracle-fail repair loop.
    for oracle_attempt in range(1, 3):
        oracle_status = run_oracle_cycle(workspace_root, project_id, dry_run)
        if oracle_status == "PASS":
            break
        if oracle_status is None:
            return False
        if oracle_attempt >= 2:
            print("Error: Oracle verification still failed after repair budget.")
            return False

        events = read_events_v4()
        repair_task_id = latest_oracle_repair_task_id(events)
        if not repair_task_id:
            print("Error: Oracle failed but Smith did not create a repair task.")
            return False

        repair_title = project_state_from_events(events).tasks.get(repair_task_id, {}).get(
            "title",
            "Repair project based on Oracle failure",
        )
        print(f"\n--- Oracle failed; dispatching repair task {repair_task_id} ---")
        if not run_morpheus_task(
            workspace_root=workspace_root,
            project_id=project_id,
            task_id=repair_task_id,
            title=repair_title,
            expected_artifacts=project_artifacts,
            project_artifacts=project_artifacts,
            dry_run=dry_run,
        ):
            return False

    # 5. Final validation check
    events = read_events_v4()
    state = project_state_from_events(events)
    print(f"\nFinal Project State Phase: {state.phase}")
    
    if state.phase != "DONE":
        print(f"Error: E2E project failed to transition to DONE. Current phase: {state.phase}")
        return False
        
    print(f"Verification: project files exist under {workspace_root}")
    # Verify tests run successfully on host
    env = project_python_env(workspace_root)
    
    test_res = subprocess.run(
        f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m pytest -q tests/test_main.py",
        shell=True,
        cwd=str(workspace_root),
        env=env,
        capture_output=True,
        text=True
    )
    if test_res.returncode != 0:
        print(f"Error: Final tests fail on host:\n{test_res.stdout}\n{test_res.stderr}")
        return False

    semantic_errors = validate_fibonacci_visualizer_project(workspace_root)
    if semantic_errors:
        print("Error: Final Fibonacci visualizer semantics failed:")
        for error in semantic_errors:
            print(f"- {error}")
        return False

    print("E2E tests verify successfully!")
    
    # Cleanup
    if keep_workspace:
        print(f"Keeping workspace at {workspace_root} for inspection.")
    else:
        assert temp_dir is not None
        shutil.rmtree(temp_dir)
        print(f"Cleanup completed. Run #{run_index} PASSED!")
    return True

def main():
    os.environ["OPENCLAW_OLLAMA_NUM_CTX"] = "16384"
    os.environ["OPENCLAW_OLLAMA_MODEL"] = "ollama/gemma3:12b"
    
    parser = argparse.ArgumentParser(description="V4 Fibonacci E2E Runner")
    parser.add_argument("--dry-run", action="store_true", help="Run with simulated dry run steps")
    parser.add_argument("--repeat", type=int, default=1, help="Number of consecutive repetitions")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Max execution time in seconds (ignored/for compatibility)")
    parser.add_argument("--stall-seconds", type=int, default=180, help="Stall detection time in seconds (ignored/for compatibility)")
    parser.add_argument("--keep-workspace", action="store_true", help="Do not delete the temporary workspace after completion")
    parser.add_argument("--project-root", help="Create the V4 project under this persistent projects root instead of /tmp")
    args = parser.parse_args()
    
    successes = 0
    for idx in range(1, args.repeat + 1):
        try:
            passed = run_single_e2e(
                idx,
                dry_run=args.dry_run,
                keep_workspace=args.keep_workspace,
                project_root=args.project_root,
            )
            if passed:
                successes += 1
            else:
                print(f"Run #{idx} FAILED!")
                sys.exit(1)
        except Exception as e:
            print(f"Run #{idx} raised exception: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    print(f"\nAll {successes}/{args.repeat} repetitions completed successfully!")
    print("E2E Validation Gate PASSED!")

if __name__ == "__main__":
    main()
