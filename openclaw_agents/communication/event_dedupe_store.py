"""Inbound event dedupe and checkpoint persistence for restart-safe recovery."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class EventDedupeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "event_dedupe.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write(
                {
                    "processed_event_ids": [],
                    "checkpoint": {"queue_id": None, "last_event_id": None, "updated_at": _utc_now()},
                    "consumer_checkpoints": {},
                }
            )

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        temp.replace(self.path)

    def seen(self, event_id: str) -> bool:
        with self._lock:
            state = self._read()
            return event_id in set(state["processed_event_ids"])

    def mark_processed(self, event_id: str) -> None:
        with self._lock:
            state = self._read()
            ids = state["processed_event_ids"]
            ids.append(event_id)
            state["processed_event_ids"] = ids[-5000:]
            self._write(state)

    def write_checkpoint(
        self,
        queue_id: str | None,
        last_event_id: str | None,
        consumer_id: str | None = None,
    ) -> None:
        with self._lock:
            state = self._read()
            checkpoint = {
                "queue_id": queue_id,
                "last_event_id": last_event_id,
                "updated_at": _utc_now(),
            }
            state["checkpoint"] = checkpoint
            state.setdefault("consumer_checkpoints", {})
            if consumer_id:
                state["consumer_checkpoints"][consumer_id] = checkpoint
            self._write(state)

    def get_checkpoint(self, consumer_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            if consumer_id:
                return state.get("consumer_checkpoints", {}).get(consumer_id, state["checkpoint"])
            return state["checkpoint"]

    def reset_for_new_queue(self, queue_id: str, consumer_id: str | None = None) -> None:
        with self._lock:
            state = self._read()
            state["processed_event_ids"] = []
            checkpoint = {"queue_id": queue_id, "last_event_id": None, "updated_at": _utc_now()}
            state["checkpoint"] = checkpoint
            state.setdefault("consumer_checkpoints", {})
            if consumer_id:
                state["consumer_checkpoints"][consumer_id] = checkpoint
            self._write(state)

    def processed_count(self) -> int:
        with self._lock:
            return len(self._read()["processed_event_ids"])
