"""First-class projection event persistence."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


PROJECTION_EVENT_TYPES = {
    "project_kickoff",
    "project_change_proposed",
    "project_change_confirmed",
    "spec_updated",
    "plan_updated",
    "tasks_updated",
    "execution_handoff_created",
    "execution_started",
    "execution_blocked",
    "verification_reported",
    "project_closed",
}


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class ProjectionEventService:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "projection_events.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"events": [], "meta": {"created_at": _utc_now(), "updated_at": _utc_now()}})

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        payload["meta"] = payload.get("meta", {})
        payload["meta"]["updated_at"] = _utc_now()
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        temp.replace(self.path)

    def record_event(
        self,
        *,
        event_type: str,
        project_id: str,
        summary: str,
        payload: dict[str, Any],
        actor_agent: str,
        project_version: str | int = 1,
    ) -> dict[str, Any]:
        if event_type not in PROJECTION_EVENT_TYPES:
            raise ValueError(f"Unsupported projection event type: {event_type}")
        record = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "project_id": project_id,
            "summary": summary,
            "payload": payload,
            "actor_agent": actor_agent,
            "project_version": project_version,
            "created_at": _utc_now(),
        }
        with self._lock:
            state = self._read()
            state["events"].append(record)
            state["events"] = state["events"][-2000:]
            self._write(state)
        return record

    def list_events(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._read().get("events", []))
        if project_id:
            return [row for row in events if row.get("project_id") == project_id]
        return events
