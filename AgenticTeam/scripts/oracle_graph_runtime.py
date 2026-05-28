#!/usr/bin/env python3
"""LangGraph-backed Oracle verification runtime."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing.
    raise RuntimeError("langgraph is required for Oracle runtime") from exc

from oracle_run_task import (
    build_report,
    build_run_dir,
    choose_test_command,
    iso_now,
    parse_verify_envelope,
    read_project_file,
    send_niaobe_result,
    verify_project_artifact,
)
from worker_runtime import (
    RUN_DEADLINE_SECONDS,
    WorkerRuntimeError,
    append_log,
    command_details,
    extract_required_outputs,
    live_bin_root,
    require_ok,
    resolve_project,
    run_command,
    write_json,
    write_text,
)


class OracleGraphState(TypedDict, total=False):
    run_dir: str
    project_id: str
    project_path: str
    task_id: str
    envelope: dict[str, str]
    inputs: dict[str, str]
    required_outputs: list[str]
    artifact_checks: list[tuple[str, bool, str]]
    test_command: list[str]
    exec_returncode: int
    exec_output: str
    project_exec: str
    verdict: str
    report_path: str


def build_graph():
    graph = StateGraph(OracleGraphState)

    def collect_inputs(state: OracleGraphState) -> dict[str, Any]:
        run_dir = Path(state["run_dir"])
        project_id = state["project_id"]
        task_id = state["task_id"]
        inputs = {
            "PROJECT.md": read_project_file(project_id, "PROJECT.md"),
            "CURRENT_TASK.md": read_project_file(project_id, "CURRENT_TASK.md"),
            f"management/tasks/{task_id}.md": read_project_file(project_id, f"management/tasks/{task_id}.md"),
            f"management/architecture/{task_id}.md": read_project_file(project_id, f"management/architecture/{task_id}.md"),
        }
        context_dir = run_dir / "context"
        for index, (relative_path, content) in enumerate(inputs.items(), start=1):
            write_text(context_dir / f"{index:02d}-{relative_path.replace('/', '_')}", content)

        required_outputs = extract_required_outputs(inputs[f"management/tasks/{task_id}.md"])
        if not required_outputs:
            required_outputs = extract_required_outputs(inputs["PROJECT.md"])
        required_outputs = required_outputs or ["README.md", "src/main.py", "tests/test_main.py"]
        write_json(
            run_dir / "state.json",
            {
                **json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
                "status": "inputs_collected",
                "required_outputs": required_outputs,
            },
        )
        return {"inputs": inputs, "required_outputs": required_outputs}

    def verify_artifacts(state: OracleGraphState) -> dict[str, Any]:
        checks = [(path, *verify_project_artifact(state["project_id"], path)) for path in state["required_outputs"]]
        return {"artifact_checks": checks}

    def run_validation(state: OracleGraphState) -> dict[str, Any]:
        test_command = choose_test_command(state["required_outputs"])
        exec_cmd = [
            "bash",
            str(live_bin_root() / "project_exec.sh"),
            state["project_id"],
            "oracle",
            *test_command,
        ]
        print("PROJECT_EXEC=" + " ".join(exec_cmd[:2]) + f' "{state["project_id"]}" oracle ' + " ".join(test_command))
        exec_result = run_command(exec_cmd, timeout=300)
        run_dir = Path(state["run_dir"])
        current = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        current.update(
            {
                "project_exec": " ".join(exec_cmd),
                "test_command": test_command,
                "exec_returncode": exec_result.returncode,
            }
        )
        write_json(run_dir / "state.json", current)
        return {
            "test_command": test_command,
            "exec_returncode": exec_result.returncode,
            "exec_output": command_details(exec_result),
            "project_exec": " ".join(exec_cmd),
        }

    def write_validation_report(state: OracleGraphState) -> dict[str, Any]:
        run_dir = Path(state["run_dir"])
        task_id = state["task_id"]
        verdict = "PASS" if state["exec_returncode"] == 0 and all(ok for _, ok, _ in state["artifact_checks"]) else "FAIL"
        exec_result = SimpleNamespace(returncode=state["exec_returncode"], stdout=state["exec_output"], stderr="")
        report_text = build_report(
            task_id=task_id,
            verdict=verdict,
            test_command=state["test_command"],
            exec_result=exec_result,
            artifact_checks=state["artifact_checks"],
        )
        draft_file = run_dir / "drafts" / f"{task_id}_REPORT.md"
        write_text(draft_file, report_text if report_text.endswith("\n") else report_text + "\n")

        output_path = f"management/validation/{task_id}_REPORT.md"
        write_result = run_command(
            [
                "bash",
                str(live_bin_root() / "project_write.sh"),
                state["project_id"],
                output_path,
                "--source-file",
                str(draft_file),
                "--action",
                "oracle_graph_runtime_report_import",
            ],
            timeout=120,
        )
        require_ok(write_result, action="project_write validation report")

        verify_report_cmd = [
            "bash",
            str(live_bin_root() / "verify_artifact.sh"),
            state["project_id"],
            "VERIFY",
            output_path,
            "--action",
            "oracle-graph-runtime-report-check",
            "--contains",
            task_id,
            "--contains",
            verdict,
            "--contains",
            "Test command",
        ]
        verify_report_result = run_command(verify_report_cmd, timeout=120)
        require_ok(verify_report_result, action="verify_artifact validation report")
        return {"verdict": verdict, "report_path": output_path}

    def send_result(state: OracleGraphState) -> dict[str, Any]:
        run_dir = Path(state["run_dir"])
        evidence = f"{' '.join(state['test_command'])} exit={state['exec_returncode']}; report={state['report_path']}."
        send_response = send_niaobe_result(
            state["project_id"],
            state["task_id"],
            verdict=state["verdict"],
            evidence=evidence,
        )
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "project_id": state["project_id"],
            "task_id": state["task_id"],
            "verdict": state["verdict"],
            "report": state["report_path"],
            "test_command": state["test_command"],
            "response": send_response,
            "engine": "langgraph",
        }
        write_json(run_dir / "result.json", result_payload)
        current = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        current.update(
            {
                "status": "sent",
                "sent_at": result_payload["sent_at"],
                "verdict": state["verdict"],
                "report": state["report_path"],
                "test_command": state["test_command"],
                "project_exec": state["project_exec"],
                "result_payload": result_payload,
                "last_send_response": send_response,
                "last_error": None,
                "runtime_engine": "langgraph",
            }
        )
        write_json(run_dir / "state.json", current)
        append_log(run_dir, "verify", f"oracle graph verification sent {state['verdict']}")
        print(f"ORACLE_VERDICT={state['verdict']}: {evidence}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return {}

    graph.add_node("collect_inputs", collect_inputs)
    graph.add_node("verify_artifacts", verify_artifacts)
    graph.add_node("run_validation", run_validation)
    graph.add_node("write_validation_report", write_validation_report)
    graph.add_node("send_result", send_result)
    graph.set_entry_point("collect_inputs")
    graph.add_edge("collect_inputs", "verify_artifacts")
    graph.add_edge("verify_artifacts", "run_validation")
    graph.add_edge("run_validation", "write_validation_report")
    graph.add_edge("write_validation_report", "send_result")
    graph.add_edge("send_result", END)
    return graph.compile()


def verify_task_graph(envelope_raw: str) -> dict[str, Any]:
    envelope = parse_verify_envelope(envelope_raw)
    resolved = resolve_project(envelope["project_id"])
    run_dir = build_run_dir(envelope["project_id"], envelope["task_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "envelope.json", envelope)
    state: dict[str, Any] = {
        "role": "oracle",
        "phase": "VERIFY",
        "status": "verifying",
        "runtime_engine": "langgraph",
        "completion_attempts": 1,
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
    append_log(run_dir, "verify", f"oracle graph verification started for {envelope['project_id']} {envelope['task_id']}")

    try:
        build_graph().invoke(
            {
                "run_dir": str(run_dir),
                "project_id": envelope["project_id"],
                "project_path": str(resolved["project_path"]),
                "task_id": envelope["task_id"],
                "envelope": envelope,
            }
        )
        return json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    except WorkerRuntimeError as exc:
        state.update({"status": "failed", "last_error": {"code": exc.code, "message": str(exc)}})
        write_json(run_dir / "state.json", state)
        append_log(run_dir, "verify", f"oracle graph verification failed: {exc}")
        raise
