#!/usr/bin/env python3
"""Workflow Orchestrator for coordinating AgenticTeam state transitions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_manifest import load_manifest, save_manifest, update_manifest_phase


def print_status(project_path: Path) -> None:
    """Prints a beautiful summary of the project state and task list."""
    manifest = load_manifest(project_path)
    print("\n==================================================")
    print(f"📁 PROJECT ORCHESTRATOR STATUS: {manifest.get('project_id')}")
    print("==================================================")
    print(f"  Overall Status : {manifest.get('status')}")
    print(f"  Current Phase  : {manifest.get('phase')}")
    print(f"  Active Owner   : {manifest.get('owner', '').upper()}")
    print(f"  Active Task ID : {manifest.get('active_task')}")
    print("--------------------------------------------------")
    print("📋 TASK TRACKING:")
    
    tasks = manifest.get("tasks", {})
    if not tasks:
        print("  No tasks defined.")
    for tid, task in tasks.items():
        status_symbol = "●" if task.get("status") == "COMPLETED" else "○"
        print(f"  [{status_symbol}] {tid}: {task.get('name')} | Phase: {task.get('phase')} | Owner: {task.get('owner', '').upper()} | Status: {task.get('status')}")
    print("==================================================\n")


def transition_phase(project_path: Path, phase: str, owner: str, task_id: str | None = None) -> None:
    """Transitions the orchestrator state to a new phase and owner."""
    print(f"Transitioning project phase to: Phase={phase}, Owner={owner.upper()}...")
    manifest = update_manifest_phase(project_path, phase, owner, active_task=task_id)
    print("Manifest successfully updated.")
    print_status(project_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgenticTeam Workflow Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show current project state and task list")
    status_parser.add_argument("project_dir", help="Path to the active project root directory")
    
    # Transition command
    trans_parser = subparsers.add_parser("transition", help="Transition active task phase and owner")
    trans_parser.add_argument("project_dir", help="Path to the active project root directory")
    trans_parser.add_argument("--phase", required=True, choices=["PLAN", "DESIGN", "IMPLEMENT", "VERIFY"], help="Target phase")
    trans_parser.add_argument("--owner", required=True, choices=["smith", "architect", "morpheus", "oracle", "niaobe"], help="Target owner agent")
    trans_parser.add_argument("--task-id", help="Active task ID")

    args = parser.parse_args()
    project_path = Path(args.project_dir)
    
    if not project_path.is_dir():
        print(f"Error: Project directory does not exist: {project_path}", file=sys.stderr)
        sys.exit(1)
        
    if args.command == "status":
        print_status(project_path)
    elif args.command == "transition":
        transition_phase(project_path, args.phase, args.owner, args.task_id)


if __name__ == "__main__":
    main()
