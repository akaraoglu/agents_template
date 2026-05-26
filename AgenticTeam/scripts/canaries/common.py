#!/usr/bin/env python3
"""Shared helpers for OpenClaw phase canaries."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTICTEAM_ROOT = REPO_ROOT / "AgenticTeam"
FIXTURES_ROOT = AGENTICTEAM_ROOT / "fixtures"
OPENCLAW_ROOT = Path("/home/alik/.openclaw")
CLAWSPACE_ROOT = Path("/home/alik/workspace/clawspace")
PROJECTS_ROOT = CLAWSPACE_ROOT / "projects" / "active"
WORKSPACES_ROOT = CLAWSPACE_ROOT / "workspaces"
REGISTRY_PATH = CLAWSPACE_ROOT / "projects" / "registry.json"
SYNC_SCRIPT = AGENTICTEAM_ROOT / "scripts" / "sync_live_openclaw.py"
NEW_PROJECT_SCRIPT = AGENTICTEAM_ROOT / "scripts" / "new_project.sh"
PHASE_RUNNER = AGENTICTEAM_ROOT / "scripts" / "run_openclaw_phase_canary.py"
PROJECT_ID_PATTERN = re.compile(r'"project_id"\s*:\s*"([^"]+)"')


class CanaryError(RuntimeError):
    """Raised when a canary precondition fails."""


@dataclass(frozen=True)
class SessionSnapshot:
    agent: str
    session_id: str
    session_file: Path
    status: str
    session_started_at: int
    updated_at: int
    line_count: int


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_process(cmd: list[str], *, timeout: int = 120, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def run(cmd: list[str], *, timeout: int = 120, cwd: Path | None = None) -> str:
    result = run_process(cmd, timeout=timeout, cwd=cwd)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        details = "\n".join(part for part in (stdout, stderr) if part)
        raise CanaryError(f"{' '.join(cmd)} failed with code {result.returncode}: {details}")
    return stdout


def gateway_is_listening() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", 18789)) == 0


def parse_project_id(output: str) -> str:
    match = re.search(r"Project ID:\s*([a-z0-9-]+)", output)
    if not match:
        raise CanaryError(f"could not parse project id from new_project output:\n{output}")
    return match.group(1)


def parse_envelope(output: str) -> str:
    for raw in output.splitlines():
        if raw.startswith("ENVELOPE: "):
            return raw.split("ENVELOPE: ", 1)[1].strip()
    raise CanaryError(f"handoff output did not contain ENVELOPE:\n{output}")


def parse_state_field(text: str, field: str) -> str:
    exact = re.compile(rf"^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    bullet = re.compile(rf"^\s*-\s*\*\*{re.escape(field)}\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = exact.search(text) or bullet.search(text)
    return match.group(1).strip().strip('"') if match else ""


def state_path(project_dir: Path) -> Path:
    project_state = project_dir / "PROJECT_STATE.md"
    legacy_state = project_dir / "STATE.md"
    if project_state.exists():
        return project_state
    if legacy_state.exists():
        return legacy_state
    return project_state


def load_state_text(project_dir: Path) -> str:
    path = state_path(project_dir)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def state_summary(project_dir: Path) -> dict[str, str]:
    text = load_state_text(project_dir)
    return {
        "owner": parse_state_field(text, "owner") or "missing",
        "phase": parse_state_field(text, "phase") or "missing",
        "active_task": parse_state_field(text, "active_task") or "missing",
        "task_phase": parse_state_field(text, "task_phase") or "missing",
        "task_status": parse_state_field(text, "task_status") or "missing",
        "waiting_for": parse_state_field(text, "waiting_for") or "missing",
        "blocked_reason": parse_state_field(text, "blocked_reason") or "none",
    }


def load_handoff_events(project_dir: Path) -> list[dict[str, Any]]:
    handoff_path = project_dir / ".openclaw" / "handoffs.jsonl"
    if not handoff_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw in handoff_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def latest_handoff_event(project_dir: Path) -> dict[str, Any] | None:
    events = load_handoff_events(project_dir)
    return events[-1] if events else None


def handoff_exists(
    events: list[dict[str, Any]],
    *,
    event_type: str | None = None,
    from_agent: str | None = None,
    to_agent: str | None = None,
    phase: str | None = None,
    task_id: str | None = None,
) -> bool:
    for event in events:
        if event_type and str(event.get("event_type", "")).strip() != event_type:
            continue
        if from_agent and str(event.get("from", "")).strip().lower() != from_agent:
            continue
        if to_agent and str(event.get("to", "")).strip().lower() != to_agent:
            continue
        if phase and str(event.get("phase", "")).strip().upper() != phase.upper():
            continue
        if task_id and str(event.get("task_id", "")).strip().upper() != task_id.upper():
            continue
        return True
    return False


def load_latest_worker_state(project_id: str, role: str) -> dict[str, Any] | None:
    runs_root = WORKSPACES_ROOT / role / "runs" / project_id
    if not runs_root.exists():
        return None
    states = sorted((path for path in runs_root.glob("**/state.json") if path.is_file()), key=lambda path: path.stat().st_mtime)
    if not states:
        return None
    try:
        payload = load_json(states[-1])
    except json.JSONDecodeError:
        return None
    payload["state_file"] = str(states[-1])
    return payload


def project_file_exists(project_dir: Path, relative_path: str) -> bool:
    return (project_dir / relative_path).exists()


def project_file_text(project_dir: Path, relative_path: str) -> str:
    return (project_dir / relative_path).read_text(encoding="utf-8")


def add_invariant(results: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    results.append({"name": name, "passed": bool(passed), "detail": detail})


def first_failed_invariant(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in results:
        if not item["passed"]:
            return item
    return None


def make_unique_title(prefix: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M")
    suffix = uuid4().hex[:8]
    return f"{prefix[:20]}-{suffix}-{stamp}"


def load_fixture_text(name: str) -> str:
    return (FIXTURES_ROOT / name).read_text(encoding="utf-8").rstrip() + "\n"


def create_project(prefix: str, fixture_name: str) -> tuple[str, Path]:
    output = run(["bash", str(NEW_PROJECT_SCRIPT), make_unique_title(prefix)], timeout=120, cwd=REPO_ROOT)
    project_id = parse_project_id(output)
    project_dir = PROJECTS_ROOT / project_id
    (project_dir / "PROJECT.md").write_text(load_fixture_text(fixture_name), encoding="utf-8")
    return project_id, project_dir


def write_project_file(project_dir: Path, relative_path: str, content: str) -> None:
    path = project_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def send_session_message(session_key: str, message: str, *, timeout_ms: int = 20000) -> str:
    payload = json.dumps({"key": session_key, "message": message}, separators=(",", ":"))
    return run(
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
        cwd=REPO_ROOT,
    )


def send_envelope_to_agent(agent: str, envelope: dict[str, Any] | str, *, timeout: int = 120) -> str:
    payload = envelope if isinstance(envelope, str) else json.dumps(envelope, separators=(",", ":"))
    return run(["bash", str(CLAWSPACE_ROOT / "bin" / "send_envelope.sh"), agent, payload], timeout=timeout, cwd=REPO_ROOT)


def write_state(project_id: str, phase: str, waiting_for: str, *args: str, timeout: int = 120) -> str:
    cmd = ["bash", str(CLAWSPACE_ROOT / "bin" / "write_state.sh"), project_id, phase, waiting_for, *args]
    return run(cmd, timeout=timeout, cwd=REPO_ROOT)


def session_snapshot(agent: str) -> SessionSnapshot | None:
    sessions_path = OPENCLAW_ROOT / "agents" / agent / "sessions" / "sessions.json"
    if not sessions_path.exists():
        return None
    payload = load_json(sessions_path)
    entry = payload.get(f"agent:{agent}:main")
    if not isinstance(entry, dict):
        return None
    session_file = Path(str(entry.get("sessionFile", "")))
    if not session_file.exists():
        return None
    line_count = len(session_file.read_text(encoding="utf-8").splitlines())
    return SessionSnapshot(
        agent=agent,
        session_id=str(entry.get("sessionId", "")),
        session_file=session_file,
        status=str(entry.get("status", "unknown")),
        session_started_at=int(entry.get("sessionStartedAt") or 0),
        updated_at=int(entry.get("updatedAt") or 0),
        line_count=line_count,
    )


def session_message_texts(raw_line: str) -> list[tuple[str, str]]:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        return []
    if payload.get("type") != "message":
        return []
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    role = str(message.get("role", "")).strip().lower()
    texts: list[tuple[str, str]] = []
    for item in message.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            texts.append((role, text))
    return texts


def extract_inbound_project_ids(raw_lines: list[str]) -> list[str]:
    project_ids: list[str] = []
    for raw_line in raw_lines:
        for role, text in session_message_texts(raw_line):
            if role != "user":
                continue
            for project_id in PROJECT_ID_PATTERN.findall(text):
                if project_id not in project_ids:
                    project_ids.append(project_id)
    return project_ids


def detect_empty_stop(raw_lines: list[str]) -> bool:
    for raw_line in reversed(raw_lines):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "message":
            continue
        message = payload.get("message")
        if not isinstance(message, dict):
            continue
        if str(message.get("role", "")).strip().lower() != "assistant":
            continue
        content = message.get("content")
        stop_reason = str(message.get("stopReason", "")).strip().lower()
        return stop_reason == "stop" and isinstance(content, list) and len(content) == 0
    return False


def session_delta(snapshot: SessionSnapshot | None, *, expected_project_id: str | None = None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    current = session_snapshot(snapshot.agent)
    if current is None:
        return None
    if current.session_file == snapshot.session_file:
        lines = current.session_file.read_text(encoding="utf-8").splitlines()
        raw_lines = lines[snapshot.line_count :]
    else:
        raw_lines = current.session_file.read_text(encoding="utf-8").splitlines()
    raw_text = "\n".join(raw_lines)
    excerpt_lines = raw_lines[-30:]
    delta_project_ids = extract_inbound_project_ids(raw_lines)
    unexpected_project_ids = [project_id for project_id in delta_project_ids if expected_project_id and project_id != expected_project_id]
    empty_stop = detect_empty_stop(raw_lines)
    return {
        "agent": snapshot.agent,
        "session_id": current.session_id,
        "session_file": str(current.session_file),
        "status": current.status,
        "session_started_at": current.session_started_at,
        "updated_at": current.updated_at,
        "line_count_delta": len(raw_lines),
        "started": current.updated_at != snapshot.updated_at or current.session_id != snapshot.session_id,
        "responded": len(raw_lines) > 0,
        "stopped": current.status == "done",
        "empty_stop": empty_stop,
        "delta_envelope_project_ids": delta_project_ids,
        "unexpected_project_ids_seen": unexpected_project_ids,
        "contaminated": bool(unexpected_project_ids),
        "raw_text": raw_text,
        "excerpt": "\n".join(excerpt_lines),
    }


def manifest_source_files(agent: str) -> list[Path]:
    manifest = load_json(AGENTICTEAM_ROOT / "config" / "live_openclaw_sync_manifest.json")
    agent_conf = manifest.get("agents", {}).get(agent, {})
    repo_agent_dir = AGENTICTEAM_ROOT / "agents" / agent
    files = [repo_agent_dir / name for name in agent_conf.get("workspace_files", [])]
    files.extend(repo_agent_dir / name for name in agent_conf.get("agent_dir_files", []))
    helper_names = manifest.get("helper_scripts", {}).get(agent, [])
    files.extend(AGENTICTEAM_ROOT / "scripts" / name for name in helper_names)
    files.extend(
        [
            AGENTICTEAM_ROOT / "config" / "exec-approvals.json",
            AGENTICTEAM_ROOT / "config" / "openclaw.json",
            AGENTICTEAM_ROOT / "config" / "live_openclaw_sync_manifest.json",
        ]
    )
    return [path for path in files if path.exists()]


def session_freshness(agent: str) -> str:
    snapshot = session_snapshot(agent)
    if snapshot is None or snapshot.session_started_at <= 0:
        return "unknown"
    source_files = manifest_source_files(agent)
    if not source_files:
        return "unknown"
    newest_source_ms = max(int(path.stat().st_mtime * 1000) for path in source_files)
    return "fresh" if snapshot.session_started_at >= newest_source_ms else "stale"


def detect_sync_drift(relevant_agents: list[str] | None = None) -> dict[str, str]:
    cmd = [sys.executable, str(SYNC_SCRIPT)]
    for agent in relevant_agents or []:
        cmd.extend(["--agent", agent])
    result = run_process(cmd, timeout=120, cwd=REPO_ROOT)
    output = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    drift = any(line.startswith("[UPDATE") or line.startswith("[CREATE") for line in output.splitlines())
    if result.returncode != 0:
        return {"sync_drift": "unknown", "detail": output or "sync drift check failed"}
    return {"sync_drift": "yes" if drift else "no", "detail": output}


def ollama_preflight() -> dict[str, str]:
    result = run_process(["ollama", "ps"], timeout=15, cwd=REPO_ROOT)
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        return {"available": "no", "running": "unknown", "detail": detail or "ollama ps failed"}
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    running = "yes" if len(lines) > 1 else "no"
    return {"available": "yes", "running": running, "detail": lines[1] if len(lines) > 1 else (lines[0] if lines else "no running model")}


def build_preflight(
    *,
    gateway_required: bool,
    sync_drift: str,
    session_freshness_value: str,
    mattermost_needed: bool,
) -> dict[str, Any]:
    return {
        "gateway_listening": "yes" if gateway_is_listening() else "no",
        "gateway_required": "yes" if gateway_required else "no",
        "ollama": ollama_preflight(),
        "sync_drift": sync_drift,
        "session_freshness": session_freshness_value,
        "mattermost_needed": "yes" if mattermost_needed else "no",
    }


def build_delivery_evidence(send_response: str | None, session_detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if send_response is None and session_detail is None:
        return None
    return {
        "envelope_sent": "yes" if send_response else "no",
        "sessions_send_response": send_response or "none",
        "target_session_line_delta_count": (session_detail or {}).get("line_count_delta", 0),
        "target_session_started": "yes" if (session_detail or {}).get("started") else "no",
        "target_session_responded": "yes" if (session_detail or {}).get("responded") else "no",
        "target_session_stopped": "yes" if (session_detail or {}).get("stopped") else "no",
        "empty_stop_detected": "yes" if (session_detail or {}).get("empty_stop") else "no",
        "contaminated": "yes" if (session_detail or {}).get("contaminated") else "no",
        "delta_envelope_project_ids": (session_detail or {}).get("delta_envelope_project_ids", []),
        "unexpected_project_ids_seen": (session_detail or {}).get("unexpected_project_ids_seen", []),
    }


def token_from_paths(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if path.exists():
            stat = path.stat()
            parts.append(f"{path}:{int(stat.st_mtime)}:{stat.st_size}")
        else:
            parts.append(f"{path}:missing")
    return "|".join(parts)


def poll_until(
    snapshot_func: Callable[[], dict[str, Any]],
    success_func: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: int,
    stall_seconds: int,
    poll_seconds: int = 5,
) -> tuple[str, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    last_token = ""
    last_change_at = time.time()
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = snapshot_func()
        token = str(latest.get("token", ""))
        if token != last_token:
            last_token = token
            last_change_at = time.time()
        if success_func(latest):
            return "success", latest
        if time.time() - last_change_at >= stall_seconds:
            return "stall", latest
        time.sleep(poll_seconds)
    return "timeout", latest


def latest_session_state(agent: str, snapshot: SessionSnapshot | None = None) -> dict[str, Any] | None:
    current = session_snapshot(agent)
    if current is None:
        return None
    payload = asdict(current)
    payload["session_file"] = str(current.session_file)
    delta = session_delta(snapshot or current)
    if delta:
        payload["line_count_delta"] = delta["line_count_delta"]
        payload["empty_stop"] = bool(delta.get("empty_stop"))
    return payload


def wait_for_session_quiescence(
    agent: str,
    *,
    timeout_seconds: int = 30,
    poll_seconds: int = 2,
    stable_polls: int = 3,
) -> dict[str, Any]:
    started_at = int(time.time())
    initial = session_snapshot(agent)
    if initial is None:
        return {
            "agent": agent,
            "outcome": "no_session",
            "polls": 0,
            "line_count_delta": 0,
            "session_id": "none",
            "updated_at": 0,
            "status": "missing",
            "session_id_changed": False,
            "session_ids_seen": [],
            "started_at": started_at,
            "finished_at": started_at,
        }
    deadline = time.time() + timeout_seconds
    polls = 0
    last_state: tuple[str, int, int, str] | None = None
    stable_count = 0
    session_ids_seen = [initial.session_id]
    saw_change = False
    while time.time() < deadline:
        polls += 1
        current = session_snapshot(agent)
        if current is None:
            finished_at = int(time.time())
            return {
                "agent": agent,
                "outcome": "no_session",
                "polls": polls,
                "line_count_delta": 0,
                "session_id": "none",
                "updated_at": 0,
                "status": "missing",
                "session_id_changed": True,
                "session_ids_seen": session_ids_seen,
                "started_at": started_at,
                "finished_at": finished_at,
            }
        if current.session_id not in session_ids_seen:
            session_ids_seen.append(current.session_id)
        state = (current.session_id, current.updated_at, current.line_count, current.status)
        if state == last_state and current.status in {"done", "idle"}:
            stable_count += 1
        elif current.status in {"done", "idle"}:
            stable_count = 1
        else:
            stable_count = 0
        if (
            current.session_id != initial.session_id
            or current.updated_at != initial.updated_at
            or current.line_count != initial.line_count
        ):
            saw_change = True
        if stable_count >= stable_polls:
            finished_at = int(time.time())
            if current.session_id != initial.session_id:
                outcome = "foreign_traffic"
            elif saw_change:
                outcome = "drained"
            else:
                outcome = "already_quiescent"
            return {
                "agent": agent,
                "outcome": outcome,
                "polls": polls,
                "line_count_delta": max(0, current.line_count - initial.line_count),
                "session_id": current.session_id,
                "updated_at": current.updated_at,
                "status": current.status,
                "session_id_changed": current.session_id != initial.session_id,
                "session_ids_seen": session_ids_seen,
                "started_at": started_at,
                "finished_at": finished_at,
            }
        last_state = state
        time.sleep(poll_seconds)
    current = session_snapshot(agent) or initial
    finished_at = int(time.time())
    return {
        "agent": agent,
        "outcome": "timeout",
        "polls": polls,
        "line_count_delta": max(0, current.line_count - initial.line_count),
        "session_id": current.session_id,
        "updated_at": current.updated_at,
        "status": current.status,
        "session_id_changed": current.session_id != initial.session_id,
        "session_ids_seen": session_ids_seen,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def classify_failure(
    detail: str,
    *,
    sync_drift: str,
    session_freshness_value: str,
    latest_worker_state: dict[str, Any] | None,
    session_detail: dict[str, Any] | None,
    delivery_evidence: dict[str, Any] | None,
) -> str:
    text = detail.lower()
    worker_error = json.dumps(latest_worker_state.get("last_error")) if latest_worker_state else ""
    session_text = (session_detail or {}).get("raw_text", "").lower()
    if (session_detail or {}).get("contaminated"):
        return "session_contamination"
    if delivery_evidence and (
        delivery_evidence.get("envelope_sent") == "no" or delivery_evidence.get("target_session_responded") == "no"
    ):
        return "runtime_message_delivery"
    if '"action":"project_write"' in session_text and '"status":"blocked"' in session_text and "done:" not in session_text and "blocked:" not in session_text:
        return "prompt_contract"
    if (session_detail or {}).get("empty_stop"):
        return "model_empty_or_malformed"
    if sync_drift == "yes" or session_freshness_value == "stale":
        return "session_staleness"
    if "gateway is not listening" in text or "sessions.send failed" in text or "command unavailable" in text:
        return "external_service"
    if (
        "morpheus drain outcome=timeout" in text
        or "session trace does not show project_exec" in text
        or "session trace did not show a done artifact summary" in text
    ):
        return "morpheus_completion_contract"
    if "allowlist" in text or "not allowed" in text or "exec denied" in text or "forbidden" in text:
        return "allowlist_policy"
    if "owner mismatch" in text or "pending receipt" in text or "state verification mismatch" in text or "handoff_received" in text:
        return "runtime_state_machine"
    if "required file missing" in text or "artifact verified" in text or "project_read" in text or "project_write" in text or "project_exec" in text or "verify_artifact" in text or "helper" in text:
        return "helper_guard"
    if "missing required content" in text or "partial" in text or "current_task" in text or "plan.md" in text or "backlog.md" in text:
        return "prompt_contract"
    if '"content":[],"stopReason":"stop"' in session_text or (session_detail or {}).get("empty_stop"):
        return "model_empty_or_malformed"
    if worker_error:
        error_text = worker_error.lower()
        if "send_failed" in error_text:
            return "external_service"
        if "verification_failed" in error_text:
            return "prompt_contract"
        if "helper_failed" in error_text or "missing_input" in error_text:
            return "helper_guard"
    return "unknown"


def infer_first_failed_boundary(
    first_failed: dict[str, Any] | None,
    *,
    delivery_evidence: dict[str, Any] | None,
    latest_worker_state: dict[str, Any] | None,
    session_detail: dict[str, Any] | None,
) -> str:
    if delivery_evidence:
        if delivery_evidence["envelope_sent"] == "no":
            return "sessions.send delivery"
        if delivery_evidence["target_session_responded"] == "no":
            return "message delivery to target session"
        if delivery_evidence.get("contaminated") == "yes":
            return "session contamination"
        if delivery_evidence["empty_stop_detected"] == "yes":
            agent = (session_detail or {}).get("agent") or (latest_worker_state or {}).get("agent") or "agent"
            return f"{agent} session turn"
    if first_failed is None:
        return "none"
    name = first_failed["name"]
    if name == "postrun:target_session_drained":
        agent = (latest_worker_state or {}).get("agent") or (session_detail or {}).get("agent") or "worker"
        return f"{agent} completion/report"
    if name.startswith("handoff:"):
        return "handoff ledger"
    if name.startswith("state:"):
        return "project state transition"
    if name.startswith("session:project_exec"):
        return "worker test execution"
    if name.startswith("session:done_message") or name.startswith("session:verdict_message"):
        return "worker completion/report"
    if name.startswith("file:management/validation"):
        return "oracle report creation"
    if name.startswith("file:management/architecture"):
        return "architect artifact creation"
    if name.startswith("file:README") or name.startswith("file:src/main.py") or name.startswith("file:tests/test_main.py"):
        return "morpheus artifact creation"
    if name.startswith("file:management/tasks") or name.startswith("current_task:"):
        return "smith planning artifact creation"
    return name


def render_markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Canary Report",
        "",
        f"- **schema_version**: `{summary['schema_version']}`",
        f"- **canary**: `{summary['canary']}`",
        f"- **status**: `{summary['status']}`",
        f"- **project_id**: `{summary.get('project_id', 'none')}`",
        f"- **project_dir**: `{summary.get('project_dir', 'none')}`",
        f"- **sync_drift**: `{summary.get('sync_drift', 'no')}`",
        f"- **session_freshness**: `{summary.get('session_freshness', 'unknown')}`",
        f"- **terminal_state**: `{summary.get('terminal_state', 'unknown')}`",
        f"- **suggested_fault_layer**: `{summary.get('suggested_fault_layer', 'unknown')}`",
        "",
        "## Preflight",
        "",
        "```json",
        json.dumps(summary.get("preflight", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Contract",
        "",
        f"- **starting_state**: {summary['contract']['starting_state']}",
        f"- **allowed_agents**: `{', '.join(summary['contract']['allowed_agents']) or 'none'}`",
        f"- **expected_files**: `{', '.join(summary['contract']['expected_files']) or 'none'}`",
        f"- **expected_state_fields**: `{json.dumps(summary['contract']['expected_state_fields'], sort_keys=True)}`",
        f"- **expected_handoffs**: `{json.dumps(summary['contract']['expected_handoffs'])}`",
        f"- **expected_terminal_state**: `{summary['contract']['expected_terminal_state']}`",
        f"- **failure_timeout_seconds**: `{summary['contract']['failure_timeout_seconds']}`",
        f"- **stall_timeout_seconds**: `{summary['contract']['stall_timeout_seconds']}`",
        "",
        "## Checked Invariants",
        "",
    ]
    for item in summary["checked_invariants"]:
        prefix = "PASS" if item["passed"] else "FAIL"
        lines.append(f"- **{prefix}** `{item['name']}` — {item['detail']}")
    lines.extend(
        [
            "",
            "## Failure Summary",
            "",
            f"- **first_failed_invariant**: `{json.dumps(summary.get('first_failed_invariant'), sort_keys=True)}`",
            f"- **first_failed_boundary**: `{summary.get('first_failed_boundary', 'unknown')}`",
            "",
            "## Delivery Evidence",
            "",
            "```json",
            json.dumps(summary.get("delivery_evidence"), indent=2, sort_keys=True),
            "```",
            "",
            "## Drain",
            "",
            "```json",
            json.dumps(summary.get("drain"), indent=2, sort_keys=True),
            "```",
            "",
            "## Final State",
            "",
            "```json",
            json.dumps(summary.get("final_state", {}), indent=2, sort_keys=True),
            "```",
            "",
            "## Latest Handoff Event",
            "",
            "```json",
            json.dumps(summary.get("latest_handoff_event"), indent=2, sort_keys=True),
            "```",
            "",
            "## Latest Worker State",
            "",
            "```json",
            json.dumps(summary.get("latest_worker_state"), indent=2, sort_keys=True),
            "```",
            "",
            "## Session Excerpt",
            "",
            "```text",
            summary.get("session_excerpt", ""),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(summary: dict[str, Any], report_file: str | None) -> None:
    if not report_file:
        return
    report_path = Path(report_file)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown_report(summary), encoding="utf-8")
    json_path = report_path.with_suffix(".json")
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finalize_summary(
    *,
    canary: str,
    contract: dict[str, Any],
    project_id: str,
    project_dir: Path,
    checked_invariants: list[dict[str, Any]],
    final_state: dict[str, Any],
    latest_handoff: dict[str, Any] | None,
    latest_worker_state: dict[str, Any] | None,
    sync_drift: str,
    session_freshness_value: str,
    preflight: dict[str, Any] | None = None,
    delivery_evidence: dict[str, Any] | None = None,
    session_detail: dict[str, Any] | None = None,
    drain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first_failed = first_failed_invariant(checked_invariants)
    status = "FAIL"
    if first_failed is None:
        if sync_drift == "yes" or session_freshness_value == "stale":
            status = "PASS_WITH_WARNINGS"
        else:
            status = "PASS"
    detail = first_failed["detail"] if first_failed else "all invariants passed"
    suggested_fault_layer = (
        "none"
        if status != "FAIL"
        else classify_failure(
            detail,
            sync_drift=sync_drift,
            session_freshness_value=session_freshness_value,
            latest_worker_state=latest_worker_state,
            session_detail=session_detail,
            delivery_evidence=delivery_evidence,
        )
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "canary": canary,
        "status": status,
        "project_id": project_id,
        "project_dir": str(project_dir),
        "contract": contract,
        "checked_invariants": checked_invariants,
        "first_failed_invariant": first_failed,
        "final_state": final_state,
        "latest_handoff_event": latest_handoff,
        "latest_worker_state": latest_worker_state,
        "sync_drift": sync_drift,
        "session_freshness": session_freshness_value,
        "terminal_state": final_state.get("phase") or final_state.get("status") or "unknown",
        "suggested_fault_layer": suggested_fault_layer,
        "first_failed_boundary": infer_first_failed_boundary(
            first_failed,
            delivery_evidence=delivery_evidence,
            latest_worker_state=latest_worker_state,
            session_detail=session_detail,
        ),
        "preflight": preflight or {},
        "delivery_evidence": delivery_evidence,
        "drain": drain,
    }
    if session_detail:
        summary["session_excerpt"] = session_detail.get("excerpt", "")
    return summary
