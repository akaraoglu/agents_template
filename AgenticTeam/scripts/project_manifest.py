#!/usr/bin/env python3
"""Stateful project.json manifest manager for AgenticTeam."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict


class TaskState(TypedDict, total=False):
    id: str
    name: str
    status: str  # PENDING, IN_PROGRESS, COMPLETED, BLOCKED
    phase: str   # PLAN, DESIGN, IMPLEMENT, VERIFY
    owner: str   # smith, architect, morpheus, oracle, niaobe
    required_outputs: list[str]
    design_file: str | None
    validation_file: str | None
    test_command: list[str]


class ProjectManifest(TypedDict):
    project_id: str
    active_task: str | None
    status: str  # IN_PROGRESS, COMPLETED, BLOCKED
    phase: str   # PLAN, DESIGN, IMPLEMENT, VERIFY
    owner: str   # smith, architect, morpheus, oracle, niaobe
    tasks: dict[str, TaskState]


def load_manifest(project_path: Path | str) -> ProjectManifest:
    """Loads the project.json manifest from the project root.
    
    If the file does not exist, returns an empty schema template.
    """
    manifest_path = Path(project_path) / "project.json"
    if not manifest_path.is_file():
        return {
            "project_id": Path(project_path).name,
            "active_task": None,
            "status": "IN_PROGRESS",
            "phase": "PLAN",
            "owner": "smith",
            "tasks": {}
        }
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Fallback to repairable baseline if JSON is malformed
        return {
            "project_id": Path(project_path).name,
            "active_task": None,
            "status": "IN_PROGRESS",
            "phase": "PLAN",
            "owner": "smith",
            "tasks": {}
        }


def save_manifest(project_path: Path | str, manifest: ProjectManifest) -> None:
    """Saves the project.json manifest atomically to the project root."""
    manifest_path = Path(project_path) / "project.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(".tmp")
    try:
        temp_path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        temp_path.replace(manifest_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def get_active_task(manifest: ProjectManifest) -> TaskState | None:
    """Returns the details of the currently active task in the manifest."""
    active_id = manifest.get("active_task")
    if not active_id or not manifest.get("tasks"):
        return None
    return manifest["tasks"].get(active_id)


def update_manifest_phase(
    project_path: Path | str, 
    phase: str, 
    owner: str, 
    active_task: str | None = None
) -> ProjectManifest:
    """Transitions the high-level project phase and owner in the manifest."""
    manifest = load_manifest(project_path)
    manifest["phase"] = phase
    manifest["owner"] = owner
    if active_task is not None:
        manifest["active_task"] = active_task
        if active_task in manifest["tasks"]:
            manifest["tasks"][active_task]["phase"] = phase
            manifest["tasks"][active_task]["owner"] = owner
            manifest["tasks"][active_task]["status"] = "IN_PROGRESS"
    save_manifest(project_path, manifest)
    return manifest


def initialize_manifest_from_state(project_path: Path | str, state: dict[str, Any]) -> ProjectManifest:
    """Seeds the project.json manifest using metadata from a legacy prepared state."""
    project_dir = Path(project_path)
    manifest = load_manifest(project_dir)
    
    manifest["project_id"] = state.get("project_id", manifest["project_id"])
    task_id = state.get("task_id", "T001")
    manifest["active_task"] = task_id
    manifest["phase"] = state.get("phase", "IMPLEMENT")
    manifest["owner"] = state.get("role", "morpheus")
    
    # Extract or infer test command
    test_cmd = state.get("team_test_command") or state.get("test_command")
    if not test_cmd and state.get("subteam_test_command"):
        test_cmd = state.get("subteam_test_command")
    if not test_cmd:
        test_cmd = ["python3", "-m", "unittest", "tests/test_main.py"]
        
    required_outputs = state.get("required_output_paths") or []
    
    task_state: TaskState = {
        "id": task_id,
        "name": state.get("task_name", "Active Task"),
        "status": "IN_PROGRESS",
        "phase": manifest["phase"],
        "owner": manifest["owner"],
        "required_outputs": [str(path) for path in required_outputs],
        "design_file": f"management/architecture/{task_id}.md" if manifest["phase"] != "PLAN" else None,
        "validation_file": f"management/validation/{task_id}_REPORT.md" if manifest["phase"] != "PLAN" else None,
        "test_command": [str(part) for part in test_cmd]
    }
    
    manifest["tasks"][task_id] = task_state
    save_manifest(project_dir, manifest)
    return manifest
