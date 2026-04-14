from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from openclaw_agents.database.project_store_migrator import ProjectStoreMigrator
from openclaw_agents.database.store import utc_now
from openclaw_agents.runtime.project_state import ProjectStateLayout

from tests.helpers import ControlPlaneHarness


class ProjectStoreMigratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _seed_legacy_shared_project(self, *, project_id: str) -> tuple[Path, str]:
        workspace = self.harness.tmp_path / "projects" / project_id
        workspace.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        with sqlite3.connect(self.harness.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO projects (
                  project_id, goal, project_status, runtime_status, priority, current_phase,
                  current_owner_agent, assigned_project_orchestrator, assigned_software_orchestrator,
                  next_action_json, workspace_ref, last_snapshot_id, last_activity_at, created_at, updated_at
                ) VALUES (?, ?, 'ACTIVE', 'WAITING_EXTERNAL', 'MEDIUM', 'software_implementation',
                          'implementer', 'niaobe', 'morpheus', '{}', ?, NULL, ?, ?, ?)
                """,
                (project_id, "Legacy project", str(workspace), now, now, now),
            )
            conn.execute(
                """
                INSERT INTO scheduling_records (
                  project_id, queue_state, eligible_for_scheduling, pause_requested, resume_requested,
                  preemption_allowed, waiting_reason, last_scheduled_at, times_scheduled
                ) VALUES (?, 'waiting_external', 0, 0, 0, 0, 'legacy', ?, 1)
                """,
                (project_id, now),
            )
            conn.execute(
                """
                INSERT INTO workspace_states (
                  workspace_ref, project_id, repo_root, branch_or_worktree_id,
                  last_clean_commit_or_checkpoint, is_consistent, last_validated_at, last_validation_summary
                ) VALUES (?, ?, ?, ?, 'initial-provision', 1, ?, 'legacy workspace')
                """,
                (str(workspace), project_id, str(workspace), project_id, now),
            )
            conn.execute(
                """
                INSERT INTO tasks (
                  task_id, project_id, parent_task_id, from_agent, to_agent, current_owner_agent,
                  return_to, task_type, title, goal, priority, status, context_json,
                  expected_output_json, decision_bounds_json, opened_at, updated_at, closed_at
                ) VALUES (
                  'T_legacy', ?, NULL, 'morpheus', 'implementer', 'implementer',
                  'morpheus', 'IMPLEMENT_SOFTWARE_TASK', 'Implement legacy task', 'Implement legacy task',
                  'MEDIUM', 'BLOCKED', '{}', '{}', '{}', ?, ?, ?
                )
                """,
                (project_id, now, now, now),
            )
            conn.execute(
                """
                INSERT INTO task_attempts (
                  attempt_id, task_id, project_id, agent_id, attempt_number, status, failure_cause,
                  sandbox_id, workspace_ref, input_artifact_refs_json, output_artifact_refs_json,
                  summary, started_at, finished_at
                ) VALUES (
                  'attempt_legacy', 'T_legacy', ?, 'implementer', 1, 'BLOCKED', 'ENVIRONMENT_FAILURE',
                  NULL, ?, '[]', '[]', 'legacy blocked', ?, ?
                )
                """,
                (project_id, str(workspace), now, now),
            )
            conn.execute(
                """
                INSERT INTO agent_runs (
                  run_id, task_id, project_id, agent_id, model_profile, model_used, runtime_backend,
                  sandbox_id, session_id, result_status, raw_transcript_ref, log_ref, started_at, ended_at, duration_ms
                ) VALUES (
                  'run_legacy', 'T_legacy', ?, 'implementer', 'ollama_coding', 'gemma4:31b', 'workspace_queue',
                  NULL, NULL, 'BLOCKED', NULL, ?, ?, ?, 1000
                )
                """,
                (project_id, str(workspace / "legacy.log"), now, now),
            )
            conn.execute(
                """
                INSERT INTO artifacts (
                  artifact_id, project_id, task_id, produced_by_agent, artifact_type, store_backend, ref,
                  content_hash, metadata_json, created_at
                ) VALUES (
                  'artifact_legacy', ?, 'T_legacy', 'implementer', 'escalation_packet', 'inline_json',
                  'inline://artifact_legacy', NULL, ?, ?
                )
                """,
                (project_id, '{"payload": {"summary": "legacy escalation"}}', now),
            )
            conn.execute(
                """
                INSERT INTO zulip_message_links (
                  link_id, project_id, task_id, control_event_id, zulip_message_id, stream_name, topic_name,
                  direction, message_kind, linked_entity_type, linked_entity_id, created_at
                ) VALUES (
                  'zulip_legacy', ?, 'T_legacy', NULL, '12345', 'projects', 'legacy-topic',
                  'outbound', 'task_result', 'task', 'T_legacy', ?
                )
                """,
                (project_id, now),
            )
            conn.commit()
        return workspace, now

    def test_migrate_project_moves_shared_state_into_project_db_and_purges_shared_rows(self) -> None:
        project_id = "P_legacy_migration"
        workspace, _ = self._seed_legacy_shared_project(project_id=project_id)
        migrator = ProjectStoreMigrator(self.harness.store)

        report = migrator.migrate_project(project_id, purge_shared=True)

        self.assertTrue(report.migrated)
        assert report.project_db_path is not None
        project_db_path = Path(report.project_db_path)
        self.assertTrue(project_db_path.exists())
        layout = ProjectStateLayout.from_workspace(workspace)
        self.assertEqual(project_db_path, layout.project_db_path)

        with sqlite3.connect(project_db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project_id,)).fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM artifacts WHERE project_id = ?", (project_id,)).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM zulip_message_links WHERE project_id = ?", (project_id,)).fetchone()[0],
                1,
            )

        with sqlite3.connect(self.harness.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project_id,)).fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM artifacts WHERE project_id = ?", (project_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM zulip_message_links WHERE project_id = ?", (project_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM projects WHERE project_id = ?", (project_id,)).fetchone()[0],
                1,
            )

        task = self.harness.store.get_task("T_legacy")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["project_id"], project_id)
        self.assertEqual(self.harness.store.get_workspace_state(str(workspace))["project_id"], project_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
