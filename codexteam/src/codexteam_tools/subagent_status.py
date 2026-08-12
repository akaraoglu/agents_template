from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import ensure_existing_workspace

def collect_subagent_status(
    project: str | Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    project_root = ensure_existing_workspace(project)
    sessions_root = project_root / ".codexteam" / "runtime" / "sessions"
    if not sessions_root.is_dir():
        return []
    observed_at = now or datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    for attempt_dir in sorted(sessions_root.glob("*/*/*")):
        if not attempt_dir.is_dir() or attempt_dir.is_symlink():
            continue
        session = _read_object(attempt_dir / "session.json")
        turn_state = _read_object(attempt_dir / "turn-state.json")
        if not session and not turn_state:
            continue
        merged = {**session, **turn_state}
        status = str(merged.get("status") or merged.get("last_status") or "unknown")
        if turn_state.get("status") == "running":
            status = _running_status(turn_state, observed_at)
        record = {
            "team": merged.get("team_id", attempt_dir.parents[1].name),
            "task": merged.get("task_id", attempt_dir.parent.name),
            "attempt": merged.get("attempt_id", attempt_dir.name),
            "role": merged.get("agent_role", "unknown"),
            "profile": merged.get("model_profile", "unknown"),
            "policy": merged.get("role_policy_name", "legacy/unpinned"),
            "policy_digest": merged.get("role_policy_digest"),
            "phase": merged.get("phase") or session.get("last_phase", "unknown"),
            "turn": merged.get("turn_number") or session.get("turn_count", 0),
            "status": status,
            "updated_at": merged.get("updated_at") or session.get("updated_at"),
            "result": session.get("final_result_path"),
            "state_path": str((attempt_dir / "turn-state.json").relative_to(project_root)),
        }
        if merged.get("execution_backend") == "opencode":
            record["backend"] = "opencode"
        records.append(record)
    return sorted(
        records,
        key=lambda item: (str(item.get("updated_at") or ""), item["task"], item["attempt"]),
        reverse=True,
    )


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _running_status(state: dict[str, Any], now: datetime) -> str:
    updated = _parse_utc(state.get("updated_at") or state.get("started_at"))
    timeout = state.get("timeout_seconds")
    if updated is None or not isinstance(timeout, int) or timeout < 1:
        return "running"
    grace = max(30, min(timeout, 300))
    return "stale" if now > updated + timedelta(seconds=timeout + grace) else "running"


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show project-local CodexTeam subagent state.")
    parser.add_argument("project", help="Initialized CodexTeam project root")
    parser.add_argument("--role")
    parser.add_argument("--status")
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = collect_subagent_status(args.project)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.role:
        records = [record for record in records if record["role"] == args.role]
    if args.status:
        records = [record for record in records if record["status"] == args.status]
    if args.active_only:
        records = [record for record in records if record["status"] in {"running", "stale"}]
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0
    if not records:
        print("No subagent sessions found.")
        return 0
    include_backend = any(record.get("backend") == "opencode" for record in records)
    fields = ["team", "task", "attempt", "role"]
    if include_backend:
        fields.append("backend")
    fields.extend(("profile", "policy", "phase", "turn", "status", "updated_at"))
    headers = ["UPDATED" if field == "updated_at" else field.upper() for field in fields]
    print(" ".join(headers))
    for record in records:
        print(
            " ".join(
                str(record.get(field, "codex" if field == "backend" else None) or "-")
                for field in fields
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
