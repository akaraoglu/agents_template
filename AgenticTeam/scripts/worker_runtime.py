#!/usr/bin/env python3
"""Generic worker-runtime primitives for OpenClaw one-shot workers."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from covenant_contracts import (
    ContractValidationError,
    TaskPack,
    WorkReport,
    validate_task_pack,
    validate_work_report,
    validate_work_result,
)
from worker_contracts import ArtifactWorkerContract, PlanningProjectContract, WorkerContract

RUN_DEADLINE_SECONDS = 1800
ARTIFACT_WORK_ORDER_MAX_CHARS = 2000
ARTIFACT_CONTEXT_SOURCE_MAX_CHARS = 1200
ARTIFACT_CONTEXT_MAX_CHARS = 3200


class WorkerRuntimeError(RuntimeError):
    """Raised when the worker runtime cannot complete the requested step."""

    def __init__(self, message: str, *, code: str = "runtime_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedRun:
    run_dir: Path
    handoff_file: Path
    context_file: Path
    draft_file: Path


@dataclass(frozen=True)
class PreparedArtifactRun:
    run_dir: Path
    handoff_file: Path
    context_file: Path
    draft_dir: Path
    manifest_file: Path


@dataclass(frozen=True)
class AgentTaskRuntimeState:
    project_id: str
    task_id: str
    agent_role: str
    phase: str
    run_id: str
    run_dir: Path
    status: str
    required_outputs: tuple[str, ...]
    artifact_manifest: Path
    validation_plan: tuple[str, ...]
    validation_runs: tuple[dict[str, Any], ...]
    validation_report: dict[str, Any] | None
    final_decision: str | None


@dataclass(frozen=True)
class RuntimeOutcome:
    outcome: str
    status: str
    signal: str | None
    code: str | None
    message: str
    report_status: str | None = None
    repair_feedback: dict[str, Any] | None = None
    result_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "status": self.status,
            "signal": self.signal,
            "code": self.code,
            "message": self.message,
            "report_status": self.report_status,
        }
        if self.repair_feedback is not None:
            payload["repair_feedback"] = self.repair_feedback
        if self.result_file is not None:
            payload["result_file"] = self.result_file
        return payload


@dataclass(frozen=True)
class RegisteredSession:
    key: str
    session_id: str
    session_file: str
    created: bool
    task_scoped: bool


def workspace_root() -> Path:
    return Path(os.environ.get("CLAWSPACE_WORKSPACE_ROOT", "/home/alik/workspace/clawspace/workspaces"))


def live_bin_root() -> Path:
    return Path(os.environ.get("CLAWSPACE_BIN_ROOT", "/home/alik/workspace/clawspace/bin"))


def openclaw_root() -> Path:
    return Path(os.environ.get("OPENCLAW_ROOT", "/home/alik/.openclaw"))


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_morpheus_virtual_team_contracts(
    *,
    run_dir: Path,
    context_file: Path,
    draft_write_root: Path,
    manifest_write_file: Path,
    required_outputs: list[str],
    suggested_test_command: list[str],
) -> dict[str, str]:
    team_dir = run_dir / "team"
    team_dir.mkdir(parents=True, exist_ok=True)
    planner_note = team_dir / "planner.md"
    implementer_checklist = team_dir / "implementer_checklist.md"
    tester_review = team_dir / "tester_review.md"
    required = required_outputs or ["README.md"]
    test_command_text = " ".join(suggested_test_command)
    write_text(
        planner_note,
        "\n".join(
            [
                "# Planner Evidence",
                "",
                "Status: pending",
                "",
                "## Required Outputs",
                *[f"- {path}" for path in required],
                "",
                "## Artifact Plan",
                *[f"- {path}: pending implementation responsibility" for path in required],
                "",
                "## Test Command",
                test_command_text,
                "",
                "## Acceptance Checks",
                "- pending runtime reporting",
                "",
                f"Work order: {context_file}",
            ]
        )
        + "\n",
    )
    write_text(
        implementer_checklist,
        "\n".join(
            [
                "# Implementer Checklist",
                "",
                "Status: pending",
                "",
                "Required outputs:",
                *[f"- {path}" for path in required],
                "",
                f"Draft root: {draft_write_root}",
                f"Manifest: {manifest_write_file}",
                f"Test command: {test_command_text}",
            ]
        )
        + "\n",
    )
    write_text(
        tester_review,
        "\n".join(
            [
                "# Tester Review",
                "",
                "Status: pending",
                "",
                "## Reviewed Artifacts",
                *[f"- {path}" for path in required],
                "",
                "## Test Command",
                test_command_text,
                "",
                "## Findings",
                "- pending runtime reporting",
                "",
                f"Draft root: {draft_write_root}",
                f"Manifest: {manifest_write_file}",
            ]
        )
        + "\n",
    )
    return {
        "team_dir": str(team_dir),
        "planner_evidence_file": str(planner_note),
        "implementer_checklist_file": str(implementer_checklist),
        "tester_review_file": str(tester_review),
    }


def agent_task_runtime_state(run_dir: Path) -> AgentTaskRuntimeState:
    state = load_state(run_dir)
    run_id = str(state.get("run_id") or run_dir.name)
    validation_runs = state.get("validation_runs")
    if not isinstance(validation_runs, list):
        validation_runs = []
    validation_report = state.get("validation_report")
    if not isinstance(validation_report, dict):
        validation_report = None
    return AgentTaskRuntimeState(
        project_id=str(state.get("project_id", "")),
        task_id=str(state.get("task_id", "")),
        agent_role=str(state.get("role", "")),
        phase=str(state.get("phase", "")),
        run_id=run_id,
        run_dir=run_dir,
        status=str(state.get("status", "")),
        required_outputs=tuple(str(path) for path in state.get("required_output_paths", []) if str(path).strip()),
        artifact_manifest=Path(str(state.get("manifest_file", ""))),
        validation_plan=tuple(str(part) for part in state.get("validation_plan", []) if str(part).strip()),
        validation_runs=tuple(item for item in validation_runs if isinstance(item, dict)),
        validation_report=validation_report,
        final_decision=state.get("final_decision") if isinstance(state.get("final_decision"), str) else None,
    )


def ensure_directory_alias(target: Path, alias: Path) -> Path:
    alias.parent.mkdir(parents=True, exist_ok=True)
    if alias.is_symlink() or alias.exists():
        if alias.is_symlink() and alias.resolve() == target.resolve():
            return alias
        if alias.is_dir() and not alias.is_symlink():
            raise WorkerRuntimeError(f"alias path already exists as a real directory: {alias}", code="runtime_conflict")
        alias.unlink()
    alias.symlink_to(target, target_is_directory=True)
    return alias


def append_log(run_dir: Path, name: str, message: str) -> None:
    log_path = run_dir / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{iso_now()}] {message.rstrip()}\n")


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def load_state(run_dir: Path) -> dict[str, Any]:
    path = state_path(run_dir)
    if not path.exists():
        raise WorkerRuntimeError(
            "run state missing: "
            f"{path}. Use the RUN_DIR from the task packet; do not pass DRAFT_WRITE_ROOT, DRAFT_DIR, "
            "or MANIFEST_WRITE_FILE to report/complete/block.",
            code="missing_state",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    write_json(state_path(run_dir), state)


def update_state(run_dir: Path, **changes: Any) -> dict[str, Any]:
    state = load_state(run_dir)
    state.update(changes)
    save_state(run_dir, state)
    return state


def sanitize_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "value"


def parse_outcome(text: str) -> dict[str, Any] | None:
    for raw in text.splitlines():
        if raw.startswith("OUTCOME_JSON: "):
            try:
                return json.loads(raw.split("OUTCOME_JSON: ", 1)[1].strip())
            except json.JSONDecodeError:
                return None
    return None


def extract_content(text: str) -> str:
    match = re.search(r"CONTENT_BEGIN\n(?P<content>.*)\nCONTENT_END\s*$", text, flags=re.DOTALL)
    if not match:
        raise WorkerRuntimeError("helper output did not include CONTENT_BEGIN/CONTENT_END", code="invalid_helper_output")
    return match.group("content")


def command_details(result: subprocess.CompletedProcess[str]) -> str:
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    parts = [part for part in (stdout, stderr) if part]
    return "\n".join(parts) if parts else "no output"


def is_tool_denial_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "allowlist miss",
            "exec denied",
            "not allowed",
            "forbidden",
            "tool policy removed",
        )
    )


def run_command(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def require_ok(result: subprocess.CompletedProcess[str], *, action: str) -> str:
    details = command_details(result)
    outcome = parse_outcome(details)
    if is_tool_denial_text(details):
        raise WorkerRuntimeError(f"{action} denied by tool policy: {details}", code="tool_denied")
    if result.returncode != 0:
        raise WorkerRuntimeError(f"{action} failed: {details}", code="helper_failed")
    if outcome and outcome.get("status") != "OK":
        if is_tool_denial_text(details):
            raise WorkerRuntimeError(f"{action} denied by tool policy: {details}", code="tool_denied")
        raise WorkerRuntimeError(f"{action} returned {outcome.get('status')}: {details}", code="helper_failed")
    return result.stdout or ""


def parse_envelope(raw: str, contract: WorkerContract) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"invalid envelope JSON: {exc}", code="envelope_invalid") from exc
    if not isinstance(payload, dict):
        raise WorkerRuntimeError("envelope must be a JSON object", code="envelope_invalid")

    required = ("project_id", "task_id", "from", "to", "phase", "instructions")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise WorkerRuntimeError(
            f"envelope missing required field(s): {', '.join(missing)}",
            code="envelope_invalid",
        )
    if "project_path" in payload:
        raise WorkerRuntimeError("envelope must not contain project_path", code="envelope_invalid")

    project_id = str(payload["project_id"]).strip()
    task_id = str(payload["task_id"]).strip().upper()
    from_agent = str(payload["from"]).strip().lower()
    to_agent = str(payload["to"]).strip().lower()
    phase = str(payload["phase"]).strip().upper()
    instructions = str(payload["instructions"]).strip()

    if not re.fullmatch(r"[a-z0-9-]+", project_id):
        raise WorkerRuntimeError(f"invalid project_id: {project_id}", code="envelope_invalid")
    if not re.fullmatch(r"[A-Z0-9_-]+", task_id):
        raise WorkerRuntimeError(f"invalid task_id: {task_id}", code="envelope_invalid")
    if from_agent != contract.expected_from or to_agent != contract.expected_to or phase != contract.phase:
        raise WorkerRuntimeError(
            f"unexpected routing: {from_agent}->{to_agent} phase={phase}; "
            f"expected {contract.expected_from}->{contract.expected_to} phase={contract.phase}",
            code="envelope_invalid",
        )

    return {
        "project_id": project_id,
        "task_id": task_id,
        "from": from_agent,
        "to": to_agent,
        "phase": phase,
        "instructions": instructions,
    }


def load_latest_handoff_event(
    project_path: str | Path,
    *,
    project_id: str,
    from_agent: str,
    to_agent: str,
    phase: str,
) -> dict[str, Any] | None:
    ledger_path = Path(project_path) / ".openclaw" / "handoffs.jsonl"
    if not ledger_path.is_file():
        return None
    for raw in reversed(ledger_path.read_text(encoding="utf-8").splitlines()):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (
            str(event.get("event_type", "")).strip() == "handoff_sent"
            and str(event.get("project_id", "")).strip() == project_id
            and str(event.get("from", "")).strip().lower() == from_agent
            and str(event.get("to", "")).strip().lower() == to_agent
            and str(event.get("phase", "")).strip().upper() == phase
        ):
            return event
    return None


def reconcile_task_id_from_handoff_ledger(
    contract: WorkerContract | ArtifactWorkerContract,
    envelope: dict[str, str],
    resolved: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any] | None, bool]:
    latest_handoff = load_latest_handoff_event(
        resolved["project_path"],
        project_id=envelope["project_id"],
        from_agent=contract.expected_from,
        to_agent=contract.expected_to,
        phase=contract.phase,
    )
    envelope_task_id = str(envelope["task_id"]).strip().upper()
    ledger_task_id = str((latest_handoff or {}).get("task_id", "")).strip().upper()
    if re.fullmatch(r"T\d{3}", envelope_task_id):
        if ledger_task_id and ledger_task_id != envelope_task_id:
            raise WorkerRuntimeError(
                f"envelope task_id {envelope_task_id} does not match latest handoff task_id {ledger_task_id}",
                code="envelope_invalid",
            )
        return envelope, latest_handoff, False
    if re.fullmatch(r"T\d{3}", ledger_task_id):
        repaired = dict(envelope)
        repaired["task_id"] = ledger_task_id
        return repaired, latest_handoff, True
    raise WorkerRuntimeError(f"invalid task_id: {envelope_task_id}", code="envelope_invalid")


def parse_planning_envelope(raw: str, contract: PlanningProjectContract) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"invalid envelope JSON: {exc}", code="envelope_invalid") from exc
    if not isinstance(payload, dict):
        raise WorkerRuntimeError("envelope must be a JSON object", code="envelope_invalid")

    required = ("project_id", "from", "to", "phase", "instructions")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise WorkerRuntimeError(
            f"envelope missing required field(s): {', '.join(missing)}",
            code="envelope_invalid",
        )
    if "project_path" in payload:
        raise WorkerRuntimeError("envelope must not contain project_path", code="envelope_invalid")

    project_id = str(payload["project_id"]).strip()
    from_agent = str(payload["from"]).strip().lower()
    to_agent = str(payload["to"]).strip().lower()
    phase = str(payload["phase"]).strip().upper()
    instructions = str(payload["instructions"]).strip()

    if not re.fullmatch(r"[a-z0-9-]+", project_id):
        raise WorkerRuntimeError(f"invalid project_id: {project_id}", code="envelope_invalid")
    if from_agent != contract.expected_from or to_agent != contract.expected_to or phase != contract.phase:
        raise WorkerRuntimeError(
            f"unexpected routing: {from_agent}->{to_agent} phase={phase}; "
            f"expected {contract.expected_from}->{contract.expected_to} phase={contract.phase}",
            code="envelope_invalid",
        )

    return {
        "project_id": project_id,
        "from": from_agent,
        "to": to_agent,
        "phase": phase,
        "instructions": instructions,
    }


def resolve_project(project_id: str) -> dict[str, Any]:
    result = run_command(
        ["bash", str(live_bin_root() / "resolve_project.sh"), project_id, "--json"],
        timeout=120,
    )
    if result.returncode != 0:
        raise WorkerRuntimeError(f"resolve_project failed: {command_details(result)}", code="missing_input")
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"resolve_project returned invalid JSON: {exc}", code="invalid_helper_output") from exc
    return payload


def send_session_message(session_key: str, message: str, *, timeout_ms: int = 20000) -> str:
    payload = json.dumps({"key": session_key, "message": message}, separators=(",", ":"))
    result = run_command(
        [
            "openclaw",
            "gateway",
            "call",
            "sessions.send",
            "--json",
            "--params",
            payload,
            "--timeout",
            str(timeout_ms),
        ],
        timeout=max(30, timeout_ms // 1000 + 10),
    )
    if result.returncode != 0:
        raise WorkerRuntimeError(f"sessions.send failed: {command_details(result)}", code="send_failed")
    return (result.stdout or "").strip()


def task_scoped_session_key(agent: str, run_id: str) -> str:
    normalized_agent = agent.strip().lower()
    if not normalized_agent:
        raise WorkerRuntimeError("cannot create task session key without an agent", code="session_registration_failed")
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id.strip()).strip(".-").lower()
    if not safe_run_id:
        raise WorkerRuntimeError("cannot create task session key without a run_id", code="session_registration_failed")
    return f"agent:{normalized_agent}:run:{safe_run_id[:96]}"


def _session_registry_path(agent: str) -> Path:
    return openclaw_root() / "agents" / agent / "sessions" / "sessions.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _new_session_entry(source_entry: Mapping[str, Any], *, session_key: str, session_file: Path) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    entry = dict(source_entry)
    session_id = session_file.stem
    key_parts = session_key.split(":")
    usage_agent = key_parts[1] if len(key_parts) > 2 else "main"
    entry.update(
        {
            "sessionId": session_id,
            "sessionFile": str(session_file),
            "updatedAt": now_ms,
            "sessionStartedAt": now_ms,
            "lastInteractionAt": now_ms,
            "systemSent": False,
            "abortedLastRun": False,
            "compactionCount": 0,
            "totalTokens": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "status": "done",
        }
    )
    if "key" in entry:
        entry["key"] = session_key
    entry["usageFamilyKey"] = f"agent:{usage_agent}:main"
    return entry


def ensure_registered_task_session(agent: str, run_id: str) -> RegisteredSession:
    agent = agent.strip().lower()
    session_key = task_scoped_session_key(agent, run_id)
    sessions_path = _session_registry_path(agent)
    sessions_dir = sessions_path.parent
    main_key = f"agent:{agent}:main"
    if not sessions_path.exists():
        raise WorkerRuntimeError(
            f"OpenClaw session registry missing for {agent}: {sessions_path}",
            code="session_registration_failed",
        )

    sessions_dir.mkdir(parents=True, exist_ok=True)
    lock_path = sessions_path.with_suffix(".lock")
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                payload = json.loads(sessions_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise WorkerRuntimeError(
                    f"OpenClaw session registry invalid for {agent}: {exc}",
                    code="session_registration_failed",
                ) from exc
            if not isinstance(payload, dict):
                raise WorkerRuntimeError(
                    f"OpenClaw session registry is not an object: {sessions_path}",
                    code="session_registration_failed",
                )

            existing = payload.get(session_key)
            if isinstance(existing, dict):
                session_file = str(existing.get("sessionFile", "")).strip()
                if session_file:
                    Path(session_file).parent.mkdir(parents=True, exist_ok=True)
                    Path(session_file).touch(exist_ok=True)
                return RegisteredSession(
                    key=session_key,
                    session_id=str(existing.get("sessionId", "")),
                    session_file=session_file,
                    created=False,
                    task_scoped=True,
                )

            source_entry = payload.get(main_key)
            if not isinstance(source_entry, dict):
                raise WorkerRuntimeError(
                    f"OpenClaw main session registry missing for {agent}: {main_key}",
                    code="session_registration_failed",
                )

            session_id = str(uuid4())
            session_file = sessions_dir / f"{session_id}.jsonl"
            session_file.write_text("", encoding="utf-8")
            payload[session_key] = _new_session_entry(source_entry, session_key=session_key, session_file=session_file)
            _write_json_atomic(sessions_path, payload)
            return RegisteredSession(
                key=session_key,
                session_id=session_id,
                session_file=str(session_file),
                created=True,
                task_scoped=True,
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def artifact_dispatch_session(contract: ArtifactWorkerContract, state: Mapping[str, Any]) -> RegisteredSession:
    if contract.role != "morpheus":
        key = f"agent:{contract.expected_to}:main"
        return RegisteredSession(key=key, session_id="", session_file="", created=False, task_scoped=False)
    run_id = str(state.get("run_id") or "").strip()
    return ensure_registered_task_session(contract.expected_to, run_id)


def parse_send_response_ids(response: str) -> dict[str, str]:
    if not response.strip():
        return {}
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return {}
    found: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = key.lower()
                if normalized in {"runid", "run_id", "gatewayrunid", "gateway_run_id"} and isinstance(nested, str):
                    found.setdefault("gateway_run_id", nested)
                elif normalized in {"sessionid", "session_id"} and isinstance(nested, str):
                    found.setdefault("gateway_session_id", nested)
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
    return found


def build_run_dir(contract: WorkerContract, project_id: str, task_id: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{uuid4().hex[:8]}"
    return workspace_root() / contract.role / "runs" / project_id / task_id / run_id


def build_phase_run_dir(role: str, project_id: str, phase_slug: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{uuid4().hex[:8]}"
    return workspace_root() / role / "runs" / project_id / phase_slug / run_id


def truncate_context_preview(content: str, *, max_chars: int, trailer: str) -> tuple[str, bool]:
    text = content.rstrip()
    if len(text) <= max_chars:
        return text, False
    reserve = max(80, len(trailer) + 2)
    clipped = text[: max_chars - reserve].rstrip()
    return clipped + trailer, True


def build_context_markdown(
    envelope: dict[str, str],
    inputs: list[dict[str, str]],
    *,
    source_max_chars: int | None = None,
    total_max_chars: int | None = None,
    include_full_input_index: bool = False,
) -> str:
    lines = [
        "# Worker Context",
        "",
        f"- **project_id**: `{envelope['project_id']}`",
        f"- **task_id**: `{envelope['task_id']}`",
        f"- **phase**: `{envelope['phase']}`",
        f"- **instructions**: {envelope['instructions']}",
        "",
        "## Rooted Inputs",
        "",
    ]
    if include_full_input_index:
        lines.extend(["## Full Input Copies", ""])
        for item in inputs:
            audit_copy = item.get("audit_copy")
            if audit_copy:
                lines.append(f"- `{item['path']}` -> `{audit_copy}`")
        lines.extend(["", "## Source Excerpts", ""])
    current_length = len("\n".join(lines))
    remaining_inputs = False
    for item in inputs:
        content = item["content"].rstrip()
        if source_max_chars:
            trailer = "\n\n[truncated; read the matching full input copy above if you need the full source]"
            content, _ = truncate_context_preview(content, max_chars=source_max_chars, trailer=trailer)
        block_lines = [f"## Source: {item['path']}", "", content, ""]
        block_text = "\n".join(block_lines)
        if total_max_chars and current_length + len(block_text) > total_max_chars:
            remaining_inputs = True
            remaining = total_max_chars - current_length
            if remaining > 240:
                trailer = "\n\n[context truncated; read the matching full input copy above if you need more detail]"
                clipped, _ = truncate_context_preview(content, max_chars=remaining - 64, trailer=trailer)
                block_lines = [f"## Source: {item['path']}", "", clipped, ""]
                lines.extend(block_lines)
            break
        lines.extend(block_lines)
        current_length += len(block_text)
    if remaining_inputs:
        lines.extend(
            [
                "[additional rooted inputs omitted from CONTEXT_FILE; use the full input copy list above for targeted follow-up reads]",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_work_order_summary(inputs: list[dict[str, str]], *, max_chars: int = 5000) -> tuple[str, bool]:
    lines = ["WORK_ORDER_BEGIN"]
    for item in inputs:
        lines.append(f"--- {item['path']} ---")
        lines.append(item["content"].strip())
        lines.append("")
    text = "\n".join(lines).rstrip()
    truncated = False
    if len(text) > max_chars:
        truncated = True
        text = text[: max_chars - 80].rstrip() + "\n\n[truncated; use CONTEXT_FILE only if more detail is required]"
    return text + "\nWORK_ORDER_END", truncated


def build_worker_draft_template(contract: WorkerContract, *, task_id: str) -> str:
    headings = [
        pattern.removeprefix("^## ")
        for pattern in contract.render_verify_patterns(task_id=task_id)
        if pattern.startswith("^## ")
    ]
    lines = ["DRAFT_TEMPLATE_BEGIN", f"# {task_id} Architecture", ""]
    for heading in headings:
        lines.extend([f"## {heading}", "", f"{heading} content for {task_id}.", ""])
    lines.append("DRAFT_TEMPLATE_END")
    return "\n".join(lines).rstrip() + "\n"


def prepare_run(contract: WorkerContract, envelope_raw: str) -> PreparedRun:
    envelope = parse_envelope(envelope_raw, contract)
    resolved = resolve_project(envelope["project_id"])
    envelope, latest_handoff, task_id_repaired = reconcile_task_id_from_handoff_ledger(contract, envelope, resolved)
    run_dir = build_run_dir(contract, envelope["project_id"], envelope["task_id"])
    run_dir.mkdir(parents=True, exist_ok=True)

    draft_file = run_dir / contract.draft_file_name
    handoff_file = run_dir / "handoff.json"
    context_file = run_dir / "context.md"
    envelope_file = run_dir / "envelope.json"
    write_json(envelope_file, envelope)

    state = {
        "role": contract.role,
        "phase": contract.phase,
        "run_id": run_dir.name,
        "runtime_model": "AgentTaskRuntime",
        "status": "preparing",
        "prepared_at": iso_now(),
        "prepared_epoch": time.time(),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=RUN_DEADLINE_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_id": envelope["project_id"],
        "task_id": envelope["task_id"],
        "session_key": contract.session_key,
        "draft_file": str(draft_file),
        "context_file": str(context_file),
        "handoff_file": str(handoff_file),
        "last_error": None,
        "last_send_response": None,
        "result_payload": None,
        "latest_handoff_event": latest_handoff,
        "task_id_repaired_from_handoff": task_id_repaired,
    }
    save_state(run_dir, state)
    append_log(run_dir, "prepare", f"prepare started for {envelope['project_id']} {envelope['task_id']}")

    try:
        output_path = contract.render_output_path(task_id=envelope["task_id"])
        context_dir = run_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        inputs: list[dict[str, str]] = []
        for index, relative_path in enumerate(contract.render_read_paths(task_id=envelope["task_id"]), start=1):
            result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_read.sh"),
                    envelope["project_id"],
                    relative_path,
                    "--action",
                    f"{contract.role}_runtime_prepare_read",
                ],
                timeout=120,
            )
            stdout = require_ok(result, action=f"project_read {relative_path}")
            content = extract_content(stdout)
            audit_copy = context_dir / f"{index:02d}-{sanitize_name(relative_path)}"
            write_text(audit_copy, content if content.endswith("\n") else content + "\n")
            inputs.append({"path": relative_path, "content": content, "audit_copy": str(audit_copy)})

        write_text(
            context_file,
            build_context_markdown(
                envelope,
                inputs,
                source_max_chars=ARTIFACT_CONTEXT_SOURCE_MAX_CHARS,
                total_max_chars=ARTIFACT_CONTEXT_MAX_CHARS,
                include_full_input_index=True,
            ),
        )
        handoff_payload = {
            "run_dir": str(run_dir),
            "context_file": str(context_file),
            "draft_file": str(draft_file),
            "output_path": output_path,
            "project_id": envelope["project_id"],
            "task_id": envelope["task_id"],
            "phase": contract.phase,
            "deadline_at": state["deadline_at"],
            "required_sections": [pattern for pattern in contract.render_verify_patterns(task_id=envelope["task_id"]) if pattern.startswith("^## ")],
            "next_command": f"bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"",
        }
        write_json(handoff_file, handoff_payload)
        update_state(
            run_dir,
            status="awaiting_draft",
            project_path=str(resolved["project_path"]),
            output_path=output_path,
            inputs=[{"path": item["path"], "audit_copy": item["audit_copy"]} for item in inputs],
            last_error=None,
        )
        append_log(run_dir, "prepare", f"prepare completed; output={output_path}")
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="prepare_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "prepare", f"prepare failed: {exc}")
        raise

    print(f"RUN_DIR={run_dir}")
    print(f"HANDOFF_FILE={handoff_file}")
    print(f"CONTEXT_FILE={context_file}")
    print(f"DRAFT_FILE={draft_file}")
    print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"")
    work_order_text, _ = build_work_order_summary(inputs)
    print(work_order_text)
    print(build_worker_draft_template(contract, task_id=envelope["task_id"]))
    return PreparedRun(run_dir=run_dir, handoff_file=handoff_file, context_file=context_file, draft_file=draft_file)


def read_run(contract: WorkerContract, run_dir: Path, relative_path: str) -> str:
    state = load_state(run_dir)
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")
    if state.get("status") in {"sent", "blocked"}:
        raise WorkerRuntimeError(f"run already terminal: {state.get('status')}", code="terminal_run")

    result = run_command(
        [
            "bash",
            str(live_bin_root() / "project_read.sh"),
            state["project_id"],
            relative_path,
            "--action",
            f"{contract.role}_runtime_followup_read",
        ],
        timeout=120,
    )
    stdout = require_ok(result, action=f"project_read {relative_path}")
    content = extract_content(stdout)
    audit_dir = run_dir / "context" / "followup"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_copy = audit_dir / sanitize_name(relative_path)
    write_text(audit_copy, content if content.endswith("\n") else content + "\n")
    reads_path = run_dir / "reads.jsonl"
    with reads_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"path": relative_path, "audit_copy": str(audit_copy), "read_at": iso_now()}, sort_keys=True) + "\n")
    append_log(run_dir, "read", f"follow-up read: {relative_path}")
    return stdout


def ensure_expected_draft(state: dict[str, Any]) -> Path:
    draft_file = Path(state["draft_file"])
    if not draft_file.exists() or not draft_file.is_file():
        raise WorkerRuntimeError(f"expected draft file missing: {draft_file}", code="missing_draft")
    if draft_file.stat().st_mtime <= float(state.get("prepared_epoch", 0.0)):
        raise WorkerRuntimeError(f"draft file was not updated after prepare: {draft_file}", code="missing_draft")
    return draft_file


def verify_draft_content(contract: WorkerContract, draft_text: str, *, task_id: str) -> None:
    missing = [
        pattern
        for pattern in contract.render_verify_patterns(task_id=task_id)
        if re.search(pattern, draft_text, flags=re.MULTILINE) is None
    ]
    if missing:
        raise WorkerRuntimeError(
            "draft is missing required content: " + ", ".join(missing),
            code="verification_failed",
        )


def build_result_payload(contract: WorkerContract, state: dict[str, Any], *, instructions: str) -> dict[str, str]:
    payload: dict[str, Any] = {
        "project_id": str(state["project_id"]),
        "task_id": str(state["task_id"]),
        "from": contract.role,
        "to": contract.expected_from,
        "phase": contract.phase,
        "instructions": instructions,
    }
    work_result = state.get("outbound_work_result")
    if isinstance(work_result, dict):
        payload["work_result"] = work_result
    work_report = state.get("outbound_work_report")
    if isinstance(work_report, dict):
        payload["work_report"] = work_report
    project_workspace = state.get("outbound_project_workspace")
    if isinstance(project_workspace, dict):
        payload["project_workspace"] = project_workspace
    artifact_manifest = state.get("outbound_artifact_manifest")
    if isinstance(artifact_manifest, dict):
        payload["artifact_manifest"] = artifact_manifest
    return payload


def build_artifact_result_payload(
    contract: ArtifactWorkerContract,
    state: dict[str, Any],
    *,
    instructions: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(state["project_id"]),
        "task_id": str(state["task_id"]),
        "from": contract.role,
        "to": contract.expected_from,
        "phase": contract.phase,
        "instructions": instructions,
    }
    work_result = state.get("outbound_work_result")
    if isinstance(work_result, dict):
        payload["work_result"] = work_result
    work_report = state.get("outbound_work_report")
    if isinstance(work_report, dict):
        payload["work_report"] = work_report
    project_workspace = state.get("outbound_project_workspace")
    if isinstance(project_workspace, dict):
        payload["project_workspace"] = project_workspace
    artifact_manifest = state.get("outbound_artifact_manifest")
    if isinstance(artifact_manifest, dict):
        payload["artifact_manifest"] = artifact_manifest
    return payload


def build_child_result_signal(
    *,
    state: dict[str, Any],
    from_agent: str,
    to_agent: str,
    phase: str,
    signal: str,
    reason: str | None = None,
) -> dict[str, str]:
    payload = {
        "project_id": str(state["project_id"]),
        "task_id": str(state["task_id"]),
        "from": from_agent,
        "to": to_agent,
        "phase": phase,
        "signal": signal,
        "run_id": str(state.get("run_id") or ""),
    }
    if reason:
        payload["reason"] = reason
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _artifact_expected_paths(state: Mapping[str, Any], fallback: list[str] | None = None) -> list[str]:
    expected = _string_list(state.get("required_output_paths"))
    if expected:
        return expected
    artifacts = _string_list(state.get("artifacts"))
    if artifacts:
        return artifacts
    if fallback:
        return fallback
    return ["README.md"]


def _artifact_relevant_files(state: Mapping[str, Any]) -> list[str]:
    inputs = state.get("inputs")
    if not isinstance(inputs, list):
        return []
    relevant: list[str] = []
    for item in inputs:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            relevant.append(path)
    return relevant


def _artifact_task_pack_payload(
    contract: ArtifactWorkerContract,
    state: Mapping[str, Any],
    *,
    expected_artifacts: list[str] | None = None,
    allowed_write_paths: list[str] | None = None,
    verification_command: list[str] | None = None,
) -> dict[str, Any]:
    expected = expected_artifacts or _artifact_expected_paths(state)
    allowed = allowed_write_paths or expected
    command = verification_command or _string_list(state.get("validation_plan")) or _string_list(state.get("team_test_command"))
    if not command:
        command = ["bash", "-lc", "runtime outcome recorded before project validation"]
    previous_failure = state.get("last_error")
    if not isinstance(previous_failure, Mapping):
        previous_failure = None
    return {
        "project_id": str(state["project_id"]),
        "workspace_root": str(Path(str(state["project_path"])).resolve()),
        "task_id": str(state["task_id"]),
        "role": contract.role,
        "goal": str(state.get("instructions") or f"{contract.phase} task {state['task_id']}"),
        "acceptance_criteria": [
            f"Complete {state['task_id']} for phase {contract.phase}.",
            "Report only DONE, BLOCKED, FAILED, or NEEDS_REVIEW with runtime-checkable evidence.",
        ],
        "allowed_write_paths": allowed,
        "expected_artifacts": expected,
        "relevant_files": _artifact_relevant_files(state),
        "available_tools": ["project_write.sh", "verify_artifact.sh", "project_exec.sh", f"{contract.role}_run_task.sh"],
        "recommended_verification": command,
        "previous_failure": dict(previous_failure) if previous_failure else None,
        "repair_budget": int(state.get("repair_budget", 5)),
        "report_destination": f"covenant://runtime/{contract.role}/{state['project_id']}/{state['task_id']}",
        "approved_runtime_evidence_roots": [],
    }


def _artifact_finish_command(contract: ArtifactWorkerContract, run_dir: Path) -> str:
    finish_command = "report" if contract.role == "morpheus" else "complete"
    return f"bash {live_bin_root() / (contract.role + '_run_task.sh')} {finish_command} \"{run_dir}\""


def _project_workspace_payload(task_pack: TaskPack) -> dict[str, Any]:
    return {
        "workspace_root": task_pack.workspace_root,
        "allowed_write_paths": task_pack.allowed_write_paths,
        "expected_artifacts": task_pack.expected_artifacts,
        "approved_runtime_evidence_roots": task_pack.approved_runtime_evidence_roots,
    }


def _artifact_exists_from_report(task_pack: TaskPack, report_payload: Mapping[str, Any]) -> Any:
    manifest = report_payload.get("artifact_manifest")
    declared: set[str] = set(_string_list(report_payload.get("changed_files")))
    if isinstance(manifest, Mapping):
        for key in ("created", "changed", "expected_artifacts", "evidence_paths"):
            declared.update(_string_list(manifest.get(key)))

    workspace_root_path = task_pack.workspace_root_path.resolve()

    def exists(path: Path) -> bool:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(workspace_root_path).as_posix()
        except ValueError:
            return resolved.exists()
        return relative in declared or resolved.exists()

    return exists


def _repair_attempts_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    last_error = state.get("last_error")
    if isinstance(last_error, Mapping):
        attempts.append(
            {
                "code": str(last_error.get("code") or "previous_failure"),
                "message": str(last_error.get("message") or ""),
                "recorded_at": iso_now(),
            }
        )
    return attempts


def _work_result_from_report(contract: ArtifactWorkerContract, state: Mapping[str, Any], report: WorkReport) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(state["project_id"]),
        "task_id": report.task_id,
        "from": contract.role,
        "phase": contract.phase,
        "status": report.status,
        "summary": report.summary,
    }
    if report.verification is not None:
        payload["verification"] = report.verification.to_dict()
    if report.blocker is not None:
        payload["reason"] = report.blocker["reason"]
        if report.blocker.get("next_action"):
            payload["next_action"] = report.blocker["next_action"]
    return validate_work_result(payload).to_dict()


def _artifact_done_report_payload(
    contract: ArtifactWorkerContract,
    state: Mapping[str, Any],
    *,
    artifacts: list[str],
    test_command: list[str],
    test_summary: str,
) -> dict[str, Any]:
    return {
        "task_id": str(state["task_id"]),
        "agent": contract.role,
        "status": "DONE",
        "summary": test_summary,
        "changed_files": artifacts,
        "verification": {
            "task_id": str(state["task_id"]),
            "agent": contract.role,
            "timestamp": iso_now(),
            "performed": True,
            "command": test_command,
            "status": "pass",
            "summary": test_summary,
            "evidence_paths": artifacts,
        },
        "repair_attempts": _repair_attempts_from_state(state),
        "next_owner": None,
        "blocker": None,
        "artifact_manifest": {
            "created": artifacts,
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": artifacts,
            "evidence_paths": artifacts,
        },
    }


def _artifact_blocked_report_payload(
    contract: ArtifactWorkerContract,
    state: Mapping[str, Any],
    *,
    code: str,
    reason: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    blocked_next_action = next_action or "Escalate to the parent owner with this blocker and decide whether to re-scope or approve new capability."
    return {
        "task_id": str(state["task_id"]),
        "agent": contract.role,
        "status": "BLOCKED",
        "summary": f"{code}: {reason}",
        "changed_files": [],
        "verification": None,
        "repair_attempts": _repair_attempts_from_state(state),
        "next_owner": contract.expected_from,
        "blocker": {
            "reason": reason,
            "next_action": blocked_next_action,
        },
        "artifact_manifest": None,
    }


def _runtime_repair_feedback(
    *,
    code: str,
    reason: str,
    next_action: str,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "next_action": next_action,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "remaining_attempts": max(0, max_attempts - attempt),
    }


def record_artifact_repair_required(
    contract: ArtifactWorkerContract,
    run_dir: Path,
    state: Mapping[str, Any],
    *,
    code: str,
    reason: str,
    next_action: str | None = None,
) -> RuntimeOutcome:
    attempt = int(state.get("completion_attempts", 0))
    max_attempts = int(state.get("repair_budget", 5))
    action = next_action or f"Repair the task drafts and rerun {_artifact_finish_command(contract, run_dir)}."
    if attempt > max_attempts:
        return send_blocked_from_state(
            contract,
            run_dir,
            dict(state),
            code=code,
            reason=f"repair budget exhausted after {attempt} attempts: {reason}",
            next_action="Escalate to the parent owner because runtime repair budget is exhausted.",
        )
    feedback = _runtime_repair_feedback(code=code, reason=reason, next_action=action, attempt=attempt, max_attempts=max_attempts)
    outcome = RuntimeOutcome(
        outcome="REPAIR_REQUIRED",
        status="repair_needed",
        signal=None,
        code=code,
        message=reason,
        report_status=None,
        repair_feedback=feedback,
        result_file=str(run_dir / "result.json"),
    )
    update_state(
        run_dir,
        status="repair_needed",
        last_error={"code": code, "message": reason},
        repair_feedback=feedback,
        last_runtime_outcome=outcome.to_dict(),
    )
    append_log(run_dir, "outcome", f"runtime outcome REPAIR_REQUIRED code={code}")
    return outcome


def handle_artifact_work_report_outcome(
    contract: ArtifactWorkerContract,
    run_dir: Path,
    state: Mapping[str, Any],
    work_report_payload: Mapping[str, Any],
    *,
    accepted_instructions: str | None = None,
    accepted_state_updates: Mapping[str, Any] | None = None,
) -> RuntimeOutcome:
    changed_files = _string_list(work_report_payload.get("changed_files"))
    expected_artifacts = _artifact_expected_paths(state, changed_files)
    allowed_write_paths = list(dict.fromkeys([*expected_artifacts, *changed_files]))
    verification_command = _string_list((work_report_payload.get("verification") or {}).get("command")) if isinstance(work_report_payload.get("verification"), Mapping) else None
    try:
        task_pack = validate_task_pack(
            _artifact_task_pack_payload(
                contract,
                state,
                expected_artifacts=expected_artifacts,
                allowed_write_paths=allowed_write_paths,
                verification_command=verification_command,
            )
        )
        report = validate_work_report(
            work_report_payload,
            task_pack=task_pack,
            artifact_exists=_artifact_exists_from_report(task_pack, work_report_payload),
        )
    except ContractValidationError as exc:
        return record_artifact_repair_required(
            contract,
            run_dir,
            state,
            code="work_report_invalid",
            reason=f"invalid work_report: {exc}",
            next_action="Repair the WorkReport fields and rerun completion; do not send a prose-only terminal signal.",
        )

    work_report = report.to_dict()
    work_result = _work_result_from_report(contract, state, report)
    if report.status == "DONE":
        project_workspace = _project_workspace_payload(task_pack)
        artifact_manifest = report.artifact_manifest.to_dict() if report.artifact_manifest else {
            "created": report.changed_files,
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": task_pack.expected_artifacts,
            "evidence_paths": report.verification.evidence_paths if report.verification else [],
        }
        payload_state = {
            **dict(state),
            "outbound_work_result": work_result,
            "outbound_work_report": work_report,
            "outbound_project_workspace": project_workspace,
            "outbound_artifact_manifest": artifact_manifest,
        }
        payload = build_artifact_result_payload(
            contract,
            payload_state,
            instructions=accepted_instructions or contract.done_message(
                artifacts=report.changed_files,
                test_command=report.verification.command if report.verification else task_pack.recommended_verification,
                test_summary=report.summary,
            ),
        )
        result_payload = {
            "status": "ready",
            "sent_at": iso_now(),
            "payload": payload,
            "work_report": work_report,
            "runtime_outcome": "ACCEPTED",
        }
        write_json(run_dir / "result.json", result_payload)
        signal_payload = build_child_result_signal(
            state=payload_state,
            from_agent=contract.role,
            to_agent=contract.expected_from,
            phase=contract.phase,
            signal="COMPLETE",
        )
        response = send_session_message(contract.session_key, json.dumps(signal_payload, separators=(",", ":")))
        result_payload["status"] = "sent"
        result_payload["response"] = response
        result_payload["signal"] = signal_payload
        write_json(run_dir / "result.json", result_payload)
        outcome = RuntimeOutcome(
            outcome="ACCEPTED",
            status="sent",
            signal="COMPLETE",
            code=None,
            message=report.summary,
            report_status=report.status,
            result_file=str(run_dir / "result.json"),
        )
        update_payload = {
            "status": "sent",
            "sent_at": result_payload["sent_at"],
            "final_decision": "DONE",
            "result_payload": payload,
            "last_send_response": response,
            "last_error": None,
            "blocked_at": None,
            "blocked_code": None,
            "repair_guard": None,
            "repair_feedback": None,
            "last_runtime_outcome": outcome.to_dict(),
            "outbound_work_result": work_result,
            "outbound_work_report": work_report,
            "outbound_project_workspace": project_workspace,
            "outbound_artifact_manifest": artifact_manifest,
        }
        if accepted_state_updates:
            update_payload.update(dict(accepted_state_updates))
        update_state(run_dir, **update_payload)
        append_log(run_dir, "outcome", f"runtime outcome ACCEPTED; sent DONE for {', '.join(report.changed_files)}")
        return outcome

    if report.status == "NEEDS_REVIEW":
        outcome = RuntimeOutcome(
            outcome="NEEDS_REVIEW",
            status="needs_review",
            signal=None,
            code=None,
            message=report.blocker["reason"] if report.blocker else report.summary,
            report_status=report.status,
            result_file=str(run_dir / "result.json"),
        )
        write_json(
            run_dir / "result.json",
            {
                "status": "needs_review",
                "recorded_at": iso_now(),
                "work_report": work_report,
                "runtime_outcome": outcome.to_dict(),
            },
        )
        update_state(
            run_dir,
            status="needs_review",
            final_decision="NEEDS_REVIEW",
            last_runtime_outcome=outcome.to_dict(),
            outbound_work_result=work_result,
            outbound_work_report=work_report,
            last_error=None,
        )
        append_log(run_dir, "outcome", "runtime outcome NEEDS_REVIEW")
        return outcome

    reason = report.blocker["reason"] if report.blocker else report.summary
    next_action = report.blocker.get("next_action") if report.blocker else None
    return send_blocked_from_state(
        contract,
        run_dir,
        {
            **dict(state),
            "outbound_work_result": work_result,
            "outbound_work_report": work_report,
        },
        code=report.status.lower(),
        reason=reason,
        next_action=next_action,
    )


def prepare_artifact_run(contract: ArtifactWorkerContract, envelope_raw: str) -> PreparedArtifactRun:
    envelope = parse_envelope(envelope_raw, contract)  # type: ignore[arg-type]
    resolved = resolve_project(envelope["project_id"])
    envelope, latest_handoff, task_id_repaired = reconcile_task_id_from_handoff_ledger(contract, envelope, resolved)
    run_dir = build_run_dir(contract, envelope["project_id"], envelope["task_id"])  # type: ignore[arg-type]
    run_dir.mkdir(parents=True, exist_ok=True)

    runtime_dir = workspace_root() / contract.role / "runtime" / run_dir.name
    draft_dir = runtime_dir / contract.draft_dir_name
    manifest_file = draft_dir / contract.manifest_file_name
    draft_write_root = ensure_directory_alias(
        draft_dir,
        workspace_root() / contract.role / "draft-aliases" / run_dir.name,
    )
    manifest_write_file = draft_write_root / contract.manifest_file_name
    handoff_file = run_dir / "handoff.json"
    context_file = run_dir / "context.md"
    envelope_file = run_dir / "envelope.json"
    draft_dir.mkdir(parents=True, exist_ok=True)
    write_json(envelope_file, envelope)

    state = {
        "role": contract.role,
        "phase": contract.phase,
        "run_id": run_dir.name,
        "status": "preparing",
        "prepared_at": iso_now(),
        "prepared_epoch": time.time(),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=RUN_DEADLINE_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_id": envelope["project_id"],
        "task_id": envelope["task_id"],
        "session_key": contract.session_key,
        "draft_dir": str(draft_dir),
        "manifest_file": str(manifest_file),
        "draft_write_root": str(draft_write_root),
        "manifest_write_file": str(manifest_write_file),
        "runtime_dir": str(runtime_dir),
        "context_file": str(context_file),
        "handoff_file": str(handoff_file),
        "last_error": None,
        "last_send_response": None,
        "result_payload": None,
        "validation_plan": [],
        "validation_runs": [],
        "validation_report": None,
        "final_decision": None,
        "latest_handoff_event": latest_handoff,
        "task_id_repaired_from_handoff": task_id_repaired,
        "inbound_receipt_acknowledged": False,
    }
    save_state(run_dir, state)
    append_log(run_dir, "prepare", f"artifact prepare started for {envelope['project_id']} {envelope['task_id']}")

    try:
        inbound_receipt_acknowledged = False
        if bool((latest_handoff or {}).get("ack_required")):
            ack_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "ack_handoff.sh"),
                    contract.role,
                    envelope["project_id"],
                    contract.phase,
                    "RECEIVED",
                    f"{contract.role} task handoff accepted.",
                ],
                timeout=120,
            )
            require_ok(ack_result, action="ack_handoff")
            inbound_receipt_acknowledged = True
        context_dir = run_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        inputs: list[dict[str, str]] = []
        for index, relative_path in enumerate(contract.render_read_paths(task_id=envelope["task_id"]), start=1):
            result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_read.sh"),
                    envelope["project_id"],
                    relative_path,
                    "--action",
                    f"{contract.role}_runtime_prepare_read",
                ],
                timeout=120,
            )
            stdout = require_ok(result, action=f"project_read {relative_path}")
            content = extract_content(stdout)
            audit_copy = context_dir / f"{index:02d}-{sanitize_name(relative_path)}"
            write_text(audit_copy, content if content.endswith("\n") else content + "\n")
            inputs.append({"path": relative_path, "content": content, "audit_copy": str(audit_copy)})

        required_output_paths: list[str] = []
        for item in inputs:
            for path in extract_required_outputs(item["content"]):
                normalized = normalize_artifact_path(path)
                if normalized not in required_output_paths:
                    required_output_paths.append(normalized)
        manifest_artifacts = required_output_paths or ["README.md"]
        suggested_test_command = (
            ["python3", "-m", "unittest", "tests/test_main.py"]
            if "tests/test_main.py" in manifest_artifacts
            else ["python3", "-m", "unittest"]
        )
        team_contracts: dict[str, str] = {}
        virtual_team_enabled = contract.role == "morpheus"
        if virtual_team_enabled:
            team_contracts = write_morpheus_virtual_team_contracts(
                run_dir=run_dir,
                context_file=context_file,
                draft_write_root=draft_write_root,
                manifest_write_file=manifest_write_file,
                required_outputs=manifest_artifacts,
                suggested_test_command=suggested_test_command,
            )

        write_text(
            context_file,
            build_context_markdown(
                envelope,
                inputs,
                source_max_chars=ARTIFACT_CONTEXT_SOURCE_MAX_CHARS,
                total_max_chars=ARTIFACT_CONTEXT_MAX_CHARS,
                include_full_input_index=True,
            ),
        )
        handoff_payload = {
            "run_dir": str(run_dir),
            "context_file": str(context_file),
            "runtime_dir": str(runtime_dir),
            "draft_dir": str(draft_dir),
            "manifest_file": str(manifest_file),
            "draft_write_root": str(draft_write_root),
            "manifest_write_file": str(manifest_write_file),
            "project_id": envelope["project_id"],
            "task_id": envelope["task_id"],
            "phase": contract.phase,
            "deadline_at": state["deadline_at"],
            "manifest_schema": {
                "artifacts": [{"path": path} for path in manifest_artifacts],
                "test_command": suggested_test_command,
            },
            "team": team_contracts,
            "next_command": _artifact_finish_command(contract, run_dir),
        }
        write_json(handoff_file, handoff_payload)
        update_state(
            run_dir,
            status="awaiting_artifacts",
            project_path=str(resolved["project_path"]),
            inbound_receipt_acknowledged=inbound_receipt_acknowledged,
            draft_write_root=str(draft_write_root),
            manifest_write_file=str(manifest_write_file),
            required_output_paths=required_output_paths,
            subteam_required=False,
            subteam={},
            virtual_team_enabled=virtual_team_enabled,
            team=team_contracts,
            team_test_command=suggested_test_command,
            inputs=[{"path": item["path"], "audit_copy": item["audit_copy"]} for item in inputs],
            last_error=None,
        )
        append_log(run_dir, "prepare", "artifact prepare completed")
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="prepare_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "prepare", f"artifact prepare failed: {exc}")
        raise

    print(f"RUN_DIR={run_dir}")
    print(f"HANDOFF_FILE={handoff_file}")
    print(f"CONTEXT_FILE={context_file}")
    print(f"RUNTIME_DIR={runtime_dir}")
    print(f"DRAFT_DIR={draft_dir}")
    print(f"MANIFEST_FILE={manifest_file}")
    print(f"DRAFT_WRITE_ROOT={draft_write_root}")
    print(f"MANIFEST_WRITE_FILE={manifest_write_file}")
    prepared_state = load_state(run_dir)
    if prepared_state.get("required_output_paths"):
        print("REQUIRED_OUTPUTS=" + ", ".join(prepared_state["required_output_paths"]))
    if prepared_state.get("virtual_team_enabled"):
        team = prepared_state.get("team") if isinstance(prepared_state.get("team"), dict) else {}
        print("TEAM_MODE=langgraph_virtual")
        for key in (
            "planner_evidence_file",
            "implementer_checklist_file",
            "tester_review_file",
        ):
            if team.get(key):
                print(f"{key.upper()}={team[key]}")
    block_command = (
        f"bash {live_bin_root() / (contract.role + '_run_task.sh')} block "
        f"\"{run_dir}\" --code \"<code>\" --reason \"<exact reason>\""
    )
    print(f"BLOCK_COMMAND={block_command}")
    print(f"NEXT_REQUIRED={_artifact_finish_command(contract, run_dir)}")
    print("ACTION_REQUIRED=Do not stop after prepare. Either write drafts plus manifest and run NEXT_REQUIRED, or run BLOCK_COMMAND.")
    print("WORK_ORDER_GUIDANCE=Use WORK_ORDER as a preview. Read CONTEXT_FILE only if required implementation details are missing. After any read, continue immediately to draft writes or BLOCK_COMMAND; never stop after reading.")
    print("REPORT_ACTION=After drafts and MANIFEST_WRITE_FILE exist, run NEXT_REQUIRED with RUN_DIR. Runtime validates through project_exec.")
    print("NEXT_ACTIONS_BEGIN")
    print("1. If required details are missing, read CONTEXT_FILE. If an excerpt there is truncated, read only the matching full input copy you need. After any read, continue to the next action; do not stop.")
    print("2. Write every REQUIRED_OUTPUTS path under DRAFT_WRITE_ROOT.")
    print("3. Write MANIFEST_WRITE_FILE with the artifact list and test_command.")
    print("4. Run NEXT_REQUIRED exactly after drafts and MANIFEST_WRITE_FILE exist; it must receive RUN_DIR, not DRAFT_WRITE_ROOT.")
    print("5. If NEXT_REQUIRED requests repair, fix drafts as directed and rerun the exact printed RUN_DIR command.")
    print("6. If you cannot continue from the available inputs, run BLOCK_COMMAND with an exact reason.")
    print("NEXT_ACTIONS_END")
    work_order_text, work_order_truncated = build_work_order_summary(inputs, max_chars=ARTIFACT_WORK_ORDER_MAX_CHARS)
    print(f"WORK_ORDER_TRUNCATED={'yes' if work_order_truncated else 'no'}")
    print(work_order_text)
    return PreparedArtifactRun(
        run_dir=run_dir,
        handoff_file=handoff_file,
        context_file=context_file,
        draft_dir=draft_dir,
        manifest_file=manifest_file,
    )


def build_artifact_task_packet(contract: ArtifactWorkerContract, run_dir: Path) -> str:
    state = load_state(run_dir)
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")
    required_outputs = [str(path) for path in state.get("required_output_paths", []) if str(path).strip()]
    test_command = [str(part) for part in state.get("team_test_command", []) if str(part).strip()]
    if not test_command:
        test_command = ["python3", "-m", "unittest"]
    report_destination = f"covenant://runtime/{contract.role}/{state['project_id']}/{state['task_id']}"
    context_text = Path(state["context_file"]).read_text(encoding="utf-8")
    context_preview, context_was_truncated = truncate_context_preview(
        context_text,
        max_chars=ARTIFACT_CONTEXT_MAX_CHARS,
        trailer="\n\n[task packet context truncated; use morpheus_run_task.sh read only for a targeted missing input]",
    )
    finish_command = _artifact_finish_command(contract, run_dir)
    complete_command = f"bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\""
    block_command = (
        f"bash {live_bin_root() / (contract.role + '_run_task.sh')} block "
        f"\"{run_dir}\" --code \"<code>\" --reason \"<exact reason>\""
    )
    manifest_example = {
        "artifacts": [{"path": path} for path in required_outputs],
        "test_command": test_command,
    }
    work_report_example = {
        "task_id": state["task_id"],
        "agent": contract.role,
        "status": "DONE | BLOCKED | FAILED | NEEDS_REVIEW",
        "summary": "Concise outcome summary.",
        "changed_files": required_outputs,
        "verification": {
            "task_id": state["task_id"],
            "agent": contract.role,
            "timestamp": "2026-06-02T00:00:00Z",
            "performed": True,
            "command": test_command,
            "status": "pass",
            "summary": "Validation passed.",
            "evidence_paths": required_outputs,
        },
        "repair_attempts": [],
        "next_owner": "niaobe",
        "blocker": None,
        "artifact_manifest": {
            "created": required_outputs,
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": required_outputs,
            "evidence_paths": required_outputs,
            "runtime_evidence_paths": [],
        },
    }
    if contract.role == "morpheus":
        lines = [
            "TASK_PACKET_BEGIN",
            f"RUNTIME_MODEL=AgentTaskRuntime",
            f"RUN_ID={state.get('run_id') or run_dir.name}",
            f"RUN_DIR={run_dir}",
            f"PROJECT_ID={state['project_id']}",
            f"TASK_ID={state['task_id']}",
            f"PHASE={state['phase']}",
            f"DRAFT_WRITE_ROOT={state['draft_write_root']}",
            f"MANIFEST_WRITE_FILE={state['manifest_write_file']}",
            f"REPORT_DESTINATION={report_destination}",
            "REQUIRED_OUTPUTS=" + ", ".join(required_outputs),
            "TEST_COMMAND=" + " ".join(test_command),
            "RUNTIME_VALIDATION=REPORT_COMMAND imports drafts and runs project_exec; do not run raw validation from DRAFT_WRITE_ROOT.",
            "ACTION_CATALOG_BEGIN",
            "write_draft_file: write each required project-relative artifact path under DRAFT_WRITE_ROOT.",
            "write_manifest: write JSON to MANIFEST_WRITE_FILE with artifacts and test_command.",
            "python_claw: optional diagnostics only; never DONE evidence.",
            "morpheus_report: run REPORT_COMMAND exactly with RUN_DIR after drafts and manifest exist.",
            "morpheus_block: run BLOCK_COMMAND exactly with RUN_DIR plus code and reason when implementation is blocked.",
            "ACTION_CATALOG_END",
            f"REPORT_COMMAND={finish_command}",
            f"BLOCK_COMMAND={block_command}",
            "PATH_INVARIANT=REPORT_COMMAND and BLOCK_COMMAND take RUN_DIR only; never pass DRAFT_WRITE_ROOT or MANIFEST_WRITE_FILE.",
            f"CONTEXT_TRUNCATED={'yes' if context_was_truncated else 'no'}",
            "",
            "TASK_CONTEXT_BEGIN",
            context_preview.rstrip(),
            "TASK_CONTEXT_END",
            "",
            "MANIFEST_SCHEMA_BEGIN",
            json.dumps(manifest_example, indent=2, sort_keys=True),
            "MANIFEST_SCHEMA_END",
            "",
            "WORK_REPORT_SCHEMA_BEGIN",
            json.dumps(work_report_example, indent=2, sort_keys=True),
            "WORK_REPORT_SCHEMA_END",
            "",
            "REQUIRED_AGENT_WORK_BEGIN",
            "1. Think through Planner -> Implementer -> Tester in this main session.",
            "2. Write every REQUIRED_OUTPUTS path under DRAFT_WRITE_ROOT.",
            "3. Write MANIFEST_WRITE_FILE with artifacts and test_command. Do not fabricate validation evidence; runtime records it.",
            "4. Run REPORT_COMMAND exactly with RUN_DIR. Do not run raw validation from DRAFT_WRITE_ROOT.",
            "5. Treat WORKER_RUNTIME_REPAIR_REQUIRED or WORKER_RUNTIME_FAILED output as not complete; repair/block or rerun only the exact printed RUN_DIR action.",
            "6. If blocked by missing or invalid task inputs, run BLOCK_COMMAND with RUN_DIR and an exact reason.",
            "7. REPORT_SUCCESS_ACTION=Only reply success after REPORT_COMMAND reports RESULT_FILE or ALREADY_SENT.",
            "REQUIRED_AGENT_WORK_END",
            "TASK_PACKET_END",
        ]
    else:
        lines = [
            "TASK_PACKET_BEGIN",
            f"RUNTIME_MODEL=AgentTaskRuntime",
            f"RUN_ID={state.get('run_id') or run_dir.name}",
            f"RUN_DIR={run_dir}",
            f"PROJECT_ID={state['project_id']}",
            f"TASK_ID={state['task_id']}",
            f"PHASE={state['phase']}",
            f"DRAFT_WRITE_ROOT={state['draft_write_root']}",
            f"MANIFEST_WRITE_FILE={state['manifest_write_file']}",
            "REQUIRED_OUTPUTS=" + ", ".join(required_outputs),
            "TEST_COMMAND=" + " ".join(test_command),
            "RUNTIME_VALIDATION=COMPLETE_COMMAND imports drafts and runs project_exec; do not run raw validation from DRAFT_WRITE_ROOT.",
            f"COMPLETE_COMMAND={complete_command}",
            f"BLOCK_COMMAND={block_command}",
            "PATH_INVARIANT=COMPLETE_COMMAND and BLOCK_COMMAND take RUN_DIR only; never pass DRAFT_WRITE_ROOT or MANIFEST_WRITE_FILE.",
            f"CONTEXT_TRUNCATED={'yes' if context_was_truncated else 'no'}",
            "",
            "TASK_CONTEXT_BEGIN",
            context_preview.rstrip(),
            "TASK_CONTEXT_END",
            "",
            "MANIFEST_SCHEMA_BEGIN",
            json.dumps(manifest_example, indent=2, sort_keys=True),
            "MANIFEST_SCHEMA_END",
            "",
            "REQUIRED_AGENT_WORK_BEGIN",
            "1. Think through Planner -> Implementer -> Tester in this main session.",
            "2. Write every REQUIRED_OUTPUTS path under DRAFT_WRITE_ROOT.",
            "3. Write MANIFEST_WRITE_FILE with artifacts and test_command. Do not fabricate validation evidence; runtime records it.",
            "4. Run COMPLETE_COMMAND exactly with RUN_DIR. Do not run raw validation from DRAFT_WRITE_ROOT.",
            "5. Treat WORKER_RUNTIME_REPAIR_REQUIRED or WORKER_RUNTIME_FAILED output as not complete; repair/block or rerun only the exact printed RUN_DIR action.",
            "6. If blocked by missing or invalid task inputs, run BLOCK_COMMAND with RUN_DIR and an exact reason.",
            "7. REPORT_SUCCESS_ACTION=Only reply success after COMPLETE_COMMAND reports RESULT_FILE or ALREADY_SENT.",
            "REQUIRED_AGENT_WORK_END",
            "TASK_PACKET_END",
        ]
    return "\n".join(lines).rstrip() + "\n"


def dispatch_artifact_task(contract: ArtifactWorkerContract, envelope_raw: str) -> dict[str, Any]:
    buffered_output = io.StringIO()
    with contextlib.redirect_stdout(buffered_output):
        prepared = prepare_artifact_run(contract, envelope_raw)
    prepared_state = load_state(prepared.run_dir)
    packet = build_artifact_task_packet(contract, prepared.run_dir)
    packet_file = prepared.run_dir / "task_packet.md"
    write_text(packet_file, packet)
    state = update_state(
        prepared.run_dir,
        status="dispatched",
        task_packet_file=str(packet_file),
        report_destination=f"covenant://runtime/{contract.role}/{prepared_state['project_id']}/{prepared_state['task_id']}",
        dispatch_prepare_output=buffered_output.getvalue(),
        dispatched_at=iso_now(),
    )
    dispatch_session = artifact_dispatch_session(contract, state)
    response = send_session_message(dispatch_session.key, packet)
    response_ids = parse_send_response_ids(response)
    write_json(
        prepared.run_dir / "dispatch.json",
        {
            "status": "sent",
            "sent_at": iso_now(),
            "session_key": dispatch_session.key,
            "session_id": dispatch_session.session_id,
            "session_file": dispatch_session.session_file,
            "task_scoped_session": dispatch_session.task_scoped,
            "session_created": dispatch_session.created,
            "response": response,
            "response_ids": response_ids,
            "task_packet_file": str(packet_file),
        },
    )
    return update_state(
        prepared.run_dir,
        last_send_response=response,
        dispatch_response=response,
        dispatch_session_key=dispatch_session.key,
        dispatch_session_id=dispatch_session.session_id,
        dispatch_session_file=dispatch_session.session_file,
        dispatch_task_scoped_session=dispatch_session.task_scoped,
        dispatch_session_created=dispatch_session.created,
        dispatch_response_ids=response_ids,
        status="awaiting_artifacts",
    )


def missing_artifact_work(state: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    manifest_file = Path(str(state.get("manifest_file", "")))
    if not manifest_file.is_file():
        missing.append("manifest.json")
    draft_dir = Path(str(state.get("draft_dir", "")))
    for artifact in state.get("required_output_paths", []):
        path = str(artifact).strip()
        if path and not (draft_dir / path).is_file():
            missing.append(path)
    return missing


def resume_artifact_task(contract: ArtifactWorkerContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")
    if str(state.get("status", "")).strip().lower() in {"sent", "blocked"}:
        raise WorkerRuntimeError(f"run already terminal: {state.get('status')}", code="terminal_run")

    attempts = int(state.get("recovery_attempts", 0)) + 1
    missing = missing_artifact_work(state)
    base_packet = build_artifact_task_packet(contract, run_dir)
    missing_label = "validation_or_reporting" if contract.role == "morpheus" else "validation_or_completion"
    continuation = "\n".join(
        [
            "TASK_CONTINUATION_BEGIN",
            f"RUN_ID={state.get('run_id') or run_dir.name}",
            "REASON=incomplete_runtime_task",
            "MISSING_WORK=" + (", ".join(missing) if missing else missing_label),
            "Continue the same task now. Do not restart with a new run. Do not call prepare.",
            f"If artifacts are missing, write them under DRAFT_WRITE_ROOT. If only reporting is missing, run {_artifact_finish_command(contract, run_dir)} exactly with RUN_DIR.",
            "TASK_CONTINUATION_END",
            "",
            base_packet.rstrip(),
        ]
    ) + "\n"
    continuation_file = run_dir / f"continuation-{attempts:02d}.md"
    write_text(continuation_file, continuation)
    if contract.role == "morpheus":
        stored_session_key = str(state.get("dispatch_session_key") or "").strip()
        expected_task_key = task_scoped_session_key(contract.expected_to, str(state.get("run_id") or run_dir.name))
        if not stored_session_key or stored_session_key == expected_task_key:
            dispatch_session = ensure_registered_task_session(contract.expected_to, str(state.get("run_id") or run_dir.name))
            session_key = dispatch_session.key
        else:
            session_key = stored_session_key
            dispatch_session = RegisteredSession(
                key=session_key,
                session_id=str(state.get("dispatch_session_id", "")),
                session_file=str(state.get("dispatch_session_file", "")),
                created=False,
                task_scoped=session_key != f"agent:{contract.expected_to}:main",
            )
    else:
        session_key = str(state.get("dispatch_session_key") or f"agent:{contract.expected_to}:main")
        dispatch_session = RegisteredSession(key=session_key, session_id="", session_file="", created=False, task_scoped=False)
    response = send_session_message(session_key, continuation)
    response_ids = parse_send_response_ids(response)
    append_log(run_dir, "resume", f"sent continuation attempt {attempts}; missing={', '.join(missing) if missing else 'none'}")
    return update_state(
        run_dir,
        status="awaiting_artifacts",
        recovery_attempts=attempts,
        last_recovery_at=iso_now(),
        last_recovery_missing=missing,
        last_recovery_file=str(continuation_file),
        last_send_response=response,
        last_recovery_response_ids=response_ids,
        dispatch_session_key=dispatch_session.key,
        dispatch_session_id=dispatch_session.session_id,
        dispatch_session_file=dispatch_session.session_file,
        dispatch_task_scoped_session=dispatch_session.task_scoped,
    )


def advance_artifact_task(contract: ArtifactWorkerContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        if not isinstance(state.get("last_runtime_outcome"), dict):
            outcome = RuntimeOutcome(
                outcome="ACCEPTED",
                status="sent",
                signal="COMPLETE",
                code=None,
                message="run already sent",
                report_status="DONE",
                result_file=str(run_dir / "result.json"),
            )
            state = update_state(run_dir, last_runtime_outcome=outcome.to_dict())
        return state
    if status == "blocked":
        if not isinstance(state.get("last_runtime_outcome"), dict):
            outcome = RuntimeOutcome(
                outcome="BLOCKED",
                status="blocked",
                signal="BLOCKED",
                code=str(state.get("blocked_code") or "blocked"),
                message=str((state.get("last_error") or {}).get("message") if isinstance(state.get("last_error"), Mapping) else "run already blocked"),
                report_status="BLOCKED",
                result_file=str(run_dir / "result.json"),
            )
            state = update_state(run_dir, last_runtime_outcome=outcome.to_dict())
        return state
    missing = missing_artifact_work(state)
    if status == "repair_needed" or missing:
        if missing:
            outcome = record_artifact_repair_required(
                contract,
                run_dir,
                state,
                code="missing_artifact_work",
                reason="missing required runtime artifact(s): " + ", ".join(missing),
                next_action="Continue the same run, write the missing drafts or manifest, then run completion.",
            )
            if outcome.outcome == "BLOCKED":
                return load_state(run_dir)
        return resume_artifact_task(contract, run_dir)
    if contract.role == "morpheus":
        from agent_runner import complete_artifact_run_graph

        return complete_artifact_run_graph(contract, run_dir)
    return complete_artifact_run(contract, run_dir)


def prepare_planning_run(contract: PlanningProjectContract, envelope_raw: str) -> PreparedArtifactRun:
    envelope = parse_planning_envelope(envelope_raw, contract)
    run_dir = build_phase_run_dir(contract.role, envelope["project_id"], "planning")
    run_dir.mkdir(parents=True, exist_ok=True)

    draft_dir = run_dir / contract.draft_dir_name
    manifest_file = draft_dir / contract.manifest_file_name
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_write_root = draft_dir
    manifest_write_file = manifest_file
    handoff_file = run_dir / "handoff.json"
    context_file = run_dir / "context.md"
    envelope_file = run_dir / "envelope.json"
    write_json(envelope_file, envelope)

    state = {
        "role": contract.role,
        "phase": contract.phase,
        "run_id": run_dir.name,
        "status": "preparing",
        "prepared_at": iso_now(),
        "prepared_epoch": time.time(),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=RUN_DEADLINE_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_id": envelope["project_id"],
        "blocked_session_key": contract.blocked_session_key,
        "success_session_key": contract.success_session_key,
        "draft_dir": str(draft_dir),
        "manifest_file": str(manifest_file),
        "draft_write_root": str(draft_write_root),
        "manifest_write_file": str(manifest_write_file),
        "context_file": str(context_file),
        "handoff_file": str(handoff_file),
        "last_error": None,
        "last_send_response": None,
        "result_payload": None,
        "project_state_written": False,
    }
    save_state(run_dir, state)
    append_log(run_dir, "prepare", f"planning prepare started for {envelope['project_id']}")

    try:
        resolved = resolve_project(envelope["project_id"])
        ack_result = run_command(
            [
                "bash",
                str(live_bin_root() / "ack_handoff.sh"),
                contract.role,
                envelope["project_id"],
                contract.phase,
                "RECEIVED",
                "Neo project handoff accepted.",
            ],
            timeout=120,
        )
        require_ok(ack_result, action="ack_handoff")
        context_dir = run_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        inputs: list[dict[str, str]] = []
        for index, relative_path in enumerate(contract.required_read_paths, start=1):
            result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_read.sh"),
                    envelope["project_id"],
                    relative_path,
                    "--action",
                    f"{contract.role}_runtime_prepare_read",
                ],
                timeout=120,
            )
            stdout = require_ok(result, action=f"project_read {relative_path}")
            content = extract_content(stdout)
            audit_copy = context_dir / f"{index:02d}-{sanitize_name(relative_path)}"
            write_text(audit_copy, content if content.endswith("\n") else content + "\n")
            inputs.append({"path": relative_path, "content": content, "audit_copy": str(audit_copy)})

        write_text(context_file, build_context_markdown({**envelope, "task_id": "PLANNING"}, inputs))
        required_artifact_paths = [
            "management/PLAN.md",
            "management/BACKLOG.md",
            "management/tasks/T001.md",
            "CURRENT_TASK.md",
        ]
        manifest_schema = {
            "artifacts": [{"path": path} for path in required_artifact_paths],
            "active_task": "T001",
        }
        next_required = f"bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\""
        block_command = (
            f"bash {live_bin_root() / 'smith_plan_project.sh'} block \"{run_dir}\" "
            "--code ambiguous_spec "
            '--reason "<exact planning blocker>"'
        )
        action_required = (
            "Do not stop after prepare. Either write all required planning drafts plus manifest and run NEXT_REQUIRED, "
            "or run BLOCK_COMMAND with an exact reason."
        )
        next_actions = (
            "1. Read WORK_ORDER and CONTEXT_FILE; do not stop after reading.",
            "2. Write management/PLAN.md under DRAFT_WRITE_ROOT.",
            "3. Write management/BACKLOG.md under DRAFT_WRITE_ROOT.",
            "4. Write management/tasks/T001.md and any additional management/tasks/T###.md drafts needed by the plan.",
            "5. Write CURRENT_TASK.md pointing to the first ready task.",
            "6. Write MANIFEST_WRITE_FILE matching MANIFEST_SCHEMA.",
            "7. Run NEXT_REQUIRED only after all required drafts and MANIFEST_WRITE_FILE exist.",
            "8. If you cannot produce a valid sequential plan from the available inputs, run BLOCK_COMMAND with an exact reason.",
        )
        handoff_payload = {
            "run_dir": str(run_dir),
            "context_file": str(context_file),
            "draft_dir": str(draft_dir),
            "manifest_file": str(manifest_file),
            "draft_write_root": str(draft_write_root),
            "manifest_write_file": str(manifest_write_file),
            "project_id": envelope["project_id"],
            "phase": contract.phase,
            "deadline_at": state["deadline_at"],
            "required_artifact_paths": required_artifact_paths,
            "manifest_schema": manifest_schema,
            "next_command": next_required,
            "next_required": next_required,
            "block_command": block_command,
            "action_required": action_required,
            "next_actions": list(next_actions),
        }
        write_json(handoff_file, handoff_payload)
        update_state(
            run_dir,
            status="awaiting_artifacts",
            project_path=str(resolved["project_path"]),
            inbound_receipt_acknowledged=True,
            draft_write_root=str(draft_write_root),
            manifest_write_file=str(manifest_write_file),
            required_artifact_paths=required_artifact_paths,
            manifest_schema=manifest_schema,
            next_required=next_required,
            block_command=block_command,
            action_required=action_required,
            next_actions=list(next_actions),
            inputs=[{"path": item["path"], "audit_copy": item["audit_copy"]} for item in inputs],
            last_error=None,
        )
        append_log(run_dir, "prepare", "planning prepare completed")
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="prepare_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "prepare", f"planning prepare failed: {exc}")
        raise

    print(f"RUN_DIR={run_dir}")
    print(f"HANDOFF_FILE={handoff_file}")
    print(f"CONTEXT_FILE={context_file}")
    print(f"DRAFT_DIR={draft_dir}")
    print(f"MANIFEST_FILE={manifest_file}")
    print(f"DRAFT_WRITE_ROOT={draft_write_root}")
    print(f"MANIFEST_WRITE_FILE={manifest_write_file}")
    print(f"REQUIRED_ARTIFACT_PATHS={','.join(required_artifact_paths)}")
    print("MANIFEST_SCHEMA_BEGIN")
    print(json.dumps(manifest_schema, indent=2, sort_keys=True))
    print("MANIFEST_SCHEMA_END")
    print(f"BLOCK_COMMAND={block_command}")
    print(f"NEXT_REQUIRED={next_required}")
    print(f"ACTION_REQUIRED={action_required}")
    print("NEXT_ACTIONS_BEGIN")
    for action in next_actions:
        print(action)
    print("NEXT_ACTIONS_END")
    work_order_text, _ = build_work_order_summary(inputs)
    print(work_order_text)
    return PreparedArtifactRun(
        run_dir=run_dir,
        handoff_file=handoff_file,
        context_file=context_file,
        draft_dir=draft_dir,
        manifest_file=manifest_file,
    )


def normalize_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerRuntimeError("artifact path must be a non-empty string", code="verification_failed")
    path = Path(value.strip())
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorkerRuntimeError(f"invalid artifact path: {value}", code="verification_failed")
    return path.as_posix()


def load_artifact_manifest(state: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any] | None]:
    manifest_file = Path(state["manifest_file"])
    if not manifest_file.exists() or not manifest_file.is_file():
        raise WorkerRuntimeError(f"expected manifest file missing: {manifest_file}", code="missing_draft")
    if manifest_file.stat().st_mtime <= float(state.get("prepared_epoch", 0.0)):
        raise WorkerRuntimeError(f"manifest file was not updated after prepare: {manifest_file}", code="missing_draft")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"manifest JSON is invalid: {exc}", code="verification_failed") from exc
    if not isinstance(manifest, dict):
        raise WorkerRuntimeError("manifest must be a JSON object", code="verification_failed")

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise WorkerRuntimeError("manifest.artifacts must be a non-empty list", code="verification_failed")
    artifacts: list[str] = []
    for item in raw_artifacts:
        path_value = item.get("path") if isinstance(item, dict) else item
        artifact = normalize_artifact_path(path_value)
        if artifact not in artifacts:
            artifacts.append(artifact)
    if not artifacts:
        raise WorkerRuntimeError("manifest has no valid artifacts", code="verification_failed")
    required_outputs = [
        normalize_artifact_path(path)
        for path in state.get("required_output_paths", [])
        if isinstance(path, str) and path.strip()
    ]
    missing_outputs = [path for path in required_outputs if path not in artifacts]
    if missing_outputs:
        raise WorkerRuntimeError(
            "manifest is missing required project output(s): " + ", ".join(missing_outputs),
            code="verification_failed",
        )

    raw_command = manifest.get("test_command")
    if not isinstance(raw_command, list) or not all(isinstance(part, str) and part.strip() for part in raw_command):
        raise WorkerRuntimeError("manifest.test_command must be a non-empty string array", code="verification_failed")
    test_command = [part.strip() for part in raw_command]
    validation_report = None
    raw_report = manifest.get("validation_report")
    if raw_report is not None:
        if not isinstance(raw_report, dict):
            raise WorkerRuntimeError("manifest.validation_report must be an object when provided", code="verification_failed")
        raw_report_command = raw_report.get("command")
        if not isinstance(raw_report_command, list) or not all(isinstance(part, str) and part.strip() for part in raw_report_command):
            raise WorkerRuntimeError("manifest.validation_report.command must be a non-empty string array", code="verification_failed")
        report_command = [part.strip() for part in raw_report_command]
        if report_command != test_command:
            raise WorkerRuntimeError(
                "manifest.validation_report.command must match manifest.test_command",
                code="verification_failed",
            )
        report_status = str(raw_report.get("status", "")).strip().lower()
        if report_status not in {"pass", "passed"}:
            raise WorkerRuntimeError("manifest.validation_report.status must be pass when provided", code="verification_failed")
        report_summary = str(raw_report.get("summary", "")).strip()
        if not report_summary:
            raise WorkerRuntimeError("manifest.validation_report.summary must be non-empty when provided", code="verification_failed")
        validation_report = {
            "command": report_command,
            "status": report_status,
            "summary": report_summary,
        }
    return artifacts, test_command, validation_report


def ensure_artifact_drafts(state: dict[str, Any], artifacts: list[str]) -> list[tuple[str, Path]]:
    draft_dir = Path(state["draft_dir"])
    prepared_epoch = float(state.get("prepared_epoch", 0.0))
    pairs: list[tuple[str, Path]] = []
    for artifact in artifacts:
        draft_file = draft_dir / artifact
        try:
            draft_file.relative_to(draft_dir)
        except ValueError as exc:
            raise WorkerRuntimeError(f"draft escapes draft_dir: {artifact}", code="verification_failed") from exc
        if not draft_file.exists() or not draft_file.is_file():
            raise WorkerRuntimeError(f"expected artifact draft missing: {draft_file}", code="missing_draft")
        if draft_file.stat().st_mtime <= prepared_epoch:
            raise WorkerRuntimeError(f"artifact draft was not updated after prepare: {draft_file}", code="missing_draft")
        pairs.append((artifact, draft_file))
    return pairs


def normalize_task_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerRuntimeError("task id must be a non-empty string", code="verification_failed")
    task_id = value.strip().upper()
    if not re.fullmatch(r"T\d{3}", task_id):
        raise WorkerRuntimeError(f"invalid task id: {value}", code="verification_failed")
    return task_id


def extract_handoff_envelope(output: str) -> str:
    for raw in output.splitlines():
        if raw.startswith("ENVELOPE: "):
            return raw.split("ENVELOPE: ", 1)[1].strip()
    raise WorkerRuntimeError("handoff helper did not produce ENVELOPE", code="helper_failed")


def load_planning_manifest(
    contract: PlanningProjectContract,
    state: dict[str, Any],
) -> tuple[list[str], str, list[str]]:
    manifest_file = Path(state["manifest_file"])
    if not manifest_file.exists() or not manifest_file.is_file():
        raise WorkerRuntimeError(f"expected manifest file missing: {manifest_file}", code="missing_draft")
    if manifest_file.stat().st_mtime <= float(state.get("prepared_epoch", 0.0)):
        raise WorkerRuntimeError(f"manifest file was not updated after prepare: {manifest_file}", code="missing_draft")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"manifest JSON is invalid: {exc}", code="verification_failed") from exc
    if not isinstance(manifest, dict):
        raise WorkerRuntimeError("manifest must be a JSON object", code="verification_failed")

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise WorkerRuntimeError("manifest.artifacts must be a non-empty list", code="verification_failed")

    artifacts: list[str] = []
    task_ids: list[str] = []
    for item in raw_artifacts:
        path_value = item.get("path") if isinstance(item, dict) else item
        artifact = normalize_artifact_path(path_value)
        if not any(re.fullmatch(pattern, artifact) for pattern in contract.allowed_artifact_patterns):
            raise WorkerRuntimeError(f"manifest contains non-planning artifact path: {artifact}", code="verification_failed")
        if artifact not in artifacts:
            artifacts.append(artifact)
        match = re.fullmatch(r"management/tasks/(T\d{3})\.md", artifact)
        if match:
            task_id = match.group(1)
            if task_id not in task_ids:
                task_ids.append(task_id)

    required = {"management/PLAN.md", "management/BACKLOG.md", "CURRENT_TASK.md"}
    missing_required = sorted(path for path in required if path not in artifacts)
    if missing_required:
        raise WorkerRuntimeError(
            "manifest is missing required planning artifact(s): " + ", ".join(missing_required),
            code="verification_failed",
        )
    if not task_ids:
        raise WorkerRuntimeError("manifest must include at least one task artifact", code="verification_failed")

    active_task = normalize_task_id(manifest.get("active_task"))
    if active_task not in task_ids:
        raise WorkerRuntimeError(f"manifest.active_task {active_task} is not declared in artifacts", code="verification_failed")
    if active_task != task_ids[0]:
        raise WorkerRuntimeError(
            f"manifest.active_task must be the first planned task; expected {task_ids[0]}, found {active_task}",
            code="verification_failed",
        )
    return artifacts, active_task, task_ids


def verify_planning_draft_contents(
    contract: PlanningProjectContract,
    draft_dir: Path,
    *,
    active_task: str,
    task_ids: list[str],
) -> None:
    def read_required(relative_path: str) -> str:
        path = draft_dir / relative_path
        if not path.exists() or not path.is_file():
            raise WorkerRuntimeError(f"expected planning draft missing: {path}", code="missing_draft")
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise WorkerRuntimeError(f"planning draft is empty: {path}", code="verification_failed")
        return text

    plan_text = read_required("management/PLAN.md")
    missing_plan = [pattern for pattern in contract.plan_patterns if re.search(pattern, plan_text, flags=re.MULTILINE) is None]
    if missing_plan:
        raise WorkerRuntimeError(
            "PLAN draft is missing required content: " + ", ".join(missing_plan),
            code="verification_failed",
        )

    backlog_text = read_required("management/BACKLOG.md")
    missing_backlog_ids = [task_id for task_id in task_ids if task_id not in backlog_text]
    if missing_backlog_ids:
        raise WorkerRuntimeError(
            "BACKLOG draft is missing planned task id(s): " + ", ".join(missing_backlog_ids),
            code="verification_failed",
        )

    current_task_text = read_required("CURRENT_TASK.md")
    if active_task not in current_task_text:
        raise WorkerRuntimeError(
            f"CURRENT_TASK draft does not reference active_task {active_task}",
            code="verification_failed",
        )

    for task_id in task_ids:
        task_text = read_required(f"management/tasks/{task_id}.md")
        if task_id not in task_text:
            raise WorkerRuntimeError(
                f"task draft management/tasks/{task_id}.md does not reference {task_id}",
                code="verification_failed",
            )


def read_prepared_project_text(state: dict[str, Any]) -> str:
    for item in state.get("inputs", []):
        if isinstance(item, dict) and item.get("path") == "PROJECT.md":
            audit_copy = Path(str(item.get("audit_copy", "")))
            if audit_copy.exists() and audit_copy.is_file():
                return audit_copy.read_text(encoding="utf-8")
    raise WorkerRuntimeError("prepared PROJECT.md audit copy is missing", code="missing_input")


def extract_required_plan_block(project_text: str) -> str:
    match = re.search(
        r"^## Required Plan\s*\n(?P<plan>.*?)(?=^## Required Outputs\s*$|^## Determinism Rules\s*$|\Z)",
        project_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise WorkerRuntimeError("PROJECT.md does not contain a deterministic ## Required Plan block", code="missing_input")
    plan = match.group("plan").strip()
    if "## Overview" not in plan or "## Phases" not in plan:
        raise WorkerRuntimeError("Required Plan block is missing ## Overview or ## Phases", code="verification_failed")
    return plan


def extract_required_outputs(project_text: str) -> list[str]:
    match = re.search(
        r"^## Required Outputs\s*\n(?P<outputs>.*?)(?=^##\s+|\Z)",
        project_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    outputs: list[str] = []
    for raw in match.group("outputs").splitlines():
        line = raw.strip()
        if line.startswith("- "):
            outputs.append(line[2:].strip(" `"))
    return outputs


def extract_required_tasks(required_plan: str) -> list[tuple[str, str, list[str]]]:
    tasks: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    for raw in required_plan.splitlines():
        line = raw.rstrip()
        match = re.match(r"\s*\d+\.\s+\*\*(T\d{3}):\s*(.+?)\*\*\s*$", line)
        if match:
            if current:
                tasks.append(current)
            current = (match.group(1), match.group(2).strip(), [])
            continue
        if current and re.match(r"\s+-\s+", line):
            current[2].append(re.sub(r"^\s+-\s+", "", line).strip())
    if current:
        tasks.append(current)
    if not tasks:
        raise WorkerRuntimeError("Required Plan block does not declare any T### tasks", code="verification_failed")
    return tasks


def write_required_plan_drafts(contract: PlanningProjectContract, run_dir: Path) -> None:
    state = load_state(run_dir)
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")
    project_text = read_prepared_project_text(state)
    required_plan = extract_required_plan_block(project_text)
    required_outputs = extract_required_outputs(project_text)
    tasks = extract_required_tasks(required_plan)

    draft_dir = Path(state["draft_dir"])
    task_ids = [task_id for task_id, _, _ in tasks]
    active_task = task_ids[0]

    plan_text = "# Plan\n\n" + required_plan.rstrip() + "\n"
    backlog_lines = ["# Backlog", ""]
    for index, (task_id, title, _) in enumerate(tasks):
        status = "READY" if index == 0 else "PENDING"
        backlog_lines.append(f"- [{status}] {task_id}: {title}")
    backlog_text = "\n".join(backlog_lines) + "\n"
    current_task_text = "\n".join(
        [
            f"# Current Task: {active_task}",
            "",
            f"## Task ID: {active_task}",
            f"## Task Name: {tasks[0][1]}",
            "",
            "## Instructions",
            f"Read `management/tasks/{active_task}.md` and complete this task only.",
            "",
        ]
    )

    drafts: dict[str, str] = {
        "management/PLAN.md": plan_text,
        "management/BACKLOG.md": backlog_text,
        "CURRENT_TASK.md": current_task_text,
    }
    outputs_text = "\n".join(f"- {path}" for path in required_outputs) if required_outputs else "- See PROJECT.md"
    for task_id, title, bullets in tasks:
        bullet_text = "\n".join(f"- {item}" for item in bullets) if bullets else "- Complete the task scope from the required plan."
        drafts[f"management/tasks/{task_id}.md"] = "\n".join(
            [
                f"# Task {task_id}: {title}",
                "",
                "## Goal",
                f"Complete `{task_id}: {title}` from the required project plan.",
                "",
                "## Scope",
                bullet_text,
                "",
                "## Required Outputs",
                outputs_text,
                "",
                "## Acceptance Criteria",
                f"- {task_id} is completed without changing the required task order.",
                "- Required project outputs remain stable.",
                "",
            ]
        )

    for relative_path, content in drafts.items():
        write_text(draft_dir / relative_path, content if content.endswith("\n") else content + "\n")

    manifest = {
        "artifacts": [{"path": path} for path in drafts],
        "active_task": active_task,
    }
    write_json(Path(state["manifest_file"]), manifest)
    update_state(
        run_dir,
        status="autoplan_drafted",
        active_task=active_task,
        task_ids=task_ids,
        artifacts=list(drafts),
    )


def autoplan_required_planning_project(contract: PlanningProjectContract, envelope_raw: str) -> dict[str, Any]:
    buffered_output = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffered_output):
            prepared = prepare_planning_run(contract, envelope_raw)
            write_required_plan_drafts(contract, prepared.run_dir)
            state = complete_planning_run(contract, prepared.run_dir)
    except WorkerRuntimeError:
        sys.stdout.write(buffered_output.getvalue())
        raise
    print(f"RESULT_FILE={prepared.run_dir / 'result.json'}")
    return state


def should_autoplan_planning_envelope(contract: PlanningProjectContract, envelope_raw: str) -> bool:
    if contract.role != "smith":
        return False
    try:
        payload = json.loads(envelope_raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    instructions = str(payload.get("instructions", "")).lower()
    return "deterministic" in instructions and "4-task" in instructions


def summarize_test_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "project_exec completed with no output"
    for line in reversed(lines):
        if line.startswith("OUTCOME_JSON:"):
            continue
        return line[:240]
    return "project_exec completed"


def send_blocked_from_state(
    contract: ArtifactWorkerContract,
    run_dir: Path,
    state: dict[str, Any],
    *,
    code: str,
    reason: str,
    next_action: str | None = None,
) -> RuntimeOutcome:
    blocked_state = dict(state)
    if not isinstance(blocked_state.get("outbound_work_report"), dict) or not isinstance(blocked_state.get("outbound_work_result"), dict):
        try:
            task_pack = validate_task_pack(_artifact_task_pack_payload(contract, blocked_state))
            blocked_report = validate_work_report(
                _artifact_blocked_report_payload(
                    contract,
                    blocked_state,
                    code=code,
                    reason=reason,
                    next_action=next_action,
                ),
                task_pack=task_pack,
            )
        except ContractValidationError as exc:
            raise WorkerRuntimeError(f"blocked outcome contract invalid: {exc}", code="work_report_invalid") from exc
        blocked_state["outbound_work_report"] = blocked_report.to_dict()
        blocked_state["outbound_work_result"] = _work_result_from_report(contract, blocked_state, blocked_report)
    payload = build_artifact_result_payload(
        contract,
        blocked_state,
        instructions=contract.blocked_message(code=code, reason=reason),
    )
    result_payload = {
        "status": "ready",
        "blocked_at": iso_now(),
        "code": code,
        "payload": payload,
        "work_report": blocked_state.get("outbound_work_report"),
        "runtime_outcome": "BLOCKED",
    }
    write_json(run_dir / "result.json", result_payload)
    signal_payload = build_child_result_signal(
        state=blocked_state,
        from_agent=contract.role,
        to_agent=contract.expected_from,
        phase=contract.phase,
        signal="BLOCKED",
        reason=reason,
    )
    response = send_session_message(contract.session_key, json.dumps(signal_payload, separators=(",", ":")))
    result_payload["status"] = "blocked"
    result_payload["response"] = response
    result_payload["signal"] = signal_payload
    write_json(run_dir / "result.json", result_payload)
    outcome = RuntimeOutcome(
        outcome="BLOCKED",
        status="blocked",
        signal="BLOCKED",
        code=code,
        message=reason,
        report_status="BLOCKED",
        result_file=str(run_dir / "result.json"),
    )
    update_state(
        run_dir,
        status="blocked",
        blocked_at=result_payload["blocked_at"],
        blocked_code=code,
        result_payload=payload,
        last_send_response=response,
        last_error={"code": code, "message": reason},
        final_decision="BLOCKED",
        last_runtime_outcome=outcome.to_dict(),
        outbound_work_result=blocked_state.get("outbound_work_result"),
        outbound_work_report=blocked_state.get("outbound_work_report"),
    )
    append_log(run_dir, "outcome", f"runtime outcome BLOCKED code={code}")
    return outcome


def send_planning_blocked_from_state(
    contract: PlanningProjectContract,
    run_dir: Path,
    state: dict[str, Any],
    *,
    code: str,
    reason: str,
) -> None:
    payload = {
        "project_id": str(state["project_id"]),
        "from": contract.role,
        "to": contract.blocked_to,
        "phase": "BLOCKED",
        "instructions": contract.blocked_message(code=code, reason=reason),
    }
    response = send_session_message(contract.blocked_session_key, json.dumps(payload, separators=(",", ":")))
    result_payload = {
        "status": "blocked",
        "blocked_at": iso_now(),
        "code": code,
        "payload": payload,
        "response": response,
    }
    write_json(run_dir / "result.json", result_payload)
    update_state(
        run_dir,
        status="blocked",
        blocked_at=result_payload["blocked_at"],
        blocked_code=code,
        result_payload=payload,
        last_send_response=response,
        last_error={"code": code, "message": reason},
    )


def maybe_write_planning_blocked_state(run_dir: Path, state: dict[str, Any], reason: str) -> None:
    if not state.get("project_state_written"):
        return
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            str(state["project_id"]),
            "BLOCKED",
            "none",
            "--actor",
            "smith",
            "--expect-owner",
            "smith",
            "--current-agent",
            "none",
            "--task-status",
            "BLOCKED",
            "--last-task-result",
            "BLOCKED",
            "--increment-blocked",
            "--blocked-reason",
            reason,
            "--note",
            "Smith planning failed. Escalating to Neo.",
        ],
        timeout=120,
    )
    if result.returncode == 0:
        append_log(run_dir, "complete", "project state updated to BLOCKED after planning failure")


def complete_planning_run(contract: PlanningProjectContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        print(f"ALREADY_SENT={run_dir / 'result.json'}")
        return state
    if status == "blocked":
        print(f"ALREADY_BLOCKED={run_dir / 'result.json'}")
        return state
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")

    attempt = int(state.get("completion_attempts", 0)) + 1
    state = update_state(run_dir, status="verifying", completion_attempts=attempt, last_error=None)
    append_log(run_dir, "complete", "planning complete started")

    try:
        artifacts, active_task, task_ids = load_planning_manifest(contract, state)
        artifact_pairs = ensure_artifact_drafts(state, artifacts)
        verify_planning_draft_contents(
            contract,
            Path(state["draft_dir"]),
            active_task=active_task,
            task_ids=task_ids,
        )

        for artifact, draft_file in artifact_pairs:
            write_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_write.sh"),
                    str(state["project_id"]),
                    artifact,
                    "--source-file",
                    str(draft_file),
                    "--action",
                    f"{contract.role}_runtime_import",
                ],
                timeout=120,
            )
            require_ok(write_result, action=f"project_write {artifact}")

        plan_verify = run_command(
            [
                "bash",
                str(live_bin_root() / "verify_artifact.sh"),
                str(state["project_id"]),
                "PLANNING",
                "management/PLAN.md",
                "--action",
                "smith-plan-check",
                "--contains",
                "## Overview",
                "--contains",
                "## Phases",
            ],
            timeout=120,
        )
        require_ok(plan_verify, action="verify_artifact management/PLAN.md")

        backlog_cmd = [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            str(state["project_id"]),
            "PLANNING",
            "management/BACKLOG.md",
            "--action",
            "smith-backlog-check",
        ]
        for task_id in task_ids:
            backlog_cmd.extend(["--contains", task_id])
        require_ok(run_command(backlog_cmd, timeout=120), action="verify_artifact management/BACKLOG.md")

        current_task_cmd = [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            str(state["project_id"]),
            "PLANNING",
            "CURRENT_TASK.md",
            "--action",
            "smith-current-task-check",
            "--contains",
            active_task,
        ]
        require_ok(run_command(current_task_cmd, timeout=120), action="verify_artifact CURRENT_TASK.md")

        for task_id in task_ids:
            task_verify = run_command(
                [
                    "bash",
                    str(live_bin_root() / "verify_artifact.sh"),
                    str(state["project_id"]),
                    "PLANNING",
                    f"management/tasks/{task_id}.md",
                    "--action",
                    "smith-task-check",
                    "--contains",
                    task_id,
                ],
                timeout=120,
            )
            require_ok(task_verify, action=f"verify_artifact management/tasks/{task_id}.md")

        write_state_result = run_command(
            [
                "bash",
                str(live_bin_root() / "write_state.sh"),
                str(state["project_id"]),
                "PLANNING",
                "niaobe",
                "--actor",
                "smith",
                "--expect-owner",
                "smith",
                "--active-task",
                active_task,
                "--task-phase",
                "TASK_HANDOFF",
                "--task-status",
                "READY",
                "--note",
                contract.ready_note(task_id=active_task),
            ],
            timeout=120,
        )
        require_ok(write_state_result, action="write_state")
        state = update_state(
            run_dir,
            project_state_written=True,
            active_task=active_task,
            task_ids=task_ids,
            artifacts=artifacts,
        )

        handoff_envelope = str(state.get("handoff_envelope", "")).strip()
        if not handoff_envelope:
            handoff_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "handoff.sh"),
                    "smith",
                    "niaobe",
                    str(state["project_id"]),
                    contract.handoff_instructions(task_id=active_task),
                    "TASK_HANDOFF",
                    active_task,
                ],
                timeout=120,
            )
            handoff_output = require_ok(handoff_result, action="handoff.sh smith->niaobe")
            handoff_envelope = extract_handoff_envelope(handoff_output)
            state = update_state(
                run_dir,
                status="delivery_pending",
                handoff_output=handoff_output,
                handoff_envelope=handoff_envelope,
            )
        else:
            handoff_output = str(state.get("handoff_output", "")).strip()

        send_response = send_session_message(contract.success_session_key, handoff_envelope)
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "active_task": active_task,
            "task_ids": task_ids,
            "handoff_envelope": handoff_envelope,
            "handoff_output": handoff_output,
            "response": send_response,
        }
        write_json(run_dir / "result.json", result_payload)
        update_state(
            run_dir,
            status="sent",
            sent_at=result_payload["sent_at"],
            active_task=active_task,
            task_ids=task_ids,
            artifacts=artifacts,
            result_payload=result_payload,
            last_send_response=send_response,
            last_error=None,
        )
        append_log(run_dir, "complete", f"planning complete succeeded; handed {active_task} to niaobe")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        append_log(run_dir, "complete", f"planning complete failed: {exc}")
        details = str(exc)
        failure_code = exc.code
        if failure_code == "helper_failed" and any(
            token in details for token in ("project_write", "verify_artifact", "handoff.sh")
        ):
            failure_code = "verification_failed"
        if failure_code == "tool_denied":
            update_state(
                run_dir,
                status="repair_needed",
                last_error={"code": failure_code, "message": details},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED=bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\"")
            raise
        if failure_code in {"missing_draft", "verification_failed"} and attempt == 1:
            update_state(
                run_dir,
                status="repair_needed",
                last_error={"code": failure_code, "message": details},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED=bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\"")
            raise
        maybe_write_planning_blocked_state(run_dir, state, details)
        try:
            send_planning_blocked_from_state(contract, run_dir, state, code=failure_code, reason=details)
        except WorkerRuntimeError as send_exc:
            update_state(run_dir, status="send_failed", last_error={"code": send_exc.code, "message": str(send_exc)})
            append_log(run_dir, "complete", f"BLOCKED send failed: {send_exc}")
            raise send_exc
        raise


def complete_artifact_run(contract: ArtifactWorkerContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        print(f"ALREADY_SENT={run_dir / 'result.json'}")
        return state
    if status == "blocked":
        print(f"ALREADY_BLOCKED={run_dir / 'result.json'}")
        return state
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")

    attempt = int(state.get("completion_attempts", 0)) + 1
    state = update_state(run_dir, status="verifying", completion_attempts=attempt, last_error=None)
    append_log(run_dir, "complete", "artifact complete started")

    try:
        artifacts, test_command, validation_report = load_artifact_manifest(state)
        state = update_state(
            run_dir,
            validation_plan=test_command,
            validation_report=validation_report,
        )
        artifact_pairs = ensure_artifact_drafts(state, artifacts)

        created_dirs: set[str] = set()
        for artifact, _draft_file in artifact_pairs:
            output_parent = Path(artifact).parent.as_posix()
            if output_parent in {"", "."} or output_parent in created_dirs:
                continue
            mkdir_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_mkdir.sh"),
                    str(state["project_id"]),
                    output_parent,
                    "--action",
                    f"{contract.role}_runtime_mkdir",
                ],
                timeout=120,
            )
            require_ok(mkdir_result, action=f"project_mkdir {output_parent}")
            created_dirs.add(output_parent)

        for artifact, draft_file in artifact_pairs:
            write_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_write.sh"),
                    str(state["project_id"]),
                    artifact,
                    "--source-file",
                    str(draft_file),
                    "--action",
                    f"{contract.role}_runtime_import",
                ],
                timeout=120,
            )
            require_ok(write_result, action=f"project_write {artifact}")

            verify_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "verify_artifact.sh"),
                    str(state["project_id"]),
                    contract.phase,
                    artifact,
                    "--action",
                    f"{contract.role}_runtime_verify",
                ],
                timeout=120,
            )
            require_ok(verify_result, action=f"verify_artifact {artifact}")

        exec_cmd = [
            "bash",
            str(live_bin_root() / "project_exec.sh"),
            str(state["project_id"]),
            contract.project_exec_role,
            *test_command,
        ]
        print("PROJECT_EXEC=" + " ".join(exec_cmd))
        exec_result = run_command(exec_cmd, timeout=300)
        exec_details = command_details(exec_result)
        exec_outcome = parse_outcome(exec_details)
        validation_run = {
            "command": test_command,
            "project_exec": " ".join(exec_cmd),
            "exit_code": exec_result.returncode,
            "stdout_excerpt": (exec_result.stdout or "")[:4000],
            "stderr_excerpt": (exec_result.stderr or "")[:4000],
            "outcome": exec_outcome,
            "recorded_at": iso_now(),
        }
        update_state(run_dir, validation_runs=[validation_run])
        exec_output = require_ok(exec_result, action="project_exec")
        test_summary = summarize_test_output(exec_output)
        validation_evidence = {
            "declared_report": validation_report,
            "runtime_command": test_command,
            "runtime_exit_code": exec_result.returncode,
            "runtime_summary": test_summary,
            "status": "pass",
        }
        outcome = handle_artifact_work_report_outcome(
            contract,
            run_dir,
            state,
            _artifact_done_report_payload(
                contract,
                state,
                artifacts=artifacts,
                test_command=test_command,
                test_summary=test_summary,
            ),
            accepted_instructions=contract.done_message(artifacts=artifacts, test_command=test_command, test_summary=test_summary),
            accepted_state_updates={
                "artifacts": artifacts,
                "test_command": test_command,
                "test_summary": test_summary,
                "project_exec": " ".join(exec_cmd),
                "validation_evidence": validation_evidence,
            },
        )
        if outcome.outcome != "ACCEPTED":
            raise WorkerRuntimeError(outcome.message, code=outcome.code or "outcome_not_accepted")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        append_log(run_dir, "complete", f"artifact complete failed: {exc}")
        failure_code = "test_failed" if exc.code == "helper_failed" and "project_exec" in str(exc) else exc.code
        max_attempts = 5
        if failure_code in {"missing_draft", "verification_failed", "test_failed", "tool_denied"} and attempt <= max_attempts:
            record_artifact_repair_required(
                contract,
                run_dir,
                state,
                code=failure_code,
                reason=str(exc),
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED={_artifact_finish_command(contract, run_dir)}")
            raise
        try:
            send_blocked_from_state(contract, run_dir, state, code=failure_code, reason=str(exc))
        except WorkerRuntimeError as send_exc:
            update_state(run_dir, status="send_failed", last_error={"code": send_exc.code, "message": str(send_exc)})
            append_log(run_dir, "complete", f"BLOCKED send failed: {send_exc}")
            raise send_exc
        raise


def complete_run(contract: WorkerContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        print(f"ALREADY_SENT={run_dir / 'result.json'}")
        return state
    if status == "blocked":
        raise WorkerRuntimeError("run is already blocked; complete is not allowed", code="terminal_run")
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")

    attempt = int(state.get("completion_attempts", 0)) + 1
    draft_file = ensure_expected_draft(state)
    draft_text = draft_file.read_text(encoding="utf-8")
    output_path = str(state.get("output_path", "")).strip()
    if not output_path:
        raise WorkerRuntimeError("run metadata is missing output_path", code="missing_state")

    update_state(run_dir, status="verifying", completion_attempts=attempt, last_error=None)
    append_log(run_dir, "complete", f"complete started with draft {draft_file}")

    try:
        verify_draft_content(contract, draft_text, task_id=str(state["task_id"]))

        output_parent = Path(output_path).parent.as_posix()
        if output_parent not in {"", "."}:
            mkdir_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_mkdir.sh"),
                    str(state["project_id"]),
                    output_parent,
                    "--action",
                    f"{contract.role}_runtime_mkdir",
                ],
                timeout=120,
            )
            require_ok(mkdir_result, action=f"project_mkdir {output_parent}")

        write_result = run_command(
            [
                "bash",
                str(live_bin_root() / "project_write.sh"),
                str(state["project_id"]),
                output_path,
                "--source-file",
                str(draft_file),
                "--action",
                f"{contract.role}_runtime_import",
            ],
            timeout=120,
        )
        require_ok(write_result, action=f"project_write {output_path}")

        verify_cmd = [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            str(state["project_id"]),
            contract.phase,
            output_path,
            "--action",
            f"{contract.role}_runtime_verify",
        ]
        for pattern in contract.render_verify_patterns(task_id=str(state["task_id"])):
            verify_cmd.extend(["--contains", pattern])
        verify_result = run_command(verify_cmd, timeout=120)
        require_ok(verify_result, action=f"verify_artifact {output_path}")
        work_result = validate_work_result(
            {
                "project_id": str(state["project_id"]),
                "task_id": str(state["task_id"]),
                "from": contract.role,
                "phase": contract.phase,
                "status": "DONE",
                "summary": f"{output_path} imported and verified.",
                "verification": {
                    "task_id": str(state["task_id"]),
                    "agent": contract.role,
                    "timestamp": iso_now(),
                    "performed": True,
                    "command": verify_cmd,
                    "status": "pass",
                    "summary": f"{output_path} verified against required patterns.",
                    "evidence_paths": [output_path],
                },
            }
        ).to_dict()
        project_workspace = {
            "workspace_root": str(state["project_path"]),
            "allowed_write_paths": [output_path],
            "expected_artifacts": [output_path],
            "approved_runtime_evidence_roots": [],
        }
        artifact_manifest = {
            "created": [output_path],
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": [output_path],
            "evidence_paths": [output_path],
        }
        state["outbound_work_result"] = work_result
        state["outbound_project_workspace"] = project_workspace
        state["outbound_artifact_manifest"] = artifact_manifest

        payload = build_result_payload(
            contract,
            state,
            instructions=contract.done_message(task_id=str(state["task_id"]), output_path=output_path),
        )
        result_payload = {
            "status": "ready",
            "sent_at": iso_now(),
            "payload": payload,
        }
        write_json(run_dir / "result.json", result_payload)
        signal_payload = build_child_result_signal(
            state=state,
            from_agent=contract.role,
            to_agent=contract.expected_from,
            phase=contract.phase,
            signal="COMPLETE",
        )
        response = send_session_message(contract.session_key, json.dumps(signal_payload, separators=(",", ":")))
        result_payload["status"] = "sent"
        result_payload["response"] = response
        result_payload["signal"] = signal_payload
        write_json(run_dir / "result.json", result_payload)
        update_state(
            run_dir,
            status="sent",
            sent_at=result_payload["sent_at"],
            result_payload=payload,
            last_send_response=response,
            last_error=None,
        )
        append_log(run_dir, "complete", f"complete succeeded; sent DONE for {output_path}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        details = str(exc)
        failure_code = exc.code
        if failure_code == "helper_failed" and is_tool_denial_text(details):
            failure_code = "tool_denied"
        failure_status = "send_failed" if failure_code == "send_failed" else "verification_failed"
        if failure_code == "tool_denied":
            update_state(
                run_dir,
                status="repair_needed",
                last_error={"code": failure_code, "message": details},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED=bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\"")
            raise
        if failure_code == "missing_draft" and attempt == 1:
            update_state(
                run_dir,
                status="repair_needed",
                last_error={"code": failure_code, "message": details},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"")
            raise
        update_state(run_dir, status=failure_status, last_error={"code": failure_code, "message": details})
        append_log(run_dir, "complete", f"complete failed: {exc}")
        raise


def block_run(contract: WorkerContract, run_dir: Path, *, code: str, reason: str) -> dict[str, Any]:
    normalized_code = code.strip().lower()
    if normalized_code not in contract.blocked_codes:
        allowed = ", ".join(contract.blocked_codes)
        raise WorkerRuntimeError(f"invalid block code: {code}; allowed: {allowed}", code="envelope_invalid")

    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        raise WorkerRuntimeError("run already sent; block is not allowed", code="terminal_run")
    if status == "blocked":
        print(f"ALREADY_BLOCKED={run_dir / 'result.json'}")
        return state

    payload = build_result_payload(
        contract,
        state,
        instructions=contract.blocked_message(code=normalized_code, reason=reason.strip()),
    )
    append_log(run_dir, "block", f"block started code={normalized_code} reason={reason.strip()}")
    try:
        result_payload = {
            "status": "ready",
            "blocked_at": iso_now(),
            "code": normalized_code,
            "payload": payload,
        }
        write_json(run_dir / "result.json", result_payload)
        signal_payload = build_child_result_signal(
            state=state,
            from_agent=contract.role,
            to_agent=contract.expected_from,
            phase=contract.phase,
            signal="BLOCKED",
            reason=reason.strip(),
        )
        response = send_session_message(contract.session_key, json.dumps(signal_payload, separators=(",", ":")))
        result_payload["status"] = "blocked"
        result_payload["response"] = response
        result_payload["signal"] = signal_payload
        write_json(run_dir / "result.json", result_payload)
        update_state(
            run_dir,
            status="blocked",
            blocked_at=result_payload["blocked_at"],
            blocked_code=normalized_code,
            result_payload=payload,
            last_send_response=response,
            last_error=None,
        )
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="send_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "block", f"block failed: {exc}")
        raise


def block_artifact_run(contract: ArtifactWorkerContract, run_dir: Path, *, code: str, reason: str) -> dict[str, Any]:
    normalized_code = code.strip().lower()
    if normalized_code not in contract.blocked_codes:
        allowed = ", ".join(contract.blocked_codes)
        raise WorkerRuntimeError(f"invalid block code: {code}; allowed: {allowed}", code="envelope_invalid")

    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        raise WorkerRuntimeError("run already sent; block is not allowed", code="terminal_run")
    if status == "blocked":
        print(f"ALREADY_BLOCKED={run_dir / 'result.json'}")
        return state
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")

    append_log(run_dir, "block", f"artifact block started code={normalized_code} reason={reason.strip()}")
    try:
        send_blocked_from_state(contract, run_dir, state, code=normalized_code, reason=reason.strip())
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="send_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "block", f"artifact block failed: {exc}")
        raise


def block_planning_run(contract: PlanningProjectContract, run_dir: Path, *, code: str, reason: str) -> dict[str, Any]:
    normalized_code = code.strip().lower()
    if normalized_code not in contract.blocked_codes:
        allowed = ", ".join(contract.blocked_codes)
        raise WorkerRuntimeError(f"invalid block code: {code}; allowed: {allowed}", code="envelope_invalid")

    state = load_state(run_dir)
    status = str(state.get("status", "")).strip().lower()
    if status == "sent":
        raise WorkerRuntimeError("run already sent; block is not allowed", code="terminal_run")
    if status == "blocked":
        print(f"ALREADY_BLOCKED={run_dir / 'result.json'}")
        return state

    append_log(run_dir, "block", f"block started code={normalized_code} reason={reason.strip()}")
    maybe_write_planning_blocked_state(run_dir, state, reason.strip())
    try:
        send_planning_blocked_from_state(contract, run_dir, state, code=normalized_code, reason=reason.strip())
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        update_state(run_dir, status="send_failed", last_error={"code": exc.code, "message": str(exc)})
        append_log(run_dir, "block", f"block failed: {exc}")
        raise


def read_envelope_arg(args: argparse.Namespace) -> str:
    if args.envelope_json:
        return args.envelope_json
    if args.envelope_file:
        return Path(args.envelope_file).read_text(encoding="utf-8")
    raise WorkerRuntimeError("prepare requires envelope_json or --envelope-file", code="envelope_invalid")


def build_parser(contract: WorkerContract) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"{contract.role}_run_task")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("envelope_json", nargs="?")
    prepare.add_argument("--envelope-file")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("envelope_json", nargs="?")
    run_parser.add_argument("--envelope-file")

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("run_dir")
    read_parser.add_argument("relative_path")

    complete = subparsers.add_parser("complete")
    complete.add_argument("run_dir")

    report = subparsers.add_parser("report")
    report.add_argument("run_dir")

    repair = subparsers.add_parser("repair")
    repair.add_argument("run_dir")

    block = subparsers.add_parser("block")
    block.add_argument("run_dir")
    block.add_argument("--code", required=True)
    block.add_argument("--reason", required=True)

    return parser


def build_artifact_parser(contract: ArtifactWorkerContract) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"{contract.role}_run_task")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("envelope_json", nargs="?")
    prepare.add_argument("--envelope-file")

    dispatch = subparsers.add_parser("dispatch")
    dispatch.add_argument("envelope_json", nargs="?")
    dispatch.add_argument("--envelope-file")

    resume = subparsers.add_parser("resume")
    resume.add_argument("run_dir")

    advance = subparsers.add_parser("advance")
    advance.add_argument("run_dir")

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("run_dir")
    read_parser.add_argument("relative_path")

    complete = subparsers.add_parser("complete")
    complete.add_argument("run_dir")

    report = subparsers.add_parser("report")
    report.add_argument("run_dir")

    repair = subparsers.add_parser("repair")
    repair.add_argument("run_dir")

    block = subparsers.add_parser("block")
    block.add_argument("run_dir")
    block.add_argument("--code", required=True)
    block.add_argument("--reason", required=True)

    return parser


def build_planning_parser(contract: PlanningProjectContract) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"{contract.role}_plan_project")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("envelope_json", nargs="?")
    prepare.add_argument("--envelope-file")

    autoplan = subparsers.add_parser("autoplan")
    autoplan.add_argument("envelope_json", nargs="?")
    autoplan.add_argument("--envelope-file")

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("run_dir")
    read_parser.add_argument("relative_path")

    complete = subparsers.add_parser("complete")
    complete.add_argument("run_dir")

    block = subparsers.add_parser("block")
    block.add_argument("run_dir")
    block.add_argument("--code", required=True)
    block.add_argument("--reason", required=True)

    return parser


def main_for_contract(contract: WorkerContract, argv: list[str] | None = None) -> int:
    parser = build_parser(contract)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_run(contract, read_envelope_arg(args))
        elif args.command == "run":
            prepare_run(contract, read_envelope_arg(args))
        elif args.command == "read":
            sys.stdout.write(read_run(contract, Path(args.run_dir), args.relative_path))
        elif args.command == "complete":
            if contract.role == "architect":
                from agent_runner import complete_run_graph

                complete_run_graph(contract, Path(args.run_dir))
            else:
                complete_run(contract, Path(args.run_dir))
        elif args.command == "repair":
            if contract.role == "architect":
                from agent_runner import print_repair_brief

                print_repair_brief(contract, Path(args.run_dir))
            else:
                raise WorkerRuntimeError(f"{contract.role} does not support repair", code="envelope_invalid")
        elif args.command == "block":
            block_run(contract, Path(args.run_dir), code=args.code, reason=args.reason)
        else:
            raise WorkerRuntimeError(f"unknown command: {args.command}", code="envelope_invalid")
        return 0
    except WorkerRuntimeError as exc:
        print(f"WORKER_RUNTIME_FAILED: {exc}")
        return 20


def main_for_planning_contract(contract: PlanningProjectContract, argv: list[str] | None = None) -> int:
    parser = build_planning_parser(contract)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            envelope_raw = read_envelope_arg(args)
            if should_autoplan_planning_envelope(contract, envelope_raw):
                if contract.role == "smith":
                    from smith_graph_runtime import autoplan_required_planning_project_graph

                    autoplan_required_planning_project_graph(contract, envelope_raw)
                else:
                    autoplan_required_planning_project(contract, envelope_raw)
            else:
                prepare_planning_run(contract, envelope_raw)
        elif args.command == "autoplan":
            envelope_raw = read_envelope_arg(args)
            if contract.role == "smith":
                from smith_graph_runtime import autoplan_required_planning_project_graph

                autoplan_required_planning_project_graph(contract, envelope_raw)
            else:
                autoplan_required_planning_project(contract, envelope_raw)
        elif args.command == "read":
            sys.stdout.write(read_run(contract, Path(args.run_dir), args.relative_path))  # type: ignore[arg-type]
        elif args.command == "complete":
            complete_planning_run(contract, Path(args.run_dir))
        elif args.command == "block":
            block_planning_run(contract, Path(args.run_dir), code=args.code, reason=args.reason)
        else:
            raise WorkerRuntimeError(f"unknown command: {args.command}", code="envelope_invalid")
        return 0
    except WorkerRuntimeError as exc:
        print(f"WORKER_RUNTIME_FAILED: {exc}")
        return 20


def main_for_artifact_contract(contract: ArtifactWorkerContract, argv: list[str] | None = None) -> int:
    parser = build_artifact_parser(contract)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_artifact_run(contract, read_envelope_arg(args))
        elif args.command == "dispatch":
            state = dispatch_artifact_task(contract, read_envelope_arg(args))
            print(f"RUN_DIR={Path(state['task_packet_file']).parent}")
            print(f"TASK_PACKET_FILE={state['task_packet_file']}")
        elif args.command == "resume":
            state = resume_artifact_task(contract, Path(args.run_dir))
            print(f"RUN_DIR={args.run_dir}")
            print(f"CONTINUATION_FILE={state['last_recovery_file']}")
        elif args.command == "advance":
            state = advance_artifact_task(contract, Path(args.run_dir))
            print(f"RUN_DIR={args.run_dir}")
            print(f"STATUS={state['status']}")
        elif args.command == "read":
            sys.stdout.write(read_run(contract, Path(args.run_dir), args.relative_path))  # type: ignore[arg-type]
        elif args.command == "complete":
            if contract.role == "morpheus":
                from agent_runner import complete_artifact_run_graph

                complete_artifact_run_graph(contract, Path(args.run_dir))
            else:
                complete_artifact_run(contract, Path(args.run_dir))
        elif args.command == "report":
            if contract.role == "morpheus":
                from agent_runner import complete_artifact_run_graph

                complete_artifact_run_graph(contract, Path(args.run_dir))
            else:
                complete_artifact_run(contract, Path(args.run_dir))
        elif args.command == "repair":
            if contract.role == "morpheus":
                from agent_runner import print_repair_brief

                print_repair_brief(contract, Path(args.run_dir))
            else:
                raise WorkerRuntimeError("repair is only available for Morpheus", code="unsupported_command")
        elif args.command == "block":
            block_artifact_run(contract, Path(args.run_dir), code=args.code, reason=args.reason)
        else:
            raise WorkerRuntimeError(f"unknown command: {args.command}", code="envelope_invalid")
        return 0
    except WorkerRuntimeError as exc:
        print(f"WORKER_RUNTIME_FAILED: {exc}")
        return 20


if __name__ == "__main__":
    raise SystemExit("Use a role-specific wrapper such as architect_run_task.py.")
