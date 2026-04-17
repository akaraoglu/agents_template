"""Short-lived conversational memory for DM and topic sessions."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class ConversationMemoryService:
    def __init__(
        self,
        path: Path | None = None,
        *,
        retention_seconds: int | None = 7 * 24 * 3600,
        max_entries_per_session: int = 40,
    ) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "conversation_memory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.retention_seconds = retention_seconds
        self.max_entries_per_session = max_entries_per_session
        if not self.path.exists():
            self._write({"sessions": {}, "meta": {"created_at": _utc_now(), "updated_at": _utc_now()}})

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

    def append_message(
        self,
        session_key: str,
        *,
        role: str,
        sender: str,
        content: str,
        event_id: str | None = None,
        max_entries: int | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "role": role,
            "sender": sender,
            "content": content,
            "event_id": event_id,
            "created_at": created_at or _utc_now(),
        }
        with self._lock:
            state = self._read()
            session = state["sessions"].setdefault(session_key, {"messages": [], "updated_at": _utc_now()})
            messages = session.setdefault("messages", [])
            messages.append(entry)
            cap = max_entries if max_entries is not None else self.max_entries_per_session
            session["messages"] = messages[-cap:]
            session["updated_at"] = _utc_now()
            self._prune_state_locked(state, max_age_seconds=self.retention_seconds)
            self._write(state)
        return entry

    def recent_messages(
        self,
        session_key: str,
        limit: int = 12,
        *,
        max_age_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            session = self._read()["sessions"].get(session_key, {})
            messages = list(session.get("messages", []))
        filtered = self._filter_by_age(messages, max_age_seconds=max_age_seconds)
        return filtered[-limit:]

    def prune(
        self,
        *,
        max_age_seconds: int | None = None,
        max_entries_per_session: int | None = None,
    ) -> None:
        with self._lock:
            state = self._read()
            self._prune_state_locked(
                state,
                max_age_seconds=self.retention_seconds if max_age_seconds is None else max_age_seconds,
                max_entries_per_session=(
                    self.max_entries_per_session if max_entries_per_session is None else max_entries_per_session
                ),
            )
            self._write(state)

    @staticmethod
    def _filter_by_age(
        messages: list[dict[str, Any]],
        *,
        max_age_seconds: int | None,
    ) -> list[dict[str, Any]]:
        if max_age_seconds is None:
            return messages
        now = datetime.now(tz=UTC)
        filtered: list[dict[str, Any]] = []
        for row in messages:
            created_at = row.get("created_at")
            try:
                created = datetime.fromisoformat(str(created_at))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if (now - created).total_seconds() <= max_age_seconds:
                filtered.append(row)
        return filtered

    def _prune_state_locked(
        self,
        state: dict[str, Any],
        *,
        max_age_seconds: int | None,
        max_entries_per_session: int | None = None,
    ) -> None:
        sessions = state.setdefault("sessions", {})
        for session_key, session in list(sessions.items()):
            messages = list(session.get("messages", []))
            messages = self._filter_by_age(messages, max_age_seconds=max_age_seconds)
            if max_entries_per_session is not None:
                messages = messages[-max_entries_per_session:]
            if messages:
                session["messages"] = messages
                session["updated_at"] = messages[-1].get("created_at", _utc_now())
            else:
                sessions.pop(session_key, None)

    def recent_messages_for_profile(
        self,
        session_key: str,
        *,
        memory_profile: dict[str, Any] | None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        access = str((memory_profile or {}).get("conversational_memory", "read_write"))
        if access == "none":
            return []
        return self.recent_messages(session_key, limit=limit)

    def cleanup(self, *, max_age_hours: int = 72) -> int:
        cutoff = datetime.now(tz=UTC).timestamp() - max(1, int(max_age_hours)) * 3600
        removed = 0
        with self._lock:
            state = self._read()
            sessions = state.get("sessions", {})
            keep: dict[str, Any] = {}
            for key, session in sessions.items():
                updated_at = str(session.get("updated_at") or "")
                try:
                    updated_ts = datetime.fromisoformat(updated_at).timestamp()
                except ValueError:
                    updated_ts = cutoff + 1
                if updated_ts >= cutoff:
                    keep[key] = session
                else:
                    removed += 1
            state["sessions"] = keep
            if removed:
                self._write(state)
        return removed

    def stats(self) -> dict[str, Any]:
        with self._lock:
            sessions = self._read().get("sessions", {})
        message_count = sum(len(session.get("messages", [])) for session in sessions.values())
        return {"sessions": len(sessions), "messages": message_count}
