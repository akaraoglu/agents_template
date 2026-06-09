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
    
# Add parent dir so imports work
if str(SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))

from AgenticTeam.scripts.v4_smith import smith_plan_project, smith_dispatch_worker, smith_accept_work_result
from AgenticTeam.scripts.v4_worker import V4WorkerRunner
from AgenticTeam.scripts.v4_state import project_state_from_events
from AgenticTeam.scripts.v4_events import clear_events_v4, read_events_v4
from AgenticTeam.scripts.v4_contracts import WorkResultV4

def main():
    os.environ["OPENCLAW_OLLAMA_NUM_CTX"] = "16384"
    os.environ["OPENCLAW_OLLAMA_MODEL"] = "ollama/gemma3:12b"
    parser = argparse.ArgumentParser(description="V4 Worker Canary")
    parser.add_argument("--fixture", required=True, help="Fixture name (e.g. minimal_python_cli)")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--stall-seconds", type=int, default=90)
    parser.add_argument("--induce-failure", action="store_true", help="Induce a failure to test repair loop")
    args = parser.parse_args()
    
    # 1. Setup workspace
    temp_dir = tempfile.mkdtemp(prefix="worker_canary_")
    workspace_root = Path(temp_dir)
    print(f"Canary workspace created at: {workspace_root}")
    
    # Set V4 environment file path to project-local to isolate from main project
    os.environ["V4_EVENT_FILE"] = str(workspace_root / ".openclaw" / "events.jsonl")
    clear_events_v4()
    
    # Copy fixture file to PROJECT.md
    fixture_path = SCRIPT_DIR.parent / "fixtures" / f"{args.fixture}.md"
    if not fixture_path.exists():
        print(f"Error: Fixture {args.fixture} not found at {fixture_path}")
        sys.exit(1)
        
    shutil.copy(fixture_path, workspace_root / "PROJECT.md")
    
    # 2. Plan project
    planned_tasks = [
        {
            "task_id": "T001",
            "title": "Implement CLI standard library main script, test suite, and README.md"
        }
    ]
    
    print("Initiating Smith Planning...")
    smith_plan_project(str(workspace_root), "canary-project", "Minimal CLI Canary", planned_tasks)
    
    # Write task description file
    tasks_dir = workspace_root / "management" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_content = """# Task T001: Implement CLI standard library main script, test suite, and README.md

## Objective
Implement a single-file Python CLI under `src/main.py` that takes an input and does something. Include `tests/test_main.py` and `README.md`.

## Required Outputs
- `src/main.py`
- `tests/test_main.py`
- `README.md`
"""
    (tasks_dir / "T001.md").write_text(task_content, encoding="utf-8")
    
    # If inducing failure, pre-create a broken main.py or test
    if args.induce_failure:
        print("Inducing failure: creating broken tests/test_main.py...")
        (workspace_root / "tests").mkdir(parents=True, exist_ok=True)
        (workspace_root / "tests" / "test_main.py").write_text("def test_broken(): assert False", encoding="utf-8")
        
    # 3. Dispatch worker
    print("Smith dispatching task T001 to worker...")
    lease = smith_dispatch_worker(str(workspace_root), "T001", "morpheus")
    if not lease:
        print("Error: Could not acquire lease for T001.")
        sys.exit(1)
        
    # Build task pack
    from AgenticTeam.scripts.v4_contracts import TaskPackV4
    task_pack = TaskPackV4(
        project_id="canary-project",
        task_id="T001",
        workspace_root=str(workspace_root),
        allowed_artifacts=["src/main.py", "tests/test_main.py", "README.md"]
    )
    
    # 4. Run worker runner
    print("Starting Morpheus Worker Runner...")
    runner = V4WorkerRunner(task_pack, lease, actor="morpheus")
    
    start_time = time.time()
    result = runner.run(max_turns=12)
    elapsed = time.time() - start_time
    print(f"Morpheus finished in {elapsed:.2f} seconds. Result: {result}")
    
    # Read final state
    events = read_events_v4()
    state = project_state_from_events(events)
    
    print(f"Project status: {state.phase}")
    print(f"Task status in state: {state.tasks.get('T001', {}).get('status')}")
    
    # 5. Verification
    # If it was a success, check artifacts
    if "Success" in result or state.tasks.get("T001", {}).get("status") == "DONE":
        # Validate artifacts exist
        main_py = workspace_root / "src" / "main.py"
        test_main = workspace_root / "tests" / "test_main.py"
        readme = workspace_root / "README.md"
        
        missing = []
        for f in [main_py, test_main, readme]:
            if not f.exists():
                missing.append(f.name)
                
        if missing:
            print(f"Error: Missing expected files: {missing}")
            sys.exit(1)
            
        print("All required files created successfully!")
        
        # Run tests to confirm they pass
        import subprocess
        test_res = subprocess.run(
            f"PYTHONDONTWRITEBYTECODE=1 {sys.executable} -m pytest -q {test_main}",
            shell=True,
            cwd=str(workspace_root),
            capture_output=True,
            text=True
        )
        if test_res.returncode != 0:
            print(f"Error: Tests fail with exit code {test_res.returncode}:\n{test_res.stdout}\n{test_res.stderr}")
            sys.exit(1)
            
        print("Canary tests passed successfully!")
    else:
        # If we expected it to fail or it was blocked
        if args.induce_failure:
            print("Induced failure correctly handled or blocked!")
        else:
            print("Error: Canary task did not complete successfully.")
            sys.exit(1)
            
    # Cleanup temp dir
    shutil.rmtree(temp_dir)
    print("Cleanup completed. Canary PASSED!")
    
if __name__ == "__main__":
    main()
