"""Persistent mapping of Zulip messages to project/task context."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class MessageMappingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "message_mappings.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"message_links": {}, "project_topics": {}, "control_events": {}})

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        temp.replace(self.path)

    def link_message(
        self,
        zulip_message_id: int | str,
        project_id: str | None,
        task_id: str | None,
        topic_name: str | None,
        message_kind: str,
    ) -> dict[str, Any]:
        record = {
            "zulip_message_id": str(zulip_message_id),
            "project_id": project_id,
            "task_id": task_id,
            "topic_name": topic_name,
            "message_kind": message_kind,
            "created_at": _utc_now(),
        }
        with self._lock:
            state = self._read()
            state["message_links"][str(zulip_message_id)] = record
            self._write(state)
        return record

    def get_message_context(self, zulip_message_id: int | str) -> dict[str, Any] | None:
        with self._lock:
            return self._read()["message_links"].get(str(zulip_message_id))

    def set_primary_topic(self, project_id: str, stream_name: str, topic_name: str) -> None:
        with self._lock:
            state = self._read()
            state["project_topics"][project_id] = {
                "stream_name": stream_name,
                "topic_name": topic_name,
                "updated_at": _utc_now(),
            }
            self._write(state)

    def get_primary_topic(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read()["project_topics"].get(project_id)

    def set_control_event_message(self, control_event_id: str, zulip_message_id: int | str) -> None:
        with self._lock:
            state = self._read()
            state["control_events"][control_event_id] = str(zulip_message_id)
            self._write(state)

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return self._read()
