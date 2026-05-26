#!/usr/bin/env python3
"""Runtime-owned Oracle task verification."""

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
    command_details,
    extract_content,
    extract_required_outputs,
    live_bin_root,
    require_ok,
    resolve_project,
    run_command,
    send_session_message,
    workspace_root,
    write_json,
    write_text,
)


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_verify_envelope(raw: str) -> dict[str, str]:
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
    if from_agent != "niaobe" or to_agent != "oracle" or phase != "VERIFY":
        raise WorkerRuntimeError(
            f"unexpected routing: {from_agent}->{to_agent} phase={phase}; expected niaobe->oracle phase=VERIFY",
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
    return workspace_root() / "oracle" / "runs" / project_id / task_id / run_id


def read_project_file(project_id: str, relative_path: str) -> str:
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "project_read.sh"),
            project_id,
            relative_path,
            "--action",
            "oracle_runtime_read",
        ],
        timeout=120,
    )
    stdout = require_ok(result, action=f"project_read {relative_path}")
    return extract_content(stdout)


def verify_project_artifact(project_id: str, relative_path: str) -> tuple[bool, str]:
    result = run_command(
        [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            project_id,
            "VERIFY",
            relative_path,
            "--action",
            "oracle-runtime-input-check",
        ],
        timeout=120,
    )
    return result.returncode == 0, command_details(result)


def choose_test_command(required_outputs: list[str]) -> list[str]:
    if "tests/test_main.py" in required_outputs:
        return ["python3", "-m", "unittest", "tests/test_main.py"]
    return ["python3", "-m", "unittest", "discover"]


def build_report(
    *,
    task_id: str,
    verdict: str,
    test_command: list[str],
    exec_result: Any,
    artifact_checks: list[tuple[str, bool, str]],
) -> str:
    lines = [
        f"# Validation Report: {task_id}",
        "",
        "## Verdict",
        verdict,
        "",
        "## Evidence",
        f"- Test command: `{' '.join(test_command)}`",
        f"- Test exit code: {exec_result.returncode}",
    ]
    for path, ok, details in artifact_checks:
        status = "OK" if ok else "FAIL"
        lines.append(f"- Artifact `{path}`: {status}")
        if not ok:
            lines.append(f"  - Details: {details[:240]}")
    output = command_details(exec_result)
    lines.extend(
        [
            "",
            "## Test Output Summary",
            output[:1200] if output else "No output.",
            "",
        ]
    )
    return "\n".join(lines)


def send_niaobe_result(project_id: str, task_id: str, *, verdict: str, evidence: str) -> str:
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "from": "oracle",
        "to": "niaobe",
        "phase": "VERIFY",
        "instructions": f"{verdict}: task verification complete. Evidence: {evidence}",
    }
    return send_session_message("agent:niaobe:main", json.dumps(payload, separators=(",", ":")))


def verify_task(envelope_raw: str) -> dict[str, Any]:
    envelope = parse_verify_envelope(envelope_raw)
    resolved = resolve_project(envelope["project_id"])
    run_dir = build_run_dir(envelope["project_id"], envelope["task_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "envelope.json", envelope)
    state: dict[str, Any] = {
        "role": "oracle",
        "phase": "VERIFY",
        "status": "verifying",
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
    append_log(run_dir, "verify", f"oracle verification started for {envelope['project_id']} {envelope['task_id']}")

    try:
        inputs = {
            "PROJECT.md": read_project_file(envelope["project_id"], "PROJECT.md"),
            "CURRENT_TASK.md": read_project_file(envelope["project_id"], "CURRENT_TASK.md"),
            f"management/tasks/{envelope['task_id']}.md": read_project_file(
                envelope["project_id"],
                f"management/tasks/{envelope['task_id']}.md",
            ),
            f"management/architecture/{envelope['task_id']}.md": read_project_file(
                envelope["project_id"],
                f"management/architecture/{envelope['task_id']}.md",
            ),
        }
        context_dir = run_dir / "context"
        for index, (relative_path, content) in enumerate(inputs.items(), start=1):
            write_text(context_dir / f"{index:02d}-{relative_path.replace('/', '_')}", content)

        required_outputs = extract_required_outputs(inputs[f"management/tasks/{envelope['task_id']}.md"])
        if not required_outputs:
            required_outputs = extract_required_outputs(inputs["PROJECT.md"])
        required_outputs = required_outputs or ["README.md", "src/main.py", "tests/test_main.py"]

        artifact_checks = [
            (path, *verify_project_artifact(envelope["project_id"], path))
            for path in required_outputs
        ]
        test_command = choose_test_command(required_outputs)
        exec_cmd = [
            "bash",
            str(live_bin_root() / "project_exec.sh"),
            envelope["project_id"],
            "oracle",
            *test_command,
        ]
        print('PROJECT_EXEC=' + " ".join(exec_cmd[:2]) + f' "{envelope["project_id"]}" oracle ' + " ".join(test_command))
        exec_result = run_command(exec_cmd, timeout=300)

        verdict = "PASS" if exec_result.returncode == 0 and all(ok for _, ok, _ in artifact_checks) else "FAIL"
        report_text = build_report(
            task_id=envelope["task_id"],
            verdict=verdict,
            test_command=test_command,
            exec_result=exec_result,
            artifact_checks=artifact_checks,
        )
        draft_file = run_dir / "drafts" / f"{envelope['task_id']}_REPORT.md"
        write_text(draft_file, report_text if report_text.endswith("\n") else report_text + "\n")

        output_path = f"management/validation/{envelope['task_id']}_REPORT.md"
        write_result = run_command(
            [
                "bash",
                str(live_bin_root() / "project_write.sh"),
                envelope["project_id"],
                output_path,
                "--source-file",
                str(draft_file),
                "--action",
                "oracle_runtime_report_import",
            ],
            timeout=120,
        )
        require_ok(write_result, action="project_write validation report")

        verify_report_cmd = [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            envelope["project_id"],
            "VERIFY",
            output_path,
            "--action",
            "oracle-runtime-report-check",
            "--contains",
            envelope["task_id"],
            "--contains",
            verdict,
        ]
        verify_report_result = run_command(verify_report_cmd, timeout=120)
        require_ok(verify_report_result, action="verify_artifact validation report")

        evidence = f"{' '.join(test_command)} exit={exec_result.returncode}; report={output_path}."
        send_response = send_niaobe_result(
            envelope["project_id"],
            envelope["task_id"],
            verdict=verdict,
            evidence=evidence,
        )
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "project_id": envelope["project_id"],
            "task_id": envelope["task_id"],
            "verdict": verdict,
            "report": output_path,
            "test_command": test_command,
            "response": send_response,
        }
        write_json(run_dir / "result.json", result_payload)
        state.update(
            {
                "status": "sent",
                "sent_at": result_payload["sent_at"],
                "verdict": verdict,
                "report": output_path,
                "test_command": test_command,
                "result_payload": result_payload,
                "last_send_response": send_response,
                "last_error": None,
            }
        )
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "verify", f"oracle verification sent {verdict}")
        print(f"ORACLE_VERDICT={verdict}: {evidence}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return state
    except WorkerRuntimeError as exc:
        state.update({"status": "failed", "last_error": {"code": exc.code, "message": str(exc)}})
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "verify", f"oracle verification failed: {exc}")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oracle_run_task")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("envelope_json")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            verify_task(args.envelope_json)
            return 0
    except WorkerRuntimeError as exc:
        print(f"ORACLE_RUNTIME_FAILED: {exc}")
        return 20
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
