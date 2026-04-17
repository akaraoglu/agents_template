"""Authoritative JSON-backed state store used by the foundation layer."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class StateStore:
    """Minimal authoritative store for projects, approvals, and handoffs.

    Zulip is intentionally not used as machine-truth persistence.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "state_store.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write(self._default_state())

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "projects": {},
            "approvals": {},
            "handoffs": {},
            "execution_states": {},
            "internal_runs": {},
            "audit_log": [],
            "events": [],
            "meta": {"created_at": _utc_now(), "updated_at": _utc_now()},
        }

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        payload["meta"] = payload.get("meta", {})
        payload["meta"]["updated_at"] = _utc_now()
        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        temp_path.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read()
            return list(state.get("projects", {}).values())

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("projects", {}).get(project_id)

    def upsert_project(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = project["id"]
        now = _utc_now()
        with self._lock:
            state = self._read()
            projects = state.setdefault("projects", {})
            existing = projects.get(project_id, {})
            merged = {**existing, **project}
            merged["id"] = project_id
            merged["created_at"] = existing.get("created_at", now)
            merged["updated_at"] = now
            projects[project_id] = merged
            self._write(state)
            return merged

    def create_approval(self, approval: dict[str, Any]) -> dict[str, Any]:
        approval_id = approval.get("approval_id", str(uuid.uuid4()))
        now = _utc_now()
        with self._lock:
            state = self._read()
            approvals = state.setdefault("approvals", {})
            record = {
                **approval,
                "approval_id": approval_id,
                "status": approval.get("status", "PENDING"),
                "created_at": approval.get("created_at", now),
                "updated_at": now,
            }
            approvals[approval_id] = record
            self._write(state)
            return record

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("approvals", {}).get(approval_id)

    def list_pending_approvals(
        self, requester_email: str | None = None, owner_agent: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            approvals = list(self._read().get("approvals", {}).values())
        filtered = [row for row in approvals if row.get("status") == "PENDING"]
        if requester_email:
            filtered = [row for row in filtered if row.get("requester_email") == requester_email]
        if owner_agent:
            filtered = [row for row in filtered if row.get("owner_agent") == owner_agent]
        return filtered

    def update_approval(self, approval_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            approvals = state.setdefault("approvals", {})
            current = approvals[approval_id]
            current.update(updates)
            current["updated_at"] = _utc_now()
            approvals[approval_id] = current
            self._write(state)
            return current

    def add_handoff(self, handoff: dict[str, Any]) -> dict[str, Any]:
        handoff_id = handoff.get("handoff_id", str(uuid.uuid4()))
        now = _utc_now()
        with self._lock:
            state = self._read()
            handoffs = state.setdefault("handoffs", {})
            record = {
                **handoff,
                "handoff_id": handoff_id,
                "created_at": handoff.get("created_at", now),
                "updated_at": now,
            }
            handoffs[handoff_id] = record
            self._write(state)
            return record

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("handoffs", {}).get(handoff_id)

    def update_handoff(self, handoff_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            handoffs = state.setdefault("handoffs", {})
            current = handoffs[handoff_id]
            current.update(updates)
            current["updated_at"] = _utc_now()
            handoffs[handoff_id] = current
            project_id = current.get("project_id")
            if project_id:
                project = state.setdefault("projects", {}).get(project_id)
                if project is not None:
                    project["last_handoff_id"] = current.get("handoff_id", handoff_id)
                    if current.get("status"):
                        project["handoff_status"] = current["status"]
                    project["updated_at"] = _utc_now()
            self._write(state)
            return current

    def list_handoffs(
        self,
        project_id: str | None = None,
        *,
        status: str | None = None,
        assignee_agent: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            handoffs = list(self._read().get("handoffs", {}).values())
        if project_id:
            handoffs = [row for row in handoffs if row.get("project_id") == project_id]
        if status:
            handoffs = [row for row in handoffs if row.get("status") == status]
        if assignee_agent:
            handoffs = [row for row in handoffs if row.get("to_agent") == assignee_agent]
        return sorted(handoffs, key=lambda row: row.get("updated_at", row.get("created_at", "")))

    def upsert_execution_state(self, execution_state: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(execution_state["execution_id"])
        now = _utc_now()
        with self._lock:
            state = self._read()
            states = state.setdefault("execution_states", {})
            existing = states.get(execution_id, {})
            merged = {**existing, **execution_state}
            merged["execution_id"] = execution_id
            merged["created_at"] = existing.get("created_at", now)
            merged["updated_at"] = now
            states[execution_id] = merged
            self._write(state)
            return merged

    def get_execution_state(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("execution_states", {}).get(execution_id)

    def list_execution_states(
        self,
        *,
        project_id: str | None = None,
        handoff_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._read().get("execution_states", {}).values())
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if handoff_id:
            rows = [row for row in rows if row.get("handoff_id") == handoff_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return sorted(rows, key=lambda row: row.get("updated_at", row.get("created_at", "")))

    def upsert_internal_run(self, internal_run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(internal_run["run_id"])
        now = _utc_now()
        with self._lock:
            state = self._read()
            runs = state.setdefault("internal_runs", {})
            existing = runs.get(run_id, {})
            merged = {**existing, **internal_run}
            merged["run_id"] = run_id
            merged["created_at"] = existing.get("created_at", now)
            merged["updated_at"] = now
            runs[run_id] = merged
            self._write(state)
            return merged

    def get_internal_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("internal_runs", {}).get(run_id)

    def list_internal_runs(
        self,
        *,
        project_id: str | None = None,
        handoff_id: str | None = None,
        status: str | None = None,
        current_stage: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._read().get("internal_runs", {}).values())
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if handoff_id:
            rows = [row for row in rows if row.get("handoff_id") == handoff_id]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if current_stage:
            rows = [row for row in rows if row.get("current_stage") == current_stage]
        return sorted(rows, key=lambda row: row.get("updated_at", row.get("created_at", "")))

    def record_audit(self, entry: dict[str, Any]) -> dict[str, Any]:
        record = {
            **entry,
            "audit_id": str(entry.get("audit_id", uuid.uuid4())),
            "created_at": entry.get("created_at", _utc_now()),
        }
        with self._lock:
            state = self._read()
            audit_log = state.setdefault("audit_log", [])
            audit_log.append(record)
            state["audit_log"] = audit_log[-5000:]
            self._write(state)
        return record

    def list_audit_entries(
        self,
        *,
        action_type: str | None = None,
        actor_agent: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._read().get("audit_log", []))
        if action_type:
            rows = [row for row in rows if row.get("action_type") == action_type]
        if actor_agent:
            rows = [row for row in rows if row.get("actor_agent") == actor_agent]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        return rows

    def record_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            state = self._read()
            events = state.setdefault("events", [])
            events.append(event)
            state["events"] = events[-2000:]
            self._write(state)
