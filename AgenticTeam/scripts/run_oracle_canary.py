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

from AgenticTeam.scripts.smith_runtime import (
    smith_plan_project,
    smith_dispatch_worker,
    smith_accept_work_result,
    smith_dispatch_oracle,
    smith_handle_oracle_result
)
from AgenticTeam.scripts.oracle_runtime import OracleRunner
from AgenticTeam.scripts.state import project_state_from_events
from AgenticTeam.scripts.events import clear_events, read_events
from AgenticTeam.scripts.contracts import WorkResult

def main():
    parser = argparse.ArgumentParser(description="Oracle Canary")
    parser.add_argument("--fixture", required=True, help="Fixture name (completed_minimal_project or broken_minimal_project)")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--stall-seconds", type=int, default=90)
    parser.add_argument("--expect-fail", action="store_true", help="Expect Oracle to fail the project")
    args = parser.parse_args()
    
    # 1. Setup workspace
    temp_dir = tempfile.mkdtemp(prefix="oracle_canary_")
    workspace_root = Path(temp_dir)
    print(f"Canary workspace created at: {workspace_root}")
    
    os.environ["TEAM_EVENT_FILE"] = str(workspace_root / ".openclaw" / "events.jsonl")
    clear_events()
    
    fixture_path = SCRIPT_DIR.parent / "fixtures" / f"{args.fixture}.md"
    if not fixture_path.exists():
        print(f"Error: Fixture {args.fixture} not found at {fixture_path}")
        sys.exit(1)
        
    shutil.copy(fixture_path, workspace_root / "PROJECT.md")
    
    # 2. Write tasks folder and T001
    tasks_dir = workspace_root / "management" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "T001.md").write_text("# Task T001: Implement CLI\nImplement minimal CLI.\n", encoding="utf-8")
    
    # 3. Plan project
    planned_tasks = [
        {
            "task_id": "T001",
            "title": "Implement CLI"
        }
    ]
    smith_plan_project(str(workspace_root), "canary-oracle-project", "Canary Oracle Project", planned_tasks)
    
    # 4. Write project files based on fixture
    (workspace_root / "src").mkdir(parents=True, exist_ok=True)
    (workspace_root / "tests").mkdir(parents=True, exist_ok=True)
    
    if not args.expect_fail:
        print("Writing completed minimal project files...")
        (workspace_root / "src" / "main.py").write_text("def main():\n    print('Hello World')\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
        (workspace_root / "tests" / "test_main.py").write_text("import src.main as main\ndef test_hello():\n    pass\n", encoding="utf-8")
        (workspace_root / "README.md").write_text("# Completed Project\n", encoding="utf-8")
    else:
        print("Writing broken minimal project files...")
        (workspace_root / "src" / "main.py").write_text("def main():\n    raise ValueError('Broken')\nif __name__ == '__main__':\n    main()\n", encoding="utf-8")
        (workspace_root / "tests" / "test_main.py").write_text("import src.main as main\ndef test_hello():\n    assert False, 'Induced failing test'\n", encoding="utf-8")
        (workspace_root / "README.md").write_text("# Broken Project\n", encoding="utf-8")
        
    # 5. Simulate Worker DONE
    worker_lease = smith_dispatch_worker(str(workspace_root), "T001", "morpheus")
    wr = WorkResult(
        task_id="T001",
        attempt_id=worker_lease.metadata["attempt_id"],
        status="DONE",
        summary="Simulated implementation complete.",
        output={"artifacts": ["src/main.py", "tests/test_main.py", "README.md"]},
        evidence={"tests_passed": True}
    )
    smith_accept_work_result(str(workspace_root), wr, worker_lease.lease_id, "morpheus")
    
    # 6. Dispatch Oracle
    print("Smith dispatching Oracle verification...")
    oracle_lease = smith_dispatch_oracle(str(workspace_root), "oracle")
    if not oracle_lease:
        print("Error: Could not acquire Oracle lease.")
        sys.exit(1)
        
    # 7. Run Oracle Runner
    print("Starting Oracle Runner...")
    runner = OracleRunner(str(workspace_root), oracle_lease, actor="oracle")
    
    start_time = time.time()
    result = runner.run(max_turns=10)
    elapsed = time.time() - start_time
    print(f"Oracle finished in {elapsed:.2f} seconds. Result: {result}")
    
    # 8. Accept result in Smith
    # Read events to find the oracle_passed or oracle_failed event
    events = read_events()
    state = project_state_from_events(events)
    
    # Extract OracleResult from event
    last_event = events[-1]
    if last_event.event_type not in ("oracle_passed", "oracle_failed"):
        # Find it in previous events
        found_ev = None
        for ev in reversed(events):
            if ev.event_type in ("oracle_passed", "oracle_failed"):
                found_ev = ev
                break
        if not found_ev:
            print("Error: Oracle did not emit a passed/failed event.")
            sys.exit(1)
        last_event = found_ev
        
    from AgenticTeam.scripts.contracts import OracleResult
    oracle_status = "PASS" if last_event.event_type == "oracle_passed" else "FAIL"
    or_res = OracleResult(
        project_id=state.project_id,
        task_id="none",
        status=oracle_status,
        evidence_paths=last_event.payload.get("evidence_paths", []),
        summary=last_event.payload.get("summary", "")
    )
    
    print(f"Smith handling OracleResult: {oracle_status}...")
    smith_handle_oracle_result(str(workspace_root), or_res, oracle_lease.lease_id, "oracle")
    
    # Re-project and check final state
    events = read_events()
    state = project_state_from_events(events)
    print(f"Final Project status: {state.phase}")
    print(f"Tasks planned/completed: {list(state.tasks.keys())}")
    
    # 9. Verification
    if args.expect_fail:
        if state.phase != "BLOCKED":
            print(f"Error: Expected project to be BLOCKED, but got {state.phase}")
            sys.exit(1)
        if "T002" not in state.tasks:
            print("Error: Expected repair task T002 to be planned, but not found.")
            sys.exit(1)
        print("Negative canary verified successfully!")
    else:
        if state.phase != "DONE":
            print(f"Error: Expected project to be DONE, but got {state.phase}")
            sys.exit(1)
        print("Positive canary verified successfully!")
        
    # Cleanup temp dir
    shutil.rmtree(temp_dir)
    print("Cleanup completed. Oracle Canary PASSED!")

if __name__ == "__main__":
    main()
