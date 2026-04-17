"""Temporary agent scratch memory that is not authoritative project truth."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class WorkingMemoryService:
    def __init__(
        self,
        path: Path | None = None,
        *,
        retention_seconds: int | None = 3 * 24 * 3600,
        max_scopes_per_agent: int = 40,
    ) -> None:
        self.path = path or (RuntimePaths.from_root().ensure().state_root / "working_memory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.retention_seconds = retention_seconds
        self.max_scopes_per_agent = max_scopes_per_agent
        if not self.path.exists():
            self._write({"agents": {}, "meta": {"created_at": _utc_now(), "updated_at": _utc_now()}})

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

    def get_state(self, agent_id: str, scope_key: str) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            return dict(state.get("agents", {}).get(agent_id, {}).get(scope_key, {}).get("payload", {}))

    def put_state(
        self,
        agent_id: str,
        scope_key: str,
        payload: dict[str, Any],
        *,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        record = {"payload": payload, "updated_at": updated_at or _utc_now()}
        with self._lock:
            state = self._read()
            state.setdefault("agents", {}).setdefault(agent_id, {})[scope_key] = record
            self._prune_state_locked(state, max_age_seconds=self.retention_seconds)
            self._write(state)
        return record

    def clear_state(self, agent_id: str, scope_key: str) -> None:
        with self._lock:
            state = self._read()
            agent_state = state.setdefault("agents", {}).setdefault(agent_id, {})
            agent_state.pop(scope_key, None)
            self._write(state)

    def prune(
        self,
        *,
        max_age_seconds: int | None = None,
        max_scopes_per_agent: int | None = None,
    ) -> None:
        with self._lock:
            state = self._read()
            self._prune_state_locked(
                state,
                max_age_seconds=self.retention_seconds if max_age_seconds is None else max_age_seconds,
                max_scopes_per_agent=(
                    self.max_scopes_per_agent if max_scopes_per_agent is None else max_scopes_per_agent
                ),
            )
            self._write(state)

    @staticmethod
    def _is_fresh(updated_at: str | None, *, max_age_seconds: int | None) -> bool:
        if max_age_seconds is None:
            return True
        if not updated_at:
            return False
        try:
            parsed = datetime.fromisoformat(str(updated_at))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (datetime.now(tz=UTC) - parsed).total_seconds() <= max_age_seconds

    def _prune_state_locked(
        self,
        state: dict[str, Any],
        *,
        max_age_seconds: int | None,
        max_scopes_per_agent: int | None = None,
    ) -> None:
        agents = state.setdefault("agents", {})
        for agent_id, scopes in list(agents.items()):
            fresh = {
                scope_key: record
                for scope_key, record in scopes.items()
                if self._is_fresh(record.get("updated_at"), max_age_seconds=max_age_seconds)
            }
            if max_scopes_per_agent is not None and len(fresh) > max_scopes_per_agent:
                ordered = sorted(
                    fresh.items(),
                    key=lambda item: item[1].get("updated_at", ""),
                    reverse=True,
                )
                fresh = dict(ordered[:max_scopes_per_agent])
            if fresh:
                agents[agent_id] = fresh
            else:
                agents.pop(agent_id, None)

    def get_state_for_profile(
        self,
        agent_id: str,
        scope_key: str,
        *,
        memory_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        access = str((memory_profile or {}).get("working_memory", "read_write"))
        if access == "none":
            return {}
        return self.get_state(agent_id, scope_key)

    def cleanup(self, *, max_age_hours: int = 24) -> int:
        cutoff = datetime.now(tz=UTC).timestamp() - max(1, int(max_age_hours)) * 3600
        removed = 0
        with self._lock:
            state = self._read()
            agents = state.get("agents", {})
            for agent_id, scopes in list(agents.items()):
                kept_scopes: dict[str, Any] = {}
                for scope_key, record in scopes.items():
                    updated_at = str(record.get("updated_at") or "")
                    try:
                        updated_ts = datetime.fromisoformat(updated_at).timestamp()
                    except ValueError:
                        updated_ts = cutoff + 1
                    if updated_ts >= cutoff:
                        kept_scopes[scope_key] = record
                    else:
                        removed += 1
                agents[agent_id] = kept_scopes
            if removed:
                self._write(state)
        return removed

    def stats(self) -> dict[str, Any]:
        with self._lock:
            agents = self._read().get("agents", {})
        scope_count = sum(len(scopes) for scopes in agents.values())
        return {"agents": len(agents), "scopes": scope_count}
