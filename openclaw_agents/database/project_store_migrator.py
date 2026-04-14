"""Migrate legacy shared project state into per-project databases."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openclaw_agents.database.store import ControlPlaneStore

MIGRATION_ORDER = [
    "projects",
    "workspace_states",
    "tasks",
    "task_attempts",
    "agent_runs",
    "artifacts",
    "decisions",
    "escalations",
    "control_events",
    "project_snapshots",
    "zulip_message_links",
    "recovery_events",
]

PROJECT_LOCAL_PURGE_TABLES = [
    "workspace_states",
    "tasks",
    "task_attempts",
    "agent_runs",
    "artifacts",
    "decisions",
    "escalations",
    "control_events",
    "project_snapshots",
    "zulip_message_links",
    "recovery_events",
]

CONFLICT_COLUMNS = {
    "projects": ["project_id"],
    "workspace_states": ["workspace_ref"],
    "tasks": ["task_id"],
    "task_attempts": ["attempt_id"],
    "agent_runs": ["run_id"],
    "artifacts": ["artifact_id"],
    "decisions": ["decision_id"],
    "escalations": ["escalation_id"],
    "control_events": ["event_id"],
    "project_snapshots": ["snapshot_id"],
    "zulip_message_links": ["link_id"],
    "recovery_events": ["recovery_id"],
}


@dataclass(slots=True)
class MigrationReport:
    project_id: str
    workspace_ref: str | None
    project_db_path: str | None
    migrated_tables: dict[str, int]
    purged_tables: dict[str, int]
    skipped_reason: str | None = None

    @property
    def migrated(self) -> bool:
        return self.skipped_reason is None


class ProjectStoreMigrator:
    """Move legacy shared project-local rows into per-project databases."""

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()

    def _table_columns(self, conn, table: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [str(row[1]) for row in rows]

    def _upsert_sql(self, table: str, columns: list[str]) -> str:
        conflict_columns = CONFLICT_COLUMNS[table]
        placeholders = ", ".join("?" for _ in columns)
        updates = [column for column in columns if column not in conflict_columns]
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        if updates:
            sql += (
                f"ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE SET "
                + ", ".join(f"{column} = excluded.{column}" for column in updates)
            )
        else:
            sql += f"ON CONFLICT ({', '.join(conflict_columns)}) DO NOTHING"
        return sql

    def _shared_rows_for_table(self, conn, table: str, project_id: str) -> list[dict[str, Any]]:
        if table == "projects":
            rows = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchall()
        elif table == "workspace_states":
            rows = conn.execute("SELECT * FROM workspace_states WHERE project_id = ?", (project_id,)).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {table} WHERE project_id = ?", (project_id,)).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            results.append(item)
        return results

    def migrate_project(self, project_id: str, *, purge_shared: bool = True) -> MigrationReport:
        project = self.store._shared_project_row(project_id)  # noqa: SLF001 - same package boundary
        if not project:
            return MigrationReport(project_id, None, None, {}, {}, skipped_reason="missing_project")
        workspace_ref = project.get("workspace_ref")
        if not workspace_ref:
            return MigrationReport(project_id, None, None, {}, {}, skipped_reason="missing_workspace_ref")

        project_db_path = self.store.ensure_project_schema(workspace_ref)
        migrated_tables: dict[str, int] = {}
        purged_tables: dict[str, int] = {}

        with self.store.connection() as shared_conn, self.store._connect(project_db_path) as project_conn:  # noqa: SLF001
            project_conn.execute("PRAGMA foreign_keys = OFF")
            for table in MIGRATION_ORDER:
                rows = self._shared_rows_for_table(shared_conn, table, project_id)
                migrated_tables[table] = len(rows)
                if not rows:
                    continue
                columns = self._table_columns(project_conn, table)
                sql = self._upsert_sql(table, columns)
                project_conn.executemany(
                    sql,
                    [tuple(row.get(column) for column in columns) for row in rows],
                )
            project_conn.commit()
            project_conn.execute("PRAGMA foreign_keys = ON")

            if purge_shared:
                for table in reversed(PROJECT_LOCAL_PURGE_TABLES):
                    if table == "workspace_states":
                        cursor = shared_conn.execute("DELETE FROM workspace_states WHERE project_id = ?", (project_id,))
                    elif table == "agent_runs":
                        cursor = shared_conn.execute(
                            """
                            DELETE FROM agent_runs
                            WHERE project_id = ?
                              AND (
                                runtime_backend != 'control_plane'
                                OR run_id NOT IN (
                                  SELECT lease_owner_run_id
                                  FROM orchestrator_leases
                                  WHERE lease_owner_run_id IS NOT NULL
                                )
                              )
                            """,
                            (project_id,),
                        )
                    else:
                        cursor = shared_conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
                    purged_tables[table] = int(cursor.rowcount or 0)
                shared_conn.commit()

        return MigrationReport(
            project_id=project_id,
            workspace_ref=str(workspace_ref),
            project_db_path=project_db_path,
            migrated_tables=migrated_tables,
            purged_tables=purged_tables,
        )

    def migrate_all(self, *, purge_shared: bool = True) -> list[MigrationReport]:
        reports: list[MigrationReport] = []
        with self.store.connection() as conn:
            project_ids = [str(row[0]) for row in conn.execute("SELECT project_id FROM projects ORDER BY created_at ASC, project_id ASC")]
        for project_id in project_ids:
            reports.append(self.migrate_project(project_id, purge_shared=purge_shared))
        return reports


def _main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy shared project state into per-project databases.")
    parser.add_argument("--shared-db", dest="shared_db", default=None)
    parser.add_argument("--project-id", action="append", dest="project_ids")
    parser.add_argument("--all", action="store_true", dest="migrate_all")
    parser.add_argument("--no-purge-shared", action="store_true")
    args = parser.parse_args()

    store = ControlPlaneStore(args.shared_db)
    migrator = ProjectStoreMigrator(store)
    purge_shared = not args.no_purge_shared

    if args.migrate_all:
        reports = migrator.migrate_all(purge_shared=purge_shared)
    else:
        project_ids = args.project_ids or []
        if not project_ids:
            parser.error("provide --project-id or --all")
        reports = [migrator.migrate_project(project_id, purge_shared=purge_shared) for project_id in project_ids]

    print(json.dumps([asdict(report) for report in reports], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
