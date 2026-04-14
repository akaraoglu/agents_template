from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from openclaw_agents.database.store import ControlPlaneStore, utc_now


class StoreMigrationTests(unittest.TestCase):
    def test_legacy_niobe_database_is_migrated_to_niaobe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "control_plane.sqlite3"
            schema_path = (
                Path(__file__).resolve().parents[1] / "openclaw_agents" / "database" / "schema.sql"
            )
            legacy_schema = schema_path.read_text().replace("niaobe", "niobe")
            now = utc_now()

            with sqlite3.connect(db_path) as conn:
                conn.executescript(legacy_schema)
                conn.execute(
                    """
                    INSERT INTO projects (
                      project_id, goal, project_status, runtime_status, priority, current_phase,
                      current_owner_agent, assigned_project_orchestrator, assigned_software_orchestrator,
                      next_action_json, workspace_ref, last_snapshot_id, last_activity_at, created_at, updated_at
                    ) VALUES (
                      'P_legacy', 'legacy project', 'ACTIVE', 'WAITING_EXTERNAL', 'MEDIUM', 'planning',
                      'niobe', 'niobe', 'morpheus', '{"target_agent":"niobe"}',
                      NULL, NULL, ?, ?, ?
                    )
                    """,
                    (now, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO tasks (
                      task_id, project_id, parent_task_id, from_agent, to_agent, current_owner_agent,
                      return_to, task_type, title, goal, priority, status, context_json,
                      expected_output_json, decision_bounds_json, opened_at, updated_at, closed_at
                    ) VALUES (
                      'T_legacy', 'P_legacy', NULL, 'niobe', 'architect', 'niobe',
                      'niobe', 'DESIGN_ARCHITECTURE', 'Legacy architecture', 'Legacy architecture',
                      'MEDIUM', 'RUNNING', '{"target_agent":"niobe"}', '{}', '{}', ?, ?, NULL
                    )
                    """,
                    (now, now),
                )
                conn.execute(
                    """
                    INSERT INTO task_attempts (
                      attempt_id, task_id, project_id, agent_id, attempt_number, status,
                      failure_cause, sandbox_id, workspace_ref, input_artifact_refs_json,
                      output_artifact_refs_json, summary, started_at, finished_at
                    ) VALUES (
                      'attempt_legacy', 'T_legacy', 'P_legacy', 'niobe', 1, 'RUNNING',
                      NULL, NULL, NULL, '[]', '[]', 'legacy', ?, NULL
                    )
                    """,
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO agent_runs (
                      run_id, task_id, project_id, agent_id, model_profile, model_used, runtime_backend,
                      sandbox_id, session_id, result_status, raw_transcript_ref, log_ref, started_at, ended_at, duration_ms
                    ) VALUES (
                      'run_legacy', 'T_legacy', 'P_legacy', 'niobe', 'ollama_reasoning', 'gemma4:31b',
                      'workspace_queue', NULL, NULL, 'RUNNING', NULL, NULL, ?, NULL, NULL
                    )
                    """,
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO orchestrator_leases (
                      orchestrator_id, lease_status, active_project_id, lease_owner_run_id,
                      lease_acquired_at, lease_expires_at, released_at, release_reason, renew_count
                    ) VALUES (
                      'niobe', 'HELD', 'P_legacy', 'run_legacy', ?, ?, NULL, NULL, 0
                    )
                    """,
                    (now, now),
                )
                conn.execute(
                    """
                    INSERT INTO control_events (
                      event_id, project_id, orchestrator_id, command, requested_by, requested_at,
                      args_json, reason, status, result_summary, mirrored_to_zulip, mirrored_message_id
                    ) VALUES (
                      'event_legacy', 'P_legacy', 'niobe', 'STATUS_SNAPSHOT', 'operator', ?,
                      '{"target_agent":"niobe"}', 'legacy', 'APPLIED', '', 0, NULL
                    )
                    """,
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO recovery_events (
                      recovery_id, project_id, orchestrator_id, workspace_ref, failure_mode, action_taken,
                      status, details_json, created_at, completed_at
                    ) VALUES (
                      'recovery_legacy', 'P_legacy', 'niobe', NULL, 'timeout', 'resume',
                      'OPEN', '{"target_agent":"niobe"}', ?, NULL
                    )
                    """,
                    (now,),
                )
                conn.commit()

            store = ControlPlaneStore(db_path=db_path)

            project = store.get_project("P_legacy")
            assert project is not None
            self.assertEqual(project["current_owner_agent"], "niaobe")
            self.assertEqual(project["assigned_project_orchestrator"], "niaobe")
            self.assertEqual(project["next_action_json"]["target_agent"], "niaobe")

            task = store.get_task("T_legacy")
            assert task is not None
            self.assertEqual(task["from_agent"], "niaobe")
            self.assertEqual(task["current_owner_agent"], "niaobe")
            self.assertEqual(task["return_to"], "niaobe")
            self.assertEqual(task["context_json"]["target_agent"], "niaobe")

            lease = store.get_lease("niaobe")
            assert lease is not None
            self.assertEqual(lease["orchestrator_id"], "niaobe")
            self.assertEqual(lease["active_project_id"], "P_legacy")

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                task_attempt = conn.execute(
                    "SELECT agent_id FROM task_attempts WHERE attempt_id = 'attempt_legacy'"
                ).fetchone()
                agent_run = conn.execute(
                    "SELECT agent_id FROM agent_runs WHERE run_id = 'run_legacy'"
                ).fetchone()
                control_event = conn.execute(
                    "SELECT orchestrator_id, args_json FROM control_events WHERE event_id = 'event_legacy'"
                ).fetchone()
                recovery_event = conn.execute(
                    "SELECT orchestrator_id, details_json FROM recovery_events WHERE recovery_id = 'recovery_legacy'"
                ).fetchone()
                migrations = conn.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                    ("2026-04-14-rename-niobe-to-niaobe",),
                ).fetchone()[0]
                lease_schema = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'orchestrator_leases'"
                ).fetchone()["sql"]

            self.assertEqual(task_attempt["agent_id"], "niaobe")
            self.assertEqual(agent_run["agent_id"], "niaobe")
            self.assertEqual(control_event["orchestrator_id"], "niaobe")
            self.assertIn('"niaobe"', control_event["args_json"])
            self.assertEqual(recovery_event["orchestrator_id"], "niaobe")
            self.assertIn('"niaobe"', recovery_event["details_json"])
            self.assertEqual(migrations, 1)
            self.assertIn("niaobe", lease_schema)
            self.assertNotIn("'niobe'", lease_schema)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
