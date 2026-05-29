#!/usr/bin/env python3
"""Programmatic handoff tool for AgenticTeam."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import subprocess

from project_manifest import load_manifest, save_manifest, update_manifest_phase


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Handoff task ownership and commit milestones.")
    parser.add_argument("--run-dir", required=True, help="Active worker run directory containing state.json")
    parser.add_argument("--target", required=True, choices=["smith", "architect", "morpheus", "oracle", "niaobe"], help="Target agent role")
    parser.add_argument("--summary", required=True, help="Summary of work completed")
    parser.add_argument("--artifacts", required=True, help="Comma-separated relative paths of created/modified artifacts")
    return parser.parse_args()


def load_run_state(run_dir: Path) -> dict:
    import json
    state_file = run_dir / "state.json"
    if not state_file.is_file():
        print(f"Error: Run state file missing at {state_file}", file=sys.stderr)
        sys.exit(1)
    return json.loads(state_file.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    state = load_run_state(run_dir)
    
    project_path_str = state.get("project_path")
    if not project_path_str:
        print("Error: project_path is missing from run state.json", file=sys.stderr)
        sys.exit(1)
        
    project_path = Path(project_path_str)
    if not project_path.is_dir():
        print(f"Error: Active project directory does not exist: {project_path}", file=sys.stderr)
        sys.exit(1)
        
    artifacts = [path.strip() for path in args.artifacts.split(",") if path.strip()]
    task_id = state.get("task_id", "T001")
    
    # Map target agent to next lifecycle phase
    phase_mapping = {
        "smith": "PLAN",
        "architect": "DESIGN",
        "morpheus": "IMPLEMENT",
        "oracle": "VERIFY",
        "niaobe": "IMPLEMENT"  # Niaobe reviews and delegates
    }
    next_phase = phase_mapping.get(args.target, "IMPLEMENT")
    
    print(f"--- Initiating Handoff to {args.target.upper()} ---")
    print(f"Project path: {project_path}")
    print(f"Task ID: {task_id}")
    print(f"Artifacts: {', '.join(artifacts)}")
    print(f"Summary: {args.summary}")
    
    # 1. Version Control: Removed intermediate Git staging as per instructions.
    print("\n[Version Control] Intermediate Git staging is disabled at this stage.")
        
    # 2. Centralized State: Update the project.json manifest
    print("\n[Manifest State] Updating centralized project.json...")
    manifest = update_manifest_phase(project_path, next_phase, args.target, active_task=task_id)
    
    # Mark task as completed if returning to Niaobe or Oracle
    if args.target in {"niaobe", "oracle"} and task_id in manifest["tasks"]:
        manifest["tasks"][task_id]["status"] = "COMPLETED"
        save_manifest(project_path, manifest)
        
    print(f"[Manifest State] Project state transitioned to: Phase={next_phase}, Owner={args.target.upper()}")
    
    # 3. OpenClaw Ledger: Record handoff_sent event for receiver acknowledgement
    print("\n[Ledger State] Recording handoff_sent event...")
    from_agent = state.get("role") or manifest.get("owner") or "neo"
    current_phase = state.get("phase") or manifest.get("phase") or "HANDOFF"
    project_id = manifest.get("project_id", project_path.name)
    
    handoff_event = {
        "event_type": "handoff_sent",
        "project_id": project_id,
        "from": from_agent,
        "to": args.target,
        "phase": current_phase,
        "task_id": task_id
    }
    
    ledger_path = project_path / ".openclaw" / "handoffs.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        import json
        f.write(json.dumps(handoff_event) + "\n")
    print(f"[Ledger State] Recorded handoff_sent event to {ledger_path.name}")
    
    print("\nHandoff milestone completed successfully. Ready for next agent activation.")


if __name__ == "__main__":
    main()
