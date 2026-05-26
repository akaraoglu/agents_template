#!/usr/bin/env python3
"""Runtime-owned Niaobe task handoff acceptance."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from worker_runtime import (
    RUN_DEADLINE_SECONDS,
    WorkerRuntimeError,
    append_log,
    extract_handoff_envelope,
    live_bin_root,
    require_ok,
    resolve_project,
    run_command,
    send_session_message,
    workspace_root,
    write_json,
)


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_task_handoff(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"invalid envelope JSON: {exc}", code="envelope_invalid") from exc
    if not isinstance(payload, dict):
        raise WorkerRuntimeError("envelope must be a JSON object", code="envelope_invalid")

    required = ("project_id", "task_id", "from", "to", "phase", "instructions")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise WorkerRuntimeError(f"envelope missing required field(s): {', '.join(missing)}", code="envelope_invalid")
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
    if not re.fullmatch(r"T\d{3}", task_id):
        raise WorkerRuntimeError(f"invalid task_id: {task_id}", code="envelope_invalid")
    if from_agent != "smith" or to_agent != "niaobe" or phase != "TASK_HANDOFF":
        raise WorkerRuntimeError(
            f"unexpected routing: {from_agent}->{to_agent} phase={phase}; expected smith->niaobe phase=TASK_HANDOFF",
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


def parse_child_result(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerRuntimeError(f"invalid envelope JSON: {exc}", code="envelope_invalid") from exc
    if not isinstance(payload, dict):
        raise WorkerRuntimeError("envelope must be a JSON object", code="envelope_invalid")

    required = ("project_id", "task_id", "from", "to", "phase", "instructions")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise WorkerRuntimeError(f"envelope missing required field(s): {', '.join(missing)}", code="envelope_invalid")
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
    if not re.fullmatch(r"T\d{3}", task_id):
        raise WorkerRuntimeError(f"invalid task_id: {task_id}", code="envelope_invalid")
    if to_agent != "niaobe":
        raise WorkerRuntimeError(f"unexpected recipient: {to_agent}; expected niaobe", code="envelope_invalid")

    expected = {
        ("architect", "DESIGN"),
        ("morpheus", "IMPLEMENT"),
        ("oracle", "VERIFY"),
    }
    if (from_agent, phase) not in expected:
        raise WorkerRuntimeError(
            f"unexpected child result: {from_agent}->niaobe phase={phase}",
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


def build_run_dir(project_id: str, task_id: str) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    return workspace_root() / "niaobe" / "runs" / project_id / task_id / run_id


def send_handoff(
    *,
    project_id: str,
    task_id: str,
    to_agent: str,
    phase: str,
    instructions: str,
) -> tuple[str, str, str]:
    handoff_result = run_command(
        [
            "bash",
            str(live_bin_root() / "handoff.sh"),
            "niaobe",
            to_agent,
            project_id,
            instructions,
            phase,
            task_id,
        ],
        timeout=120,
    )
    handoff_output = require_ok(handoff_result, action=f"handoff.sh niaobe->{to_agent}")
    handoff_envelope = extract_handoff_envelope(handoff_output)
    send_response = send_session_message(f"agent:{to_agent}:main", handoff_envelope)
    return handoff_output, handoff_envelope, send_response


def send_smith_result(project_id: str, task_id: str, *, phase: str, instructions: str) -> str:
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "from": "niaobe",
        "to": "smith",
        "phase": phase,
        "instructions": instructions,
    }
    return send_session_message("agent:smith:main", json.dumps(payload, separators=(",", ":")))


def mark_child_runtime_blocked(
    run_dir: Path,
    state: dict[str, Any],
    envelope: dict[str, str],
    *,
    code: str,
    reason: str,
) -> dict[str, Any]:
    write_state_result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            envelope["project_id"],
            "BLOCKED",
            "smith",
            "--actor",
            "niaobe",
            "--expect-owner",
            "niaobe",
            "--active-task",
            envelope["task_id"],
            "--task-phase",
            envelope["phase"],
            "--task-status",
            "BLOCKED",
            "--blocked-reason",
            f"{code}: {reason}",
            "--note",
            f"Task {envelope['task_id']} blocked during Niaobe {envelope['phase']} continuation.",
        ],
        timeout=120,
    )
    require_ok(write_state_result, action="write_state child blocked")
    send_response = send_smith_result(
        envelope["project_id"],
        envelope["task_id"],
        phase="TASK_BLOCKED",
        instructions=f"BLOCKED[{code}]: {reason}",
    )
    result_payload = {
        "status": "blocked",
        "blocked_at": iso_now(),
        "project_id": envelope["project_id"],
        "task_id": envelope["task_id"],
        "code": code,
        "reason": reason,
        "response": send_response,
    }
    write_json(run_dir / "result.json", result_payload)
    state.update(
        {
            "status": "blocked",
            "blocked_at": result_payload["blocked_at"],
            "blocked_code": code,
            "last_send_response": send_response,
            "result_payload": result_payload,
            "last_error": {"code": code, "message": reason},
        }
    )
    write_json(run_dir / "state.json", state)
    return state


def accept_task_handoff(envelope_raw: str) -> dict[str, Any]:
    envelope = parse_task_handoff(envelope_raw)
    resolved = resolve_project(envelope["project_id"])
    run_dir = build_run_dir(envelope["project_id"], envelope["task_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "envelope.json", envelope)

    state: dict[str, Any] = {
        "role": "niaobe",
        "phase": "TASK_HANDOFF",
        "status": "accepting",
        "prepared_at": iso_now(),
        "prepared_epoch": time.time(),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=RUN_DEADLINE_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_id": envelope["project_id"],
        "project_path": str(resolved["project_path"]),
        "task_id": envelope["task_id"],
        "last_error": None,
        "last_send_response": None,
        "result_payload": None,
    }
    write_json(run_dir / "state.json", state)
    append_log(run_dir, "accept", f"task handoff accept started for {envelope['project_id']} {envelope['task_id']}")

    try:
        ack_result = run_command(
            [
                "bash",
                str(live_bin_root() / "ack_handoff.sh"),
                "niaobe",
                envelope["project_id"],
                "TASK_HANDOFF",
                "RECEIVED",
                "Smith task handoff accepted.",
            ],
            timeout=120,
        )
        require_ok(ack_result, action="ack_handoff")

        read_paths = (
            "PROJECT.md",
            "PROJECT_STATE.md",
            "CURRENT_TASK.md",
            f"management/tasks/{envelope['task_id']}.md",
        )
        for relative_path in read_paths:
            read_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_read.sh"),
                    envelope["project_id"],
                    relative_path,
                    "--action",
                    "niaobe_runtime_accept_read",
                ],
                timeout=120,
            )
            require_ok(read_result, action=f"project_read {relative_path}")

        write_state_result = run_command(
            [
                "bash",
                str(live_bin_root() / "write_state.sh"),
                envelope["project_id"],
                "IN_PROGRESS",
                "architect",
                "--actor",
                "niaobe",
                "--expect-owner",
                "smith",
                "--set-owner",
                "niaobe",
                "--active-task",
                envelope["task_id"],
                "--task-phase",
                "DESIGN",
                "--task-status",
                "IN_PROGRESS",
                "--note",
                f"Task {envelope['task_id']} acknowledged. Delegating design to Architect.",
            ],
            timeout=120,
        )
        require_ok(write_state_result, action="write_state")

        architect_instructions = (
            f"Read PROJECT.md, CURRENT_TASK.md, and management/tasks/{envelope['task_id']}.md. "
            f"Write management/architecture/{envelope['task_id']}.md and report DONE or BLOCKED."
        )
        handoff_output, handoff_envelope, send_response = send_handoff(
            project_id=envelope["project_id"],
            task_id=envelope["task_id"],
            to_agent="architect",
            phase="DESIGN",
            instructions=architect_instructions,
        )

        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "project_id": envelope["project_id"],
            "task_id": envelope["task_id"],
            "handoff_envelope": handoff_envelope,
            "handoff_output": handoff_output,
            "response": send_response,
        }
        write_json(run_dir / "result.json", result_payload)
        state.update(
            {
                "status": "sent",
                "sent_at": result_payload["sent_at"],
                "handoff_envelope": handoff_envelope,
                "handoff_output": handoff_output,
                "last_send_response": send_response,
                "result_payload": result_payload,
                "last_error": None,
            }
        )
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "accept", "task handoff accepted and delegated to architect")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return state
    except WorkerRuntimeError as exc:
        state.update({"status": "failed", "last_error": {"code": exc.code, "message": str(exc)}})
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "accept", f"task handoff accept failed: {exc}")
        raise


def continue_child_result(envelope_raw: str) -> dict[str, Any]:
    envelope = parse_child_result(envelope_raw)
    resolved = resolve_project(envelope["project_id"])
    run_dir = build_run_dir(envelope["project_id"], envelope["task_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "envelope.json", envelope)

    state: dict[str, Any] = {
        "role": "niaobe",
        "phase": envelope["phase"],
        "status": "continuing",
        "prepared_at": iso_now(),
        "prepared_epoch": time.time(),
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=RUN_DEADLINE_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_id": envelope["project_id"],
        "project_path": str(resolved["project_path"]),
        "task_id": envelope["task_id"],
        "from": envelope["from"],
        "last_error": None,
        "last_send_response": None,
        "result_payload": None,
    }
    write_json(run_dir / "state.json", state)
    append_log(run_dir, "child", f"child result started from {envelope['from']} phase={envelope['phase']}")

    try:
        instructions_upper = envelope["instructions"].upper()
        if "BLOCKED" in instructions_upper or instructions_upper.startswith("FAIL"):
            write_state_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "write_state.sh"),
                    envelope["project_id"],
                    "BLOCKED",
                    "smith",
                    "--actor",
                    "niaobe",
                    "--expect-owner",
                    "niaobe",
                    "--active-task",
                    envelope["task_id"],
                    "--task-phase",
                    envelope["phase"],
                    "--task-status",
                    "BLOCKED",
                    "--blocked-reason",
                    envelope["instructions"],
                    "--note",
                    f"Task {envelope['task_id']} blocked during {envelope['phase']}.",
                ],
                timeout=120,
            )
            require_ok(write_state_result, action="write_state blocked")
            send_response = send_smith_result(
                envelope["project_id"],
                envelope["task_id"],
                phase="TASK_BLOCKED",
                instructions=f"BLOCKED: {envelope['instructions']}",
            )
            result_payload = {
                "status": "blocked",
                "sent_at": iso_now(),
                "project_id": envelope["project_id"],
                "task_id": envelope["task_id"],
                "response": send_response,
            }
        elif envelope["from"] == "architect":
            verify_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "verify_artifact.sh"),
                    envelope["project_id"],
                    "DESIGN",
                    f"management/architecture/{envelope['task_id']}.md",
                    "--action",
                    "niaobe-design-check",
                    "--contains",
                    envelope["task_id"],
                    "--contains",
                    "^## Overview",
                    "--contains",
                    "^## Test Strategy",
                ],
                timeout=120,
            )
            require_ok(verify_result, action="verify_artifact architecture")
            write_state_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "write_state.sh"),
                    envelope["project_id"],
                    "IN_PROGRESS",
                    "morpheus",
                    "--actor",
                    "niaobe",
                    "--expect-owner",
                    "niaobe",
                    "--active-task",
                    envelope["task_id"],
                    "--task-phase",
                    "IMPLEMENT",
                    "--task-status",
                    "IN_PROGRESS",
                    "--note",
                    "Architecture verified. Delegating implementation to Morpheus.",
                ],
                timeout=120,
            )
            require_ok(write_state_result, action="write_state implement")
            implementation_instructions = (
                f"Implement only task {envelope['task_id']} using CURRENT_TASK.md, "
                f"management/tasks/{envelope['task_id']}.md, and management/architecture/{envelope['task_id']}.md. "
                "Report DONE or BLOCKED with exact artifact paths and test summary."
            )
            handoff_output, handoff_envelope, send_response = send_handoff(
                project_id=envelope["project_id"],
                task_id=envelope["task_id"],
                to_agent="morpheus",
                phase="IMPLEMENT",
                instructions=implementation_instructions,
            )
            result_payload = {
                "status": "sent",
                "sent_at": iso_now(),
                "project_id": envelope["project_id"],
                "task_id": envelope["task_id"],
                "handoff_envelope": handoff_envelope,
                "handoff_output": handoff_output,
                "response": send_response,
            }
        elif envelope["from"] == "morpheus":
            for artifact in ("README.md", "src/main.py", "tests/test_main.py"):
                verify_result = run_command(
                    [
                        "bash",
                        str(live_bin_root() / "verify_artifact.sh"),
                        envelope["project_id"],
                        "IMPLEMENT",
                        artifact,
                        "--action",
                        "niaobe-implementation-check",
                    ],
                    timeout=120,
                )
                require_ok(verify_result, action=f"verify_artifact {artifact}")
            write_state_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "write_state.sh"),
                    envelope["project_id"],
                    "IN_PROGRESS",
                    "oracle",
                    "--actor",
                    "niaobe",
                    "--expect-owner",
                    "niaobe",
                    "--active-task",
                    envelope["task_id"],
                    "--task-phase",
                    "VERIFY",
                    "--task-status",
                    "IN_PROGRESS",
                    "--note",
                    "Implementation verified present. Delegating validation to Oracle.",
                ],
                timeout=120,
            )
            require_ok(write_state_result, action="write_state verify")
            oracle_instructions = (
                f"Verify only task {envelope['task_id']}, write management/validation/{envelope['task_id']}_REPORT.md, "
                "and report PASS or FAIL."
            )
            handoff_output, handoff_envelope, send_response = send_handoff(
                project_id=envelope["project_id"],
                task_id=envelope["task_id"],
                to_agent="oracle",
                phase="VERIFY",
                instructions=oracle_instructions,
            )
            result_payload = {
                "status": "sent",
                "sent_at": iso_now(),
                "project_id": envelope["project_id"],
                "task_id": envelope["task_id"],
                "handoff_envelope": handoff_envelope,
                "handoff_output": handoff_output,
                "response": send_response,
            }
        else:
            verify_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "verify_artifact.sh"),
                    envelope["project_id"],
                    "VERIFY",
                    f"management/validation/{envelope['task_id']}_REPORT.md",
                    "--action",
                    "niaobe-validation-check",
                    "--contains",
                    envelope["task_id"],
                    "--contains",
                    "PASS",
                ],
                timeout=120,
            )
            require_ok(verify_result, action="verify_artifact validation")
            write_state_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "write_state.sh"),
                    envelope["project_id"],
                    "DONE",
                    "none",
                    "--actor",
                    "niaobe",
                    "--expect-owner",
                    "niaobe",
                    "--active-task",
                    envelope["task_id"],
                    "--task-phase",
                    "VERIFY",
                    "--task-status",
                    "DONE",
                    "--last-completed-task",
                    envelope["task_id"],
                    "--last-task-result",
                    "PASS",
                    "--note",
                    f"Task {envelope['task_id']} verified PASS. Reporting complete to Smith.",
                ],
                timeout=120,
            )
            require_ok(write_state_result, action="write_state done")
            send_response = send_smith_result(
                envelope["project_id"],
                envelope["task_id"],
                phase="TASK_DONE",
                instructions=f"DONE: task {envelope['task_id']} verified PASS.",
            )
            result_payload = {
                "status": "done",
                "sent_at": iso_now(),
                "project_id": envelope["project_id"],
                "task_id": envelope["task_id"],
                "response": send_response,
            }

        write_json(run_dir / "result.json", result_payload)
        state.update(
            {
                "status": result_payload["status"],
                "sent_at": result_payload["sent_at"],
                "last_send_response": result_payload.get("response"),
                "result_payload": result_payload,
                "last_error": None,
            }
        )
        if "handoff_envelope" in result_payload:
            state["handoff_envelope"] = result_payload["handoff_envelope"]
            state["handoff_output"] = result_payload["handoff_output"]
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "child", f"child result completed with status={result_payload['status']}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return state
    except WorkerRuntimeError as exc:
        append_log(run_dir, "child", f"child result failed: {exc}")
        try:
            blocked_state = mark_child_runtime_blocked(
                run_dir,
                state,
                envelope,
                code=exc.code,
                reason=str(exc),
            )
        except WorkerRuntimeError as block_exc:
            state.update(
                {
                    "status": "failed",
                    "last_error": {"code": exc.code, "message": str(exc)},
                    "block_error": {"code": block_exc.code, "message": str(block_exc)},
                }
            )
            write_json(run_dir / "state.json", state)
            append_log(run_dir, "child", f"child blocked transition failed: {block_exc}")
            raise block_exc
        append_log(run_dir, "child", "child result failure converted to TASK_BLOCKED")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return blocked_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="niaobe_run_task")
    subparsers = parser.add_subparsers(dest="command", required=True)
    accept = subparsers.add_parser("accept")
    accept.add_argument("envelope_json")
    child = subparsers.add_parser("child")
    child.add_argument("envelope_json")
    args = parser.parse_args(argv)
    try:
        if args.command == "accept":
            accept_task_handoff(args.envelope_json)
            return 0
        if args.command == "child":
            continue_child_result(args.envelope_json)
            return 0
    except WorkerRuntimeError as exc:
        print(f"NIAOBE_RUNTIME_FAILED: {exc}")
        return 20
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
