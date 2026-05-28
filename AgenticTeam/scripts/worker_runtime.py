#!/usr/bin/env python3
"""Generic worker-runtime primitives for OpenClaw one-shot workers."""

from __future__ import annotations

import argparse
import contextlib
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


def workspace_root() -> Path:
    return Path(os.environ.get("CLAWSPACE_WORKSPACE_ROOT", "/home/alik/workspace/clawspace/workspaces"))


def live_bin_root() -> Path:
    return Path(os.environ.get("CLAWSPACE_BIN_ROOT", "/home/alik/workspace/clawspace/bin"))


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
                "- pending runtime completion",
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
                "- pending runtime completion",
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
        raise WorkerRuntimeError(f"run state missing: {path}", code="missing_state")
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


def run_command(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def require_ok(result: subprocess.CompletedProcess[str], *, action: str) -> str:
    details = command_details(result)
    outcome = parse_outcome(details)
    if result.returncode != 0:
        raise WorkerRuntimeError(f"{action} failed: {details}", code="helper_failed")
    if outcome and outcome.get("status") != "OK":
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
    return {
        "project_id": str(state["project_id"]),
        "task_id": str(state["task_id"]),
        "from": contract.role,
        "to": contract.expected_from,
        "phase": contract.phase,
        "instructions": instructions,
    }


def build_artifact_result_payload(
    contract: ArtifactWorkerContract,
    state: dict[str, Any],
    *,
    instructions: str,
) -> dict[str, str]:
    return {
        "project_id": str(state["project_id"]),
        "task_id": str(state["task_id"]),
        "from": contract.role,
        "to": contract.expected_from,
        "phase": contract.phase,
        "instructions": instructions,
    }


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
            "next_command": f"bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"",
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
    print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"")
    print("ACTION_REQUIRED=Do not stop after prepare. Either write drafts plus manifest and run NEXT_REQUIRED, or run BLOCK_COMMAND.")
    print("WORK_ORDER_GUIDANCE=Use WORK_ORDER as a preview only. If WORK_ORDER_TRUNCATED=yes or details are missing, read CONTEXT_FILE before drafting. If a source excerpt there is still truncated, read only the matching full input copy you need.")
    print("NEXT_ACTIONS_BEGIN")
    print("1. If WORK_ORDER_TRUNCATED=yes or required details are missing, read CONTEXT_FILE. If an excerpt there is truncated, read only the matching full input copy you need.")
    print("2. Write every REQUIRED_OUTPUTS path under DRAFT_WRITE_ROOT.")
    print("3. Write MANIFEST_WRITE_FILE with the artifact list and test_command.")
    print("4. Run NEXT_REQUIRED only after every required draft and MANIFEST_WRITE_FILE exist.")
    print("5. If you cannot continue from the available inputs, run BLOCK_COMMAND with an exact reason.")
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


def prepare_planning_run(contract: PlanningProjectContract, envelope_raw: str) -> PreparedArtifactRun:
    envelope = parse_planning_envelope(envelope_raw, contract)
    run_dir = build_phase_run_dir(contract.role, envelope["project_id"], "planning")
    run_dir.mkdir(parents=True, exist_ok=True)

    draft_dir = run_dir / contract.draft_dir_name
    manifest_file = draft_dir / contract.manifest_file_name
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_write_root = ensure_directory_alias(
        draft_dir,
        workspace_root() / contract.role / "draft-aliases" / run_dir.name,
    )
    manifest_write_file = draft_write_root / contract.manifest_file_name
    handoff_file = run_dir / "handoff.json"
    context_file = run_dir / "context.md"
    envelope_file = run_dir / "envelope.json"
    write_json(envelope_file, envelope)

    state = {
        "role": contract.role,
        "phase": contract.phase,
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
            "manifest_schema": {
                "artifacts": [
                    {"path": "management/PLAN.md"},
                    {"path": "management/BACKLOG.md"},
                    {"path": "management/tasks/T001.md"},
                    {"path": "CURRENT_TASK.md"},
                ],
                "active_task": "T001",
            },
            "next_command": f"bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\"",
        }
        write_json(handoff_file, handoff_payload)
        update_state(
            run_dir,
            status="awaiting_artifacts",
            project_path=str(resolved["project_path"]),
            inbound_receipt_acknowledged=True,
            draft_write_root=str(draft_write_root),
            manifest_write_file=str(manifest_write_file),
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
    print(f"NEXT_REQUIRED=bash {live_bin_root() / 'smith_plan_project.sh'} complete \"{run_dir}\"")
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


def load_artifact_manifest(state: dict[str, Any]) -> tuple[list[str], list[str]]:
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
    return artifacts, test_command


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
) -> None:
    payload = build_artifact_result_payload(
        contract,
        state,
        instructions=contract.blocked_message(code=code, reason=reason),
    )
    response = send_session_message(contract.session_key, json.dumps(payload, separators=(",", ":")))
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
        artifacts, test_command = load_artifact_manifest(state)
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
        exec_output = require_ok(exec_result, action="project_exec")
        test_summary = summarize_test_output(exec_output)

        payload = build_artifact_result_payload(
            contract,
            state,
            instructions=contract.done_message(artifacts=artifacts, test_command=test_command, test_summary=test_summary),
        )
        response = send_session_message(contract.session_key, json.dumps(payload, separators=(",", ":")))
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "payload": payload,
            "response": response,
        }
        write_json(run_dir / "result.json", result_payload)
        update_state(
            run_dir,
            status="sent",
            sent_at=result_payload["sent_at"],
            artifacts=artifacts,
            test_command=test_command,
            test_summary=test_summary,
            project_exec=" ".join(exec_cmd),
            result_payload=payload,
            last_send_response=response,
            last_error=None,
        )
        append_log(run_dir, "complete", f"artifact complete succeeded; sent DONE for {', '.join(artifacts)}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        append_log(run_dir, "complete", f"artifact complete failed: {exc}")
        failure_code = "test_failed" if exc.code == "helper_failed" and "project_exec" in str(exc) else exc.code
        if failure_code in {"missing_draft", "verification_failed", "test_failed"} and attempt == 1:
            update_state(
                run_dir,
                status="repair_needed",
                last_error={"code": failure_code, "message": str(exc)},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"")
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

    draft_file = ensure_expected_draft(state)
    draft_text = draft_file.read_text(encoding="utf-8")
    output_path = str(state.get("output_path", "")).strip()
    if not output_path:
        raise WorkerRuntimeError("run metadata is missing output_path", code="missing_state")

    update_state(run_dir, status="verifying", last_error=None)
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

        payload = build_result_payload(
            contract,
            state,
            instructions=contract.done_message(task_id=str(state["task_id"]), output_path=output_path),
        )
        response = send_session_message(contract.session_key, json.dumps(payload, separators=(",", ":")))
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "payload": payload,
            "response": response,
        }
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
        failure_status = "send_failed" if exc.code == "send_failed" else "verification_failed"
        update_state(run_dir, status=failure_status, last_error={"code": exc.code, "message": str(exc)})
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
        response = send_session_message(contract.session_key, json.dumps(payload, separators=(",", ":")))
        result_payload = {
            "status": "blocked",
            "blocked_at": iso_now(),
            "code": normalized_code,
            "payload": payload,
            "response": response,
        }
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

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("run_dir")
    read_parser.add_argument("relative_path")

    complete = subparsers.add_parser("complete")
    complete.add_argument("run_dir")

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
                from agent_runner import complete_run_graph

                complete_run_graph(contract, Path(args.run_dir))
            else:
                raise WorkerRuntimeError(f"{contract.role} does not support repair", code="envelope_invalid")
        elif args.command == "block":
            block_run(contract, Path(args.run_dir), code=args.code, reason=args.reason)
        else:
            raise WorkerRuntimeError(f"unknown command: {args.command}", code="envelope_invalid")
        return 0
    except WorkerRuntimeError as exc:
        print(f"WORKER_RUNTIME_FAILED: {exc}", file=sys.stderr)
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
        print(f"WORKER_RUNTIME_FAILED: {exc}", file=sys.stderr)
        return 20


def main_for_artifact_contract(contract: ArtifactWorkerContract, argv: list[str] | None = None) -> int:
    parser = build_artifact_parser(contract)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_artifact_run(contract, read_envelope_arg(args))
        elif args.command == "read":
            sys.stdout.write(read_run(contract, Path(args.run_dir), args.relative_path))  # type: ignore[arg-type]
        elif args.command == "complete":
            if contract.role == "morpheus":
                from agent_runner import complete_artifact_run_graph

                complete_artifact_run_graph(contract, Path(args.run_dir))
            else:
                complete_artifact_run(contract, Path(args.run_dir))
        elif args.command == "repair":
            if contract.role == "morpheus":
                from agent_runner import complete_artifact_run_graph

                complete_artifact_run_graph(contract, Path(args.run_dir))
            else:
                raise WorkerRuntimeError("repair is only available for Morpheus", code="unsupported_command")
        elif args.command == "block":
            block_run(contract, Path(args.run_dir), code=args.code, reason=args.reason)  # type: ignore[arg-type]
        else:
            raise WorkerRuntimeError(f"unknown command: {args.command}", code="envelope_invalid")
        return 0
    except WorkerRuntimeError as exc:
        print(f"WORKER_RUNTIME_FAILED: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit("Use a role-specific wrapper such as architect_run_task.py.")
