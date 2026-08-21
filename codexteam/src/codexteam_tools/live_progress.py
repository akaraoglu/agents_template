from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
SAFE_EVENT_TYPES = {
    "error", "item.completed", "item.started", "step_finish", "step_start",
    "text", "thread.started", "tool_use", "turn.completed", "turn.started",
}
SAFE_TOOLS = {
    "apply_patch", "bash", "edit", "glob", "grep", "question", "read",
    "skill", "task", "todowrite", "webfetch", "write",
}
ACTIVE_SECONDS = 30
STALLED_SECONDS = 120


def collect_live_progress(
    attempt_dir: Path,
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "last_event_at": None,
        "event_count": 0,
        "output_bytes": 0,
        "last_event_type": None,
        "last_tool": None,
        "model_step_count": 0,
        "idle_seconds": None,
        "activity_state": None,
    }
    running = state.get("status") == "running"

    event_path = _current_event_path(attempt_dir, state)
    if event_path is None:
        return _classify(progress, _state_time(state), now) if running else progress
    stderr_path = event_path.with_suffix(".stderr.txt")
    paths = [path for path in (event_path, stderr_path) if _regular_file(path)]
    progress["output_bytes"] = sum(_file_size(path) for path in paths)

    modified_times = [value for path in paths if (value := _modified_at(path)) is not None]
    latest_time = max(modified_times, default=None)
    if latest_time is not None:
        progress["last_event_at"] = _isoformat(latest_time)
    try:
        with event_path.open(encoding="utf-8") as events:
            for line in events:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                progress["event_count"] += 1
                progress["last_event_type"] = _safe_event_type(event.get("type"))
                if event.get("type") == "step_finish":
                    progress["model_step_count"] += 1
                tool = _tool_name(event)
                if tool is not None:
                    progress["last_tool"] = tool
    except (OSError, UnicodeDecodeError):
        pass
    return _classify(progress, latest_time or _state_time(state), now) if running else progress


def _current_event_path(attempt_dir: Path, state: dict[str, Any]) -> Path | None:
    number = state.get("turn_number")
    phase = state.get("phase")
    if isinstance(number, int) and number > 0 and phase in {"draft", "feedback", "final"}:
        turns_dir = attempt_dir / "turns"
        if turns_dir.is_symlink() or not turns_dir.is_dir():
            return None
        current = turns_dir / f"{number:03d}-{phase}.jsonl"
        if state.get("status") == "running" or _regular_file(current):
            return current
        candidates = [
            path for path in turns_dir.iterdir()
            if _regular_file(path) and re.fullmatch(r"\d{3}-(?:draft|feedback|final)\.jsonl", path.name)
        ]
        return max(candidates, key=lambda path: path.name, default=None)
    return None


def _tool_name(event: dict[str, Any]) -> str | None:
    if event.get("type") == "tool_use":
        part = event.get("part")
        return _safe_tool(part.get("tool")) if isinstance(part, dict) else None
    if event.get("type") in {"item.completed", "item.started"}:
        item = event.get("item")
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type in {"command_execution", "mcp_tool_call", "file_change"}:
            return item_type
    return None


def _classify(
    progress: dict[str, Any],
    last_activity: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    if last_activity is None:
        return progress
    idle = max(0, int((now - last_activity).total_seconds()))
    progress["idle_seconds"] = idle
    progress["activity_state"] = (
        "active" if idle <= ACTIVE_SECONDS else "quiet" if idle <= STALLED_SECONDS else "stalled"
    )
    return progress


def _regular_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _modified_at(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def _state_time(state: dict[str, Any]) -> datetime | None:
    value = state.get("updated_at") or state.get("started_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _safe_label(value: Any) -> str | None:
    return value if isinstance(value, str) and SAFE_LABEL.fullmatch(value) else "unknown"


def _safe_event_type(value: Any) -> str:
    return value if value in SAFE_EVENT_TYPES else "unknown"


def _safe_tool(value: Any) -> str:
    return value if value in SAFE_TOOLS else "unknown"


def _isoformat(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")
