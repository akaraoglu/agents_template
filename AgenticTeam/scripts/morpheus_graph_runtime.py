#!/usr/bin/env python3
"""LangGraph-backed Morpheus artifact completion runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError as exc:  # pragma: no cover - exercised only when optional dep is missing.
    raise RuntimeError("langgraph is required when MORPHEUS_RUNTIME_ENGINE=langgraph") from exc

from worker_contracts import ArtifactWorkerContract
from worker_runtime import (
    WorkerRuntimeError,
    append_log,
    build_artifact_result_payload,
    iso_now,
    live_bin_root,
    load_artifact_manifest,
    load_state,
    require_ok,
    run_command,
    send_blocked_from_state,
    send_session_message,
    summarize_test_output,
    update_state,
    write_json,
)


class MorpheusGraphState(TypedDict, total=False):
    run_dir: str
    project_id: str
    task_id: str
    attempt: int
    artifacts: list[str]
    test_command: list[str]
    draft_files: dict[str, str]
    test_summary: str
    project_exec: str
    verdict: Literal["done", "repair", "blocked"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_test_artifact(path: str) -> bool:
    artifact = Path(path)
    return artifact.parts[:1] == ("tests",) or artifact.name.startswith("test_")


def test_artifact_hashes(draft_dir: Path, artifacts: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for artifact in artifacts:
        if not is_test_artifact(artifact):
            continue
        draft_file = draft_dir / artifact
        if draft_file.is_file():
            hashes[artifact] = sha256_file(draft_file)
    return hashes


def artifact_hashes(draft_dir: Path, artifacts: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for artifact in artifacts:
        draft_file = draft_dir / artifact
        if draft_file.is_file():
            hashes[artifact] = sha256_file(draft_file)
    return hashes


def implementation_repair_paths(artifacts: list[str]) -> list[str]:
    src_paths = [path for path in artifacts if Path(path).parts[:1] == ("src",) and not is_test_artifact(path)]
    if src_paths:
        return src_paths
    return [
        path
        for path in artifacts
        if not is_test_artifact(path)
        and Path(path).name.lower() not in {"readme.md", "readme.txt"}
        and Path(path).suffix.lower() not in {".md", ".rst", ".txt"}
    ]


def changed_test_artifacts(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for path, old_hash in previous.items():
        if current.get(path) != old_hash:
            changed.append(path)
    for path in current:
        if path not in previous:
            changed.append(path)
    return sorted(set(changed))


def changed_artifacts(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for path, old_hash in previous.items():
        if current.get(path) != old_hash:
            changed.append(path)
    for path in current:
        if path not in previous:
            changed.append(path)
    return sorted(set(changed))


def ensure_artifact_drafts_for_graph(state: dict[str, Any], artifacts: list[str]) -> dict[str, str]:
    draft_dir = Path(state["draft_dir"])
    prepared_epoch = float(state.get("prepared_epoch", 0.0))
    draft_files: dict[str, str] = {}
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
        draft_files[artifact] = str(draft_file)
    return draft_files


def build_graph(contract: ArtifactWorkerContract):
    graph = StateGraph(MorpheusGraphState)

    def validate_manifest(graph_state: MorpheusGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = load_state(run_dir)
        artifacts, test_command = load_artifact_manifest(state)
        draft_files = ensure_artifact_drafts_for_graph(state, artifacts)
        current_artifact_hashes = artifact_hashes(Path(state["draft_dir"]), artifacts)
        current_test_hashes = test_artifact_hashes(Path(state["draft_dir"]), artifacts)
        repair_guard = state.get("repair_guard") if isinstance(state.get("repair_guard"), dict) else {}
        repair_context = state.get("repair_context") if isinstance(state.get("repair_context"), dict) else {}
        previous_test_hashes = repair_guard.get("test_hashes") if isinstance(repair_guard, dict) else None
        previous_artifact_hashes = repair_guard.get("artifact_hashes") if isinstance(repair_guard, dict) else None
        allowed_repair_paths = repair_guard.get("allowed_repair_paths") if isinstance(repair_guard, dict) else None
        if repair_context.get("status") == "repair_needed" and repair_context.get("error_code") == "test_failed":
            if isinstance(previous_test_hashes, dict):
                changed_tests = changed_test_artifacts(previous_test_hashes, current_test_hashes)
                if changed_tests:
                    raise WorkerRuntimeError(
                        "test artifacts changed after test_failed repair request: " + ", ".join(changed_tests),
                        code="test_weakening_detected",
                    )
            if isinstance(previous_artifact_hashes, dict) and isinstance(allowed_repair_paths, list):
                changed = changed_artifacts(previous_artifact_hashes, current_artifact_hashes)
                allowed = {str(path) for path in allowed_repair_paths}
                forbidden = [path for path in changed if path not in allowed]
                if forbidden:
                    raise WorkerRuntimeError(
                        "forbidden artifact changed during implementation-only repair: " + ", ".join(forbidden),
                        code="forbidden_repair_edit",
                    )
        update_state(
            run_dir,
            artifacts=artifacts,
            test_command=test_command,
            current_artifact_hashes=current_artifact_hashes,
            current_test_artifact_hashes=current_test_hashes,
        )
        return {"artifacts": artifacts, "test_command": test_command, "draft_files": draft_files}

    def import_artifacts(graph_state: MorpheusGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = load_state(run_dir)
        created_dirs: set[str] = set()
        for artifact in graph_state["artifacts"]:
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
                    f"{contract.role}_graph_runtime_mkdir",
                ],
                timeout=120,
            )
            require_ok(mkdir_result, action=f"project_mkdir {output_parent}")
            created_dirs.add(output_parent)

        for artifact, draft_path in graph_state["draft_files"].items():
            write_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "project_write.sh"),
                    str(state["project_id"]),
                    artifact,
                    "--source-file",
                    draft_path,
                    "--action",
                    f"{contract.role}_graph_runtime_import",
                ],
                timeout=120,
            )
            require_ok(write_result, action=f"project_write {artifact}")
        return {}

    def verify_artifacts(graph_state: MorpheusGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = load_state(run_dir)
        for artifact in graph_state["artifacts"]:
            verify_result = run_command(
                [
                    "bash",
                    str(live_bin_root() / "verify_artifact.sh"),
                    str(state["project_id"]),
                    contract.phase,
                    artifact,
                    "--action",
                    f"{contract.role}_graph_runtime_verify",
                ],
                timeout=120,
            )
            require_ok(verify_result, action=f"verify_artifact {artifact}")
        return {}

    def run_tests(graph_state: MorpheusGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = load_state(run_dir)
        exec_cmd = [
            "bash",
            str(live_bin_root() / "project_exec.sh"),
            str(state["project_id"]),
            contract.project_exec_role,
            *graph_state["test_command"],
        ]
        print("PROJECT_EXEC=" + " ".join(exec_cmd))
        exec_result = run_command(exec_cmd, timeout=300)
        exec_output = require_ok(exec_result, action="project_exec")
        return {
            "project_exec": " ".join(exec_cmd),
            "test_summary": summarize_test_output(exec_output),
        }

    def send_done(graph_state: MorpheusGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = load_state(run_dir)
        payload = build_artifact_result_payload(
            contract,
            state,
            instructions=contract.done_message(
                artifacts=graph_state["artifacts"],
                test_command=graph_state["test_command"],
                test_summary=graph_state["test_summary"],
            ),
        )
        response = send_session_message(contract.session_key, json.dumps(payload, separators=(",", ":")))
        result_payload = {
            "status": "sent",
            "sent_at": iso_now(),
            "payload": payload,
            "response": response,
            "engine": "langgraph",
        }
        write_json(run_dir / "result.json", result_payload)
        update_state(
            run_dir,
            status="sent",
            sent_at=result_payload["sent_at"],
            artifacts=graph_state["artifacts"],
            test_command=graph_state["test_command"],
            test_summary=graph_state["test_summary"],
            project_exec=graph_state["project_exec"],
            result_payload=payload,
            last_send_response=response,
            last_error=None,
            runtime_engine="langgraph",
        )
        append_log(run_dir, "complete", f"langgraph complete succeeded; sent DONE for {', '.join(graph_state['artifacts'])}")
        print(f"RESULT_FILE={run_dir / 'result.json'}")
        return {"verdict": "done"}

    graph.add_node("validate_manifest", validate_manifest)
    graph.add_node("import_artifacts", import_artifacts)
    graph.add_node("verify_artifacts", verify_artifacts)
    graph.add_node("run_tests", run_tests)
    graph.add_node("send_done", send_done)
    graph.set_entry_point("validate_manifest")
    graph.add_edge("validate_manifest", "import_artifacts")
    graph.add_edge("import_artifacts", "verify_artifacts")
    graph.add_edge("verify_artifacts", "run_tests")
    graph.add_edge("run_tests", "send_done")
    graph.add_edge("send_done", END)
    return graph.compile()


def complete_artifact_run_graph(contract: ArtifactWorkerContract, run_dir: Path) -> dict[str, Any]:
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
    previous_status = status
    previous_error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    state = update_state(
        run_dir,
        status="verifying",
        completion_attempts=attempt,
        runtime_engine="langgraph",
        repair_context={
            "status": previous_status,
            "error_code": previous_error.get("code"),
        },
        last_error=None,
    )
    append_log(run_dir, "complete", "langgraph artifact complete started")

    try:
        graph = build_graph(contract)
        graph.invoke(
            {
                "run_dir": str(run_dir),
                "project_id": str(state["project_id"]),
                "task_id": str(state["task_id"]),
                "attempt": attempt,
            }
        )
        return load_state(run_dir)
    except WorkerRuntimeError as exc:
        append_log(run_dir, "complete", f"langgraph artifact complete failed: {exc}")
        failure_code = "test_failed" if exc.code == "helper_failed" and "project_exec" in str(exc) else exc.code
        latest_state = load_state(run_dir)
        if failure_code in {"missing_draft", "verification_failed", "test_failed"} and attempt == 1:
            allowed_repair_paths = (
                implementation_repair_paths(latest_state.get("artifacts", []))
                if failure_code == "test_failed"
                else latest_state.get("artifacts", [])
            )
            update_state(
                run_dir,
                status="repair_needed",
                repair_guard={
                    "reason": failure_code,
                    "allowed_repair_paths": allowed_repair_paths,
                    "artifact_hashes": latest_state.get("current_artifact_hashes", {}),
                    "test_hashes": latest_state.get("current_test_artifact_hashes", {}),
                },
                last_error={"code": failure_code, "message": str(exc)},
            )
            print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{failure_code}]: {exc}")
            if failure_code == "test_failed":
                print("REPAIR_POLICY=Implementation-only repair. Do not edit tests, docs, or manifest after a test failure.")
                print("ALLOWED_REPAIR_PATHS=" + ", ".join(allowed_repair_paths))
                print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} repair \"{run_dir}\"")
            else:
                print(f"NEXT_REQUIRED=bash {live_bin_root() / (contract.role + '_run_task.sh')} complete \"{run_dir}\"")
            raise
        try:
            send_blocked_from_state(contract, run_dir, latest_state, code=failure_code, reason=str(exc))
        except WorkerRuntimeError as send_exc:
            update_state(run_dir, status="send_failed", last_error={"code": send_exc.code, "message": str(send_exc)})
            append_log(run_dir, "complete", f"langgraph BLOCKED send failed: {send_exc}")
            raise send_exc
        raise


def print_repair_brief(contract: ArtifactWorkerContract, run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    if state.get("role") != contract.role:
        raise WorkerRuntimeError(f"run_dir belongs to {state.get('role')}, not {contract.role}", code="wrong_role")
    if state.get("status") != "repair_needed":
        raise WorkerRuntimeError(f"run is not waiting for repair: status={state.get('status')}", code="wrong_state")

    repair_guard = state.get("repair_guard") if isinstance(state.get("repair_guard"), dict) else {}
    allowed = [str(path) for path in repair_guard.get("allowed_repair_paths", []) if str(path).strip()]
    last_error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    error_message = str(last_error.get("message", "no error detail"))

    print(f"RUN_DIR={run_dir}")
    print(f"DRAFT_WRITE_ROOT={state['draft_write_root']}")
    print(f"MANIFEST_WRITE_FILE={state['manifest_write_file']}")
    print("REPAIR_MODE=implementation_only")
    print("ALLOWED_REPAIR_PATHS=" + ", ".join(allowed))
    forbidden = [
        path
        for path in state.get("artifacts", [])
        if path not in allowed
    ]
    if forbidden:
        print("FORBIDDEN_REPAIR_PATHS=" + ", ".join(forbidden))
    print("REPAIR_REASON=" + str(last_error.get("code", repair_guard.get("reason", "unknown"))))
    print("REPAIR_EVIDENCE_BEGIN")
    print(error_message[:4000])
    print("REPAIR_EVIDENCE_END")
    print("NEXT_REQUIRED=bash " + str(live_bin_root() / (contract.role + "_run_task.sh")) + f' complete "{run_dir}"')
    append_log(run_dir, "repair", "repair brief printed")
    return state
