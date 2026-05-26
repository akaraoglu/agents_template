#!/usr/bin/env python3
"""Phase-level OpenClaw canaries."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from canaries.common import (
    CanaryError,
    add_invariant,
    build_delivery_evidence,
    build_preflight,
    create_project,
    detect_sync_drift,
    finalize_summary,
    gateway_is_listening,
    handoff_exists,
    latest_handoff_event,
    latest_session_state,
    load_handoff_events,
    load_latest_worker_state,
    poll_until,
    parse_envelope,
    project_file_exists,
    project_file_text,
    run,
    send_envelope_to_agent,
    session_delta,
    session_freshness,
    session_snapshot,
    state_path,
    state_summary,
    token_from_paths,
    wait_for_session_quiescence,
    write_project_file,
    write_state,
    CLAWSPACE_ROOT,
    REPO_ROOT,
    WORKSPACES_ROOT,
    AGENTICTEAM_ROOT,
)
from canaries.fixtures import (
    architecture_t001_markdown_counter,
    current_task_t001,
    seeded_main_py,
    seeded_readme,
    seeded_test_main_py,
    smith_backlog_draft,
    smith_plan_draft,
    task_t001_markdown_counter,
)

FIBONACCI_PLAN_STRINGS = (
    "## Overview",
    "## Phases",
    "T001: Core Fibonacci Logic & Tree Generation Engine",
    "T002: ASCII/Unicode Rendering Engine",
    "T003: CLI Interface & Parameter Implementation",
    "T004: Testing & Final Verification",
)
FIBONACCI_TASK_FILES = (
    "management/tasks/T001.md",
    "management/tasks/T002.md",
    "management/tasks/T003.md",
    "management/tasks/T004.md",
)


def project_token(project_dir: Path, extra_paths: list[str], *, agent: str | None = None) -> str:
    paths = [state_path(project_dir), project_dir / ".openclaw" / "handoffs.jsonl"]
    paths.extend(project_dir / relative for relative in extra_paths)
    token = token_from_paths(paths)
    if agent:
        snapshot = session_snapshot(agent)
        if snapshot:
            token = f"{token}|session:{snapshot.updated_at}:{snapshot.status}"
    return token


def parse_runtime_value(output: str, key: str) -> str:
    prefix = f"{key}="
    for raw in output.splitlines():
        if raw.startswith(prefix):
            return raw.split(prefix, 1)[1].strip()
    raise CanaryError(f"runtime output did not contain {key}=:\n{output}")


def direct_handoff_output(from_agent: str, to_agent: str, project_id: str, instructions: str, phase: str, task_id: str) -> str:
    return run(
        [
            "bash",
            str(CLAWSPACE_ROOT / "bin" / "handoff.sh"),
            from_agent,
            to_agent,
            project_id,
            instructions,
            phase,
            task_id,
        ],
        timeout=120,
        cwd=REPO_ROOT,
    )


def seed_task_inputs(
    project_dir: Path,
    *,
    task_text: str,
    current_task_text: str,
    architecture_text: str | None = None,
    readme_text: str | None = None,
    main_py_text: str | None = None,
    test_py_text: str | None = None,
) -> None:
    write_project_file(project_dir, "management/tasks/T001.md", task_text)
    write_project_file(project_dir, "CURRENT_TASK.md", current_task_text)
    if architecture_text is not None:
        write_project_file(project_dir, "management/architecture/T001.md", architecture_text)
    if readme_text is not None:
        write_project_file(project_dir, "README.md", readme_text)
    if main_py_text is not None:
        write_project_file(project_dir, "src/main.py", main_py_text)
    if test_py_text is not None:
        write_project_file(project_dir, "tests/test_main.py", test_py_text)


def preflight_target_session(agent: str, checked: list[dict[str, Any]], preflight: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    drain = wait_for_session_quiescence(agent)
    preflight["target_session_before_start"] = drain
    clean = drain["outcome"] == "already_quiescent"
    add_invariant(
        checked,
        "preflight:target_session_quiescent",
        clean,
        f"{agent} drain outcome={drain['outcome']}, line_count_delta={drain['line_count_delta']}, session_id_changed={drain['session_id_changed']}",
    )
    return clean, drain


def postrun_target_session(agent: str, checked: list[dict[str, Any]]) -> dict[str, Any]:
    drain = wait_for_session_quiescence(agent)
    add_invariant(
        checked,
        "postrun:target_session_drained",
        drain["outcome"] in {"no_session", "already_quiescent", "drained"},
        f"{agent} drain outcome={drain['outcome']}, line_count_delta={drain['line_count_delta']}, session_id_changed={drain['session_id_changed']}",
    )
    return drain


def neo_project_create(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    del timeout_seconds, stall_seconds
    project_id, project_dir = create_project("canary_neo_project_create", "minimal_python_cli.md")
    contract = {
        "starting_state": "Fresh scaffold created through new_project.sh with a fixed minimal Python CLI fixture.",
        "allowed_agents": [],
        "expected_files": [
            "PROJECT.md",
            "PROJECT_STATE.md",
            "CURRENT_TASK.md",
            "RESULT.md",
            "management/PLAN.md",
            "management/BACKLOG.md",
            "CONTEXT.json",
        ],
        "expected_state_fields": {"owner": "smith", "phase": "PLANNING", "waiting_for": "none"},
        "expected_handoffs": [],
        "expected_terminal_state": "scaffold_ready",
        "failure_timeout_seconds": 0,
        "stall_timeout_seconds": 0,
    }
    checked: list[dict[str, Any]] = []
    final_state = state_summary(project_dir)
    sync = detect_sync_drift(["neo", "smith"])
    preflight = build_preflight(
        gateway_required=False,
        sync_drift=sync["sync_drift"],
        session_freshness_value="unknown",
        mattermost_needed=False,
    )
    for relative_path in contract["expected_files"]:
        add_invariant(
            checked,
            f"file:{relative_path}",
            project_file_exists(project_dir, relative_path),
            f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}",
        )
    add_invariant(checked, "state:owner", final_state["owner"] == "smith", f"owner={final_state['owner']}")
    add_invariant(checked, "state:phase", final_state["phase"] == "PLANNING", f"phase={final_state['phase']}")
    add_invariant(checked, "state:waiting_for", final_state["waiting_for"] == "none", f"waiting_for={final_state['waiting_for']}")
    registry = json.loads((CLAWSPACE_ROOT / "projects" / "registry.json").read_text(encoding="utf-8"))
    add_invariant(
        checked,
        "registry:project",
        project_id in (registry.get("projects") or {}),
        "registry contains created project" if project_id in (registry.get("projects") or {}) else "registry is missing created project",
    )
    return finalize_summary(
        canary="neo_project_create",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=None,
        latest_worker_state=None,
        sync_drift=sync["sync_drift"],
        session_freshness_value="unknown",
        preflight=preflight,
    )


def smith_planning(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or 300
    stall_seconds = stall_seconds or 60
    project_id, project_dir = create_project("canary_smith_planning", "fibonacci_tree_visualizer.md")
    contract = {
        "starting_state": "Fresh Fibonacci project with a Neo->Smith HANDOFF.",
        "allowed_agents": ["neo", "smith"],
        "expected_files": ["management/PLAN.md", "management/BACKLOG.md", *FIBONACCI_TASK_FILES, "CURRENT_TASK.md"],
        "expected_state_fields": {
            "owner": "smith",
            "phase": "PLANNING",
            "waiting_for": "niaobe",
            "active_task": "T001",
            "task_phase": "TASK_HANDOFF",
            "task_status": "READY",
        },
        "expected_handoffs": [
            {"event_type": "handoff_sent", "from": "neo", "to": "smith", "phase": "HANDOFF"},
            {"event_type": "handoff_received", "from": "neo", "to": "smith", "phase": "HANDOFF"},
            {"event_type": "handoff_sent", "from": "smith", "to": "niaobe", "phase": "TASK_HANDOFF", "task_id": "T001"},
        ],
        "expected_terminal_state": "smith_task_ready",
        "failure_timeout_seconds": timeout_seconds,
        "stall_timeout_seconds": stall_seconds,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["smith"])
    freshness = session_freshness("smith")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    if not gateway_is_listening():
        add_invariant(checked, "gateway:listening", False, "OpenClaw gateway is not listening on 127.0.0.1:18789.")
        return finalize_summary(
            canary="smith_planning",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("smith"),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(None, expected_project_id=project_id),
        )
    ready, _ = preflight_target_session("smith", checked, preflight)
    smith_before = session_snapshot("smith")
    if not ready:
        return finalize_summary(
            canary="smith_planning",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("smith", smith_before),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(smith_before, expected_project_id=project_id),
        )
    handoff_output = direct_handoff_output(
        "neo",
        "smith",
        project_id,
        "Read PROJECT.md and create the required deterministic 4-task sequential plan.",
        "HANDOFF",
        "",
    )
    envelope = next(line.split("ENVELOPE: ", 1)[1] for line in handoff_output.splitlines() if line.startswith("ENVELOPE: "))
    send_response = send_envelope_to_agent("smith", envelope)

    def snapshot() -> dict[str, Any]:
        events = load_handoff_events(project_dir)
        state = state_summary(project_dir)
        worker_state = load_latest_worker_state(project_id, "smith")
        worker_token = ""
        if worker_state and worker_state.get("state_file"):
            path = Path(str(worker_state["state_file"]))
            if path.exists():
                stat = path.stat()
                worker_token = f"|worker:{int(stat.st_mtime)}:{stat.st_size}:{worker_state.get('status', 'unknown')}"
        return {
            "token": project_token(project_dir, contract["expected_files"], agent="smith") + worker_token,
            "events": events,
            "state": state,
            "worker_state": worker_state,
        }

    status, current = poll_until(
        snapshot,
        lambda snap: handoff_exists(
            snap["events"],
            event_type="handoff_sent",
            from_agent="smith",
            to_agent="niaobe",
            phase="TASK_HANDOFF",
            task_id="T001",
        )
        and (snap.get("worker_state") or {}).get("status") == "sent",
        timeout_seconds=timeout_seconds,
        stall_seconds=stall_seconds,
        poll_seconds=5,
    )
    final_state = current.get("state", state_summary(project_dir))
    events = current.get("events", load_handoff_events(project_dir))
    worker_state = current.get("worker_state") or load_latest_worker_state(project_id, "smith")
    session_detail = session_delta(smith_before, expected_project_id=project_id)
    for relative_path in contract["expected_files"]:
        add_invariant(checked, f"file:{relative_path}", project_file_exists(project_dir, relative_path), f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}")
    plan_text = project_file_text(project_dir, "management/PLAN.md") if project_file_exists(project_dir, "management/PLAN.md") else ""
    for token in FIBONACCI_PLAN_STRINGS:
        add_invariant(
            checked,
            f"plan:{token}",
            token in plan_text,
            f"management/PLAN.md contains {token}" if token in plan_text else f"management/PLAN.md is missing {token}",
        )
    current_task_points_to_t001 = project_file_exists(project_dir, "CURRENT_TASK.md") and "T001" in project_file_text(project_dir, "CURRENT_TASK.md")
    add_invariant(checked, "current_task:T001", current_task_points_to_t001, "CURRENT_TASK.md points to T001" if current_task_points_to_t001 else "CURRENT_TASK.md does not point to T001")
    for forbidden in ("README.md", "src/main.py", "tests/test_main.py"):
        add_invariant(
            checked,
            f"forbidden:{forbidden}",
            not project_file_exists(project_dir, forbidden),
            f"{forbidden} not created during planning" if not project_file_exists(project_dir, forbidden) else f"{forbidden} should not exist during planning",
        )
    for field, expected in contract["expected_state_fields"].items():
        actual = final_state.get(field, "missing")
        add_invariant(checked, f"state:{field}", actual == expected, f"{field}={actual}")
    for item in contract["expected_handoffs"]:
        passed = handoff_exists(
            events,
            event_type=item["event_type"],
            from_agent=item["from"],
            to_agent=item["to"],
            phase=item["phase"],
            task_id=item.get("task_id"),
        )
        add_invariant(checked, f"handoff:{item['from']}->{item['to']}:{item['phase']}", passed, json.dumps(item, sort_keys=True))
    add_invariant(
        checked,
        "runtime:status",
        (worker_state or {}).get("status") == "sent",
        f"smith runtime status={(worker_state or {}).get('status', 'missing')}",
    )
    add_invariant(checked, "execution:terminal", status == "success", f"poll status={status}")
    drain = postrun_target_session("smith", checked)
    return finalize_summary(
        canary="smith_planning",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=events[-1] if events else None,
        latest_worker_state=worker_state or latest_session_state("smith", smith_before),
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence(send_response, session_detail),
        session_detail=session_detail,
        drain=drain,
    )


def smith_niaobe_handoff(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or 300
    stall_seconds = stall_seconds or 60
    project_id, project_dir = create_project("canary_smith_niaobe_handoff", "single_file_markdown_counter.md")
    contract = {
        "starting_state": "Fresh project with deterministic Smith planning drafts and Smith delegate helper invocation.",
        "allowed_agents": ["smith", "niaobe"],
        "expected_files": ["management/PLAN.md", "management/BACKLOG.md", "management/tasks/T001.md", "CURRENT_TASK.md"],
        "expected_state_fields": {"owner": "niaobe", "phase": "IN_PROGRESS", "waiting_for": "architect", "active_task": "T001", "task_phase": "DESIGN"},
        "expected_handoffs": [
            {"event_type": "handoff_sent", "from": "smith", "to": "niaobe", "phase": "TASK_HANDOFF", "task_id": "T001"},
            {"event_type": "handoff_received", "from": "smith", "to": "niaobe", "phase": "TASK_HANDOFF", "task_id": "T001"},
        ],
        "expected_terminal_state": "niaobe_received_task_handoff",
        "failure_timeout_seconds": timeout_seconds,
        "stall_timeout_seconds": stall_seconds,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["niaobe"])
    freshness = session_freshness("niaobe")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    if not gateway_is_listening():
        add_invariant(checked, "gateway:listening", False, "OpenClaw gateway is not listening on 127.0.0.1:18789.")
        return finalize_summary(
            canary="smith_niaobe_handoff",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("niaobe"),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(None, expected_project_id=project_id),
        )
    ready, _ = preflight_target_session("niaobe", checked, preflight)
    niaobe_before = session_snapshot("niaobe")
    if not ready:
        return finalize_summary(
            canary="smith_niaobe_handoff",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("niaobe", niaobe_before),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(niaobe_before, expected_project_id=project_id),
        )
    handoff_output = run(
        [
            "bash",
            str(CLAWSPACE_ROOT / "bin" / "handoff.sh"),
            "neo",
            "smith",
            project_id,
            "Create a full sequential plan and delegate only T001.",
            "HANDOFF",
        ],
        timeout=120,
        cwd=REPO_ROOT,
    )
    prepare_output = run(
        [
            "bash",
            str(CLAWSPACE_ROOT / "bin" / "smith_plan_project.sh"),
            "prepare",
            parse_envelope(handoff_output),
        ],
        timeout=120,
        cwd=REPO_ROOT,
    )
    run_dir = parse_runtime_value(prepare_output, "RUN_DIR")
    draft_dir = Path(parse_runtime_value(prepare_output, "DRAFT_DIR"))
    manifest_file = Path(parse_runtime_value(prepare_output, "MANIFEST_FILE"))
    (draft_dir / "management" / "PLAN.md").parent.mkdir(parents=True, exist_ok=True)
    (draft_dir / "management" / "tasks").mkdir(parents=True, exist_ok=True)
    (draft_dir / "management" / "PLAN.md").write_text(smith_plan_draft(), encoding="utf-8")
    (draft_dir / "management" / "BACKLOG.md").write_text(smith_backlog_draft(), encoding="utf-8")
    (draft_dir / "management" / "tasks" / "T001.md").write_text(task_t001_markdown_counter(), encoding="utf-8")
    (draft_dir / "CURRENT_TASK.md").write_text(current_task_t001(), encoding="utf-8")
    manifest_file.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"path": "management/PLAN.md"},
                    {"path": "management/BACKLOG.md"},
                    {"path": "management/tasks/T001.md"},
                    {"path": "CURRENT_TASK.md"},
                ],
                "active_task": "T001",
            }
        ),
        encoding="utf-8",
    )
    delegate_output = run(
        [
            "bash",
            str(CLAWSPACE_ROOT / "bin" / "smith_plan_project.sh"),
            "complete",
            run_dir,
        ],
        timeout=120,
        cwd=REPO_ROOT,
    )

    def snapshot() -> dict[str, Any]:
        events = load_handoff_events(project_dir)
        return {
            "token": project_token(project_dir, contract["expected_files"], agent="niaobe"),
            "events": events,
            "state": state_summary(project_dir),
            "worker_state": load_latest_worker_state(project_id, "smith"),
        }

    status, current = poll_until(
        snapshot,
        lambda snap: handoff_exists(
            snap["events"],
            event_type="handoff_received",
            from_agent="smith",
            to_agent="niaobe",
            phase="TASK_HANDOFF",
            task_id="T001",
        )
        and snap["state"].get("owner") == "niaobe"
        and snap["state"].get("task_phase") == "DESIGN"
        and snap["state"].get("waiting_for") == "architect"
        and (snap.get("worker_state") or {}).get("status") == "sent",
        timeout_seconds=timeout_seconds,
        stall_seconds=stall_seconds,
        poll_seconds=5,
    )
    events = current.get("events", load_handoff_events(project_dir))
    final_state = current.get("state", state_summary(project_dir))
    worker_state = current.get("worker_state") or load_latest_worker_state(project_id, "smith")
    session_detail = session_delta(niaobe_before, expected_project_id=project_id)
    for relative_path in contract["expected_files"]:
        add_invariant(checked, f"file:{relative_path}", project_file_exists(project_dir, relative_path), f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}")
    for field, expected in contract["expected_state_fields"].items():
        actual = final_state.get(field, "missing")
        add_invariant(checked, f"state:{field}", actual == expected, f"{field}={actual}")
    for item in contract["expected_handoffs"]:
        passed = handoff_exists(
            events,
            event_type=item["event_type"],
            from_agent=item["from"],
            to_agent=item["to"],
            phase=item["phase"],
            task_id=item.get("task_id"),
        )
        add_invariant(checked, f"handoff:{item['from']}->{item['to']}:{item['phase']}", passed, json.dumps(item, sort_keys=True))
    add_invariant(
        checked,
        "runtime:status",
        (worker_state or {}).get("status") == "sent",
        f"smith runtime status={(worker_state or {}).get('status', 'missing')}",
    )
    add_invariant(checked, "execution:terminal", status == "success", f"poll status={status}")
    drain = postrun_target_session("niaobe", checked)
    return finalize_summary(
        canary="smith_niaobe_handoff",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=events[-1] if events else None,
        latest_worker_state=worker_state or latest_session_state("niaobe", niaobe_before),
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence(delegate_output, session_detail),
        session_detail=session_detail,
        drain=drain,
    )


def architect_worker_runtime(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    del timeout_seconds, stall_seconds
    project_id, project_dir = create_project("canary_architect_worker_runtime", "single_file_markdown_counter.md")
    contract = {
        "starting_state": "Fresh project with deterministic task files and direct Architect worker runtime invocation.",
        "allowed_agents": ["architect"],
        "expected_files": ["management/tasks/T001.md", "CURRENT_TASK.md", "management/architecture/T001.md"],
        "expected_state_fields": {"owner": "niaobe", "phase": "IN_PROGRESS", "waiting_for": "architect", "active_task": "T001", "task_phase": "DESIGN"},
        "expected_handoffs": [],
        "expected_terminal_state": "worker_runtime_sent",
        "failure_timeout_seconds": 120,
        "stall_timeout_seconds": 60,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["architect"])
    freshness = session_freshness("architect")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    seed_task_inputs(
        project_dir,
        task_text=task_t001_markdown_counter(),
        current_task_text=current_task_t001(),
    )
    write_state(
        project_id,
        "IN_PROGRESS",
        "architect",
        "--actor",
        "niaobe",
        "--expect-owner",
        "smith",
        "--set-owner",
        "niaobe",
        "--active-task",
        "T001",
        "--task-phase",
        "DESIGN",
        "--task-status",
        "IN_PROGRESS",
        "--note",
        "Canary seeded direct Architect runtime task.",
    )
    envelope = {
        "project_id": project_id,
        "task_id": "T001",
        "from": "niaobe",
        "to": "architect",
        "phase": "DESIGN",
        "instructions": "Write management/architecture/T001.md for the active task.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        envelope_path = Path(tmp) / "envelope.json"
        envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
        prepare_output = run(
            [sys.executable, str(AGENTICTEAM_ROOT / "scripts" / "architect_run_task.py"), "prepare", "--envelope-file", str(envelope_path)],
            timeout=120,
            cwd=REPO_ROOT,
        )
    values = dict(line.split("=", 1) for line in prepare_output.splitlines() if "=" in line)
    run_dir = Path(values["RUN_DIR"])
    draft_file = Path(values["DRAFT_FILE"])
    draft_file.write_text(architecture_t001_markdown_counter(), encoding="utf-8")
    complete_error = ""
    try:
        run(
            [sys.executable, str(AGENTICTEAM_ROOT / "scripts" / "architect_run_task.py"), "complete", str(run_dir)],
            timeout=120,
            cwd=REPO_ROOT,
        )
    except CanaryError as exc:
        complete_error = str(exc)
    worker_state = load_latest_worker_state(project_id, "architect")
    final_state = state_summary(project_dir)
    add_invariant(checked, "prepare:run_dir", run_dir.exists(), f"run_dir={run_dir}")
    add_invariant(checked, "file:management/tasks/T001.md", project_file_exists(project_dir, "management/tasks/T001.md"), "management/tasks/T001.md exists")
    add_invariant(checked, "file:CURRENT_TASK.md", project_file_exists(project_dir, "CURRENT_TASK.md"), "CURRENT_TASK.md exists")
    add_invariant(checked, "file:management/architecture/T001.md", project_file_exists(project_dir, "management/architecture/T001.md"), "management/architecture/T001.md exists" if project_file_exists(project_dir, "management/architecture/T001.md") else "management/architecture/T001.md is missing")
    add_invariant(checked, "complete:succeeded", not complete_error, complete_error or "complete succeeded")
    add_invariant(checked, "worker:status", bool(worker_state) and worker_state.get("status") == "sent", f"worker status={worker_state.get('status') if worker_state else 'missing'}")
    add_invariant(checked, "worker:last_error", bool(worker_state) and worker_state.get("last_error") in (None, "none"), f"last_error={worker_state.get('last_error') if worker_state else 'missing'}")
    add_invariant(checked, "state:owner", final_state["owner"] == "niaobe", f"owner={final_state['owner']}")
    add_invariant(checked, "state:task_phase", final_state["task_phase"] == "DESIGN", f"task_phase={final_state['task_phase']}")
    return finalize_summary(
        canary="architect_worker_runtime",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=worker_state or final_state,
        latest_handoff=None,
        latest_worker_state=worker_state,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence((worker_state or {}).get("last_send_response"), None),
    )


def morpheus_direct_implementation(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or 420
    stall_seconds = stall_seconds or 90
    project_id, project_dir = create_project("canary_morpheus_direct_implementation", "single_file_markdown_counter.md")
    contract = {
        "starting_state": "Fresh project seeded to a deterministic IMPLEMENT-ready task with direct Niaobe->Morpheus handoff.",
        "allowed_agents": ["niaobe", "morpheus"],
        "expected_files": ["management/tasks/T001.md", "CURRENT_TASK.md", "management/architecture/T001.md", "README.md", "src/main.py", "tests/test_main.py"],
        "expected_state_fields": {"owner": "niaobe", "phase": "IN_PROGRESS", "waiting_for": "morpheus", "active_task": "T001", "task_phase": "IMPLEMENT"},
        "expected_handoffs": [{"event_type": "handoff_sent", "from": "niaobe", "to": "morpheus", "phase": "IMPLEMENT", "task_id": "T001"}],
        "expected_terminal_state": "morpheus_done",
        "failure_timeout_seconds": timeout_seconds,
        "stall_timeout_seconds": stall_seconds,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["morpheus"])
    freshness = session_freshness("morpheus")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    if not gateway_is_listening():
        add_invariant(checked, "gateway:listening", False, "OpenClaw gateway is not listening on 127.0.0.1:18789.")
        return finalize_summary(
            canary="morpheus_direct_implementation",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("morpheus"),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(None, expected_project_id=project_id),
        )
    ready, _ = preflight_target_session("morpheus", checked, preflight)
    morpheus_before = session_snapshot("morpheus")
    if not ready:
        return finalize_summary(
            canary="morpheus_direct_implementation",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("morpheus", morpheus_before),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(morpheus_before, expected_project_id=project_id),
        )
    seed_task_inputs(
        project_dir,
        task_text=task_t001_markdown_counter(),
        current_task_text=current_task_t001(),
        architecture_text=architecture_t001_markdown_counter(),
    )
    write_state(
        project_id,
        "IN_PROGRESS",
        "morpheus",
        "--actor",
        "niaobe",
        "--expect-owner",
        "smith",
        "--set-owner",
        "niaobe",
        "--active-task",
        "T001",
        "--task-phase",
        "IMPLEMENT",
        "--task-status",
        "IN_PROGRESS",
        "--note",
        "Canary seeded direct Morpheus implementation task.",
    )
    handoff_output = direct_handoff_output(
        "niaobe",
        "morpheus",
        project_id,
        "Implement only task T001 using CURRENT_TASK.md, management/tasks/T001.md, and management/architecture/T001.md. Report DONE or BLOCKED with exact artifact paths and test summary.",
        "IMPLEMENT",
        "T001",
    )
    envelope = next(line.split("ENVELOPE: ", 1)[1] for line in handoff_output.splitlines() if line.startswith("ENVELOPE: "))
    send_response = send_envelope_to_agent("morpheus", envelope)

    def snapshot() -> dict[str, Any]:
        return {
            "token": project_token(project_dir, contract["expected_files"], agent="morpheus"),
            "state": state_summary(project_dir),
            "events": load_handoff_events(project_dir),
            "worker_state": load_latest_worker_state(project_id, "morpheus"),
        }

    status, current = poll_until(
        snapshot,
        lambda snap: (
            project_file_exists(project_dir, "src/main.py")
            and project_file_exists(project_dir, "tests/test_main.py")
            and ((snap.get("worker_state") or {}).get("status") in {"sent", "blocked"})
        ),
        timeout_seconds=timeout_seconds,
        stall_seconds=stall_seconds,
        poll_seconds=5,
    )
    final_state = current.get("state", state_summary(project_dir))
    events = current.get("events", load_handoff_events(project_dir))
    session_detail = session_delta(morpheus_before, expected_project_id=project_id)
    session_state = latest_session_state("morpheus", morpheus_before)
    worker_state = current.get("worker_state") or load_latest_worker_state(project_id, "morpheus")
    raw_text = (session_detail or {}).get("raw_text", "")
    worker_payload = (worker_state or {}).get("result_payload") or {}
    worker_instructions = str(worker_payload.get("instructions", ""))
    worker_project_exec = str((worker_state or {}).get("project_exec", ""))
    for relative_path in contract["expected_files"]:
        add_invariant(checked, f"file:{relative_path}", project_file_exists(project_dir, relative_path), f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}")
    add_invariant(checked, "state:owner", final_state["owner"] == "niaobe", f"owner={final_state['owner']}")
    add_invariant(checked, "state:task_phase", final_state["task_phase"] == "IMPLEMENT", f"task_phase={final_state['task_phase']}")
    add_invariant(checked, "handoff:niaobe->morpheus", handoff_exists(events, event_type="handoff_sent", from_agent="niaobe", to_agent="morpheus", phase="IMPLEMENT", task_id="T001"), "niaobe->morpheus handoff recorded")
    project_exec_seen = (
        f'project_exec.sh "{project_id}"' in raw_text
        or f"project_exec.sh \\\"{project_id}\\\"" in raw_text
        or f"project_exec.sh {project_id}" in raw_text
        or f"project_exec.sh {project_id}" in worker_project_exec
    )
    done_seen = (
        ("DONE: Artifacts=" in raw_text and "BLOCKED:" not in raw_text)
        or (worker_instructions.startswith("DONE: Artifacts=") and not worker_instructions.startswith("BLOCKED:"))
    )
    add_invariant(checked, "session:project_exec", project_exec_seen, "runtime/session trace contains project_exec" if project_exec_seen else "session trace does not show project_exec")
    add_invariant(checked, "session:done_message", done_seen, "runtime/session trace contains DONE artifact summary" if done_seen else "session trace did not show a DONE artifact summary")
    add_invariant(checked, "execution:terminal", status == "success", f"poll status={status}")
    drain = postrun_target_session("morpheus", checked)
    return finalize_summary(
        canary="morpheus_direct_implementation",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=events[-1] if events else None,
        latest_worker_state=worker_state or session_state,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence(send_response, session_detail),
        session_detail=session_detail,
        drain=drain,
    )


def morpheus_forced_repair(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or 540
    stall_seconds = stall_seconds or 150
    project_id, project_dir = create_project("canary_morpheus_forced_repair", "single_file_markdown_counter.md")
    contract = {
        "starting_state": "Fresh IMPLEMENT-ready task with direct Niaobe->Morpheus handoff that explicitly exercises LangGraph repair.",
        "allowed_agents": ["niaobe", "morpheus"],
        "expected_files": ["management/tasks/T001.md", "CURRENT_TASK.md", "management/architecture/T001.md", "README.md", "src/main.py", "tests/test_main.py"],
        "expected_state_fields": {"owner": "niaobe", "phase": "IN_PROGRESS", "waiting_for": "morpheus", "active_task": "T001", "task_phase": "IMPLEMENT"},
        "expected_handoffs": [{"event_type": "handoff_sent", "from": "niaobe", "to": "morpheus", "phase": "IMPLEMENT", "task_id": "T001"}],
        "expected_terminal_state": "morpheus_done_after_repair",
        "failure_timeout_seconds": timeout_seconds,
        "stall_timeout_seconds": stall_seconds,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["morpheus"])
    freshness = session_freshness("morpheus")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    if not gateway_is_listening():
        add_invariant(checked, "gateway:listening", False, "OpenClaw gateway is not listening on 127.0.0.1:18789.")
        return finalize_summary(
            canary="morpheus_forced_repair",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("morpheus"),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(None, expected_project_id=project_id),
        )
    ready, _ = preflight_target_session("morpheus", checked, preflight)
    morpheus_before = session_snapshot("morpheus")
    if not ready:
        return finalize_summary(
            canary="morpheus_forced_repair",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("morpheus", morpheus_before),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(morpheus_before, expected_project_id=project_id),
        )
    seed_task_inputs(
        project_dir,
        task_text=task_t001_markdown_counter(),
        current_task_text=current_task_t001(),
        architecture_text=architecture_t001_markdown_counter(),
    )
    write_state(
        project_id,
        "IN_PROGRESS",
        "morpheus",
        "--actor",
        "niaobe",
        "--expect-owner",
        "smith",
        "--set-owner",
        "niaobe",
        "--active-task",
        "T001",
        "--task-phase",
        "IMPLEMENT",
        "--task-status",
        "IN_PROGRESS",
        "--note",
        "Canary seeded forced Morpheus repair task.",
    )
    instructions = (
        "FORCED_REPAIR_CANARY: Implement task T001, but deliberately exercise the runtime repair path. "
        "First create README.md, src/main.py, tests/test_main.py, and manifest.json so that tests/test_main.py "
        "asserts correct markdown counting behavior while src/main.py has one small implementation bug that makes "
        "`python3 -m unittest tests/test_main.py` fail. Then run the required complete command. "
        "When complete returns WORKER_RUNTIME_REPAIR_REQUIRED, run the printed NEXT_REQUIRED repair command before "
        "editing again. During repair, edit only ALLOWED_REPAIR_PATHS, fix src/main.py, do not edit tests, README, "
        "or manifest, then run the final complete command. Report DONE or BLOCKED with exact artifact paths and test summary."
    )
    handoff_output = direct_handoff_output("niaobe", "morpheus", project_id, instructions, "IMPLEMENT", "T001")
    envelope = parse_envelope(handoff_output)
    send_response = send_envelope_to_agent("morpheus", envelope)

    def snapshot() -> dict[str, Any]:
        return {
            "token": project_token(project_dir, contract["expected_files"], agent="morpheus"),
            "state": state_summary(project_dir),
            "events": load_handoff_events(project_dir),
            "worker_state": load_latest_worker_state(project_id, "morpheus"),
        }

    status, current = poll_until(
        snapshot,
        lambda snap: (
            ((snap.get("worker_state") or {}).get("status") in {"sent", "blocked"})
            and int((snap.get("worker_state") or {}).get("completion_attempts", 0) or 0) >= 2
        ),
        timeout_seconds=timeout_seconds,
        stall_seconds=stall_seconds,
        poll_seconds=5,
    )
    final_state = current.get("state", state_summary(project_dir))
    events = current.get("events", load_handoff_events(project_dir))
    session_detail = session_delta(morpheus_before, expected_project_id=project_id)
    session_state = latest_session_state("morpheus", morpheus_before)
    worker_state = current.get("worker_state") or load_latest_worker_state(project_id, "morpheus")
    raw_text = (session_detail or {}).get("raw_text", "")
    worker_payload = (worker_state or {}).get("result_payload") or {}
    worker_instructions = str(worker_payload.get("instructions", ""))
    attempts = int((worker_state or {}).get("completion_attempts", 0) or 0)
    worker_status = str((worker_state or {}).get("status", "missing"))
    repair_guard = (worker_state or {}).get("repair_guard") if isinstance((worker_state or {}).get("repair_guard"), dict) else {}
    for relative_path in contract["expected_files"]:
        add_invariant(checked, f"file:{relative_path}", project_file_exists(project_dir, relative_path), f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}")
    add_invariant(checked, "handoff:niaobe->morpheus", handoff_exists(events, event_type="handoff_sent", from_agent="niaobe", to_agent="morpheus", phase="IMPLEMENT", task_id="T001"), "niaobe->morpheus handoff recorded")
    add_invariant(checked, "runtime:langgraph", (worker_state or {}).get("runtime_engine") == "langgraph", f"runtime_engine={(worker_state or {}).get('runtime_engine', 'missing')}")
    add_invariant(checked, "repair:required_seen", "WORKER_RUNTIME_REPAIR_REQUIRED[test_failed]" in raw_text, "session trace contains repair-required marker")
    add_invariant(checked, "repair:brief_seen", "REPAIR_MODE=implementation_only" in raw_text and "ALLOWED_REPAIR_PATHS=" in raw_text, "session trace contains repair brief")
    add_invariant(checked, "repair:allowed_paths", repair_guard.get("allowed_repair_paths") == ["src/main.py"], f"allowed_repair_paths={repair_guard.get('allowed_repair_paths')}")
    add_invariant(checked, "repair:attempts", attempts >= 2, f"completion_attempts={attempts}")
    add_invariant(checked, "worker:sent", worker_status == "sent", f"worker status={worker_status}")
    add_invariant(checked, "session:done_message", worker_instructions.startswith("DONE: Artifacts="), "runtime/session trace contains DONE artifact summary" if worker_instructions.startswith("DONE: Artifacts=") else "session trace did not show a DONE artifact summary")
    add_invariant(checked, "execution:terminal", status == "success", f"poll status={status}")
    drain = postrun_target_session("morpheus", checked)
    return finalize_summary(
        canary="morpheus_forced_repair",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=events[-1] if events else None,
        latest_worker_state=worker_state or session_state,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence(send_response, session_detail),
        session_detail=session_detail,
        drain=drain,
    )


def oracle_verification(timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    timeout_seconds = timeout_seconds or 300
    stall_seconds = stall_seconds or 60
    project_id, project_dir = create_project("canary_oracle_verification", "single_file_markdown_counter.md")
    contract = {
        "starting_state": "Fresh project seeded to a deterministic VERIFY-ready task with direct Niaobe->Oracle handoff.",
        "allowed_agents": ["niaobe", "oracle"],
        "expected_files": [
            "management/tasks/T001.md",
            "CURRENT_TASK.md",
            "management/architecture/T001.md",
            "README.md",
            "src/main.py",
            "tests/test_main.py",
            "management/validation/T001_REPORT.md",
        ],
        "expected_state_fields": {"owner": "niaobe", "phase": "IN_PROGRESS", "waiting_for": "oracle", "active_task": "T001", "task_phase": "VERIFY"},
        "expected_handoffs": [{"event_type": "handoff_sent", "from": "niaobe", "to": "oracle", "phase": "VERIFY", "task_id": "T001"}],
        "expected_terminal_state": "oracle_report_written",
        "failure_timeout_seconds": timeout_seconds,
        "stall_timeout_seconds": stall_seconds,
    }
    checked: list[dict[str, Any]] = []
    sync = detect_sync_drift(["oracle"])
    freshness = session_freshness("oracle")
    preflight = build_preflight(
        gateway_required=True,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        mattermost_needed=False,
    )
    if not gateway_is_listening():
        add_invariant(checked, "gateway:listening", False, "OpenClaw gateway is not listening on 127.0.0.1:18789.")
        return finalize_summary(
            canary="oracle_verification",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("oracle"),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(None, expected_project_id=project_id),
        )
    ready, _ = preflight_target_session("oracle", checked, preflight)
    oracle_before = session_snapshot("oracle")
    if not ready:
        return finalize_summary(
            canary="oracle_verification",
            contract=contract,
            project_id=project_id,
            project_dir=project_dir,
            checked_invariants=checked,
            final_state=state_summary(project_dir),
            latest_handoff=latest_handoff_event(project_dir),
            latest_worker_state=latest_session_state("oracle", oracle_before),
            sync_drift=sync["sync_drift"],
            session_freshness_value=freshness,
            preflight=preflight,
            session_detail=session_delta(oracle_before, expected_project_id=project_id),
        )
    seed_task_inputs(
        project_dir,
        task_text=task_t001_markdown_counter(),
        current_task_text=current_task_t001(),
        architecture_text=architecture_t001_markdown_counter(),
        readme_text=seeded_readme(),
        main_py_text=seeded_main_py(),
        test_py_text=seeded_test_main_py(),
    )
    write_state(
        project_id,
        "IN_PROGRESS",
        "oracle",
        "--actor",
        "niaobe",
        "--expect-owner",
        "smith",
        "--set-owner",
        "niaobe",
        "--active-task",
        "T001",
        "--task-phase",
        "VERIFY",
        "--task-status",
        "IN_PROGRESS",
        "--note",
        "Canary seeded direct Oracle verification task.",
    )
    handoff_output = direct_handoff_output(
        "niaobe",
        "oracle",
        project_id,
        "Verify only task T001, write management/validation/T001_REPORT.md, and report PASS or FAIL.",
        "VERIFY",
        "T001",
    )
    envelope = next(line.split("ENVELOPE: ", 1)[1] for line in handoff_output.splitlines() if line.startswith("ENVELOPE: "))
    send_response = send_envelope_to_agent("oracle", envelope)

    def snapshot() -> dict[str, Any]:
        return {
            "token": project_token(project_dir, contract["expected_files"], agent="oracle"),
            "state": state_summary(project_dir),
            "events": load_handoff_events(project_dir),
        }

    status, current = poll_until(
        snapshot,
        lambda snap: project_file_exists(project_dir, "management/validation/T001_REPORT.md"),
        timeout_seconds=timeout_seconds,
        stall_seconds=stall_seconds,
        poll_seconds=5,
    )
    final_state = current.get("state", state_summary(project_dir))
    events = current.get("events", load_handoff_events(project_dir))
    session_detail = session_delta(oracle_before, expected_project_id=project_id)
    session_state = latest_session_state("oracle", oracle_before)
    raw_text = (session_detail or {}).get("raw_text", "")
    report_text = project_file_text(project_dir, "management/validation/T001_REPORT.md") if project_file_exists(project_dir, "management/validation/T001_REPORT.md") else ""
    for relative_path in contract["expected_files"]:
        add_invariant(checked, f"file:{relative_path}", project_file_exists(project_dir, relative_path), f"{relative_path} {'exists' if project_file_exists(project_dir, relative_path) else 'is missing'}")
    add_invariant(checked, "state:owner", final_state["owner"] == "niaobe", f"owner={final_state['owner']}")
    add_invariant(checked, "state:task_phase", final_state["task_phase"] == "VERIFY", f"task_phase={final_state['task_phase']}")
    add_invariant(checked, "handoff:niaobe->oracle", handoff_exists(events, event_type="handoff_sent", from_agent="niaobe", to_agent="oracle", phase="VERIFY", task_id="T001"), "niaobe->oracle handoff recorded")
    add_invariant(checked, "report:verdict", "PASS" in report_text or "FAIL" in report_text, "validation report contains PASS/FAIL" if "PASS" in report_text or "FAIL" in report_text else "validation report does not contain PASS/FAIL")
    add_invariant(checked, "session:project_exec", f'project_exec.sh "{project_id}"' in raw_text or f"project_exec.sh \\\"{project_id}\\\"" in raw_text, "session trace contains project_exec" if f'project_exec.sh "{project_id}"' in raw_text or f"project_exec.sh \\\"{project_id}\\\"" in raw_text else "session trace does not show project_exec")
    add_invariant(checked, "session:verdict_message", "PASS:" in raw_text or "FAIL:" in raw_text, "session trace contains PASS/FAIL return" if "PASS:" in raw_text or "FAIL:" in raw_text else "session trace does not contain PASS/FAIL return")
    add_invariant(checked, "execution:terminal", status == "success", f"poll status={status}")
    drain = postrun_target_session("oracle", checked)
    return finalize_summary(
        canary="oracle_verification",
        contract=contract,
        project_id=project_id,
        project_dir=project_dir,
        checked_invariants=checked,
        final_state=final_state,
        latest_handoff=events[-1] if events else None,
        latest_worker_state=session_state,
        sync_drift=sync["sync_drift"],
        session_freshness_value=freshness,
        preflight=preflight,
        delivery_evidence=build_delivery_evidence(send_response, session_detail),
        session_detail=session_detail,
        drain=drain,
    )


CANARY_RUNNERS = {
    "neo_project_create": neo_project_create,
    "smith_planning": smith_planning,
    "smith_niaobe_handoff": smith_niaobe_handoff,
    "architect_worker_runtime": architect_worker_runtime,
    "morpheus_direct_implementation": morpheus_direct_implementation,
    "morpheus_forced_repair": morpheus_forced_repair,
    "oracle_verification": oracle_verification,
}


def run_phase_canary(phase: str, *, timeout_seconds: int | None = None, stall_seconds: int | None = None) -> dict[str, Any]:
    if phase not in CANARY_RUNNERS:
        raise CanaryError(f"unknown phase canary: {phase}")
    return CANARY_RUNNERS[phase](timeout_seconds=timeout_seconds, stall_seconds=stall_seconds)
