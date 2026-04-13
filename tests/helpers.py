from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.runtime.dispatcher import RuntimeDispatcher


class ControlPlaneHarness:
    def __init__(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.db_path = self.tmp_path / "control.sqlite3"
        self.state_dir = self.tmp_path / "runtime"
        self.store = ControlPlaneStore(self.db_path)

    def cleanup(self) -> None:
        self._tmpdir.cleanup()


def seed_project(
    store: ControlPlaneStore,
    *,
    project_id: str,
    goal: str,
    current_phase: str,
    current_owner_agent: str,
    project_status: str = "ACTIVE",
    runtime_status: str = "READY",
    priority: str = "MEDIUM",
    next_action: dict[str, Any] | None = None,
    workspace_ref: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    store.upsert(
        "projects",
        {
            "project_id": project_id,
            "goal": goal,
            "project_status": project_status,
            "runtime_status": runtime_status,
            "priority": priority,
            "current_phase": current_phase,
            "current_owner_agent": current_owner_agent,
            "assigned_project_orchestrator": "niobe",
            "assigned_software_orchestrator": "morpheus",
            "next_action_json": next_action or {},
            "workspace_ref": workspace_ref,
            "last_snapshot_id": None,
            "last_activity_at": now,
            "created_at": now,
            "updated_at": now,
        },
        conflict_columns=["project_id"],
    )
    store.upsert(
        "scheduling_records",
        {
            "project_id": project_id,
            "queue_state": "normal_ready",
            "eligible_for_scheduling": True,
            "pause_requested": False,
            "resume_requested": False,
            "preemption_allowed": True,
            "waiting_reason": None,
            "last_scheduled_at": now,
            "times_scheduled": 1,
        },
        conflict_columns=["project_id"],
    )
    return store.get_project(project_id) or {}


def queue_task(dispatcher: RuntimeDispatcher, task: dict[str, Any], *, target_agent: str | None = None) -> None:
    reply_stream, reply_topic = dispatcher.router.reply_address_for_task(
        task["project_id"],
        task["task_id"],
        task["task_type"],
    )
    dispatcher.dispatch_plan(
        SimpleNamespace(
            project_id=task["project_id"],
            task_id=task["task_id"],
            target_agent=target_agent or task["to_agent"],
            task_type=task["task_type"],
            reply_stream=reply_stream,
            reply_topic=reply_topic,
            reason=task["goal"],
        )
    )


def drain_worker(worker: Any, *, agent_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        result = worker.process_once(agent_id=agent_id)
        if result is None:
            break
        seen.append(
            {
                "task_id": result.task_id,
                "agent_id": result.agent_id,
                "status": result.status,
            }
        )
    return seen


def run_git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def init_git_workspace(root: Path, *, branch: str = "main") -> tuple[Path, str]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    run_git(workspace, "init")
    run_git(workspace, "config", "user.email", "recovery-tests@example.com")
    run_git(workspace, "config", "user.name", "Recovery Tests")
    run_git(workspace, "checkout", "-B", branch)
    (workspace / "README.md").write_text("seed\n")
    run_git(workspace, "add", "README.md")
    run_git(workspace, "commit", "-m", "seed")
    head = run_git(workspace, "rev-parse", "HEAD")
    return workspace, head
