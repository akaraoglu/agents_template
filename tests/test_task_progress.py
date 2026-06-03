from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
import sys

if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from smith_task_progress import advance_task, block_task
import smith_task_progress
from task_progress import (
    mark_blocked,
    mark_done,
    merge_plan_and_backlog,
    next_pending,
    parse_backlog,
    parse_plan,
    render_brief,
    render_backlog,
    render_current_task,
)


PLAN_TEXT = """# Plan

## Overview
Build a thing.

## Phases
1. **T001: Core Logic**
   - Do the first part.
2. **T002: Rendering**
   - Do the second part.
3. **T003: CLI**
   - Do the third part.
"""


BACKLOG_TEXT = """# Backlog

## Ready Queue
- [READY] T001: Core Logic
- [PENDING] T002: Rendering
"""


def _ok() -> CompletedProcess[str]:
    return CompletedProcess(args=["bash"], returncode=0, stdout="", stderr="")


class TaskProgressTests(unittest.TestCase):
    def test_parse_and_next_pending(self) -> None:
        plan = parse_plan(PLAN_TEXT)
        backlog = merge_plan_and_backlog(plan, parse_backlog(BACKLOG_TEXT, plan))
        self.assertEqual([task.task_id for task in plan], ["T001", "T002", "T003"])
        self.assertEqual([task.status for task in backlog], ["READY", "PENDING", "PENDING"])
        done = mark_done(backlog, "T001")
        self.assertEqual(done[0].status, "DONE")
        next_task = next_pending(plan, done, "T001")
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task.task_id, "T002")

    def test_blocked_and_rendering(self) -> None:
        plan = parse_plan(PLAN_TEXT)
        backlog = merge_plan_and_backlog(plan, parse_backlog(BACKLOG_TEXT, plan))
        blocked = mark_blocked(backlog, "T002", "Missing dependency")
        self.assertEqual(blocked[1].status, "BLOCKED")
        self.assertEqual(blocked[1].note, "Missing dependency")
        backlog_text = render_backlog(blocked)
        self.assertIn("[BLOCKED] T002: Rendering -- Missing dependency", backlog_text)
        current_text = render_current_task("T002", "Rendering", project_id="demo-project")
        self.assertIn("Task ID: T002", current_text)
        self.assertIn("management/tasks/T002.md", current_text)
        brief_text = render_brief(
            "demo-project",
            active_task_id="T002",
            active_task_title="Rendering",
            next_task_id="T003",
            next_task_title="CLI",
            status_note="Sync before handoff.",
        )
        self.assertIn("Active task: T002: Rendering", brief_text)
        self.assertIn("Next task: T003: CLI", brief_text)
        self.assertIn("Sync before handoff.", brief_text)

    def test_advance_task_updates_backlog_and_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-project"
            (project_dir / "management" / "validation").mkdir(parents=True, exist_ok=True)
            (project_dir / "management").mkdir(parents=True, exist_ok=True)
            (project_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
            (project_dir / "CURRENT_TASK.md").write_text(
                render_current_task("T001", "Core Logic", project_id="demo-project"),
                encoding="utf-8",
            )
            (project_dir / "management" / "PLAN.md").write_text(PLAN_TEXT, encoding="utf-8")
            (project_dir / "management" / "BACKLOG.md").write_text(BACKLOG_TEXT, encoding="utf-8")
            (project_dir / "management" / "validation" / "T001_REPORT.md").write_text(
                "# Report\nPASS: T001\n",
                encoding="utf-8",
            )

            handoff_payload = {
                "project_id": "demo-project",
                "from": "smith",
                "to": "niaobe",
                "phase": "TASK_HANDOFF",
                "task_id": "T002",
                "instructions": "Task T002 is ready.",
            }

            def run_side_effect(cmd: list[str], *, timeout: int = 120) -> CompletedProcess[str]:
                if "write_state.sh" in cmd[1]:
                    return _ok()
                if "handoff.sh" in cmd[1]:
                    return CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout="HANDOFF_READY\nENVELOPE: " + json.dumps(handoff_payload, separators=(",", ":")) + "\n",
                        stderr="",
                    )
                raise AssertionError(f"Unexpected command: {cmd}")

            with mock.patch("smith_task_progress.resolve_project", return_value={"project_path": str(project_dir)}), \
                mock.patch("smith_task_progress.run_command", side_effect=run_side_effect), \
                mock.patch("smith_task_progress.send_session_message", return_value="sent") as send_mock:
                outcome = advance_task("demo-project", "T001")

            self.assertEqual(outcome["status"], "advanced")
            self.assertIn("Activated T002", outcome["message"])
            backlog_text = (project_dir / "management" / "BACKLOG.md").read_text(encoding="utf-8")
            self.assertIn("[DONE] T001: Core Logic", backlog_text)
            self.assertIn("[READY] T002: Rendering", backlog_text)
            current_text = (project_dir / "CURRENT_TASK.md").read_text(encoding="utf-8")
            self.assertIn("Task ID: T002", current_text)
            brief_text = (project_dir / "BRIEF.md").read_text(encoding="utf-8")
            self.assertIn("Active task: T002: Rendering", brief_text)
            self.assertIn("Next task: T003: CLI", brief_text)
            send_mock.assert_called_once()

    def test_advance_task_marks_project_done_when_no_tasks_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-project"
            (project_dir / "management" / "validation").mkdir(parents=True, exist_ok=True)
            (project_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
            (project_dir / "CURRENT_TASK.md").write_text(
                render_current_task("T001", "Core Logic", project_id="demo-project"),
                encoding="utf-8",
            )
            plan_text = """# Plan

## Overview
One task only.

## Phases
1. **T001: Core Logic**
   - Do the first part.
"""
            backlog_text = """# Backlog

## Ready Queue
- [READY] T001: Core Logic
"""
            (project_dir / "management" / "PLAN.md").write_text(plan_text, encoding="utf-8")
            (project_dir / "management" / "BACKLOG.md").write_text(backlog_text, encoding="utf-8")
            (project_dir / "management" / "validation" / "T001_REPORT.md").write_text(
                "# Report\nPASS: T001\n",
                encoding="utf-8",
            )

            def run_side_effect(cmd: list[str], *, timeout: int = 120) -> CompletedProcess[str]:
                if "write_state.sh" in cmd[1]:
                    return _ok()
                raise AssertionError(f"Unexpected command: {cmd}")

            with mock.patch("smith_task_progress.resolve_project", return_value={"project_path": str(project_dir)}), \
                mock.patch("smith_task_progress.run_command", side_effect=run_side_effect), \
                mock.patch("smith_task_progress.send_session_message", return_value="sent") as send_mock:
                outcome = advance_task("demo-project", "T001")

            self.assertEqual(outcome["status"], "done")
            self.assertIn("Project complete", outcome["message"])
            current_text = (project_dir / "CURRENT_TASK.md").read_text(encoding="utf-8")
            self.assertIn("Task ID: none", current_text)
            send_mock.assert_called_once()

    def test_block_task_records_blocker_without_advancing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-project"
            (project_dir / "management" / "validation").mkdir(parents=True, exist_ok=True)
            (project_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
            (project_dir / "CURRENT_TASK.md").write_text(
                render_current_task("T002", "Rendering", project_id="demo-project"),
                encoding="utf-8",
            )
            (project_dir / "management" / "PLAN.md").write_text(PLAN_TEXT, encoding="utf-8")
            (project_dir / "management" / "BACKLOG.md").write_text(BACKLOG_TEXT, encoding="utf-8")

            def run_side_effect(cmd: list[str], *, timeout: int = 120) -> CompletedProcess[str]:
                if "write_state.sh" in cmd[1]:
                    return _ok()
                raise AssertionError(f"Unexpected command: {cmd}")

            with mock.patch("smith_task_progress.resolve_project", return_value={"project_path": str(project_dir)}), \
                mock.patch("smith_task_progress.run_command", side_effect=run_side_effect), \
                mock.patch("smith_task_progress.send_session_message") as send_mock:
                outcome = block_task("demo-project", "T002", "Missing dependency")

            self.assertEqual(outcome["status"], "blocked")
            backlog_text = (project_dir / "management" / "BACKLOG.md").read_text(encoding="utf-8")
            self.assertIn("[BLOCKED] T002: Rendering -- Missing dependency", backlog_text)
            current_text = (project_dir / "CURRENT_TASK.md").read_text(encoding="utf-8")
            self.assertIn("status**: blocked", current_text)
            brief_text = (project_dir / "BRIEF.md").read_text(encoding="utf-8")
            self.assertIn("Task T002 is blocked", brief_text)
            send_mock.assert_not_called()

    def test_duplicate_task_done_is_stale_and_does_not_advance_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-project"
            (project_dir / "management" / "validation").mkdir(parents=True, exist_ok=True)
            (project_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
            (project_dir / "CURRENT_TASK.md").write_text(
                render_current_task("T002", "Rendering", project_id="demo-project"),
                encoding="utf-8",
            )
            (project_dir / "management" / "PLAN.md").write_text(PLAN_TEXT, encoding="utf-8")
            (project_dir / "management" / "BACKLOG.md").write_text(BACKLOG_TEXT, encoding="utf-8")

            with mock.patch("smith_task_progress.resolve_project", return_value={"project_path": str(project_dir)}), \
                mock.patch("smith_task_progress.run_command") as run_mock, \
                mock.patch("smith_task_progress.send_session_message") as send_mock:
                outcome = advance_task("demo-project", "T001")

            self.assertEqual(outcome["status"], "stale")
            self.assertIn("ignoring duplicate TASK_DONE", outcome["message"])
            run_mock.assert_not_called()
            send_mock.assert_not_called()

    def test_sync_task_docs_repairs_stale_current_task_and_writes_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-project"
            (project_dir / "management" / "validation").mkdir(parents=True, exist_ok=True)
            (project_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
            (project_dir / "CURRENT_TASK.md").write_text(
                render_current_task("T001", "Core Logic", project_id="demo-project"),
                encoding="utf-8",
            )
            (project_dir / "BRIEF.md").write_text("# stale brief\n", encoding="utf-8")
            (project_dir / "management" / "PLAN.md").write_text(PLAN_TEXT, encoding="utf-8")
            (project_dir / "management" / "BACKLOG.md").write_text(BACKLOG_TEXT, encoding="utf-8")
            (project_dir / "PROJECT_STATE.md").write_text(
                """# Project State

## Status
- **active_task**: T002
- **last_completed_task**: T001
- **phase**: PLANNING
- **owner**: smith
- **waiting_for**: niaobe
""",
                encoding="utf-8",
            )

            with mock.patch("smith_task_progress.resolve_project", return_value={"project_path": str(project_dir)}):
                outcome = smith_task_progress._sync_task_docs_from_state(project_dir, "demo-project")

            self.assertEqual(outcome["status"], "synced")
            current_text = (project_dir / "CURRENT_TASK.md").read_text(encoding="utf-8")
            self.assertIn("Task ID: T002", current_text)
            backlog_text = (project_dir / "management" / "BACKLOG.md").read_text(encoding="utf-8")
            self.assertIn("[DONE] T001: Core Logic", backlog_text)
            self.assertIn("[READY] T002: Rendering", backlog_text)
            brief_text = (project_dir / "BRIEF.md").read_text(encoding="utf-8")
            self.assertIn("Active task: T002: Rendering", brief_text)
            self.assertIn("Next task: T003: CLI", brief_text)


if __name__ == "__main__":
    unittest.main()
