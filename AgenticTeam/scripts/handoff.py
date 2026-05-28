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
    
    # 1. Version Control: Git Stage and Commit Milestone
    print("\n[Git Checkpoint] Staging output artifacts...")
    for art in artifacts:
        art_path = project_path / art
        if art_path.is_file():
            subprocess.run(["git", "add", art], cwd=str(project_path), check=True)
            print(f"  Staged: {art}")
        else:
            print(f"  Warning: Artifact file missing in workspace: {art}", file=sys.stderr)
            
    commit_msg = f"[{state.get('phase', 'WORK')}] {task_id} handoff to {args.target}: {args.summary}"
    try:
        # Check if there are any staged changes before committing
        status_proc = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], 
            cwd=str(project_path)
        )
        if status_proc.returncode == 1:  # Staged changes exist
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(project_path), check=True)
            print(f"[Git Checkpoint] Committed milestone successfully: \"{commit_msg}\"")
        else:
            print("[Git Checkpoint] No changes staged. Skipping commit.")
    except subprocess.CalledProcessError as exc:
        print(f"Warning: Git commit failed: {exc}", file=sys.stderr)
        
    # 2. Centralized State: Update the project.json manifest
    print("\n[Manifest State] Updating centralized project.json...")
    manifest = update_manifest_phase(project_path, next_phase, args.target, active_task=task_id)
    
    # Mark task as completed if returning to Niaobe or Oracle
    if args.target in {"niaobe", "oracle"} and task_id in manifest["tasks"]:
        manifest["tasks"][task_id]["status"] = "COMPLETED"
        save_manifest(project_path, manifest)
        
    print(f"[Manifest State] Project state transitioned to: Phase={next_phase}, Owner={args.target.upper()}")
    print("\nHandoff milestone completed successfully. Ready for next agent activation.")


if __name__ == "__main__":
    main()
