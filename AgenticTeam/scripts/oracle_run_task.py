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

from covenant_contracts import validate_work_result
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


def build_niaobe_result_payload(
    project_id: str,
    task_id: str,
    *,
    verdict: str,
    evidence: str,
    test_command: list[str],
    report_path: str,
    exec_returncode: int,
    workspace_root: str,
) -> str:
    status = "DONE" if verdict.upper() == "PASS" else "FAILED"
    work_result = validate_work_result(
        {
            "project_id": project_id,
            "task_id": task_id,
            "from": "oracle",
            "phase": "VERIFY",
            "status": status,
            "summary": evidence,
            "reason": None if status == "DONE" else f"Oracle verification verdict={verdict}, exit={exec_returncode}.",
            "next_action": None if status == "DONE" else "Inspect validation report and repair failing implementation.",
            "verification": {
                "task_id": task_id,
                "agent": "oracle",
                "timestamp": iso_now(),
                "performed": True,
                "command": test_command,
                "status": "pass" if status == "DONE" else "pass",
                "summary": evidence,
                "evidence_paths": [report_path],
            }
            if status == "DONE"
            else None,
        }
    ).to_dict()
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "from": "oracle",
        "to": "niaobe",
        "phase": "VERIFY",
        "instructions": f"{verdict}: task verification complete. Evidence: {evidence}",
        "work_result": work_result,
        "project_workspace": {
            "workspace_root": workspace_root,
            "allowed_write_paths": [report_path],
            "expected_artifacts": [report_path],
            "approved_runtime_evidence_roots": [],
        },
        "artifact_manifest": {
            "created": [report_path],
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": [report_path],
            "evidence_paths": [report_path],
        },
    }
    return payload


def verify_task(envelope_raw: str) -> dict[str, Any]:
    from oracle_graph_runtime import verify_task_graph

    return verify_task_graph(envelope_raw)


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
