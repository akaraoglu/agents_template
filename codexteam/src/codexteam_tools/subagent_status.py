from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import ensure_existing_workspace
from .contract_registry import DEFAULT_DRAFT_FORMAT, DRAFT_FORMATS
from .execution_spec import EXECUTION_SPEC_FILENAME, load_execution_spec, ExecutionSpecError
from .execution_spec import execution_spec_reference

DRAFT_FORMAT_FILENAME = "draft-format.json"

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
        draft_pin = _read_object(attempt_dir / DRAFT_FORMAT_FILENAME)
        execution_spec_error: str | None = None
        try:
            execution_spec = load_execution_spec(attempt_dir / EXECUTION_SPEC_FILENAME)
            execution_spec_status = "valid"
        except (ExecutionSpecError, OSError) as exc:
            execution_spec = {}
            execution_spec_status = (
                "invalid"
                if (attempt_dir / EXECUTION_SPEC_FILENAME).exists()
                or (attempt_dir / EXECUTION_SPEC_FILENAME).is_symlink()
                else "absent"
            )
            execution_spec_error = str(exc) if execution_spec_status == "invalid" else None
        expected_spec = session.get("execution_spec")
        if execution_spec_status == "absent" and isinstance(expected_spec, dict):
            execution_spec_status = "invalid"
            execution_spec_error = "session references a missing execution specification"
        elif execution_spec_status == "absent" and (session or turn_state):
            execution_spec_status = "unsupported_pre_cutover"
            execution_spec_error = "attempt predates the curated execution contract"
        if execution_spec_status == "valid" and isinstance(expected_spec, dict):
            if expected_spec != execution_spec_reference(execution_spec):
                execution_spec_status = "invalid"
                execution_spec_error = "session execution specification reference mismatch"
                execution_spec = {}
        if not session and not turn_state and not draft_pin and not execution_spec:
            continue
        merged = {**session, **turn_state}
        identity = execution_spec.get("identity", {}) if execution_spec else {}
        profile_record = execution_spec.get("execution_profile", {}) if execution_spec else {}
        pinned_format = draft_pin.get("draft_format") or merged.get("draft_format")
        if pinned_format not in DRAFT_FORMATS:
            pinned_format = None
        explicit_pin_state = merged.get("draft_format_pinned")
        format_is_pinned = (
            bool(explicit_pin_state)
            if isinstance(explicit_pin_state, bool)
            else bool(draft_pin) or "draft_format" in session
        )
        status = str(merged.get("status") or merged.get("last_status") or "unknown")
        if turn_state.get("status") == "running":
            status = _running_status(turn_state, observed_at)
        record = {
            "team": merged.get("team_id", identity.get("team_id", attempt_dir.parents[1].name)),
            "task": merged.get("task_id", identity.get("task_id", attempt_dir.parent.name)),
            "attempt": merged.get("attempt_id", identity.get("attempt_id", attempt_dir.name)),
            "role": merged.get("agent_role", identity.get("role", "unknown")),
            "profile": profile_record.get("profile", {}).get("id", "unknown"),
            "agent_spec": (
                execution_spec.get("agent_spec", {}).get("id")
                if isinstance(execution_spec.get("agent_spec"), dict)
                else None
            ),
            "draft_format": pinned_format or DEFAULT_DRAFT_FORMAT,
            "draft_format_pinned": format_is_pinned,
            "policy": execution_spec.get("role_policy", {}).get("name", "invalid/unavailable"),
            "policy_digest": execution_spec.get("role_policy", {}).get("digest"),
            "phase": merged.get("phase") or session.get("last_phase", "unknown"),
            "turn": merged.get("turn_number") or session.get("turn_count", 0),
            "status": status,
            "updated_at": merged.get("updated_at") or session.get("updated_at"),
            "result": session.get("final_result_path"),
            "state_path": str((attempt_dir / "turn-state.json").relative_to(project_root)),
            "execution_spec_digest": execution_spec.get("execution_spec_digest"),
            "execution_spec_pinned": execution_spec_status in {"valid", "invalid"},
            "execution_spec_status": execution_spec_status,
            "execution_spec_error": execution_spec_error,
        }
        if profile_record.get("backend", {}).get("id"):
            record["backend"] = profile_record["backend"]["id"]
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
    include_format = any(record.get("draft_format_pinned") for record in records)
    include_agent_spec = any(record.get("agent_spec") for record in records)
    fields = ["team", "task", "attempt", "role"]
    if include_backend:
        fields.append("backend")
    if include_format:
        fields.append("draft_format")
    if include_agent_spec:
        fields.append("agent_spec")
    fields.extend(("profile", "policy", "phase", "turn", "status", "updated_at"))
    headers = [
        "UPDATED" if field == "updated_at" else "FORMAT" if field == "draft_format" else "AGENT_SPEC" if field == "agent_spec" else field.upper()
        for field in fields
    ]
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
