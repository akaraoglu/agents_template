#!/usr/bin/env python3
import argparse
import sys
import os
import json
import time
import shutil
import tempfile
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
    smith_handle_oracle_result
)
from AgenticTeam.scripts.v4_worker import V4WorkerRunner
from AgenticTeam.scripts.v4_oracle import V4OracleRunner
from AgenticTeam.scripts.v4_state import project_state_from_events
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_contracts import TaskPackV4, WorkResultV4, OracleResultV4

def run_single_e2e(run_index: int, dry_run: bool = False) -> bool:
    print(f"\n==========================================")
    print(f"Starting E2E Run #{run_index} (dry_run={dry_run})")
    print(f"==========================================\n")
    
    # 1. Setup workspace
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
            "title": "Implement core Fibonacci tree generation logic in src/main.py"
        },
        {
            "task_id": "T002",
            "title": "Implement tree ASCII visualization renderer in src/main.py"
        },
        {
            "task_id": "T003",
            "title": "Implement command-line interface argument parsing in src/main.py"
        },
        {
            "task_id": "T004",
            "title": "Implement unit tests under tests/test_main.py and verify correctness"
        }
   ]
    
    print("Smith planning project...")
    smith_plan_project(str(workspace_root), f"fib-v4-run-{run_index}", "Fibonacci Tree Visualizer", planned_tasks)
    
    # Write the task description files (normally Smith does this during planning)
    tasks_dir = workspace_root / "management" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    t001_desc = """# Task T001: Implement core Fibonacci tree generation logic in src/main.py

## Objective
Implement a function `generate_fibonacci_tree(n)` in `src/main.py` that recursively constructs a Fibonacci tree of height `n`.

## Specifications
1. If `n <= 0`, return `None`.
2. The tree is represented as a dictionary: `{"value": int, "left": dict or None, "right": dict or None}`.
3. Fibonacci sequence values are: F(1)=1, F(2)=1, F(3)=2, F(4)=3, F(5)=5, etc.
4. For `n = 1`, return `{"value": 1, "left": None, "right": None}`.
5. For `n = 2`, return `{"value": 1, "left": {"value": 1, "left": None, "right": None}, "right": None}`.
6. For `n > 2`, the root has `value = F(n)`, `left = generate_fibonacci_tree(n-1)`, and `right = generate_fibonacci_tree(n-2)`.
7. You must use the following helper function to calculate Fibonacci values:
```python
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
```

## Required Outputs
- `src/main.py`
- `README.md`
"""

    t002_desc = """# Task T002: Implement tree ASCII visualization renderer in src/main.py

## Objective
Implement a function `render_tree(tree, indent="")` in `src/main.py` that takes the tree dictionary generated in T001 and returns its ASCII/Unicode visualization as a string.

## Specifications
1. If `tree` is `None`, return empty string `""`.
2. It should return a string showing the tree hierarchy. For example:
   Root value on the first line.
   Left child indented on the next line.
   Right child indented below it.
3. Example format for n=3:
   ```
   2
     1
       1
     1
   ```
   (indented by two spaces per level).

## Required Outputs
- `src/main.py`
- `README.md`
"""

    t003_desc = """# Task T003: Implement command-line interface argument parsing in src/main.py

## Objective
Implement a CLI wrapper in `src/main.py` under `if __name__ == "__main__":` block that parses command-line arguments using `argparse`.

## Specifications
1. Command-line argument: `n` (positional, integer, representing the height of the tree).
2. It should call `generate_fibonacci_tree(n)` and print the output of `render_tree(t)` to stdout.
3. Example: running `python src/main.py 3` should output:
   ```
   2
     1
       1
     1
   ```
4. CRITICAL: The argument parser creation, argument definition, `args = parser.parse_args()`, and print statement MUST be inside the `if __name__ == "__main__":` block. Do NOT execute `parse_args()` or execute print statements at the module level (outside the block), because other files (such as tests) will import `src/main.py`, and executing argparse at the module level will cause import crashes during test execution.

## Required Outputs
- `src/main.py`
- `README.md`
"""

    t004_desc = """# Task T004: Implement unit tests under tests/test_main.py and verify correctness

## Objective
Implement unit tests in `tests/test_main.py` to verify the correctness of the Fibonacci tree generation, rendering, and CLI functionality.

## Specifications
1. Write tests using `unittest` (or simple functions with `assert`).
2. Test `generate_fibonacci_tree(n)`: assert that calling `generate_fibonacci_tree(1)` returns `{"value": 1, "left": None, "right": None}`.
3. Test `render_tree(tree)`: note that `render_tree` returns a string directly and does NOT print to stdout. Do NOT capture stdout to test it. Assert that `render_tree(None)` returns `""`, and `render_tree({"value": 1, "left": None, "right": None}).strip() == "1"` (use `.strip()` to allow optional trailing whitespace/newlines).
4. Run the tests using the tests runner tool to verify they pass successfully.
5. You must import the functions from the `src.main` module (e.g., `from src.main import generate_fibonacci_tree, render_tree`). Do NOT attempt to import a module named `fibonacci`, and do NOT write or create any new files/directories inside the `tests` directory other than `tests/test_main.py`.

## Required Outputs
- `tests/test_main.py`
- `README.md`
"""

    (tasks_dir / "T001.md").write_text(t001_desc, encoding="utf-8")
    (tasks_dir / "T002.md").write_text(t002_desc, encoding="utf-8")
    (tasks_dir / "T003.md").write_text(t003_desc, encoding="utf-8")
    (tasks_dir / "T004.md").write_text(t004_desc, encoding="utf-8")
        
    # Create empty placeholders to avoid missing files before starting
    (workspace_root / "src").mkdir(parents=True, exist_ok=True)
    (workspace_root / "tests").mkdir(parents=True, exist_ok=True)
    skeleton = """# Fibonacci Tree Visualizer

def fibonacci(n):
    pass

def generate_fibonacci_tree(n):
    pass

def render_tree(tree, indent=""):
    pass

if __name__ == "__main__":
    pass
"""
    (workspace_root / "src" / "main.py").write_text(skeleton, encoding="utf-8")
    (workspace_root / "tests" / "test_main.py").write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    (workspace_root / "README.md").write_text("# Fibonacci Tree Visualizer\n", encoding="utf-8")

    # 3. Task implementation loop (T001 -> T002 -> T003 -> T004)
    for t in planned_tasks:
        task_id = t["task_id"]
        title = t["title"]
        print(f"\n--- Processing Task {task_id}: {title} ---")
        
        # Smith dispatches
        lease = smith_dispatch_worker(str(workspace_root), task_id, "morpheus")
        if not lease:
            print(f"Error: Smith could not acquire lease for task {task_id}")
            return False
            
        if task_id in ("T001", "T002", "T003"):
            allowed_artifacts = ["src/main.py", "README.md"]
        else:
            allowed_artifacts = ["tests/test_main.py", "README.md"]
            
        task_pack = TaskPackV4(
            project_id=f"fib-v4-run-{run_index}",
            task_id=task_id,
            workspace_root=str(workspace_root),
            allowed_artifacts=allowed_artifacts
        )
        
        if dry_run:
            # Simulate implementation work
            print(f"[Dry Run] Simulating Morpheus work for {task_id}...")
            if task_id == "T001":
                # Implement basic fibonacci tree generation
                code = """
def generate_fibonacci_tree(n):
    if n <= 0:
        return {}
    # Returns a simple node structure representing levels
    tree = {"value": 1, "left": None, "right": None}
    if n > 1:
        tree["left"] = {"value": 1, "left": None, "right": None}
    if n > 2:
        tree["right"] = {"value": 2, "left": None, "right": None}
    return tree
"""
                (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
            elif task_id == "T002":
                # Add visualization
                code = (workspace_root / "src" / "main.py").read_text(encoding="utf-8") + """
def render_tree(tree, indent=""):
    if not tree:
        return ""
    result = indent + str(tree["value"]) + "\\n"
    if tree["left"]:
        result += render_tree(tree["left"], indent + "  ")
    if tree["right"]:
        result += render_tree(tree["right"], indent + "  ")
    return result
"""
                (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
            elif task_id == "T003":
                # Add CLI
                code = (workspace_root / "src" / "main.py").read_text(encoding="utf-8") + """
import sys
if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    t = generate_fibonacci_tree(n)
    print(render_tree(t))
"""
                (workspace_root / "src" / "main.py").write_text(code, encoding="utf-8")
            elif task_id == "T004":
                # Add unit tests
                test_code = """
from src.main import generate_fibonacci_tree, render_tree
def test_generation():
    t = generate_fibonacci_tree(3)
    assert t["value"] == 1
    assert t["left"]["value"] == 1
    assert t["right"]["value"] == 2
def test_render():
    t = generate_fibonacci_tree(2)
    rendered = render_tree(t)
    assert "1" in rendered
"""
                (workspace_root / "tests" / "test_main.py").write_text(test_code, encoding="utf-8")
                
            # Submit result
            wr = WorkResultV4(
                task_id=task_id,
                attempt_id=lease.metadata["attempt_id"],
                status="DONE",
                summary=f"Completed task {task_id}.",
                output={"artifacts": ["src/main.py", "tests/test_main.py", "README.md"]},
                evidence={"tests_passed": True}
            )
            smith_accept_work_result(str(workspace_root), wr, lease.lease_id, "morpheus")
        else:
            # Live LLM execution
            print(f"Starting Morpheus Worker Runner for {task_id}...")
            runner = V4WorkerRunner(task_pack, lease, actor="morpheus")
            res = runner.run(max_turns=35)
            print(f"Morpheus result for {task_id}: {res}")
            
            # Read state events
            events = read_events_v4()
            state = project_state_from_events(events)
            
            # Check if task got BLOCKED or FAILED in the state
            if state.tasks.get(task_id, {}).get("status") in ("BLOCKED", "FAILED"):
                print(f"Error: Task {task_id} was marked {state.tasks.get(task_id, {}).get('status')} by worker.")
                return False
                
            # Find the work_submitted event to accept it
            last_ev = events[-1]
            if last_ev.event_type != "work_submitted":
                for ev in reversed(events):
                    if ev.event_type == "work_submitted":
                        if ev.payload.get("task_id") == task_id:
                            last_ev = ev
                            break
                        
            if last_ev.event_type == "work_submitted" and last_ev.payload.get("task_id") == task_id:
                wr = WorkResultV4(
                    task_id=last_ev.payload["task_id"],
                    attempt_id=last_ev.payload["attempt_id"],
                    status=last_ev.payload["status"],
                    summary=last_ev.payload["summary"],
                    output=last_ev.payload["output"],
                    evidence=last_ev.payload["evidence"]
                )
                print(f"Smith accepting work result for {task_id}...")
                smith_accept_work_result(str(workspace_root), wr, lease.lease_id, "morpheus")
            else:
                print(f"Error: Morpheus did not submit work result for {task_id}.")
                return False
                
        # Assert state shows task is DONE
        events = read_events_v4()
        state = project_state_from_events(events)
        if state.tasks.get(task_id, {}).get("status") != "DONE":
            print(f"Error: Task {task_id} status in state is not DONE: {state.tasks.get(task_id)}")
            return False
            
    # 4. Project verification with Oracle
    print("\n--- Dispatching Oracle Project Verification ---")
    oracle_lease = smith_dispatch_oracle(str(workspace_root), "oracle")
    if not oracle_lease:
        print("Error: Smith could not dispatch Oracle.")
        return False
        
    if dry_run:
        print("[Dry Run] Simulating Oracle PASS report...")
        or_res = OracleResultV4(
            project_id=f"fib-v4-run-{run_index}",
            task_id="none",
            status="PASS",
            evidence_paths=["src/main.py", "tests/test_main.py"],
            summary="All Fibonacci E2E dry-run requirements satisfied."
        )
        smith_handle_oracle_result(str(workspace_root), or_res, oracle_lease.lease_id, "oracle")
    else:
        print("Starting Oracle Runner...")
        runner = V4OracleRunner(str(workspace_root), oracle_lease, actor="oracle")
        res = runner.run(max_turns=25)
        print(f"Oracle result: {res}")
        
        events = read_events_v4()
        last_ev = events[-1]
        if last_ev.event_type not in ("oracle_passed", "oracle_failed"):
            for ev in reversed(events):
                if ev.event_type in ("oracle_passed", "oracle_failed"):
                    last_ev = ev
                    break
                    
        if last_ev.event_type in ("oracle_passed", "oracle_failed"):
            oracle_status = "PASS" if last_ev.event_type == "oracle_passed" else "FAIL"
            or_res = OracleResultV4(
                project_id=f"fib-v4-run-{run_index}",
                task_id="none",
                status=oracle_status,
                evidence_paths=last_ev.payload.get("evidence_paths", []),
                summary=last_ev.payload.get("summary", "")
            )
            print("Smith handling OracleResult...")
            smith_handle_oracle_result(str(workspace_root), or_res, oracle_lease.lease_id, "oracle")
        else:
            print("Error: Oracle did not submit a verification report.")
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
    import subprocess
    env = os.environ.copy()
    ws_root_str = str(workspace_root)
    env["PYTHONPATH"] = f"{ws_root_str}:{ws_root_str}/src:" + env.get("PYTHONPATH", "")
    
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
        
    print("E2E tests verify successfully!")
    
    # Cleanup
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
    args = parser.parse_args()
    
    successes = 0
    for idx in range(1, args.repeat + 1):
        try:
            passed = run_single_e2e(idx, dry_run=args.dry_run)
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
