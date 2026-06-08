#!/usr/bin/env python3
"""Deterministic liveness watchdog (Slice A) for wedged worker phases.

The local model that drives the workers empty-stops mid-task: after a self-test
failure it stops with ``content:[]`` and never runs ``report`` or ``block`` (see
the e2e ``run-e2e-fibonacci-test-20260605-1230`` and ``...-1430`` failures). The
flow is a pure event-chain with no process that stays alive across a worker
session, so a project then hangs forever at ``waiting_for=<role>``.

Today the only "watchdog" is a *model-driven* heartbeat prompt (Niaobe's
``phase-watchdog``) that asks the same unreliable model to notice the timeout and
react -- exactly the mechanism that fails. This module replaces that with a
*deterministic* reaper that needs no model: it reads the authoritative
``PROJECT_STATE.md``, decides whether the awaited worker is genuinely stale, and
synthesizes the terminal ``BLOCKED`` transition the worker should have produced,
driving the existing Niaobe block path (``write_state BLOCKED -> Smith``).

Correctness/safety rules (mirrors ``transition_guard``):
  * Only acts when the project still shows a worker awaited at its phase
    (owner==niaobe, waiting_for in {architect,morpheus,oracle}, task_status==
    IN_PROGRESS, task_phase==EXPECTED_PHASE[role]).
  * Staleness uses the most recent activity timestamp across PROJECT_STATE.md and
    the awaited worker's run directory, so a genuinely-slow-but-active worker is
    never reaped.
  * If the worker actually produced a terminal result (its ``LATEST.json`` pointer
    shows COMPLETE/BLOCKED) the watchdog does NOT reap -- that is a Niaobe-side
    processing issue, not a worker hang (this avoids the 1502-class misfire where
    the worker succeeded but the parent failed to resolve the result).
  * The reap runs under ``transition_lock`` and re-checks ``classify_child`` so it
    cannot race a real callback that lands between assessment and the block.
  * Idempotent by construction: a successful reap advances the state
    (task_status=BLOCKED, owner=smith), so a second pass classifies the project as
    no longer worker-awaited and skips.

Known limitations (acceptable for this minimal slice; addressed by the later
ledger-backed supervisor):
  * Bias to NOT reap. The terminal guard inspects ``LATEST.json`` AND every run's
    ``result.json`` without a generation token, so after a same-task re-dispatch a
    stale terminal result could mask a newly-hung run. We prefer this false
    negative (a hang persists, surfaced on the next sweep / by the analyzer) over
    the cardinal sin of false-blocking genuinely-finished or active work.
  * ``mark_child_runtime_blocked`` advances state (write_state.sh) before it
    notifies Smith; if the Smith send fails after the state flip, the project is
    BLOCKED but Smith is not notified, and a later sweep skips it (no longer
    niaobe-owned). This send-after-state-advance crash window is inherent to the
    existing block path (a real worker block has the same window) and is owned by
    the later supervisor's durable outbox; it is not introduced here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from niaobe_run_task import build_run_dir, mark_child_runtime_blocked, send_smith_result
from transition_guard import (
    EXPECTED_PHASE,
    classify_child,
    event_key,
    is_owner_mismatch,
    read_project_state,
    record_transition,
    transition_lock,
)
from worker_runtime import (
    WorkerRuntimeError,
    child_latest_pointer_path,
    iso_now,
    live_bin_root,
    require_ok,
    run_command,
    workspace_root,
    write_json,
)

WORKER_ROLES = frozenset({"architect", "morpheus", "oracle"})
DEFAULT_IDLE_SECONDS = 1800  # matches worker RUN_DEADLINE_SECONDS budget
TERMINAL_SIGNALS = frozenset({"COMPLETE", "BLOCKED"})
WATCHDOG_RUN_ID = "watchdog"
WATCHDOG_BLOCK_CODE = "worker_timeout"

# Second liveness class: a TASK_HANDOFF that Niaobe never acknowledged. A
# successful Niaobe ack always advances ``owner`` to niaobe BEFORE it writes its
# result, so a project still showing ``owner=smith, waiting_for=niaobe,
# task_phase=TASK_HANDOFF, task_status=READY`` past the idle budget genuinely
# means the handoff was dropped (the shared niaobe session empty-stopped or was
# busy). The watchdog escalates it to BLOCKED for Smith -- it never re-delivers
# (that would just feed the wedged session); the real fix is session rotation.
NIAOBE_ACK_PHASE = "TASK_HANDOFF"
NIAOBE_ACK_STATUS = "READY"
NIAOBE_ACK_BLOCK_CODE = "niaobe_ack_timeout"
# Niaobe terminal statuses that, if newer than the current handoff, prove the ack
# was actually processed (so the watchdog must stand down).
NIAOBE_TERMINAL_STATUSES = frozenset({"sent", "superseded", "blocked", "done"})


def default_projects_root() -> Path:
    return Path(
        os.environ.get(
            "CLAWSPACE_PROJECTS_ROOT",
            "/home/alik/workspace/clawspace/projects/active",
        )
    )


@dataclass
class LivenessDecision:
    """Pure decision about one project's worker-awaited liveness."""

    action: str  # "skip" | "reap" | "worker_terminal_pending" | "reap_niaobe_ack" | "niaobe_ack_terminal_pending"
    reason: str
    role: str = ""
    task_id: str = ""
    phase: str = ""
    idle_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["idle_seconds"] = round(self.idle_seconds, 1)
        return data


@dataclass
class ProjectResult:
    """Outcome of processing one project (decision + any action taken)."""

    project_id: str
    project_path: str
    decision: LivenessDecision
    outcome: str  # "skipped" | "reaped" | "would_reap" | "superseded" | "error"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_path": self.project_path,
            "outcome": self.outcome,
            "detail": self.detail,
            "decision": self.decision.as_dict(),
        }


def parse_project_id(project_path: Path) -> str:
    """Read ``project_id`` from PROJECT_STATE.md (falls back to dir name)."""

    state_file = Path(project_path) / "PROJECT_STATE.md"
    if state_file.is_file():
        try:
            text = state_file.read_text(encoding="utf-8")
        except OSError:
            text = ""
        pattern = re.compile(r"^\s*-?\s*\*?\*?project_id\*?\*?\s*:\s*(.+?)\s*$", re.IGNORECASE)
        for raw in text.splitlines():
            match = pattern.match(raw)
            if match:
                candidate = match.group(1).strip().strip('"')
                if re.fullmatch(r"[a-z0-9-]+", candidate):
                    return candidate
    name = Path(project_path).name
    return name if re.fullmatch(r"[a-z0-9-]+", name) else ""


def _newest_mtime(root: Path) -> float | None:
    """Most recent mtime among ``root`` and everything under it."""

    if not root.exists():
        return None
    newest: float | None = None
    try:
        candidates = [root, *root.rglob("*")]
    except OSError:
        candidates = [root]
    for entry in candidates:
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def project_state_mtime(project_path: Path) -> float | None:
    state_file = Path(project_path) / "PROJECT_STATE.md"
    try:
        return state_file.stat().st_mtime
    except OSError:
        return None


def _task_runs_dir(role: str, project_id: str, task_id: str) -> Path:
    return child_latest_pointer_path(role, project_id, task_id).parent


def _run_ids_for_task(role: str, project_id: str, task_id: str) -> list[str]:
    runs_dir = _task_runs_dir(role, project_id, task_id)
    if not runs_dir.is_dir():
        return []
    try:
        return [child.name for child in runs_dir.iterdir() if child.is_dir()]
    except OSError:
        return []


def worker_last_activity_epoch(role: str, project_id: str, task_id: str) -> float | None:
    """Newest mtime reflecting the awaited worker's activity for this task.

    Scans both the callback-facing run tree (``runs/<project>/<task>/``) and the
    per-run *runtime* tree (``runtime/<run_id>/``) where the worker actually writes
    drafts/manifests while working -- otherwise an actively-writing worker (whose
    only fresh files live under ``runtime/<run_id>``) would look idle and be
    falsely reaped.
    """

    if not (role and project_id and task_id):
        return None
    newest = _newest_mtime(_task_runs_dir(role, project_id, task_id))
    runtime_root = workspace_root() / role / "runtime"
    for run_id in _run_ids_for_task(role, project_id, task_id):
        candidate = _newest_mtime(runtime_root / run_id)
        if candidate is not None and (newest is None or candidate > newest):
            newest = candidate
    return newest


def _signal_is_terminal(payload: dict[str, Any], role: str, task_id: str) -> bool:
    """True when a result.json/LATEST.json payload is a terminal worker outcome."""

    role = role.strip().lower()
    task_id = task_id.strip().upper()

    # Runtime-owned LATEST.json pointer (architect/morpheus) uses flat fields.
    flat_signal = str(payload.get("signal", "")).strip().upper()
    if flat_signal in TERMINAL_SIGNALS:
        if str(payload.get("from", "")).strip().lower() == role and (
            str(payload.get("task_id", "")).strip().upper() == task_id
        ):
            return True

    # result.json carries a nested ``signal`` dict and a top-level status; oracle
    # writes result.json but no LATEST.json, so this branch is its only signal.
    nested = payload.get("signal")
    if isinstance(nested, dict):
        if (
            str(nested.get("signal", "")).strip().upper() in TERMINAL_SIGNALS
            and str(nested.get("from", "")).strip().lower() == role
            and str(nested.get("task_id", "")).strip().upper() == task_id
        ):
            return True

    if str(payload.get("status", "")).strip().lower() in {"sent", "blocked"}:
        if str(payload.get("task_id", "")).strip().upper() == task_id:
            return True
    return False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def worker_terminal_pending(role: str, project_id: str, task_id: str) -> bool:
    """True when the worker already produced a terminal result for this task.

    Such a project is awaiting *Niaobe* (the parent failed to resolve/process the
    child result); reaping it would wrongly block a worker that actually finished
    (the "1502" failure class). Checks the runtime-owned ``LATEST.json`` pointer
    AND every run's ``result.json`` -- Oracle writes only ``result.json`` (no
    pointer), so the pointer check alone would leave finished Oracle runs
    unprotected.
    """

    if not (role and project_id and task_id):
        return False

    pointer = child_latest_pointer_path(role, project_id, task_id)
    pointer_payload = _read_json(pointer) if pointer.is_file() else None
    if pointer_payload is not None and _signal_is_terminal(pointer_payload, role, task_id):
        return True

    runs_dir = _task_runs_dir(role, project_id, task_id)
    if runs_dir.is_dir():
        for run_id in _run_ids_for_task(role, project_id, task_id):
            result_payload = _read_json(runs_dir / run_id / "result.json")
            if result_payload is not None and _signal_is_terminal(result_payload, role, task_id):
                return True
    return False


def _is_niaobe_ack_class(state: dict[str, str]) -> bool:
    """True when the project is a TASK_HANDOFF still awaiting Niaobe's ack."""

    return (
        state.get("owner", "").strip().lower() == "smith"
        and state.get("waiting_for", "").strip().lower() == "niaobe"
        and state.get("task_phase", "").strip().upper() == NIAOBE_ACK_PHASE
        and state.get("task_status", "").strip().upper() == NIAOBE_ACK_STATUS
    )


def niaobe_runs_dir(project_id: str, task_id: str) -> Path:
    return workspace_root() / "niaobe" / "runs" / project_id / task_id


def niaobe_ack_terminal_pending(
    project_id: str, task_id: str, state_mtime: float | None
) -> bool:
    """True when Niaobe already processed *this* handoff generation.

    Generation-bound (finding #3): only counts a Niaobe terminal result whose
    mtime is newer than the current PROJECT_STATE.md write. A successful ack
    advances ``owner`` to niaobe, so for a genuinely-stuck project this never
    fires; the mtime gate is what prevents a *stale* terminal result from an
    earlier handoff generation (after a Smith re-handoff) from masking a freshly
    dropped ack -- without it the watchdog would false-negative forever.
    """

    if not (project_id and task_id):
        return False
    runs_dir = niaobe_runs_dir(project_id, task_id)
    if not runs_dir.is_dir():
        return False
    threshold = state_mtime or 0.0
    task_norm = task_id.strip().upper()
    try:
        run_dirs = [child for child in runs_dir.iterdir() if child.is_dir()]
    except OSError:
        return False
    for run_dir in run_dirs:
        for name in ("result.json", "state.json"):
            candidate = run_dir / name
            if not candidate.is_file():
                continue
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime <= threshold:
                continue
            payload = _read_json(candidate)
            if payload is None:
                continue
            if (
                str(payload.get("status", "")).strip().lower() in NIAOBE_TERMINAL_STATUSES
                and str(payload.get("task_id", "")).strip().upper() == task_norm
            ):
                return True
    return False


def _niaobe_idle(
    project_path: Path, project_id: str, task_id: str, now_epoch: float
) -> tuple[float, float | None]:
    """Idle seconds for a Niaobe-ack project + the PROJECT_STATE.md mtime.

    Activity = max mtime across PROJECT_STATE.md and any Niaobe run/runtime dir
    for the task (a Niaobe that *started* accepting but has not yet flipped owner
    is still live and must not be reaped).
    """

    state_mtime = project_state_mtime(project_path)
    last_activity = state_mtime
    niaobe_activity = worker_last_activity_epoch("niaobe", project_id, task_id)
    if niaobe_activity is not None:
        last_activity = (
            niaobe_activity if last_activity is None else max(last_activity, niaobe_activity)
        )
    idle = float("inf") if last_activity is None else now_epoch - last_activity
    return idle, state_mtime


def classify_liveness(
    state: dict[str, str],
    *,
    now_epoch: float,
    last_activity_epoch: float | None,
    idle_threshold: float,
    terminal_pending: bool,
) -> LivenessDecision:
    """Pure decision: should this project's awaited worker be reaped?"""

    owner = state.get("owner", "").strip().lower()
    waiting_for = state.get("waiting_for", "").strip().lower()
    task_status = state.get("task_status", "").strip().upper()
    task_phase = state.get("task_phase", "").strip().upper()
    active_task = state.get("active_task", "").strip().upper()

    if owner != "niaobe":
        # Second class: a TASK_HANDOFF that Niaobe never acknowledged.
        if _is_niaobe_ack_class(state):
            if last_activity_epoch is None:
                idle = float("inf")
            else:
                idle = now_epoch - last_activity_epoch
            base = dict(role="niaobe", task_id=active_task, phase=task_phase, idle_seconds=idle)
            if idle < idle_threshold:
                return LivenessDecision(
                    "skip",
                    f"niaobe ack idle {idle:.0f}s < threshold {idle_threshold:.0f}s",
                    **base,
                )
            if terminal_pending:
                return LivenessDecision(
                    "niaobe_ack_terminal_pending",
                    "niaobe already processed this handoff generation; not a dropped ack",
                    **base,
                )
            return LivenessDecision(
                "reap_niaobe_ack",
                f"niaobe failed to ack TASK_HANDOFF for {idle:.0f}s >= threshold "
                f"{idle_threshold:.0f}s",
                **base,
            )
        return LivenessDecision("skip", f"owner is {owner or '<none>'}, not niaobe")
    if waiting_for not in WORKER_ROLES:
        return LivenessDecision("skip", f"waiting_for is {waiting_for or '<none>'}, not a worker")
    if task_status != "IN_PROGRESS":
        return LivenessDecision("skip", f"task_status is {task_status or '<none>'}, not IN_PROGRESS")
    expected_phase = EXPECTED_PHASE.get(waiting_for, "")
    if task_phase != expected_phase:
        return LivenessDecision(
            "skip",
            f"task_phase {task_phase or '<none>'} != expected {expected_phase} for {waiting_for}",
            role=waiting_for,
            task_id=active_task,
            phase=task_phase,
        )

    if last_activity_epoch is None:
        idle = float("inf")
    else:
        idle = now_epoch - last_activity_epoch

    base = dict(role=waiting_for, task_id=active_task, phase=task_phase, idle_seconds=idle)
    if idle < idle_threshold:
        return LivenessDecision(
            "skip",
            f"{waiting_for} idle {idle:.0f}s < threshold {idle_threshold:.0f}s",
            **base,
        )
    if terminal_pending:
        return LivenessDecision(
            "worker_terminal_pending",
            f"{waiting_for} produced a terminal result; awaiting niaobe, not a worker hang",
            **base,
        )
    return LivenessDecision(
        "reap",
        f"{waiting_for} stale {idle:.0f}s >= threshold {idle_threshold:.0f}s with no terminal result",
        **base,
    )


def _watchdog_envelope(project_id: str, decision: LivenessDecision) -> dict[str, str]:
    return {
        "project_id": project_id,
        "task_id": decision.task_id,
        "from": decision.role,
        "to": "niaobe",
        "phase": decision.phase,
        "signal": "BLOCKED",
    }


def _ledger_entry(
    project_id: str,
    decision: LivenessDecision,
    outcome: str,
    reason: str,
    *,
    run_token: str = WATCHDOG_RUN_ID,
) -> dict[str, Any]:
    return {
        "kind": "watchdog",
        "event_key": event_key(
            project_id,
            decision.task_id,
            decision.role,
            decision.phase,
            "BLOCKED",
            run_token,
        ),
        "project_id": project_id,
        "task_id": decision.task_id,
        "from": decision.role,
        "phase": decision.phase,
        "signal": "BLOCKED",
        "outcome": outcome,
        "reason": reason,
    }


def reap_project(
    project_path: Path,
    project_id: str,
    decision: LivenessDecision,
) -> ProjectResult:
    """Synthesize the terminal BLOCKED transition for a stale worker.

    Runs under ``transition_lock`` and re-validates ``classify_child`` so a real
    callback that landed since assessment wins (stand-down, no double block).
    """

    project_path = Path(project_path)
    envelope = _watchdog_envelope(project_id, decision)
    reason = (
        f"watchdog: {decision.role} exceeded idle budget "
        f"({int(decision.idle_seconds)}s) at {decision.phase} with no terminal result"
    )

    with transition_lock(project_path):
        fresh = read_project_state(project_path)
        current = classify_child(fresh, envelope)
        terminal_now = worker_terminal_pending(decision.role, project_id, decision.task_id)
        if current.superseded or terminal_now:
            stand_reason = (
                current.reason
                if current.superseded
                else "worker produced a terminal result before reap"
            )
            try:
                record_transition(
                    project_path,
                    _ledger_entry(project_id, decision, "superseded", stand_reason),
                )
            except OSError:
                pass
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="superseded",
                detail=f"stood down under lock: {stand_reason}",
            )

        run_dir = build_run_dir(project_id, decision.task_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "envelope.json", envelope)
        state: dict[str, Any] = {
            "role": "niaobe",
            "phase": decision.phase,
            "status": "watchdog_block",
            "project_id": project_id,
            "task_id": decision.task_id,
            "from": decision.role,
            "started_at": iso_now(),
        }
        try:
            mark_child_runtime_blocked(
                run_dir,
                state,
                envelope,
                code=WATCHDOG_BLOCK_CODE,
                reason=reason,
            )
        except WorkerRuntimeError as exc:
            if is_owner_mismatch(exc):
                try:
                    record_transition(
                        project_path,
                        _ledger_entry(project_id, decision, "superseded", str(exc)),
                    )
                except OSError:
                    pass
                return ProjectResult(
                    project_id,
                    str(project_path),
                    decision,
                    outcome="superseded",
                    detail=f"owner mismatch during reap: {exc}",
                )
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="error",
                detail=f"block failed: {exc}",
            )

        try:
            record_transition(
                project_path,
                _ledger_entry(project_id, decision, "reaped_blocked", reason),
            )
        except OSError:
            pass
        return ProjectResult(
            project_id,
            str(project_path),
            decision,
            outcome="reaped",
            detail=reason,
        )


def _block_niaobe_ack(run_dir: Path, envelope: dict[str, str], *, reason: str) -> str:
    """Drive the Niaobe-ack BLOCKED transition (sibling of mark_child_runtime_blocked).

    Mirrors the existing Niaobe block protocol so Smith's blocked handler processes
    it identically, but with ``--expect-owner smith`` and ``--actor smith`` (owner
    stays smith; Niaobe never owned this generation) and NO ``--set-owner``. Bumps
    ``blocked_count`` for oscillation visibility.
    """

    project_id = envelope["project_id"]
    task_id = envelope["task_id"]
    write_state_result = run_command(
        [
            "bash",
            str(live_bin_root() / "write_state.sh"),
            project_id,
            "BLOCKED",
            "smith",
            "--actor",
            "smith",
            "--expect-owner",
            "smith",
            "--active-task",
            task_id,
            "--task-phase",
            NIAOBE_ACK_PHASE,
            "--task-status",
            "BLOCKED",
            "--increment-blocked",
            "--blocked-reason",
            f"{NIAOBE_ACK_BLOCK_CODE}: {reason}",
            "--note",
            f"Task {task_id} blocked: Niaobe did not acknowledge TASK_HANDOFF (watchdog).",
        ],
        timeout=120,
    )
    require_ok(write_state_result, action="write_state niaobe-ack blocked")
    send_response = send_smith_result(
        project_id,
        task_id,
        phase="TASK_BLOCKED",
        instructions=(
            f"BLOCKED[{NIAOBE_ACK_BLOCK_CODE}]: {reason}. Do NOT re-handoff to Niaobe "
            "without rotating Niaobe's session first -- the existing session is wedged "
            "and will drop the re-handoff."
        ),
    )
    result_payload = {
        "status": "blocked",
        "blocked_at": iso_now(),
        "project_id": project_id,
        "task_id": task_id,
        "code": NIAOBE_ACK_BLOCK_CODE,
        "reason": reason,
        "response": send_response,
    }
    write_json(run_dir / "result.json", result_payload)
    write_json(
        run_dir / "state.json",
        {
            "role": "niaobe",
            "phase": NIAOBE_ACK_PHASE,
            "status": "watchdog_block",
            "project_id": project_id,
            "task_id": task_id,
            "blocked_at": result_payload["blocked_at"],
            "blocked_code": NIAOBE_ACK_BLOCK_CODE,
            "result_payload": result_payload,
        },
    )
    return send_response


def reap_niaobe_ack(
    project_path: Path,
    project_id: str,
    decision: LivenessDecision,
    *,
    idle_threshold: float,
    now_epoch: float,
) -> ProjectResult:
    """Escalate a dropped TASK_HANDOFF to BLOCKED for Smith.

    Runs under ``transition_lock`` and re-validates the niaobe-ack class, then
    RECOMPUTES idle in-lock (finding #1) so a Niaobe that began accepting between
    classification and the lock is not false-blocked, and re-checks the
    generation-bound terminal guard (finding #3) before synthesizing the block.
    """

    project_path = Path(project_path)
    envelope = {
        "project_id": project_id,
        "task_id": decision.task_id,
        "from": "niaobe",
        "to": "smith",
        "phase": NIAOBE_ACK_PHASE,
        "signal": "BLOCKED",
    }

    with transition_lock(project_path):
        fresh = read_project_state(project_path)
        if not _is_niaobe_ack_class(fresh) or fresh.get("active_task", "").strip().upper() != (
            decision.task_id.strip().upper()
        ):
            stand_reason = "no longer awaiting a niaobe ack for this task"
            try:
                record_transition(
                    project_path,
                    _ledger_entry(project_id, decision, "superseded", stand_reason),
                )
            except OSError:
                pass
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="superseded",
                detail=f"stood down under lock: {stand_reason}",
            )

        # Finding #1: recompute idle under the lock; a Niaobe that just started
        # accepting (fresh run/runtime mtime) must win and not be reaped.
        idle, state_mtime = _niaobe_idle(project_path, project_id, decision.task_id, now_epoch)
        if idle < idle_threshold:
            stand_reason = f"niaobe became active under lock (idle {idle:.0f}s)"
            try:
                record_transition(
                    project_path,
                    _ledger_entry(project_id, decision, "superseded", stand_reason),
                )
            except OSError:
                pass
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="superseded",
                detail=stand_reason,
            )

        # Finding #3: generation-bound terminal check.
        if niaobe_ack_terminal_pending(project_id, decision.task_id, state_mtime):
            stand_reason = "niaobe processed this handoff generation before reap"
            try:
                record_transition(
                    project_path,
                    _ledger_entry(project_id, decision, "superseded", stand_reason),
                )
            except OSError:
                pass
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="superseded",
                detail=stand_reason,
            )

        run_token = f"ack-{int(state_mtime or 0)}"
        reason = (
            f"watchdog: niaobe did not acknowledge TASK_HANDOFF within the idle budget "
            f"({int(idle)}s)"
        )
        run_dir = build_run_dir(project_id, decision.task_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "envelope.json", envelope)
        try:
            _block_niaobe_ack(run_dir, envelope, reason=reason)
        except WorkerRuntimeError as exc:
            if is_owner_mismatch(exc):
                try:
                    record_transition(
                        project_path,
                        _ledger_entry(
                            project_id, decision, "superseded", str(exc), run_token=run_token
                        ),
                    )
                except OSError:
                    pass
                return ProjectResult(
                    project_id,
                    str(project_path),
                    decision,
                    outcome="superseded",
                    detail=f"owner mismatch during niaobe-ack reap: {exc}",
                )
            return ProjectResult(
                project_id,
                str(project_path),
                decision,
                outcome="error",
                detail=f"niaobe-ack block failed: {exc}",
            )

        try:
            record_transition(
                project_path,
                _ledger_entry(
                    project_id,
                    decision,
                    "niaobe_ack_reaped_blocked",
                    reason,
                    run_token=run_token,
                ),
            )
        except OSError:
            pass
        return ProjectResult(
            project_id,
            str(project_path),
            decision,
            outcome="reaped",
            detail=reason,
        )


def process_project(
    project_path: Path,
    *,
    idle_threshold: float = DEFAULT_IDLE_SECONDS,
    now_epoch: float | None = None,
    dry_run: bool = False,
) -> ProjectResult:
    """Assess and (unless dry-run) reap one project."""

    project_path = Path(project_path)
    now = time.time() if now_epoch is None else now_epoch
    state = read_project_state(project_path)
    project_id = parse_project_id(project_path)

    if not state.get("owner", "").strip():
        decision = LivenessDecision("skip", "no authoritative PROJECT_STATE.md")
        return ProjectResult(project_id, str(project_path), decision, outcome="skipped", detail=decision.reason)
    if not project_id:
        decision = LivenessDecision("skip", "could not resolve project_id")
        return ProjectResult(project_id, str(project_path), decision, outcome="skipped", detail=decision.reason)

    role = state.get("waiting_for", "").strip().lower()
    task_id = state.get("active_task", "").strip().upper()
    owner = state.get("owner", "").strip().lower()

    last_activity = project_state_mtime(project_path)
    terminal_pending: bool = False
    if owner == "niaobe" and role in WORKER_ROLES and task_id:
        worker_activity = worker_last_activity_epoch(role, project_id, task_id)
        if worker_activity is not None:
            last_activity = worker_activity if last_activity is None else max(last_activity, worker_activity)
        terminal_pending = worker_terminal_pending(role, project_id, task_id)
    elif _is_niaobe_ack_class(state) and task_id:
        last_activity = max(
            [v for v in (last_activity, worker_last_activity_epoch("niaobe", project_id, task_id)) if v is not None],
            default=None,
        )
        terminal_pending = niaobe_ack_terminal_pending(
            project_id, task_id, project_state_mtime(project_path)
        )

    decision = classify_liveness(
        state,
        now_epoch=now,
        last_activity_epoch=last_activity,
        idle_threshold=idle_threshold,
        terminal_pending=bool(terminal_pending),
    )

    if decision.action == "skip":
        return ProjectResult(project_id, str(project_path), decision, outcome="skipped", detail=decision.reason)
    if decision.action in {"worker_terminal_pending", "niaobe_ack_terminal_pending"}:
        return ProjectResult(
            project_id, str(project_path), decision, outcome="skipped", detail=decision.reason
        )
    if dry_run:
        return ProjectResult(
            project_id, str(project_path), decision, outcome="would_reap", detail=decision.reason
        )
    if decision.action == "reap_niaobe_ack":
        return reap_niaobe_ack(
            project_path,
            project_id,
            decision,
            idle_threshold=idle_threshold,
            now_epoch=now,
        )
    return reap_project(project_path, project_id, decision)


def iter_project_dirs(projects_root: Path) -> list[Path]:
    root = Path(projects_root)
    if not root.is_dir():
        return []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    return [child for child in children if (child / "PROJECT_STATE.md").is_file()]


def run(
    *,
    project_dirs: list[Path],
    idle_threshold: float,
    dry_run: bool,
    now_epoch: float | None = None,
) -> list[ProjectResult]:
    results: list[ProjectResult] = []
    for project_dir in project_dirs:
        try:
            results.append(
                process_project(
                    project_dir,
                    idle_threshold=idle_threshold,
                    now_epoch=now_epoch,
                    dry_run=dry_run,
                )
            )
        except Exception as exc:  # noqa: BLE001 - never let one project break the sweep
            decision = LivenessDecision("skip", f"unexpected error: {exc}")
            results.append(
                ProjectResult(
                    parse_project_id(project_dir),
                    str(project_dir),
                    decision,
                    outcome="error",
                    detail=str(exc),
                )
            )
    return results


def render_text(results: list[ProjectResult]) -> str:
    lines: list[str] = []
    reaped = [r for r in results if r.outcome in {"reaped", "would_reap"}]
    lines.append(f"Liveness watchdog: {len(results)} project(s) scanned, {len(reaped)} stale.")
    for result in results:
        d = result.decision
        head = f"- [{result.outcome}] {result.project_id or '<unknown>'}"
        if d.role:
            head += f" waiting_for={d.role} task={d.task_id} phase={d.phase} idle={d.idle_seconds:.0f}s"
        lines.append(head)
        if result.detail:
            lines.append(f"    {result.detail}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic liveness watchdog: reap wedged worker phases (Slice A)."
    )
    parser.add_argument(
        "--project-dir",
        action="append",
        default=[],
        help="A single project directory containing PROJECT_STATE.md. Repeatable.",
    )
    parser.add_argument(
        "--projects-root",
        default=None,
        help="Scan every project under this active-projects root. "
        "Defaults to $CLAWSPACE_PROJECTS_ROOT or the live active dir.",
    )
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=DEFAULT_IDLE_SECONDS,
        help=f"Idle budget before a worker is considered stale (default {DEFAULT_IDLE_SECONDS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Assess and report only; do not block any project.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_dirs: list[Path] = [Path(p) for p in args.project_dir]
    if not project_dirs:
        root = Path(args.projects_root) if args.projects_root else default_projects_root()
        project_dirs = iter_project_dirs(root)

    results = run(
        project_dirs=project_dirs,
        idle_threshold=args.idle_seconds,
        dry_run=args.dry_run,
    )

    if args.format == "json":
        print(json.dumps([r.as_dict() for r in results], indent=2, sort_keys=True))
    else:
        print(render_text(results), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
