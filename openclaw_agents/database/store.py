"""SQLite-backed persistence helpers for the control plane.

This module intentionally stays small and explicit. It provides the minimal
storage operations needed by the scheduler and communication layers without
trying to hide the schema behind a heavy ORM.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse timestamps persisted by this module."""
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return value


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key.endswith("_json") and isinstance(value, str):
            try:
                result[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        result[key] = value
    return result


class ControlPlaneStore:
    """Low-level storage wrapper around the SQLite control-plane database."""

    def __init__(self, db_path: str | Path | None = None, *, initialize: bool = True) -> None:
        if db_path is None:
            db_path = os.environ.get("OPENCLAW_DB_PATH", "/tmp/openclaw_agents_control_plane.sqlite3")
        self.db_path = str(db_path)
        if initialize:
            self.initialize_schema()
            self.ensure_orchestrator_leases()

    @property
    def schema_path(self) -> Path:
        return Path(__file__).with_name("schema.sql")

    def connection(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterable[sqlite3.Connection]:
        conn = self.connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        with self.transaction() as conn:
            conn.executescript(self.schema_path.read_text())

    def execute(self, sql: str, params: Iterable[Any] = (), *, conn: sqlite3.Connection | None = None) -> int:
        normalized = tuple(_normalize_value(value) for value in params)
        if conn is not None:
            cursor = conn.execute(sql, normalized)
            return cursor.rowcount
        with self.transaction() as local_conn:
            cursor = local_conn.execute(sql, normalized)
            return cursor.rowcount

    def fetchone(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        normalized = tuple(_normalize_value(value) for value in params)
        if conn is not None:
            return _row_to_dict(conn.execute(sql, normalized).fetchone())
        with self.connection() as local_conn:
            return _row_to_dict(local_conn.execute(sql, normalized).fetchone())

    def fetchall(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        normalized = tuple(_normalize_value(value) for value in params)
        if conn is not None:
            rows = conn.execute(sql, normalized).fetchall()
        else:
            with self.connection() as local_conn:
                rows = local_conn.execute(sql, normalized).fetchall()
        return [_row_to_dict(row) or {} for row in rows]

    def upsert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        conflict_columns: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        columns = list(data.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = [column for column in columns if column not in conflict_columns]
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(conflict_columns)}) DO "
        )
        if updates:
            sql += "UPDATE SET " + ", ".join(f"{column} = excluded.{column}" for column in updates)
        else:
            sql += "NOTHING"
        self.execute(sql, [_normalize_value(data[column]) for column in columns], conn=conn)

    def update(
        self,
        table: str,
        data: dict[str, Any],
        *,
        where_clause: str,
        where_params: Iterable[Any],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        assignments = ", ".join(f"{column} = ?" for column in data)
        params = [_normalize_value(data[column]) for column in data]
        params.extend(_normalize_value(value) for value in where_params)
        sql = f"UPDATE {table} SET {assignments} WHERE {where_clause}"
        return self.execute(sql, params, conn=conn)

    def ensure_orchestrator_leases(self) -> None:
        with self.transaction() as conn:
            for orchestrator_id in ("niobe", "morpheus"):
                conn.execute(
                    """
                    INSERT INTO orchestrator_leases (
                      orchestrator_id,
                      lease_status,
                      active_project_id,
                      lease_owner_run_id,
                      lease_acquired_at,
                      lease_expires_at
                    ) VALUES (?, 'FREE', NULL, NULL, NULL, NULL)
                    ON CONFLICT (orchestrator_id) DO NOTHING
                    """,
                    (orchestrator_id,),
                )

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def get_project(self, project_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        return self.fetchone("SELECT * FROM projects WHERE project_id = ?", (project_id,), conn=conn)

    def get_task(self, task_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        return self.fetchone("SELECT * FROM tasks WHERE task_id = ?", (task_id,), conn=conn)

    def get_scheduling_record(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone("SELECT * FROM scheduling_records WHERE project_id = ?", (project_id,), conn=conn)

    def get_workspace_state(
        self,
        workspace_ref: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone("SELECT * FROM workspace_states WHERE workspace_ref = ?", (workspace_ref,), conn=conn)

    def get_lease(
        self,
        orchestrator_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone(
            "SELECT * FROM orchestrator_leases WHERE orchestrator_id = ?",
            (orchestrator_id,),
            conn=conn,
        )

    def get_latest_snapshot(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone(
            """
            SELECT *
            FROM project_snapshots
            WHERE project_id = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (project_id,),
            conn=conn,
        )

    def list_open_tasks(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT *
            FROM tasks
            WHERE project_id = ?
              AND status NOT IN ('SUCCESS', 'FAILED', 'CANCELLED')
            ORDER BY opened_at ASC
            """,
            (project_id,),
            conn=conn,
        )

    def list_child_tasks(
        self,
        parent_task_id: str,
        *,
        task_type: str | None = None,
        include_terminal: bool = True,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT *
            FROM tasks
            WHERE parent_task_id = ?
        """
        params: list[Any] = [parent_task_id]
        if task_type:
            sql += " AND task_type = ?"
            params.append(task_type)
        if not include_terminal:
            sql += " AND status NOT IN ('SUCCESS', 'FAILED', 'CANCELLED')"
        sql += " ORDER BY opened_at ASC"
        return self.fetchall(sql, params, conn=conn)

    def get_latest_child_task(
        self,
        parent_task_id: str,
        *,
        task_type: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        sql = """
            SELECT *
            FROM tasks
            WHERE parent_task_id = ?
        """
        params: list[Any] = [parent_task_id]
        if task_type:
            sql += " AND task_type = ?"
            params.append(task_type)
        sql += " ORDER BY opened_at DESC LIMIT 1"
        return self.fetchone(sql, params, conn=conn)

    def list_task_attempts(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT *
            FROM task_attempts
            WHERE task_id = ?
            ORDER BY attempt_number ASC
            """,
            (task_id,),
            conn=conn,
        )

    def list_project_active_task_attempts(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT *
            FROM task_attempts
            WHERE project_id = ?
              AND status IN ('PENDING', 'RUNNING')
              AND finished_at IS NULL
            ORDER BY started_at ASC
            """,
            (project_id,),
            conn=conn,
        )

    def get_latest_task_attempt(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone(
            """
            SELECT *
            FROM task_attempts
            WHERE task_id = ?
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (task_id,),
            conn=conn,
        )

    def get_active_task_attempt(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self.fetchone(
            """
            SELECT *
            FROM task_attempts
            WHERE task_id = ?
              AND status IN ('PENDING', 'RUNNING')
              AND finished_at IS NULL
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (task_id,),
            conn=conn,
        )

    def get_agent_run(self, run_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        return self.fetchone("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,), conn=conn)

    def list_agent_runs(
        self,
        *,
        task_id: str | None = None,
        project_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM agent_runs WHERE 1=1"
        params: list[Any] = []
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY started_at ASC"
        return self.fetchall(sql, params, conn=conn)

    def list_project_active_agent_runs(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT *
            FROM agent_runs
            WHERE project_id = ?
              AND result_status = 'RUNNING'
              AND ended_at IS NULL
            ORDER BY started_at ASC
            """,
            (project_id,),
            conn=conn,
        )

    def list_pending_runtime_runs(
        self,
        *,
        runtime_backend: str = "workspace_queue",
        agent_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
              ar.*,
              t.to_agent,
              t.task_type,
              t.goal,
              t.project_id AS task_project_id,
              p.workspace_ref
            FROM agent_runs AS ar
            JOIN tasks AS t ON t.task_id = ar.task_id
            JOIN projects AS p ON p.project_id = ar.project_id
            WHERE ar.runtime_backend = ?
              AND ar.result_status = 'PENDING'
        """
        params: list[Any] = [runtime_backend]
        if agent_id:
            sql += " AND ar.agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY ar.started_at ASC"
        return self.fetchall(sql, params, conn=conn)

    def list_result_mirror_candidates(
        self,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT
              t.task_id,
              t.project_id,
              t.task_type,
              t.status,
              t.from_agent,
              t.return_to,
              t.updated_at,
              ta.attempt_id,
              ta.agent_id AS attempt_agent_id,
              ta.summary AS attempt_summary,
              ta.output_artifact_refs_json,
              p.current_owner_agent,
              p.assigned_project_orchestrator,
              p.assigned_software_orchestrator,
              p.next_action_json
            FROM tasks AS t
            JOIN task_attempts AS ta
              ON ta.attempt_id = (
                SELECT attempt_id
                FROM task_attempts
                WHERE task_id = t.task_id
                ORDER BY attempt_number DESC
                LIMIT 1
              )
            JOIN projects AS p ON p.project_id = t.project_id
            LEFT JOIN (
              SELECT task_id, MAX(created_at) AS last_mirrored_at
              FROM zulip_message_links
              WHERE direction = 'outbound'
                AND message_kind = 'task_result'
              GROUP BY task_id
            ) AS mirrored
              ON mirrored.task_id = t.task_id
            WHERE t.status IN ('SUCCESS', 'NEEDS_CLARIFICATION', 'BLOCKED', 'FAILED', 'CANCELLED')
              AND ta.agent_id NOT IN ('planner', 'implementer', 'tester')
              AND (mirrored.last_mirrored_at IS NULL OR mirrored.last_mirrored_at < t.updated_at)
            ORDER BY t.updated_at ASC
            """,
            conn=conn,
        )

    def next_attempt_number(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        row = self.fetchone(
            "SELECT COALESCE(MAX(attempt_number), 0) AS max_attempt FROM task_attempts WHERE task_id = ?",
            (task_id,),
            conn=conn,
        )
        return int((row or {}).get("max_attempt") or 0) + 1

    def claim_agent_run(
        self,
        run_id: str,
        *,
        started_at: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        started_at = started_at or utc_now()
        rowcount = self.update(
            "agent_runs",
            {"result_status": "RUNNING", "started_at": started_at},
            where_clause="run_id = ? AND result_status = 'PENDING'",
            where_params=[run_id],
            conn=conn,
        )
        return bool(rowcount)

    def list_recent_artifact_refs(
        self,
        project_id: str,
        *,
        limit: int = 20,
        conn: sqlite3.Connection | None = None,
    ) -> list[str]:
        rows = self.fetchall(
            """
            SELECT ref
            FROM artifacts
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
            conn=conn,
        )
        return [row["ref"] for row in rows]

    def list_projects_for_scheduler(
        self,
        orchestrator_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        orchestrator_column = (
            "assigned_project_orchestrator" if orchestrator_id == "niobe" else "assigned_software_orchestrator"
        )
        return self.fetchall(
            f"""
            SELECT
              p.*,
              s.queue_state,
              s.eligible_for_scheduling,
              s.pause_requested,
              s.resume_requested,
              s.preemption_allowed,
              s.waiting_reason,
              s.last_scheduled_at,
              s.times_scheduled,
              s.fairness_deadline_at,
              s.last_switch_reason,
              s.current_safe_boundary_type,
              ps.safe_boundary_type AS last_snapshot_safe_boundary_type,
              ws.repo_root,
              ws.branch_or_worktree_id,
              ws.last_clean_commit_or_checkpoint,
              ws.is_consistent,
              ws.last_validated_at
            FROM projects AS p
            LEFT JOIN scheduling_records AS s ON s.project_id = p.project_id
            LEFT JOIN project_snapshots AS ps ON ps.snapshot_id = p.last_snapshot_id
            LEFT JOIN workspace_states AS ws ON ws.workspace_ref = p.workspace_ref
            WHERE p.{orchestrator_column} = ?
            """,
            (orchestrator_id,),
            conn=conn,
        )

    def record_control_event(
        self,
        *,
        project_id: str,
        command: str,
        requested_by: str,
        status: str,
        args: dict[str, Any] | None = None,
        orchestrator_id: str | None = None,
        reason: str | None = None,
        result_summary: str | None = None,
        mirrored_to_zulip: bool = False,
        mirrored_message_id: str | None = None,
        event_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "event_id": event_id or self.new_id("ctrl"),
            "project_id": project_id,
            "orchestrator_id": orchestrator_id,
            "command": command,
            "requested_by": requested_by,
            "requested_at": utc_now(),
            "args_json": args or {},
            "reason": reason,
            "status": status,
            "result_summary": result_summary,
            "mirrored_to_zulip": mirrored_to_zulip,
            "mirrored_message_id": mirrored_message_id,
        }
        self.upsert("control_events", payload, conflict_columns=["event_id"], conn=conn)
        return payload

    def record_task(
        self,
        *,
        project_id: str,
        from_agent: str,
        to_agent: str,
        task_type: str,
        title: str,
        goal: str,
        priority: str,
        current_owner_agent: str | None = None,
        return_to: str = "requesting_agent",
        parent_task_id: str | None = None,
        context: dict[str, Any] | None = None,
        expected_output: dict[str, Any] | None = None,
        decision_bounds: dict[str, Any] | None = None,
        opened_at: str | None = None,
        updated_at: str | None = None,
        closed_at: str | None = None,
        status: str = "PENDING",
        task_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        timestamp = opened_at or utc_now()
        payload = {
            "task_id": task_id or self.new_id("T"),
            "project_id": project_id,
            "parent_task_id": parent_task_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "current_owner_agent": current_owner_agent or to_agent,
            "return_to": return_to,
            "task_type": task_type,
            "title": title,
            "goal": goal,
            "priority": priority,
            "status": status,
            "context_json": context or {},
            "expected_output_json": expected_output or {},
            "decision_bounds_json": decision_bounds or {},
            "opened_at": timestamp,
            "updated_at": updated_at or timestamp,
            "closed_at": closed_at,
        }
        self.upsert("tasks", payload, conflict_columns=["task_id"], conn=conn)
        return payload

    def record_task_attempt(
        self,
        *,
        task_id: str,
        project_id: str,
        agent_id: str,
        attempt_number: int,
        status: str,
        failure_cause: str | None = None,
        sandbox_id: str | None = None,
        workspace_ref: str | None = None,
        input_artifact_refs: list[str] | None = None,
        output_artifact_refs: list[str] | None = None,
        summary: str = "",
        started_at: str | None = None,
        finished_at: str | None = None,
        attempt_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "attempt_id": attempt_id or self.new_id("attempt"),
            "task_id": task_id,
            "project_id": project_id,
            "agent_id": agent_id,
            "attempt_number": attempt_number,
            "status": status,
            "failure_cause": failure_cause,
            "sandbox_id": sandbox_id,
            "workspace_ref": workspace_ref,
            "input_artifact_refs_json": input_artifact_refs or [],
            "output_artifact_refs_json": output_artifact_refs or [],
            "summary": summary,
            "started_at": started_at or utc_now(),
            "finished_at": finished_at,
        }
        self.upsert("task_attempts", payload, conflict_columns=["attempt_id"], conn=conn)
        return payload

    def record_agent_run(
        self,
        *,
        project_id: str,
        agent_id: str,
        model_profile: str,
        runtime_backend: str,
        task_id: str | None = None,
        model_used: str | None = None,
        sandbox_id: str | None = None,
        session_id: str | None = None,
        result_status: str | None = None,
        raw_transcript_ref: str | None = None,
        log_ref: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        run_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "run_id": run_id or self.new_id("run"),
            "task_id": task_id,
            "project_id": project_id,
            "agent_id": agent_id,
            "model_profile": model_profile,
            "model_used": model_used,
            "runtime_backend": runtime_backend,
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "result_status": result_status,
            "raw_transcript_ref": raw_transcript_ref,
            "log_ref": log_ref,
            "started_at": started_at or utc_now(),
            "ended_at": ended_at,
            "duration_ms": duration_ms,
        }
        self.upsert("agent_runs", payload, conflict_columns=["run_id"], conn=conn)
        return payload

    def record_snapshot(
        self,
        payload: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        snapshot = {
            "snapshot_id": payload.get("snapshot_id", self.new_id("snap")),
            "project_id": payload["project_id"],
            "captured_at": payload.get("captured_at", utc_now()),
            "captured_by": payload["captured_by"],
            "project_status": payload["project_status"],
            "current_phase": payload["current_phase"],
            "current_owner_agent": payload.get("current_owner_agent"),
            "open_tasks_json": payload["open_tasks"],
            "next_action_json": payload["next_action"],
            "workspace_ref": payload["workspace_ref"],
            "artifact_refs_json": payload["artifact_refs"],
            "latest_human_summary": payload["latest_human_summary"],
            "safe_boundary_type": payload.get("safe_boundary_type"),
            "created_from_control_event_id": payload.get("created_from_control_event_id"),
            "created_from_run_id": payload.get("created_from_run_id"),
        }
        self.upsert("project_snapshots", snapshot, conflict_columns=["snapshot_id"], conn=conn)
        self.update(
            "projects",
            {
                "last_snapshot_id": snapshot["snapshot_id"],
                "last_activity_at": snapshot["captured_at"],
                "updated_at": snapshot["captured_at"],
            },
            where_clause="project_id = ?",
            where_params=[snapshot["project_id"]],
            conn=conn,
        )
        return snapshot

    def record_recovery_event(
        self,
        *,
        project_id: str,
        failure_mode: str,
        action_taken: str,
        status: str,
        orchestrator_id: str | None = None,
        workspace_ref: str | None = None,
        details: dict[str, Any] | None = None,
        recovery_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "recovery_id": recovery_id or self.new_id("recovery"),
            "project_id": project_id,
            "orchestrator_id": orchestrator_id,
            "workspace_ref": workspace_ref,
            "failure_mode": failure_mode,
            "action_taken": action_taken,
            "status": status,
            "details_json": details or {},
            "created_at": utc_now(),
            "completed_at": utc_now() if status in {"COMPLETED", "FAILED"} else None,
        }
        self.upsert("recovery_events", payload, conflict_columns=["recovery_id"], conn=conn)
        return payload

    def link_zulip_message(
        self,
        *,
        project_id: str,
        zulip_message_id: str,
        stream_name: str,
        topic_name: str,
        direction: str,
        message_kind: str,
        linked_entity_type: str,
        linked_entity_id: str,
        task_id: str | None = None,
        control_event_id: str | None = None,
        link_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "link_id": link_id or self.new_id("zulip"),
            "project_id": project_id,
            "task_id": task_id,
            "control_event_id": control_event_id,
            "zulip_message_id": zulip_message_id,
            "stream_name": stream_name,
            "topic_name": topic_name,
            "direction": direction,
            "message_kind": message_kind,
            "linked_entity_type": linked_entity_type,
            "linked_entity_id": linked_entity_id,
            "created_at": utc_now(),
        }
        self.upsert("zulip_message_links", payload, conflict_columns=["zulip_message_id"], conn=conn)
        return payload
