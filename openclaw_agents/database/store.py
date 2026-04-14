"""SQLite-backed persistence helpers for the control plane.

Phase 2 splits persistence into:
- a shared scheduler/control-plane database
- per-project databases under ``<project>/.agents/project.db``

The public store surface stays small and explicit so the rest of the codebase
does not need to know which database owns which record family.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from openclaw_agents.runtime.project_state import ProjectStateLayout

NON_TERMINAL_TASK_STATUSES = ("PENDING", "RUNNING")
SHARED_ONLY_TABLES = {"schema_migrations", "scheduling_records", "orchestrator_leases"}
PROJECT_LOCAL_TABLES = {
    "tasks",
    "task_attempts",
    "agent_runs",
    "artifacts",
    "decisions",
    "escalations",
    "zulip_message_links",
    "project_snapshots",
    "control_events",
    "workspace_states",
    "recovery_events",
}
ALL_TABLES = SHARED_ONLY_TABLES | PROJECT_LOCAL_TABLES | {"projects"}
TABLE_NAME_RE = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_][a-z0-9_]*)\b", re.IGNORECASE)


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
    """Shared + project-routed storage wrapper around SQLite databases."""

    def __init__(self, db_path: str | Path | None = None, *, initialize: bool = True) -> None:
        if db_path is None:
            db_path = os.environ.get("OPENCLAW_DB_PATH", "/tmp/openclaw_agents_control_plane.sqlite3")
        self.shared_db_path = str(db_path)
        self.db_path = self.shared_db_path
        self._project_id_cache: dict[tuple[str, str], str] = {}
        if initialize:
            self.initialize_schema()
            self.ensure_orchestrator_leases()

    @property
    def schema_path(self) -> Path:
        return Path(__file__).with_name("schema.sql")

    def _connect(self, db_path: str | Path) -> sqlite3.Connection:
        db_path = str(db_path)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def connection(self) -> sqlite3.Connection:
        return self._connect(self.shared_db_path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def project_transaction(self, project_id: str) -> Iterator[sqlite3.Connection]:
        db_path = self._db_path_for_project(project_id, create_if_missing=True) or self.shared_db_path
        conn = self._connect(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        self._initialize_db(self.shared_db_path)

    def _initialize_db(self, db_path: str | Path) -> None:
        with self._connect(db_path) as conn:
            conn.executescript(self.schema_path.read_text())

    def _normalize_params(self, params: Iterable[Any]) -> tuple[Any, ...]:
        return tuple(_normalize_value(value) for value in params)

    def _execute_db(
        self,
        db_path: str | Path,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        normalized = self._normalize_params(params)
        if conn is not None:
            cursor = conn.execute(sql, normalized)
            return cursor.rowcount
        with self._connect(db_path) as local_conn:
            cursor = local_conn.execute(sql, normalized)
            local_conn.commit()
            return cursor.rowcount

    def _fetchone_db(
        self,
        db_path: str | Path,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_params(params)
        if conn is not None:
            return _row_to_dict(conn.execute(sql, normalized).fetchone())
        with self._connect(db_path) as local_conn:
            return _row_to_dict(local_conn.execute(sql, normalized).fetchone())

    def _fetchall_db(
        self,
        db_path: str | Path,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        normalized = self._normalize_params(params)
        if conn is not None:
            rows = conn.execute(sql, normalized).fetchall()
        else:
            with self._connect(db_path) as local_conn:
                rows = local_conn.execute(sql, normalized).fetchall()
        return [_row_to_dict(row) or {} for row in rows]

    def _extract_tables(self, sql: str) -> set[str]:
        return {match.group(1) for match in TABLE_NAME_RE.finditer(sql)}

    def _shared_project_row(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self._fetchone_db(
            self.shared_db_path,
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
            conn=conn,
        )

    def _project_db_path_from_workspace(
        self,
        workspace_ref: str | Path,
        *,
        create_if_missing: bool = False,
    ) -> str:
        layout = ProjectStateLayout.from_workspace(workspace_ref)
        db_path = layout.project_db_path
        if create_if_missing or db_path.exists():
            self._initialize_db(db_path)
        return str(db_path)

    def ensure_project_schema(self, workspace_ref: str | Path) -> str:
        return self._project_db_path_from_workspace(workspace_ref, create_if_missing=True)

    def _db_path_for_project(
        self,
        project_id: str,
        *,
        create_if_missing: bool = False,
    ) -> str | None:
        project = self._shared_project_row(project_id)
        if not project or not project.get("workspace_ref"):
            return None
        db_path = self._project_db_path_from_workspace(project["workspace_ref"], create_if_missing=create_if_missing)
        if create_if_missing or Path(db_path).exists():
            return db_path
        return None

    def _iter_registered_projects(self) -> list[dict[str, Any]]:
        return self._fetchall_db(
            self.shared_db_path,
            "SELECT project_id, workspace_ref, created_at FROM projects ORDER BY created_at ASC, project_id ASC",
        )

    def _iter_project_databases(self) -> Iterator[tuple[str, str]]:
        for project in self._iter_registered_projects():
            project_id = str(project["project_id"])
            yield project_id, self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path

    def _cache_project_id(self, table: str, key: str, project_id: str) -> None:
        self._project_id_cache[(table, str(key))] = project_id

    def _resolve_project_id_for_lookup(self, table: str, lookup_column: str, lookup_value: Any) -> str | None:
        cache_key = (f"{table}:{lookup_column}", str(lookup_value))
        cached = self._project_id_cache.get(cache_key)
        if cached:
            return cached

        if table == "projects" and lookup_column == "project_id":
            self._cache_project_id(f"{table}:{lookup_column}", lookup_value, str(lookup_value))
            return str(lookup_value)

        if table == "workspace_states" and lookup_column == "workspace_ref":
            project = self._fetchone_db(
                self.shared_db_path,
                "SELECT project_id FROM projects WHERE workspace_ref = ?",
                (lookup_value,),
            )
            if project:
                project_id = str(project["project_id"])
                self._cache_project_id(f"{table}:{lookup_column}", lookup_value, project_id)
                return project_id

        shared_row = self._fetchone_db(
            self.shared_db_path,
            f"SELECT project_id FROM {table} WHERE {lookup_column} = ? LIMIT 1",
            (lookup_value,),
        )
        if shared_row:
            project_id = str(shared_row["project_id"])
            self._cache_project_id(f"{table}:{lookup_column}", lookup_value, project_id)
            return project_id

        for project_id, db_path in self._iter_project_databases():
            if db_path == self.shared_db_path or not Path(db_path).exists():
                continue
            row = self._fetchone_db(
                db_path,
                f"SELECT project_id FROM {table} WHERE {lookup_column} = ? LIMIT 1",
                (lookup_value,),
            )
            if row:
                resolved_project_id = str(row.get("project_id") or project_id)
                self._cache_project_id(f"{table}:{lookup_column}", lookup_value, resolved_project_id)
                return resolved_project_id
        return None

    def _project_id_for_table_operation(
        self,
        table: str,
        *,
        data: dict[str, Any] | None = None,
        where_clause: str | None = None,
        where_params: Iterable[Any] = (),
    ) -> str | None:
        if table == "projects":
            if data and data.get("project_id"):
                return str(data["project_id"])
            params = list(where_params)
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            return None

        if data and data.get("project_id"):
            return str(data["project_id"])

        params = list(where_params)
        if table == "workspace_states":
            if data and data.get("workspace_ref"):
                return self._resolve_project_id_for_lookup("workspace_states", "workspace_ref", data["workspace_ref"])
            if where_clause == "workspace_ref = ?" and params:
                return self._resolve_project_id_for_lookup("workspace_states", "workspace_ref", params[0])
        if table == "tasks":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "task_id = ?" and params:
                return self._resolve_project_id_for_lookup("tasks", "task_id", params[0])
        if table == "task_attempts":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "attempt_id = ?" and params:
                return self._resolve_project_id_for_lookup("task_attempts", "attempt_id", params[0])
            if where_clause == "task_id = ?" and params:
                return self._resolve_project_id_for_lookup("tasks", "task_id", params[0])
        if table == "agent_runs":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "run_id = ?" and params:
                return self._resolve_project_id_for_lookup("agent_runs", "run_id", params[0])
        if table == "artifacts":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "artifact_id = ?" and params:
                return self._resolve_project_id_for_lookup("artifacts", "artifact_id", params[0])
        if table == "control_events":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "event_id = ?" and params:
                return self._resolve_project_id_for_lookup("control_events", "event_id", params[0])
        if table == "recovery_events":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "recovery_id = ?" and params:
                return self._resolve_project_id_for_lookup("recovery_events", "recovery_id", params[0])
        if table == "zulip_message_links":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
            if where_clause == "task_id = ?" and params:
                return self._resolve_project_id_for_lookup("tasks", "task_id", params[0])
            if where_clause == "zulip_message_id = ?" and params:
                return self._resolve_project_id_for_lookup("zulip_message_links", "zulip_message_id", params[0])
        if table == "decisions":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
        if table == "escalations":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
        if table == "project_snapshots":
            if where_clause == "project_id = ?" and params:
                return str(params[0])
        return None

    def _db_path_for_project_table(
        self,
        table: str,
        *,
        data: dict[str, Any] | None = None,
        where_clause: str | None = None,
        where_params: Iterable[Any] = (),
    ) -> str:
        project_id = self._project_id_for_table_operation(
            table,
            data=data,
            where_clause=where_clause,
            where_params=where_params,
        )
        if not project_id:
            return self.shared_db_path
        return self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path

    def _route_select_db(self, sql: str, params: Iterable[Any]) -> str:
        stripped = " ".join(sql.strip().split()).upper()
        if stripped == "SELECT CURRENT_TIMESTAMP AS TS":
            return self.shared_db_path

        tables = {table for table in self._extract_tables(sql) if table in ALL_TABLES}
        if not tables or tables.issubset({"projects"} | SHARED_ONLY_TABLES):
            return self.shared_db_path

        if len(tables) == 1:
            table = next(iter(tables))
            params_list = list(params)
            project_id: str | None = None
            if "WHERE project_id = ?" in sql and params_list:
                project_id = str(params_list[0])
            elif table == "tasks" and "WHERE task_id = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("tasks", "task_id", params_list[0])
            elif table == "artifacts" and "WHERE artifact_id = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("artifacts", "artifact_id", params_list[0])
            elif table == "artifacts" and "WHERE ref = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("artifacts", "ref", params_list[0])
            elif table == "recovery_events" and "WHERE recovery_id = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("recovery_events", "recovery_id", params_list[0])
            elif table == "zulip_message_links" and "WHERE zulip_message_id = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("zulip_message_links", "zulip_message_id", params_list[0])
            elif table == "zulip_message_links" and "WHERE task_id = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("tasks", "task_id", params_list[0])
            elif table == "workspace_states" and "WHERE workspace_ref = ?" in sql and params_list:
                project_id = self._resolve_project_id_for_lookup("workspace_states", "workspace_ref", params_list[0])
            if project_id:
                return self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path

        return self.shared_db_path

    def execute(self, sql: str, params: Iterable[Any] = (), *, conn: sqlite3.Connection | None = None) -> int:
        if conn is not None:
            return self._execute_db(self.shared_db_path, sql, params, conn=conn)
        db_path = self._route_select_db(sql, params)
        return self._execute_db(db_path, sql, params)

    def fetchone(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if conn is not None:
            return self._fetchone_db(self.shared_db_path, sql, params, conn=conn)
        stripped = " ".join(sql.strip().split()).upper()
        if stripped == "SELECT CURRENT_TIMESTAMP AS TS":
            return {"ts": utc_now()}
        db_path = self._route_select_db(sql, params)
        return self._fetchone_db(db_path, sql, params)

    def fetchall(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if conn is not None:
            return self._fetchall_db(self.shared_db_path, sql, params, conn=conn)
        db_path = self._route_select_db(sql, params)
        return self._fetchall_db(db_path, sql, params)

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
        params = [_normalize_value(data[column]) for column in columns]

        if conn is not None:
            self._execute_db(self.shared_db_path, sql, params, conn=conn)
            return

        if table in SHARED_ONLY_TABLES:
            self._execute_db(self.shared_db_path, sql, params)
            return

        if table == "projects":
            self._execute_db(self.shared_db_path, sql, params)
            merged = self._shared_project_row(str(data["project_id"])) or dict(data)
            workspace_ref = merged.get("workspace_ref")
            if workspace_ref:
                project_db_path = self._project_db_path_from_workspace(workspace_ref, create_if_missing=True)
                self._execute_db(project_db_path, sql, [_normalize_value(merged[column]) for column in columns])
            return

        db_path = self._db_path_for_project_table(table, data=data)
        self._execute_db(db_path, sql, params)
        project_id = str(data.get("project_id") or "")
        if project_id:
            for column in ("task_id", "attempt_id", "run_id", "artifact_id", "event_id", "recovery_id", "zulip_message_id"):
                if data.get(column):
                    self._cache_project_id(f"{table}:{column}", data[column], project_id)

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

        if conn is not None:
            return self._execute_db(self.shared_db_path, sql, params, conn=conn)

        if table in SHARED_ONLY_TABLES:
            return self._execute_db(self.shared_db_path, sql, params)

        if table == "projects":
            rowcount = self._execute_db(self.shared_db_path, sql, params)
            project_id = self._project_id_for_table_operation(
                table,
                data=data,
                where_clause=where_clause,
                where_params=where_params,
            )
            if project_id:
                merged = self._shared_project_row(project_id)
                if merged and merged.get("workspace_ref"):
                    project_db_path = self._project_db_path_from_workspace(merged["workspace_ref"], create_if_missing=True)
                    project_columns = list(merged.keys())
                    project_placeholders = ", ".join("?" for _ in project_columns)
                    project_updates = ", ".join(
                        f"{column} = excluded.{column}" for column in project_columns if column != "project_id"
                    )
                    project_sql = (
                        f"INSERT INTO projects ({', '.join(project_columns)}) VALUES ({project_placeholders}) "
                        f"ON CONFLICT (project_id) DO UPDATE SET {project_updates}"
                    )
                    self._execute_db(
                        project_db_path,
                        project_sql,
                        [_normalize_value(merged[column]) for column in project_columns],
                    )
            return rowcount

        db_path = self._db_path_for_project_table(
            table,
            data=data,
            where_clause=where_clause,
            where_params=where_params,
        )
        return self._execute_db(db_path, sql, params)

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
        shared = self._shared_project_row(project_id, conn=conn)
        if not shared:
            return None
        workspace_ref = shared.get("workspace_ref")
        if not workspace_ref:
            return shared
        project_db_path = self._db_path_for_project(project_id, create_if_missing=False)
        if not project_db_path:
            return shared
        local = self._fetchone_db(project_db_path, "SELECT * FROM projects WHERE project_id = ?", (project_id,))
        if not local:
            return shared
        merged = dict(shared)
        merged.update(local)
        return merged

    def get_project_feedback_thread(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[str, str] | None:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        row = self._fetchone_db(
            db_path,
            """
            SELECT stream_name, topic_name
            FROM zulip_message_links
            WHERE project_id = ?
              AND direction = 'inbound'
            ORDER BY
              CASE message_kind
                WHEN 'human_note' THEN 0
                WHEN 'control_event' THEN 1
                WHEN 'task_assignment' THEN 2
                ELSE 3
              END,
              created_at ASC
            LIMIT 1
            """,
            (project_id,),
            conn=conn,
        )
        if row:
            return str(row["stream_name"]), str(row["topic_name"])
        row = self._fetchone_db(
            db_path,
            """
            SELECT stream_name, topic_name
            FROM zulip_message_links
            WHERE project_id = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id,),
            conn=conn,
        )
        if row:
            return str(row["stream_name"]), str(row["topic_name"])
        return None

    def get_task(self, task_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("tasks", "task_id", task_id)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(db_path or self.shared_db_path, "SELECT * FROM tasks WHERE task_id = ?", (task_id,), conn=conn)

    def get_scheduling_record(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self._fetchone_db(
            self.shared_db_path,
            "SELECT * FROM scheduling_records WHERE project_id = ?",
            (project_id,),
            conn=conn,
        )

    def get_workspace_state(
        self,
        workspace_ref: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("workspace_states", "workspace_ref", workspace_ref)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        row = self._fetchone_db(
            db_path or self.shared_db_path,
            "SELECT * FROM workspace_states WHERE workspace_ref = ?",
            (workspace_ref,),
            conn=conn,
        )
        if row or not db_path or db_path == self.shared_db_path:
            return row
        return self._fetchone_db(
            self.shared_db_path,
            "SELECT * FROM workspace_states WHERE workspace_ref = ?",
            (workspace_ref,),
            conn=conn,
        )

    def get_lease(
        self,
        orchestrator_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        return self._fetchone_db(
            self.shared_db_path,
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
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        return self._fetchone_db(
            db_path,
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
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        return self._fetchall_db(
            db_path,
            """
            SELECT *
            FROM tasks
            WHERE project_id = ?
              AND status IN (?, ?)
            ORDER BY opened_at ASC
            """,
            (project_id, *NON_TERMINAL_TASK_STATUSES),
            conn=conn,
        )

    def list_tasks_for_project(
        self,
        project_id: str,
        *,
        to_agent: str | None = None,
        task_type: str | None = None,
        task_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        sql = "SELECT * FROM tasks WHERE project_id = ?"
        params: list[Any] = [project_id]
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        if to_agent:
            sql += " AND to_agent = ?"
            params.append(to_agent)
        if task_type:
            sql += " AND task_type = ?"
            params.append(task_type)
        sql += " ORDER BY opened_at ASC"
        return self._fetchall_db(db_path, sql, params, conn=conn)

    def list_child_tasks(
        self,
        parent_task_id: str,
        *,
        task_type: str | None = None,
        include_terminal: bool = True,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        parent = self.get_task(parent_task_id)
        if not parent:
            return []
        db_path = self._db_path_for_project(parent["project_id"], create_if_missing=False) or self.shared_db_path
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
            sql += " AND status IN (?, ?)"
            params.extend(NON_TERMINAL_TASK_STATUSES)
        sql += " ORDER BY opened_at ASC"
        return self._fetchall_db(db_path, sql, params, conn=conn)

    def get_latest_child_task(
        self,
        parent_task_id: str,
        *,
        task_type: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        parent = self.get_task(parent_task_id)
        if not parent:
            return None
        db_path = self._db_path_for_project(parent["project_id"], create_if_missing=False) or self.shared_db_path
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
        return self._fetchone_db(db_path, sql, params, conn=conn)

    def list_task_attempts(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return []
        db_path = self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path
        return self._fetchall_db(
            db_path,
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
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        return self._fetchall_db(
            db_path,
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
        task = self.get_task(task_id)
        if not task:
            return None
        db_path = self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path
        return self._fetchone_db(
            db_path,
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
        task = self.get_task(task_id)
        if not task:
            return None
        db_path = self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path
        return self._fetchone_db(
            db_path,
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
        project_id = self._resolve_project_id_for_lookup("agent_runs", "run_id", run_id)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(db_path or self.shared_db_path, "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,), conn=conn)

    def list_agent_runs(
        self,
        *,
        task_id: str | None = None,
        project_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if project_id:
            db_paths = [self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path]
            project_ids = [project_id]
        elif task_id:
            task = self.get_task(task_id)
            if not task:
                return []
            project_ids = [task["project_id"]]
            db_paths = [self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path]
        else:
            project_ids = []
            db_paths = []
            for candidate_project_id, db_path in self._iter_project_databases():
                project_ids.append(candidate_project_id)
                db_paths.append(db_path)

        rows: list[dict[str, Any]] = []
        for index, db_path in enumerate(db_paths):
            sql = "SELECT * FROM agent_runs WHERE 1=1"
            params: list[Any] = []
            if task_id:
                sql += " AND task_id = ?"
                params.append(task_id)
            if project_ids:
                sql += " AND project_id = ?"
                params.append(project_ids[index])
            sql += " ORDER BY started_at ASC"
            rows.extend(self._fetchall_db(db_path, sql, params, conn=conn))
        return sorted(rows, key=lambda item: str(item.get("started_at") or ""))

    def list_project_active_agent_runs(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        rows = self._fetchall_db(
            db_path,
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
        if db_path != self.shared_db_path:
            shared_rows = self._fetchall_db(
                self.shared_db_path,
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
            seen = {row["run_id"] for row in rows}
            rows.extend(row for row in shared_rows if row["run_id"] not in seen)
        return sorted(rows, key=lambda item: str(item.get("started_at") or ""))

    def list_pending_runtime_runs(
        self,
        *,
        runtime_backend: str = "workspace_queue",
        agent_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for project_id, db_path in self._iter_project_databases():
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
                  AND ar.project_id = ?
            """
            params: list[Any] = [runtime_backend, project_id]
            if agent_id:
                sql += " AND ar.agent_id = ?"
                params.append(agent_id)
            sql += " ORDER BY ar.started_at ASC"
            rows.extend(self._fetchall_db(db_path, sql, params, conn=conn))
        return sorted(rows, key=lambda item: str(item.get("started_at") or ""))

    def list_result_mirror_candidates(
        self,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for project_id, db_path in self._iter_project_databases():
            project = self.get_project(project_id)
            if not project:
                continue
            rows = self._fetchall_db(
                db_path,
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
                  ta.output_artifact_refs_json
                FROM tasks AS t
                JOIN task_attempts AS ta
                  ON ta.attempt_id = (
                    SELECT attempt_id
                    FROM task_attempts
                    WHERE task_id = t.task_id
                    ORDER BY attempt_number DESC
                    LIMIT 1
                  )
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
            for row in rows:
                row["current_owner_agent"] = project.get("current_owner_agent")
                row["assigned_project_orchestrator"] = project.get("assigned_project_orchestrator")
                row["assigned_software_orchestrator"] = project.get("assigned_software_orchestrator")
                row["next_action_json"] = project.get("next_action_json") or {}
                candidates.append(row)
        return sorted(candidates, key=lambda item: str(item.get("updated_at") or ""))

    def list_dispatch_mirror_candidates(
        self,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for project_id, db_path in self._iter_project_databases():
            project = self.get_project(project_id)
            if not project or project.get("project_status") in {"DONE", "CANCELLED"}:
                continue
            rows = self._fetchall_db(
                db_path,
                """
                SELECT
                  t.task_id,
                  t.project_id,
                  t.task_type,
                  t.status,
                  t.from_agent,
                  t.to_agent,
                  t.goal,
                  t.priority,
                  t.return_to,
                  t.opened_at
                FROM tasks AS t
                LEFT JOIN (
                  SELECT task_id, MAX(created_at) AS last_mirrored_at
                  FROM zulip_message_links
                  WHERE direction = 'outbound'
                    AND message_kind = 'task_assignment'
                  GROUP BY task_id
                ) AS mirrored
                  ON mirrored.task_id = t.task_id
                WHERE t.to_agent NOT IN ('planner', 'implementer', 'tester')
                  AND mirrored.last_mirrored_at IS NULL
                ORDER BY t.opened_at ASC
                """,
                conn=conn,
            )
            for row in rows:
                row["current_phase"] = project.get("current_phase")
                row["runtime_status"] = project.get("runtime_status")
                row["next_action_json"] = project.get("next_action_json") or {}
                candidates.append(row)
        return sorted(candidates, key=lambda item: str(item.get("opened_at") or ""))

    def list_morpheus_progress_update_candidates(
        self,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for project_id, db_path in self._iter_project_databases():
            project = self.get_project(project_id)
            if not project or project.get("project_status") in {"DONE", "CANCELLED"}:
                continue
            rows = self._fetchall_db(
                db_path,
                """
                SELECT
                  child.task_id,
                  child.parent_task_id,
                  child.project_id,
                  child.task_type,
                  child.status,
                  child.opened_at,
                  parent.task_type AS parent_task_type
                FROM tasks AS child
                JOIN tasks AS parent ON parent.task_id = child.parent_task_id
                LEFT JOIN (
                  SELECT linked_entity_id AS task_id, MAX(created_at) AS last_mirrored_at
                  FROM zulip_message_links
                  WHERE direction = 'outbound'
                    AND message_kind = 'status_update'
                    AND linked_entity_type = 'task'
                  GROUP BY linked_entity_id
                ) AS mirrored
                  ON mirrored.task_id = child.task_id
                WHERE child.to_agent IN ('planner', 'implementer', 'tester')
                  AND child.task_type IN ('PLAN_SOFTWARE_TASK', 'IMPLEMENT_SOFTWARE_TASK', 'TEST_SOFTWARE_TASK')
                  AND parent.to_agent = 'morpheus'
                  AND mirrored.last_mirrored_at IS NULL
                ORDER BY child.opened_at ASC
                """,
                conn=conn,
            )
            candidates.extend(rows)
        return sorted(candidates, key=lambda item: str(item.get("opened_at") or ""))

    def next_attempt_number(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        task = self.get_task(task_id)
        if not task:
            return 1
        db_path = self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path
        row = self._fetchone_db(
            db_path,
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
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        rows = self._fetchall_db(
            db_path,
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
        shared_rows = self._fetchall_db(
            self.shared_db_path,
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
              s.current_safe_boundary_type
            FROM projects AS p
            LEFT JOIN scheduling_records AS s ON s.project_id = p.project_id
            WHERE p.{orchestrator_column} = ?
            """,
            (orchestrator_id,),
            conn=conn,
        )
        enriched: list[dict[str, Any]] = []
        for row in shared_rows:
            snapshot = self.get_latest_snapshot(row["project_id"])
            workspace_state = self.get_workspace_state(row["workspace_ref"]) if row.get("workspace_ref") else None
            row["last_snapshot_safe_boundary_type"] = snapshot.get("safe_boundary_type") if snapshot else None
            row["repo_root"] = workspace_state.get("repo_root") if workspace_state else None
            row["branch_or_worktree_id"] = workspace_state.get("branch_or_worktree_id") if workspace_state else None
            row["last_clean_commit_or_checkpoint"] = (
                workspace_state.get("last_clean_commit_or_checkpoint") if workspace_state else None
            )
            row["is_consistent"] = workspace_state.get("is_consistent") if workspace_state else None
            row["last_validated_at"] = workspace_state.get("last_validated_at") if workspace_state else None
            enriched.append(row)
        return enriched

    def list_active_leases_for_project(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return self._fetchall_db(
            self.shared_db_path,
            """
            SELECT orchestrator_id, active_project_id, lease_owner_run_id, lease_expires_at
            FROM orchestrator_leases
            WHERE active_project_id = ?
              AND lease_status = 'HELD'
            ORDER BY orchestrator_id ASC
            """,
            (project_id,),
            conn=conn,
        )

    def get_artifact(self, artifact_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("artifacts", "artifact_id", artifact_id)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(
            db_path or self.shared_db_path,
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
            conn=conn,
        )

    def get_artifact_by_ref(self, ref: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("artifacts", "ref", ref)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(
            db_path or self.shared_db_path,
            "SELECT * FROM artifacts WHERE ref = ?",
            (ref,),
            conn=conn,
        )

    def list_project_artifacts(
        self,
        project_id: str,
        *,
        artifact_type: str | None = None,
        task_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        sql = "SELECT * FROM artifacts WHERE project_id = ?"
        params: list[Any] = [project_id]
        if artifact_type:
            sql += " AND artifact_type = ?"
            params.append(artifact_type)
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at ASC"
        return self._fetchall_db(db_path, sql, params, conn=conn)

    def list_control_events(
        self,
        project_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        return self._fetchall_db(
            db_path,
            "SELECT * FROM control_events WHERE project_id = ? ORDER BY requested_at ASC",
            (project_id,),
            conn=conn,
        )

    def get_recovery_event(
        self,
        recovery_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("recovery_events", "recovery_id", recovery_id)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(
            db_path or self.shared_db_path,
            "SELECT * FROM recovery_events WHERE recovery_id = ?",
            (recovery_id,),
            conn=conn,
        )

    def list_escalations(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        db_path = self._db_path_for_project(project_id, create_if_missing=False) or self.shared_db_path
        sql = "SELECT * FROM escalations WHERE project_id = ?"
        params: list[Any] = [project_id]
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at ASC"
        return self._fetchall_db(db_path, sql, params, conn=conn)

    def get_zulip_message_link(
        self,
        zulip_message_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        project_id = self._resolve_project_id_for_lookup("zulip_message_links", "zulip_message_id", zulip_message_id)
        db_path = self._db_path_for_project(project_id, create_if_missing=False) if project_id else None
        return self._fetchone_db(
            db_path or self.shared_db_path,
            "SELECT * FROM zulip_message_links WHERE zulip_message_id = ?",
            (zulip_message_id,),
            conn=conn,
        )

    def list_zulip_links_for_task(
        self,
        task_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return []
        db_path = self._db_path_for_project(task["project_id"], create_if_missing=False) or self.shared_db_path
        return self._fetchall_db(
            db_path,
            """
            SELECT *
            FROM zulip_message_links
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
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
